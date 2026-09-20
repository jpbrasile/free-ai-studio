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

import budget_modal

# Le compteur des depenses Modal est commun aux quatre usages -- la video, la
# chanson, le dialogue et le bac a sable lui-meme. Il tient le fichier, le
# verrou, la table des prix et le plafond ; ce module n'en garde que des
# renvois. CONFIG_DIR a disparu d'ici avec le fichier qu'il servait a nommer.
BUDGET_FICHIER = budget_modal.FICHIER

# TABLE UNIQUE depuis le 19/09/2026 : les prix Modal vivent dans
# budget_modal.py et ce module les LIT au lieu d'en garder une copie. Les noms
# sont conserves parce que les tests et les pages les citent ; ce ne sont plus
# que des renvois.
#
# Ce que la copie coutait, et qu'aucun test ne voyait : video.py portait les
# HUIT cartes, chanson.py et dialogue.py n'en portaient que QUATRE. Le test qui
# gardait ce flanc ne comparait que les cartes COMMUNES, donc il passait au
# vert -- pendant que prix_seconde() facturait une A100 au tarif L40S et une
# H100 a la MOITIE de son prix, parce qu'une carte inconnue retombe sur la plus
# chere CONNUE. Une table tronquee rend ce repli menteur.
PRIX_RELEVE_LE = budget_modal.PRIX_RELEVE_LE
PRIX_GPU_USD_S = budget_modal.PRIX_GPU_USD_S
PRIX_CPU_USD_S = budget_modal.PRIX_CPU_USD_S
PRIX_MEMOIRE_USD_S = budget_modal.PRIX_MEMOIRE_USD_S

# Ce que les DEMANDES peuvent atteindre : le plafond unique moins la part
# reservee au bac a sable. VIDEO_BUDGET_USD_PAR_MOIS n'est plus lu -- trois
# plafonds qui s'ignorent etaient precisement le defaut a reparer, et leur
# somme valait deja le credit entier. Voir budget_modal.py.
BUDGET_MENSUEL_USD = budget_modal.plafond_de("video")
CREDIT_OFFERT_USD = budget_modal.CREDIT_OFFERT_USD

# Duree maximale d'un clip, garde-fou dur : au-dela, la Sandbox est arretee et le
# compteur encaisse ce qui a ete consomme. 40 min couvre le premier lancement,
# telechargement du modele compris.
DUREE_MAX_S = int(os.getenv("VIDEO_TIMEOUT_SECONDS", "2400"))

VOLUME_MODELES = os.getenv("VIDEO_MODAL_VOLUME", "free-ai-studio-modeles")
CACHE_MODAL = "/modeles/hf"
# Ou le bac a sable de la maison garde les 34 Go de poids. Le worker construit
# un environnement nu pour le script : sans ce chemin ecrit DANS la demande, le
# modele se retelechargerait a chaque clip, dans un dossier de travail efface
# ensuite. Le meme chemin est monte cote compose (docker-compose.gpu.yml).
CACHE_MAISON = os.getenv("VIDEO_CACHE_MAISON", "/cache/huggingface")

# Sous quel systeme le Studio a ete lance. Ce service tourne dans un conteneur
# Linux quelle que soit la machine : il ne PEUT pas le deviner. C'est le
# lanceur qui le dit -- `scripts/demarrer.ps1` pose "windows", `start.sh` pose
# "linux" -- et la seule chose qui en depend est le nom du script a taper pour
# descendre les 34 Go. Nommer un script PowerShell a quelqu'un sous Linux, ou
# l'inverse, transforme un message utile en cul-de-sac.
STUDIO_LANCEUR = (os.getenv("STUDIO_LANCEUR") or "").strip().lower()
_TELECHARGEMENT_PS1 = "powershell -ExecutionPolicy Bypass -File scripts\\telecharger-modele-video.ps1"
_TELECHARGEMENT_SH = "./scripts/telecharger-modele-video.sh"


