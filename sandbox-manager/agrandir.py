"""Agrandir un clip ou un film du Studio, visages compris : SeedVR2 (ByteDance,
Apache-2.0), par les nœuds d'origine de ComfyUI (comfy_extras/nodes_seedvr.py,
présents dans la version épinglée pour H3).

Demande du propriétaire, 29/09/2026 : « regarde les améliorations 4k et fait les
essais sur la vidéo… pour traiter les visages aussi », puis le 30/09 « visage
improvement in studio too ? » — « oui ajoute ». Essai du 29/09 hors du Studio, sur
un plan de la gare (832×480, 121 images), A100-80GB : ×2 en 119 s de calcul, 4K
(3744×2160) en 579 s ; cheveux, barbe, yeux et dents plus nets, mêmes visages.
Topaz Iris a été écarté : payant, sans Linux ni ligne de commande.

Le film est découpé en morceaux (aux fins de plans quand on les connaît) : un film
de 20 s en 4K, gardé entier, occuperait ~95 Go de mémoire vive en images flottantes.
Chaque morceau passe dans ComfyUI, puis les morceaux sont recollés et le son
d'origine reposé. Les poids (3,5 Go) sont posés sur le disque Modal de H3 au
premier agrandissement, et y restent.
"""
import base64
import math

import budget_modal
import video_h3

HF = "Comfy-Org/SeedVR2"
HF_REVISION = "df48879708206a403d2a61acd55578c2e80fd233"   # relevée le 30/09/2026
UNET = "seedvr2_3b_int8_convrot.safetensors"   # celui du modèle officiel de ComfyUI
VAE = "seedvr2_ema_vae_fp16.safetensors"
FICHIERS = ("diffusion_models/" + UNET, "vae/" + VAE)
DOSSIER_POIDS = video_h3.POINT_DE_MONTAGE + "/seedvr2"

# La machine de l'essai du 29/09. La 4K n'a été essayée que sur 80 Go.
GPU = "A100-80GB"
MEMOIRE_MB = 65536
COEURS = 4.0
DUREE_MAX_S = 3600
PAQUETS = ("huggingface_hub==1.9.2",)

# Secondes de calcul par image, mesurées le 29/09 (121 images, chargement du modèle
# compris) ; et ce qui précède le calcul : machine, ComfyUI, poids (davantage la
# première fois, quand les 3,5 Go se téléchargent).
ECHELLES = {
    "x2": {"titre": "×2 (960p)", "redim": {"resize_type": "scale by multiplier", "resize_type.multiplier": 2.0},
           "decoupe": False, "s_par_image": 118.7 / 121},
    "4k": {"titre": "4K (2160p)", "redim": {"resize_type": "scale height", "resize_type.height": 2160},
           "decoupe": True, "s_par_image": 578.9 / 121},
}
# Chez Modal aussi, la 4K par FlashVSR (07/10, voir FLASHVSR_MODAL) : SeedVR2 4K vieillissait les visages. EN
# ATTENTE (propriétaire, 07/10 : « hold modal works ») : éteint, jamais lancé chez Modal. NON MESURÉ sur L40S :
# la 4090 du 03/10 (160,8 s pour 120 images) avec un quart de marge, davantage au départ (image, poids).
FLASHVSR_CHEZ_MODAL = False
if FLASHVSR_CHEZ_MODAL:
    ECHELLES["4k"].update(s_par_image=160.8 / 120 * 1.25, demarrage_s=240, modele="FlashVSR v1.1")
DEMARRAGE_S = 150
# Un morceau au plus de cette longueur : celle de l'essai (121 images, 12 Go de
# mémoire vive pour les images de sortie en 4K).
MORCEAU_MAX = 125
VIDEO_MAX_OCTETS = 60 * 1024 * 1024

