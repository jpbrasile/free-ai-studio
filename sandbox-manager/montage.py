"""Le montage d'une video prolongee : sa derniere image, et le recollage de deux clips.

Brique « Prolonger une vidéo » (24/09/2026, demande du proprietaire : « le
recollage en un clip est un composite du studio »). Le modele loue ne sait
faire que 81 images, 5 s ; 10 s se font en deux clips, le second partant de
la DERNIERE image du premier (image de depart, VACE). On la retire du second
au recollage : sinon elle se montre deux fois, un arret sur image d'un
seizieme de seconde a chaque jointure.

ffmpeg fait les deux gestes. Il est installe dans l'image du service
(Dockerfile) ; absent, la brique le dit au lieu de rendre un clip de 5 s
presente comme prolonge.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

DELAI_S = 120


class MontageImpossible(Exception):
    """Une phrase francaise, montree telle quelle par la chaine."""


def _ffmpeg() -> str:
    chemin = shutil.which("ffmpeg")
    if not chemin:
        raise MontageImpossible(
            "Le montage vidéo (ffmpeg) n'est pas installé dans le Studio : la vidéo "
            "ne peut pas être prolongée. Reconstruisez le service (demarrer.cmd).")
    return chemin


def _lancer(arguments: list[str], quoi: str) -> None:
    fini = subprocess.run([_ffmpeg(), "-loglevel", "error", "-y", *arguments],
                          capture_output=True, text=True, timeout=DELAI_S)
    if fini.returncode != 0:
        raise MontageImpossible("%s a échoué : %s" % (quoi, (fini.stderr or "").strip()[-300:]))


VOIX_TAUX = 32000   # celui du VAE audio de H3 : le nœud ne rééchantillonne rien


def voix_de_reference(son: bytes, max_s: float) -> tuple[bytes, float]:
    """Un exemple de voix mis au propre pour H3 : WAV mono, silence de tête retiré,
    `max_s` secondes au plus. Rend (wav, durée en secondes). Un son, une vidéo ou
    un enregistrement du navigateur passent de même."""
    with tempfile.TemporaryDirectory() as dossier:
        a, sortie = Path(dossier, "entree"), Path(dossier, "voix.wav")
        a.write_bytes(son)
        _lancer(["-i", str(a), "-vn", "-ac", "1", "-ar", str(VOIX_TAUX),
                 "-af", "silenceremove=start_periods=1:start_threshold=-45dB", "-t", "%.2f" % max_s,
                 "-c:a", "pcm_s16le", str(sortie)], "La mise au propre de la voix")
        wav = sortie.read_bytes() if sortie.is_file() else b""
    # 44 octets d'en-tête, 2 octets par échantillon mono.
    return wav, round(max(0, len(wav) - 44) / (2 * VOIX_TAUX), 2)


def derniere_image(video: bytes) -> bytes:
    """La derniere image d'une video, en PNG. Lue a la fin du flux, pas estimee."""
    with tempfile.TemporaryDirectory() as dossier:
        entree, sortie = Path(dossier, "a.mp4"), Path(dossier, "derniere.png")
        entree.write_bytes(video)
        _lancer(["-sseof", "-0.5", "-i", str(entree), "-update", "1", str(sortie)],
                "L'extraction de la dernière image")
        if not sortie.is_file() or not sortie.stat().st_size:
            raise MontageImpossible("La vidéo reçue n'a pas d'image lisible à sa fin.")
        return sortie.read_bytes()


def recadrer_image(image: bytes, largeur: int, hauteur: int) -> bytes:
    """L'image à la taille du clip, en PNG : agrandie jusqu'à couvrir, puis coupée
    au centre, sans déformer (comme la page le fait pour un clip seul). Sert à
    l'image de départ d'un plan de scénario (28/09/2026)."""
    with tempfile.TemporaryDirectory() as dossier:
        entree, sortie = Path(dossier, "image"), Path(dossier, "recadree.png")
        entree.write_bytes(image)
        _lancer(["-i", str(entree), "-vf",
                 "scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d"
                 % (largeur, hauteur, largeur, hauteur), "-frames:v", "1", str(sortie)],
                "Le recadrage de l'image de départ")
        if not sortie.is_file() or not sortie.stat().st_size:
            raise MontageImpossible("L'image de départ n'a pas pu être recadrée.")
        return sortie.read_bytes()


