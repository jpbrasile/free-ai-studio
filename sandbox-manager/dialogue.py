"""Dialogues a deux voix (facon podcast), rendus par FireRedTTS-2 sur un GPU loue.

Un script a plusieurs locuteurs, balise ligne par ligne, rendu en un seul fichier
audio ou les voix se repondent. Ce n'est PAS la synthese vocale du routeur
(/v1/audio/speech, Piper, une voix par langue, sur processeur) : ici le modele
fabrique une conversation, pas une lecture.

DEUX ENDROITS, ET CHACUN A TOURNE EN VRAI : Modal et Kaggle. Cette page n'a
longtemps propose que Modal, parce que rien n'avait jamais tourne ailleurs. Ce
motif a cesse d'exister le 17/09/2026, par deux mesures et non par un
raisonnement : sur UNE Tesla T4 de Kaggle, pic de 12,13 Go sur 14,56 pour 9,5 s
d'audio, puis 12,95 Go pour 147,5 s -- 1,61 Go de marge, en float32, sans
bfloat16. Le << non >> ecrit le matin meme partait des 14 Go annonces par les
auteurs, pris pour une mesure alors que le vrai cout etait 12,13.

COLAB RESTE REFUSE, et pas par prudence vague : la mesure du 16/09 est deja
payee par ce projet (chanson.py:678). Colab gratuit est mort faute de MEMOIRE
VIVE (~12,7 Go, une seule carte) avec une chanson de 7 Go ; ce modele-ci pese
12,6 Go de poids, qui transitent par la RAM au chargement.

CE QUE KAGGLE COUTE, ET QU'IL FAUT DIRE : x3,35 le temps reel (494 s de calcul
pour 148 s d'audio), soit de l'ordre de douze minutes d'attente de bout en bout
pour deux minutes et demie de dialogue, telechargement des poids compris. C'est gratuit,
pas rapide.

LA BORNE EST CELLE DE LA MESURE, PAS CELLE DE L'ANNONCE. 147,5 s ne sont pas les
180 s annoncees par les auteurs : le maximum reel n'a jamais ete atteint. La
route refuse donc sur Kaggle au-dela de ce qui a REELLEMENT tourne, plutot que
d'extrapoler -- c'est en prenant une extrapolation pour un fait que le faux
<< non >> du matin a ete ecrit.

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

# CE QUI ETAIT ECRIT ICI, et qui a ete repare le 19/09/2026 :
#
#   << ARITHMETIQUE A DIRE TOUT HAUT : 5 (chanson) + 20 (video) + 5
#   (dialogue) = 30 $, soit EXACTEMENT le credit Modal que l'utilisateur
#   declare. Les trois compteurs sont etanches -- aucun ne voit les deux
#   autres -- donc les trois peuvent atteindre leur plafond le meme mois et
#   le total sortirait du credit. >>
#
# Le depot avait donc ECRIT son propre defaut sans le corriger, et le
# renvoyait a la limite de depense reglee chez Modal. C'etait vrai et
# insuffisant : un garde-fou qui delegue sa garde n'en est pas un. Il y a
# desormais UN plafond pour les quatre usages, ce module compris.
BUDGET_MENSUEL_USD = budget_modal.plafond_de("dialogue")
CREDIT_OFFERT_USD = budget_modal.CREDIT_OFFERT_USD

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

# --- Kaggle, ouvert le 17/09/2026 apres deux mesures reelles ------------------
# Kaggle choisit la carte d'apres machine_shape. Les deux essais ont tourne sur
# une Tesla T4 ; le script n'a besoin que d'une seule carte, la seconde ne sert a
# rien ici (FireRedTTS2 est construit avec device="cuda", donc la carte 0 seule).
KAGGLE_MACHINE = os.getenv("DIALOGUE_KAGGLE_MACHINE", "NvidiaTeslaT4")
# Mesure du 17/09 : 720,4 s de bout en bout pour le dialogue le plus long
# (installation 23,4 s, poids 86 s, chargement 107,8 s, rendu 494,1 s). Le delai
# laisse une marge large -- Kaggle coupe lui-meme a l'echeance, et un notebook
# coupe trop tot serait un quota perdu pour rien.
KAGGLE_DELAI_S = int(os.getenv("DIALOGUE_KAGGLE_TIMEOUT_SECONDS", "3600"))

MODELE = {
    "hf": "FireRedTeam/FireRedTTS2",
    # Revision epinglee le 17/09/2026. Ce n'est pas qu'une question de
    # reproductibilite : les poids sont des fichiers .pt, c'est-a-dire des
    # pickles, et torch.load(weights_only=False) execute ce qu'ils contiennent.
    # Epingler le commit est ici une barriere de securite.
    "revision": "4af3f5cc4963373b86b52d750220d4de85261f05",
    "code": "https://github.com/FireRedTeam/FireRedTTS2",
    # EPINGLEE le 17/09/2026. Elle est restee ouverte deux commits durant, faute
    # d'avoir releve le moindre commit de ce depot -- un manque avoue plutot
    # qu'un SHA plausible invente. Ceci est la tete de la branche principale,
    # datee du 26/10/2025 : le depot n'a pas bouge depuis onze mois, donc
    # l'epingler ne coute aucune maintenance. Meme motif que pour les poids :
    # c'est ce code-la qui appelle torch.load sur des pickles.
    "code_revision": "404f3f61d25bb4804859b588a6a734bf8468090c",
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

# COMMENT CE PAQUET S'INSTALLE -- ET POURQUOI PAS COMME JE L'AVAIS CRU.
#
# Deux lancements payes ont ete perdus a RECONSTRUIRE une procedure
# d'installation au lieu de LIRE celle des auteurs. Elle tient en quatre
# commandes, et COMMANDES_MODAL la reproduit telle quelle :
#     git clone ... && cd FireRedTTS2
#     pip install torch torchvision torchaudio   (index PyTorch)
#     pip install -e .
#     pip install -r requirements.txt
#
# LE PIEGE, paye au tarif de la carte le 17/09/2026 :
#     ModuleNotFoundError: No module named 'fireredtts2.utils'
# Leur setup.py tient en une ligne -- setup(name="fireredtts2", version="0.1",
# packages=find_packages()) -- et fireredtts2/utils/ ne contient QUE spliter.py,
# sans __init__.py. find_packages() ne retient que les dossiers qui en ont un :
# << pip install git+... >> livre donc un paquet AMPUTE. Verifie sur le depot :
# llm/ et codec/ ont le leur, utils/ non -- le trou est unique, il n'y a pas une
# seconde panne identique derriere.
#
# Les auteurs ne peuvent pas voir ce trou : << pip install -e . >> laisse
# l'arborescence source en place, ou un dossier sans __init__.py s'importe quand
# meme comme paquet-espace-de-noms. AUCUNE lecture des imports, si soigneuse
# soit-elle, ne pouvait reveler ca : ce n'est pas une dependance manquante,
# c'est un paquet mutile par l'installation. La procedure etait la seule source.
#
# CE QUI RESTE DANS CETTE LISTE, ET SA REGLE : exactement ce que le
# requirements.txt de l'amont ne peut pas donner -- ce qu'il OUBLIE, et ce qu'il
# SOUS-SPECIFIE. Rien d'autre. Je ne trie plus ce que les auteurs installent :
# gradio, optuna, accelerate et tensorboard partent desormais dans l'image via
# leur fichier, alors qu'un commentaire precedent les ecartait comme outillage
# de demonstration. Ce tri etait sans doute juste, mais il n'etait qu'un
# raisonnement, et aucune mesure ne le soutient -- alors que deux mesures
# condamnent l'ecart a la procedure documentee. Une construction ratee se paie
# en temps PROCESSEUR ; une dependance oubliee se paie au tarif de la CARTE,
# apres le telechargement des poids. L'asymetrie tranche seule.
#
# L'ORDRE EST LE CORRECTIF. Ces paquets sont poses AVANT les commandes, et c'est
# ce qui sauve les epingles : le requirements.txt de l'amont demande
# << torchao >> et << torchtune >> SANS version, une contrainte nue est
# satisfaite par n'importe quelle version deja installee, et pip ne met a niveau
# que sur -U. Dans l'autre ordre, la commande officielle remonterait torchao en
# silence et rejouerait la panne de ce matin.
#
# torchtune EST necessaire : fireredtts2/llm/modules.py fait
# << from torchtune.models.qwen2 import qwen2 >> et construit par la tous les
# transformeurs. Une premiere lecture, arretee un cran trop haut (llm.py, qui ne
# fait que re-exporter), avait conclu l'inverse ; descendre d'un fichier a
# renverse la conclusion.
#
# torchao EST necessaire, et le premier lancement l'a prouve. Il n'apparait dans
# aucun import de fireredtts2 : il etait garde par pari, parce qu'il figure au
# requirements.txt de l'amont et que torchtune pouvait l'appeler en interne.
# C'est exactement ce qui arrive -- torchtune/modules/common_utils.py fait
# << from torchao.dtypes.nf4tensor import NF4Tensor >>. Le pari etait bon.
#
# DEUX VERSIONS EPINGLEES, ET CHACUNE EST UN NUMERO RELEVE, PAS CHOISI AU JUGE.
#
# Premier lancement, 17/09/2026 : l'image s'est construite, les poids se sont
# telecharges (14 fichiers, 66 s), puis le travail est mort a l'import sur
#     ModuleNotFoundError: No module named 'torchao.dtypes.nf4tensor'
# leve depuis torchtune/modules/common_utils.py. Noter l'endroit : PAS
# << No module named 'torchao' >>. torchao etait bien installe ; c'est le chemin
# du sous-module qui n'existait plus.
#
# Pourquoi pip ne pouvait pas s'en sortir seul : le pyproject.toml de torchtune
# ne declare NI torch NI torchao, alors qu'il importe les deux a l'import. Il
# n'y avait donc aucune contrainte a resoudre -- pip a pris le torchao le plus
# recent. Retirer torchao de cette liste n'aiderait pas : l'erreur deviendrait
# << No module named 'torchao' >> tout court. L'epinglage ne peut venir que
# d'ici.
#
# Ou est passe le fichier, d'apres le commit qui l'a deplace (pytorch/ao
# 60b42ac6, 13/04/2026, << Move NF4Tensor to quantization.quantize_.workflows >>) :
#     torchao/dtypes/nf4tensor.py -> torchao/quantization/quantize_/workflows/nf4/nf4_tensor.py
# et, dit par le commit lui-meme, << after this commit torchao/dtypes/ is now
# empty >>. Verifie sur main : le dossier dtypes n'y est plus du tout.
#
# La frontiere, relevee par quatre sondes sur les tags publies :
#     v0.15.0 present (40 651 o) | v0.16.0 present (41 508 o)
#     v0.17.0 present (41 508 o) | v0.18.0 ABSENT (404)
# 0.17.0 est donc la derniere version publiee qui expose le chemin attendu par
# torchtune. torchtune est epingle a 0.6.1, sa derniere version publiee, c'est-a-dire
# celle que pip installait deja : l'epingler ne change pas le comportement, il
# empeche qu'une version future rejoue la meme panne.
#
# LE RESTE N'EST TOUJOURS PAS EPINGLE, et c'est delibere : je n'ai mesure que ces
# deux numeros. Epingler les autres au juge reviendrait a inventer des chiffres.
# Ce que la prochaine construction tranchera, et qui n'est pas verifie : qu'un
# torchao de la generation 0.17 s'installe avec le torch recent que pip choisit.
# La construction reste le test, et elle reste BON MARCHE : facturee en temps
# PROCESSEUR, pas en temps de carte -- et les poids sont desormais en cache dans
# le volume Modal, donc un nouvel essai ne retelecharge pas 12,6 Go.
PAQUETS_MODAL = (
    # Ce que la procedure des auteurs installe HORS requirements.txt, depuis
    # l'index PyTorch. Sans numero, deliberement : ils epinglent
    # torch==2.7.1+cu126 pour leur Python 3.11, quand modal_execute code en dur
    # un Python 3.12. Transposer leur numero sans l'avoir verifie, ce serait
    # l'inventer.
    "torch",
    "torchaudio",
    # SOUS-SPECIFIES par leur requirements.txt, qui les demande nus. Poses ici,
    # donc AVANT lui -- c'est l'ordre explique plus haut qui sauve l'epingle.
    "torchtune==0.6.1",
    "torchao==0.17.0",
    # OUBLIES par leur requirements.txt : llm.py fait
    # << from huggingface_hub import PyTorchModelHubMixin >>, et le script du
    # travail s'en sert aussi pour snapshot_download.
    "huggingface_hub",
    "tqdm",
)
# transformers, einops et librosa ne sont plus listes ici, et gradio, optuna,
# accelerate et tensorboard n'en sont plus exclus : tous arrivent par le
# requirements.txt des auteurs, execute tel quel dans COMMANDES_MODAL. Une seule
# liste fait foi, et c'est la leur -- en maintenir une seconde a cote invitait
# la derive qui a coute les deux lancements du 17/09.

# SUR KAGGLE, torch ET torchaudio SONT RETIRES DE LA LISTE. Leur image porte
# torch 2.10.0+cu128, compile pour leur carte ; le remplacer casserait CUDA. Meme
# regle que pour la chanson (chanson.py:268), et elle est MESUREE ici : le
# 17/09, torchao 0.17.0 et torchtune 0.6.1 se sont poses sur LEUR torch sans le
# remplacer (garde explicite relisant la version apres coup, cuda: True), et
# transformers 5.0.0 n'a pas gene, alors que l'amont n'a pas ete ecrit pour cette
# version majeure. Leur image porte torchao 0.10.0, d'ou l'epingle qui compte.
PAQUETS_KAGGLE = tuple(p for p in PAQUETS_MODAL if p not in ("torch", "torchaudio"))

# LA PROCEDURE DES AUTEURS, EXECUTEE TELLE QUELLE.
#
# Elle tourne APRES les paquets ci-dessus, et cet ordre est le correctif. Il est
# MESURE, pas suppose (sonde locale, Python 3.11.5) : on pose packaging==23.0,
# puis on execute un requirements.txt qui demande << packaging >> nu. pip
# repond << Requirement already satisfied ... (23.0) >> et ne remonte rien --
# il ne met a niveau que sur -U. Nos epingles torchao et torchtune survivent
# donc au fichier de l'amont, qui les demande sans version. Dans l'autre ordre,
# la commande officielle aurait remonte torchao en silence et rejoue la panne.
#
# Le clone est COMPLET, et non --depth 1 : le commit epingle doit rester
# atteignable meme si la branche avance. S'il disparaissait, la construction
# echouerait bruyamment -- ce qui est le comportement voulu, et facture en temps
# processeur, pas en temps de carte.
DOSSIER_CODE = "/opt/FireRedTTS2"
COMMANDES_MODAL = (
    "git clone " + MODELE["code"] + ".git " + DOSSIER_CODE,
    "cd " + DOSSIER_CODE + " && git checkout " + MODELE["code_revision"],
    "cd " + DOSSIER_CODE + " && pip install -e . && pip install -r requirements.txt",
)
# git est necessaire dans l'image pour le clone ci-dessus.
APT_MODAL = ("git",)

# BORNES DE LA DEMANDE : CELLES DU MODELE, LES MEMES PARTOUT.
#
# Jusqu'au 23/09/2026 : 6 000 caracteres et 80 repliques, << tailles pour rester
# dessous sans calcul savant >> -- jamais mesures -- et une borne a part pour
# Kaggle, 2 725, dont la phrase de refus disait << ce n'est pas une limite du
# modele... choisissez Modal >>. La mesure l'a dementi : sur la 4090, un
# dialogue de 5 836 caracteres et 63 repliques a rendu 35 repliques, puis
# FireRedTTS-2 a refuse la 36e (<< Inputs too long, must be below max_seq_len -
# max_generation_len: 2725 >>). Le modele garde dans son contexte chaque
# replique deja rendue, texte ET son : c'est ce contexte qui deborde, quelle
# que soit la carte. Modal aurait donc loue une carte pour un rendu voue a
# echouer a mi-chemin.
#
# Les deux nombres sont ceux du SEUL dialogue long qui ait abouti (Kaggle,
# 17/09) : 2 725 caracteres, 35 repliques, 147,5 s d'audio. La vraie frontiere
# est quelque part entre ce dialogue et celui du 23/09 ; personne ne l'a
# cherchee, et refuser un peu trop tot coute une phrase, pas une carte payee.
MAX_CARACTERES = 2725
MAX_REPLIQUES = 35
_POURQUOI_LA_BORNE = (
    "Le modèle garde en mémoire chaque réplique déjà dite, et cette mémoire est "
    "pleine vers la 35e : au-delà il s'arrête en route, sur n'importe quelle carte. "
    "Le plus long dialogue qui ait abouti faisait 2 725 caractères et 35 répliques, "
    "environ deux minutes et demie. Raccourcissez-le, ou coupez-le en deux "
    "dialogues.")
LOCUTEURS_MAX = int(MODELE["locuteurs_max"])
# La balise se colle au texte, sans espace : c'est la forme exacte des exemples
# des auteurs ([S1]..., [S2]...). preparer() la reconstruit pour que ce soit
# vrai meme si l'utilisateur a laisse une espace derriere.
BALISE = re.compile(r"^\[S([1-9][0-9]*)\]")


# --- Compteur de depense ------------------------------------------------------
#
# UN SEUL compteur depuis le 19/09/2026 : budget_modal.py, partage avec les
# deux autres fonctions ET avec le bac a sable lui-meme, qui envoyait du code
# sur Modal sans etre compte par personne. Ce qui suit ne compte plus rien :
# ce sont des renvois, gardes pour que app.py, les tests et les pages n'aient
# pas a savoir ou vit le compteur. Le motif est en tete de budget_modal.py.


def budget_lire() -> dict:
    """L'etat du mois, TOUS usages confondus, vu du plafond de celui-ci."""
    etat = budget_modal.vue("dialogue")
    etat["dialogues"] = etat["appels"]["dialogue"]
    return etat


