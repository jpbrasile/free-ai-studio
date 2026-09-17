"""Dialogues a deux voix (facon podcast), rendus par FireRedTTS-2 sur un GPU loue.

Un script a plusieurs locuteurs, balise ligne par ligne, rendu en un seul fichier
audio ou les voix se repondent. Ce n'est PAS la synthese vocale du routeur
(/v1/audio/speech, Piper, une voix par langue, sur processeur) : ici le modele
fabrique une conversation, pas une lecture.

UN SEUL ENDROIT : Modal. /chanson offre aussi Kaggle et Colab parce que son
chemin sur carte T4 a ete essaye en vrai, le 15/09. Pour ce modele-ci, rien n'a
jamais tourne nulle part : proposer un endroit gratuit non verifie reviendrait a
vendre un essai dont personne ne connait le resultat. Modal seul, et la page le
dit.

CE QUI N'EST PAS MESURE, ET QUI COMPTE :
- Le francais. Le modele l'annonce parmi sept langues ; AUCUN banc d'essai
  public ne le note (PodEval, SoulX-Podcast, le tableau des auteurs et celui de
  MOSS-TTSD portent tous sur le mandarin et l'anglais). La verification sera une
  ecoute, comme pour le surlignage karaoke, et comme Piper l'attend encore.
- Le cout. Le seul repere mesure par le Studio est YuE2 a 0,044 $ pour 2 minutes
  de chant sur L4. Celui-ci est plus leger, donc VRAISEMBLABLEMENT moins cher --
  et << vraisemblablement >> n'est pas une mesure. Aucun chiffre n'est annonce.
- La memoire vive demandee. Reprise telle quelle de /chanson, jamais mesuree
  pour ce modele : se tromper vers le haut coute des centimes, se tromper vers
  le bas tue le travail apres l'avoir paye.
"""

from __future__ import annotations

import base64
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Dict

CONFIG_DIR = Path(os.getenv("FREE_AI_CONFIG_DIR", "/config"))
BUDGET_FICHIER = CONFIG_DIR / "dialogue-budget.json"
_VERROU = threading.Lock()

# Prix Modal releves sur https://modal.com/pricing. Ils servent a COMPTER, pas a
# facturer. Ces six chiffres sont les MEMES que ceux de chanson.py et video.py :
# un test le verifie, parce que le 17/09 deux de ces tables portaient deja deux
# dates de releve differentes sans que rien ne le signale.
PRIX_RELEVE_LE = "2026-09-17"
PRIX_GPU_USD_S: Dict[str, float] = {
    "T4": 0.000164,
    "L4": 0.000222,
    "A10": 0.000306,
    "L40S": 0.000542,
}
PRIX_CPU_USD_S = 0.0000131       # par coeur physique et par seconde
PRIX_MEMOIRE_USD_S = 0.00000222  # par Gio et par seconde

# 5 $ par mois, demande de l'utilisateur le 17/09 (<< budget 5 $ aussi >>).
#
# ARITHMETIQUE A DIRE TOUT HAUT : 5 (chanson) + 20 (video) + 5 (dialogue) = 30 $,
# soit EXACTEMENT le credit Modal que l'utilisateur declare. Les trois compteurs
# sont etanches -- aucun ne voit les deux autres -- donc les trois peuvent
# atteindre leur plafond le meme mois et le total sortirait du credit. Ce n'est
# pas un defaut cache : c'est la raison pour laquelle la page renvoie vers la
# limite de depense a regler chez Modal, seul endroit ou le compte fait foi.
BUDGET_MENSUEL_USD = float(os.getenv("DIALOGUE_BUDGET_USD_PAR_MOIS", "5"))
CREDIT_OFFERT_USD = float(os.getenv("MODAL_CREDIT_MENSUEL_USD", "30"))

# Garde-fou dur : au-dela, la machine est arretee et le compteur encaisse ce qui
# a ete consomme. Le premier lancement telecharge environ 12,6 Go de poids.
DUREE_MAX_S = int(os.getenv("DIALOGUE_TIMEOUT_SECONDS", "1800"))
GPU_MODAL = os.getenv("DIALOGUE_GPU", "L4")
# Reprise de /chanson, NON MESUREE pour ce modele : 12,6 Go de poids passent par
# la memoire vive au chargement. Voir l'entete.
MEMOIRE_MB = int(os.getenv("DIALOGUE_MEMORY_MB", "24576"))
# Meme disque persistant que la video et la chanson : un seul volume a
# surveiller chez Modal.
VOLUME_MODELES = os.getenv("VIDEO_MODAL_VOLUME", "free-ai-studio-modeles")
CACHE_MODAL = "/modeles/hf"