def recadrer_zone(image: bytes, zone: tuple, largeur_min: int = 512) -> bytes:
    """La zone (x0, y0, x1, y1, en fractions) de l'image, en PNG, agrandie à
    `largeur_min` de large au moins : le gros plan d'un visage pour une fiche."""
    x0, y0, x1, y1 = zone
    with tempfile.TemporaryDirectory() as dossier:
        entree, sortie = Path(dossier, "image"), Path(dossier, "zone.png")
        entree.write_bytes(image)
        _lancer(["-i", str(entree), "-vf",
                 "crop=iw*%.4f:ih*%.4f:iw*%.4f:ih*%.4f,scale='max(%d,iw)':-2:flags=lanczos"
                 % (x1 - x0, y1 - y0, x0, y0, largeur_min), "-frames:v", "1", str(sortie)],
                "Le recadrage sur le visage")
        if not sortie.is_file() or not sortie.stat().st_size:
            raise MontageImpossible("Le visage n'a pas pu être recadré.")
        return sortie.read_bytes()


def planche_visages(images: list, cote: int = 320) -> bytes:
    """Des images côte à côte, chacune dans un carré de `cote` (sans déformer) :
    les photos de la fiche, puis le visage de l'image générée."""
    if not images:
        raise MontageImpossible("Aucun visage à comparer.")
    with tempfile.TemporaryDirectory() as dossier:
        entrees = []
        for i, octets in enumerate(images):
            p = Path(dossier, "v%d" % i)
            p.write_bytes(octets)
            entrees += ["-i", str(p)]
        cases = "".join("[%d:v]scale=%d:%d:force_original_aspect_ratio=decrease,pad=%d:%d:(ow-iw)/2:(oh-ih)/2:"
                        "color=white,setsar=1[c%d];" % (i, cote, cote, cote, cote, i) for i in range(len(images)))
        pile = ("".join("[c%d]" % i for i in range(len(images))) + "hstack=inputs=%d[p]" % len(images)
                if len(images) > 1 else "[c0]null[p]")
        sortie = Path(dossier, "planche.png")
        _lancer([*entrees, "-filter_complex", cases + pile, "-map", "[p]", "-frames:v", "1", str(sortie)],
                "La planche des visages")
        return sortie.read_bytes()


def recoller(premiere: bytes, suite: bytes) -> bytes:
    """Les deux clips en un seul ; la premiere image de la suite est retiree (elle
    EST la derniere de la premiere)."""
    with tempfile.TemporaryDirectory() as dossier:
        a, b, sortie = Path(dossier, "a.mp4"), Path(dossier, "b.mp4"), Path(dossier, "ab.mp4")
        a.write_bytes(premiere)
        b.write_bytes(suite)
        num, den = _cadence(a)
        # Les images sont NUMEROTEES a la cadence du clip (settb + setpts=N), pas
        # recalees sur leurs horodatages : mesure du 24/09, sur deux clips loues
        # de 17 images, `trim` + `concat` seuls rendaient 33 images avec ffmpeg
        # 6.1 et 32 avec le 7.1.5 du conteneur -- une image perdue en silence.
        _lancer(["-i", str(a), "-i", str(b), "-filter_complex",
                 "[1:v]trim=start_frame=1[b];"
                 "[0:v][b]concat=n=2:v=1:a=0,settb=%d/%d,setpts=N[v]" % (den, num),
                 "-map", "[v]", "-r", "%d/%d" % (num, den),
                 "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
                 "-movflags", "+faststart", str(sortie)],
                "Le recollage des deux clips")
        attendu = images(a) + images(b) - 1
        obtenu = images(sortie)
        if obtenu != attendu:
            raise MontageImpossible(
                "Le recollage a rendu %d images au lieu de %d : le clip n'est pas "
                "rendu, plutôt que de le montrer amputé." % (obtenu, attendu))
        return sortie.read_bytes()


