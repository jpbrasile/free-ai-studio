"""La deuxième retouche des images de départ : Qwen-Image 2.1 (Alibaba, 20/09/2026, « Qwen Research
License », non commerciale — relu le 05/10 sur la carte du modèle ; Apache-2.0 est la gamme 20B d'avant),
par les nœuds d'origine de ComfyUI v0.37.0 (TextEncodeQwenImage21), sur la machine H3 de Modal.

Demande du propriétaire, 04/10/2026 : « ajoute Qwen comme deuxième retouche dans le studio ».
Essai du même jour hors du Studio (« Le robot perdu », maître f970b321), L40S, graphe du modèle
officiel « image_qwen_image_2_1_image_edit » : 186 s en tout, dont 82 s de poids posés sur le
disque et 17 à 32 s par image. Pixel refait d'après sa fiche aux plans 3, 4 et 7, à une taille
plus juste que l'image du Studio ; mais la capsule retirée au plan 3 et Leila recadrée : la
consigne dit donc aussi les objets, le cadrage et la pose (allongé, assis, debout).
"""
import base64
import re
import struct
import zlib

import video_h3

HF = "Comfy-Org/Qwen-Image-2.1"
HF_REVISION = "cb504a4090723e43f17ad01cec0359490e2de613"   # relevée le 04/10/2026
UNET = "qwen_image_2.1_int8_convrot.safetensors"
ENCODEUR = "qwen3vl_8b_int8_convrot.safetensors"
VAE = "qwen_image_2.1_vae_bf16.safetensors"
FICHIERS = ("diffusion_models/" + UNET, "text_encoders/" + ENCODEUR, "vae/" + VAE)
DOSSIER_POIDS = video_h3.POINT_DE_MONTAGE + "/qwen-image-21"

# La machine de l'essai du 04/10.
GPU = "L40S"
MEMOIRE_MB = 32768
COEURS = 4.0
# Machine, ComfyUI, poids (17 Go la première fois), modèles chargés, une image : 186 s à
# l'essai pour quatre images. Au-delà, la machine est arrêtée.
DUREE_MAX_S = 600
PAQUETS = video_h3.PAQUETS_POIDS
RESOLUTION = 1024    # celle du modèle officiel
GRAINE = 42
REFERENCES_MAX = 15  # TextEncodeQwenImage21 prend 16 images, la première est l'image à reprendre
CLASSES = ("UNETLoader", "CLIPLoader", "VAELoader", "LoadImage", "TextEncodeQwenImage21", "KSampler",
           "VAEDecode", "SaveImage")

GARDER = ("Keep everything else in <image1> exactly as it is: the framing and the camera, the place, the light, "
          "every object (nothing is added, moved or removed), and every character's place, size, pose (lying, "
          "sitting or standing), the side they face and the direction they look. ")


def consigne(personnages: list, a_eviter=(), etats: str = "") -> str:
    """`personnages` : [(nom, nombre de photos)] dans l'ordre des images jointes, qui suivent <image1>.
    `etats` : l'état de départ des éléments du plan (video_h3.etats_au_debut), suivi même contre <image1>."""
    phrases, n = [], 2
    for nom, k in personnages:
        images = " and ".join("<image%d>" % i for i in range(n, n + k))
        phrases.append("%s is the character of %s." % (nom, images))
        n += k
    texte = (" ".join(phrases) + " In <image1>, replace each of them who does not look like their pictures with "
             "the one of the pictures, whole: head, body, proportions, material, colours, face and clothes, at the "
             "same place and facing the same way, with ITS OWN size and shape from the pictures even if the old one "
             "was taller or shaped differently; nothing of the old one remains. " + GARDER)
    if etats:
        texte += ("At this instant each element is exactly in this state, even where <image1> shows it otherwise: "
                  + etats + " ")
    fautes = [" ".join(str(f or "").split()).rstrip(".") for f in a_eviter]
    fautes = [f for f in fautes if f]
    if fautes:
        texte += "A previous attempt had these faults, avoid them: " + "; ".join(fautes) + "."
    return texte


