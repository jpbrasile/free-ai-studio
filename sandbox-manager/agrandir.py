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
DEMARRAGE_S = 150
# Un morceau au plus de cette longueur : celle de l'essai (121 images, 12 Go de
# mémoire vive pour les images de sortie en 4K).
MORCEAU_MAX = 125
VIDEO_MAX_OCTETS = 60 * 1024 * 1024

# Ici, sur la carte de cet ordinateur (01/10, mesuré sur la 4090, WSL à 48 Go) : un plan
# 768p de 124 images d'un seul morceau a tué ComfyUI au décodage (46 438 Mio de mémoire
# vive sur 47 Go) ; en 4 morceaux de 31 images, 28 180 Mio au plus, 15 365 Mio de carte,
# 796,4 s de calcul. Le gestionnaire coupe donc en morceaux de 32 images au plus.
MORCEAU_MAX_MAISON = 32
S_PAR_IMAGE_MAISON = 796.4 / 124
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
    return DEMARRAGE_S + images * ECHELLES[echelle]["s_par_image"]


def estimation_maison_s(images: int) -> float:
    """La 4K sur la carte d'ici : poids déjà sur le disque, ComfyUI démarré en ~15 s."""
    return 30 + images * S_PAR_IMAGE_MAISON


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
    par_s = budget_modal.prix_seconde(GPU, MEMOIRE_MB, COEURS)
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


def construire_script(video: bytes, echelle: str, coupes: list, delai_s: int = DUREE_MAX_S) -> str:
    return video_h3._emballer(_SCRIPT, demande(video, echelle, coupes, delai_s))


# Les poids lus par la carte d'ici : le même dossier que le disque Modal (/poids/seedvr2).
FICHIERS_MAISON = tuple("seedvr2/" + f for f in FICHIERS)


def tient_maison(images: int) -> bool:
    """Une location d'ici tient dans le plafond de la machine de la carte, avec une marge."""
    return estimation_maison_s(images) <= video_h3.MAISON_DUREE_MAX_S * 0.8


def phrase_d_echec(stderr: str) -> str:
    s = stderr or ""
    for mot, phrase in (
            ("POIDS_ABSENTS", "Les poids de SeedVR2 n'ont pas pu être posés sur le disque Modal."),
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