# Le niveau du son d'un plan à l'autre (30/09, film campus) : H3 choisit le niveau
# de chaque plan. Une suite par raccord le garde (le son des 22 images reprises
# l'ancre) ; une coupe repart de rien : le plan 5 est arrivé 5 à 6 dB sous les
# quatre premiers (−16,7 LUFS contre −10,4 à −12,3). Décision du propriétaire :
# harmoniser, « de façon systématique ». Chaque plan recollé prend la sonie (EBU
# R128) du film déjà monté ; un limiteur garde ses crêtes sous −1 dBFS.
ECART_SONIE_MAX_DB = 12.0   # au-delà, c'est un plan presque muet : on ne le pousse pas plus
ECART_SONIE_MIN_DB = 0.5    # en deçà, inaudible : rien n'est touché
SONIE_SILENCE = -60.0       # un son plus bas que cela n'a pas de niveau à suivre
LIMITE_CRETE = 0.891        # −1 dBFS


def sonie(chemin: Path, debut_s: float = 0.0):
    """La sonie intégrée (LUFS) du son de `chemin` à partir de `debut_s`, ou None
    (pas de son, silence, ou mesure illisible)."""
    fini = subprocess.run([_ffmpeg(), "-hide_banner", "-nostats", "-ss", "%.6f" % debut_s, "-i", str(chemin),
                           "-vn", "-af", "ebur128", "-f", "null", "-"],
                          capture_output=True, text=True, timeout=DELAI_S)
    mesures = re.findall(r"I:\s+(-?[\d.]+) LUFS", fini.stderr or "")
    if fini.returncode != 0 or not mesures or float(mesures[-1]) <= SONIE_SILENCE:
        return None
    return float(mesures[-1])


def gain_de_suite(premiere: Path, suite: Path, debut_s: float = 0.0) -> float:
    """Le gain (dB) qui met la suite, à partir de `debut_s`, au niveau du film `premiere`."""
    avant, apres = sonie(premiere), sonie(suite, debut_s)
    if avant is None or apres is None:
        return 0.0
    gain = max(-ECART_SONIE_MAX_DB, min(ECART_SONIE_MAX_DB, avant - apres))
    return round(gain, 2) if abs(gain) >= ECART_SONIE_MIN_DB else 0.0


def recoller_son(premiere: bytes, suite: bytes, retirer: int = 1) -> bytes:
    """Comme `recoller`, mais le son suit : la vidéo H3 parle (27/09/2026).

    `retirer` images sont ôtées du debut de la suite, et le son de la meme
    duree avec elles : 1 quand la suite part de la derniere image du premier
    clip, 0 quand elle arrive deja coupee (prolongation par troncon). Le son de
    la suite prend le niveau du film (`gain_de_suite`, 30/09)."""
    with tempfile.TemporaryDirectory() as dossier:
        a, b, sortie = Path(dossier, "a.mp4"), Path(dossier, "b.mp4"), Path(dossier, "ab.mp4")
        a.write_bytes(premiere)
        b.write_bytes(suite)
        num, den = _cadence(a)
        debut_s = retirer * den / num
        gain = gain_de_suite(a, b, debut_s)
        niveau = (",volume=%.2fdB,alimiter=limit=%.3f:level=0:latency=1" % (gain, LIMITE_CRETE)) if gain else ""
        _lancer(["-i", str(a), "-i", str(b), "-filter_complex",
                 "[1:v]trim=start_frame=%d[bv];"
                 "[1:a]atrim=start=%.6f,asetpts=PTS-STARTPTS%s[ba];"
                 "[0:v][0:a][bv][ba]concat=n=2:v=1:a=1[v0][a];"
                 "[v0]settb=%d/%d,setpts=N[v]" % (retirer, debut_s, niveau, den, num),
                 "-map", "[v]", "-map", "[a]", "-r", "%d/%d" % (num, den),
                 "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
                 "-c:a", "aac", "-movflags", "+faststart", str(sortie)],
                "Le recollage des deux clips")
        attendu = images(a) + images(b) - retirer
        obtenu = images(sortie)
        if obtenu != attendu:
            raise MontageImpossible(
                "Le recollage a rendu %d images au lieu de %d : le clip n'est pas "
                "rendu, plutôt que de le montrer amputé." % (obtenu, attendu))
        return sortie.read_bytes()


