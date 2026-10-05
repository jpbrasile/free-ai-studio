"""Refaire les visages petits d'un clip H3 : ComfyUI-H3-FaceRefine (Carasibana, MIT).

Question du propriétaire, 30/09/2026 : « pour améliorer la qualité des visages en
champ lointain en basse résolution aucune astuce sur le web ? », puis « oui code la
route visages ». H3 rend mal un visage qui occupe peu de l'image ; un agrandisseur
(SeedVR2, agrandir.py) affine ce qui est là, il ne refait pas un visage. FaceRefine
détecte le visage à chaque image, recadre pour qu'il remplisse l'image, fait
regénérer ce recadrage par H3 à faible débruitage, puis le recolle.

Choix du Studio, sur l'étude du 30/09 (lecture seule du dépôt au tag v1.1.2) :
- un personnage par passe (dit par le nœud) ; deux au plus, la passe 2 part du
  résultat de la passe 1 ;
- l'identité vient des photos de la FICHE, données en références à H3 ; ni
  InsightFace (poids « non-commercial research only ») ni son suivi d'identité :
  le personnage est choisi par sa place dans l'image (le plus à gauche, …) ;
- sans MiniMaxH3NativeAudioLock (dépôt sans licence publiée) : le son régénéré est
  jeté, le son d'origine est reposé ;
- le détecteur `face_yolov8m.pt` (Bingsu/adetailer, révision épinglée) et
  ultralytics (AGPL-3.0) vivent dans la machine louée, jamais importés ici : le
  même schéma que ComfyUI (GPL). Une version hébergée ou vendue demanderait une
  licence Ultralytics ou un autre détecteur.

Temps et prix : le dépôt n'en publie aucun ; ceux ci-dessous viennent du premier
essai par le Studio, le 30/09/2026.
"""
import base64
import re

import budget_modal
import video_h3

FR_DEPOT = "https://github.com/Carasibana/ComfyUI-H3-FaceRefine"
FR_COMMIT = "d8521d14fe0d721d80cd9417fff5a559cbc21aba"   # tag v1.1.2, lu le 30/09/2026
FR_DOSSIER = video_h3.DOSSIER_COMFY + "/custom_nodes/h3_face_refine"
# ultralytics seul : scipy vient avec ComfyUI ; scenedetect (coupes) et insightface
# (identité) ne sont importés que si on les demande, et on ne les demande pas.
COMMANDES = video_h3.COMMANDES + (
    f"git clone {FR_DEPOT} {FR_DOSSIER}",
    f"cd {FR_DOSSIER} && git checkout {FR_COMMIT}",
    "pip install ultralytics==8.4.166",
)
DETECTEUR = "face_yolov8m.pt"
DETECTEUR_DEPOT = "Bingsu/adetailer"
DETECTEUR_REVISION = "53cc19de382014514d9d4038601d261a7faa9b7b"   # relevée le 30/09/2026
DETECTEUR_OCTETS = 52026019
DOSSIER_DETECTEUR = video_h3.POINT_DE_MONTAGE + "/facerefine"
PAQUETS = ("huggingface_hub==1.9.2",)

# La machine d'un clip H3 : mêmes poids, même carte.
GPU, MEMOIRE_MB, COEURS = video_h3.GPU, video_h3.MEMOIRE_MB, video_h3.COEURS
DUREE_MAX_S = video_h3.DUREE_MAX_S
# Mesuré le 30/09/2026 (parc, plan 3, 123 images, 2 personnages de 32 px) : location
# 229 s, dont ComfyUI prêt en 30 s et calcul 78 s, soit 0,32 s par image et par passe ;
# pic 39,2 Go. Majoré : 150 s de démarrage (machine + ComfyUI), 0,4 s par image et passe.
DEMARRAGE_S = 150
S_PAR_IMAGE_ET_PASSE = 0.4
SUJETS_MAX = 2
PHOTOS_PAR_SUJET = 3
VIDEO_MAX_OCTETS = 60 * 1024 * 1024
# Valeurs des exemples du dépôt, sauf les pas : 4, ceux de notre LoRA Turbo.
DEBRUITAGE = 0.4
# « largest_face_2 » : le 2e plus grand visage (select_index 1). Essai du 30/09, parc
# plans 1 et 4 : « right_most » a pris un passant au fond (visage de 6-7 px) au lieu de
# Marc ; les deux personnages sont les deux plus grands visages, les passants non.
CHOIX = ("left_most", "right_most", "centre_most", "largest_face", "largest_face_2", "smallest_face")
# Sous cette hauteur moyenne, le visage suivi est sans doute un passant du fond.
VISAGE_MINUSCULE_PX = 12