MODELE = {
    "hf": "FireRedTeam/FireRedTTS2",
    # Revision epinglee le 17/09/2026. Ce n'est pas qu'une question de
    # reproductibilite : les poids sont des fichiers .pt, c'est-a-dire des
    # pickles, et torch.load(weights_only=False) execute ce qu'ils contiennent.
    # Epingler le commit est ici une barriere de securite.
    "revision": "4af3f5cc4963373b86b52d750220d4de85261f05",
    "code": "https://github.com/FireRedTeam/FireRedTTS2",
    # PAS EPINGLEE, et c'est un manque, pas un choix : les poids vivent sur
    # Hugging Face (revision ci-dessus), le paquet Python vit sur GitHub, et je
    # n'ai releve aucun commit de ce depot-la. Fabriquer un SHA plausible serait
    # pire que l'avouer. Meme reserve que la LoRA de /chanson, dite au meme
    # endroit : dans la fiche du travail et sur la page.
    "code_revision": None,
    "licence": "Apache 2.0",
    "restriction": "la licence elle-meme n'interdit rien, usage commercial compris",
    # LA NUANCE QUI COMPTE, ET QUI N'EST PAS DANS LA LICENCE. Le README des
    # auteurs ecrit que cette capacite est << intended solely for academic
    # research purposes >>. Une licence Apache 2.0 et cette phrase ne disent pas
    # la meme chose. Le Studio ne tranche pas a la place de l'utilisateur : il
    # affiche LES DEUX, la ou le modele se choisit.
    "reserve_auteurs": "leurs auteurs ecrivent pourtant que cette capacite est "
                       "« intended solely for academic research purposes » : la licence "
                       "et cette phrase ne disent pas la meme chose",
    # << pas trouvee >> n'est pas << inexistante >> : deux verifications
    # independantes n'ont rien montre, mais le fichier de licence brut n'a pas
    # ete lu ligne a ligne.
    "territoire": "aucune restriction de pays trouvee",
    "langues": "anglais, chinois, japonais, coreen, francais, allemand et russe",
    "locuteurs_max": 4,
    "minutes_max": 3,
    "echantillonnage": 24000,
    "poids_go": 12.6,
    "fiche": "https://huggingface.co/FireRedTeam/FireRedTTS2",
}

# Ce qui se telecharge, et ce qui ne se telecharge PAS.
#
# Le depot pese environ 20,9 Go, dont DEUX modeles de langue de 8,27 Go chacun.
# La source choisit l'un ou l'autre selon le mode :
#     if gen_type == "monologue": llm_ckpt_path = ... "llm_pretrain.pt"
#     else:                       llm_ckpt_path = ... "llm_posttrain.pt"
# Le mode dialogue ne lit donc JAMAIS llm_pretrain.pt. Le laisser de cote fait
# passer le premier telechargement de 20,9 a 12,6 Go -- 8,27 Go de moins a payer
# au tarif de la carte, puisque le compteur facture le temps d'horloge.
FICHIERS_MODELE = (
    "config_llm.json",
    "config_codec.json",
    "codec.pt",
    "llm_posttrain.pt",
    "Qwen2.5-1.5B/*",
)

# Dependances d'inference, etablies en lisant les imports un fichier apres
# l'autre plutot qu'en recopiant le requirements.txt de l'amont -- lequel est
# INCOMPLET : il oublie huggingface_hub, dont llm.py a pourtant besoin
# (PyTorchModelHubMixin). Le suivre a la lettre donnerait une image qui tombe au
# premier import.
#
# torchtune EST necessaire : fireredtts2/llm/modules.py fait
# << from torchtune.models.qwen2 import qwen2 >> et construit par la tous les
# transformeurs. Une premiere lecture, arretee un cran trop haut (llm.py, qui ne
# fait que re-exporter), avait conclu l'inverse ; descendre d'un fichier a
# renverse la conclusion.
#
# torchao n'est importe NULLE PART dans ce qui a ete lu. Il reste ici parce
# qu'il figure au requirements.txt de l'amont et que torchtune peut l'appeler
# en interne : l'ajouter coute des secondes de processeur a la construction,
# l'omettre couterait un travail GPU mort a l'import.
#
# Ecartes : gradio, optuna, tensorboard -- interface de demonstration et
# outillage de developpement, rien que l'inference appelle.
#
# AUCUNE VERSION N'EST EPINGLEE, et c'est un defaut ASSUME plutot qu'un oubli :
# le requirements.txt de l'amont n'epingle rien non plus, et je n'ai verifie
# aucun numero de mon cote. Epingler une version non verifiee reviendrait a
# inventer un chiffre. La construction de l'image est le test, et c'est le test
# BON MARCHE : Modal la facture en temps PROCESSEUR, pas en temps de carte.
PAQUETS_MODAL = (
    "torch",
    "torchaudio",
    "torchtune",
    "torchao",
    "transformers",
    "huggingface_hub",
    "einops",
    "librosa",
    "tqdm",
    "git+" + MODELE["code"] + ".git",
)
# git+https:// a besoin de git dans l'image.
APT_MODAL = ("git",)