def poser_musique(film: bytes, musique: bytes, debut_s: float, volume: float = 0.3,
                  depart_chanson_s: float = 0.0, fondu_s: float = 0.3,
                  sous_paroles: bool = False) -> bytes:
    """Une musique SOUS le son du film, de `debut_s` à la fin (28/09/2026).

    Demande du propriétaire : une musique qui commence au deuxième plan et
    continue sur le troisième. Trois clips H3 tournés à part ont chacun leur
    musique, qui change à la coupe ; un seul morceau posé après coup est le
    même signal d'un bout à l'autre. Les images ne sont pas réencodées, et le
    son d'origine (paroles, ambiance) est gardé tel quel, la musique en dessous,
    avec une entrée et une sortie en fondu.

    Essai du 28/09 : le chant d'une chanson YuE2 commençait à 8 s ; il a
    fallu la prendre à `depart_chanson_s` (un passage choisi DANS la chanson),
    l'entrée en fondu plus longue (`fondu_s`), et la baisser quand on parle
    (`sous_paroles` : le son du film commande le volume de la musique,
    compresseur à déclenchement externe)."""
    if depart_chanson_s < 0 or not 0 <= fondu_s <= 5:
        raise MontageImpossible("Départ dans la chanson ou fondu hors bornes.")
    with tempfile.TemporaryDirectory() as dossier:
        a, m, sortie = Path(dossier, "film.mp4"), Path(dossier, "musique"), Path(dossier, "avec.mp4")
        a.write_bytes(film)
        m.write_bytes(musique)
        num, den = _cadence(a)
        duree_s = images(a) * den / num
        if not 0 <= debut_s < duree_s - 0.5:
            raise MontageImpossible("La musique commencerait après la fin du film.")
        longueur_s = duree_s - debut_s
        # Decrescendo final (demande du 28/09) : un fondu d'une seconde sonnait
        # comme une coupure ; 2,5 s, ou le tiers de la musique si elle est courte.
        fin_s = min(2.5, longueur_s / 3)
        entree_s = min(fondu_s, longueur_s / 3)
        musique_f = ("[1:a]atrim=start=%.3f:end=%.3f,asetpts=PTS-STARTPTS,aresample=48000,"
                     "afade=t=in:d=%.3f,afade=t=out:st=%.3f:d=%.3f,volume=%.2f,adelay=%d:all=1[m0];"
                     % (depart_chanson_s, depart_chanson_s + longueur_s, entree_s,
                        longueur_s - fin_s, fin_s, volume, round(debut_s * 1000)))
        if sous_paroles:
            # La voix du film (au-dessus de -26 dB environ) écrase la musique d'un
            # facteur 8 ; l'ambiance, plus basse, la laisse presque intacte.
            filtre = (musique_f + "[0:a]aresample=48000,asplit=2[f][cle];"
                      "[m0][cle]sidechaincompress=threshold=0.05:ratio=8:attack=15:release=450[m];"
                      "[f][m]amix=inputs=2:duration=first:normalize=0[a]")
        else:
            filtre = (musique_f.replace("[m0];", "[m];") + "[0:a]aresample=48000[f];"
                      "[f][m]amix=inputs=2:duration=first:normalize=0[a]")
        _lancer(["-i", str(a), "-i", str(m), "-filter_complex", filtre,
                 "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac",
                 "-movflags", "+faststart", str(sortie)],
                "La pose de la musique")
        if images(sortie) != images(a):
            raise MontageImpossible("La pose de la musique a changé le nombre d'images : "
                                    "le film n'est pas rendu.")
        return sortie.read_bytes()


PASSAGES_MAX = 8


def lire_silences(journal: str, duree_s: float, min_s: float = 0.3, marge_s: float = 0.25) -> list:
    """Les passages NON silencieux d'après le journal de `silencedetect`, élargis
    de `marge_s`, ceux de moins de `min_s` écartés (bruits de pas). Rend
    [(debut, fin)], au plus PASSAGES_MAX, dans l'ordre."""
    silences, debut = [], None
    for m in re.finditer(r"silence_(start|end): (-?[\d.]+)", journal):
        t = max(0.0, float(m.group(2)))
        if m.group(1) == "start":
            debut = t
        elif debut is not None:
            silences.append((debut, t))
            debut = None
    if debut is not None:
        silences.append((debut, duree_s))
    passages, t = [], 0.0
    for a, b in silences + [(duree_s, duree_s)]:
        if a - t >= min_s:
            passages.append((round(max(0.0, t - marge_s), 2), round(min(duree_s, a + marge_s), 2)))
        t = b
    return passages[:PASSAGES_MAX]


