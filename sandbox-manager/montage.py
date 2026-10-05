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

import array
import math
import re
import shutil
import subprocess
import tempfile
import wave
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


# Le plancher (05/10, jalon 0, PLAN 21.5) : H3 de base + LoRA Realism rend −26,5 LUFS là où la Turbo
# LoRA rend −10,5 ; la suite suivant le film, un film tout entier en H3 de base restait 16 dB plus bas.
# Sous le plancher, le film monté est remonté vers la cible (EBU R128, gain plafonné, limiteur), et la
# suite suit ce niveau-là. Au-dessus, rien ne change (les films Turbo, de −10 à −12, gardent le leur).
PLANCHER_SONIE = -20.0
CIBLE_SONIE = -14.0


def gain_du_film(premiere: Path) -> float:
    """Le gain (dB) qui remonte le film `premiere` vers CIBLE_SONIE s'il est sous PLANCHER_SONIE, sinon 0."""
    avant = sonie(premiere)
    if avant is None or avant >= PLANCHER_SONIE:
        return 0.0
    return round(min(ECART_SONIE_MAX_DB, CIBLE_SONIE - avant), 2)


def gain_de_suite(premiere: Path, suite: Path, debut_s: float = 0.0, gain_film: float = 0.0) -> float:
    """Le gain (dB) qui met la suite, à partir de `debut_s`, au niveau du film `premiere`
    (remonté de `gain_film` dB)."""
    avant, apres = sonie(premiere), sonie(suite, debut_s)
    if avant is None or apres is None:
        return 0.0
    gain = max(-ECART_SONIE_MAX_DB, min(ECART_SONIE_MAX_DB, avant + gain_film - apres))
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
        gain_film = gain_du_film(a)
        gain = gain_de_suite(a, b, debut_s, gain_film)
        limiteur = ",alimiter=limit=%.3f:level=0:latency=1" % LIMITE_CRETE
        niveau = (",volume=%.2fdB" % gain + limiteur) if gain else ""
        niveau_film = ("volume=%.2fdB" % gain_film + limiteur) if gain_film else "anull"
        _lancer(["-i", str(a), "-i", str(b), "-filter_complex",
                 "[0:a]%s[aa];"
                 "[1:v]trim=start_frame=%d[bv];"
                 "[1:a]atrim=start=%.6f,asetpts=PTS-STARTPTS%s[ba];"
                 "[0:v][aa][bv][ba]concat=n=2:v=1:a=1[v0][a];"
                 "[v0]settb=%d/%d,setpts=N[v]" % (niveau_film, retirer, debut_s, niveau, den, num),
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


def couper_son(video: bytes) -> bytes:
    """Le clip avec un son muet de même durée ; l'image n'est pas recompressée. Propriétaire, 04/10
    (« Le robot perdu ») : couper le son des clips où le juge a entendu des paroles non écrites."""
    with tempfile.TemporaryDirectory() as dossier:
        a, sortie = Path(dossier, "a.mp4"), Path(dossier, "muet.mp4")
        a.write_bytes(video)
        _lancer(["-i", str(a), "-map", "0:v", "-map", "0:a", "-af", "volume=0", "-c:v", "copy",
                 "-c:a", "aac", "-movflags", "+faststart", str(sortie)], "Le son coupé du clip")
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


# Ambiance égale d'un plan à l'autre (02/10/2026, film 4 ; propriétaire : « le niveau sonore de
# la fontaine est inégal », « à 20 s avant la fin le niveau sonore augmente », puis « tu mets
# ces réglages en automatique dans le studio »). Chaque plan H3 fabrique son propre son :
# mesuré sur le film 4, bande 4-10 kHz (l'eau ; la voix y pèse peu), de -73 dB (plan 2, fin
# des plans 3 et 6 : silence) à -26 dB (plan 4). Deux gestes, réglés à la main puis repris ici :
#   0. la référence : l'ambiance du plan qui l'a le plus fort, AMB_RETRAIT_DB en retrait (le réglage
#      fait à la main : plan 4, -29,9 dB → -33,9). Pas la médiane des plans : le plan 1 (pigeons,
#      peu d'eau, -49 dB) la tirait si bas que le plan 4, baissé de 10 dB, devenait un creux ;
#   1. un plan dont l'ambiance dépasse la référence de plus de AMB_TROP_FORT_DB est baissé à
#      la référence (plan 4 : -4 dB), avec des fondus ;
#   2. là où l'ambiance manque, une nappe la complète jusqu'à la référence ; la nappe est le
#      VRAI son du film (le plus long passage sans paroles d'un plan au niveau de référence),
#      répété en fondu, et baissée sous la parole (AMB_SOUS_VOIX ; sans cela Whisper lisait
#      « e-suit » pour « instant »).
# Rien n'est jamais monté : un plan trop bas est complété, pas amplifié (sa voix resterait).
#   3. un grondement sous AMB_COUPE_BAS_HZ est retiré de tout le film (propriétaire, 02/10 : « le
#      bruit de fond augmente brutalement » ; mesuré : plan 5 à -16,8 dB sous 150 Hz, les autres
#      de -27 à -44 ; hors de la bande d'eau, rien d'autre ne le voyait). Les voix d'enfants
#      sont au-dessus ;
#   4. chaque plan garde un réglage à la main (`ajustements_db`, ± AMB_AJUSTEMENT_MAX_DB) : son
#      fond visé est la référence + son ajustement (« un bouton d'ajustement manuel pour chaque
#      clip si besoin »).
AMB_COUPE_BAS_HZ = 120
AMB_AJUSTEMENT_MAX_DB = 12.0
AMB_BANDE = "highpass=f=4000,lowpass=f=10000"
AMB_TAUX, AMB_PAS = 24000, 2400            # mesures : 100 ms
AMB_MIX_TAUX = 48000
# La parole : la bande voix nettement au-dessus de ce que l'eau y met déjà (~4 dB de plus que la
# bande d'eau, mesuré plan 4 du film 4), ou du plancher du film. « 12 dB au-dessus de la médiane »
# ne couvrait que 4 % des mots situés par Whisper sur le film 4 entier (dialogue partout : la
# médiane EST la parole) ; la nappe masquait alors « notebook » et « instant ». Celle-ci : 92 %.
AMB_EAU_DANS_VOIX_DB = 4.0
AMB_VOIX_DB = 9.0
AMB_VOIX_MARGE = 3                         # ± 0,3 s autour de la parole
# ~ -16 dB sous la parole. 0,35 (-9 dB) masquait encore « notebook » (Whisper : « le nôtre ») au
# plan 6b du film 4 ; à 0,15, toutes les répliques du film reviennent comme sur le son brut.
AMB_SOUS_VOIX = 0.15
# 12 dB sous le plan le plus fort : choix du propriétaire à l'écoute (02/10, film 4 : « le niveau du
# background est trop fort » à 4 dB ; trois versions comparées, « moins 8 dB, mets-le par défaut »).
AMB_RETRAIT_DB = 12.0
AMB_TROP_FORT_DB, AMB_BAISSE_MAX_DB = 1.0, 10.0
AMB_SANS_DB = -55.0                        # un plan plus bas n'a pas d'ambiance : il ne compte pas
AMB_SOURCE_MIN_S, AMB_SOURCE_MAX_S = 2.0, 8.0
AMB_FONDU_S = 0.5
AMB_NAPPE_MAX = 1.5


def _db(x: float) -> float:
    return 20 * math.log10(x) if x > 1e-9 else -180.0


def _mediane(valeurs: list) -> float:
    v = sorted(valeurs)
    return v[len(v) // 2] if v else -180.0


def ajustements_valides(ajustements_db, plans: int) -> list:
    """Un réglage à la main par plan, en dB, borné ; ValueError si ce n'est pas des nombres."""
    ajustements = list(ajustements_db or [])
    if len(ajustements) > plans:
        raise ValueError("Un réglage du fond par plan, %d au plus." % plans)
    try:
        ajustements = [float(x or 0) for x in ajustements]
    except (TypeError, ValueError) as exc:
        raise ValueError("Le réglage du fond se donne en dB, un nombre par plan.") from exc
    if any(not math.isfinite(x) or abs(x) > AMB_AJUSTEMENT_MAX_DB for x in ajustements):
        raise ValueError("Le réglage du fond va de -%g à +%g dB." % (AMB_AJUSTEMENT_MAX_DB, AMB_AJUSTEMENT_MAX_DB))
    return [round(x, 1) for x in ajustements] + [0.0] * (plans - len(ajustements))


def regler_ambiance(amb_db: list, voix_db: list, bornes: list, ajustements_db=None, nappe_db=None) -> dict:
    """La décision, sans rien lire ni écrire (100 ms par mesure).

    `amb_db`, `voix_db` : niveau de la bande d'ambiance et de la bande voix par pas ;
    `bornes` : la fin de chaque plan, en pas ; `ajustements_db` : le réglage à la main de
    chaque plan (son fond visé = référence + réglage). `nappe_db` : le niveau (bande
    d'ambiance) de la piste son du lieu, gardée sur la fiche du décor (03/10) ; elle sert
    alors de nappe à la place d'un passage du film. Rend {parole, plans: [{niveau_db,
    gain_db}], reference_db, source: (k0, k1), « fiche » ou None, nappe: [gain par pas]}."""
    n = min(len(amb_db), len(voix_db))
    plancher = sorted(voix_db[:n])[n // 10] if n else -180.0
    brut = [voix_db[k] > max(amb_db[k] + AMB_EAU_DANS_VOIX_DB, plancher) + AMB_VOIX_DB for k in range(n)]
    parole = [any(brut[max(0, k - AMB_VOIX_MARGE):k + AMB_VOIX_MARGE + 1]) for k in range(n)]
    debuts = [0] + [min(b, n) for b in bornes[:-1]]
    fins = [min(b, n) for b in bornes]
    plans = []
    ajustements = ajustements_valides(ajustements_db, len(bornes))
    for a, b, aj in zip(debuts, fins, ajustements):
        calmes = [amb_db[k] for k in range(a, b) if not parole[k]]
        plans.append({"niveau_db": round(_mediane(calmes), 1) if len(calmes) >= 10 else None,
                      "ajustement_db": aj})
    vivants = [p["niveau_db"] for p in plans if p["niveau_db"] is not None and p["niveau_db"] > AMB_SANS_DB]
    if not vivants:
        return {"parole": parole, "plans": [dict(p, gain_db=0.0, vise_db=None) for p in plans], "reference_db": None,
                "source": None, "nappe": [0.0] * n}
    ref = max(vivants) - AMB_RETRAIT_DB
    for p in plans:
        lv, p["vise_db"] = p["niveau_db"], round(ref + p["ajustement_db"], 1)
        trop = lv is not None and lv > p["vise_db"] + AMB_TROP_FORT_DB
        p["gain_db"] = round(max(-AMB_BAISSE_MAX_DB, p["vise_db"] - lv), 1) if trop else 0.0
    gain_pas, vise_pas = [0.0] * n, [ref] * n
    for p, a, b in zip(plans, debuts, fins):
        for k in range(a, b):
            gain_pas[k], vise_pas[k] = p["gain_db"], p["vise_db"]
    if nappe_db is not None and nappe_db > AMB_SANS_DB:
        # La piste son du lieu (fiche du décor, 03/10) : la même eau d'un film à l'autre.
        source, niveau_source = "fiche", nappe_db
    else:
        # La source : le plus long passage sans paroles d'un plan au niveau de référence.
        source, longueur = None, 0
        min_pas, max_pas = round(AMB_SOURCE_MIN_S * 10), round(AMB_SOURCE_MAX_S * 10)
        for p, a, b in zip(plans, debuts, fins):
            lv = p["niveau_db"]
            if lv is None or abs(lv + p["gain_db"] - p["vise_db"]) > 3.0:
                continue
            k = a
            while k < b:
                if parole[k]:
                    k += 1
                    continue
                j = k
                while j < b and not parole[j]:
                    j += 1
                if j - k > longueur:
                    source, longueur = (k, min(j, k + max_pas)), j - k
                k = j
        if source is None or longueur < min_pas:
            return {"parole": parole, "plans": plans, "reference_db": round(ref, 1), "source": None,
                    "nappe": [0.0] * n}
        k0, k1 = source
        # La nappe est le son BRUT de la source : le réglage de son propre plan ne l'affaiblit pas ailleurs.
        niveau_source = _mediane([amb_db[k] for k in range(k0, k1)])
    unite = 10 ** (niveau_source / 20)
    nappe = []
    for k in range(n):
        cible = 10 ** (vise_pas[k] / 20)
        o = 10 ** ((amb_db[k] + gain_pas[k]) / 20)
        g = math.sqrt(max(0.0, cible * cible - o * o)) / unite
        plafond = AMB_NAPPE_MAX * 10 ** (max(0.0, vise_pas[k] - ref) / 20)
        nappe.append(min(g, plafond) * (AMB_SOUS_VOIX if parole[k] else 1.0))
    lisse = [sum(nappe[max(0, k - 2):k + 3]) / len(nappe[max(0, k - 2):k + 3]) for k in range(n)]
    return {"parole": parole, "plans": plans, "reference_db": round(ref, 1), "source": source,
            "nappe": lisse}


def _pcm(chemin: Path, filtre: str, canaux: int, taux: int) -> array.array:
    fini = subprocess.run([_ffmpeg(), "-v", "error", "-i", str(chemin), "-vn", "-af", filtre, "-ac", str(canaux),
                           "-ar", str(taux), "-f", "s16le", "-"], capture_output=True, timeout=DELAI_S)
    if fini.returncode != 0:
        raise MontageImpossible("La lecture du son du film a échoué.")
    a = array.array("h")
    a.frombytes(fini.stdout[:len(fini.stdout) // 2 * 2])
    return a


def _niveaux(ech: array.array, pas: int) -> list:
    return [_db(math.sqrt(sum(x * x for x in ech[i:i + pas]) / pas) / 32768)
            for i in range(0, len(ech) - pas + 1, pas)]


def egaliser_ambiance(film: bytes, bornes_s: list, ajustements_db=None, nappe_wav=None) -> tuple:
    """Le film, son ambiance égalisée d'un plan à l'autre (voir AMB_*), et le rapport.
    Les images ne sont pas réencodées. `bornes_s` : la fin de chaque plan, en secondes ;
    `ajustements_db` : le réglage à la main du fond de chaque plan ; `nappe_wav` : la piste
    son du lieu (fiche du décor), nappe à la place d'un passage du film."""
    with tempfile.TemporaryDirectory() as dossier:
        a, son, sortie = Path(dossier, "film.mp4"), Path(dossier, "son.wav"), Path(dossier, "egal.mp4")
        a.write_bytes(film)
        amb = _niveaux(_pcm(a, AMB_BANDE, 1, AMB_TAUX), AMB_PAS)
        voix = _niveaux(_pcm(a, VOIX_BANDE.rstrip(","), 1, AMB_TAUX), AMB_PAS)
        bornes = [round(b * 10) for b in bornes_s]
        src_fiche, nappe_db = None, None
        if nappe_wav:
            piste = Path(dossier, "lieu.wav")
            piste.write_bytes(nappe_wav)
            src_fiche = _pcm(piste, "highpass=f=%d" % AMB_COUPE_BAS_HZ, 2, AMB_MIX_TAUX)
            nappe_db = _mediane(_niveaux(_pcm(piste, AMB_BANDE, 1, AMB_TAUX), AMB_PAS))
            if len(src_fiche) < 2 * AMB_SOURCE_MIN_S * AMB_MIX_TAUX:
                src_fiche, nappe_db = None, None   # trop courte pour boucler : le film donne la sienne
        d = regler_ambiance(amb, voix, bornes, ajustements_db, nappe_db)
        orig = _pcm(a, "highpass=f=%d" % AMB_COUPE_BAS_HZ, 2, AMB_MIX_TAUX)
        cadres = len(orig) // 2
        par_pas = AMB_MIX_TAUX // 10
        # Le gain de chaque plan, avec des fondus de AMB_FONDU_S de part et d'autre de ses bornes.
        g_plan = [0.0] * len(d["nappe"])
        debuts = [0] + bornes[:-1]
        for p, b0, b1 in zip(d["plans"], debuts, bornes):
            for k in range(b0, min(b1, len(g_plan))):
                g_plan[k] = p["gain_db"]
        f = round(AMB_FONDU_S * 10)
        lin = [10 ** (x / 20) for x in g_plan]
        lin = [sum(lin[max(0, k - f // 2):k + f // 2 + 1]) / len(lin[max(0, k - f // 2):k + f // 2 + 1])
               for k in range(len(lin))]
        nappe = d["nappe"]
        if d["source"] == "fiche":
            src = src_fiche
            fondu = min(round(AMB_FONDU_S * AMB_MIX_TAUX), len(src) // 6)
        elif d["source"]:
            s0, s1 = d["source"][0] * par_pas, d["source"][1] * par_pas
            src = orig[2 * s0:2 * s1]
            fondu = min(round(AMB_FONDU_S * AMB_MIX_TAUX), (s1 - s0) // 3)
        sortie_pcm = array.array("h", bytes(len(orig) * 2))
        lg = len(src) // 2 - fondu if d["source"] else 1
        for i in range(cadres):
            k = min(i // par_pas, len(lin) - 1)
            go = lin[k]
            gn = nappe[k] if d["source"] else 0.0
            for c in (0, 1):
                v = orig[2 * i + c] * go
                if gn:
                    # La boucle : la fin de chaque tour se fond dans le début du suivant.
                    t = i % lg
                    x = src[2 * t + c]
                    if t < fondu and i >= lg:
                        w = t / fondu
                        x = x * w + src[2 * (t + lg) + c] * (1 - w)
                    v += x * gn
                sortie_pcm[2 * i + c] = max(-32768, min(32767, int(v)))
        with wave.open(str(son), "wb") as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(AMB_MIX_TAUX)
            w.writeframes(sortie_pcm.tobytes())
        _lancer(["-i", str(a), "-i", str(son), "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac",
                 "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(sortie)],
                "L'égalisation de l'ambiance")
        if images(sortie) != images(a):
            raise MontageImpossible("L'égalisation de l'ambiance a changé le nombre d'images : "
                                    "le film n'est pas rendu.")
        return sortie.read_bytes(), _rapport_ambiance(d)


def _rapport_ambiance(d: dict) -> dict:
    return {"reference_db": d["reference_db"],
            "coupe_bas_hz": AMB_COUPE_BAS_HZ,
            "plans": [{"plan": i + 1, "niveau_db": p["niveau_db"], "gain_db": p["gain_db"],
                       "ajustement_db": p["ajustement_db"], "vise_db": p.get("vise_db")}
                      for i, p in enumerate(d["plans"])],
            "nappe_depuis_s": [round(d["source"][0] / 10, 1), round(d["source"][1] / 10, 1)]
            if d["source"] and d["source"] != "fiche" else None,
            "nappe_de": "fiche du décor" if d["source"] == "fiche" else "film" if d["source"] else None,
            "parole_s": round(sum(d["parole"]) / 10, 1)}


def piste_du_lieu(film: bytes, depuis_s: list) -> bytes:
    """Le passage sans paroles choisi comme nappe (`nappe_depuis_s` du rapport), en WAV
    stéréo 48 kHz : la piste son du lieu, gardée sur la fiche du décor (03/10)."""
    with tempfile.TemporaryDirectory() as dossier:
        a, sortie = Path(dossier, "film.mp4"), Path(dossier, "lieu.wav")
        a.write_bytes(film)
        _lancer(["-i", str(a), "-ss", "%.2f" % depuis_s[0], "-to", "%.2f" % depuis_s[1], "-vn", "-ac", "2",
                 "-ar", str(AMB_MIX_TAUX), "-c:a", "pcm_s16le", str(sortie)], "La piste son du lieu")
        return sortie.read_bytes()


PASSAGES_MAX = 8


def lire_silences(journal: str, duree_s: float, min_s: float = 0.3, marge_s: float = 0.25,
                  maximum: int = PASSAGES_MAX) -> list:
    """Les passages NON silencieux d'après le journal de `silencedetect`, élargis
    de `marge_s`, ceux de moins de `min_s` écartés (bruits de pas). Rend
    [(debut, fin)], au plus `maximum`, dans l'ordre."""
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
    return passages[:maximum]


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


# Coupe franche DANS un plan (02/10, film 4, plan 2) : une « suite » partie du gros plan de fin du
# plan 1 l'a gardé 0,8 s puis a sauté en plan moyen. Mesuré, en gris 160x90, écart moyen entre deux
# images voisines : 48,2 au saut, médiane 3,3 sur ce plan ; aucune paire au-dessus de 4 fois la
# médiane sur le plan 1 (médiane 4,0) ni sur la reprise au recul continu (3,7).
SAUT_LARGEUR, SAUT_HAUTEUR = 160, 90
SAUT_FOIS_MEDIANE = 4.0
# Un mouvement rapide (pigeons qui s'envolent, prise 2 du même plan) fait des écarts de 8 à 10
# sur huit paires de suite ; une coupe est un pic SEUL, loin au-dessus de ses deux voisines.
SAUT_ECART_MIN = 15.0
SAUT_FOIS_VOISINES = 3.0


def ecarts_d_images(video: bytes) -> list:
    """L'écart moyen (0-255) entre chaque image et la suivante, en gris 160x90."""
    with tempfile.TemporaryDirectory() as dossier:
        a = Path(dossier, "entree")
        a.write_bytes(video)
        fini = subprocess.run([_ffmpeg(), "-loglevel", "error", "-i", str(a), "-an", "-vf",
                               "scale=%d:%d,format=gray" % (SAUT_LARGEUR, SAUT_HAUTEUR), "-f", "rawvideo", "-"],
                              capture_output=True, timeout=DELAI_S)
    taille = SAUT_LARGEUR * SAUT_HAUTEUR
    if fini.returncode != 0 or len(fini.stdout) < 2 * taille:
        raise MontageImpossible("La lecture des images du plan a échoué.")
    brut = fini.stdout
    images = [brut[k:k + taille] for k in range(0, len(brut) - taille + 1, taille)]
    return [sum(abs(x - y) for x, y in zip(a, b)) / taille for a, b in zip(images, images[1:])]


def sauts_d_image(ecarts: list) -> list:
    """[(k, écart)] : les paires (k, k+1) dont l'écart passe SAUT_FOIS_MEDIANE fois la médiane
    du plan, SAUT_ECART_MIN, et SAUT_FOIS_VOISINES fois ses deux voisines : une coupe franche,
    pas un mouvement."""
    if not ecarts:
        return []
    tries = sorted(ecarts)
    mediane = tries[len(tries) // 2]
    seuil = max(SAUT_FOIS_MEDIANE * mediane, SAUT_ECART_MIN)
    sauts = []
    for k, x in enumerate(ecarts):
        voisines = ecarts[max(0, k - 1):k] + ecarts[k + 1:k + 2]
        if x > seuil and all(x > SAUT_FOIS_VOISINES * v for v in voisines):
            sauts.append((k, round(x, 1)))
    return sauts


# Sous-titres (30/09/2026, « il manque la musique et les sous-titres… via le studio »).
# Mesuré sur le film campus : à -35 dB sur tout le spectre, l'ambiance fait un seul passage
# de 17 à 28 s ; dans la bande de la voix (300-3400 Hz) à -30 dB, sept morceaux pour six
# répliques. Une pause ne suffit pas à dire qui parle : 0,54 s au MILIEU de « Hey, are you
# lost? », 0,59 s ENTRE « Je… parle un peu français » et la réponse de Leila. Donc les
# morceaux proches (moins de VOIX_TROU_S) sont écoutés ensemble, puis recoupés aux pauses
# d'au moins VOIX_COUPURE_S seulement si ce qui est entendu fait plusieurs phrases.
VOIX_BANDE = "highpass=f=300,lowpass=f=3400,"
VOIX_SEUIL_DB = -30
VOIX_TROU_S = 0.8
VOIX_COUPURE_S = 0.5
REPLIQUES_MAX = 200
SOUS_TITRE_MIN_S = 1.2     # le temps de lire une réplique courte
SOUS_TITRE_APRES_S = 0.5   # le sous-titre reste un peu après la voix
DELAI_INCRUSTATION_S = 1800


def passages_de_voix(video: bytes) -> list:
    """[(debut, fin, [(debut, fin) des morceaux])] en secondes : ce qui s'écoute d'un coup."""
    with tempfile.TemporaryDirectory() as dossier:
        a = Path(dossier, "entree")
        a.write_bytes(video)
        fini = subprocess.run([_ffmpeg(), "-hide_banner", "-nostats", "-i", str(a), "-vn", "-af",
                               VOIX_BANDE + "silencedetect=n=%ddB:d=0.35" % VOIX_SEUIL_DB, "-f", "null", "-"],
                              capture_output=True, text=True, timeout=DELAI_S)
        duree = re.search(r"Duration: (\d+):(\d+):([\d.]+)", fini.stderr or "")
        if fini.returncode != 0 or not duree:
            raise MontageImpossible("La recherche des répliques a échoué.")
        h, m, s = duree.groups()
        bruts = lire_silences(fini.stderr, int(h) * 3600 + int(m) * 60 + float(s), min_s=0.3, marge_s=0.0,
                              maximum=REPLIQUES_MAX)
    passages = []
    for de, a in bruts:
        if passages and de - passages[-1][1] < VOIX_TROU_S:
            passages[-1] = (passages[-1][0], a, passages[-1][2] + [(de, a)])
        else:
            passages.append((de, a, [(de, a)]))
    return passages


def repartir(morceaux: list, texte: str) -> list:
    """Ce qui a été entendu sur un passage, rendu en répliques [(de, a, texte)] : une
    seule, sauf si le texte fait plusieurs phrases ET que le passage a des pauses d'au
    moins VOIX_COUPURE_S ; on coupe alors aux plus longues, les phrases réparties au
    prorata de leur longueur et de la durée des parts."""
    texte = " ".join(texte.split())
    phrases = [p for p in re.split(r"(?<=[.!?…])\s+", texte) if p]
    pauses = sorted(((morceaux[i + 1][0] - morceaux[i][1], i) for i in range(len(morceaux) - 1)
                     if morceaux[i + 1][0] - morceaux[i][1] >= VOIX_COUPURE_S), reverse=True)
    coupes = sorted(i for _, i in pauses[:max(0, len(phrases) - 1)])
    if not coupes:
        return [(morceaux[0][0], morceaux[-1][1], texte)] if texte else []
    parts, d = [], 0
    for i in coupes + [len(morceaux) - 1]:
        parts.append((morceaux[d][0], morceaux[i][1]))
        d = i + 1
    duree = sum(b - a for a, b in parts)
    bornes, t = [], 0.0
    for a, b in parts:
        t += (b - a) / duree
        bornes.append(t)
    lettres = sum(len(p) for p in phrases)
    textes, c = [[] for _ in parts], 0
    for j, p in enumerate(phrases):
        milieu = (c + len(p) / 2) / lettres
        c += len(p)
        k = next(k for k, b in enumerate(bornes) if milieu <= b + 1e-9)
        # Autant de phrases que de parts : une chacune, dans l'ordre.
        textes[j if len(phrases) == len(parts) else k].append(p)
    sortie = []
    for (a, b), ps in zip(parts, textes):
        if ps:
            sortie.append((a, b, " ".join(ps)))
        elif sortie:
            sortie[-1] = (sortie[-1][0], b, sortie[-1][2])
    return sortie


def calage(repliques: list) -> list:
    """[(de, a, texte)] entendus -> [(de, a, texte)] à afficher : un peu avant la voix,
    assez longtemps pour être lus, jamais par-dessus le suivant."""
    sortie = []
    for k, (de, a, texte) in enumerate(repliques):
        debut = max(0.0, de - 0.15, sortie[-1][1] + 0.05 if sortie else 0.0)
        fin = max(a + SOUS_TITRE_APRES_S, debut + SOUS_TITRE_MIN_S)
        if k + 1 < len(repliques):
            fin = min(fin, max(a, repliques[k + 1][0] - 0.2))
        sortie.append((round(debut, 2), round(fin, 2), texte))
    return sortie


def srt(repliques: list) -> str:
    """Le fichier .srt de [(de, a, texte)] déjà calés."""
    def t(s):
        ms = round(s * 1000)
        return "%02d:%02d:%02d,%03d" % (ms // 3600000, ms // 60000 % 60, ms // 1000 % 60, ms % 1000)
    return "".join("%d\n%s --> %s\n%s\n\n" % (i + 1, t(de), t(a), " ".join(texte.split()))
                   for i, (de, a, texte) in enumerate(repliques))


def incruster_sous_titres(film: bytes, texte_srt: str) -> bytes:
    """Les sous-titres dessinés dans l'image (visibles partout, sur un téléphone comme
    dans une page). Taille relative à la hauteur de l'image : pareil en 480p et en 4K.
    Le son est gardé tel quel ; seules les images sont réencodées."""
    with tempfile.TemporaryDirectory() as dossier:
        a, s, sortie = Path(dossier, "film.mp4"), Path(dossier, "sous.srt"), Path(dossier, "sous_titre.mp4")
        a.write_bytes(film)
        s.write_text(texte_srt, encoding="utf-8")
        style = ("FontName=DejaVu Sans,FontSize=16,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
                 "BorderStyle=1,Outline=1.2,Shadow=0,MarginV=18")
        # Qualité fixe, mais jamais plus lourd que la source (30/09, film campus 4K :
        # 95 Mo réencodés en 147 Mo au crf 17, au-delà de la réserve du Studio).
        debit = debit_video(a)
        plafond = (["-maxrate", "%dk" % (debit * 1.05 // 1000), "-bufsize", "%dk" % (debit * 2 // 1000)]
                   if debit else [])
        # Un film déjà en AV1 le reste, au même réglage : le repasser par H.264 au
        # débit (bas) de l'AV1 l'abîmerait.
        video = (_av1(AV1_CRFS[0]) if codec_video(a) == "av1"
                 else ["-c:v", "libx264", "-crf", "17", *plafond, "-preset", "medium", "-pix_fmt", "yuv420p"])
        fini = subprocess.run([_ffmpeg(), "-loglevel", "error", "-y", "-i", str(a), "-vf",
                               "subtitles=sous.srt:charenc=UTF-8:force_style='%s'" % style,
                               "-map", "0:v", "-map", "0:a?", *video,
                               "-c:a", "copy", "-movflags", "+faststart", str(sortie)],
                              capture_output=True, text=True, timeout=DELAI_INCRUSTATION_S, cwd=dossier)
        if fini.returncode != 0:
            raise MontageImpossible("L'incrustation des sous-titres a échoué : %s"
                                    % (fini.stderr or "").strip()[-300:])
        if images(sortie) != images(a):
            raise MontageImpossible("L'incrustation des sous-titres a changé le nombre d'images : "
                                    "le film n'est pas rendu.")
        return sortie.read_bytes()


# --- Un visage refait qui saute (30/09/2026) ------------------------------------
# Le fond du film aux visages refaits est celui de l'origine : l'écart entre les
# deux vient des visages collés, et il varie doucement d'une image à l'autre. Un
# visage qui change d'un coup (les « trucs bizarres » du film campus, hors de la
# grille 17k+5) le fait bondir. Calibrage du 30/09 sur ce film, vignettes grises
# 112x64 : film abîmé, plus grand saut de trois passages à 2,7, 3,4 et 3,5 fois
# leur médiane (et 1,7 pour un quatrième) ; film corrigé, 1,4 au plus.
SAUT_VISAGE_FOIS = 1.6
VIGNETTE_L, VIGNETTE_H = 112, 64


def _vignettes(video: bytes) -> list:
    with tempfile.TemporaryDirectory() as dossier:
        a = Path(dossier, "v.mp4")
        a.write_bytes(video)
        fini = subprocess.run([_ffmpeg(), "-v", "error", "-i", str(a), "-vf",
                               "scale=%d:%d" % (VIGNETTE_L, VIGNETTE_H), "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                              capture_output=True, timeout=DELAI_S)
    if fini.returncode != 0:
        raise MontageImpossible("La lecture des images pour le contrôle des visages a échoué.")
    n = VIGNETTE_L * VIGNETTE_H
    return [fini.stdout[i:i + n] for i in range(0, len(fini.stdout) - n + 1, n)]


def sauts_de_visages(origine: bytes, retouche: bytes, passages: list) -> list:
    """Les passages [de, a) (en images) où un visage refait saute : [{de, a, image, fois}]."""
    a, b = _vignettes(origine), _vignettes(retouche)
    n = VIGNETTE_L * VIGNETTE_H
    ecarts = [bytes(abs(x - y) for x, y in zip(fa, fb)) for fa, fb in zip(a, b)]
    trouves = []
    for de, fin in passages:
        fin = min(fin, len(ecarts))
        sauts = [sum(abs(x - y) for x, y in zip(ecarts[i + 1], ecarts[i])) / n for i in range(de, fin - 1)]
        if len(sauts) < 3:
            continue
        mediane = sorted(sauts)[len(sauts) // 2]
        haut = max(sauts)
        if mediane > 0 and haut > SAUT_VISAGE_FOIS * mediane:
            trouves.append({"de": de, "a": fin, "image": de + 1 + sauts.index(haut),
                            "fois": round(haut / mediane, 1)})
    return trouves


# --- AV1 pour les films en haute définition (30/09/2026) -----------------------
# Demande du propriétaire : un compresseur qui garde la qualité, en post-traitement
# 4K, codé dans le Studio, SANS copie H.264 à côté. Essai du même soir sur le film
# campus 4K (H.264, 95,5 Mo, 30 s), SVT-AV1 preset 6, ~35 s de calcul par essai sur
# ce PC, VMAF 4K (une image sur 4) mesuré contre le H.264 :
#   crf 26 : 79,7 Mo, VMAF 99,6 (pire image 97,1) ; PSNR-Y 43,5, pire image 42,9
#   crf 30 : 61,4 Mo, VMAF 99,1 (96,0) ; 42,5 / 41,8
#   crf 34 : 46,3 Mo, VMAF 98,4 (94,7) ; 41,5 / 40,5   <- retenu : moitié du poids
#   crf 38 : 35,2 Mo, VMAF 97,4 (93,0) ; 40,5 / 39,3
#   crf 42 : 27,1 Mo, VMAF 96,2 (91,1) ; 39,5 / 38,1
# Le conteneur n'a pas VMAF : la garde est le PSNR, dont les deux seuils séparent
# crf 34 (gardé) de crf 38 (refusé) SUR CE FILM -- un seul film de calibrage.
# La garde refuse crf 34 : on essaie crf 30 ; refusé encore : le film reste en H.264.
AV1_CRFS = (34, 30)
AV1_PRESET = 6
AV1_PSNR_Y_MOYEN_MIN = 41.0   # dB, moyenne de la luminance
AV1_PSNR_PIRE_MIN = 40.0      # dB, la pire image (toutes composantes)
DELAI_AV1_S = 3600


def codec_video(chemin: Path) -> str:
    """Le codec de la première piste vidéo (« h264 », « av1 »...)."""
    return _sonde(chemin, "codec_name")


def _av1(crf: int) -> list:
    return ["-c:v", "libsvtav1", "-preset", str(AV1_PRESET), "-crf", str(crf), "-pix_fmt", "yuv420p"]


# 02/10, 4K de « Leila et un martien » : l'AV1 rendait 752 images pour 843 (ffmpeg en
# cadence fixe jetait celles aux horodatages irréguliers des morceaux agrandis), et la
# garde refusait le film. Chaque image passe, horodatée de neuf à 24 images/s.
AV1_IPS = 24


def _av1_film(crf: int) -> list:
    # « -fps_mode passthrough » laisse SVT-AV1 sans cadence (Invalid argument) : les
    # horodatages refaits sont réguliers, la cadence fixe n'a plus rien à jeter.
    return ["-vf", "setpts=N/(%d*TB)" % AV1_IPS, "-r", str(AV1_IPS), *_av1(crf)]


def psnr(distordu: Path, reference: Path) -> tuple:
    """(PSNR-Y moyen, PSNR de la pire image) en dB, une image sur 4."""
    f = ("[0:v]select='not(mod(n\\,4))',setpts=N[a];[1:v]select='not(mod(n\\,4))',setpts=N[b];[a][b]psnr")
    fini = subprocess.run([_ffmpeg(), "-hide_banner", "-nostats", "-i", str(distordu), "-i", str(reference),
                           "-lavfi", f, "-f", "null", "-"], capture_output=True, text=True, timeout=DELAI_AV1_S)
    m = re.search(r"PSNR y:([\d.]+|inf).*?min:([\d.]+|inf)", fini.stderr or "")
    if fini.returncode != 0 or not m:
        raise MontageImpossible("La mesure de qualité (PSNR) a échoué.")
    return tuple(float(x) for x in m.groups())


# 02/10, « Leila et un martien » en 4K : sept passages de carte (3 h 30), puis 102 Mo
# après la compression, pour une réserve de 100 Mo : le film a été jeté. Au-dessus du
# plafond, on comprime un cran de plus, jusqu'à tenir ; la fiche garde le PSNR mesuré.
AV1_CRFS_PLAFOND = (38, 42, 46, 50)


def compacter_av1(film: bytes, plafond: int = 0) -> tuple:
    """Le film en AV1 s'il garde la qualité mesurée et pèse moins ; sinon tel quel.
    Rend (octets, fiche) ; la fiche dit ce qui a été fait et mesuré. Avec `plafond`
    (octets), un film qui le dépasse encore est recomprimé plus fort jusqu'à tenir."""
    octets, fiche = _compacter_av1_qualite(film)
    if not plafond or len(octets) <= plafond or fiche.get("deja"):
        return octets, fiche
    with tempfile.TemporaryDirectory() as dossier:
        a = Path(dossier, "film.mp4")
        a.write_bytes(film)
        essais = list(fiche.get("essais") or [])
        for crf in AV1_CRFS_PLAFOND:
            sortie = Path(dossier, "av1_%d.mp4" % crf)
            fini = subprocess.run([_ffmpeg(), "-loglevel", "error", "-y", "-i", str(a), "-map", "0:v", "-map", "0:a?",
                                   *_av1_film(crf), "-c:a", "copy", "-movflags", "+faststart", str(sortie)],
                                  capture_output=True, text=True, timeout=DELAI_AV1_S)
            if fini.returncode != 0 or images(sortie) != images(a):
                break
            moyen, pire = psnr(sortie, a)
            essai = {"crf": crf, "mo": round(sortie.stat().st_size / 1e6, 1),
                     "psnr_y": round(moyen, 2), "psnr_pire": round(pire, 2)}
            essais.append(essai)
            if sortie.stat().st_size <= plafond:
                return sortie.read_bytes(), dict(essai, codec="av1", avant_mo=round(len(film) / 1e6, 1),
                                                 sous_plafond=True, essais=essais)
        return octets, dict(fiche, essais=essais, plafond="aucun réglage ne tient sous le plafond")


def _compacter_av1_qualite(film: bytes) -> tuple:
    with tempfile.TemporaryDirectory() as dossier:
        a = Path(dossier, "film.mp4")
        a.write_bytes(film)
        if codec_video(a) == "av1":
            return film, {"codec": "av1", "deja": True}
        essais = []
        for crf in AV1_CRFS:
            sortie = Path(dossier, "av1_%d.mp4" % crf)
            fini = subprocess.run([_ffmpeg(), "-loglevel", "error", "-y", "-i", str(a), "-map", "0:v", "-map", "0:a?",
                                   *_av1_film(crf), "-c:a", "copy", "-movflags", "+faststart", str(sortie)],
                                  capture_output=True, text=True, timeout=DELAI_AV1_S)
            if fini.returncode != 0 or images(sortie) != images(a):
                return film, {"codec": codec_video(a), "raison": "l'encodage AV1 a échoué", "essais": essais}
            moyen, pire = psnr(sortie, a)
            essai = {"crf": crf, "mo": round(sortie.stat().st_size / 1e6, 1),
                     "psnr_y": round(moyen, 2), "psnr_pire": round(pire, 2)}
            essais.append(essai)
            if (moyen >= AV1_PSNR_Y_MOYEN_MIN and pire >= AV1_PSNR_PIRE_MIN
                    and sortie.stat().st_size < a.stat().st_size):
                return sortie.read_bytes(), dict(essai, codec="av1", avant_mo=round(len(film) / 1e6, 1),
                                                 essais=essais)
        return film, {"codec": codec_video(a), "raison": "la qualité mesurée ne suffisait pas", "essais": essais}


def debit_video(chemin: Path):
    """Le débit (bits/s) de la première piste vidéo, ou None s'il est illisible."""
    try:
        debit = int(_sonde(chemin, "bit_rate"))
    except (MontageImpossible, ValueError):
        return None
    return debit if debit > 0 else None


def son_du_passage(video: bytes, debut_s: float, fin_s: float) -> bytes:
    """Le son de [debut_s, fin_s), en MP3, pour l'envoyer à l'écoute."""
    with tempfile.TemporaryDirectory() as dossier:
        a, sortie = Path(dossier, "entree"), Path(dossier, "passage.mp3")
        a.write_bytes(video)
        _lancer(["-ss", "%.3f" % debut_s, "-to", "%.3f" % fin_s, "-i", str(a), "-vn",
                 "-ac", "1", "-b:a", "96k", str(sortie)], "L'extraction d'un passage parlé")
        return sortie.read_bytes()


COUPE_SEUIL = 0.3   # changement de scène vu par ffmpeg (03/10 : les 5 coupes du maître, rien d'autre)


def coupes_vues(video: bytes, seuil: float = COUPE_SEUIL) -> list:
    """Les heures (s) où l'image change de plan, vues par ffmpeg (filtre scene)."""
    with tempfile.TemporaryDirectory() as dossier:
        a = Path(dossier, "a.mp4")
        a.write_bytes(video)
        fini = subprocess.run([_ffmpeg(), "-loglevel", "info", "-i", str(a), "-vf",
                               "select='gt(scene,%g)',showinfo" % seuil, "-f", "null", "-"],
                              capture_output=True, text=True, timeout=DELAI_S)
    if fini.returncode != 0:
        raise MontageImpossible("La recherche des coupes a échoué : %s" % (fini.stderr or "").strip()[-300:])
    return [float(m) for m in re.findall(r"pts_time:([0-9.]+)", fini.stderr or "")]


def image_numero(video: bytes, numero: int) -> bytes:
    """L'image n° `numero` (à partir de 0) d'une vidéo, en PNG."""
    with tempfile.TemporaryDirectory() as dossier:
        a, sortie = Path(dossier, "a.mp4"), Path(dossier, "image.png")
        a.write_bytes(video)
        _lancer(["-i", str(a), "-vf", "select=eq(n\\,%d)" % numero, "-frames:v", "1", str(sortie)],
                "L'extraction d'une image du clip")
        if not sortie.is_file() or not sortie.stat().st_size:
            raise MontageImpossible("Le clip n'a pas d'image n° %d." % numero)
        return sortie.read_bytes()


PLANCHE_IMAGES = 12   # 4 x 3, une image toutes les 0,5 s : un plan de 5 s y tient
# 03/10, clip maître de 15 s : la planche 4 x 3 n'en montrait que les 6 premières secondes, et le
# juge a dit « ok » à une fillette dédoublée à 12,5 s. Jusqu'à 36 images (18 s, au-delà des 15,1 s
# d'un clip H3), 6 de front passé 12 ; un passage plus long se juge en plusieurs planches.
PLANCHE_IMAGES_MAX = 36


def planche(video: bytes, debut_s: float, duree_s: float) -> tuple[bytes, int]:
    """Une planche PNG du passage [debut_s, debut_s + duree_s) : une image toutes
    les 0,5 s, numérotées de gauche à droite puis de haut en bas (28/09/2026,
    pour faire juger un plan par un modèle qui voit). Rend (png, nombre d'images)."""
    nombre = max(1, min(PLANCHE_IMAGES_MAX, int(-(-duree_s * 2 // 1))))
    colonnes = 4 if nombre <= PLANCHE_IMAGES else 6
    lignes = max(3, -(-nombre // colonnes))
    with tempfile.TemporaryDirectory() as dossier:
        a, sortie = Path(dossier, "a.mp4"), Path(dossier, "planche.png")
        a.write_bytes(video)
        _lancer(["-ss", "%.3f" % debut_s, "-t", "%.3f" % duree_s, "-i", str(a),
                 "-vf", "fps=2,scale=416:-1,tile=%dx%d" % (colonnes, lignes), "-frames:v", "1", str(sortie)],
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


def taire(video: bytes) -> bytes:
    """La même vidéo, images intactes (copiées), son mis à zéro : la piste reste."""
    with tempfile.TemporaryDirectory() as dossier:
        a, b = Path(dossier, "a.mp4"), Path(dossier, "b.mp4")
        a.write_bytes(video)
        _lancer(["-i", str(a), "-c:v", "copy", "-af", "volume=0", "-c:a", "aac", str(b)], "Le silence du raccord")
        return b.read_bytes()


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


def largeur_image(image: bytes) -> int:
    """La largeur d'une image, en pixels."""
    with tempfile.TemporaryDirectory() as dossier:
        chemin = Path(dossier, "image")
        chemin.write_bytes(image)
        try:
            return int(_sonde(chemin, "width"))
        except ValueError as exc:
            raise MontageImpossible("La largeur de l'image est illisible.") from exc


def taille(video: bytes) -> tuple[int, int]:
    """La largeur et la hauteur d'une vidéo (ou d'une image), en pixels."""
    with tempfile.TemporaryDirectory() as dossier:
        chemin = Path(dossier, "video")
        chemin.write_bytes(video)
        try:
            return int(_sonde(chemin, "width")), int(_sonde(chemin, "height"))
        except ValueError as exc:
            raise MontageImpossible("La taille de la vidéo est illisible.") from exc


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


def coller_sans_reencoder(videos: list, ips: float = 0, son: bytes = b"") -> bytes:
    """Des vidéos faites par la même machine, de mêmes réglages, mises bout à bout
    sans réencodage : un film 4K réencodé ici prendrait plusieurs minutes de
    processeur (finalisation, 30/09/2026). Nombre d'images vérifié.

    `ips` : la cadence du film, reposée sans réencoder. 02/10, 4K de « Leila et un
    martien » : les morceaux agrandis sortaient à 24,77 et 24,83 images/s, en deux
    échelles de temps ; collés tels quels, 843 images duraient 43,6 s pour 34 s de son,
    et l'AV1 échouait ensuite. `son` : le film d'où reprendre le son (l'original)."""
    if len(videos) == 1 and not ips:
        return videos[0]
    with tempfile.TemporaryDirectory() as dossier:
        chemins = []
        for k, v in enumerate(videos):
            c = Path(dossier, "m%02d.mp4" % k)
            c.write_bytes(v)
            if ips:
                c = _recadencer(c, Path(dossier, "r%02d.mp4" % k), ips)
            chemins.append(c)
        liste, sortie = Path(dossier, "liste.txt"), Path(dossier, "film.mp4")
        liste.write_text("".join("file '%s'\n" % c.name for c in chemins))
        _lancer(["-f", "concat", "-safe", "0", "-i", str(liste), "-c", "copy", "-movflags", "+faststart",
                 str(sortie)], "La mise bout à bout")
        attendu = sum(images(c) for c in chemins)
        if images(sortie) != attendu:
            raise MontageImpossible("La mise bout à bout a rendu %d images au lieu de %d."
                                    % (images(sortie), attendu))
        if son:
            original, avec_son = Path(dossier, "son.mp4"), Path(dossier, "film_son.mp4")
            original.write_bytes(son)
            _lancer(["-i", str(sortie), "-i", str(original), "-map", "0:v", "-map", "1:a?", "-c", "copy",
                     "-movflags", "+faststart", str(avec_son)], "Le son de l'original")
            if images(avec_son) != attendu:
                raise MontageImpossible("Le son repris a laissé %d images au lieu de %d."
                                        % (images(avec_son), attendu))
            sortie = avec_son
        return sortie.read_bytes()


def _recadencer(morceau: Path, sortie: Path, ips: float) -> Path:
    """Le même flux vidéo, sans réencodage, horodaté à `ips` images/s sur une échelle de
    temps commune (`-itsscale` garde l'ordre des images B) ; le son du morceau part, le
    film reprend celui de l'original."""
    n = images(morceau)
    duree = float(_sonde(morceau, "duration"))
    if n <= 0 or duree <= 0:
        raise MontageImpossible("Un morceau du film n'a pas pu être lu.")
    _lancer(["-itsscale", "%.9f" % (n / duree / ips), "-i", str(morceau), "-map", "0:v", "-c", "copy",
             "-video_track_timescale", str(int(round(ips * 512))), str(sortie)], "La cadence reposée")
    return sortie