def commande_telechargement() -> str:
    """La commande qui descend les 34 Go, ecrite pour CETTE machine.

    Lanceur inconnu -- un `docker compose up` tape a la main, par exemple : on
    nomme les deux plutot que d'en inventer un. Se tromper coute a la personne
    le temps de comprendre pourquoi la commande n'existe pas ; donner les deux
    ne coute qu'une ligne."""
    if STUDIO_LANCEUR == "windows":
        return _TELECHARGEMENT_PS1
    if STUDIO_LANCEUR == "linux":
        return _TELECHARGEMENT_SH
    return "%s   (Linux, macOS)\n    %s   (Windows)" % (_TELECHARGEMENT_SH, _TELECHARGEMENT_PS1)


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
    # Le modele de la MAISON. Il ne se choisit pas dans la liste des qualites :
    # il est choisi par `ou_calculer.decider()` quand le clip peut etre fabrique
    # sur la carte d'ici. Premier clip mesure le 19/09/2026 a 18:43 : 412 s de
    # calcul, 12 841 Mo de pic, 0 $, contre 422 s et 0,117 $ pour le meme clip
    # de 3 s loue chez Modal -- mais en 720p au lieu de 480p.
    #
    # Il n'a PAS de VACE, et c'est la contrainte qui gouverne tout le routage :
    # la Wan 2.2 n'en publie aucun, et le seul qui existe (chez une autre
    # equipe) pese 81,24 Go en deux experts de 34,68 Go, donc ne tient pas dans
    # 24 Go. Une image de fin ou de reference ne peut donc pas etre fabriquee
    # ici -- elle part chez Modal, et la page le dit.
    "maison": {
        "titre": "A la maison (gratuit)",
        "hf": "Wan-AI/Wan2.2-TI2V-5B-Diffusers",
        "famille": "ti2v",
        "parametres": "5 milliards",
        "poids_go": 34,
        "licence": "Apache 2.0",
        "territoire": "aucune restriction de pays",
        "gpu": "maison",
        "largeur": 1280,
        "hauteur": 704,
        "flow_shift": None,
        "etapes": 50,
        "images_par_seconde": 24,
        "note": "Fabrique sur la carte de cet ordinateur. Ne coute rien, "
                "ne sait pas faire l'image de fin ni l'image de reference.",
    },
}

# Le modele de la maison tourne a 24 images par seconde, pas 16, et n'accepte
# lui aussi qu'un nombre d'images de la forme 4k+1. Cette table ne porte que les
# durees dont le besoin memoire a ete MESURE sur la carte -- voir
# `ou_calculer.BESOIN_MO_MESURE`. Une duree absente d'ici part chez Modal avec
# son motif : on ne lance pas un travail sur un chiffre suppose.
DUREES_MAISON = {
    "3": {"images": 73, "secondes": 3},
    "5": {"images": 121, "secondes": 5},
}


def images_maison(duree: str):
    """Combien d'images pour cette duree sur le modele de la maison, ou None.

    `None` n'est pas un echec : il veut dire << cette duree n'a pas encore ete
    mesuree ici >>, et le routage part chez Modal en le disant."""
    entree = DUREES_MAISON.get(str(duree))
    return entree["images"] if entree else None

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
#
# UN SEUL compteur depuis le 19/09/2026 : budget_modal.py, partage avec les
# deux autres fonctions ET avec le bac a sable lui-meme, qui envoyait du code
# sur Modal sans etre compte par personne. Ce qui suit ne compte plus rien :
# ce sont des renvois, gardes pour que app.py, les tests et les pages n'aient
# pas a savoir ou vit le compteur. Le motif est en tete de budget_modal.py.


def budget_lire() -> dict:
    """L'etat du mois, TOUS usages confondus, vu du plafond de celui-ci."""
    etat = budget_modal.vue("video")
    etat["clips"] = etat["appels"]["video"]
    return etat


def budget_ecrire(secondes: float, usd: float, clips: int) -> None:
    """Pose l'etat de cet usage. Outil de TEST : le service passe par
    budget_consommer(), qui ajoute au lieu de poser."""
    budget_modal.poser("video", secondes, usd, clips)


def prix_seconde(gpu: str) -> float:
    return budget_modal.prix_seconde(gpu, int(os.getenv("VIDEO_MEMORY_MB", "16384")))