def passages_parles(video: bytes) -> list:
    """Où le clip fait du son au-dessus de -35 dB (voix, le plus souvent). Pour
    écouter passage par passage : sur le clip entier, Whisper n'a gardé qu'une
    langue et a perdu une réplique d'un clip bilingue (essai du 28/09). Un son
    seul (une chanson) marche aussi : la durée est celle du fichier, pas des images."""
    with tempfile.TemporaryDirectory() as dossier:
        a = Path(dossier, "entree")
        a.write_bytes(video)
        fini = subprocess.run([_ffmpeg(), "-hide_banner", "-nostats", "-i", str(a), "-vn",
                               "-af", "silencedetect=n=-35dB:d=0.3", "-f", "null", "-"],
                              capture_output=True, text=True, timeout=DELAI_S)
        duree = re.search(r"Duration: (\d+):(\d+):([\d.]+)", fini.stderr or "")
        if fini.returncode != 0 or not duree:
            raise MontageImpossible("La recherche des passages parlés a échoué.")
        h, m, s = duree.groups()
        return lire_silences(fini.stderr, int(h) * 3600 + int(m) * 60 + float(s))


def son_du_passage(video: bytes, debut_s: float, fin_s: float) -> bytes:
    """Le son de [debut_s, fin_s), en MP3, pour l'envoyer à l'écoute."""
    with tempfile.TemporaryDirectory() as dossier:
        a, sortie = Path(dossier, "entree"), Path(dossier, "passage.mp3")
        a.write_bytes(video)
        _lancer(["-ss", "%.3f" % debut_s, "-to", "%.3f" % fin_s, "-i", str(a), "-vn",
                 "-ac", "1", "-b:a", "96k", str(sortie)], "L'extraction d'un passage parlé")
        return sortie.read_bytes()


PLANCHE_IMAGES = 12   # 4 x 3, une image toutes les 0,5 s : un plan de 5 s y tient


