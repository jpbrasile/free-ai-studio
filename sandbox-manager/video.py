"""Fabrication de videos courtes, sur un GPU loue a la minute.

Pourquoi un fichier a part. La video est la seule fonction du Studio qui coute
vraiment de l'argent : une image se fabrique en deux secondes chez Google, une
video demande des minutes de carte graphique. Tout ce qui compte les secondes et
refuse de depasser est donc rassemble ici, lisible d'un coup d'oeil, plutot que
dispersé dans le gestionnaire de bacs a sable.

Un seul modele couvre les trois demandes du debutant, et c'est ce qui rend la
chose possible sans budget : Wan 2.1 VACE en 1,3 milliard de parametres (licence
Apache 2.0, environ 6 Go) sait a la fois partir d'une simple phrase, partir d'une
image, finir sur une autre image, et garder un personnage ressemblant a une image
de reference. Le meme code marche sur le grand modele 14B quand on a de quoi
payer : seul le nom du modele change.
"""

from __future__ import annotations

import base64
import json
import os
import threading
import time
from pathlib import Path
from typing import Dict

CONFIG_DIR = Path(os.getenv("FREE_AI_CONFIG_DIR", "/config"))
BUDGET_FICHIER = CONFIG_DIR / "video-budget.json"
_VERROU = threading.Lock()

# Prix Modal a la seconde, releves sur https://modal.com/pricing le 09/09/2026.
# Ils servent a COMPTER, pas a facturer : Modal facture, nous ne faisons
# qu'estimer pour pouvoir refuser avant de depasser. Un prix qui change chez
# Modal sans changer ici rend l'estimation fausse : c'est pourquoi la page
# affiche la date du releve.
PRIX_RELEVE_LE = "2026-09-09"
PRIX_GPU_USD_S: Dict[str, float] = {
    "T4": 0.000164,
    "L4": 0.000222,
    "A10G": 0.000306,
    "L40S": 0.000542,
    "A100": 0.000583,
    "A100-80GB": 0.000694,
    "H100": 0.001097,
}

# Modal affiche 30 $ de credit par mois pour son offre Starter (modal.com/pricing,
# releve du 11/09/2026). Il exige une carte bancaire, et au-dela du credit il
# facture jusqu'a la limite de depense du compte (modal.com/docs/guide/budgets).
# Le Studio ne lit PAS ce compte : CREDIT_OFFERT_USD est une declaration de
# l'utilisateur, affichee comme telle.
#
# Plafond par defaut : 20 $. Il reste sous les 30 $ et laisse 10 $ au reste du
# bac a sable, que ce compteur ne voit pas. Au prix du 09/09/2026, il paie
# environ 200 clips << Rapide >> de 3 s par mois (0,096 $ chacun, le dernier
# n'etant lance que si son pire cas, 0,53 $, tient encore).
BUDGET_MENSUEL_USD = float(os.getenv("VIDEO_BUDGET_USD_PAR_MOIS", "20"))
CREDIT_OFFERT_USD = float(os.getenv("MODAL_CREDIT_MENSUEL_USD", "30"))

# Duree maximale d'un clip, garde-fou dur : au-dela, la Sandbox est arretee et le
# compteur encaisse ce qui a ete consomme. 40 min couvre le premier lancement,
# telechargement du modele compris.
DUREE_MAX_S = int(os.getenv("VIDEO_TIMEOUT_SECONDS", "2400"))

VOLUME_MODELES = os.getenv("VIDEO_MODAL_VOLUME", "free-ai-studio-modeles")
CACHE_MODAL = "/modeles/hf"

MODELES = {
    "rapide": {
        "titre": "Rapide (defaut)",
        "hf": "Wan-AI/Wan2.1-VACE-1.3B-diffusers",
        "parametres": "1,3 milliard",
        # 19 Go de fichiers dans le depot (le lecteur de texte pese plus lourd
        # que le modele d'images lui-meme). Telecharges une fois, gardes sur le
        # disque Modal, qui est offert jusqu'a 1 Tio.
        "poids_go": 19,
        "licence": "Apache 2.0",
        "territoire": "aucune restriction de pays",
        "gpu": os.getenv("VIDEO_GPU_RAPIDE", "L4"),
        "largeur": 832,
        "hauteur": 480,
        "flow_shift": 3.0,
        "etapes": 30,
        "note": "Tient sur une petite carte : marche aussi sur Kaggle et Colab gratuits.",
    },
    "soigne": {
        "titre": "Soigne (plus lent, plus cher)",
        "hf": "Wan-AI/Wan2.1-VACE-14B-diffusers",
        "parametres": "14 milliards",
        "poids_go": 75,
        "licence": "Apache 2.0",
        "territoire": "aucune restriction de pays",
        "gpu": os.getenv("VIDEO_GPU_SOIGNE", "A100"),
        "largeur": 1280,
        "hauteur": 720,
        "flow_shift": 5.0,
        "etapes": 30,
        "note": "Meilleure image, environ six fois le prix. Reserve aux plans qui comptent.",
    },
}