# Temps de calcul MESURE sur une machine louee, par qualite et par duree. Sert
# a chiffrer ce qu'une location couterait AVANT de la lancer : quand la carte
# d'ici est prise, le client choisit entre attendre et payer, et il ne peut pas
# choisir sans le prix. Rien n'est extrapole -- une combinaison absente rend
# None, et la page affiche alors le plafond du pire cas, qui est honnete mais
# large.
SECONDES_MESUREES = {
    ("rapide", "3"): 422,   # 09/09/2026, L4, 49 images en 832x480, 0,117 $
}


def prix_estime(qualite: str, duree: str):
    """Ce que cette location couterait, en dollars, ou None si non mesure."""
    secondes = SECONDES_MESUREES.get((str(qualite), str(duree)))
    if secondes is None or qualite not in MODELES:
        return None
    return round(prix_seconde(MODELES[qualite]["gpu"]) * secondes, 4)


def budget_verifier(gpu: str, duree_max_s: int) -> dict:
    """Refuse AVANT de lancer si le pire cas entame ce qui reste a cet usage."""
    etat = budget_modal.verifier(
        "video", gpu, duree_max_s, int(os.getenv("VIDEO_MEMORY_MB", "16384")),
        quoi="Ce clip", suite="")
    etat["cout_max_du_clip_usd"] = etat["cout_max_usd"]
    etat["clips"] = etat["appels"]["video"]
    return etat


def budget_consommer(gpu: str, secondes: float) -> dict:
    """Encaisse le temps reellement passe, meme si le clip a echoue."""
    etat = budget_modal.consommer("video", gpu, secondes, int(os.getenv("VIDEO_MEMORY_MB", "16384")))
    etat["clips"] = etat["appels"]["video"]
    return etat


# LA MEME exception pour les trois, et c'etait un piege arme : un
# `except video.BudgetDepasse` attrapait jusqu'ici une classe differente de
# celle que chanson.py levait.
BudgetDepasse = budget_modal.BudgetDepasse


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
    # Le bac a sable de la maison n'a PAS internet (reseau `internal: true`,
    # comme celui sur processeur). Si les poids ne sont pas deja dans le cache,
    # il ne pourra pas aller les chercher -- et le message brut serait une pile
    # d'erreurs de resolution de nom, ou personne ne lit << il manque le
    # modele >>. On regarde donc AVANT, et on dit quoi faire.
    if os.environ.get("HF_HUB_OFFLINE") == "1":
        dossier = os.path.join(D["cache"], "hub", "models--" + D["modele"].replace("/", "--"))
        if not os.path.isdir(dossier):
            print("ECHEC : les poids du modele %s ne sont pas sur cet ordinateur.\n"
                  "Ce bac a sable n'a pas internet, par construction : il ne peut pas les\n"
                  "telecharger lui-meme. Lancez UNE FOIS, dans le dossier du Studio :\n"
                  "    %s\n"
                  "C'est environ 34 Go, une seule fois, et le clip repartira ensuite tout seul."
                  % (D["modele"], D.get("aide_poids", "scripts/telecharger-modele-video")),
                  file=sys.stderr)
            sys.exit(5)
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
from diffusers import AutoencoderKLWan, WanPipeline, WanVACEPipeline
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
# Deux familles de modeles passent par ce script, et une seule sait faire les
# images de fin et de reference :
#   "vace" -> Wan 2.1 VACE, loue chez Modal ou Kaggle, 16 images/s
#   "ti2v" -> Wan 2.2 TI2V-5B, la carte de la maison, 24 images/s, PAS de VACE
FAMILLE = D.get("famille", "vace")
FPS = int(D.get("images_par_seconde", 16))


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
if FAMILLE == "ti2v":
    # Le modele de la maison. Sa configuration porte son propre ordonnanceur et
    # son propre `expand_timesteps` : on ne lui impose PAS de flow_shift, qui
    # est un reglage de la 2.1.
    pipe = WanPipeline.from_pretrained(D["modele"], vae=vae, torch_dtype=dtype)