# Bornes de la demande. Trois minutes de dialogue, plafond annonce par les
# auteurs ; le reste est taille pour rester dessous sans calcul savant.
MAX_CARACTERES = 6000
MAX_REPLIQUES = 80
LOCUTEURS_MAX = int(MODELE["locuteurs_max"])
# La balise se colle au texte, sans espace : c'est la forme exacte des exemples
# des auteurs ([S1]..., [S2]...). preparer() la reconstruit pour que ce soit
# vrai meme si l'utilisateur a laisse une espace derriere.
BALISE = re.compile(r"^\[S([1-9][0-9]*)\]")


# --- Compteur de depense ------------------------------------------------------

def _mois_courant() -> str:
    return time.strftime("%Y-%m")


def budget_lire() -> dict:
    """Etat du mois en cours. Un mois neuf remet les compteurs a zero."""
    donnees = {"mois": _mois_courant(), "secondes": 0.0, "usd": 0.0, "dialogues": 0}
    try:
        brut = json.loads(BUDGET_FICHIER.read_text(encoding="utf-8"))
        if brut.get("mois") == donnees["mois"]:
            donnees.update({
                "secondes": float(brut.get("secondes", 0)),
                "usd": float(brut.get("usd", 0)),
                "dialogues": int(brut.get("dialogues", 0)),
            })
    except (OSError, ValueError, TypeError):
        pass
    donnees["plafond_usd"] = BUDGET_MENSUEL_USD
    donnees["credit_offert_usd"] = CREDIT_OFFERT_USD
    donnees["reste_usd"] = max(0.0, BUDGET_MENSUEL_USD - donnees["usd"])
    donnees["prix_releve_le"] = PRIX_RELEVE_LE
    return donnees


