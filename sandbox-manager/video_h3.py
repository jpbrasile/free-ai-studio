"""Vidéo H3 : MiniMax H3 par ComfyUI, sur une machine louée chez Modal.

Décision du propriétaire, 27/09/2026 (« go H3, budget 2 $ ») ; découpage au
point 18.9 de PLAN.md, page décrite au point 18.7.

POURQUOI CE MODULE NE TOUCHE PAS À COMFYUI. ComfyUI est sous GPL-3.0 et le
Studio sous MIT. Rien ici n'importe ComfyUI : le script envoyé sur la machine
louée clone ComfyUI dans l'image Modal, le lance comme un service à part, et
lui parle par HTTP (/object_info, /prompt, /history). Le graphe est un
dictionnaire JSON fabriqué ici. Même règle que pour Piper (PLAN.md:803).

CE QUI A TOURNÉ, ET SEULEMENT CELA (27/09/2026, A100 40 Go, 832x480, 124
images, LoRA Turbo 4 étapes, hors du Studio, en fonction Modal) :
  - texte seul : 48,1 s de calcul, 72,4 s en tout ;
  - première image : 26,4 s de calcul ;
  - première et dernière, et références : 111 s de calcul pour les deux.
Les quatre modes sont donc proposés. Aucune autre taille, aucune autre durée
n'a tourné : la page le dit à côté de chaque durée.

LICENCE. Les poids de MiniMax H3 excluent par défaut l'UE, le Royaume-Uni et la
Corée. Chaque Studio doit porter la copie de SA propre autorisation écrite de
MiniMax (PLAN.md, 18.0) : sans elle, /video-h3/creer refuse avant de louer.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import random
import time
from typing import Optional

import budget_modal

# --- Moteur et poids ------------------------------------------------------------

COMFY_DEPOT = "https://github.com/Comfy-Org/ComfyUI"
COMFY_VERSION = "v0.37.0"   # dernière publiée au 27/09/2026 ; celle des essais
DOSSIER_COMFY = "/comfy"
HF = "Comfy-Org/MiniMax-H3"
HF_REVISION = "bf92c4091e333e69b8ca1998e0a669f15cb0832b"   # relevée le 27/09/2026
FICHIERS = (
    "diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors",
    # INT8 et pas NVFP4 : l'A100 est une Ampere.
    "text_encoders/qwen3vl_32b_minimax_h3_int8_convrot.safetensors",
    "vae/minimax_h3_video_vae_int8_convrot.safetensors",
    "vae/minimax_h3_audio_vae_fp32.safetensors",
    "loras/minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors",
)
POIDS_GO = 52   # total téléchargé le 27/09/2026 (essai hors du Studio)

# Le disque Modal où les poids restent d'un clip à l'autre. Un disque à part
# de celui de la vidéo « Rapide » : 52 Go qu'on veut pouvoir effacer seuls.
VOLUME = os.getenv("H3_MODAL_VOLUME", "free-ai-studio-h3")
POINT_DE_MONTAGE = "/poids"

# La machine des essais du 27/09. « A100 » est le nom que Modal facture au
# tarif de la table (budget_modal.PRIX_GPU_USD_S) ; « A100-40GB » y serait une
# carte inconnue, comptée au prix de la plus chère.
GPU = os.getenv("H3_GPU", "A100")
# Pic mesuré le 27/09 : 56,7 Gio de mémoire vive avec --disable-pinned-memory ;
# les deux modes du même jour ont réussi avec 48 Gio demandés. Modal traite la
# demande comme un minimum, pas comme une limite.
MEMOIRE_MB = int(os.getenv("H3_MEMOIRE_MB", "49152"))
COEURS = float(os.getenv("H3_COEURS", "4"))
# Garde-fou dur : au-delà, la machine est arrêtée. Le pire cas du compteur se
# calcule sur ce délai.
DUREE_MAX_S = int(os.getenv("H3_TIMEOUT_SECONDS", "900"))
APT = ("git", "ffmpeg")
COMMANDES = (
    f"git clone --depth 1 --branch {COMFY_VERSION} {COMFY_DEPOT} {DOSSIER_COMFY}",
    f"pip install -r {DOSSIER_COMFY}/requirements.txt psutil",
)
PAQUETS_POIDS = ("huggingface_hub==1.9.2",)

# --- Ce que la page propose ------------------------------------------------------

LARGEUR, HAUTEUR, IMAGES_PAR_SECONDE = 832, 480, 24
# Grille du modèle : 17k+5 images à 24 images/s. 124 = 5,2 s ; le modèle a été
# entraîné de 124 à 362 (15,1 s) ; au-delà, « non essayé » selon ComfyUI.
LONGUEURS = tuple(124 + 17 * k for k in range(15))
LONGUEUR_PAR_DEFAUT = 124

MODES = {
    "texte": {"titre": "Texte seul", "noeud": "MiniMaxH3ImageToVideo", "images_min": 0,
              "images_max": 0, "essaye_le": "2026-09-27",
              "note": "Le début du clip peut être déformé : donner une première image l'évite."},
    "premiere": {"titre": "Première image", "noeud": "MiniMaxH3ImageToVideo", "images_min": 1,
                 "images_max": 1, "essaye_le": "2026-09-27",
                 "note": "Le clip part exactement de votre image."},
    "premiere_derniere": {"titre": "Première et dernière image", "noeud": "MiniMaxH3ImageToVideo",
                          "images_min": 2, "images_max": 2, "essaye_le": "2026-09-27",
                          "note": "Le clip part de la première image et finit sur la seconde."},
    "references": {"titre": "Références (garder un personnage)", "noeud": "MiniMaxH3ReferenceToVideo",
                   "images_min": 1, "images_max": 9, "essaye_le": "2026-09-27",
                   "note": "Une nouvelle scène avec le même personnage. Essayé avec une seule "
                           "image de référence ; jusqu'à 9 acceptées par le modèle."},
}
COUPES = (0.0, 0.25, 0.5)   # secondes retirées au début, par ffmpeg
IMAGE_MAX_OCTETS = 8 * 1024 * 1024
IMAGES_MAX_OCTETS = 24 * 1024 * 1024

# Temps de location MESURÉ, par longueur : le clip texte seul du 27/09, démarrage
# de ComfyUI compris (72,4 s). Une seule longueur a été chronométrée ; les
# autres n'ont pas d'estimation, seulement le pire cas.
SECONDES_MESUREES = {124: 72.4}
MESURE_LE = "2026-09-27"


def secondes_de(longueur: int) -> float:
    return round(longueur / IMAGES_PAR_SECONDE, 2)


def prix_estime(longueur: int) -> Optional[float]:
    """Le temps mesuré au tarif du bac à sable ; None si jamais mesuré."""
    s = SECONDES_MESUREES.get(int(longueur))
    if s is None:
        return None
    return round(budget_modal.prix_seconde(GPU, MEMOIRE_MB, COEURS) * s, 4)


def pire_cas() -> float:
    """Le clip qui va jusqu'au bout de son délai sans rien rendre."""
    return round(budget_modal.prix_seconde(GPU, MEMOIRE_MB, COEURS) * DUREE_MAX_S, 3)