else:
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
if FAMILLE == "ti2v" and (depart is not None or fin is not None or reference is not None):
    # Ce cas ne doit jamais arriver : `ou_calculer.decider()` envoie ces clips
    # chez Modal, et `preparer(maison=True)` refuse deja. Le troisieme garde est
    # ici parce que les deux premiers sont dans un autre fichier, et que la
    # panne qu'on evite est SILENCIEUSE : `diffusers` accepte `last_image` sur
    # ce modele et ne s'en sert pas (mesure du 19/09), et `WanPipeline` n'a
    # meme pas d'argument `image` -- une image de depart posee ici partirait a
    # la poubelle sans un mot. Mieux vaut un arret net qu'un clip qui a l'air
    # bon et ignore la consigne.
    print("ECHEC : le modele de la maison, tel qu'il est lance ici, ne pose ni "
          "l'image de depart ni l'image de fin ni l'image de reference. "
          "Ce clip devait partir chez Modal.",
          file=sys.stderr)
    sys.exit(4)

if FAMILLE != "ti2v" and (depart is not None or fin is not None):
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
if reference is not None and FAMILLE != "ti2v":
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
export_to_video(resultat, chemin, fps=FPS)

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
    "images_par_seconde": FPS,
    "secondes_video": round(IMAGES / float(FPS), 1),
    "largeur": L,
    "hauteur": H,
    "modele": D["modele"],
    "famille": FAMILLE,
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