# Ici, sur la carte de cet ordinateur : FlashVSR v1.1 Tiny, plus SeedVR2 (03/10/2026, demande
# du propriétaire). SeedVR2 4K vieillissait les visages des films du Studio (rides inventées,
# peau dure : ses auteurs le disent trop fort sur la vidéo IA propre) et coûtait 6,4 s l'image
# sur la 4090 (01/10). FlashVSR, même plan (fin du 6b, 120 images 960x548 -> 3840x2176), sur
# la 4090 : 160,8 s de calcul, pic 14,7 Go, visage gardé jeune. Morceaux de 32 images au plus
# (demande du propriétaire, 03/10) : le film 4 en morceaux de 128 a fait tuer le conteneur à
# 28 Go et laissé 0,6 Go de mémoire virtuelle à Windows ; en 32, 41 morceaux de 33 à 37 s,
# pic carte 18,5 Go, 7,5 Go de mémoire virtuelle libres au plus bas.
# Chez Modal, l'agrandissement reste SeedVR2 (rien d'essayé là-bas avec FlashVSR Tiny).
MORCEAU_MAX_MAISON = 32
S_PAR_IMAGE_MAISON = 160.8 / 120
# Un morceau qui continue un plan reçoit les images d'avant en amorce (jetées ensuite) :
# FlashVSR lit le film en flux, son début de morceau n'a pas d'images passées.
AMORCE_MAISON = 8
FLASHVSR = {"depot": "JunhaoZhuang/FlashVSR-v1.1", "revision": "27561b186ded3402d7c975f4fd722e2885b6135f",
            "fichiers": ("diffusion_pytorch_model_streaming_dmd.safetensors", "LQ_proj_in.ckpt", "TCDecoder.ckpt"),
            "wanvsr": "/opt/flashvsr/examples/WanVSR", "chemins": ["/opt/flashvsr-sm89", "/opt/flashvsr"]}
MOTEUR_MAISON = "FlashVSR v1.1"
# La même 4K chez Modal (07/10) : flashvsr-sm89-ops vise les cartes Ada (sm89), la 4090 d'ici et la L40S de
# Modal. Mémoire : le film réduit (1,6 Mo l'image) et un morceau de 32 images en 4K tiennent largement.
FLASHVSR_MODAL = {"gpu": "L40S", "memoire_mb": 32768, "coeurs": 4.0}
FLASHVSR_COMMIT = "cf910c61a60733e610e9c6e8b607f80c3a6c202b"   # ceux de comfy-maison/Dockerfile
SM89_COMMIT = "59c74311b715b0f038854365b799707636236e73"
APT_FLASHVSR = video_h3.APT + ("gcc", "libc6-dev")      # Triton compile ses noyaux au premier appel
COMMANDES_FLASHVSR = video_h3.COMMANDES + (
    "git clone https://github.com/OpenImagingLab/FlashVSR /opt/flashvsr"
    f" && git -C /opt/flashvsr checkout {FLASHVSR_COMMIT}"
    " && git clone https://github.com/aireet/flashvsr-sm89-ops /opt/flashvsr-sm89"
    f" && git -C /opt/flashvsr-sm89 checkout {SM89_COMMIT}"
    f" && ln -s {video_h3.POINT_DE_MONTAGE}/flashvsr/FlashVSR-v1.1 /opt/flashvsr/examples/WanVSR/FlashVSR-v1.1",
    "pip install --no-deps imageio==2.37.0 imageio-ffmpeg==0.6.0 opencv-python-headless==4.11.0.86 ftfy==6.3.1"
    " peft==0.16.0 wcwidth==0.9.1",
)
# SeedVR2 perd des images d'un morceau qui n'en a pas un multiple de 4 (01/10 : 31 images
# rendues 30, et le film recollé passé à 24,8 images par seconde) ; 124 et 724 ont été
# rendues entières. Le script complète chaque morceau jusqu'au multiple de 4 en répétant
# sa dernière image, puis retire ces images du rendu.
MULTIPLE = 4