def planche(video: bytes, debut_s: float, duree_s: float) -> tuple[bytes, int]:
    """Une planche PNG du passage [debut_s, debut_s + duree_s) : une image toutes
    les 0,5 s, numérotées de gauche à droite puis de haut en bas (28/09/2026,
    pour faire juger un plan par un modèle qui voit). Rend (png, nombre d'images)."""
    nombre = max(1, min(PLANCHE_IMAGES, int(-(-duree_s * 2 // 1))))
    with tempfile.TemporaryDirectory() as dossier:
        a, sortie = Path(dossier, "a.mp4"), Path(dossier, "planche.png")
        a.write_bytes(video)
        _lancer(["-ss", "%.3f" % debut_s, "-t", "%.3f" % duree_s, "-i", str(a),
                 "-vf", "fps=2,scale=416:-1,tile=4x3", "-frames:v", "1", str(sortie)],
                "La planche du plan")
        if not sortie.is_file() or not sortie.stat().st_size:
            raise MontageImpossible("La planche du plan n'a pas pu être faite.")
        return sortie.read_bytes(), nombre


def planche_serree(video: bytes, debut_s: float, duree_s: float, pas_s: float) -> tuple[bytes, int]:
    """Comme `planche`, une image toutes les `pas_s` secondes (0,125 : le début d'un
    plan, 29/09/2026), en images plus grandes (4 x 3, 480 px de large chacune)."""
    nombre = max(1, min(PLANCHE_IMAGES, int(-(-duree_s / pas_s // 1))))
    with tempfile.TemporaryDirectory() as dossier:
        a, sortie = Path(dossier, "a.mp4"), Path(dossier, "serree.png")
        a.write_bytes(video)
        _lancer(["-ss", "%.3f" % debut_s, "-t", "%.3f" % duree_s, "-i", str(a),
                 "-vf", "fps=%g,scale=480:-1,tile=4x3" % (1 / pas_s), "-frames:v", "1", str(sortie)],
                "La planche serrée du début du plan")
        if not sortie.is_file() or not sortie.stat().st_size:
            raise MontageImpossible("La planche serrée du plan n'a pas pu être faite.")
        return sortie.read_bytes(), nombre


def extraire(video: bytes, premiere: int, fin: int) -> bytes:
    """Les images [premiere, fin) d'un film, son compris : un plan déjà tourné,
    repris tel quel quand un scénario est rejoué (28/09/2026). Un seul
    réencodage (crf 18), comme au recollage."""
    if not 0 <= premiere < fin:
        raise MontageImpossible("Le passage à reprendre est vide.")
    with tempfile.TemporaryDirectory() as dossier:
        a, sortie = Path(dossier, "a.mp4"), Path(dossier, "extrait.mp4")
        a.write_bytes(video)
        num, den = _cadence(a)
        _lancer(["-i", str(a), "-filter_complex",
                 "[0:v]trim=start_frame=%d:end_frame=%d,setpts=PTS-STARTPTS[v0];"
                 "[v0]settb=%d/%d,setpts=N[v];"
                 "[0:a]atrim=start=%.6f:end=%.6f,asetpts=PTS-STARTPTS[a]"
                 % (premiere, fin, den, num, premiere * den / num, fin * den / num),
                 "-map", "[v]", "-map", "[a]", "-r", "%d/%d" % (num, den),
                 "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
                 "-c:a", "aac", "-movflags", "+faststart", str(sortie)],
                "La reprise du plan")
        if images(sortie) != fin - premiere:
            raise MontageImpossible("La reprise du plan a rendu %d images au lieu de %d."
                                    % (images(sortie), fin - premiere))
        return sortie.read_bytes()


def fin(video: bytes, nombre: int) -> bytes:
    """Les `nombre` dernières images d'un film, son compris : le raccord que le plan
    suivant épingle à son image 0 (30/09/2026, MiniMaxH3AddGuide)."""
    with tempfile.TemporaryDirectory() as dossier:
        a = Path(dossier, "a.mp4")
        a.write_bytes(video)
        total = images(a)
    if total < nombre:
        raise MontageImpossible("Le plan précédent a %d images, moins que les %d du raccord." % (total, nombre))
    return extraire(video, total - nombre, total)


def _sonde(chemin: Path, champ: str, compter: bool = False) -> str:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise MontageImpossible("ffprobe (livré avec ffmpeg) manque dans le Studio : "
                                "le recollage ne peut pas être vérifié.")
    fini = subprocess.run([ffprobe, "-v", "error", *(["-count_frames"] if compter else []),
                           "-select_streams", "v:0", "-show_entries", "stream=" + champ,
                           "-of", "default=nw=1:nk=1", str(chemin)],
                          capture_output=True, text=True, timeout=DELAI_S)
    valeur = (fini.stdout or "").strip().splitlines()
    if fini.returncode != 0 or not valeur:
        raise MontageImpossible("La vidéo n'a pas pu être lue (%s)." % champ)
    return valeur[0]


def _cadence(chemin: Path) -> tuple[int, int]:
    num, _, den = _sonde(chemin, "r_frame_rate").partition("/")
    try:
        num, den = int(num), int(den or 1)
    except ValueError:
        num = den = 0
    if num <= 0 or den <= 0:
        raise MontageImpossible("La cadence de la vidéo est illisible.")
    return num, den


def images(chemin: Path) -> int:
    """Le nombre d'images, COMPTEES en decodant (pas lu dans l'en-tete)."""
    try:
        return int(_sonde(chemin, "nb_read_frames", compter=True))
    except ValueError as exc:
        raise MontageImpossible("Le nombre d'images de la vidéo est illisible.") from exc


# --- Les coupes et les fondus à l'intérieur d'une vidéo (30/09/2026) ---------------
# Film campus : le plan 6 finit par un fondu de H3 vers un gros plan de Leila. Le score
# de scène de ffmpeg (image à image) y vaut 0,006 contre 0,606 pour une coupe franche :
# un fondu ne se voit que sur la distance. On compare donc les couleurs de l'image i et
# de l'image i + 12 (une demi-seconde). Mesuré sur ce film : 0,76 dans le fondu, 0,61 à
# la coupe franche, au plus 0,38 ailleurs (Tyler entrant en gros plan de dos), 0,19 au
# plus hors du plan 1.
TRANSITION_PAS = 12
TRANSITION_SEUIL = 0.5
_VIGNETTE = (32, 18)


def _histogramme(pixels: bytes) -> list:
    """8 cases par couleur, en part des pixels."""
    h = [0] * 24
    for i in range(0, len(pixels), 3):
        h[pixels[i] >> 5] += 1
        h[8 + (pixels[i + 1] >> 5)] += 1
        h[16 + (pixels[i + 2] >> 5)] += 1
    n = len(pixels) // 3
    return [x / n for x in h]


def ecarts_de_couleur(video: bytes, pas: int = TRANSITION_PAS) -> list:
    """Pour chaque image i, l'écart (0 à 1) entre ses couleurs et celles de l'image i + pas."""
    largeur, hauteur = _VIGNETTE
    with tempfile.TemporaryDirectory() as dossier:
        a = Path(dossier, "a.mp4")
        a.write_bytes(video)
        fini = subprocess.run([_ffmpeg(), "-loglevel", "error", "-i", str(a), "-vf",
                               "scale=%d:%d:flags=area" % (largeur, hauteur), "-an",
                               "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                              capture_output=True, timeout=DELAI_S)
    if fini.returncode != 0:
        raise MontageImpossible("Les images de la vidéo n'ont pas pu être lues pour trouver ses coupes.")
    taille = largeur * hauteur * 3
    hs = [_histogramme(fini.stdout[k:k + taille]) for k in range(0, len(fini.stdout) - taille + 1, taille)]
    return [sum(abs(x - y) for x, y in zip(hs[i], hs[i + pas])) / 2 for i in range(len(hs) - pas)]


def transitions(video: bytes, pas: int = TRANSITION_PAS, seuil: float = TRANSITION_SEUIL) -> list:
    """Les images où la vidéo change de scène (coupe ou fondu), au milieu du changement.
    Un changement couvre les paires (i, i + pas) au-dessus du seuil, de s à e : il se
    trouve entre s et e + pas."""
    ecarts = ecarts_de_couleur(video, pas)
    sortie, debut = [], None
    for i, e in enumerate(ecarts + [0.0]):
        if e >= seuil and debut is None:
            debut = i
        elif e < seuil and debut is not None:
            sortie.append(round((debut + i - 1 + pas) / 2))
            debut = None
    return sortie


def vignettes(video: bytes, numeros: list, largeur: int = 320) -> list:
    """Les images demandées (numéros d'image), en JPEG, dans l'ordre : de quoi voir
    qui est dans chaque passage avant de choisir."""
    if not numeros:
        return []
    with tempfile.TemporaryDirectory() as dossier:
        entree = Path(dossier, "a.mp4")
        entree.write_bytes(video)
        choix = "+".join("eq(n\\,%d)" % int(n) for n in sorted(set(numeros)))
        _lancer(["-i", str(entree), "-vf", "select='%s',scale=%d:-2" % (choix, largeur), "-vsync", "0",
                 "-q:v", "5", str(Path(dossier, "v%03d.jpg"))], "L'extraction des vignettes")
        rangees = sorted(set(numeros))
        fichiers = sorted(Path(dossier).glob("v*.jpg"))
        if len(fichiers) != len(rangees):
            raise MontageImpossible("Les vignettes du film n'ont pas pu être extraites.")
        par_numero = dict(zip(rangees, (f.read_bytes() for f in fichiers)))
    return [par_numero[int(n)] for n in numeros]


def coller_sans_reencoder(videos: list) -> bytes:
    """Des vidéos faites par la même machine, de mêmes réglages, mises bout à bout
    sans réencodage : un film 4K réencodé ici prendrait plusieurs minutes de
    processeur (finalisation, 30/09/2026). Nombre d'images vérifié."""
    if len(videos) == 1:
        return videos[0]
    with tempfile.TemporaryDirectory() as dossier:
        chemins = []
        for k, v in enumerate(videos):
            c = Path(dossier, "m%02d.mp4" % k)
            c.write_bytes(v)
            chemins.append(c)
        liste, sortie = Path(dossier, "liste.txt"), Path(dossier, "film.mp4")
        liste.write_text("".join("file '%s'\n" % c.name for c in chemins))
        _lancer(["-f", "concat", "-safe", "0", "-i", str(liste), "-c", "copy", "-movflags", "+faststart",
                 str(sortie)], "La mise bout à bout")
        attendu = sum(images(c) for c in chemins)
        if images(sortie) != attendu:
            raise MontageImpossible("La mise bout à bout a rendu %d images au lieu de %d."
                                    % (images(sortie), attendu))
        return sortie.read_bytes()