def preparer(payload: dict, pour_modal: bool = True, maison: bool = False) -> dict:
    """Traduit ce que la page a envoye en une demande complete et bornee.

    `maison` n'est pas un choix du client : c'est le verdict de
    `ou_calculer.decider()`. La qualite demandee ne survit pas a ce verdict --
    le modele de la maison a sa propre definition et sa propre cadence -- et
    c'est voulu : le client choisit OU, pas quel modele."""
    qualite = payload.get("qualite") or "rapide"
    if qualite not in MODELES or qualite == "maison":
        qualite = "rapide"
    if maison:
        qualite = "maison"
    modele = MODELES[qualite]
    table_durees = DUREES_MAISON if maison else DUREES

    duree = str(payload.get("duree") or "5")
    if duree not in table_durees:
        if maison:
            raise ValueError(
                "La duree de %s s n'a pas encore ete mesuree sur la carte d'ici. "
                "Ce clip ne peut pas etre fabrique a la maison." % duree
            )
        duree = "5"

    description = str(payload.get("description") or "").strip()
    if not description:
        raise ValueError("Il faut decrire la scene en quelques mots.")
    if len(description) > 2000:
        description = description[:2000]

    demande = {
        "modele": modele["hf"],
        "famille": modele.get("famille", "vace"),
        "description": description,
        "negatif": NEGATIF,
        "largeur": modele["largeur"],
        "hauteur": modele["hauteur"],
        "flow_shift": modele["flow_shift"],
        "etapes": modele["etapes"],
        "images": table_durees[duree]["images"],
        "images_par_seconde": modele.get("images_par_seconde", 16),
        "cache": CACHE_MAISON if maison else (CACHE_MODAL if pour_modal else ""),
        # Le script part sur une machine qui ne sait rien du systeme d'ou vient
        # la demande : la commande a taper voyage donc AVEC lui.
        "aide_poids": commande_telechargement(),
    }
    for cle_page, cle_demande in (
        ("image_depart", "image_depart"),
        ("image_fin", "image_fin"),
        ("image_reference", "image_reference"),
    ):
        brut = payload.get(cle_page)
        if brut:
            demande[cle_demande] = _nettoyer_image(brut, cle_page)

    # Le modele de la maison n'a pas de VACE : il ne SAIT PAS poser une image de
    # fin ni une image de reference. `diffusers` ne s'en plaindrait pas -- il
    # accepte l'argument et l'ignore en silence (mesure du 19/09 sur la 5B, ou
    # `last_image` est accepte puis jamais utilise). Un clip qui ignore la
    # consigne sans rien dire est pire qu'un clip paye : on refuse ici, fort.
    # L'image de DEPART est refusee pour une autre raison : le modele sait la
    # poser, mais par `WanImageToVideoPipeline`, pas par `WanPipeline` que ce
    # script emploie -- laquelle n'accepte meme pas l'argument. Non mesure ici,
    # donc non offert : le silence serait le meme.
    if maison:
        ignorees = [n for n in ("image_depart", "image_fin", "image_reference") if demande.get(n)]
        if ignorees:
            raise ValueError(
                "Le modele de la maison ne sait pas poser %s. Ce clip doit partir "
                "chez Modal." % " ni ".join(n.replace("_", " de ") for n in ignorees)
            )

    return {
        "qualite": qualite,
        "duree": duree,
        "gpu": modele["gpu"],
        "demande": demande,
        "resume_public": {
            # La phrase tapee par le client. Elle manquait jusqu'au 19/09/2026,
            # et son absence se mesure : des deux clips fabriques ce soir-la,
            # l'un pese 1 901 468 octets et l'autre 390 313 -- personne ne peut
            # plus dire sur quel texte, ni refaire le meme clip, ni comparer
            # deux modeles << sur le meme texte >> comme le plan le demande.
            # Elle ne quitte pas cet ordinateur : elle est ecrite dans la fiche
            # du travail, a cote du reste.
            "description": description,
            "modele": modele["hf"],
            "titre_modele": modele["titre"],
            "licence": modele["licence"],
            "carte": modele["gpu"],
            "definition": f"{modele['largeur']}x{modele['hauteur']}",
            "secondes_video": table_durees[duree]["secondes"],
            "images_par_seconde": demande["images_par_seconde"],
            "maison": maison,
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
/* La boite qui s'ouvre quand la carte de la maison est prise. Jaune et non
   rouge : rien n'est en panne, on attend une reponse. */
.attente{padding:14px 16px;border-radius:14px;margin:16px 0;border:1px solid #d6b45a;background:#fdf6e3}
.attente h3{margin:0 0 6px;font-size:1rem}
.attente .chiffres{font-size:.88rem;opacity:.85;margin:6px 0 12px}
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
  <!-- « si on loue » ici aussi, et pour la même raison que le menu voisin :
       quand le clip est fabriqué sur la carte de cet ordinateur, ce menu ne
       gouverne rien. Le modèle de la maison n'est pas dans cette liste -- il
       ne se choisit pas, il se déduit du réglage du dessous -- et la page l'a
       donc tu jusqu'au 19/09/2026 au soir, alors qu'il est celui qui fabrique
       le clip sur le réglage PAR DÉFAUT. Le propriétaire l'a vu : « pas de
       Wan 2.2 sur le lien /video ». La ligne de licence en dessous nomme
       maintenant les deux, et dit lequel part vraiment. -->
  <label>Qualité si on loue
    <select id="qualite"><option value="rapide" selected>Rapide — Wan 2.1, 1,3 B</option><option value="soigne">Soignée — Wan 2.1, 14 B (plus chère)</option></select>
  </label>
  <!-- Ce menu ne dit plus OÙ le clip se fabrique : depuis le 19/09/2026 c'est
       la ligne « Carte de cet ordinateur », juste en dessous, qui le décide.
       Celui-ci dit quelle machine on loue QUAND on loue. Garder le mot « Où »
       aurait laissé deux réglages se disputer la même question. -->
  <label>Si on loue
    <select id="ou"><option value="modal" selected>Modal — machine louée (carte bancaire exigée)</option><option value="kaggle">Kaggle — gratuit, plus lent</option></select>
  </label>
  <button id="lancer" class="primaire">Fabriquer</button>
</div>
<p id="licence" class="avert"></p>

<!-- N'apparait QUE si cet ordinateur a une carte branchee au Studio. Celui qui
     n'en a pas ne doit pas voir un reglage qui ne le concerne pas. -->
<div id="ouCalculer" class="ligne" hidden>
  <label>Carte de cet ordinateur
    <select id="reglage">
      <option value="maison-si-libre">À la maison si la carte est libre (défaut)</option>
      <option value="toujours-modal">Toujours sur une machine louée</option>
      <option value="toujours-maison">Toujours à la maison, quitte à attendre</option>
    </select>
  </label>
  <span class="avert" id="reglageNote"></span>
</div>

<div id="carteprise" class="attente" hidden></div>

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
let CARTE_POSSIBLE = false;   // cet ordinateur a-t-il une carte branchée au Studio

// Du texte libre qui repasse dans du HTML redevient du code si on le laisse
// faire. Une seule ligne, et elle sert partout où l'on affiche ce que le
// client a tapé.
function enTexte(s){
  const d = document.createElement("div");
  d.textContent = String(s == null ? "" : s);
  return d.innerHTML;
}

// La licence s'affiche LA OU l'on choisit, pas dans une note en bas de page.
//
// Et depuis le 19/09/2026 elle nomme les DEUX modèles quand il y a une carte
// ici : celui qu'on loue, et celui de la maison. Le menu « Qualité si on loue »
// ne nomme que la Wan 2.1 ; or sur le réglage par défaut, carte libre, c'est la
// Wan 2.2 qui fabrique le clip -- 1280x704 à 24 images/s au lieu de 832x480 à
// 16. La page affichait donc, sur son chemin le plus fréquent, le nom d'un
// modèle qui ne tournait pas. Aucun chiffre n'est écrit ici à la main : tout
// vient du dictionnaire servi par /video/budget.
function majLicence(){
  const cible = document.getElementById("licence");
  if(!MODELES){ cible.textContent = ""; return; }
  const m = MODELES[document.getElementById("qualite").value];
  const lignes = [];
  if(m){
    lignes.push("Si on loue : <b>" + m.hf + "</b> — licence " + m.licence + ", "
                + m.territoire + ".");
  }
  const maison = MODELES["maison"];
  const reglage = (document.getElementById("reglage") || {}).value;
  if(CARTE_POSSIBLE && maison && reglage !== "toujours-modal"){
    lignes.push("À la maison : <b>" + maison.hf + "</b> — licence " + maison.licence
                + ", " + maison.largeur + "×" + maison.hauteur + " à "
                + maison.images_par_seconde + " images/s, gratuit. "
                + maison.note);
  }
  cible.innerHTML = lignes.join("<br>");
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
  return "Dépensé sur Modal ce mois-ci selon le Studio, tous usages confondus : <b>"
    + b.usd.toFixed(2) + " $</b> sur les " + b.plafond_usd.toFixed(2)
    + " $ ouverts aux demandes. " + b.clips + " clip(s) sur cette page."
    + '<div class="jauge"><span style="width:' + part.toFixed(1) + '%"></span></div>'
    + '<span class="avert">Estimation locale d’après les prix relevés le '
    + b.prix_releve_le
    + ', pas une facture. Ce compteur est <b>unique</b> depuis le 19/09/2026 : il compte '
    + 'ensemble les clips, les chansons, les dialogues et le code envoyé au Sandbox, sur un '
    + 'budget de ' + b.plafond_total_usd.toFixed(2) + ' $, dont '
    + b.reserve_autonome_usd.toFixed(2) + ' $ sont réservés au Sandbox et ne peuvent pas '
    + 'être entamés ici. '
    + 'Le Studio ne lit pas votre compte Modal : le crédit de '
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
      // Deux modèles, pas un : celui qu'on loue et celui d'ici. Le pied ne
      // citait que le premier -- voir le commentaire de majLicence().
      p.innerHTML = "Modèles : <b>" + d.modeles.rapide.hf + "</b> (" + d.modeles.rapide.licence
        + ", " + d.modeles.rapide.poids_go + " Go) quand on loue"
        + (CARTE_POSSIBLE && d.modeles.maison
            ? (", <b>" + d.modeles.maison.hf + "</b> (" + d.modeles.maison.licence + ", "
               + d.modeles.maison.poids_go + " Go) sur la carte de cet ordinateur")
            : "")
        + ". Rien ne part chez un fournisseur d’IA : "
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
          // Deux mots suffisent : fait ici, ou loué. Et le prix s'il y en a un.
          const maison = j.ou_calculer && j.ou_calculer.ou === "maison";
          const ouFait = maison
            ? "fait à la maison, 0 $"
            : ("loué" + (j.ou_calculer && j.ou_calculer.prix_estime_usd != null
                         ? (" — environ " + j.ou_calculer.prix_estime_usd.toFixed(3) + " $") : ""));
          etat.innerHTML = '<span class="ok">✔ Vidéo prête</span> — ' + ouFait + (j.resume ?
            (", " + j.resume.secondes_calcul + " s de calcul, " + Math.round(j.resume.octets/1024) + " Ko") : "");
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
            + '</div>'
            // Le texte qui a fait ce clip, sous le clip. Sans lui, deux clips
            // côte à côte ne se distinguent plus dès le lendemain. Échappé :
            // c'est du texte libre, et il ne doit jamais redevenir du code en
            // revenant du serveur.
            + ((j.video && j.video.description)
                ? ('<p class="avert">Texte : « ' + enTexte(j.video.description) + ' »</p>')
                : "");
        } else {
          etat.innerHTML = '<span class="ko">✖ Échec</span> — ' + (j.message || "voir le journal ci-dessous.");
        }
      })
      .catch(() => {});
  }, 4000);
}