def sur_la_grille(n: int) -> int:
    """La longueur que H3 calcule pour `n` images : la première de la forme 17k+5 qui les
    contient. FaceRefine arrondit en complétant avec l'image de RÉFÉRENCE ; mesuré le
    30/09/2026 sur le film campus (« des trucs bizarres sur les visages ») : passages de
    119 images, portés à 124, visages des ~11 dernières images remplacés par une bouillie
    violet et or ; ceux de 124 images, propres."""
    return max(5, n + (5 - n) % 17)


def ordre_sur_la_grille(n: int) -> list:
    """Les images du passage à donner à FaceRefine, déjà sur la grille : le passage, puis
    lui-même en miroir (…, n-2, n-3, …) jusqu'à la longueur de la grille. Le miroir garde
    le même plan et le même visage, là où l'image voisine du film appartient souvent au
    plan suivant (les passages sont coupés aux changements de plan) et tirerait le lissage
    du recadrage (21 images) vers un autre visage. La sortie est recoupée aux `n` premières."""
    if n == 1:
        return [0] * sur_la_grille(1)
    periode = 2 * (n - 1)
    return [j % periode if j % periode < n else periode - j % periode for j in range(sur_la_grille(n))]


def estimation_s(images: int, sujets: int) -> float:
    return estimation_passages([(images, sujets)])


def estimation_passages(passages: list) -> float:
    """Une location, un seul chargement du modèle, les passages [(images, sujets)] l'un
    après l'autre : le démarrage ne se paie qu'une fois (30/09/2026, demande du
    propriétaire : « autant avoir un seul chargement et en série »). Chaque passage se
    calcule à sa longueur sur la grille (`sur_la_grille`)."""
    return DEMARRAGE_S + sum(s * sur_la_grille(n) * S_PAR_IMAGE_ET_PASSE for n, s in passages)


def tient_en_une_location(passages: list) -> bool:
    return estimation_passages(passages) <= DUREE_MAX_S * 0.8


def delai_s(images: int, sujets: int) -> int:
    """Le démarrage compte double dans la marge, quelle que soit la longueur : le 30/09,
    quatre passages loués en même temps (finalisation) ont lu ensemble les 26 Go du
    modèle de texte sur le disque Modal ; deux ont fini en 142 et 149 s, les deux plus
    courts chargeaient encore à 316 et 344 s et ont été coupés à leur délai (365 et
    396 s), qui dépendait de leur longueur alors que le démarrage n'en dépend pas."""
    return delai_passages([(images, sujets)])


def delai_passages(passages: list) -> int:
    calcul = sum(s * sur_la_grille(n) * S_PAR_IMAGE_ET_PASSE for n, s in passages)
    return min(DUREE_MAX_S, int((2 * DEMARRAGE_S + calcul) * 1.5) + 120)


def prix_passages(passages: list) -> dict:
    """Le devis d'une location pour plusieurs passages ; ValueError si trop long."""
    if not passages or any(n <= 0 for n, _ in passages):
        raise ValueError("Vidéo vide.")
    if any(not 1 <= s <= SUJETS_MAX for _, s in passages):
        raise ValueError("Un ou deux personnages par traitement.")
    estime = estimation_passages(passages)
    if estime > DUREE_MAX_S * 0.8:
        raise ValueError("Trop long en une fois (%d s de calcul estimées, %d au plus) : "
                         "traitez un plan à la fois." % (estime, int(DUREE_MAX_S * 0.8)))
    par_s = budget_modal.prix_seconde(GPU, MEMOIRE_MB, COEURS)
    delai = delai_passages(passages)
    return {"images": sum(n for n, _ in passages), "sujets": max(s for _, s in passages),
            "passages": len(passages), "secondes_estimees": round(estime),
            "estime_usd": round(par_s * estime, 2), "pire_usd": round(par_s * delai, 2),
            "delai_s": delai, "mesure": True}