def graphe(base: str, refs: list, texte: str, graine: int = GRAINE) -> dict:
    """Le modèle officiel « image_qwen_image_2_1_image_edit » de ComfyUI v0.37.0, en format API."""
    g = {"1": {"class_type": "UNETLoader", "inputs": {"unet_name": UNET, "weight_dtype": "default"}},
         "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": ENCODEUR, "type": "qwen_image",
                                                     "device": "default"}},
         "3": {"class_type": "VAELoader", "inputs": {"vae_name": VAE}},
         "10": {"class_type": "LoadImage", "inputs": {"image": base}}}
    enc = {"clip": ["2", 0], "prompt": texte, "negative_prompt": "", "vae": ["3", 0], "resolution": RESOLUTION,
           "images.image_1": ["10", 0]}
    for k, r in enumerate(refs, 2):
        g[str(9 + k)] = {"class_type": "LoadImage", "inputs": {"image": r}}
        enc["images.image_%d" % k] = [str(9 + k), 0]
    g["40"] = {"class_type": "TextEncodeQwenImage21", "inputs": enc}
    g["41"] = {"class_type": "KSampler", "inputs": {"model": ["1", 0], "seed": graine, "steps": 25, "cfg": 1.0,
                                                    "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0,
                                                    "positive": ["40", 0], "negative": ["40", 1],
                                                    "latent_image": ["40", 2]}}
    g["42"] = {"class_type": "VAEDecode", "inputs": {"samples": ["41", 0], "vae": ["3", 0]}}
    g["43"] = {"class_type": "SaveImage", "inputs": {"images": ["42", 0], "filename_prefix": "retouche"}}
    return g


def demande(image: bytes, refs: list, texte: str, graine: int = GRAINE) -> dict:
    """`refs` : les photos des fiches (octets), dans l'ordre que `consigne` a nommé."""
    if not refs:
        raise ValueError("Aucune photo de fiche pour la retouche Qwen.")
    refs = list(refs)[:REFERENCES_MAX]
    noms = ["ref_%02d.png" % k for k in range(len(refs))]
    return {"base": base64.b64encode(image).decode(),
            "refs": {n: base64.b64encode(r).decode() for n, r in zip(noms, refs)},
            "graphe": graphe("base.png", noms, texte, graine), "classes": list(CLASSES),
            "comfy": video_h3.DOSSIER_COMFY, "base_poids": DOSSIER_POIDS, "depot": HF, "revision": HF_REVISION,
            "fichiers": list(FICHIERS), "delai_s": DUREE_MAX_S}


def construire_script(image: bytes, refs: list, texte: str, graine: int = GRAINE) -> str:
    return video_h3._emballer(_SCRIPT, demande(image, refs, texte, graine))


# --- L'image de départ entière par Qwen (propriétaire, 05/10 : « qwen est meilleur pour le job ») ---
# Jalon 0 bis, clip 6 : même texte, mêmes photos, même plaque du lieu ; ArcFace contre la fiche 0,562
# (Qwen) contre 0,408 (Gemini du routeur). La demande du routeur (video_h3.demande_image) est reprise
# telle quelle : ses « image jointe N » deviennent des <imageN>. <image1> fixe la taille du latent
# (TextEncodeQwenImage21) : la plaque du lieu quand il y en a une, sinon une toile unie au format
# de l'image du Studio.
TOILE = ("<image1> is an empty canvas that only gives the size of the picture: paint a complete new photograph "
         "over the whole of it, nothing of the canvas remains. ")
_JOINTE = re.compile(r"(l'|L')?(images?) jointes? (\d+)(?: à (\d+))?")


def _png_uni(largeur: int, hauteur: int, gris: int = 24) -> bytes:
    """Une toile PNG unie, sans dépendance (le gestionnaire n'a pas PIL)."""
    def bloc(genre, donnees):
        return (struct.pack(">I", len(donnees)) + genre + donnees
                + struct.pack(">I", zlib.crc32(genre + donnees) & 0xFFFFFFFF))
    ligne = b"\x00" + bytes([gris]) * (3 * largeur)
    return (b"\x89PNG\r\n\x1a\n" + bloc(b"IHDR", struct.pack(">IIBBBBB", largeur, hauteur, 8, 2, 0, 0, 0))
            + bloc(b"IDAT", zlib.compress(ligne * hauteur, 9)) + bloc(b"IEND", b""))