def bornes(total: int, fins=None, morceau_max: int = MORCEAU_MAX) -> list:
    """Les coupes du film, en images : aux fins de plans données, puis chaque
    morceau trop long partagé en parts égales. [0, …, total]."""
    points = sorted({int(f) for f in (fins or []) if 0 < int(f) < total}) + [total]
    sortie, debut = [0], 0
    for fin in points:
        n = -(-(fin - debut) // morceau_max)
        sortie += [debut + round((fin - debut) * k / n) for k in range(1, n + 1)]
        debut = fin
    return sortie


def estimation_s(images: int, echelle: str) -> float:
    e = ECHELLES[echelle]
    return e.get("demarrage_s", DEMARRAGE_S) + images * e["s_par_image"]


def machine(echelle: str) -> dict:
    """La machine louée pour cette échelle : FlashVSR (4K) sur L40S, SeedVR2 (×2) sur A100-80GB."""
    if echelle == "4k" and FLASHVSR_CHEZ_MODAL:
        return dict(FLASHVSR_MODAL)
    return {"gpu": GPU, "memoire_mb": MEMOIRE_MB, "coeurs": COEURS}


def image(echelle: str) -> dict:
    """De quoi construire l'image Modal de cette échelle (arguments de modal_execute)."""
    if echelle == "4k" and FLASHVSR_CHEZ_MODAL:
        return {"apt": APT_FLASHVSR, "commandes": COMMANDES_FLASHVSR, "paquets": PAQUETS}
    return {"apt": video_h3.APT, "commandes": video_h3.COMMANDES, "paquets": PAQUETS}


def modele(echelle: str) -> str:
    return ECHELLES[echelle].get("modele", "SeedVR2")


def estimation_maison_s(images: int) -> float:
    """La 4K sur la carte d'ici : poids déjà sur le disque, chargés en ~15 s ; plus
    l'amorce d'un morceau sur deux et l'encodage."""
    return 60 + images * S_PAR_IMAGE_MAISON * 1.1


def delai_s(images: int, echelle: str) -> int:
    """Le garde-fou dur de la machine : l'estimation avec une marge d'une moitié."""
    return min(DUREE_MAX_S, int(estimation_s(images, echelle) * 1.5) + 120)


def prix(images: int, echelle: str) -> dict:
    """Ce que la page affiche AVANT de payer ; ValueError si c'est trop long."""
    if echelle not in ECHELLES:
        raise ValueError("Agrandissement non proposé.")
    if images <= 0:
        raise ValueError("Vidéo vide.")
    estime = estimation_s(images, echelle)
    if estime > DUREE_MAX_S * 0.8:
        raise ValueError("Trop long pour %s en une fois (%d s de calcul estimées, %d au plus) : "
                         "choisissez ×2." % (ECHELLES[echelle]["titre"], estime, int(DUREE_MAX_S * 0.8)))
    m = machine(echelle)
    par_s = budget_modal.prix_seconde(m["gpu"], m["memoire_mb"], m["coeurs"])
    return {"echelle": echelle, "titre": ECHELLES[echelle]["titre"], "images": images,
            "secondes_estimees": round(estime), "estime_usd": round(par_s * estime, 2),
            "pire_usd": round(par_s * delai_s(images, echelle), 2), "delai_s": delai_s(images, echelle)}


def graphe(fichier: str, echelle: str, prefixe: str) -> dict:
    """Le modèle officiel de ComfyUI « utility_seedvr2_3b_int8_upscale_video », en format API."""
    e = ECHELLES[echelle]
    g = {
        "1": {"class_type": "LoadVideo", "inputs": {"file": fichier}},
        "2": {"class_type": "GetVideoComponents", "inputs": {"video": ["1", 0]}},
        "3": {"class_type": "ResizeImageMaskNode", "inputs": dict({"input": ["2", 0], "scale_method": "lanczos"},
                                                                 **e["redim"])},
        "4": {"class_type": "SeedVR2Preprocess", "inputs": {"resized_images": ["3", 0]}},
        "5": {"class_type": "VAELoader", "inputs": {"vae_name": VAE}},
        "6": {"class_type": "UNETLoader", "inputs": {"unet_name": UNET, "weight_dtype": "default"}},
        "7": {"class_type": "VAEEncodeTiled", "inputs": {"pixels": ["4", 0], "vae": ["5", 0], "tile_size": 512,
                                                         "overlap": 128, "temporal_size": 64, "temporal_overlap": 8}},
    }
    latent = ["7", 0]
    if e["decoupe"]:
        g["8"] = {"class_type": "SeedVR2TemporalChunk", "inputs": {"latent": latent, "temporal_overlap": 0,
                                                                   "chunking_mode": "auto"}}
        latent = ["8", 0]
    g["9"] = {"class_type": "SeedVR2Conditioning", "inputs": {"model": ["6", 0], "vae_conditioning": latent}}
    g["10"] = {"class_type": "KSampler", "inputs": {"model": ["6", 0], "positive": ["9", 0], "negative": ["9", 1],
                                                    "latent_image": latent, "seed": 42, "steps": 1, "cfg": 1.0,
                                                    "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}}
    sortie = ["10", 0]
    if e["decoupe"]:
        g["11"] = {"class_type": "SeedVR2TemporalMerge", "inputs": {"latents": ["10", 0],
                                                                    "temporal_overlap": ["8", 1]}}
        sortie = ["11", 0]
    g["12"] = {"class_type": "VAEDecodeTiled", "inputs": {"samples": sortie, "vae": ["5", 0], "tile_size": 512,
                                                          "overlap": 128, "temporal_size": 64, "temporal_overlap": 8}}
    # « lab » : les couleurs de l'original gardées, comme à l'essai.
    g["13"] = {"class_type": "SeedVR2PostProcessing", "inputs": {"images": ["12", 0],
                                                                 "original_resized_images": ["3", 0],
                                                                 "color_correction_method": "lab"}}
    g["14"] = {"class_type": "CreateVideo", "inputs": {"images": ["13", 0], "fps": ["2", 2], "audio": ["2", 1]}}
    g["15"] = {"class_type": "SaveVideo", "inputs": {"video": ["14", 0], "filename_prefix": prefixe,
                                                     "format": "auto", "format.codec": "auto"}}
    return g


CLASSES = ("LoadVideo", "GetVideoComponents", "ResizeImageMaskNode", "SeedVR2Preprocess", "VAELoader",
           "UNETLoader", "VAEEncodeTiled", "SeedVR2TemporalChunk", "SeedVR2Conditioning", "KSampler",
           "SeedVR2TemporalMerge", "VAEDecodeTiled", "SeedVR2PostProcessing", "CreateVideo", "SaveVideo")


def demande(video: bytes, echelle: str, coupes: list, delai_s: int = DUREE_MAX_S) -> dict:
    if len(video) > VIDEO_MAX_OCTETS:
        raise ValueError("Vidéo trop lourde pour être agrandie ici.")
    n = len(coupes) - 1
    return {"video": base64.b64encode(video).decode(), "coupes": coupes,
            "images_par_seconde": video_h3.IMAGES_PAR_SECONDE, "multiple": MULTIPLE,
            "graphes": [graphe(f"morceau_{k}.mp4", echelle, f"agrandi/m{k:02d}") for k in range(n)],
            "classes": list(CLASSES), "comfy": video_h3.DOSSIER_COMFY, "base_poids": DOSSIER_POIDS,
            "depot": HF, "revision": HF_REVISION, "fichiers": list(FICHIERS),
            "delai_s": delai_s, "echelle": echelle}


def construire_script(video: bytes, echelle: str, coupes: list, delai_s: int = DUREE_MAX_S,
                      fins=None, taille=None) -> str:
    """Le script de la machine louée. En 4K : celui de la carte d'ici (FlashVSR), en morceaux de
    MORCEAU_MAX_MAISON, recoupés aux `fins` de plans (à défaut, aux coupes données), poids posés
    sur le disque Modal d'abord ; `taille` = (largeur, hauteur) du film."""
    if echelle == "4k" and FLASHVSR_CHEZ_MODAL:
        fins = list(coupes[1:]) if fins is None else list(fins)
        coupes = bornes(coupes[-1], fins, MORCEAU_MAX_MAISON)
        d = dict(demande_maison(video, coupes, fins, *taille, delai_s),
                 poser_hf=[{"depot": FLASHVSR["depot"], "revision": FLASHVSR["revision"],
                            "dossier": DOSSIER_MAISON, "fichiers": list(FLASHVSR["fichiers"])}])
        return video_h3._emballer(video_h3.avec_poids_hf(_SCRIPT_MAISON), d)
    return video_h3._emballer(_SCRIPT, demande(video, echelle, coupes, delai_s))


# Les poids lus par la carte d'ici : ceux de FlashVSR, dans le dossier des poids (/poids).
DOSSIER_MAISON = "flashvsr/FlashVSR-v1.1"
FICHIERS_MAISON = tuple(DOSSIER_MAISON + "/" + f for f in FLASHVSR["fichiers"])


def dimensions_maison(largeur: int, hauteur: int) -> dict:
    """La 4K d'ici : hauteur 2160, largeur du film gardée (paire). FlashVSR agrandit x4 sur
    un canevas multiple de 128 : l'entrée est réduite juste assez pour le couvrir, puis le
    canevas est ramené à 2160 de haut et rogné au centre. 1344x768 -> entrée 960x550,
    canevas 3840x2176, film 3780x2160 (l'essai du 03/10 : 960x548, même canevas)."""
    finale_l = int(round(2160 * largeur / hauteur / 2)) * 2
    tw, th = math.ceil(finale_l * 2176 / 2160 / 128) * 128, 2176
    k = max(tw / (4 * largeur), th / (4 * hauteur))
    return {"entree": [2 * math.ceil(largeur * k / 2 - 1e-6), 2 * math.ceil(hauteur * k / 2 - 1e-6)],
            "canevas": [tw, th], "finale": [finale_l, 2160]}


def demande_maison(video: bytes, coupes: list, fins: list, largeur: int, hauteur: int,
                   delai_s: int) -> dict:
    if len(video) > VIDEO_MAX_OCTETS:
        raise ValueError("Vidéo trop lourde pour être agrandie ici.")
    # Pas d'amorce à un changement de plan : les images d'avant sont un autre plan.
    plans = set(int(f) for f in fins or [])
    amorces = [0 if (k == 0 or c in plans) else min(AMORCE_MAISON, c - coupes[k - 1])
               for k, c in enumerate(coupes[:-1])]
    return {"video": base64.b64encode(video).decode(), "coupes": coupes, "amorces": amorces,
            "images_par_seconde": video_h3.IMAGES_PAR_SECONDE, "delai_s": delai_s, "echelle": "4k",
            "base_poids": video_h3.POINT_DE_MONTAGE, "fichiers": list(FICHIERS_MAISON),
            "wanvsr": FLASHVSR["wanvsr"], "chemins": FLASHVSR["chemins"],
            **dimensions_maison(largeur, hauteur)}


def construire_script_maison(video: bytes, coupes: list, fins: list, largeur: int, hauteur: int,
                             delai_s: int = DUREE_MAX_S) -> str:
    return video_h3._emballer(_SCRIPT_MAISON, demande_maison(video, coupes, fins, largeur, hauteur, delai_s))


def tient_maison(images: int) -> bool:
    """Une location d'ici tient dans le plafond de la machine de la carte, avec une marge."""
    return estimation_maison_s(images) <= video_h3.MAISON_DUREE_MAX_S * 0.8


def phrase_d_echec(stderr: str) -> str:
    s = stderr or ""
    for mot, phrase in (
            ("POIDS_ABSENTS", "Les poids de SeedVR2 n'ont pas pu être posés sur le disque Modal."),
            ("FLASHVSR_ABSENT", "La machine de la carte d'ici n'a pas FlashVSR ou ses poids : relancez "
                                "le Studio par demarrer.cmd (ou ./start.sh) pour la reconstruire."),
            ("MEMOIRE_CARTE", "La carte d'ici a manqué de mémoire pendant l'agrandissement (un autre "
                              "programme s'en sert ?). Le détail est dans le journal."),
            ("NOEUD_ABSENT", "Ce ComfyUI n'a pas les nœuds de SeedVR2."),
            ("GRAPHE_REFUSE", "ComfyUI a refusé le graphe avant tout calcul. Le détail est dans le journal."),
            ("COMFY_ARRETE", "ComfyUI s'est arrêté pendant le calcul (mémoire ?). Le détail est dans le journal."),
            ("CALCUL_ECHOUE", "Un morceau n'a pas pu être agrandi. Le détail est dans le journal."),
            ("MONTAGE_ECHOUE", "Les morceaux agrandis n'ont pas pu être recollés."),
            ("DELAI", "L'agrandissement n'était pas fini avant le délai. Rien n'a été rendu.")):
        if mot in s:
            return phrase
    return ""


# --- Le script envoyé sur la machine louée -----------------------------------------

_SCRIPT = r'''
# Agrandissement SeedVR2 du Free AI Studio : lance ComfyUI (service à part,
# GPL-3.0) et lui envoie un graphe par morceau. Rien de ComfyUI n'est importé ici.
import base64, json, os, subprocess, sys, time, urllib.error, urllib.request
from pathlib import Path

D = json.loads(base64.b64decode("__DEMANDE_B64__").decode())
OUT = Path(os.environ.get("FREE_AI_OUTPUT_DIR", "/tmp/free_ai_output"))
OUT.mkdir(parents=True, exist_ok=True)
BASE, COMFY = Path(D["base_poids"]), Path(D["comfy"])
t0, pic = time.time(), 0.0

# Les poids restent sur le disque Modal : téléchargés une seule fois.
manque = [f for f in D["fichiers"] if not (BASE / f).is_file()]
if manque:
    try:
        from huggingface_hub import hf_hub_download
        for f in manque:
            hf_hub_download(D["depot"], f, revision=D["revision"], local_dir=str(BASE))
        subprocess.run(["sync"], check=False)
    except Exception as exc:
        print("POIDS_ABSENTS " + repr(exc)[:500], file=sys.stderr)
        sys.exit(3)
poids_s = round(time.time() - t0, 1)

Path("/tmp/chemins.yaml").write_text("seedvr2:\n  base_path: " + str(BASE)
                                     + "\n  diffusion_models: diffusion_models\n  vae: vae\n")
entree = COMFY / "input"
entree.mkdir(exist_ok=True)
film = Path("/tmp/film.mp4")
film.write_bytes(base64.b64decode(D["video"]))
ips, c = D["images_par_seconde"], D["coupes"]
for k in range(len(c) - 1):
    # Coupe exacte à l'image, son compris (le graphe le garde ; le film le reprend à la fin),
    # complétée jusqu'au multiple de 4 par sa dernière image répétée (retirée au recollage).
    plus = -(c[k + 1] - c[k]) % D["multiple"]
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(film), "-vf",
                        "select='between(n\\,%d\\,%d)',setpts=N/FRAME_RATE/TB,tpad=stop_mode=clone:stop=%d"
                        % (c[k], c[k + 1] - 1, plus),
                        "-af", "aselect='between(t\\,%.4f\\,%.4f)',asetpts=N/SR/TB" % (c[k] / ips, c[k + 1] / ips),
                        "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p", "-c:a", "aac",
                        str(entree / ("morceau_%d.mp4" % k))], capture_output=True, text=True)
    if r.returncode:
        print("MONTAGE_ECHOUE découpe " + r.stderr[-1500:], file=sys.stderr)
        sys.exit(9)

journal = open("/tmp/comfy.log", "w")
proc = subprocess.Popen(
    [sys.executable, "main.py", "--listen", "127.0.0.1", "--port", "8188",
     "--extra-model-paths-config", "/tmp/chemins.yaml", "--output-directory", "/tmp/sortie"],
    cwd=str(COMFY), stdout=journal, stderr=subprocess.STDOUT)
URL = "http://127.0.0.1:8188"


def lire(chemin):
    with urllib.request.urlopen(URL + chemin, timeout=30) as r:
        return json.loads(r.read())


def echouer(code, mot, detail=""):
    journal.flush()
    print(mot + " " + str(detail)[:3000], file=sys.stderr)
    print("--- journal ComfyUI ---\n" + Path("/tmp/comfy.log").read_text(errors="replace")[-4000:], file=sys.stderr)
    proc.kill()
    sys.exit(code)


def vram():
    # À la carte : ComfyUI est un autre processus.
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
info = lire("/object_info")
absents = [x for x in D["classes"] if x not in info]
if absents:
    echouer(4, "NOEUD_ABSENT", absents)

calculs, limite = [], t0 + D["delai_s"] - 60
for k, g in enumerate(D["graphes"]):
    t = time.time()
    corps = json.dumps({"prompt": g, "client_id": "free-ai-studio"}).encode()
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
            echouer(7, "COMFY_ARRETE", "pendant le morceau %d" % (k + 1))
        pic = max(pic, vram())
        time.sleep(2)
    if etat is None:
        echouer(8, "DELAI", "au morceau %d" % (k + 1))
    if etat.get("status", {}).get("status_str") != "success":
        echouer(6, "CALCUL_ECHOUE", json.dumps(etat.get("status", {}).get("messages", []))[-3000:])
    calculs.append(round(time.time() - t, 1))
    print("morceau %d/%d : %.1f s" % (k + 1, len(D["graphes"]), calculs[-1]), flush=True)
proc.kill()

morceaux = []
for k in range(len(D["graphes"])):
    trouves = sorted(Path("/tmp/sortie/agrandi").glob("m%02d*" % k))
    if not trouves:
        echouer(6, "CALCUL_ECHOUE", "morceau %d sans fichier" % (k + 1))
    # Les images ajoutées au découpage retirées : le morceau rendu a ses images d'origine.
    juste = Path("/tmp/juste_%02d.mp4" % k)
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(trouves[-1]), "-map", "0:v",
                        "-frames:v", str(c[k + 1] - c[k]), "-c", "copy", str(juste)], capture_output=True, text=True)
    if r.returncode:
        print("MONTAGE_ECHOUE morceau %d : %s" % (k + 1, r.stderr[-1500:]), file=sys.stderr)
        sys.exit(9)
    morceaux.append(juste)
Path("/tmp/liste.txt").write_text("".join("file '%s'\n" % m for m in morceaux))
r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", "/tmp/liste.txt",
                    "-i", str(film), "-map", "0:v", "-map", "1:a?", "-c:v", "copy", "-c:a", "copy", "-shortest",
                    str(OUT / "video.mp4")], capture_output=True, text=True)
if r.returncode:
    print("MONTAGE_ECHOUE " + r.stderr[-1500:], file=sys.stderr)
    sys.exit(9)
resume = {"echelle": D["echelle"], "morceaux": len(morceaux), "calcul_s": round(sum(calculs), 1),
          "calcul_par_morceau_s": calculs, "poids_s": poids_s, "total_s": round(time.time() - t0, 1),
          "pic_vram_go": round(pic, 1)}
(OUT / "resume.json").write_text(json.dumps(resume))
print("AGRANDI " + json.dumps(resume), flush=True)
'''


# --- Le script de la carte d'ici : FlashVSR v1.1 Tiny (03/10/2026) -------------------

_SCRIPT_MAISON = r'''
# Agrandissement 4K du Free AI Studio sur la carte d'ici : FlashVSR v1.1 Tiny avec
# flashvsr-sm89-ops (Triton, FP8, rendu en tuiles à la mémoire libre), morceau par morceau.
# Le chemin du script officiel (infer_flashvsr_v1.1_tiny.py) : entrée réduite, bicubique x4,
# rognée au multiple de 128, 1 pas. Repris de l'essai du 03/10 sur la 4090.
import base64, importlib.util, json, os, subprocess, sys, time
from pathlib import Path

D = json.loads(base64.b64decode("__DEMANDE_B64__").decode())
OUT = Path(os.environ.get("FREE_AI_OUTPUT_DIR", "/tmp/free_ai_output"))
OUT.mkdir(parents=True, exist_ok=True)
# 03/10, film 4 sur la 4090 avec 15 Go déjà pris par un autre programme : mort au décodage
# (« 2,31 GiB reserved but unallocated », 960 Mio demandés). Avant le premier import de torch.
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
t0 = time.time()
limite = t0 + D["delai_s"] - 60
BASE = Path(D["base_poids"])
manque = [f for f in D["fichiers"] if not (BASE / f).is_file()]
manque += [c for c in D["chemins"] + [D["wanvsr"]] if not Path(c).is_dir()]
if manque:
    print("FLASHVSR_ABSENT " + ", ".join(manque), file=sys.stderr)
    sys.exit(3)
sys.path[:0] = D["chemins"] + [D["wanvsr"]]


def echouer(code, mot, detail=""):
    print(mot + " " + str(detail)[-3000:], file=sys.stderr)
    sys.exit(code)


(w_in, h_in), (tw, th), (wf, hf) = D["entree"], D["canevas"], D["finale"]
ips, c, amorces = D["images_par_seconde"], D["coupes"], D["amorces"]
film = Path("/tmp/film_fv.mp4")
film.write_bytes(base64.b64decode(D["video"]))
# Toutes les images, réduites, en mémoire (1,6 Mo l'image en 960x550).
r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(film), "-vf", "scale=%d:%d:flags=lanczos" % (w_in, h_in),
                    "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True)
if r.returncode:
    echouer(9, "MONTAGE_ECHOUE", r.stderr.decode(errors="replace"))

import numpy as np  # noqa: E402
import torch  # noqa: E402
from PIL import Image  # noqa: E402

tout = np.frombuffer(r.stdout, np.uint8).reshape(-1, h_in, w_in, 3)
if len(tout) < c[-1]:
    echouer(9, "MONTAGE_ECHOUE", "%d images lues, %d attendues" % (len(tout), c[-1]))
try:
    import flashvsr_sm89_ops  # avant diffsynth : le remplaçant Triton de block_sparse_attn
    from flashvsr_sm89_ops.tiling import auto_tile_limits, render_tiled
    os.chdir(D["wanvsr"])   # le script officiel lit ses poids et son invite en chemins relatifs
    spec = importlib.util.spec_from_file_location("flashvsr_tiny", "infer_flashvsr_v1.1_tiny.py")
    officiel = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(officiel)
    t = time.time()
    pipe = officiel.init_pipeline()
    ops = flashvsr_sm89_ops.enable(pipe)
except torch.cuda.OutOfMemoryError as exc:
    echouer(6, "MEMOIRE_CARTE au chargement", exc)
except Exception as exc:
    echouer(3, "FLASHVSR_ABSENT", repr(exc))
charge_s = round(time.time() - t, 1)
print("FlashVSR chargé en %.1f s (%s)" % (charge_s, flashvsr_sm89_ops.active_backend()), flush=True)

gauche, haut = (4 * w_in - tw) // 2, (4 * h_in - th) // 2
calculs, pic, morceaux = [], 0.0, []
for k in range(len(c) - 1):
    if time.time() > limite:
        echouer(8, "DELAI", "au morceau %d" % (k + 1))
    a, b = c[k], c[k + 1]
    d = a - amorces[k]
    n = b - d
    F = n + 4                       # le script officiel : 8n+1 images, la dernière répétée
    while (F - 1) % 8:
        F += 1
    cadres = []
    for i in list(range(d, b)) + [b - 1] * (F - n):
        up = Image.fromarray(tout[i]).resize((4 * w_in, 4 * h_in), Image.BICUBIC)
        x = torch.from_numpy(np.asarray(up.crop((gauche, haut, gauche + tw, haut + th)), np.uint8))
        cadres.append(x.to(torch.float32).div_(255.0).mul_(2.0).sub_(1.0).to(torch.bfloat16).permute(2, 0, 1))
    lq = torch.stack(cadres, 0).permute(1, 0, 2, 3).unsqueeze(0)
    del cadres
    seuil, cible = auto_tile_limits(num_frames=F)
    torch.cuda.reset_peak_memory_stats()
    t = time.time()
    try:
        v = render_tiled(pipe, lq, prompt="", negative_prompt="", cfg_scale=1.0, num_inference_steps=1, seed=0,
                         is_full_block=False, if_buffer=True, topk_ratio=2.0 * 768 * 1280 / (th * tw),
                         kv_ratio=3.0, local_range=11, color_fix=True, tile_threshold=seuil, tile_target=cible)
        torch.cuda.synchronize()
    except torch.cuda.OutOfMemoryError as exc:
        echouer(6, "MEMOIRE_CARTE morceau %d" % (k + 1), exc)
    calculs.append(round(time.time() - t, 1))
    pic = max(pic, torch.cuda.max_memory_reserved() / 2**30)
    del lq
    v = v[:, a - d:n].clamp_(-1, 1).add_(1.0).mul_(127.5).permute(1, 2, 3, 0).to(torch.uint8).cpu().numpy()
    m = Path("/tmp/fv_m%02d.mp4" % k)
    # Ramené à 2160 de haut et rogné au centre à la largeur du film.
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
                          "-s", "%dx%d" % (tw, th), "-r", str(ips), "-i", "-",
                          "-vf", "scale=-2:%d:flags=lanczos,crop=%d:%d" % (hf, wf, hf),
                          "-c:v", "libx264", "-preset", "medium", "-crf", "14", "-pix_fmt", "yuv420p", str(m)],
                         stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    for im in v:
        p.stdin.write(im.tobytes())
    p.stdin.close()
    err = p.stderr.read().decode(errors="replace")
    if p.wait() or len(v) != b - a:
        echouer(9, "MONTAGE_ECHOUE morceau %d" % (k + 1), err or "%d images rendues sur %d" % (len(v), b - a))
    del v
    torch.cuda.empty_cache()
    morceaux.append(m)
    print("morceau %d/%d : %.1f s" % (k + 1, len(c) - 1, calculs[-1]), flush=True)

Path("/tmp/liste_fv.txt").write_text("".join("file '%s'\n" % m for m in morceaux))
r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", "/tmp/liste_fv.txt",
                    "-i", str(film), "-map", "0:v", "-map", "1:a?", "-c:v", "copy", "-c:a", "copy", "-shortest",
                    str(OUT / "video.mp4")], capture_output=True, text=True)
if r.returncode:
    echouer(9, "MONTAGE_ECHOUE", r.stderr)
resume = {"echelle": D["echelle"], "modele": "FlashVSR v1.1 Tiny", "morceaux": len(morceaux),
          "calcul_s": round(sum(calculs), 1), "calcul_par_morceau_s": calculs, "poids_s": charge_s,
          "total_s": round(time.time() - t0, 1), "pic_vram_go": round(pic, 1), "ops": str(ops)[:300]}
(OUT / "resume.json").write_text(json.dumps(resume))
print("AGRANDI " + json.dumps(resume), flush=True)
'''