def prix(images: int, sujets: int) -> dict:
    """Ce que la page affiche AVANT de payer ; ValueError si ce n'est pas faisable."""
    if images <= 0:
        raise ValueError("Vidéo vide.")
    if not 1 <= sujets <= SUJETS_MAX:
        raise ValueError("Un ou deux personnages par traitement.")
    d = prix_passages([(images, sujets)])
    del d["passages"]
    return d


def invite(nb_photos: int) -> str:
    """Un sujet, ses photos, un gros plan : le recadrage ne montre que son visage."""
    return (video_h3.sujets_des_fiches([nb_photos]) + video_h3.TITRE_DESCRIPTION_REFERENCES + "[Shot 1] A close-up "
            "of the face of <Subject 1>, who moves exactly as in the source frames.\n\nnon_diegetic_music: N/A")


def graphe(sujets: list, prefixe: str = "visages/v", source: str = "source.mp4", premiere_photo: int = 0) -> dict:
    """`sujets` : [(choix, nombre de photos)], dans l'ordre des passes. Format API."""
    nom = lambda chemin: chemin.split("/")[1]  # noqa: E731
    g = {
        "1": _n("LoadVideo", {"file": source}),
        "2": _n("GetVideoComponents", {"video": ["1", 0]}),
        "3": _n("UNETLoader", {"unet_name": nom(video_h3.FICHIERS[0]), "weight_dtype": "default"}),
        "4": _n("LoraLoaderModelOnly", {"model": ["3", 0], "lora_name": nom(video_h3.FICHIERS[4]),
                                         "strength_model": 1.0}),
        "5": _n("CLIPLoader", {"clip_name": nom(video_h3.FICHIERS[1]), "type": "minimax"}),
        "6": _n("VAELoader", {"vae_name": nom(video_h3.FICHIERS[2])}),
        "7": _n("VAELoader", {"vae_name": nom(video_h3.FICHIERS[3])}),
        "8": _n("KSamplerSelect", {"sampler_name": "res_multistep"}),
        "9": _n("RandomNoise", {"noise_seed": 42}),
    }
    images, photo = ["2", 0], premiere_photo
    for p, (choix, nb) in enumerate(sujets):
        b = 100 * (p + 1)
        k = lambda i: str(b + i)  # noqa: E731
        g[k(1)] = _n("H3FaceTrackCrop", {
            "images": images, "detector": DETECTEUR, "confidence": 0.35, "crop_factor": 3.0,
            "canvas_width": 768, "canvas_height": 768, "canvas_mode": "auto_capped_768",
            "smooth_window": 21, "size_smooth_window": 51, "smooth_method": "gaussian", "size_mode": "per_frame",
            "identity_track": False, "select": choix.removesuffix("_2"), "select_index": int(choix.endswith("_2")),
            "fallback_detector": "none", "cut_detection": "none", "absent_shots": "off"})
        entrees = {"clip": ["5", 0], "vae": ["6", 0], "audio_vae": ["7", 0], "prompt": invite(nb),
                   "ref_image_size": "match", "width": [k(1), 4], "height": [k(1), 5], "length": [k(1), 6]}
        for i in range(nb):
            g[k(10 + i)] = _n("LoadImage", {"image": "ref_%d.png" % (photo + i)})
            entrees["ref_images.ref_image_%d" % i] = [k(10 + i), 0]
        photo += nb
        g[k(2)] = _n("MiniMaxH3ReferenceToVideo", entrees)
        g[k(3)] = _n("H3InjectVideoLatent", {"av_latent": [k(2), 1], "images": [k(1), 0], "vae": ["6", 0]})
        g[k(4)] = _n("H3PerFrameDenoise", {
            "model": ["4", 0], "av_latent": [k(3), 0], "transform": [k(1), 1],
            "denoise_multiplier_small_face": 1.0, "denoise_multiplier_large_face": 0.35,
            "scale_mode": "absolute_px", "face_px_small": 30.0, "face_px_large": 120.0, "gamma": 1.0,
            "smooth_frames": 9})
        # Le modèle patché par PerFrameDenoise, sinon son effet est perdu sans message.
        g[k(5)] = _n("BasicGuider", {"model": [k(4), 2], "conditioning": [k(2), 0]})
        g[k(6)] = _n("BasicScheduler", {"model": [k(4), 2], "scheduler": "simple", "steps": 4,
                                         "denoise": DEBRUITAGE})
        g[k(7)] = _n("SamplerCustomAdvanced", {"noise": ["9", 0], "guider": [k(5), 0], "sampler": ["8", 0],
                                                "sigmas": [k(6), 0], "latent_image": [k(4), 0]})
        g[k(8)] = _n("VAEDecode", {"samples": [k(7), 0], "vae": ["6", 0]})
        g[k(9)] = _n("H3FaceStitch", {
            "base_images": images, "refined_crops": [k(8), 0], "transform": [k(1), 1],
            "paste_region": "face_only", "mask_dilation": 24, "feather": 24, "colour_match": 1.0,
            "blend": 1.0, "undetected_frames": "fade_out"})
        images = [k(9), 0]
    # Le son d'origine : celui que H3 régénère n'est tenu par rien (pas d'AudioLock).
    g["90"] = _n("CreateVideo", {"images": images, "fps": ["2", 2], "audio": ["2", 1]})
    g["91"] = _n("SaveVideo", {"video": ["90", 0], "filename_prefix": prefixe, "format": "auto",
                               "format.codec": "auto"})
    return g