def depuis_demande_image(demande: dict, lieu=None) -> tuple:
    """(image1, références, texte) pour Qwen depuis la demande du routeur. `lieu` : le rang (1…) de la
    plaque du lieu parmi les images jointes, qui passe alors en <image1>."""
    photos = [base64.b64decode(str(u).split(",", 1)[1]) for u in demande.get("image_reference") or []]
    if lieu and not 1 <= int(lieu) <= len(photos):
        raise ValueError("Plaque du lieu introuvable parmi les images jointes.")
    if lieu:
        base, refs = photos[lieu - 1], photos[:lieu - 1] + photos[lieu:]
        rang = lambda i: 1 if i == lieu else (i + 1 if i < lieu else i)  # noqa: E731
        tete = ""
    else:
        largeur, hauteur = (int(x) for x in str(video_h3.TAILLE_IMAGE_DEMANDEE).split("x"))
        base, refs, rang, tete = _png_uni(largeur, hauteur), photos, (lambda i: i + 1), TOILE
    if len(refs) > REFERENCES_MAX:
        raise ValueError("Trop de photos pour Qwen (%d au plus)." % REFERENCES_MAX)

    def nommer(m):
        debut = "<image%d>" % rang(int(m.group(3)))
        return debut + (" à <image%d>" % rang(int(m.group(4))) if m.group(4) else "")
    return base, refs, tete + _JOINTE.sub(nommer, str(demande.get("prompt") or ""))


def phrase_d_echec(stderr: str) -> str:
    s = stderr or ""
    for mot, phrase in (
            ("POIDS_ABSENTS", "Les poids de Qwen-Image 2.1 n'ont pas pu être posés sur le disque Modal."),
            ("NOEUD_ABSENT", "Ce ComfyUI n'a pas les nœuds de Qwen-Image 2.1."),
            ("GRAPHE_REFUSE", "ComfyUI a refusé le graphe de la retouche Qwen."),
            ("COMFY_ARRETE", "ComfyUI s'est arrêté pendant la retouche Qwen (mémoire ?)."),
            ("CALCUL_ECHOUE", "La retouche Qwen n'a pas pu être dessinée."),
            ("DELAI", "La retouche Qwen n'était pas finie avant le délai.")):
        if mot in s:
            return phrase
    return ""


# --- Le script envoyé sur la machine louée -----------------------------------------

_SCRIPT = r'''
# Retouche Qwen-Image 2.1 du Free AI Studio : lance ComfyUI (service à part, GPL-3.0) et lui
# envoie un graphe. Rien de ComfyUI n'est importé ici.
import base64, json, os, subprocess, sys, time, urllib.error, urllib.request
from pathlib import Path

D = json.loads(base64.b64decode("__DEMANDE_B64__").decode())
OUT = Path(os.environ.get("FREE_AI_OUTPUT_DIR", "/tmp/free_ai_output"))
OUT.mkdir(parents=True, exist_ok=True)
BASE, COMFY = Path(D["base_poids"]), Path(D["comfy"])
t0 = time.time()

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

Path("/tmp/chemins.yaml").write_text("qwen:\n  base_path: " + str(BASE) + "\n  diffusion_models: "
                                     "diffusion_models\n  text_encoders: text_encoders\n  vae: vae\n")
entree = COMFY / "input"
entree.mkdir(exist_ok=True)
(entree / "base.png").write_bytes(base64.b64decode(D["base"]))
for nom, b64 in D["refs"].items():
    (entree / nom).write_bytes(base64.b64decode(b64))

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

t = time.time()
corps = json.dumps({"prompt": D["graphe"], "client_id": "free-ai-studio"}).encode()
try:
    with urllib.request.urlopen(urllib.request.Request(URL + "/prompt", data=corps,
                                headers={"Content-Type": "application/json"}), timeout=60) as r:
        rep = json.loads(r.read())
except urllib.error.HTTPError as e:
    echouer(5, "GRAPHE_REFUSE", e.read().decode(errors="replace"))
if rep.get("node_errors") or "prompt_id" not in rep:
    echouer(5, "GRAPHE_REFUSE", json.dumps(rep))
pid, etat, limite = rep["prompt_id"], None, t0 + D["delai_s"] - 30
while time.time() < limite:
    h = lire("/history/" + pid)
    if pid in h:
        etat = h[pid]
        break
    if proc.poll() is not None:
        echouer(7, "COMFY_ARRETE", "pendant le dessin")
    time.sleep(1)
if etat is None:
    echouer(8, "DELAI", "")
if etat.get("status", {}).get("status_str") != "success":
    echouer(6, "CALCUL_ECHOUE", json.dumps(etat.get("status", {}).get("messages", []))[-3000:])
images = etat.get("outputs", {}).get("43", {}).get("images", [])
if not images:
    echouer(6, "CALCUL_ECHOUE", "aucune image rendue")
proc.kill()
png = Path("/tmp/sortie", images[0].get("subfolder", ""), images[0]["filename"]).read_bytes()
(OUT / "retouche.png").write_bytes(png)
resume = {"poids_s": poids_s, "dessin_s": round(time.time() - t, 1), "total_s": round(time.time() - t0, 1)}
print("RETOUCHE " + json.dumps(resume), flush=True)
'''