def durees() -> list:
    return [{"images": n, "secondes": secondes_de(n), "prix_estime_usd": prix_estime(n)}
            for n in LONGUEURS]


# --- L'invite en trois cases -----------------------------------------------------

def invite(image_paroles: str, ambiance: str = "", musique: str = "") -> str:
    """Une seule invite pour le modèle, à partir des trois cases de la page.

    H3 fabrique l'image ET le son à partir du même texte : la case « image et
    paroles » décrit ce qu'on voit et ce qui est dit (les paroles entre
    guillemets), les deux autres le reste de la bande son.
    """
    morceaux = []
    for texte, prefixe in ((image_paroles, ""), (ambiance, "Sound: "), (musique, "Music: ")):
        t = " ".join(str(texte or "").split())
        if t:
            if t[-1] not in ".!?\"»":
                t += "."
            morceaux.append(prefixe + t)
    return " ".join(morceaux)


# --- Le graphe ComfyUI -------------------------------------------------------------

def _n(classe: str, entrees: dict) -> dict:
    return {"class_type": classe, "inputs": entrees}


def noms_images(mode: str, nombre: int) -> list:
    if mode == "premiere":
        return ["premiere.png"]
    if mode == "premiere_derniere":
        return ["premiere.png", "derniere.png"]
    if mode == "references":
        return [f"ref_{i}.png" for i in range(nombre)]
    return []