// --- Où le clip se fabrique --------------------------------------------------
//
// Le service tranche ce qui est factuel — ce que la carte d'ici sait faire, la
// place qu'il faut, ce qui reste de libre — et REND LA QUESTION dès qu'il ne
// reste qu'un arbitrage de goût : attendre ne coûte rien, louer coûte de
// l'argent, et personne d'autre que le client ne sait s'il est pressé.
// Un 409 n'est donc pas une panne : c'est une question.

let ATTENTE_DEPUIS = null;      // l'heure où le client a dit « j'attends »
let ATTENTE_MINUTEUR = null;

function reglageActuel(){
  const s = document.getElementById("reglage");
  return s ? s.value : null;
}

function chargerReglage(){
  return fetch("/video/ou-calculer", {headers:{"Authorization":"Bearer "+CLE}})
    .then(r => r.json())
    .then(d => {
      if(!d.carte_possible) return d;   // pas de carte ici : rien à régler
      CARTE_POSSIBLE = true;
      document.getElementById("ouCalculer").hidden = false;
      document.getElementById("reglage").value = d.reglage;
      majLicence();   // la ligne de licence doit nommer le modèle de la maison
      const durees = Object.keys(d.durees_maison || {}).join(" et ");
      document.getElementById("reglageNote").textContent =
        "Fabriquer ici ne coûte rien. La carte est partagée : le Studio ne prend "
        + "jamais la place d'un calcul en cours."
        + (durees ? (" Durées mesurées ici : " + durees + " secondes.") : "");
      return d;
    })
    .catch(() => null);
}