def budget_ecrire(secondes: float, usd: float, dialogues: int) -> None:
    """Pose l'etat de cet usage. Outil de TEST : le service passe par
    budget_consommer(), qui ajoute au lieu de poser."""
    budget_modal.poser("dialogue", secondes, usd, dialogues)


def prix_seconde(gpu: str) -> float:
    return budget_modal.prix_seconde(gpu, MEMOIRE_MB)


def budget_verifier(gpu: str, duree_max_s: int) -> dict:
    """Refuse AVANT de lancer si le pire cas entame ce qui reste a cet usage."""
    etat = budget_modal.verifier(
        "dialogue", gpu, duree_max_s, MEMOIRE_MB,
        quoi="Un dialogue", suite="")
    etat["cout_max_usd"] = etat["cout_max_usd"]
    etat["dialogues"] = etat["appels"]["dialogue"]
    return etat


def budget_consommer(gpu: str, secondes: float) -> dict:
    """Encaisse le temps reellement passe, meme si le dialogue a echoue."""
    etat = budget_modal.consommer("dialogue", gpu, secondes, MEMOIRE_MB)
    etat["dialogues"] = etat["appels"]["dialogue"]
    return etat


# LA MEME exception pour les trois, et c'etait un piege arme : un
# `except video.BudgetDepasse` attrapait jusqu'ici une classe differente de
# celle que chanson.py levait.
BudgetDepasse = budget_modal.BudgetDepasse