def graphe(mode: str, texte: str, longueur: int, graine: int, nb_images: int = 0) -> dict:
    """Le graphe des essais du 27/09, pour un clip.

    Chargeurs, LoRA Turbo 4 étapes, échantillonneur `res_multistep`, ordonnanceur
    `simple`, puis image et son décodés et réunis en un MP4.
    """
    nom = lambda chemin: chemin.split("/")[1]  # noqa: E731
    g = {
        "1": _n("UNETLoader", {"unet_name": nom(FICHIERS[0]), "weight_dtype": "default"}),
        "2": _n("LoraLoaderModelOnly", {"model": ["1", 0], "lora_name": nom(FICHIERS[4]),
                                         "strength_model": 1.0}),
        "3": _n("CLIPLoader", {"clip_name": nom(FICHIERS[1]), "type": "minimax"}),
        "4": _n("VAELoader", {"vae_name": nom(FICHIERS[2])}),
        "5": _n("VAELoader", {"vae_name": nom(FICHIERS[3])}),
        "8": _n("KSamplerSelect", {"sampler_name": "res_multistep"}),
        "9": _n("BasicScheduler", {"model": ["2", 0], "scheduler": "simple", "steps": 4, "denoise": 1.0}),
    }
    taille = {"width": LARGEUR, "height": HAUTEUR, "length": int(longueur)}
    images = noms_images(mode, nb_images)
    for i, fichier in enumerate(images):
        g[f"6{i}"] = _n("LoadImage", {"image": fichier})
    if mode == "references":
        entrees = {"clip": ["3", 0], "vae": ["4", 0], "audio_vae": ["5", 0], "prompt": texte,
                   "ref_image_size": "match", **taille}
        for i in range(len(images)):
            entrees[f"ref_images.ref_image_{i}"] = [f"6{i}", 0]
        g["10"] = _n("MiniMaxH3ReferenceToVideo", entrees)
    else:
        entrees = {"clip": ["3", 0], "vae": ["4", 0], "prompt": texte, **taille}
        if images:
            entrees["first_frame"] = ["60", 0]
        if len(images) == 2:
            entrees["last_frame"] = ["61", 0]
        g["10"] = _n("MiniMaxH3ImageToVideo", entrees)
    g["12"] = _n("RandomNoise", {"noise_seed": int(graine)})
    g["13"] = _n("BasicGuider", {"model": ["2", 0], "conditioning": ["10", 0]})
    g["14"] = _n("SamplerCustomAdvanced", {"noise": ["12", 0], "guider": ["13", 0], "sampler": ["8", 0],
                                            "sigmas": ["9", 0], "latent_image": ["10", 1]})
    g["15"] = _n("VAEDecode", {"samples": ["14", 0], "vae": ["4", 0]})
    g["16"] = _n("VAEDecodeAudio", {"samples": ["14", 0], "vae": ["5", 0]})
    g["17"] = _n("CreateVideo", {"images": ["15", 0], "audio": ["16", 0], "fps": IMAGES_PAR_SECONDE})
    g["18"] = _n("SaveVideo", {"video": ["17", 0], "filename_prefix": "h3/clip",
                               "format": "auto", "format.codec": "auto"})
    return g


# --- La demande ------------------------------------------------------------------