const selReglage = document.getElementById("reglage");
if(selReglage){
  selReglage.addEventListener("change", () => {
    majLicence();   // « toujours sur une machine louée » retire la ligne maison
    fetch("/video/ou-calculer", {method:"POST", headers:ENTETES,
                                 body:JSON.stringify({reglage: selReglage.value})})
      .catch(() => {});
  });
}

function fermerAttente(){
  if(ATTENTE_MINUTEUR){ clearTimeout(ATTENTE_MINUTEUR); ATTENTE_MINUTEUR = null; }
  ATTENTE_DEPUIS = null;
  document.getElementById("carteprise").hidden = true;
  document.getElementById("carteprise").innerHTML = "";
}

function prix(d){
  return d.prix_estime_usd == null ? "" : (" — environ " + d.prix_estime_usd.toFixed(3) + " $");
}

// La carte est prise. On montre CE QUI BLOQUE avec ses nombres, puis on attend
// une réponse. Jamais « indisponible » tout seul : un refus sans chiffre envoie
// chercher une panne qui n'existe pas.
function demanderAuClient(d){
  const boite = document.getElementById("carteprise");
  const c = d.carte || {};
  const chiffres = (c.libre_mo != null && c.totale_mo != null)
    ? (c.nom + " : " + (c.libre_mo/1024).toFixed(1) + " Go libres sur "
       + (c.totale_mo/1024).toFixed(1) + ", il en faut " + (d.besoin_mo/1024).toFixed(1) + ".")
    : (d.pourquoi || "");
  boite.hidden = false;

  // `titre` n'arrive que quand ce n'est PAS la carte qui bloque -- aujourd'hui
  // le modèle qui se télécharge. Sans lui, la boîte dirait « la carte est
  // prise » pendant que le Studio descend 34 Go, ce qui est faux et inquiète.
  if(d.ou === "attente"){
    const depuis = ATTENTE_DEPUIS ? Math.round((Date.now() - ATTENTE_DEPUIS)/1000) : 0;
    boite.innerHTML = "<h3>⏸ " + (d.titre ? d.titre : "J’attends la carte") + "</h3>"
      + '<div class="chiffres">' + chiffres + " Nouvel essai toutes les 30 secondes ; "
      + "j’attends depuis " + depuis + " s."
      + (d.titre ? "" : " On n’arrête jamais le calcul qui tient la carte.") + "</div>"
      + '<div class="ligne">'
      + '<button class="primaire" id="btLouer">Louer chez ' + (document.getElementById("ou").value === "kaggle" ? "Kaggle" : "Modal") + prix(d) + '</button>'
      + '<button id="btAnnuler">Annuler</button></div>';
    document.getElementById("btLouer").onclick = () => { fermerAttente(); envoyer({ou_calculer:"toujours-modal"}); };
    document.getElementById("btAnnuler").onclick = () => {
      fermerAttente();
      document.getElementById("lancer").disabled = false;
      document.getElementById("etat").textContent = "Abandonné. Rien n’a été fabriqué, rien n’a été facturé.";
    };
    if(!ATTENTE_DEPUIS) ATTENTE_DEPUIS = Date.now();
    ATTENTE_MINUTEUR = setTimeout(() => envoyer({attendre:true}), 30000);
    return;
  }

  // « on-demande » : trois sorties, et le prix AVANT, pas après.
  boite.innerHTML = "<h3>" + (d.titre ? d.titre : "La carte de cet ordinateur est prise") + "</h3>"
    + '<div class="chiffres">' + chiffres + " Attendre ne coûte rien ; louer, si.</div>"
    + '<div class="ligne">'
    + '<button class="primaire" id="btAttendre">J’attends</button>'
    + '<button id="btLouer">Louer chez ' + (document.getElementById("ou").value === "kaggle" ? "Kaggle" : "Modal") + prix(d) + '</button>'
    + '<button id="btAnnuler">Annuler</button></div>';
  document.getElementById("btAttendre").onclick = () => { ATTENTE_DEPUIS = Date.now(); envoyer({attendre:true}); };
  document.getElementById("btLouer").onclick = () => { fermerAttente(); envoyer({ou_calculer:"toujours-modal"}); };
  document.getElementById("btAnnuler").onclick = () => {
    fermerAttente();
    document.getElementById("lancer").disabled = false;
    document.getElementById("etat").textContent = "Abandonné. Rien n’a été fabriqué, rien n’a été facturé.";
  };
}