# 16 images par seconde, et le modele n'accepte qu'un nombre d'images de la forme
# 4k+1. D'ou ces valeurs qui ne sont pas rondes.
DUREES = {
    "3": {"images": 49, "secondes": 3},
    "5": {"images": 81, "secondes": 5},
}

NEGATIF = (
    "couleurs criardes, surexpose, statique, details flous, sous-titres, style, "
    "oeuvre, peinture, image fixe, gris terne, pire qualite, basse qualite, "
    "compression JPEG, laid, incomplet, doigts en trop, mains mal dessinees, "
    "visages mal dessinés, deforme, membres difformes, doigts fusionnes, "
    "arriere-plan encombre, trois jambes, marche a reculons"
)


# --- Compteur de depense ------------------------------------------------------

def _mois_courant() -> str:
    return time.strftime("%Y-%m")


def budget_lire() -> dict:
    """Etat du mois en cours. Un mois neuf remet les compteurs a zero."""
    donnees = {"mois": _mois_courant(), "secondes": 0.0, "usd": 0.0, "clips": 0}
    try:
        brut = json.loads(BUDGET_FICHIER.read_text(encoding="utf-8"))
        if brut.get("mois") == donnees["mois"]:
            donnees.update({
                "secondes": float(brut.get("secondes", 0)),
                "usd": float(brut.get("usd", 0)),
                "clips": int(brut.get("clips", 0)),
            })
    except (OSError, ValueError, TypeError):
        pass
    donnees["plafond_usd"] = BUDGET_MENSUEL_USD
    donnees["credit_offert_usd"] = CREDIT_OFFERT_USD
    donnees["reste_usd"] = max(0.0, BUDGET_MENSUEL_USD - donnees["usd"])
    donnees["prix_releve_le"] = PRIX_RELEVE_LE
    return donnees