def budget_ecrire(secondes: float, usd: float, dialogues: int) -> None:
    BUDGET_FICHIER.parent.mkdir(parents=True, exist_ok=True)
    tmp = BUDGET_FICHIER.with_suffix(".tmp")
    tmp.write_text(json.dumps({
        "mois": _mois_courant(),
        "secondes": round(secondes, 1),
        "usd": round(usd, 4),
        "dialogues": dialogues,
        "note": "Estimation locale, pas une facture. Le compte qui fait foi est "
                "celui de Modal. Ce plafond est a part de ceux de la chanson et "
                "de la video. Supprimez ce fichier pour repartir de zero.",
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(BUDGET_FICHIER)


def prix_seconde(gpu: str) -> float:
    """Carte + processeur + memoire demandee, par seconde.

    Une carte inconnue est comptee au prix de la plus chere connue : se tromper
    vers le haut est le bon sens du refus.
    """
    carte = PRIX_GPU_USD_S.get(gpu.upper(), max(PRIX_GPU_USD_S.values()))
    coeurs = float(os.getenv("MODAL_CPU", "1.0"))
    return carte + PRIX_CPU_USD_S * coeurs + PRIX_MEMOIRE_USD_S * MEMOIRE_MB / 1024


def budget_verifier(gpu: str, duree_max_s: int) -> dict:
    """Refuse AVANT de lancer si le pire cas depasse le plafond du mois."""
    etat = budget_lire()
    pire = prix_seconde(gpu) * duree_max_s
    if etat["usd"] + pire > BUDGET_MENSUEL_USD:
        raise BudgetDepasse(
            f"Plafond du mois atteint pour les dialogues. Déjà dépensé ce mois-ci : "
            f"{etat['usd']:.2f} $ sur {BUDGET_MENSUEL_USD:.2f} $. Un dialogue peut "
            f"coûter jusqu'à {pire:.2f} $ sur Modal, donc il n'est pas lancé. "
            f"Le compteur repart tout seul le 1er du mois prochain."
        )
    etat["cout_max_usd"] = round(pire, 3)
    return etat


def budget_consommer(gpu: str, secondes: float) -> dict:
    """Encaisse le temps reellement passe, meme si le dialogue a echoue."""
    with _VERROU:
        etat = budget_lire()
        secondes_total = etat["secondes"] + max(0.0, secondes)
        usd_total = etat["usd"] + prix_seconde(gpu) * max(0.0, secondes)
        budget_ecrire(secondes_total, usd_total, etat["dialogues"] + 1)
    return budget_lire()


class BudgetDepasse(RuntimeError):
    """Le plafond mensuel serait franchi : rien n'est lance."""


# --- Le script envoye sur la machine distante ---------------------------------

_SCRIPT = r'''# -*- coding: utf-8 -*-
"""Rend un dialogue a plusieurs voix avec FireRedTTS-2. Genere par Free AI Studio.

Rien ne s'installe ici : tout est dans l'image Modal, construite une fois puis
mise en cache. Seuls les poids se telechargent, et seulement ceux du mode
dialogue.
"""
import base64, json, os, sys, time

DEBUT = time.time()
D = json.loads(base64.b64decode("__DEMANDE__").decode("utf-8"))
SORTIE = os.environ.get("FREE_AI_OUTPUT_DIR", "/tmp/free_ai_output")
os.makedirs(SORTIE, exist_ok=True)
if D.get("cache"):
    os.makedirs(D["cache"], exist_ok=True)
    os.environ["HF_HOME"] = D["cache"]
# Pose AVANT le premier import de torch, sinon ignore en silence.
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
AVERTISSEMENTS = []
TEMPS = {}

import torch

if not torch.cuda.is_available():
    print("ECHEC : aucune carte graphique sur cette machine.", file=sys.stderr)
    sys.exit(2)

nom_gpu = torch.cuda.get_device_name(0)
vram_go = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
# Les auteurs annoncent 9 Go en bfloat16, 14 Go sinon. On ne REFUSE pas une
# carte sans bfloat16 -- elle peut suffire -- mais on le dit dans le resume.
BF16 = torch.cuda.get_device_capability(0) >= (8, 0)
print("Carte : %s, %.1f Go. bfloat16 : %s." % (nom_gpu, vram_go, "oui" if BF16 else "non"), flush=True)

# Seuls les fichiers du mode dialogue. llm_pretrain.pt (8,27 Go) sert au mode
# monologue et n'est JAMAIS lu ici : le telecharger serait 8,27 Go payes au
# tarif de la carte pour un fichier qui ne sera pas ouvert.
from huggingface_hub import snapshot_download

t0 = time.time()
print("Telechargement des poids (environ %.1f Go la premiere fois) ..." % D["poids_go"], flush=True)
DOSSIER = snapshot_download(
    D["modele"],
    revision=D["revision"],
    allow_patterns=list(D["fichiers"]),
)
TEMPS["telechargement"] = round(time.time() - t0, 1)
print("Poids prets en %.0f s : %s" % (TEMPS["telechargement"], DOSSIER), flush=True)

manquants = [n for n in D["fichiers"] if "*" not in n
             and not os.path.exists(os.path.join(DOSSIER, n))]
if manquants:
    print("ECHEC : fichiers absents du depot apres telechargement : %s. La revision "
          "epinglee ne contient pas ce qui est attendu." % ", ".join(manquants), file=sys.stderr)
    sys.exit(4)

t0 = time.time()
from fireredtts2.fireredtts2 import FireRedTTS2

moteur = FireRedTTS2(pretrained_dir=DOSSIER, gen_type="dialogue", device="cuda")
TEMPS["chargement"] = round(time.time() - t0, 1)
print("Modele pret en %.0f s" % TEMPS["chargement"], flush=True)

t0 = time.time()
# Aucun son de reference n'est fourni : prompt_wav_list et prompt_text_list sont
# facultatifs. Le modele invente donc les voix, et rien ne garantit qu'elles
# soient les memes au rendu suivant. C'est dit sur la page, pas seulement ici.
son = moteur.generate_dialogue(text_list=list(D["repliques"]))
TEMPS["rendu"] = round(time.time() - t0, 1)

import torchaudio

chemin = os.path.join(SORTIE, "dialogue.wav")
torchaudio.save(chemin, son, D["echantillonnage"])

echantillons = int(son.shape[-1])
secondes_audio = round(echantillons / float(D["echantillonnage"]), 1)
print("Dialogue rendu : %.1f s d'audio en %.0f s de calcul" % (secondes_audio, TEMPS["rendu"]), flush=True)

for message in AVERTISSEMENTS:
    print("AVERTISSEMENT : " + message, flush=True)

resume = {
    "fichier": "dialogue.wav",
    "octets": os.path.getsize(chemin),
    "secondes_audio": secondes_audio,
    "echantillonnage": int(D["echantillonnage"]),
    "repliques": len(D["repliques"]),
    "locuteurs": sorted(set(D["locuteurs"])),
    "modele": "%s@%s" % (D["modele"], D["revision"][:12]),
    "code_revision": D["code_revision"] or "non epinglee (main)",
    "carte": nom_gpu,
    "precision": "bfloat16 disponible" if BF16 else "sans bfloat16",
    "voix": "inventees par le modele, aucun son de reference fourni",
    "temps": TEMPS,
    "avertissements": AVERTISSEMENTS,
    "secondes_calcul": round(time.time() - DEBUT, 1),
}
with open(os.path.join(SORTIE, "resume.json"), "w", encoding="utf-8") as f:
    json.dump(resume, f, ensure_ascii=False, indent=2)
print(json.dumps(resume, ensure_ascii=False), flush=True)
'''


def construire_script(demande: dict) -> str:
    """Le script autonome, demande comprise : un seul fichier part."""
    charge = base64.b64encode(
        json.dumps(demande, ensure_ascii=False).encode("utf-8")
    ).decode("ascii")
    return _SCRIPT.replace("__DEMANDE__", charge)


def preparer(payload: dict) -> dict:
    """Traduit ce que la page a envoye en une demande complete et bornee.

    Refuse AVANT de lancer tout ce qui ferait echouer le travail une fois la
    carte payee : ligne sans balise, balise hors des quatre locuteurs, replique
    vide, texte trop long.
    """
    texte = str(payload.get("texte") or "").replace("\r\n", "\n").strip()
    if not texte:
        raise ValueError(
            "Écrivez le dialogue, une réplique par ligne, en commençant chaque ligne "
            "par [S1] ou [S2].")
    if len(texte) > MAX_CARACTERES:
        raise ValueError(
            f"Dialogue trop long ({len(texte)} caractères, {MAX_CARACTERES} au plus). "
            f"Le modèle ne tient que trois minutes.")

    repliques = []
    locuteurs = []
    for numero, ligne in enumerate((l.strip() for l in texte.split("\n")), 1):
        if not ligne:
            continue
        marque = BALISE.match(ligne)
        if not marque:
            raise ValueError(
                f"Ligne {numero} : il manque la balise du locuteur. Chaque réplique "
                f"commence par [S1], [S2]… — par exemple « [S1]Bonjour, tu as vu ça ? ». "
                f"Ligne reçue : « {ligne[:60]} »")
        qui = int(marque.group(1))
        if not 1 <= qui <= LOCUTEURS_MAX:
            raise ValueError(
                f"Ligne {numero} : le locuteur [S{qui}] n'existe pas. Ce modèle gère "
                f"{LOCUTEURS_MAX} locuteurs au plus, de [S1] à [S{LOCUTEURS_MAX}].")
        corps = ligne[marque.end():].strip()
        if not corps:
            raise ValueError(f"Ligne {numero} : la réplique de [S{qui}] est vide.")
        # La balise se colle au texte, sans espace : forme exacte des exemples
        # des auteurs. On la reconstruit plutot que de faire confiance a la
        # frappe de l'utilisateur.
        repliques.append("[S%d]%s" % (qui, corps))
        locuteurs.append(qui)

    if not repliques:
        raise ValueError("Le dialogue ne contient aucune réplique.")
    if len(repliques) > MAX_REPLIQUES:
        raise ValueError(
            f"Dialogue trop découpé ({len(repliques)} répliques, {MAX_REPLIQUES} au plus).")

    distincts = sorted(set(locuteurs))
    demande = {
        "modele": MODELE["hf"],
        "revision": MODELE["revision"],
        "code_revision": MODELE["code_revision"],
        "fichiers": list(FICHIERS_MODELE),
        "poids_go": MODELE["poids_go"],
        "echantillonnage": MODELE["echantillonnage"],
        "repliques": repliques,
        "locuteurs": distincts,
        "cache": CACHE_MODAL,
    }
    return {
        "gpu": GPU_MODAL,
        "demande": demande,
        "resume_public": {
            "modele": MODELE["hf"],
            # La licence ET la phrase des auteurs, ensemble : elles ne disent pas
            # la meme chose, et la fiche du travail ne doit pas n'en garder qu'une.
            "licence": MODELE["licence"] + " — " + MODELE["restriction"]
                       + " ; " + MODELE["reserve_auteurs"],
            "territoire": MODELE["territoire"],
            "carte": GPU_MODAL + " (Modal)",
            "repliques": len(repliques),
            "locuteurs": distincts,
            "caracteres": len(texte),
            "voix_inventees": True,
            "code_revision_epinglee": MODELE["code_revision"] is not None,
        },
    }


# --- La page ------------------------------------------------------------------

PAGE_HTML = r"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dialogue — Free AI Studio</title>
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
textarea{font:inherit;width:100%;box-sizing:border-box;height:230px;padding:12px;
 border-radius:12px;border:1px solid #999}
label.titre{display:block;font-weight:600;margin:16px 0 6px}
pre{background:#f6f6f6;border:1px solid #ddd;border-radius:12px;padding:12px;
 overflow-x:auto;white-space:pre-wrap;word-break:break-word;font-size:.82rem}
audio{width:100%;margin-top:12px}
.ok{color:#1d6b32}.ko{color:#9b2116}
button.danger{background:#9b2116;color:#fff;border-color:#9b2116;cursor:pointer}
.avert{font-size:.86rem;opacity:.75}
button.discret{font:inherit;font-size:.86rem;padding:5px 10px;border-radius:8px;
 border:1px solid #666;background:#fff;color:#222;cursor:pointer;margin-right:8px}
.licence{padding:10px 14px;border-radius:12px;border:1px solid #d9ad63;background:#fdf6e8;font-size:.9rem}
.jauge{height:9px;border-radius:999px;background:#e6e6e6;overflow:hidden;margin:6px 0 2px}
.jauge span{display:block;height:100%;background:#5b8c5a}
.pied{margin-top:26px;padding-top:16px;border-top:1px solid #ddd;font-size:.9rem;opacity:.8}
</style>
</head><body>
<h1>🎙️ Faire parler deux voix</h1>
<p class="sous">Écrivez un dialogue, une réplique par ligne : le modèle le joue en audio,
les voix se répondent, façon podcast. Jusqu’à trois minutes et quatre locuteurs.</p>

<div id="banniere" class="banniere">Vérification en cours…</div>

<label class="titre" for="texte">Le dialogue</label>
<textarea id="texte" maxlength="6000" placeholder="[S1]Tu as vu qu’on peut faire parler deux voix maintenant ?
[S2]Attends, c’est le modèle qui invente les deux ?
[S1]Oui, on écrit juste le texte, une réplique par ligne.
[S2]Et il fait les silences, les hésitations, tout ça ?
[S1]D’après ses auteurs, oui. Nous, on n’a encore rien écouté."></textarea>
<p class="avert">Commencez chaque ligne par <code>[S1]</code>, <code>[S2]</code>,
<code>[S3]</code> ou <code>[S4]</code>, collé au texte. Une ligne sans balise est refusée
<b>avant</b> de lancer, pour ne pas payer un calcul qui échouera.</p>
<p><button type="button" id="modele-texte" class="discret">Utiliser cet exemple</button>
<span id="note-texte" class="avert"></span></p>

<div class="ligne">
  <button id="lancer" class="primaire">Faire parler</button>
  <span class="avert">Sur Modal uniquement — voir plus bas pourquoi.</span>
</div>
<p id="licence" class="licence"></p>
<p id="reserves" class="avert"></p>

<div id="etat" class="ligne"></div>
<div class="ligne"><button id="arreter" class="danger" hidden>⛔ Arrêt d’urgence</button>
<span id="arreter-texte" class="avert"></span></div>
<details id="detailJournal" hidden><summary>Voir le détail technique</summary>
<pre id="journal"></pre></details>
<div id="resultat"></div>

<div class="pied" id="pied"></div>

<script>
const CLE = "__CLE__";
const ENTETES = {"Authorization":"Bearer "+CLE, "Content-Type":"application/json"};
let minuteur = null;
let ETAT = null;

const TEXTE_ORIGINE = document.getElementById("texte").placeholder;

// L'exemple en grise disparait au premier caractere : il ne sert qu'une fois.
// Ce bouton le DEPOSE dans le champ, ou il devient modifiable. On n'ecrase
// JAMAIS un texte deja saisi : effacer le travail de l'utilisateur d'un clic
// serait pire que l'absence du bouton.
document.getElementById("modele-texte").addEventListener("click", () => {
  const champ = document.getElementById("texte");
  const note = document.getElementById("note-texte");
  if(champ.value.trim()){
    note.textContent = "Le champ n’est pas vide : je n’efface pas ce que vous avez écrit.";
    return;
  }
  champ.value = TEXTE_ORIGINE;
  note.textContent = "";
  champ.focus();
});

function budgetTexte(b){
  const part = Math.min(100, 100 * b.usd / b.plafond_usd);
  return "Dialogues sur Modal ce mois-ci, selon le Studio : <b>" + b.usd.toFixed(2)
    + " $</b> sur un plafond de " + b.plafond_usd.toFixed(2) + " $. " + b.dialogues + " dialogue(s)."
    + '<div class="jauge"><span style="width:' + part.toFixed(1) + '%"></span></div>'
    + '<span class="avert">Estimation locale d’après les prix relevés le ' + b.prix_releve_le
    + ', pas une facture. Ce plafond est <b>à part</b> de ceux de la chanson et de la vidéo, '
    + 'et aucun des trois ne voit les deux autres : additionnés, ils atteignent exactement le '
    + 'crédit de ' + b.credit_offert_usd.toFixed(0) + ' $ que vous avez déclaré. '
    + '<a href="https://modal.com/settings/usage" target="_blank" rel="noopener">Réglez votre '
    + 'limite de dépense chez Modal</a> : c’est le seul compte qui fait foi.</span>';
}

function echapper(t){
  return String(t).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[c]));
}

// La licence se dit A L'ENDROIT DU CHOIX, pas en note de bas de page. Ici elle
// est DOUBLE, et c'est tout l'interet : Apache 2.0 n'interdit rien, mais les
// auteurs ecrivent << solely for academic research purposes >>. Le Studio ne
// tranche pas a la place de l'utilisateur, il montre les deux.
function rafraichir(){
  return fetch("/dialogue/etat", {headers:{"Authorization":"Bearer "+CLE}})
    .then(r => r.json())
    .then(d => {
      ETAT = d;
      document.getElementById("banniere").innerHTML = budgetTexte(d.budget);
      const m = d.modele;
      document.getElementById("licence").innerHTML = "Modèle <a href=\"" + m.fiche
        + "\" target=\"_blank\" rel=\"noopener\">" + m.hf + "</a> : poids sous licence <b>"
        + m.licence + "</b> — " + m.restriction + ". <b>Mais " + m.reserve_auteurs
        + ".</b> Le Studio affiche les deux et ne tranche pas à votre place : pour un usage "
        + "commercial, lisez la fiche du modèle. " + m.territoire
        + ". Il parle " + m.langues + ".";
      const reserves = [
        "Les voix ne sont pas choisies : aucun son de référence n’est envoyé, le modèle "
        + "les invente, et rien ne garantit qu’elles soient les mêmes d’un rendu à l’autre.",
        "<b>Le français n’est mesuré par personne.</b> Le modèle l’annonce parmi ses "
        + m.langues.split(",").length + " langues, mais aucun banc d’essai public ne le note : "
        + "tous portent sur le mandarin et l’anglais. Personne n’a encore écouté ce que ça donne.",
        "Le coût n’est pas annoncé parce qu’il n’a jamais été mesuré pour ce modèle. Le seul "
        + "repère du Studio est la chanson, à 0,044 $ pour deux minutes sur la même carte.",
        "Modal uniquement : le chemin gratuit de la chanson (carte T4 de Kaggle) a été essayé "
        + "en vrai, celui-ci ne l’a jamais été. Proposer un endroit non vérifié reviendrait à "
        + "vous vendre un essai dont personne ne connaît le résultat."
      ];
      if(!m.code_revision){
        reserves.push("Les <b>poids</b> sont épinglés à une révision précise, mais le "
          + "<b>code</b> est installé depuis la branche principale de son dépôt, sans "
          + "révision fixée : si le dépôt change, ce rendu n’est plus reproductible à "
          + "l’identique.");
      }
      document.getElementById("reserves").innerHTML = "· " + reserves.join("<br>· ");
      document.getElementById("pied").innerHTML = "Rien ne part chez un fournisseur d’IA : le "
        + "modèle tourne sur une machine que vous louez."
        + '<br><a href="/">Retour au Sandbox</a> &nbsp; <a href="/cles">Brancher Modal ou Kaggle</a>';
      return d;
    })
    .catch(() => {
      document.getElementById("banniere").textContent =
        "État non vérifiable : le service Sandbox ne répond pas.";
    });
}

function condenser(t){
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
  const d = new Date();
  const jour = d.getFullYear() + "-" + String(d.getMonth()+1).padStart(2,"0") + "-"
    + String(d.getDate()).padStart(2,"0");
  const heure = String(d.getHours()).padStart(2,"0") + "h" + String(d.getMinutes()).padStart(2,"0");
  const mots = document.getElementById("texte").value.replace(/\[S\d+\]/g, " ")
    .normalize("NFD").replace(/[^\x00-\x7F]/g, "")
    .toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+/, "").slice(0, 40).replace(/-+$/, "");
  return jour + "-" + heure + "-" + (mots || "dialogue") + ".wav";
}

function afficherDialogue(j){
  const r = j.resume || {};
  const nom = nomDeFichier();
  const lien = j.son_url + "&telecharger=1&nom=" + encodeURIComponent(nom);
  let html = '<audio id="lecteur" controls src="' + j.son_url + '"></audio>'
    + '<div class="ligne"><a class="bouton" href="' + lien + '" download="' + nom + '">⬇️ Télécharger le dialogue</a>'
    + '<span class="avert">Fichier WAV, ' + (r.echantillonnage || 24000) / 1000 + ' kHz.</span></div>';
  const notes = [];
  if(r.locuteurs) notes.push("Locuteurs entendus : " + r.locuteurs.map(n => "[S" + n + "]").join(", ")
    + " sur " + r.repliques + " réplique(s).");
  notes.push("Les voix ont été inventées par le modèle : un nouveau rendu du même texte "
    + "peut donner d’autres voix.");
  if(r.code_revision && r.code_revision.indexOf("non epinglee") === 0){
    notes.push("Code installé depuis la branche principale, sans révision fixée : rendu non "
      + "reproductible à l’identique.");
  }
  (r.avertissements || []).forEach(a => notes.push(echapper(a)));
  notes.push("<b>Personne n’a vérifié à l’oreille ce que ce modèle donne en français.</b>");
  html += '<p class="avert">' + notes.join("<br>") + "</p>";
  document.getElementById("resultat").innerHTML = html;
}

function suivre(id){
  const etat = document.getElementById("etat");
  minuteur = setInterval(() => {
    fetch("/dialogue/jobs/" + id, {headers:{"Authorization":"Bearer "+CLE}})
      .then(r => r.json())
      .then(j => {
        if(["running","queued","preparing","submitting"].indexOf(j.status) >= 0){
          const t = Math.round((Date.now()/1000) - (j.created_at || Date.now()/1000));
          etat.innerHTML = "⏳ En cours depuis " + t + " s. Le premier dialogue est le plus "
            + "long : environ 12,6 Go de poids se téléchargent.";
          montrerArret(id);
          return;
        }
        clearInterval(minuteur); minuteur = null;
        cacherArret();
        document.getElementById("lancer").disabled = false;
        afficherJournal([j.stdout, j.stderr].filter(Boolean).join("\n"));
        rafraichir();
        if(j.son_url){
          const r = j.resume || {};
          etat.innerHTML = '<span class="ok">✔ Dialogue prêt</span> — '
            + (r.secondes_audio ? r.secondes_audio + " s d’audio, " + r.secondes_calcul + " s de calcul" : "");
          afficherDialogue(j);
        } else if(j.status === "cancelled"){
          // Un arret VOULU n'est pas une panne : meme regle que /chanson, ou la
          // preuve que l'arret avait reussi s'affichait en rouge sous le mot
          // « Echec », et en anglais.
          etat.innerHTML = '<span class="avert">⛔ Arrêté à votre demande.</span> '
            + echapper(j.arret_detail || "");
        } else {
          etat.innerHTML = '<span class="ko">✖ Échec</span> — ' + echapper(j.message || "voir le détail technique.");
        }
      })
      .catch(() => {});
  }, 5000);
}

document.getElementById("lancer").addEventListener("click", () => {
  const bouton = document.getElementById("lancer");
  const etat = document.getElementById("etat");
  const corps = {texte: document.getElementById("texte").value};
  bouton.disabled = true;
  etat.textContent = "Envoi…";
  document.getElementById("resultat").innerHTML = "";
  afficherJournal("");
  fetch("/dialogue/creer", {method:"POST", headers:ENTETES, body:JSON.stringify(corps)})
    .then(async r => {
      const d = await r.json().catch(() => ({}));
      if(!r.ok){ throw new Error(d.detail || ("HTTP " + r.status)); }
      return d;
    })
    .then(d => { etat.textContent = "⏳ Lancé."; suivre(d.id); })
    .catch(e => {
      bouton.disabled = false;
      etat.innerHTML = '<span class="ko">✖ ' + echapper(e.message) + "</span>";
    });
});

// LE BOUTON VIT HORS DE #etat, ET C'EST VOULU. suivre() reecrit etat.innerHTML
// toutes les 5 secondes : un bouton pose dedans serait detruit et recree a
// chaque tour, et l'etat << Arret demande... >> disparaitrait sous les doigts.
let travailEnCours = null;

function montrerArret(id){
  travailEnCours = id;
  const b = document.getElementById("arreter");
  if(b.hidden){ b.hidden = false; b.disabled = false; b.textContent = "⛔ Arrêt d’urgence"; }
}

function cacherArret(){
  travailEnCours = null;
  document.getElementById("arreter").hidden = true;
  document.getElementById("arreter-texte").textContent = "";
}

document.getElementById("arreter").addEventListener("click", () => {
  if(!travailEnCours){ return; }
  const b = document.getElementById("arreter");
  const t = document.getElementById("arreter-texte");
  b.disabled = true;
  b.textContent = "Arrêt demandé…";
  fetch("/jobs/" + travailEnCours + "/arreter", {method:"POST", headers:ENTETES})
    .then(async r => {
      const d = await r.json().catch(() => ({}));
      if(!r.ok){ throw new Error(d.detail || ("HTTP " + r.status)); }
      return d;
    })
    .then(d => { t.textContent = d.detail || ""; })
    .catch(e => {
      b.disabled = false;
      b.textContent = "⛔ Arrêt d’urgence";
      t.innerHTML = '<span class="ko">✖ ' + echapper(e.message) + "</span>";
    });
});

rafraichir();
</script>
</body></html>"""