def _n(classe: str, entrees: dict) -> dict:
    return {"class_type": classe, "inputs": entrees}


CLASSES = ("LoadVideo", "GetVideoComponents", "UNETLoader", "LoraLoaderModelOnly", "CLIPLoader", "VAELoader",
           "KSamplerSelect", "RandomNoise", "H3FaceTrackCrop", "LoadImage", "MiniMaxH3ReferenceToVideo",
           "H3InjectVideoLatent", "H3PerFrameDenoise", "BasicGuider", "BasicScheduler", "SamplerCustomAdvanced",
           "VAEDecode", "H3FaceStitch", "CreateVideo", "SaveVideo")


def photos(fid) -> list:
    """Les photos d'une fiche de personne (base64 nu), face d'abord, 3 au plus."""
    fiche = video_h3.fiche_lire(fid)
    if video_h3.fiche_est_objet(fiche):
        raise ValueError("« %s » est un objet : seuls les visages se refont." % fiche["nom"])
    images = video_h3.fiche_images(fid)[:PHOTOS_PAR_SUJET]
    if not images:
        raise ValueError("La fiche « %s » n'a pas de photo." % fiche["nom"])
    return images


def demande(video: bytes, sujets: list, de: int, a: int) -> dict:
    """`sujets` : [(fiche, choix)]. `de`, `a` : les images du clip à traiter [de, a)."""
    return demande_passages(video, [(de, a, sujets)])


def demande_passages(video: bytes, passages: list) -> dict:
    """`passages` : [(de, a, [(fiche, choix)])], dans l'ordre du film. Une location :
    ComfyUI démarre une fois, les modèles se chargent une fois, les passages passent
    l'un après l'autre ; la vidéo rendue est leur suite, bout à bout, avec leur son."""
    if len(video) > VIDEO_MAX_OCTETS:
        raise ValueError("Vidéo trop lourde pour être traitée ici.")
    refs, sortie = [], []
    for k, (de, a, sujets) in enumerate(passages):
        if not 1 <= len(sujets) <= SUJETS_MAX:
            raise ValueError("Un ou deux personnages par traitement.")
        if not 0 <= int(de) < int(a):
            raise ValueError("Passage vide.")
        passes, premiere = [], len(refs)
        for fid, choix in sujets:
            if choix not in CHOIX:
                raise ValueError("Place du personnage inconnue : %s." % choix)
            p = photos(fid)
            refs += p
            passes.append((choix, len(p)))
        source = "source.mp4" if len(passages) == 1 else "source_%d.mp4" % k
        prefixe = "visages/v" if len(passages) == 1 else "visages/p%02d_" % k
        sortie.append({"de": int(de), "a": int(a), "source": source, "prefixe": prefixe,
                       "ordre": ordre_sur_la_grille(int(a) - int(de)),
                       "graphe": graphe(passes, prefixe, source, premiere)})
    return {"video": base64.b64encode(video).decode(), "de": sortie[0]["de"], "a": sortie[-1]["a"],
            "passages": sortie, "images_par_seconde": video_h3.IMAGES_PAR_SECONDE,
            "images": {"ref_%d.png" % i: b for i, b in enumerate(refs)},
            "graphe": sortie[0]["graphe"], "classes": list(CLASSES), "comfy": video_h3.DOSSIER_COMFY,
            "base_poids": video_h3.POINT_DE_MONTAGE, "fichiers": list(video_h3.FICHIERS),
            "detecteur": {"depot": DETECTEUR_DEPOT, "revision": DETECTEUR_REVISION, "nom": DETECTEUR,
                          "octets": DETECTEUR_OCTETS, "dossier": DOSSIER_DETECTEUR},
            # Le délai de la location : le script rend la main (DELAI) avant d'être coupé.
            "delai_s": delai_passages([(int(a) - int(de), len(s)) for de, a, s in passages])}