def _image(b64: str, quoi: str) -> str:
    """Contrôle une image venue de la page (base64, sans l'en-tête data:)."""
    b64 = str(b64 or "")
    if "," in b64[:100] and b64.startswith("data:"):
        b64 = b64.split(",", 1)[1]
    try:
        octets = base64.b64decode(b64, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{quoi} : fichier illisible.") from exc
    if not octets:
        raise ValueError(f"{quoi} : fichier vide.")
    if len(octets) > IMAGE_MAX_OCTETS:
        raise ValueError(f"{quoi} : plus de 8 Mo, réduisez l'image.")
    if not (octets[:8] == b"\x89PNG\r\n\x1a\n" or octets[:3] == b"\xff\xd8\xff"
            or (octets[:4] == b"RIFF" and octets[8:12] == b"WEBP")):
        raise ValueError(f"{quoi} : seules les images PNG, JPEG et WebP sont acceptées.")
    return base64.b64encode(octets).decode()


def preparer(payload: dict, graine_hasard=None) -> dict:
    """Vérifie la demande de la page et fabrique ce qui part sur la machine.

    Rend {"demande", "resume_public"} ou lève ValueError avec une phrase pour
    la page. Rien n'est loué ici.
    """
    mode = str(payload.get("mode") or "texte")
    if mode not in MODES:
        raise ValueError("Mode inconnu.")
    texte = invite(payload.get("image_paroles", ""), payload.get("ambiance", ""),
                   payload.get("musique", ""))
    if not texte:
        raise ValueError("Décrivez au moins ce qu'on voit (première case).")
    if len(texte) > 4000:
        raise ValueError("Invite trop longue (4 000 caractères au plus).")
    try:
        longueur = int(payload.get("longueur") or LONGUEUR_PAR_DEFAUT)
    except (TypeError, ValueError) as exc:
        raise ValueError("Durée illisible.") from exc
    if longueur not in LONGUEURS:
        raise ValueError("Durée hors de la grille du modèle.")
    try:
        coupe = float(payload.get("coupe_s") or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("Coupe du début illisible.") from exc
    if coupe not in COUPES:
        raise ValueError("Coupe du début non proposée.")
    graine = payload.get("graine")
    if graine in (None, ""):
        graine = (graine_hasard or random.randint)(0, 2**31 - 1)
    try:
        graine = int(graine)
    except (TypeError, ValueError) as exc:
        raise ValueError("Graine illisible : un nombre entier.") from exc
    if not 0 <= graine < 2**63:
        raise ValueError("Graine hors bornes.")

    brutes = payload.get("images") or []
    if not isinstance(brutes, list):
        raise ValueError("Images illisibles.")
    m = MODES[mode]
    if not m["images_min"] <= len(brutes) <= m["images_max"]:
        if m["images_max"] == 0:
            raise ValueError("Le mode « Texte seul » ne prend pas d'image.")
        if m["images_min"] == m["images_max"]:
            raise ValueError(f"Le mode « {m['titre']} » demande {m['images_min']} image(s).")
        raise ValueError(f"Le mode « {m['titre']} » demande de {m['images_min']} à "
                         f"{m['images_max']} images.")
    noms = noms_images(mode, len(brutes))
    images = {nom: _image(b, f"Image {i + 1}") for i, (nom, b) in enumerate(zip(noms, brutes))}
    if sum(len(v) * 3 // 4 for v in images.values()) > IMAGES_MAX_OCTETS:
        raise ValueError("Images trop lourdes ensemble (24 Mo au plus).")

    demande = {
        "mode": mode,
        "graphe": graphe(mode, texte, longueur, graine, len(brutes)),
        "classes": [m["noeud"]],
        "images": images,
        "fichiers": list(FICHIERS),
        "base_poids": POINT_DE_MONTAGE,
        "comfy": DOSSIER_COMFY,
        "comfy_version": COMFY_VERSION,
        "coupe_s": coupe,
        "delai_s": max(60, DUREE_MAX_S - 120),
        "longueur": longueur,
        "graine": graine,
    }
    return {
        "demande": demande,
        "resume_public": {
            "moteur": "MiniMax H3 (ComfyUI " + COMFY_VERSION + ")",
            "mode": mode,
            "mode_titre": m["titre"],
            "invite": texte,
            "images": longueur,
            "secondes": secondes_de(longueur),
            "coupe_s": coupe,
            "graine": graine,
            "taille": f"{LARGEUR}x{HAUTEUR}",
            "carte": GPU,
            "prix_estime_usd": prix_estime(longueur),
            "cout_max_usd": pire_cas(),
        },
    }


# --- La garde de licence ---------------------------------------------------------

DOSSIER_AUTORISATION = budget_modal.CONFIG_DIR / "h3-autorisation"
FICHE_AUTORISATION = DOSSIER_AUTORISATION / "fiche.json"
AUTORISATION_MAX_OCTETS = 10 * 1024 * 1024
TYPES_AUTORISATION = {b"\x89PNG": ".png", b"\xff\xd8\xff": ".jpg", b"%PDF": ".pdf"}


def autorisation_etat() -> dict:
    """La copie de l'autorisation MiniMax de CE Studio, sans son contenu."""
    try:
        fiche = json.loads(FICHE_AUTORISATION.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"presente": False}
    copie = DOSSIER_AUTORISATION / str(fiche.get("fichier", ""))
    if not copie.is_file() or copie.is_symlink():
        return {"presente": False}
    return {"presente": True, "date_autorisation": fiche.get("date_autorisation", ""),
            "deposee_le": fiche.get("deposee_le", ""), "octets": fiche.get("octets", 0),
            "empreinte": fiche.get("empreinte", "")}


def autorisation_poser(b64: str, date_autorisation: str) -> dict:
    """Range la copie déposée par le client. Elle ne quitte jamais cette machine."""
    date_autorisation = str(date_autorisation or "").strip()
    if not (len(date_autorisation) == 10 and date_autorisation[4] == "-" and date_autorisation[7] == "-"
            and date_autorisation.replace("-", "").isdigit()):
        raise ValueError("Date de l'autorisation illisible (jour/mois/année).")
    b64 = str(b64 or "")
    if b64.startswith("data:") and "," in b64[:100]:
        b64 = b64.split(",", 1)[1]
    try:
        octets = base64.b64decode(b64, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("Copie illisible.") from exc
    if not octets or len(octets) > AUTORISATION_MAX_OCTETS:
        raise ValueError("Copie vide ou de plus de 10 Mo.")
    ext = next((e for debut, e in TYPES_AUTORISATION.items() if octets.startswith(debut)), None)
    if not ext:
        raise ValueError("La copie doit être une image PNG, JPEG, ou un PDF.")
    DOSSIER_AUTORISATION.mkdir(parents=True, exist_ok=True)
    for ancien in DOSSIER_AUTORISATION.glob("copie.*"):
        ancien.unlink()
    (DOSSIER_AUTORISATION / ("copie" + ext)).write_bytes(octets)
    FICHE_AUTORISATION.write_text(json.dumps({
        "fichier": "copie" + ext,
        "date_autorisation": date_autorisation,
        "deposee_le": time.strftime("%Y-%m-%d %H:%M:%S"),  # date-machine
        "octets": len(octets),
        "empreinte": hashlib.sha256(octets).hexdigest()[:16],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return autorisation_etat()


# --- Les poids, préparés une fois --------------------------------------------------

FICHE_POIDS = budget_modal.CONFIG_DIR / "h3-poids.json"


def poids_etat() -> dict:
    try:
        fiche = json.loads(FICHE_POIDS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"prets": False, "volume": VOLUME}
    fiche["volume"] = VOLUME
    fiche["prets"] = bool(fiche.get("prets")) and fiche.get("revision") == HF_REVISION
    return fiche


def poids_noter(prets: bool, detail: str = "") -> dict:
    FICHE_POIDS.parent.mkdir(parents=True, exist_ok=True)
    FICHE_POIDS.write_text(json.dumps({
        "prets": bool(prets), "revision": HF_REVISION, "volume": VOLUME,
        "le": time.strftime("%Y-%m-%d %H:%M:%S"),  # date-machine
        "detail": detail[:500]}, ensure_ascii=False, indent=2), encoding="utf-8")
    return poids_etat()


# --- Messages d'échec --------------------------------------------------------------

def phrase_d_echec(stderr: str) -> str:
    s = str(stderr or "")
    if "POIDS_ABSENTS" in s:
        return ("Les poids de H3 ne sont pas sur le disque Modal « " + VOLUME + " ». "
                "Cliquez « Préparer les poids » (une fois), puis relancez.")
    if "NOEUD_ABSENT" in s:
        return ("Ce ComfyUI n'a pas le nœud de ce mode : le mode n'est pas proposé tant "
                "que la version épinglée ne l'a pas.")
    if "GRAPHE_REFUSE" in s:
        return "ComfyUI a refusé le graphe avant tout calcul. Le détail est dans le journal."
    if "COMFY_ARRETE" in s:
        return "ComfyUI s'est arrêté pendant le calcul (mémoire ?). Le détail est dans le journal."
    if "DELAI" in s:
        return "Le clip n'était pas fini avant le délai. Rien n'a été rendu."
    return ""


# --- Les scripts envoyés sur la machine louée ---------------------------------------

_SCRIPT = r'''
# Vidéo H3 du Free AI Studio : lance ComfyUI (service à part, GPL-3.0) et lui
# envoie un graphe par HTTP. Rien de ComfyUI n'est importé ici.
import base64, json, os, shutil, subprocess, sys, time, urllib.error, urllib.request
from pathlib import Path

D = json.loads(base64.b64decode("__DEMANDE_B64__").decode())
OUT = Path(os.environ.get("FREE_AI_OUTPUT_DIR", "/tmp/free_ai_output"))
OUT.mkdir(parents=True, exist_ok=True)
BASE = Path(D["base_poids"])
COMFY = Path(D["comfy"])
t0 = time.time()

manque = [f for f in D["fichiers"] if not (BASE / f).is_file()]
if manque:
    print("POIDS_ABSENTS " + ", ".join(manque), file=sys.stderr)
    sys.exit(3)

Path("/tmp/chemins.yaml").write_text(
    "h3:\n  base_path: " + str(BASE) + "\n  diffusion_models: diffusion_models\n"
    "  text_encoders: text_encoders\n  vae: vae\n  loras: loras\n")
(COMFY / "input").mkdir(exist_ok=True)
for nom, b64 in D["images"].items():
    (COMFY / "input" / nom).write_bytes(base64.b64decode(b64))

journal = open("/tmp/comfy.log", "w")
proc = subprocess.Popen(
    [sys.executable, "main.py", "--listen", "127.0.0.1", "--port", "8188", "--disable-pinned-memory",
     "--extra-model-paths-config", "/tmp/chemins.yaml", "--output-directory", "/tmp/sortie"],
    cwd=str(COMFY), stdout=journal, stderr=subprocess.STDOUT)
BASE_URL = "http://127.0.0.1:8188"


def lire(chemin):
    with urllib.request.urlopen(BASE_URL + chemin, timeout=30) as r:
        return json.loads(r.read())


def fin_du_journal():
    journal.flush()
    return Path("/tmp/comfy.log").read_text(errors="replace")[-4000:]


def echouer(code, mot, detail=""):
    print(mot + " " + str(detail)[:3000], file=sys.stderr)
    print("--- journal ComfyUI ---\n" + fin_du_journal(), file=sys.stderr)
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
t_pret = time.time()

info = lire("/object_info")
absents = [c for c in D["classes"] if c not in info]
if absents:
    echouer(4, "NOEUD_ABSENT", absents)

corps = json.dumps({"prompt": D["graphe"], "client_id": "free-ai-studio"}).encode()
req = urllib.request.Request(BASE_URL + "/prompt", data=corps, headers={"Content-Type": "application/json"})
try:
    with urllib.request.urlopen(req, timeout=60) as r:
        rep = json.loads(r.read())
except urllib.error.HTTPError as e:
    echouer(5, "GRAPHE_REFUSE", e.read().decode(errors="replace"))
if rep.get("node_errors") or "prompt_id" not in rep:
    echouer(5, "GRAPHE_REFUSE", json.dumps(rep))

pid, etat, limite = rep["prompt_id"], None, time.time() + D["delai_s"]
while time.time() < limite:
    h = lire("/history/" + pid)
    if pid in h:
        etat = h[pid]
        break
    if proc.poll() is not None:
        echouer(7, "COMFY_ARRETE", "pendant le calcul")
    time.sleep(2)
if etat is None:
    echouer(8, "DELAI", "%d s" % D["delai_s"])
statut = etat.get("status", {}).get("status_str")
if statut != "success":
    echouer(6, "CALCUL_ECHOUE", json.dumps(etat.get("status", {}).get("messages", []))[-3000:])
calcul_s = round(time.time() - t_pret, 1)

clips = sorted(Path("/tmp/sortie/h3").glob("clip_*"))
if not clips:
    echouer(6, "CALCUL_ECHOUE", "aucun fichier rendu")
if D["coupe_s"] > 0:
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(D["coupe_s"]), "-i", str(clips[-1]),
                        "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac",
                        str(OUT / "video.mp4")], capture_output=True, text=True)
    if r.returncode:
        echouer(9, "COUPE_ECHOUEE", r.stderr)
else:
    shutil.copyfile(clips[-1], OUT / "video.mp4")
proc.kill()
(OUT / "resume.json").write_text(json.dumps({
    "moteur": "MiniMax H3, ComfyUI " + D["comfy_version"], "mode": D["mode"],
    "images": D["longueur"], "graine": D["graine"], "coupe_s": D["coupe_s"],
    "demarrage_comfy_s": round(t_pret - t0, 1), "calcul_s": calcul_s,
    "total_s": round(time.time() - t0, 1)}, ensure_ascii=False))
print("ok", calcul_s, "s de calcul")
'''

_SCRIPT_POIDS = r'''
# Poids de MiniMax H3 (Comfy-Org, révision épinglée) vers le disque Modal.
# Sur processeur : aucune carte n'est louée pendant le téléchargement.
import base64, json, os, subprocess, sys, time
from pathlib import Path
from huggingface_hub import hf_hub_download

D = json.loads(base64.b64decode("__DEMANDE_B64__").decode())
OUT = Path(os.environ.get("FREE_AI_OUTPUT_DIR", "/tmp/free_ai_output"))
OUT.mkdir(parents=True, exist_ok=True)
t0 = time.time()
tailles = {}
for f in D["fichiers"]:
    p = hf_hub_download(D["depot"], f, revision=D["revision"], local_dir=D["base_poids"])
    tailles[f] = os.path.getsize(p)
    print("ok %6.2f Gio  %s  (%d s)" % (tailles[f] / 2**30, f, time.time() - t0), flush=True)
subprocess.run(["sync"], check=False)
(OUT / "poids.json").write_text(json.dumps({"secondes": round(time.time() - t0, 1),
                                           "gio": round(sum(tailles.values()) / 2**30, 2)}))
'''


def _emballer(gabarit: str, demande: dict) -> str:
    b64 = base64.b64encode(json.dumps(demande, ensure_ascii=False).encode()).decode()
    return gabarit.replace("__DEMANDE_B64__", b64)


def construire_script(demande: dict) -> str:
    return _emballer(_SCRIPT, demande)


def construire_script_poids() -> str:
    return _emballer(_SCRIPT_POIDS, {"fichiers": list(FICHIERS), "depot": HF, "revision": HF_REVISION,
                                     "base_poids": POINT_DE_MONTAGE})


# Le téléchargement : 52 Go sur processeur. Délai large, carte aucune.
POIDS_DUREE_MAX_S = int(os.getenv("H3_POIDS_TIMEOUT_SECONDS", "3600"))
POIDS_MEMOIRE_MB = 4096
POIDS_COEURS = 2.0


def pire_cas_poids() -> float:
    return round(budget_modal.prix_seconde(None, POIDS_MEMOIRE_MB, POIDS_COEURS) * POIDS_DUREE_MAX_S, 3)


# --- La page -----------------------------------------------------------------------

PAGE_HTML = r"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Vidéo H3 — Free AI Studio</title>
<style>
  body { font-family: system-ui, sans-serif; max-width: 860px; margin: 0 auto; padding: 16px; background: #fafafa; color: #222; }
  h1 { font-size: 1.5rem; margin-bottom: 4px; }
  .bloc { background: #fff; border: 1px solid #ddd; border-radius: 8px; padding: 12px 14px; margin: 12px 0; }
  label { display: block; font-weight: 600; margin-top: 10px; }
  textarea, select, input[type=text], input[type=number], input[type=date] { width: 100%; box-sizing: border-box; font: inherit; padding: 6px; }
  textarea { min-height: 70px; }
  .note { color: #555; font-size: .92rem; }
  .avert { color: #8a4b00; }
  .refus { color: #a40000; font-weight: 600; }
  button { font: inherit; padding: 8px 16px; margin-top: 12px; cursor: pointer; }
  video { width: 100%; margin-top: 10px; background: #000; }
  pre { white-space: pre-wrap; font-size: .8rem; max-height: 240px; overflow: auto; background: #f3f3f3; padding: 8px; }
</style>
</head>
<body>
<h1>🎞️ Vidéo H3 <span class="note">expérimental</span></h1>
<p class="note">MiniMax H3 fabrique l'image <b>et</b> le son d'un clip, sur une machine louée chez Modal
(A100). Moteur : ComfyUI, lancé à part sur la machine louée.</p>

<div class="bloc" id="banniere">Lecture du budget…</div>

<div class="bloc" id="licence">
  <b>Licence de MiniMax H3.</b> Elle exclut par défaut l'Union européenne, le Royaume-Uni et la Corée :
  il faut l'autorisation écrite de MiniMax.
  <div id="licence_etat">Lecture…</div>
  <div id="licence_depot" hidden>
    <label for="licence_fichier">Copie de votre autorisation (image PNG ou JPEG, ou PDF)</label>
    <input type="file" id="licence_fichier" accept="image/png,image/jpeg,application/pdf">
    <label for="licence_date">Date de l'autorisation</label>
    <input type="date" id="licence_date">
    <button id="licence_envoyer">Enregistrer ma copie</button>
    <p class="note">La copie reste sur cet ordinateur (dossier de configuration du Studio). Elle ne part chez personne.</p>
  </div>
</div>

<div class="bloc" id="poids">
  <b>Poids du modèle.</b> <span id="poids_etat">Lecture…</span>
  <button id="poids_preparer" hidden>Préparer les poids</button>
</div>

<div class="bloc">
  <label for="mode">Mode</label>
  <select id="mode"></select>
  <p class="note" id="mode_note"></p>
  <div id="images_bloc" hidden>
    <label for="images" id="images_titre">Images</label>
    <input type="file" id="images" accept="image/png,image/jpeg,image/webp" multiple>
    <p class="note" id="images_note"></p>
  </div>

  <label for="image_paroles">1. Image et paroles</label>
  <textarea id="image_paroles" placeholder="Une femme en manteau rouge marche sous la pluie à Paris, la nuit ; elle se retourne et dit : « On y est presque. »"></textarea>
  <label for="ambiance">2. Ambiance sonore</label>
  <textarea id="ambiance" placeholder="Pluie, circulation au loin."></textarea>
  <label for="musique">3. Musique</label>
  <textarea id="musique" placeholder="(vide = pas de musique demandée)"></textarea>

  <label for="longueur">Durée</label>
  <select id="longueur"></select>
  <p class="note" id="prix"></p>

  <label for="coupe">Couper le début</label>
  <select id="coupe">
    <option value="0">Ne rien couper</option>
    <option value="0.25">0,25 s</option>
    <option value="0.5">0,5 s</option>
  </select>
  <label for="graine">Graine (vide = au hasard ; la même graine refait le même tirage)</label>
  <input type="number" id="graine" min="0" step="1">

  <button id="lancer">Fabriquer le clip</button>
  <p id="statut" class="note"></p>
  <div id="resultat" hidden>
    <video id="lecteur" controls playsinline></video>
    <p><a id="telecharger" href="#">Enregistrer le clip</a></p>
    <p class="note" id="fiche"></p>
  </div>
  <pre id="journal" hidden></pre>
</div>

<script>
const CLE = "__CLE__";
const H = {"Authorization": "Bearer " + CLE, "Content-Type": "application/json"};
let ETAT = null;

function lireFichier(f){
  return new Promise((ok, ko) => {
    const r = new FileReader();
    r.onload = () => ok(String(r.result));
    r.onerror = () => ko(r.error);
    r.readAsDataURL(f);
  });
}

function majMode(){
  const m = ETAT.modes[document.getElementById("mode").value];
  document.getElementById("mode_note").textContent = m.note + " Essayé le " + dateFr(m.essaye_le) + ".";
  const bloc = document.getElementById("images_bloc");
  bloc.hidden = m.images_max === 0;
  document.getElementById("images_note").textContent = m.images_min === m.images_max
    ? m.images_min + " image(s), dans l'ordre : première, puis dernière."
    : "De " + m.images_min + " à " + m.images_max + " images.";
}

function majPrix(){
  const n = Number(document.getElementById("longueur").value);
  const d = ETAT.durees.find(x => x.images === n);
  const pire = "Au pire (la machine va jusqu'au bout de son délai) : " + fr(ETAT.pire_cas_usd, 2) + " $.";
  document.getElementById("prix").textContent = (d && d.prix_estime_usd !== null)
    ? "Estimé : " + fr(d.prix_estime_usd, 3) + " $, d'après " + fr(ETAT.secondes_mesurees, 0)
      + " s de location mesurées le " + dateFr(ETAT.mesure_le) + " au tarif relevé chez Modal. " + pire
    : "Durée jamais essayée : pas d'estimation mesurée. " + pire;
}

function afficherLicence(a){
  const e = document.getElementById("licence_etat");
  document.getElementById("licence_depot").hidden = a.presente;
  e.className = a.presente ? "" : "refus";
  e.textContent = a.presente
    ? "Copie de l'autorisation déposée le " + dateFr(a.deposee_le) + " (autorisation du "
      + dateFr(a.date_autorisation) + "). Les clips sont permis."
    : "Aucune copie d'autorisation sur ce Studio : les clips sont refusés tant qu'elle n'est pas déposée.";
}

function afficherPoids(p){
  document.getElementById("poids_etat").textContent = p.prets
    ? "Prêts sur le disque Modal « " + p.volume + " » (depuis le " + dateFr(p.le) + ")."
    : "Pas encore sur le disque Modal « " + p.volume + " ». Une fois pour toutes : environ "
      + ETAT.poids_go + " Go, téléchargés sur processeur (sans carte). Au pire " + fr(ETAT.pire_cas_poids_usd, 2) + " $.";
  document.getElementById("poids_preparer").hidden = p.prets;
}

function rafraichir(){
  return fetch("/video-h3/etat", {headers: H}).then(r => r.json()).then(d => {
    ETAT = d;
    document.getElementById("banniere").textContent = "Budget Modal : " + fr(d.budget.usd, 2) + " $ dépensés sur "
      + fr(d.budget.plafond_usd, 2) + " $ ouverts aux demandes. " + renouvellementTexte(d.budget);
    const sm = document.getElementById("mode");
    if (!sm.options.length){
      for (const [k, m] of Object.entries(d.modes)){ sm.add(new Option(m.titre, k)); }
      const sl = document.getElementById("longueur");
      for (const x of d.durees){
        sl.add(new Option(fr(x.secondes, 1) + " s (" + x.images + " images)"
          + (x.prix_estime_usd !== null ? " — mesurée" : " — jamais essayée"), x.images));
      }
    }
    afficherLicence(d.autorisation);
    afficherPoids(d.poids);
    majMode();
    majPrix();
  });
}

function suivre(jid){
  fetch("/video/jobs/" + jid, {headers: H}).then(r => r.json()).then(j => {
    const st = document.getElementById("statut");
    if (j.status === "succeeded" && j.video_url){
      st.textContent = "Clip prêt.";
      document.getElementById("resultat").hidden = false;
      document.getElementById("lecteur").src = j.video_url;
      document.getElementById("telecharger").href = j.video_url + "&telecharger=1&nom=clip-h3";
      const r = j.resume || {};
      document.getElementById("fiche").textContent = "Graine " + r.graine + " ; " + fr(r.calcul_s, 0)
        + " s de calcul, " + fr(r.total_s, 0) + " s en tout.";
      rafraichir();
      return;
    }
    if (j.status === "failed"){
      st.className = "refus";
      st.textContent = "Échec : " + (j.message || "voir le journal.");
      const jr = document.getElementById("journal");
      jr.hidden = false;
      jr.textContent = (j.stderr || "") + "\n" + (j.stdout || "");
      rafraichir();
      return;
    }
    st.textContent = "En cours (" + j.status + ")… Le premier clip construit aussi la machine : plusieurs minutes.";
    setTimeout(() => suivre(jid), 4000);
  });
}

document.getElementById("mode").addEventListener("change", majMode);
document.getElementById("longueur").addEventListener("change", majPrix);

document.getElementById("licence_envoyer").addEventListener("click", async () => {
  const f = document.getElementById("licence_fichier").files[0];
  const date = document.getElementById("licence_date").value;
  if (!f || !date){ alerteTexte("Choisissez le fichier et la date."); return; }
  const r = await fetch("/video-h3/autorisation", {method: "POST", headers: H,
    body: JSON.stringify({copie: await lireFichier(f), date_autorisation: date})});
  const d = await r.json();
  if (!r.ok){ alerteTexte(d.detail || "Refusé."); return; }
  afficherLicence(d);
});

document.getElementById("poids_preparer").addEventListener("click", async () => {
  const r = await fetch("/video-h3/poids/preparer", {method: "POST", headers: H, body: "{}"});
  const d = await r.json();
  if (!r.ok){ alerteTexte(d.detail || "Refusé."); return; }
  document.getElementById("poids_etat").textContent = "Téléchargement lancé (plusieurs minutes)…";
  document.getElementById("poids_preparer").hidden = true;
  const attendre = () => fetch("/video/jobs/" + d.id, {headers: H}).then(x => x.json()).then(j => {
    if (j.status === "succeeded" || j.status === "failed"){ rafraichir(); return; }
    setTimeout(attendre, 10000);
  });
  attendre();
});

function alerteTexte(t){
  const st = document.getElementById("statut");
  st.className = "refus";
  st.textContent = t;
}

document.getElementById("lancer").addEventListener("click", async () => {
  const st = document.getElementById("statut");
  st.className = "note";
  document.getElementById("resultat").hidden = true;
  document.getElementById("journal").hidden = true;
  const m = document.getElementById("mode").value;
  const fichiers = ETAT.modes[m].images_max ? Array.from(document.getElementById("images").files) : [];
  const images = [];
  for (const f of fichiers){ images.push(await lireFichier(f)); }
  const graine = document.getElementById("graine").value;
  const r = await fetch("/video-h3/creer", {method: "POST", headers: H, body: JSON.stringify({
    mode: m, images: images,
    image_paroles: document.getElementById("image_paroles").value,
    ambiance: document.getElementById("ambiance").value,
    musique: document.getElementById("musique").value,
    longueur: Number(document.getElementById("longueur").value),
    coupe_s: Number(document.getElementById("coupe").value),
    graine: graine === "" ? null : Number(graine)})});
  const d = await r.json();
  if (!r.ok){ alerteTexte(typeof d.detail === "string" ? d.detail : "Refusé."); return; }
  st.textContent = "Lancé.";
  suivre(d.id);
});

rafraichir();
</script>
</body>
</html>
"""