# --- Le script envoye sur la machine distante ---------------------------------

_SCRIPT = r'''# -*- coding: utf-8 -*-
"""Rend un dialogue a plusieurs voix avec FireRedTTS-2. Genere par Free AI Studio.

SUR MODAL, rien ne s'installe ici : tout est dans l'image, construite une fois
puis mise en cache. Seuls les poids se telechargent, et seulement ceux du mode
dialogue.

SUR KAGGLE, il n'y a pas d'image a nous : les bibliotheques et le code des
auteurs s'installent au debut de CE script, a chaque fois. Leur PyTorch est
garde tel quel -- il est compile pour leur carte.
"""
# importlib sert a invalidate_caches(), plus bas, apres l'ajout du depot a
# sys.path. Bibliotheque standard : rien a installer, sur aucune des deux
# machines.
import base64, importlib, json, os, subprocess, sys, time

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


def installer(*args):
    # sys.executable, JAMAIS le pip du PATH. Sur Kaggle ce sont deux
    # interpreteurs differents : le 17/09/2026, un << pip install -e . >> nu a
    # reussi, pose le paquet dans un autre site-packages, et le travail est mort
    # 89 s plus tard sur ModuleNotFoundError: No module named 'fireredtts2'.
    # Un quota a ete perdu pour redecouvrir un correctif qui dormait deja dans
    # le fichier voisin (chanson.py).
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", *args])


if D.get("installer"):
    # Kaggle : leur PyTorch est garde, il est compile pour leur carte.
    t0 = time.time()
    print("Installation des bibliotheques ...", flush=True)
    # NOS EPINGLES D'ABORD. Le requirements.txt de l'amont demande torchao et
    # torchtune SANS version ; une contrainte nue est satisfaite par n'importe
    # quelle version deja posee, et pip ne met a niveau que sur -U. Dans l'autre
    # ordre, la commande officielle remonterait torchao en silence et rejouerait
    # la panne ModuleNotFoundError: No module named 'torchao.dtypes.nf4tensor'.
    installer(*D["paquets"])
    depot = "/kaggle/working/FireRedTTS2"
    if not os.path.isdir(depot):
        subprocess.check_call(["git", "clone", D["code"] + ".git", depot])
    if D.get("code_revision"):
        subprocess.check_call(["git", "-C", depot, "checkout", D["code_revision"]])
    # Leur procedure, telle quelle. << pip install -e . >> et non
    # << pip install . >> : leur setup.py se reduit a find_packages(), et
    # fireredtts2/utils/ n'a pas d'__init__.py -- une installation par copie
    # livrerait un paquet AMPUTE de spliter.py. En mode editable, l'arborescence
    # source reste en place et le dossier s'importe quand meme.
    installer("-e", depot)
    installer("-r", os.path.join(depot, "requirements.txt"))
    # ET POURTANT CELA NE SUFFIT PAS ICI. Mesure du 17/09/2026, reproduite hors
    # Kaggle AVANT d'etre corrigee, sur un paquet d'essai de la meme forme :
    # une installation editable ne prend pas effet dans le processus qui la
    # lance. Elle ne copie rien -- elle depose un __editable__*.pth et un
    # finder dans site-packages -- et un .pth n'est lu qu'au DEMARRAGE de
    # l'interpreteur. Meme paquet, meme pip, meme machine : import dans le
    # processus courant -> ModuleNotFoundError ; import dans un processus neuf
    # -> succes.
    #
    # Sur Modal la question ne se pose pas : l'installation a lieu a la
    # construction de l'image, et le rendu demarre APRES, dans un interpreteur
    # neuf. Sur Kaggle, installer et importer sont le meme processus. C'est
    # toute la difference entre un chemin qui marche et un chemin mort a 83 s
    # sur << No module named 'fireredtts2' >>, poids de 12,6 Go deja payes.
    #
    # Le premier correctif, le 17/09 au matin, avait accuse le pip du PATH et
    # impose sys.executable. Il n'a rien change a cette panne : elle est revenue
    # a l'identique, parce que ce n'etait pas la cause. Il est garde -- il reste
    # juste par ailleurs -- mais on cesse de lui attribuer cette correction-ci.
    #
    # Le remede tient au chemin d'import, pas a pip, et il conserve exactement
    # ce que l'editable apportait : l'arborescence source reste en place, donc
    # fireredtts2/utils/ sans __init__.py s'importe quand meme. Les deux ont ete
    # verifies dans la reproduction.
    sys.path.insert(0, depot)
    importlib.invalidate_caches()
    TEMPS["installation"] = round(time.time() - t0, 1)
    print("Bibliotheques pretes en %.0f s" % TEMPS["installation"], flush=True)

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

# --- DEBUT ecriture du WAV (bloc exerce hors ligne par une sonde) -------------
# torchaudio.save() NE SAIT PLUS ECRIRE SEUL. Depuis sa migration vers
# TorchCodec il delegue, et TorchCodec n'est pas installe -- il reclamerait en
# prime les bibliotheques FFmpeg dans l'image. Le PREMIER rendu reel du projet
# a ete perdu ici meme, le 17/09/2026 : 80 s de chargement, 28 s de synthese,
# la parole existait en memoire, et rien ne savait l'ecrire.
#     ImportError: TorchCodec is required for save_with_torchcodec.
# Les auteurs ne voient pas ce defaut : leur torchaudio==2.7.1 ecrivait encore
# lui-meme.
#
# Ajouter torchcodec serait un TROISIEME pari sur une dependance, apres deux qui
# ont coute une carte chacun. Le module wave de la bibliotheque standard ecrit
# un WAV PCM 16 bits sans rien installer : on RETIRE une dependance au lieu d'en
# ajouter une. torchaudio reste dans l'image -- fireredtts2 s'en sert en
# interne -- on cesse seulement de lui demander d'ecrire.
#
# Forme relevee dans fireredtts2.py A LA REVISION EPINGLEE, pas supposee :
# generate_dialogue fait torch.cat([...], dim=1) puis .cpu() et rend un
# torch.Tensor (1, echantillons) float32, deja sur le processeur.
import wave

onde = son.detach().to("cpu", torch.float32)
if onde.dim() == 1:
    onde = onde.unsqueeze(0)
canaux = int(onde.shape[0])
echantillons = int(onde.shape[-1])

# NORMALISER AVANT DE BORNER. Le clamp seul ne deborde pas, mais il APLATIT :
# tout ce qui depasse 1.0 devient exactement 1.0, et une crete ecretee n'est
# plus la forme d'onde que le modele a produite. Mesure sur le rendu de 147 s du
# 17/09 : 753 echantillons colles a la pleine echelle. C'est un defaut de CE
# fichier, pas du modele -- lui rendait des valeurs au-dela de 1.0, ce qui est
# normal pour un float, et c'est a l'ecriture de faire tenir l'echelle.
# Diviser par la crete CONSERVE la forme : le rapport entre les echantillons ne
# bouge pas, seul le niveau global baisse, ce qui ne s'entend pas.
# Le clamp reste derriere, et ce n'est pas une precaution decorative : une
# valeur non finie (nan, inf) ne se normalise pas -- nan > 1.0 est faux, et
# diviser par inf viderait le fichier -- donc la condition les ecarte toutes
# deux et le bornage garde le dernier mot.
crete = float(onde.abs().max()) if echantillons else 0.0
if 1.0 < crete < float("inf"):
    onde = onde / crete
    print("Crete a %.3f : onde normalisee, aucun echantillon ecrete." % crete, flush=True)
entiers = (onde.clamp(-1.0, 1.0) * 32767.0).round().to(torch.int16)
# wave attend les canaux ENTRELACES, echantillon par echantillon : (C, N) doit
# donc etre transpose en (N, C) avant d'etre aplati. Sans quoi un futur rendu
# stereo donnerait un canal joue apres l'autre.
octets = entiers.t().contiguous().numpy().tobytes()

chemin = os.path.join(SORTIE, "dialogue.wav")
with wave.open(chemin, "wb") as fichier_wav:
    fichier_wav.setnchannels(canaux)
    fichier_wav.setsampwidth(2)
    fichier_wav.setframerate(int(D["echantillonnage"]))
    fichier_wav.writeframes(octets)
# --- FIN ecriture du WAV ------------------------------------------------------

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


def preparer(payload: dict, ou: str = "modal") -> dict:
    """Traduit ce que la page a envoye en une demande complete et bornee.

    Refuse AVANT de lancer tout ce qui ferait echouer le travail une fois la
    carte payee : ligne sans balise, balise hors des quatre locuteurs, replique
    vide, texte trop long pour le modele -- la meme borne partout, parce que
    c'est le modele qui deborde, pas la carte.
    """
    texte = str(payload.get("texte") or "").replace("\r\n", "\n").strip()
    if not texte:
        raise ValueError(
            "Écrivez le dialogue, une réplique par ligne, en commençant chaque ligne "
            "par [S1] ou [S2].")
    # Une seule borne pour les trois endroits : c'est le MODELE qui deborde,
    # pas la carte (voir MAX_CARACTERES). Aucun endroit n'est donc propose en
    # echange -- tous echoueraient au meme point.
    if len(texte) > MAX_CARACTERES:
        raise ValueError(
            f"Dialogue trop long ({len(texte)} caractères, {MAX_CARACTERES} au plus). "
            f"{_POURQUOI_LA_BORNE}")

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
            f"Dialogue trop long ({len(repliques)} répliques, {MAX_REPLIQUES} au plus). "
            f"{_POURQUOI_LA_BORNE}")

    distincts = sorted(set(locuteurs))
    pour_modal = ou == "modal"
    demande = {
        "modele": MODELE["hf"],
        "revision": MODELE["revision"],
        "code": MODELE["code"],
        "code_revision": MODELE["code_revision"],
        "fichiers": list(FICHIERS_MODELE),
        "poids_go": MODELE["poids_go"],
        "echantillonnage": MODELE["echantillonnage"],
        "repliques": repliques,
        "locuteurs": distincts,
        # Modal : bibliotheques dans l'image, poids sur le disque persistant.
        # Kaggle : rien n'est garde d'une fois sur l'autre, tout s'installe et se
        # retelecharge dans le script.
        "cache": CACHE_MODAL if pour_modal else "",
        "installer": not pour_modal,
        "paquets": [] if pour_modal else list(PAQUETS_KAGGLE),
    }
    carte = {"modal": GPU_MODAL + " (Modal)", "kaggle": "T4 (Kaggle)"}.get(ou, ou)
    return {
        "gpu": GPU_MODAL,
        "ou": ou,
        "demande": demande,
        "resume_public": {
            "modele": MODELE["hf"],
            # La licence ET la phrase des auteurs, ensemble : elles ne disent pas
            # la meme chose, et la fiche du travail ne doit pas n'en garder qu'une.
            "licence": MODELE["licence"] + " — " + MODELE["restriction"]
                       + " ; " + MODELE["reserve_auteurs"],
            "territoire": MODELE["territoire"],
            "carte": carte,
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
<textarea id="texte" maxlength="2725" placeholder="[S1]Tu as vu qu’on peut faire parler deux voix maintenant ?
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
  <label>Où
    <select id="ou">
      <option value="modal" selected>Modal — machine louée (carte bancaire exigée)</option>
      <option value="kaggle">Kaggle — gratuit, bien plus lent</option>
    </select>
  </label>
  <button id="lancer" class="primaire">Faire parler</button>
</div>
<p id="ou-texte" class="avert"></p>
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

// Ce que chaque endroit implique, dit LA OU L'ON CHOISIT -- pas en note de bas
// de page. Les deux ont tourne en vrai le 17/09 ; ce qui les separe est le prix
// et l'attente, et les deux chiffres sont des releves.
function majOu(){
  const ou = document.getElementById("ou").value;
  const texte = {
    modal: "Carte " + (ETAT ? ETAT.carte_modal : "L4") + " louée à la seconde. Relevé du "
      + "17/09 : environ 0,03 $ et 105 s pour un dialogue, une fois les poids en cache. "
      + "Au pire " + (ETAT ? fr(ETAT.cout_max_modal_usd, 2) : "?") + " $ si le calcul "
      + "va jusqu’au délai maximal.",
    kaggle: "Carte T4 gratuite, sur votre compte Kaggle. Mesuré le 17/09 : 12,95 Go de "
      + "mémoire utilisés sur 14,56 pour 147,5 s d’audio — il restait 1,61 Go. C’est gratuit "
      + "mais lent : environ <b>3,3 fois le temps réel</b>, soit une douzaine de minutes "
      + "d’attente pour deux minutes et demie de dialogue, téléchargement des poids compris. Le texte "
      + "est limité à " + (ETAT ? ETAT.max_caracteres : "2725") + " caractères, "
      + "comme partout : c’est la limite du modèle, pas de la carte."
  }[ou];
  document.getElementById("ou-texte").innerHTML = texte || "";
}
document.getElementById("ou").addEventListener("change", majOu);

function budgetTexte(b){
  const part = Math.min(100, 100 * b.usd / b.plafond_usd);
  // Le nombre affiché vient de Modal dès que leur relevé est là et qu'il est le
  // plus grand des deux. Le dire, parce que « estimation » et « relevé » ne se
  // discutent pas de la même façon.
  const reel = (b.usd_reel !== null && b.usd_reel !== undefined
                && b.usd_reel >= b.usd_estime);
  return "Dépensé sur Modal ce mois-ci " + (reel ? "selon Modal" : "selon le Studio")
    + ", tous usages confondus : <b>"
    + fr(b.usd, 2) + " $</b> sur les " + fr(b.plafond_usd, 2)
    + " $ ouverts aux demandes. " + b.dialogues + " dialogue(s) sur cette page."
    + '<div class="jauge"><span style="width:' + fr(part, 1) + '%"></span></div>'
    + '<span class="avert">'
    + (reel
       // Les 8 % décrivent la MÉTHODE de comptage, pas le total affiché : ce total court
       // sur tout le mois et peut contenir des travaux comptés AVANT la correction des
       // tarifs du 20/09/2026, à des prix trop bas. Mesuré ce jour-là sur cette page :
       // 1,39 $ estimé contre 3,80 $ facturés, soit 37 % — annoncer 8 % sur CE nombre
       // serait faux de loin.
       ? 'Chiffre <b>relevé chez Modal</b> le ' + dateFr(b.usd_reel_le) + ' : leur compte, pas '
         + 'le nôtre. Notre estimation locale, d’après les prix relevés le '
         + dateFr(b.prix_releve_le) + ', dit ' + fr(b.usd_estime, 2) + ' $. La méthode '
         + 'sous-compte d’environ 8 %, le temps de processeur réellement utilisé dépassant '
         + 'le cœur réservé — et ce total peut contenir des travaux comptés avant le '
         + dateFr(b.prix_releve_le) + ', à des tarifs plus bas. '
       : 'Estimation locale d’après les prix relevés le ' + dateFr(b.prix_releve_le)
         + ', pas une facture : Modal n’a pas répondu. La méthode <b>sous-compte d’environ '
         + '8 %</b> (le processeur réellement utilisé dépasse le cœur réservé, et cela ne se '
         + 'sait qu’après), et ce total peut contenir des travaux comptés avant cette date, '
         + 'à des tarifs plus bas. ')
    + 'Ce compteur est <b>unique</b> depuis le 19/09/2026 : il compte '
    + 'ensemble les clips, les chansons, les dialogues et le code envoyé au Sandbox, sur un '
    + 'budget de ' + fr(b.plafond_total_usd, 2) + ' $, dont '
    + fr(b.reserve_autonome_usd, 2) + ' $ sont réservés au Sandbox et ne peuvent pas '
    + 'être entamés ici. '
    + 'Le crédit de ' + fr(b.credit_offert_usd, 0)
    + ' $ par mois est celui que vous avez déclaré. '
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
        "<b>Le nettoyage est systématique.</b> Ce modèle insère parfois de la parole que "
        + "personne n’a demandée, y compris en anglais — mesuré le 17/09 : cinq intrusions "
        + "en 147,5 s, toutes en fin de réplique. Le Studio transcrit le rendu, le compare "
        + "au texte envoyé et retire ce qui a été ajouté. <b>Le fichier d’origine reste "
        + "téléchargeable</b> : rien n’est coupé en douce. La transcription sous-estime, "
        + "donc ce qui est retiré est un plancher, pas un compte.",
        "Colab n’est pas proposé : la mesure du 16/09 a montré qu’il manque de mémoire vive "
        + "(environ 12,7 Go) pour des poids de 12,6 Go. C’est un échec dont la cause est "
        + "connue d’avance."
      ];
      if(!m.code_revision){
        reserves.push("Les <b>poids</b> sont épinglés à une révision précise, mais le "
          + "<b>code</b> est installé depuis la branche principale de son dépôt, sans "
          + "révision fixée : si le dépôt change, ce rendu n’est plus reproductible à "
          + "l’identique.");
      }
      document.getElementById("reserves").innerHTML = "· " + reserves.join("<br>· ");
      // Kaggle automatique se sert des identifiants PERSONNELS du proprietaire
      // de cette machine. Des que le Studio sert quelqu'un d'autre, le serveur
      // refuse ; la page le dit d'avance plutot que de laisser cliquer pour
      // rien. Le verrou qui compte est celui du serveur, pas celui-ci.
      if(d.kaggle_permis === false){
        const k = document.querySelector('#ou option[value="kaggle"]');
        k.disabled = true;
        k.textContent = "Kaggle — coupé ici : Studio partagé";
      }
      majOu();
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

// CE QUI A ETE RETIRE SE DIT. Defaut reel du 17/09, trouve en lancant un vrai
// dialogue : le serveur envoyait bien le rapport, la page le jetait. Elle a
// coupe 4,67 s sur 65,12 s sans l’ecrire nulle part, alors que ses propres
// reserves promettent que le fichier d’origine reste telechargeable. Les trois
// cas comptent, y compris celui ou le nettoyage n’a PAS eu lieu : le taire
// laisserait croire qu’un rendu a ete verifie alors qu’il ne l’a pas ete.
function blocNettoyage(j){
  const n = j.nettoyage;
  // JAMAIS MUET. Un rapport absent n’est pas un rapport vide : c’est le cas
  // même où la page peut servir un son déjà coupé sans l’écrire nulle part,
  // et c’est arrivé deux fois — le 17/09 parce que l’affichage jetait les
  // champs, le 18/09 parce qu’il affichait avant que le nettoyage soit inscrit.
  // Le silence était le point commun des deux.
  // Depuis le 18/09 le filtrage est DEMANDÉ, plus automatique : « pas de
  // rapport » ne veut donc plus dire « en retard », mais « personne ne l’a
  // demandé ». Dire l’un pour l’autre ferait attendre un rapport qui ne
  // viendra jamais.
  if(!n && j.nettoyage_en_cours){
    return '<p class="avert"><b>Filtrage de la voix en cours…</b> Quelques dizaines de '
      + 'secondes : le son est transcrit sur votre ordinateur, puis comparé au texte '
      + 'que vous avez envoyé. Le rapport et le fichier d’origine arrivent ensemble.</p>';
  }
  if(!n){
    return '<p class="avert"><b>Son brut, tel que le modèle l’a produit.</b> Écoutez-le : '
      + 's’il vous convient, il n’y a rien à faire. Si le modèle a ajouté des mots qui '
      + 'n’étaient pas dans votre texte — ça lui arrive en fin de réplique — le filtrage '
      + 'les repère et les retire, et garde l’original à côté.'
      + '<div class="ligne"><button type="button" id="filtrer" class="primaire">'
      + '🔎 Filtrer la voix</button>'
      + '<span class="avert">Transcription sur votre processeur, gratuite, '
      + 'quelques dizaines de secondes. Rien n’est envoyé ailleurs.</span></div></p>';
  }
  if(n.fait === false){
    return '<p class="avert"><b>Le filtrage n’a pas eu lieu</b> — ' + echapper(n.motif || "raison inconnue")
      + '. Le dialogue est livré tel que le modèle l’a produit.</p>';
  }
  const coupes = n.coupes || 0;
  if(!coupes){
    return '<p class="avert"><b>Filtrage : rien à retirer.</b> Le rendu correspond au texte envoyé. '
      + 'La transcription sous-estime, donc c’est un plancher, pas une garantie.</p>';
  }
  const details = n.details || [];
  const morceaux = details.filter(d => d.millisecondes)
    .map(d => '« ' + echapper(d.texte) + ' » à ' + d.debut + ' s (' + d.millisecondes + ' ms)');
  const gardes = details.filter(d => d.garde);
  let t = '<p class="avert"><b>Filtrage : ' + coupes + ' passage(s) retiré(s)</b>, '
    + n.secondes_retirees + ' s en tout — de ' + n.duree_avant_s + ' s à ' + n.duree_apres_s + ' s.';
  if(morceaux.length) t += '<br>' + morceaux.join('<br>');
  // Le motif vient du rapport, jamais d'ici. La version precedente annoncait
  // « une élision ou un nombre réellement prononcé » pour TOUT passage epargne :
  // sur le rendu Kaggle du 17/09, les 8 epargnes etaient des « ? », donc de la
  // ponctuation. La garde avait raison, la phrase mentait sur sa raison.
  if(gardes.length){
    const parMotif = {};
    gardes.forEach(d => { parMotif[d.garde] = (parMotif[d.garde] || 0) + 1; });
    // Le compte par motif n'a de sens qu'a partir de deux motifs : « 8 passages
    // épargnés : 8 × ponctuation » se lit deux fois pour rien.
    const plusieurs = Object.keys(parMotif).length > 1;
    const motifs = Object.keys(parMotif).sort()
      .map(m => (plusieurs ? parMotif[m] + ' × ' : '') + echapper(m));
    t += '<br>' + gardes.length + ' passage(s) épargné(s) par les gardes : '
      + motifs.join(', ') + '.';
  }
  t += '<br>La transcription sous-estime : ce qui a été retiré est un plancher, pas un compte.</p>';
  return t;
}

function afficherDialogue(j){
  const r = j.resume || {};
  const nom = nomDeFichier();
  const lien = j.son_url + "&telecharger=1&nom=" + encodeURIComponent(nom);
  let html = '<audio id="lecteur" controls src="' + j.son_url + '"></audio>'
    + '<div class="ligne"><a class="bouton" href="' + lien + '" download="' + nom + '">⬇️ Télécharger le dialogue</a>'
    + '<span class="avert">Fichier WAV, ' + (r.echantillonnage || 24000) / 1000 + ' kHz.</span></div>';
  // Nom DIFFERENT pour l’original : deux fichiers de meme nom se recouvrent
  // dans le dossier de telechargement, et la comparaison a l’oreille -- seul
  // juge reel de ce nettoyage -- deviendrait impossible.
  if(j.son_original_url){
    const nomOrigine = nom.slice(0, -4) + "-origine.wav";
    const lienOrigine = j.son_original_url + "&telecharger=1&nom=" + encodeURIComponent(nomOrigine);
    html += '<div class="ligne"><a class="bouton" href="' + lienOrigine + '" download="' + nomOrigine
      + '">⬇️ Télécharger l’original, avant nettoyage</a>'
      + '<span class="avert">Le son joué ci-dessus est la version nettoyée.</span></div>';
  }
  html += blocNettoyage(j);
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
  // Le bouton est recréé à chaque affichage, puisque tout le bloc est réécrit :
  // son écouteur doit l’être aussi. Un écouteur posé une fois au chargement
  // viserait un bouton qui n’existe pas encore.
  const filtrer = document.getElementById("filtrer");
  if(filtrer) filtrer.addEventListener("click", () => demanderFiltrage(j.id, filtrer));
}

function demanderFiltrage(id, bouton){
  bouton.disabled = true;
  bouton.textContent = "Filtrage demandé…";
  fetch("/dialogue/jobs/" + id + "/nettoyer", {method:"POST", headers:ENTETES})
    .then(async r => {
      const d = await r.json().catch(() => ({}));
      if(!r.ok){ throw new Error(d.detail || ("HTTP " + r.status)); }
      return d;
    })
    // La scrutation reprend : le rendu est fini, la page avait donc arrêté de
    // regarder. Sans cela le filtrage tournerait sans que rien ne s’affiche,
    // et il faudrait recharger la page pour voir qu’il a eu lieu.
    .then(() => suivre(id))
    .catch(e => {
      bouton.disabled = false;
      bouton.textContent = "🔎 Filtrer la voix";
      document.getElementById("etat").innerHTML =
        '<span class="ko">✖ ' + echapper(e.message) + "</span>";
    });
}

function suivre(id){
  const etat = document.getElementById("etat");
  // Borne de l’attente du nettoyage. Sans elle, un témoin resté levé par une
  // fiche illisible ferait tourner la page sans fin, et mieux vaut montrer ce
  // qu’on a en le disant que faire attendre pour toujours.
  let limiteNettoyage = 0;
  // suivre() est appelé deux fois maintenant : au lancement, puis au clic sur
  // « Filtrer la voix », le rendu étant fini et la scrutation arrêtée. Sans
  // cette ligne, un minuteur oublié interrogerait le serveur en double pour
  // toujours — une page laissée ouverte finirait par marteler la route.
  if(minuteur){ clearInterval(minuteur); minuteur = null; }
  minuteur = setInterval(() => {
    fetch("/dialogue/jobs/" + id, {headers:{"Authorization":"Bearer "+CLE}})
      .then(r => r.json())
      .then(j => {
        if(["running","queued","preparing","submitting"].indexOf(j.status) >= 0){
          const t = Math.round((Date.now()/1000) - (j.created_at || Date.now()/1000));
          etat.innerHTML = "⏳ En cours depuis " + t + " s. Le premier dialogue est le plus "
            + "long : environ 12,6 Go de poids se téléchargent.";
          montrerArret(id, j.fournisseur);
          return;
        }
        // LE FILTRAGE TOURNE ENCORE. Il dure une vingtaine de secondes et la
        // page doit continuer de regarder, sinon le rapport et le lien vers
        // l’original n’apparaîtraient qu’au prochain rechargement.
        // Mesuré le 18/09, quand le filtrage était encore automatique : sur
        // deux onglets du même lancement, celui au premier plan n’a rien vu,
        // celui en arrière-plan — minuteurs bridés par Chrome — a tout vu. Le
        // hasard décidait. Depuis, le filtrage est demandé, donc l’attente est
        // voulue et annoncée ; le témoin reste ce qui la borne.
        // On ne réaffiche PAS le dialogue ici : réécrire le bloc recréerait le
        // lecteur audio et couperait l’écoute en cours — or c’est en écoutant
        // qu’on vient de cliquer.
        if(j.nettoyage_en_cours && !j.nettoyage){
          if(!limiteNettoyage) limiteNettoyage = Date.now() + 300000;
          if(Date.now() < limiteNettoyage){
            cacherArret();
            etat.innerHTML = '<span class="ok">✔ Dialogue rendu</span> — filtrage de la voix '
              + 'en cours, quelques dizaines de secondes. Le rapport de ce qui est retiré et '
              + 'le fichier d’origine arrivent avec lui.';
            return;
          }
          // Au-delà de la borne, on montre ce qu’on a. blocNettoyage() le dira :
          // il n’est plus muet quand le rapport manque.
        }
        clearInterval(minuteur); minuteur = null;
        cacherArret();
        document.getElementById("lancer").disabled = false;
        // Le journal du noyau Kaggle s’ajoute aux deux autres. Le 17/09/2026,
        // sur le premier echec du chemin gratuit, stdout et stderr etaient
        // vides tous les deux : « Voir le détail technique » s’ouvrait sur du
        // vide, et il ne restait au debutant qu’a relancer au hasard, sur son
        // quota, sans rien savoir de ce qui avait casse.
        afficherJournal([j.stdout, j.stderr, j.journal_kaggle].filter(Boolean).join("\n"));
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
  const corps = {texte: document.getElementById("texte").value,
                 ou: document.getElementById("ou").value};
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
let fournisseurEnCours = "";

// Kaggle n'a AUCUNE annulation : le bouton ne promet donc pas un arrêt. Il
// dit ce qu'il fait vraiment, cesser d'attendre, et que le quota court encore
// (remarque du propriétaire, 23/09/2026).
function libelleArret(fournisseur){
  return fournisseur === "kaggle" ? "Ne plus attendre" : "⛔ Arrêt d’urgence";
}

function montrerArret(id, fournisseur){
  travailEnCours = id;
  fournisseurEnCours = fournisseur || "";
  const b = document.getElementById("arreter");
  if(b.hidden){
    b.hidden = false; b.disabled = false; b.textContent = libelleArret(fournisseur);
    b.className = fournisseur === "kaggle" ? "discret" : "danger";
    document.getElementById("arreter-texte").textContent = fournisseur === "kaggle"
      ? "Kaggle ne sait pas s’arrêter à distance : le Studio cesserait d’attendre, "
        + "mais le calcul continue chez Kaggle jusqu’à son échéance, et votre quota gratuit avec."
      : "";
  }
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
      b.textContent = libelleArret(fournisseurEnCours);
      t.innerHTML = '<span class="ko">✖ ' + echapper(e.message) + "</span>";
    });
});

rafraichir();
</script>
</body></html>"""