def construire_script_passages(video: bytes, passages: list) -> str:
    return video_h3._emballer(_SCRIPT, demande_passages(video, passages))


def construire_script(video: bytes, sujets: list, de: int, a: int) -> str:
    return video_h3._emballer(_SCRIPT, demande(video, sujets, de, a))


def avertissements(rapports: list, noms: list) -> list:
    """Ce que le rapport du suiveur dit d'un mauvais choix, passe par passe (dans
    l'ordre de `noms`) : un visage minuscule, ou un visage trouvé sur peu d'images."""
    tailles = [float(m.group(1)) for m in (re.search(r"face height .*mean=([0-9.]+)px", l) for l in rapports) if m]
    trouves = [int(m.group(1)) for m in (re.search(r"frames=\d+ +face=\d+ \((\d+)%\)", l) for l in rapports) if m]
    dits = []
    for nom, taille, part in zip(noms, tailles, trouves):
        if taille < VISAGE_MINUSCULE_PX:
            dits.append("%s : le visage suivi ne fait que %d px de haut, sans doute un passant du fond. "
                        "Refaites avec une autre place (par exemple « 2e plus grand visage »)." % (nom, taille))
        elif part < 50:
            dits.append("%s : visage trouvé sur %d %% des images seulement ; le reste est deviné." % (nom, part))
    return dits


def phrase_d_echec(stderr: str) -> str:
    s = stderr or ""
    for mot, phrase in (
            ("POIDS_ABSENTS", "Les poids de H3 ne sont pas sur le disque Modal : préparez d'abord H3."),
            ("DETECTEUR_ABSENT", "Le détecteur de visages n'a pas pu être posé sur le disque Modal."),
            ("NOEUD_ABSENT", "Ce ComfyUI n'a pas les nœuds de FaceRefine."),
            ("GRAPHE_REFUSE", "ComfyUI a refusé le graphe avant tout calcul. Le détail est dans le journal."),
            ("COMFY_ARRETE", "ComfyUI s'est arrêté pendant le calcul (mémoire ?). Le détail est dans le journal."),
            ("CALCUL_ECHOUE", "Les visages n'ont pas pu être refaits. Le détail est dans le journal."),
            ("MONTAGE_ECHOUE", "Le passage à traiter n'a pas pu être découpé."),
            ("DELAI", "Le traitement n'était pas fini avant le délai. Rien n'a été rendu.")):
        if mot in s:
            return phrase
    return ""


# --- Le script envoyé sur la machine louée -----------------------------------------