def budget_ecrire(secondes: float, usd: float, clips: int) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = BUDGET_FICHIER.with_suffix(".tmp")
    tmp.write_text(json.dumps({
        "mois": _mois_courant(),
        "secondes": round(secondes, 1),
        "usd": round(usd, 4),
        "clips": clips,
        "note": "Estimation locale, pas une facture. Le compte qui fait foi est "
                "celui de Modal. Supprimez ce fichier pour repartir de zero.",
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(BUDGET_FICHIER)


def prix_seconde(gpu: str) -> float:
    """Prix de la carte, ou le plus cher connu si le nom est inconnu.

    Se tromper vers le haut est le bon sens du refus : on prefere refuser un clip
    de trop que d'en laisser passer un qui creuse la facture.
    """
    return PRIX_GPU_USD_S.get(gpu.upper(), max(PRIX_GPU_USD_S.values()))


def budget_verifier(gpu: str, duree_max_s: int) -> dict:
    """Refuse AVANT de lancer si le pire cas depasse le plafond du mois.

    Le pire cas, c'est le clip qui va jusqu'au bout de son delai sans rien rendre.
    C'est le seul chiffre honnete : au moment de lancer, personne ne sait combien
    de temps prendra le calcul.
    """
    etat = budget_lire()
    pire = prix_seconde(gpu) * duree_max_s
    if etat["usd"] + pire > BUDGET_MENSUEL_USD:
        raise BudgetDepasse(
            f"Plafond du mois atteint. Deja depense ce mois-ci : "
            f"{etat['usd']:.2f} $ sur {BUDGET_MENSUEL_USD:.2f} $. Ce clip peut "
            f"coûter jusqu'a {pire:.2f} $, donc il n'est pas lance. Le compteur "
            f"repart tout seul le 1er du mois prochain."
        )
    etat["cout_max_du_clip_usd"] = round(pire, 3)
    return etat


def budget_consommer(gpu: str, secondes: float) -> dict:
    """Encaisse le temps reellement passe, meme si le clip a echoue.

    Un calcul qui plante a la derniere minute a quand meme loue la carte pendant
    ce temps-la. Ne compter que les reussites donnerait un compteur menteur.
    """
    with _VERROU:
        etat = budget_lire()
        secondes_total = etat["secondes"] + max(0.0, secondes)
        usd_total = etat["usd"] + prix_seconde(gpu) * max(0.0, secondes)
        budget_ecrire(secondes_total, usd_total, etat["clips"] + 1)
    return budget_lire()


class BudgetDepasse(RuntimeError):
    """Le plafond mensuel serait franchi : rien n'est lance."""


# --- Le script envoye sur la machine distante ---------------------------------

# Ce texte part tel quel sur le GPU. Il est autonome : il installe ce qui manque,
# telecharge le modele dans le cache s'il n'y est pas, fabrique la video, et
# depose le fichier dans le repertoire de sortie que le bac a sable ramene.
_SCRIPT = r'''# -*- coding: utf-8 -*-
"""Fabrique une video courte. Genere par Free AI Studio."""
import base64, importlib.util, io, json, os, subprocess, sys, time

DEBUT = time.time()
D = json.loads(base64.b64decode("__DEMANDE__").decode("utf-8"))
SORTIE = os.environ.get("FREE_AI_OUTPUT_DIR", "/tmp/free_ai_output")
os.makedirs(SORTIE, exist_ok=True)
if D.get("cache"):
    os.makedirs(D["cache"], exist_ok=True)
    os.environ["HF_HOME"] = D["cache"]
os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "0")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
# La memoire de la carte se morcelle au fil du calcul : il reste de la place au
# total, mais plus un seul bloc assez grand d'un seul tenant. Ce reglage laisse
# le systeme agrandir les blocs deja poses au lieu d'en reserver de nouveaux.
# Il doit etre pose AVANT le premier import de torch, sinon il est ignore en
# silence -- c'est pourquoi il est ici et pas plus bas.
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")


def assurer(paquets):
    """Installe ce qui manque. Sur Modal l'image les contient deja : cout nul."""
    manquants = [pip for pip, mod in paquets if importlib.util.find_spec(mod) is None]
    if manquants:
        print("Installation de : " + ", ".join(manquants), flush=True)
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", *manquants])


assurer([
    ("torch", "torch"),
    ("torchvision", "torchvision"),
    ("diffusers>=0.35.0", "diffusers"),
    ("transformers", "transformers"),
    ("accelerate", "accelerate"),
    ("sentencepiece", "sentencepiece"),
    ("protobuf", "google.protobuf"),
    ("ftfy", "ftfy"),
    ("imageio", "imageio"),
    ("imageio-ffmpeg", "imageio_ffmpeg"),
    ("pillow", "PIL"),
])

import PIL.Image
import torch
from diffusers import AutoencoderKLWan, WanVACEPipeline
from diffusers.schedulers.scheduling_unipc_multistep import UniPCMultistepScheduler
from diffusers.utils import export_to_video

if not torch.cuda.is_available():
    print("ECHEC : aucune carte graphique sur cette machine.", file=sys.stderr)
    sys.exit(2)

nom_gpu = torch.cuda.get_device_name(0)
vram_go = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
print("Carte : %s, %.1f Go" % (nom_gpu, vram_go), flush=True)

# Un T4 est de generation Turing : il sait faire du float16, pas du bfloat16.
# Lui imposer bfloat16 le fait retomber sur une emulation lente, en silence.
supporte_bf16 = torch.cuda.is_bf16_supported()
dtype = torch.bfloat16 if supporte_bf16 else torch.float16
print("Precision : %s" % ("bfloat16" if supporte_bf16 else "float16"), flush=True)

L, H = int(D["largeur"]), int(D["hauteur"])
IMAGES = int(D["images"])


def charger(cle):
    brut = D.get(cle)
    if not brut:
        return None
    img = PIL.Image.open(io.BytesIO(base64.b64decode(brut))).convert("RGB")
    return img.resize((L, H))


depart = charger("image_depart")
fin = charger("image_fin")
reference = charger("image_reference")

print("Chargement du modele %s ..." % D["modele"], flush=True)
t0 = time.time()
vae = AutoencoderKLWan.from_pretrained(D["modele"], subfolder="vae", torch_dtype=torch.float32)
pipe = WanVACEPipeline.from_pretrained(D["modele"], vae=vae, torch_dtype=dtype)
pipe.scheduler = UniPCMultistepScheduler.from_config(
    pipe.scheduler.config, flow_shift=float(D["flow_shift"])
)

# MESURE DU 09/09 : tout mettre sur la carte a sature 22 Go et le clip est mort
# en pleine compression d'images. Le coupable n'est pas le modele d'images (1,3
# milliard de parametres) mais le LECTEUR DE TEXTE qui l'accompagne, bien plus
# gros, et qui n'a rien a faire sur la carte pendant le calcul des images.
# enable_model_cpu_offload() ne garde sur la carte que la piece qui travaille a
# cet instant. On ne s'en passe qu'avec beaucoup de memoire.
if vram_go < 60:
    pipe.enable_model_cpu_offload()
    print("Pieces chargees une par une sur la carte (memoire limitee).", flush=True)
else:
    pipe.to("cuda")

# Deuxieme economie, sur le meme echec : la compression des images se faisait
# d'un bloc. En tuiles, le pic de memoire descend fortement pour un cout de
# temps faible.
for piece in ("vae",):
    objet = getattr(pipe, piece, None)
    for methode in ("enable_tiling", "enable_slicing"):
        fonction = getattr(objet, methode, None)
        if callable(fonction):
            try:
                fonction()
            except (RuntimeError, ValueError, TypeError) as exc:
                print("%s.%s indisponible : %s" % (piece, methode, exc), flush=True)

print("Modele pret en %.0f s" % (time.time() - t0), flush=True)

kwargs = dict(
    prompt=D["description"],
    negative_prompt=D["negatif"],
    height=H,
    width=L,
    num_frames=IMAGES,
    num_inference_steps=int(D["etapes"]),
    guidance_scale=5.0,
)

# Image de depart et/ou de fin : on fabrique une piste ou seules ces deux images
# sont connues, le reste est gris et masque. C'est la facon dont VACE recoit une
# contrainte de premiere et de derniere image.
if depart is not None or fin is not None:
    gris = PIL.Image.new("RGB", (L, H), (128, 128, 128))
    noir = PIL.Image.new("L", (L, H), 0)
    blanc = PIL.Image.new("L", (L, H), 255)
    pistes, masque = [], []
    for i in range(IMAGES):
        premiere = i == 0 and depart is not None
        derniere = i == IMAGES - 1 and fin is not None
        if premiere:
            pistes.append(depart); masque.append(noir)
        elif derniere:
            pistes.append(fin); masque.append(noir)
        else:
            pistes.append(gris); masque.append(blanc)
    kwargs["video"] = pistes
    kwargs["mask"] = masque

resultat = None
erreurs = []
# L'image de reference se passe en liste. Selon la version de diffusers, c'est
# une liste d'images ou une liste par element du lot : on essaie les deux plutot
# que d'epingler une version qui vieillira.
essais = [None]
if reference is not None:
    essais = [[reference], [[reference]]]

for tentative in essais:
    args = dict(kwargs)
    if tentative is not None:
        args["reference_images"] = tentative
    try:
        print("Calcul en cours (%d images, %d etapes) ..." % (IMAGES, args["num_inference_steps"]), flush=True)
        t1 = time.time()
        resultat = pipe(**args).frames[0]
        print("Calcul fait en %.0f s" % (time.time() - t1), flush=True)
        break
    except (TypeError, ValueError) as exc:
        erreurs.append("%s: %s" % (type(exc).__name__, exc))
        continue

if resultat is None:
    print("ECHEC du calcul : " + " | ".join(erreurs), file=sys.stderr)
    sys.exit(3)

chemin = os.path.join(SORTIE, "video.mp4")
export_to_video(resultat, chemin, fps=16)

# Un MP4 range son sommaire (duree, taille, position des images) a la FIN du
# fichier. Un navigateur doit alors telecharger tout le fichier avant d'afficher
# la premiere image. Le deplacer au debut ne recompresse rien -- on recopie les
# memes donnees dans un autre ordre -- et la lecture demarre tout de suite.
# Si quoi que ce soit echoue ici, on garde le fichier d'origine : il est bon,
# seulement moins commode.
try:
    import imageio_ffmpeg
    provisoire = chemin + ".rapide.mp4"
    subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error",
         "-i", chemin, "-c", "copy", "-movflags", "+faststart", provisoire],
        check=True, timeout=120,
    )
    if os.path.getsize(provisoire) > 0:
        os.replace(provisoire, chemin)
        print("Index deplace en tete : la lecture demarre sans tout telecharger.", flush=True)
except Exception as exc:  # noqa: BLE001 - une commodite, jamais une condition
    print("Index laisse en fin de fichier (%s). Le clip reste lisible." % exc, flush=True)

taille = os.path.getsize(chemin)
resume = {
    "fichier": "video.mp4",
    "octets": taille,
    "images": IMAGES,
    "secondes_video": round(IMAGES / 16.0, 1),
    "largeur": L,
    "hauteur": H,
    "modele": D["modele"],
    "carte": nom_gpu,
    "precision": "bfloat16" if supporte_bf16 else "float16",
    "secondes_calcul": round(time.time() - DEBUT, 1),
}
with open(os.path.join(SORTIE, "resume.json"), "w", encoding="utf-8") as f:
    json.dump(resume, f, ensure_ascii=False, indent=2)
print(json.dumps(resume, ensure_ascii=False), flush=True)
'''


def construire_script(demande: dict) -> str:
    """Fabrique le script autonome a envoyer sur le GPU.

    La demande voyage encodee DANS le script : un seul fichier part, quel que
    soit le fournisseur (Modal ecrit un fichier, Kaggle pousse un carnet, Colab
    fabrique un notebook). Une seule facon de faire, donc une seule a reparer.
    """
    charge = base64.b64encode(
        json.dumps(demande, ensure_ascii=False).encode("utf-8")
    ).decode("ascii")
    return _SCRIPT.replace("__DEMANDE__", charge)


def preparer(payload: dict, pour_modal: bool = True) -> dict:
    """Traduit ce que la page a envoye en une demande complete et bornee."""
    qualite = payload.get("qualite") or "rapide"
    if qualite not in MODELES:
        qualite = "rapide"
    modele = MODELES[qualite]

    duree = str(payload.get("duree") or "5")
    if duree not in DUREES:
        duree = "5"

    description = str(payload.get("description") or "").strip()
    if not description:
        raise ValueError("Il faut decrire la scene en quelques mots.")
    if len(description) > 2000:
        description = description[:2000]

    demande = {
        "modele": modele["hf"],
        "description": description,
        "negatif": NEGATIF,
        "largeur": modele["largeur"],
        "hauteur": modele["hauteur"],
        "flow_shift": modele["flow_shift"],
        "etapes": modele["etapes"],
        "images": DUREES[duree]["images"],
        "cache": CACHE_MODAL if pour_modal else "",
    }
    for cle_page, cle_demande in (
        ("image_depart", "image_depart"),
        ("image_fin", "image_fin"),
        ("image_reference", "image_reference"),
    ):
        brut = payload.get(cle_page)
        if brut:
            demande[cle_demande] = _nettoyer_image(brut, cle_page)

    return {
        "qualite": qualite,
        "duree": duree,
        "gpu": modele["gpu"],
        "demande": demande,
        "resume_public": {
            "modele": modele["hf"],
            "titre_modele": modele["titre"],
            "licence": modele["licence"],
            "carte": modele["gpu"],
            "definition": f"{modele['largeur']}x{modele['hauteur']}",
            "secondes_video": DUREES[duree]["secondes"],
            "image_depart": bool(demande.get("image_depart")),
            "image_fin": bool(demande.get("image_fin")),
            "image_reference": bool(demande.get("image_reference")),
        },
    }


MAX_IMAGE_OCTETS = int(os.getenv("VIDEO_MAX_IMAGE_BYTES", str(900 * 1024)))


def _nettoyer_image(brut: str, nom: str) -> str:
    """Accepte une image de la page, en base64 nue ou en data URI."""
    valeur = str(brut)
    if valeur.startswith("data:"):
        _, _, valeur = valeur.partition(",")
    valeur = "".join(valeur.split())
    try:
        octets = base64.b64decode(valeur, validate=True)
    except Exception as exc:  # noqa: BLE001 - message destine au debutant
        raise ValueError(f"L'image « {nom} » n'a pas pu etre lue.") from exc
    if len(octets) > MAX_IMAGE_OCTETS:
        raise ValueError(
            f"L'image « {nom} » est trop lourde ({len(octets) // 1024} Ko). "
            f"La page les reduit normalement toute seule ; reessayez avec une "
            f"image plus petite que {MAX_IMAGE_OCTETS // 1024} Ko."
        )
    if not octets:
        raise ValueError(f"L'image « {nom} » est vide.")
    return base64.b64encode(octets).decode("ascii")


# --- La page ------------------------------------------------------------------

PAGE_HTML = r"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Vidéo — Free AI Studio</title>
<style>
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;max-width:900px;
 margin:34px auto;padding:0 18px;line-height:1.55}
h1{font-size:1.5rem;margin-bottom:4px}
.sous{opacity:.8;margin-top:0}
.banniere{padding:14px 16px;border-radius:14px;margin:16px 0;border:1px solid #bbb;background:#eef4fb}
.ligne{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:14px 0}
select,button,input{font:inherit;padding:9px 12px;border-radius:10px;border:1px solid #666;background:#fff}
button.primaire{background:#222;color:#fff;border-color:#222;cursor:pointer}
button[disabled]{opacity:.5;cursor:default}
a.bouton{display:inline-block;font:inherit;padding:10px 16px;border-radius:10px;
 border:1px solid #222;background:#222;color:#fff;text-decoration:none;cursor:pointer}
a.bouton.discret{background:#fff;color:#222;border-color:#666}
a.bouton:hover{opacity:.86}
textarea{font:inherit;width:100%;box-sizing:border-box;height:110px;padding:12px;
 border-radius:12px;border:1px solid #999}
.images{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:14px}
.case{border:1px solid #bbb;border-radius:14px;padding:14px}
.case h3{margin:0 0 4px;font-size:1rem}
.case p{margin:0 0 10px;font-size:.85rem;opacity:.8}
.case img{max-width:100%;border-radius:9px;margin-top:9px;display:block}
pre{background:#f6f6f6;border:1px solid #ddd;border-radius:12px;padding:12px;
 overflow-x:auto;white-space:pre-wrap;word-break:break-word;font-size:.82rem}
video{width:100%;border-radius:12px;margin-top:12px;background:#000}
.ok{color:#1d6b32}.ko{color:#9b2116}
.avert{font-size:.86rem;opacity:.75}
.jauge{height:9px;border-radius:999px;background:#e6e6e6;overflow:hidden;margin:6px 0 2px}
.jauge span{display:block;height:100%;background:#5b8c5a}
.pied{margin-top:26px;padding-top:16px;border-top:1px solid #ddd;font-size:.9rem;opacity:.8}
</style></head><body>
<h1>🎬 Fabriquer une vidéo</h1>
<p class="sous">Décrivez une scène. Vous pouvez aussi donner l’image de départ,
celle d’arrivée, et une image de référence pour garder le même personnage.</p>

<div id="banniere" class="banniere">Vérification en cours…</div>

<textarea id="description" placeholder="Un phare breton sous la pluie, la mer se soulève, la lumière tourne."></textarea>

<div class="ligne">
  <label>Durée
    <select id="duree"><option value="3">3 secondes</option><option value="5" selected>5 secondes</option></select>
  </label>
  <label>Qualité
    <select id="qualite"><option value="rapide" selected>Rapide — Wan 2.1, 1,3 B</option><option value="soigne">Soignée — Wan 2.1, 14 B (plus chère)</option></select>
  </label>
  <label>Où
    <select id="ou"><option value="modal" selected>Modal — machine louée (carte bancaire exigée)</option><option value="kaggle">Kaggle — gratuit, plus lent</option></select>
  </label>
  <button id="lancer" class="primaire">Fabriquer</button>
</div>
<p id="licence" class="avert"></p>

<div class="images">
  <div class="case"><h3>Image de départ</h3>
    <p>Facultatif. La vidéo commencera exactement sur cette image.</p>
    <input type="file" accept="image/*" data-cle="image_depart"><div></div></div>
  <div class="case"><h3>Image de fin</h3>
    <p>Facultatif. La vidéo se terminera exactement sur celle-ci.</p>
    <input type="file" accept="image/*" data-cle="image_fin"><div></div></div>
  <div class="case"><h3>Image de référence</h3>
    <p>Facultatif. Le personnage ou l’objet montré ici sera gardé ressemblant.</p>
    <input type="file" accept="image/*" data-cle="image_reference"><div></div></div>
</div>

<div id="etat" class="ligne"></div>
<details id="detailJournal" hidden><summary>Voir le détail technique</summary>
<pre id="journal"></pre></details>
<div id="resultat"></div>

<div class="pied" id="pied"></div>

<script>
const CLE = "__CLE__";
const ENTETES = {"Authorization":"Bearer "+CLE, "Content-Type":"application/json"};
const IMAGES = {};
let minuteur = null;
let MODELES = null;

// La licence s'affiche LA OU l'on choisit, pas dans une note en bas de page.
function majLicence(){
  const m = MODELES && MODELES[document.getElementById("qualite").value];
  document.getElementById("licence").textContent = m
    ? ("Modèle " + m.hf + " : licence " + m.licence + ", " + m.territoire + ".")
    : "";
}
document.getElementById("qualite").addEventListener("change", majLicence);

// Les images sont réduites ICI, dans le navigateur : le modèle travaille de
// toute façon en 480p, et une photo de téléphone de 4 Mo n'apporterait rien
// qu'un envoi lent et un refus pour cause de taille.
function reduire(fichier, cote){
  return new Promise((ok, ko) => {
    const lecteur = new FileReader();
    lecteur.onerror = () => ko(new Error("lecture impossible"));
    lecteur.onload = () => {
      const img = new Image();
      img.onerror = () => ko(new Error("image illisible"));
      img.onload = () => {
        const r = Math.min(1, cote / Math.max(img.width, img.height));
        const c = document.createElement("canvas");
        c.width = Math.round(img.width * r); c.height = Math.round(img.height * r);
        c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
        ok(c.toDataURL("image/jpeg", 0.85));
      };
      img.src = lecteur.result;
    };
    lecteur.readAsDataURL(fichier);
  });
}

document.querySelectorAll('input[type=file]').forEach(entree => {
  entree.addEventListener("change", async () => {
    const cle = entree.dataset.cle;
    const apercu = entree.nextElementSibling;
    if(!entree.files || !entree.files[0]){ delete IMAGES[cle]; apercu.innerHTML=""; return; }
    try {
      const uri = await reduire(entree.files[0], 1024);
      IMAGES[cle] = uri;
      apercu.innerHTML = '<img src="' + uri + '" alt="">';
    } catch(e){
      delete IMAGES[cle];
      apercu.innerHTML = '<span class="ko">Image illisible.</span>';
    }
  });
});

function budgetTexte(b){
  const part = Math.min(100, 100 * b.usd / b.plafond_usd);
  return "Dépensé ce mois-ci selon le Studio : <b>" + b.usd.toFixed(2) + " $</b> sur un plafond de "
    + b.plafond_usd.toFixed(2) + " $. " + b.clips + " clip(s)."
    + '<div class="jauge"><span style="width:' + part.toFixed(1) + '%"></span></div>'
    + '<span class="avert">Estimation locale d’après les prix relevés le '
    + b.prix_releve_le + ', pas une facture. Le Studio ne lit pas votre compte Modal : le crédit de '
    + b.credit_offert_usd.toFixed(0) + ' $ par mois est celui que vous avez déclaré '
    + '(MODAL_CREDIT_MENSUEL_USD), non vérifié chez Modal. Modal exige une carte bancaire et facture '
    + 'au-delà du crédit, jusqu’à votre limite de dépense : '
    + '<a href="https://modal.com/settings/usage" target="_blank" rel="noopener">réglez-la au plus bas chez Modal</a>.</span>';
}

function rafraichirBudget(){
  return fetch("/video/budget", {headers:{"Authorization":"Bearer "+CLE}})
    .then(r => r.json())
    .then(d => {
      document.getElementById("banniere").innerHTML = budgetTexte(d.budget);
      MODELES = d.modeles;
      majLicence();
      if(d.kaggle_permis === false){
        const k = document.querySelector('#ou option[value="kaggle"]');
        k.disabled = true;
        k.textContent = "Kaggle — coupé ici : Studio partagé";
      }
      const p = document.getElementById("pied");
      p.innerHTML = "Modèle : <b>" + d.modeles.rapide.hf + "</b> (" + d.modeles.rapide.licence
        + ", " + d.modeles.rapide.poids_go + " Go). Rien ne part chez un fournisseur d’IA : "
        + "le calcul tourne sur une machine que vous louez à la minute, et le modèle est "
        + "téléchargé une fois puis gardé en cache."
        + '<br><a href="/">Retour au Sandbox</a> &nbsp; <a href="/cles">Brancher Modal ou Kaggle</a>';
      return d;
    })
    .catch(() => {
      document.getElementById("banniere").textContent =
        "État non vérifiable : le service Sandbox ne répond pas.";
    });
}

function condenser(t){
  // Les barres d'avancement ecrivent une ligne par pourcentage : le
  // telechargement du modele en produit plusieurs centaines, toutes pareilles,
  // et le debutant se retrouve devant un mur de chiffres ou il ne trouve plus
  // le message qui compte. On ne garde que la ligne d'arrivee de chaque barre,
  // et on dit combien de lignes ont ete mises de cote -- masquer sans le dire
  // serait mentir sur ce qui s'est passe.
  const gardees = []; let cachees = 0;
  for(const ligne of (t || "").split("\n")){
    if(/\d+%\|/.test(ligne) && !/100%\|/.test(ligne)){ cachees++; continue; }
    gardees.push(ligne);
  }
  if(cachees) gardees.push("… " + cachees + " lignes d’avancement masquées.");
  return gardees.join("\n");
}

function afficherJournal(t){
  document.getElementById("detailJournal").hidden = !t;
  document.getElementById("journal").textContent = condenser(t);
}

function nomDeFichier(){
  // Dix clips fabriques, et le dossier Telechargements contient video.mp4,
  // video(1).mp4, video(2).mp4 : plus personne ne sait lequel est lequel. Le nom
  // porte donc la date, l'heure, et le debut de la phrase demandee.
  const d = new Date();
  const jour = d.getFullYear() + "-"
    + String(d.getMonth()+1).padStart(2,"0") + "-"
    + String(d.getDate()).padStart(2,"0");
  const heure = String(d.getHours()).padStart(2,"0") + "h" + String(d.getMinutes()).padStart(2,"0");
  const mots = (document.getElementById("description").value || "")
    .normalize("NFD").replace(/[^\x00-\x7F]/g, "")
    .toLowerCase().replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+/, "").slice(0, 40).replace(/-+$/, "");
  return jour + "-" + heure + "-" + (mots || "video") + ".mp4";
}

function suivre(id){
  const etat = document.getElementById("etat");
  minuteur = setInterval(() => {
    fetch("/video/jobs/" + id, {headers:{"Authorization":"Bearer "+CLE}})
      .then(r => r.json())
      .then(j => {
        if(j.status === "running" || j.status === "queued"){
          const t = Math.round((Date.now()/1000) - (j.created_at || Date.now()/1000));
          etat.innerHTML = "⏳ En cours depuis " + t + " s. Le tout premier clip est le plus "
            + "long : le modèle se télécharge (une seule fois).";
          return;
        }
        clearInterval(minuteur); minuteur = null;
        document.getElementById("lancer").disabled = false;
        afficherJournal([j.stdout, j.stderr].filter(Boolean).join("\n"));
        rafraichirBudget();
        if(j.video_url){
          etat.innerHTML = '<span class="ok">✔ Vidéo prête</span> — ' + (j.resume ?
            (j.resume.secondes_calcul + " s de calcul, " + Math.round(j.resume.octets/1024) + " Ko") : "");
          const nom = nomDeFichier();
          const lienTelecharger = j.video_url + "&telecharger=1&nom=" + encodeURIComponent(nom);
          document.getElementById("resultat").innerHTML =
            '<video controls autoplay loop src="' + j.video_url + '"></video>'
            + '<div class="ligne">'
            + '<a class="bouton" href="' + lienTelecharger + '" download="' + nom + '">'
            + '⬇️ Télécharger la vidéo</a>'
            + '<a class="bouton discret" href="' + j.video_url + '" target="_blank" '
            + 'rel="noopener">Ouvrir dans un onglet</a>'
            + '<span class="avert">Le fichier s’appellera <code>' + nom + '</code> et ira '
            + 'dans votre dossier Téléchargements.</span>'
            + '</div>';
        } else {
          etat.innerHTML = '<span class="ko">✖ Échec</span> — ' + (j.message || "voir le journal ci-dessous.");
        }
      })
      .catch(() => {});
  }, 4000);
}

document.getElementById("lancer").addEventListener("click", () => {
  const bouton = document.getElementById("lancer");
  const etat = document.getElementById("etat");
  const corps = Object.assign({
    description: document.getElementById("description").value,
    duree: document.getElementById("duree").value,
    qualite: document.getElementById("qualite").value,
    ou: document.getElementById("ou").value,
  }, IMAGES);
  bouton.disabled = true;
  etat.textContent = "Envoi…";
  document.getElementById("resultat").innerHTML = "";
  afficherJournal("");
  fetch("/video/creer", {method:"POST", headers:ENTETES, body:JSON.stringify(corps)})
    .then(async r => {
      const d = await r.json().catch(() => ({}));
      if(!r.ok){ throw new Error(d.detail || ("HTTP " + r.status)); }
      return d;
    })
    .then(d => { etat.textContent = "⏳ Lancé."; suivre(d.id); })
    .catch(e => {
      bouton.disabled = false;
      etat.innerHTML = '<span class="ko">✖ ' + e.message + '</span>';
    });
});

rafraichirBudget();
</script>
</body></html>"""