function envoyer(extra){
  const bouton = document.getElementById("lancer");
  const etat = document.getElementById("etat");
  const corps = Object.assign({
    description: document.getElementById("description").value,
    duree: document.getElementById("duree").value,
    qualite: document.getElementById("qualite").value,
    ou: document.getElementById("ou").value,
    ou_calculer: reglageActuel(),
  }, IMAGES, extra || {});
  bouton.disabled = true;
  if(!extra || !extra.attendre){
    etat.textContent = "Envoi…";
    document.getElementById("resultat").innerHTML = "";
    afficherJournal("");
  }
  fetch("/video/creer", {method:"POST", headers:ENTETES, body:JSON.stringify(corps)})
    .then(async r => {
      const d = await r.json().catch(() => ({}));
      // 409 : rien n'est cassé, la carte est prise et c'est au client de dire.
      if(r.status === 409 && d.detail && d.detail.ou){ demanderAuClient(d.detail); return null; }
      if(!r.ok){ throw new Error(typeof d.detail === "string" ? d.detail : ("HTTP " + r.status)); }
      return d;
    })
    .then(d => {
      if(!d) return;
      fermerAttente();
      const ouFait = (d.ou_calculer && d.ou_calculer.ou === "maison")
        ? "⏳ Lancé sur la carte de cet ordinateur — gratuit."
        : "⏳ Lancé sur une machine louée.";
      etat.textContent = ouFait;
      suivre(d.id);
    })
    .catch(e => {
      fermerAttente();
      bouton.disabled = false;
      etat.innerHTML = '<span class="ko">✖ ' + e.message + '</span>';
    });
}

document.getElementById("lancer").addEventListener("click", () => { ATTENTE_DEPUIS = null; envoyer(null); });

// Dans cet ordre, et pas l'inverse : le pied de page et la ligne de licence
// nomment le modèle de la maison, ce qu'ils ne peuvent faire que si l'on sait
// déjà si cet ordinateur a une carte. chargerReglage() répond à cette
// question ; rafraichirBudget() écrit les deux lignes.
chargerReglage().then(rafraichirBudget);
</script>
</body></html>"""