_SCRIPT = r'''
# Visages refaits du Free AI Studio : lance ComfyUI (GPL-3.0) avec FaceRefine (MIT) et
# ultralytics (AGPL-3.0), et lui envoie un graphe par HTTP. Rien n'en est importé ici.
import base64, json, os, shutil, subprocess, sys, time, urllib.error, urllib.request
from pathlib import Path

D = json.loads(base64.b64decode("__DEMANDE_B64__").decode())
OUT = Path(os.environ.get("FREE_AI_OUTPUT_DIR", "/tmp/free_ai_output"))
OUT.mkdir(parents=True, exist_ok=True)
BASE, COMFY, DET = Path(D["base_poids"]), Path(D["comfy"]), D["detecteur"]
t0, pic = time.time(), 0.0

manque = [f for f in D["fichiers"] if not (BASE / f).is_file()]
if manque:
    print("POIDS_ABSENTS " + ", ".join(manque), file=sys.stderr)
    sys.exit(3)
poids = Path(DET["dossier"]) / DET["nom"]
if not poids.is_file() or poids.stat().st_size != DET["octets"]:
    try:
        from huggingface_hub import hf_hub_download
        hf_hub_download(DET["depot"], DET["nom"], revision=DET["revision"], local_dir=DET["dossier"])
        subprocess.run(["sync"], check=False)
    except Exception as exc:
        print("DETECTEUR_ABSENT " + repr(exc)[:500], file=sys.stderr)
        sys.exit(3)
    if not poids.is_file() or poids.stat().st_size != DET["octets"]:
        print("DETECTEUR_ABSENT taille inattendue", file=sys.stderr)
        sys.exit(3)
bbox = COMFY / "models" / "ultralytics" / "bbox"
bbox.mkdir(parents=True, exist_ok=True)
shutil.copyfile(poids, bbox / DET["nom"])

Path("/tmp/chemins.yaml").write_text(
    "h3:\n  base_path: " + str(BASE) + "\n  diffusion_models: diffusion_models\n"
    "  text_encoders: text_encoders\n  vae: vae\n  loras: loras\n")
entree = COMFY / "input"
entree.mkdir(exist_ok=True)
for nom, b64 in D["images"].items():
    (entree / nom).write_bytes(base64.b64decode(b64))
film = Path("/tmp/film.mp4")
film.write_bytes(base64.b64decode(D["video"]))
ips, de, a = D["images_par_seconde"], D["de"], D["a"]
for k, P in enumerate(D["passages"]):
    # Le passage déjà sur la grille H3 (P["ordre"] : lui, puis son miroir), sinon FaceRefine
    # le complète avec l'image de référence et les visages de la fin tournent en bouillie.
    brut, rang = Path("/tmp/brut_%d" % k), Path("/tmp/rang_%d" % k)
    brut.mkdir()
    rang.mkdir()
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(film), "-vf",
                        "select='between(n\\,%d\\,%d)',setpts=N/FRAME_RATE/TB" % (P["de"], P["a"] - 1),
                        "-vsync", "0", str(brut / "%05d.png")], capture_output=True, text=True)
    images = sorted(brut.glob("*.png"))
    if r.returncode or len(images) != P["a"] - P["de"]:
        print("MONTAGE_ECHOUE %d images sur %d. %s" % (len(images), P["a"] - P["de"], r.stderr[-1500:]),
              file=sys.stderr)
        sys.exit(9)
    for j, i in enumerate(P["ordre"]):
        os.link(images[i], rang / ("%05d.png" % j))
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(ips), "-i", str(rang / "%05d.png"),
                        "-i", str(film), "-map", "0:v", "-map", "1:a", "-af",
                        "atrim=start=%.4f:end=%.4f,asetpts=PTS-STARTPTS,apad=whole_dur=%.4f"
                        % (P["de"] / ips, P["a"] / ips, len(P["ordre"]) / ips),
                        "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p", "-c:a", "aac",
                        "-frames:v", str(len(P["ordre"])), str(entree / P["source"])], capture_output=True, text=True)
    if r.returncode:
        print("MONTAGE_ECHOUE " + r.stderr[-1500:], file=sys.stderr)
        sys.exit(9)

journal = open("/tmp/comfy.log", "w")
proc = subprocess.Popen(
    [sys.executable, "main.py", "--listen", "127.0.0.1", "--port", "8188", "--disable-pinned-memory",
     "--extra-model-paths-config", "/tmp/chemins.yaml", "--output-directory", "/tmp/sortie"],
    cwd=str(COMFY), stdout=journal, stderr=subprocess.STDOUT)
URL = "http://127.0.0.1:8188"


def lire(chemin):
    with urllib.request.urlopen(URL + chemin, timeout=30) as r:
        return json.loads(r.read())


def echouer(code, mot, detail=""):
    journal.flush()
    print(mot + " " + str(detail)[:3000], file=sys.stderr)
    print("--- journal ComfyUI ---\n" + Path("/tmp/comfy.log").read_text(errors="replace")[-6000:], file=sys.stderr)
    proc.kill()
    sys.exit(code)


def vram():
    try:
        return int(subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                                  capture_output=True, text=True, timeout=5).stdout.split()[0]) / 1024
    except Exception:
        return 0.0


for _ in range(300):
    try:
        lire("/system_stats")
        break
    except Exception:
        if proc.poll() is not None:
            echouer(7, "COMFY_ARRETE", "au démarrage")
        time.sleep(1)
else:
    echouer(7, "COMFY_ARRETE", "pas de réponse en 300 s")
t_pret = time.time()
info = lire("/object_info")
absents = [x for x in D["classes"] if x not in info]
if absents:
    echouer(4, "NOEUD_ABSENT", absents)

limite, rendus, calculs = t0 + D["delai_s"] - 60, [], []
for k, P in enumerate(D["passages"]):
    debut_passage = time.time()
    corps = json.dumps({"prompt": P["graphe"], "client_id": "free-ai-studio"}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(URL + "/prompt", data=corps,
                                    headers={"Content-Type": "application/json"}), timeout=60) as r:
            rep = json.loads(r.read())
    except urllib.error.HTTPError as e:
        echouer(5, "GRAPHE_REFUSE", e.read().decode(errors="replace"))
    if rep.get("node_errors") or "prompt_id" not in rep:
        echouer(5, "GRAPHE_REFUSE", json.dumps(rep))
    pid, etat = rep["prompt_id"], None
    while time.time() < limite:
        h = lire("/history/" + pid)
        if pid in h:
            etat = h[pid]
            break
        if proc.poll() is not None:
            echouer(7, "COMFY_ARRETE", "pendant le passage %d" % (k + 1))
        pic = max(pic, vram())
        time.sleep(2)
    if etat is None:
        echouer(8, "DELAI", "%d s, au passage %d" % (D["delai_s"], k + 1))
    if etat.get("status", {}).get("status_str") != "success":
        echouer(6, "CALCUL_ECHOUE", json.dumps(etat.get("status", {}).get("messages", []))[-3000:])
    dossier, _, debut_nom = ("/tmp/sortie/" + P["prefixe"]).rpartition("/")
    trouves = sorted(Path(dossier).glob(debut_nom + "*"))
    if not trouves:
        echouer(6, "CALCUL_ECHOUE", "aucun fichier rendu au passage %d" % (k + 1))
    rendus.append(trouves[-1])
    calculs.append(round(time.time() - debut_passage, 1))
    print("passage %d/%d : %.1f s" % (k + 1, len(D["passages"]), calculs[-1]), flush=True)
calcul_s = round(time.time() - t_pret, 1)
journal.flush()
rapports = [l for l in Path("/tmp/comfy.log").read_text(errors="replace").splitlines() if "[H3FaceRefine]" in l]
proc.kill()
# Chaque passage recoupé à ses [de, a) (le miroir ajouté pour la grille part), puis bout à
# bout. Le son est pris dans le FILM, pas dans ce que rend ComfyUI : le 30/09, un des sept
# passages est revenu sans piste son alors que sa source en avait une, et le bout à bout
# a échoué après tout le calcul.
sans_son = [k + 1 for k, x in enumerate(rendus) if not subprocess.run(
    ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", str(x)],
    capture_output=True, text=True).stdout.strip()]
if sans_son:
    print("rendus sans son (le son du film est reposé) : passages %s" % sans_son, flush=True)
n = len(rendus)
entrees = sum((["-i", str(x)] for x in rendus), []) + ["-i", str(film)]
filtre = "[%d:a]asplit=%d%s;" % (n, n, "".join("[s%d]" % i for i in range(n))) if n > 1 else "[%d:a]anull[s0];" % n
filtre += "".join("[%d:v]trim=end_frame=%d,setpts=PTS-STARTPTS[v%d];[s%d]atrim=start=%.4f:end=%.4f,"
                  "asetpts=PTS-STARTPTS[a%d];" % (i, P["a"] - P["de"], i, i, P["de"] / ips, P["a"] / ips, i)
                  for i, P in enumerate(D["passages"]))
filtre += "".join("[v%d][a%d]" % (i, i) for i in range(n)) + "concat=n=%d:v=1:a=1[v][a]" % n
r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *entrees, "-filter_complex", filtre,
                    "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", str(OUT / "video.mp4")], capture_output=True, text=True)
if r.returncode:
    print("MONTAGE_ECHOUE " + r.stderr[-1500:], file=sys.stderr)
    sys.exit(9)
resume = {"de": de, "a": a, "passages": [[P["de"], P["a"]] for P in D["passages"]], "calcul_s": calcul_s,
          "calcul_par_passage_s": calculs, "demarrage_comfy_s": round(t_pret - t0, 1),
          "total_s": round(time.time() - t0, 1), "pic_vram_go": round(pic, 1), "sans_son": sans_son,
          "rapports": rapports[-200:]}
(OUT / "resume.json").write_text(json.dumps(resume, ensure_ascii=False))
print("VISAGES " + json.dumps(resume, ensure_ascii=False), flush=True)
'''
