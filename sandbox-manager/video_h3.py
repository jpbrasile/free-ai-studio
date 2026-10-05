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
import html
import json
import os
import random
import re
import time
import unicodedata
from pathlib import Path
from typing import Optional

import budget_modal
import montage

# Le niveau de la voix de référence envoyée à H3 (05/10, jalon 0 bis) : la voix de Leila enregistrée
# à −15,8 LUFS, près du micro ; les clips qui l'ont reçue sont sortis à −10,8 et −14 LUFS contre −26 à
# −28 sans elle, le fond sonore enterré de 12 à 17 dB (« le fond sonore a disparu », propriétaire).
# Ramenée au niveau des clips H3 de base sans voix. PROVISOIRE : à confirmer à l'écoute.
VOIX_REFERENCE_LUFS = -26.0

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
# Le mode Références a ses propres poids (01/10/2026) : le modèle officiel Comfy-Org
# `video_minimax_h3_r2v.json` charge `ref2va` et sa LoRA, « a different set of weights
# from the fl2va model used by the t2v/i2v templates ». Sur `fl2va`, même graine, H3
# dessinait une seconde Leila dès l'image 40 ; sur `ref2va`, une seule (4090, 01/10).
# Mêmes révision, encodeur et VAE ; ils remplacent FICHIERS[0] et FICHIERS[4].
FICHIERS_REFERENCES = (
    "diffusion_models/minimax_h3_ref2va_pruned_int8_convrot.safetensors",
    "loras/minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors",
)
POIDS_GO = 75   # 52 Go le 27/09/2026 (essai hors du Studio), + 22,9 Go de ref2va et sa LoRA (01/10)


def fichiers_du_mode(mode: str) -> tuple:
    """Les poids que charge un clip de ce mode, dans l'ordre de FICHIERS."""
    if mode != "references":
        return FICHIERS
    return (FICHIERS_REFERENCES[0],) + FICHIERS[1:4] + (FICHIERS_REFERENCES[1],)


def actif() -> bool:
    """H3 est un outil du poste administrateur (PLAN 20.1) : la licence de
    MiniMax est accordée à une personne, pas aux clients du Studio. Éteint par
    défaut ; VIDEO_H3_ACTIF=true dans le .env de l'administrateur l'allume.
    Lu à chaque appel, pour que les tests puissent le basculer."""
    return os.getenv("VIDEO_H3_ACTIF", "false").strip().lower() == "true"

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

# --- La carte de cet ordinateur (« Ici, sans urgence », 01/10/2026) -----------------
# Seule carte mesurée : la 4090 du propriétaire, 24 564 Mio. Un plan 768p de 5 s y a pris
# 23 141 Mio au pic, carte vide (ComfyUI charge selon la place qu'on lui laisse :
# l'encodeur de 25,9 Go et le DiT de 20 Go n'y sont jamais ensemble), 212 s de calcul.
# Une carte plus petite n'a pas été essayée : elle n'est pas offerte, H3 part chez Modal.
MAISON_CARTE_MIN_MO = int(os.getenv("H3_MAISON_CARTE_MIN_MO", "24000"))
# Le plafond d'un plan sur la carte, attente de la file NON comprise (elle n'a pas de
# limite) ; le bac à sable de la machine H3 le plafonne aussi (docker-compose.gpu.yml).
MAISON_DUREE_MAX_S = int(os.getenv("H3_MAISON_TIMEOUT_SECONDS", "1800"))


def maison_manque(fichiers_presents: dict, demande: dict) -> list:
    """Les poids que ce plan lit et que la machine H3 d'ici n'a pas."""
    return [f for f in demande.get("fichiers") or [] if f not in (fichiers_presents or {})]
COMMANDES = (
    f"git clone --depth 1 --branch {COMFY_VERSION} {COMFY_DEPOT} {DOSSIER_COMFY}",
    f"pip install -r {DOSSIER_COMFY}/requirements.txt psutil",
)
PAQUETS_POIDS = ("huggingface_hub==1.9.2",)

# --- Ce que la page propose ------------------------------------------------------

LARGEUR, HAUTEUR, IMAGES_PAR_SECONDE = 832, 480, 24
# La définition de l'image. 480p est celle des essais du 27/09 ; le LoRA Turbo
# chargé (FICHIERS[4], « 768p ») a été entraîné en 1344 × 768 selon ses auteurs
# (lightx2v, 11/08/2026) : 768p est proposé depuis le 28/09. Tous les plans d'un
# scénario ont la même, pour que le montage les recolle.
DEFINITIONS = {"480p": (LARGEUR, HAUTEUR), "768p": (1344, 768)}
DEFINITION_PAR_DEFAUT = "480p"
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
# --- Prolonger un clip ---------------------------------------------------------------
# Par défaut, le plan suivant part de la DERNIÈRE IMAGE du précédent (mode
# « première image »), puis le Studio recolle les deux, son compris, en retirant
# l'image qui se montrerait deux fois. Rien de plus n'est installé.
#
# En option (H3_MOTION_CONTEXT=true, décision du propriétaire le 27/09 :
# « autoriser en option sinon dernière image ») : « par tronçon ». Le plan suivant
# reprend 22 images et 1 s de son du précédent, pris dans son latent gardé sur le
# disque Modal, par le nœud ComfyUI-H3-Motion-Context (NikoDemon80, GPL-3.0,
# essayé hors du Studio le 27/09). Cloné dans la machine louée au commit relu,
# appelé par le graphe, jamais importé ici.
MC_DEPOT = "https://github.com/NikoDemon80/ComfyUI-H3-Motion-Context"
MC_COMMIT = "5335715abe54c1a9bfbe3494da29aae3e8635ce3"   # relu le 27/09/2026
COMMANDES_MC = (
    f"git clone {MC_DEPOT} {DOSSIER_COMFY}/custom_nodes/h3_motion_context",
    f"cd {DOSSIER_COMFY}/custom_nodes/h3_motion_context && git checkout {MC_COMMIT}",
)
CONTEXTE_IMAGES, CONTEXTE_SON = "22", 24   # réglage recommandé par le nœud, celui de l'essai
# Au-delà de ~4 raccords la texture se dégrade (limite connue, PLAN 18.x) :
# 4 plans au plus par chaîne, puis on repart d'une image.
PLANS_MAX = 4
DOSSIER_CHAINES = POINT_DE_MONTAGE + "/chaines"


def motion_context_actif() -> bool:
    return os.getenv("H3_MOTION_CONTEXT", "false").strip().lower() == "true"


def commandes() -> tuple:
    """Ce qui construit la machine louée ; le nœud tiers seulement si l'option est mise."""
    return COMMANDES + (COMMANDES_MC if motion_context_actif() else ())


COUPES = (0.0, 0.25, 0.5)   # secondes retirées au début, par ffmpeg
IMAGE_MAX_OCTETS = 8 * 1024 * 1024
IMAGES_MAX_OCTETS = 24 * 1024 * 1024

# Temps de location MESURÉ PAR LE STUDIO, par longueur : le second clip passé par
# /video-h3 le 27/09 (première image, disque déjà lu) a été compté 109 s,
# création de la machine comprise ; Modal en a facturé 0,107 $. L'essai du matin
# hors du Studio (72,4 s) sous-estimait : il ne comptait ni la création de la
# machine ni le tarif du bac à sable. Le tout premier clip coûte plus (lecture
# des 52 Go sur un disque neuf : 0,21 $ avec le téléchargement). Une seule
# longueur a été chronométrée ; les autres n'ont pas d'estimation, seulement le
# pire cas.
SECONDES_MESUREES = {124: 109.1}
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

# Les paroles au format des poids : `(S1) <d>[French] …</d>` (fiche du modèle,
# MiniMaxAI/MiniMax-H3). Sans balise ni langue, la réécriture d'invite de MiniMax
# (H3-Context-IR, non publiée) manque et la parole sort au hasard : le 27/09, un
# « Enfin au sec » entre guillemets est sorti en charabia (PLAN 18.9).
LANGUE_PAROLES = "French"
# Les 11 langues que la fiche dit « stables », sous leur nom anglais attendu dans la balise.
LANGUES_PAROLES = {
    "French": "français", "English": "anglais", "Spanish": "espagnol", "German": "allemand",
    "Italian": "italien", "Portuguese": "portugais", "Arabic": "arabe", "Chinese": "chinois",
    "Japanese": "japonais", "Korean": "coréen", "Russian": "russe",
}
_PAROLES = re.compile(r"«\s*([^«»]+?)\s*»|“\s*([^“”]+?)\s*”|\"\s*([^\"]+?)\s*\"")
_REPLIQUE_OU_BALISE = re.compile(_PAROLES.pattern + r"|<d>\s*(?:\[[^\]]*\]\s*)?(.+?)\s*</d>")


_NOM_DE_LANGUE = {**{k.lower(): k for k in LANGUES_PAROLES}, **{v: k for k, v in LANGUES_PAROLES.items()}}


# L'émotion d'une réplique (30/09, demande du propriétaire : « l'utilisation des émotions
# dans H3 »). FireRedTTS3 n'en met aucune sur une voix clonée (article des auteurs,
# arXiv 2608.17492) ; H3 si : il prend le TIMBRE de <Audio j> et le ton écrit à côté de
# la réplique — « <Subject 3> (S1), using the clear youthful voice timbre referenced from
# <Audio 1>, exclaims with light annoyance » (VIDEO_PROMPT_WRITING_GUIDE_ref_en.md).
# La marque se met en tête de la réplique, avec ou sans langue :
# « [anglais, joie] I made the team! », « [tristesse] Elle n'est pas venue… ».
# Chaque émotion : son nom sur la page, puis le ton que lit H3.
EMOTIONS = {
    "joie": ("joie", "overjoyed, bursting with happiness"),
    "tristesse": ("tristesse", "sadly, the voice close to tears"),
    "colere": ("colère", "angrily, the voice tense and raised"),
    "peur": ("peur", "fearfully, the voice trembling"),
    "surprise": ("surprise", "in surprise, the voice rising"),
    "calme": ("calme", "calmly and gently"),
    "tendresse": ("tendresse", "tenderly and softly"),
    "enthousiasme": ("enthousiasme", "enthusiastically, full of energy"),
    "ironie": ("ironie", "with an amused, ironic cadence"),
    "amusement": ("amusement", "amused, a playful smile in the voice"),
    "gene": ("gêne", "awkwardly, hesitating"),
    "fatigue": ("fatigue", "wearily, tired"),
    "rire": ("rire", "laughing while speaking"),
    "chuchote": ("chuchoté", "in a whisper"),
    "crie": ("crié", "shouting"),
}
# Les autres mots qu'on écrit pour la même émotion, en français et en anglais (sans accents).
_EMOTION_SYNONYMES = {
    "joyeux": "joie", "joyeuse": "joie", "heureux": "joie", "heureuse": "joie", "joy": "joie",
    "happy": "joie", "joyful": "joie", "triste": "tristesse", "sad": "tristesse", "sadness": "tristesse",
    "en colere": "colere", "fache": "colere", "fachee": "colere", "angry": "colere", "anger": "colere",
    "effraye": "peur", "effrayee": "peur", "apeure": "peur", "apeuree": "peur", "fear": "peur",
    "scared": "peur", "afraid": "peur", "surpris": "surprise", "surprised": "surprise", "calm": "calme",
    "tendre": "tendresse", "tender": "tendresse", "enthousiaste": "enthousiasme",
    "enthusiastic": "enthousiasme", "excited": "enthousiasme", "ironique": "ironie", "ironic": "ironie",
    "gene": "gene", "genee": "gene", "awkward": "gene", "fatigue": "fatigue", "fatiguee": "fatigue",
    "tired": "fatigue", "en riant": "rire", "riant": "rire", "laughing": "rire", "chuchote": "chuchote",
    "chuchotee": "chuchote", "murmure": "chuchote", "whisper": "chuchote", "whispering": "chuchote",
    "cri": "crie", "criee": "crie", "shouting": "crie", "shout": "crie",
    # Les noms anglais que MARQUES apprend au chat du Studio.
    "tenderness": "tendresse", "enthusiasm": "enthousiasme", "irony": "ironie", "awkwardness": "gene",
    "tiredness": "fatigue",
    # Les mots du chat pour ces émotions (film campus, 30/09).
    "overjoyed": "joie", "ravi": "joie", "ravie": "joie", "embarrassed": "gene", "embarrasse": "gene",
    # 01/10, « shouts, joyfully: » : l'adverbe n'était pas reconnu, le ton s'ajoutait
    # derrière les deux-points et H3 l'a prononcé (« Leila et un martien », plan 6).
    "joyfully": "joie", "happily": "joie", "cheerfully": "joie", "gleefully": "joie", "joyously": "joie",
    "joyeusement": "joie", "tristement": "tristesse", "kindly": "tendresse",
    "gently": "calme", "excitedly": "enthousiasme", "ironically": "ironie", "wearily": "fatigue",
    "embarrassee": "gene",
    "amuse": "amusement", "amusee": "amusement", "amused": "amusement", "playful": "amusement",
    "taquin": "amusement", "taquine": "amusement", "teasing": "amusement",
}
EMOTIONS_ANGLAIS = ("joy", "sadness", "anger", "fear", "surprise", "calm", "tenderness", "enthusiasm",
                    "irony", "amusement", "awkwardness", "tiredness", "laughing", "whisper", "shouting")

# Ce que le chat du Studio sait de la marque (découpage, correction, traduction de
# l'histoire). Demande du propriétaire, 30/09 : « le LLM qui crée le script connaît
# cette syntaxe pour produire les scripts ». Chaque réplique porte la langue de SES
# mots : un personnage qui passe au français garde ainsi la bonne voix (règle 4).
MARQUES = ("Each line of dialogue starts, inside its « », with a mark in square brackets: the language its words "
           "are in, then, when the script says or clearly shows how the line is said, one emotion, e.g. "
           "« [English, joy] I made the team! » or « [French, sadness] Elle n'est pas venue… ». Languages: "
           + ", ".join(LANGUES_PAROLES) + ". Emotions: " + ", ".join(EMOTIONS_ANGLAIS) + ". Keep every mark "
           "already written; add a missing one; never change the words of the line itself. ")


def _sans_accents(mot: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", mot) if unicodedata.category(c) != "Mn")


def emotion_connue(mot: str):
    """La clé de EMOTIONS pour ce mot (« joyeuse », « sad »…), sinon None."""
    m = " ".join(_sans_accents(str(mot or "")).lower().split())
    return m if m in EMOTIONS else _EMOTION_SYNONYMES.get(m)


_MARQUE = re.compile(r"\s*\[([^\]]+)\]\s*(.*)", re.S)


def _lire_marque(contenu: str):
    """(langue, émotion) si chaque morceau de la marque est une langue ou une émotion
    connue, une de chaque au plus ; sinon None (ce n'est pas une marque)."""
    langue = emotion = None
    for morceau in re.split(r"[,;/|+]", contenu):
        mot = morceau.strip().lower()
        if not mot:
            return None
        if mot in _NOM_DE_LANGUE and langue is None:
            langue = _NOM_DE_LANGUE[mot]
        elif emotion_connue(mot) and emotion is None:
            emotion = emotion_connue(mot)
        else:
            return None
    return langue, emotion


def marque_de_replique(dite: str, defaut: str) -> tuple:
    """(langue, émotion ou None, réplique sans la marque)."""
    m = _MARQUE.match(dite)
    lue = _lire_marque(m.group(1)) if m else None
    if lue:
        return lue[0] or defaut, lue[1], m.group(2).strip()
    return defaut, None, dite


def langue_de_replique(dite: str, defaut: str) -> tuple:
    """Une réplique peut dire sa langue en tête : « [English] Nice to meet you! »
    ou « [anglais] … ». Le même personnage passe ainsi d'une langue à l'autre,
    de la même voix (essai du 28/09). La marque peut aussi porter une émotion
    (« [anglais, joie] », 30/09) : elle est retirée ici avec la langue.
    Rend (langue, réplique sans la marque)."""
    langue, _emotion, reste = marque_de_replique(dite, defaut)
    return langue, reste


def marques_inconnues(texte: str) -> list:
    """Les marques en tête de réplique qui ne se lisent pas (« [joyeus] ») : elles seraient
    DITES par le personnage. La page refuse avant de lancer."""
    fautes = []
    for m in _PAROLES.finditer(str(texte or "")):
        dite = next(g for g in m.groups() if g)
        tete = _MARQUE.match(dite)
        if tete and not _lire_marque(tete.group(1)) and len(tete.group(1)) <= 40:
            fautes.append(tete.group(1).strip())
    return fautes


def marques_du_chat(texte: str, permises=()) -> str:
    """Découpage réel du 30/09 : le chat a écrit « [English, amused] », hors de la liste ;
    tout le découpage était refusé comme réplique inventée. Une marque qu'il ajoute est
    ramenée à ce qui se lit — la langue, une émotion connue — et le reste tombe : un mot
    entre crochets ne doit jamais être DIT. `permises` : les répliques du scénario
    (normées) ; une réplique écrite telle quelle par l'auteur n'est pas touchée."""
    def nettoie(m):
        dite = next(g for g in m.groups() if g)
        tete = _MARQUE.match(dite)
        if not tete or _lire_marque(tete.group(1)) or len(tete.group(1)) > 40 \
                or _norme_replique(dite) in permises:
            return m.group(0)
        langue = emotion = None
        for morceau in re.split(r"[,;/|+]", tete.group(1)):
            mot = morceau.strip().lower()
            if mot in _NOM_DE_LANGUE and langue is None:
                langue = _NOM_DE_LANGUE[mot]
            elif emotion_connue(mot) and emotion is None:
                emotion = EMOTIONS[emotion_connue(mot)][0]
        garde = ", ".join(x for x in (langue, emotion) if x)
        reste = tete.group(2).strip()
        return m.group(0).replace(dite, ("[%s] %s" % (garde, reste)) if garde else reste)
    return _PAROLES.sub(nettoie, str(texte or ""))


# Découpage réel du 30/09 : malgré MARQUES, le chat n'a posé aucune marque manquante ;
# « I made the team! » de Leila partait en français, avec sa voix française. Une étape à
# part lui demande, réplique par réplique, la langue et l'émotion ; le Studio écrit les
# marques lui-même, et une marque de l'auteur l'emporte toujours.
def _repliques_a_marquer(plans: list) -> list:
    """[(plan, champ, réplique telle qu'écrite, contexte)] des répliques sans marque complète."""
    a_marquer = []
    for i, p in enumerate(plans):
        for champ in ("image_paroles", "ambiance"):
            texte, fin_precedente = str(p.get(champ) or ""), 0
            for m in _PAROLES.finditer(texte):
                dite = next(g for g in m.groups() if g)
                tete = _MARQUE.match(dite)
                lue = _lire_marque(tete.group(1)) if tete else None
                # La phrase commence après la réplique d'avant : son « ! » ne coupe pas.
                coupure = max(texte.rfind(c, fin_precedente, m.start()) for c in ".!?;\n")
                debut = max(fin_precedente, coupure + 1)
                fin_precedente = m.end()
                if lue and lue[0] and lue[1]:
                    continue
                a_marquer.append((i, champ, dite, texte[debut:m.end()].strip()))
    return a_marquer


def consigne_marquer(plans: list) -> str:
    """La question au chat, ou "" s'il n'y a rien à marquer."""
    lignes = _repliques_a_marquer(plans)
    if not lignes:
        return ""
    return ("For each numbered line of dialogue below (the sentence around it is given for context), say the "
            "language its words are in, and one emotion only if the context says or clearly shows how it is "
            "said (otherwise null). Languages: " + ", ".join(LANGUES_PAROLES) + ". Emotions: "
            + ", ".join(EMOTIONS_ANGLAIS) + ". Answer with a JSON array only, one object per line, in order: "
            '[{"n": 1, "language": "English", "emotion": "joy"}, …].\n\n'
            + "\n".join("%d. %s" % (n + 1, contexte) for n, (_i, _c, _d, contexte) in enumerate(lignes)))


def poser_marques(plans: list, reponse: str) -> list:
    """Les plans, chaque réplique marquée d'après la réponse du chat. Une marque déjà
    écrite l'emporte ; une valeur illisible est ignorée (la réplique garde alors la langue
    de son personnage). ValueError si la réponse ne se lit pas."""
    lignes = _repliques_a_marquer(plans)
    t = str(reponse or "")
    debut, fin = t.find("["), t.rfind("]")
    try:
        lues = json.loads(t[debut:fin + 1]) if debut >= 0 else None
    except ValueError:
        lues = None
    if not isinstance(lues, list):
        raise ValueError("La réponse du chat sur les marques ne se lit pas.")
    par_n = {}
    for k, x in enumerate(lues):
        if isinstance(x, dict):
            n = x.get("n") if isinstance(x.get("n"), int) else k + 1
            par_n.setdefault(n, x)
    plans = [dict(p) for p in plans]
    for n, (i, champ, dite, _contexte) in enumerate(lignes, start=1):
        x = par_n.get(n) or {}
        tete = _MARQUE.match(dite)
        lue = _lire_marque(tete.group(1)) if tete else None
        reste = tete.group(2).strip() if lue else dite
        langue = (lue or (None, None))[0] or _NOM_DE_LANGUE.get(str(x.get("language") or "").strip().lower())
        cle = (lue or (None, None))[1] or emotion_connue(str(x.get("emotion") or ""))
        garde = ", ".join(v for v in (langue, EMOTIONS[cle][0] if cle else None) if v)
        if garde:
            plans[i][champ] = plans[i][champ].replace(dite, "[%s] %s" % (garde, reste), 1)
    return plans


_MOTS_VIDES_DU_TON = {"in", "a", "an", "the", "with", "and", "while", "speaking", "voice"}


def _contexte_avant(texte: str, debut: int) -> str:
    """La phrase qui mène à la réplique : depuis la dernière fin de phrase ou réplique."""
    t = texte[:debut]
    return t[max(t.rfind(c) for c in ".!?;\n»”\"") + 1:]


def _emotion_deja_dite(emotion, contexte: str) -> bool:
    """Le texte dit déjà l'émotion juste avant la réplique (« says, amused: »)."""
    mots = re.findall(r"[a-z]+", _sans_accents(contexte).lower())
    if any(emotion_connue(m) == emotion for m in mots + [" ".join(p) for p in zip(mots, mots[1:])]):
        return True
    tete = EMOTIONS[emotion][1].split(",")[0].split()
    return any(m in mots for m in tete if m not in _MOTS_VIDES_DU_TON)


def _ton(emotion, contexte: str = "") -> str:
    """Le ton lu par H3, avec ses virgules : « , overjoyed, bursting with happiness, ».
    Rien quand la phrase le dit déjà : le 30/09, « says, amused: amused, a playful smile
    in the voice, » partait à H3 (vérification à blanc du film campus)."""
    if not emotion or _emotion_deja_dite(emotion, contexte):
        return ""
    return ", %s," % EMOTIONS[emotion][1]


def balises_paroles(texte: str, langue: str = LANGUE_PAROLES, locuteur: str = "(S1)") -> str:
    """Chaque réplique entre guillemets devient `(S1) <d>[langue] …</d>`.
    Un texte qui porte déjà ses balises `<d>` est laissé tel quel."""
    if "<d>" in texte:
        return texte

    def balise(m):
        sa_langue, emotion, dite = marque_de_replique(next(g for g in m.groups() if g), langue)
        return f"{locuteur}{_ton(emotion, _contexte_avant(texte, m.start()))} <d>[{sa_langue}] {dite}</d>"
    return _PAROLES.sub(balise, texte)


def _motif_nom(nom: str) -> str:
    """Le nom d'un personnage, accents facultatifs : la traduction en anglais peut
    rendre « Lea » pour « Léa »."""
    morceaux = []
    for c in nom.strip():
        base = unicodedata.normalize("NFD", c)[0]
        morceaux.append(re.escape(c) if base == c else "[%s%s]" % (re.escape(c), re.escape(base)))
    return r"(?<!\w)" + "".join(morceaux) + r"(?!\w)"


_SANS_ARTICLE = re.compile(r"\b(?:the|a|an)\s+(<Subject \d+>)", re.I)


def attribuer_repliques(texte: str, sujets: list, garder_noms: bool = False, objets=(),
                        audios=None, releve=None) -> str:
    """Plusieurs personnages (guide de MiniMax, ref-en.txt, 5.4) : `sujets` est la
    liste des (nom, langue) dans l'ordre des <Subject N>.

    Chaque nom devient `<Subject N>` : dit tel quel, un nom a été récité (28/09).
    Chaque réplique va au PREMIER personnage nommé dans sa phrase (« Léa dit à
    Tom : « … » » : Léa), sinon au dernier nommé avant, sinon au premier ; elle
    part dans SA langue, les (Sx) numérotés dans l'ordre où l'on parle.

    Forme du guide (5.4) : `<Subject 2> (S1) turns … and says, <d>[English] …</d>`.
    Quand le locuteur est nommé dans la phrase, (Sx) suit ce nom et la réplique
    n'a que sa balise `<d>` ; le 28/09, « James demande <Subject 2> (S1) … »
    faisait parler James à lui-même, et le juge a vu une personne de trop.
    Sinon, la réplique porte `<Subject N> (Sx) <d>[langue] …</d>`.

    `garder_noms` : le clip part d'une image de départ, sans photos de fiche à
    désigner ; les noms restent des noms, seuls les (Sx) et les langues sont posés.

    Une marque « [langue, émotion] » en tête de réplique (30/09) : la langue va dans
    `<d>[…]`, l'émotion devient le ton écrit devant, forme du guide de MiniMax.
    `audios` : {rang : {langue : numéro de <Audio j>}} ; un personnage qui a DEUX voix
    dans le plan (une par langue) reçoit, à chaque réplique, celle de sa langue.
    `releve` : liste où ajouter (rang, langue) de chaque réplique, dans l'ordre."""
    texte = str(texte or "")
    repliques_vues = list(_PAROLES.finditer(texte))
    dans_une_replique = [(m.start(), m.end()) for m in repliques_vues]
    noms = sorted((m.start(), m.end(), k) for k, (nom, _langue) in enumerate(sujets) if nom.strip()
                  for m in re.finditer(_motif_nom(nom), texte, re.I)
                  if not any(a <= m.start() < b for a, b in dans_une_replique))
    locuteurs, parleur, fin_precedente = {}, {}, 0
    nom_du_locuteur = {}   # début du nom qui porte (Sx) -> personnage
    dit_par_son_nom = set()   # répliques dont le locuteur est nommé dans la phrase
    for m in repliques_vues:
        avant = texte[fin_precedente:m.start()]
        coupure = max(avant.rfind(c) for c in ".!?;\n")
        debut_phrase = fin_precedente + coupure + 1
        # Un objet ne parle pas : seuls les personnages portent une réplique.
        parlants = [n for n in noms if n[2] not in objets]
        dans_la_phrase = [n for n in parlants if debut_phrase <= n[0] < m.start()]
        plus_tot = [n for n in parlants if n[0] < debut_phrase]
        premier = next((k for k in range(len(sujets)) if k not in objets), 0)
        k = dans_la_phrase[0][2] if dans_la_phrase else plus_tot[-1][2] if plus_tot else premier
        parleur[m.start()] = k
        if dans_la_phrase:
            nom_du_locuteur[dans_la_phrase[0][0]] = k
            dit_par_son_nom.add(m.start())
        # Un numéro par PERSONNE, le même dans tous les plans (02/10) : numérotés dans
        # l'ordre de parole de chaque plan, Zib était (S1) au plan 5 et Leila (S1) au
        # plan 6, une suite qui reçoit la fin du plan 5, son compris ; « la voix change »
        # (le propriétaire). Guides de H3 : « The woman is Speaker 1. The man is Speaker 2 ».
        locuteurs.setdefault(k, sum(1 for r in range(k) if r not in objets) + 1)
        fin_precedente = m.end()
    evenements = sorted([(a, b, "nom", k) for a, b, k in noms]
                        + [(m.start(), m.end(), "replique", m) for m in repliques_vues], key=lambda e: e[0])
    sortie, pos = [], 0
    for debut, fin, genre, valeur in evenements:
        sortie.append(texte[pos:debut])
        pos = fin
        if genre == "nom":
            marque = f" (S{locuteurs[valeur]})" if nom_du_locuteur.get(debut) == valeur else ""
            sortie.append((texte[debut:fin] if garder_noms else f"<Subject {valeur + 1}>") + marque)
        else:
            k = parleur[debut]
            sa_langue, emotion, dite = marque_de_replique(next(g for g in valeur.groups() if g), sujets[k][1])
            if releve is not None:
                releve.append((k, sa_langue))
            siennes = (audios or {}).get(k) or {}
            timbre = (", using the voice timbre referenced from <Audio %d>," % siennes[sa_langue]
                      if len(siennes) > 1 and sa_langue in siennes else "")
            son_ton = _ton(emotion, _contexte_avant(texte, debut))
            ton = (timbre[:-1] + son_ton) if timbre and son_ton else (timbre or son_ton)
            if debut in dit_par_son_nom:
                sortie.append(f"{ton.strip(', ')}, <d>[{sa_langue}] {dite}</d>" if ton
                              else f"<d>[{sa_langue}] {dite}</d>")
            else:
                qui = "%s (S%d)" % (sujets[k][0] if garder_noms else f"<Subject {k + 1}>", locuteurs[k])
                sortie.append(f"{qui}{ton} <d>[{sa_langue}] {dite}</d>")
    sortie.append(texte[pos:])
    return "".join(sortie)


_LOCUTEUR = re.compile(r"<Subject (\d+)> \(S\d+\)")
_LOCUTEUR_NUMERO = re.compile(r"<Subject (\d+)> \(S(\d+)\)")


def rangs_qui_parlent(textes, sujets: list, objets=()) -> set:
    """Les rangs (0…) des personnages qui ont une réplique dans ces textes, attribuées
    comme attribuer_repliques les attribue. Film du parc, 30/09 : la voix de Leila
    partait avec un plan sans réplique, et H3 lui a fait dire du français inventé
    (« Bien. Jaffer, vous étiez… », entendu par le Whisper du Studio)."""
    return {int(m.group(1)) - 1 for t in textes
            for m in _LOCUTEUR.finditer(attribuer_repliques(t, sujets, objets=objets))}


# --- La caméra (01/10) ---------------------------------------------------------------
# Plan 1 du film campus rejoué chez Modal : « In a medium shot », sans phrase de caméra,
# et la caméra a reculé pendant tout le plan. Le guide de MiniMax
# (docs/VIDEO_PROMPT_WRITING_GUIDE_base_en.md, 4.3) écrit la caméra en type + amplitude
# + vitesse, en phrase anglaise dans le plan (« The camera holds a static shot as… »).
# Demande du propriétaire : un menu déroulant ; fixe par défaut.
CAMERA_MOUVEMENTS = {
    "fixe": ("Fixe", "holds a static shot"),
    "auto": ("Au choix du modèle (rien n'est écrit)", ""),
    "avance": ("Avance vers les personnages", "pushes in"),
    "recule": ("Recule", "pulls out"),
    "zoom_avant": ("Zoom avant", "zooms in"),
    "zoom_arriere": ("Zoom arrière", "zooms out"),
    "pano_gauche": ("Panoramique vers la gauche", "pans left"),
    "pano_droite": ("Panoramique vers la droite", "pans right"),
    "travelling_gauche": ("Glisse vers la gauche", "trucks left"),
    "travelling_droite": ("Glisse vers la droite", "trucks right"),
    "bascule_haut": ("Bascule vers le haut", "tilts up"),
    "bascule_bas": ("Bascule vers le bas", "tilts down"),
    "monte": ("Monte", "pedestals up"),
    "descend": ("Descend", "pedestals down"),
    "arc": ("Tourne autour des personnages", "moves in an arc shot around the subjects"),
    "suit": ("Suit le personnage qui bouge", "follows the moving subject in a tracking shot"),
    "tremble": ("Tremble un peu (caméra à l'épaule)", "shakes slightly"),
}
CAMERA_AMPLITUDES = {"": "Normale", "petite": "Petite", "grande": "Grande"}
CAMERA_VITESSES = {"": "Normale", "lente": "Lente", "rapide": "Rapide"}
_CAMERA_SANS_REGLAGE = ("fixe", "auto", "tremble")
CAMERA_DEFAUT = {"mouvement": "fixe", "amplitude": "", "vitesse": ""}


def lire_longueur_plan(longueur) -> Optional[int]:
    """La durée propre d'un plan (01/10, « mets 10 s pour le plan 6 ») ; absente, le
    plan prend celle du scénario. ValueError hors de la grille du modèle."""
    if longueur in (None, "", 0):
        return None
    try:
        n = int(longueur)
    except (TypeError, ValueError) as exc:
        raise ValueError("Durée illisible.") from exc
    if n not in LONGUEURS:
        raise ValueError("Durée hors de la grille du modèle.")
    return n


def lire_camera(camera) -> dict:
    """Le choix du menu, contrôlé ; absent, la caméra est fixe."""
    if camera in (None, "", {}):
        return dict(CAMERA_DEFAUT)
    if not isinstance(camera, dict):
        raise ValueError("Caméra illisible.")
    c = {"mouvement": str(camera.get("mouvement") or "fixe"), "amplitude": str(camera.get("amplitude") or ""),
         "vitesse": str(camera.get("vitesse") or "")}
    if c["mouvement"] not in CAMERA_MOUVEMENTS:
        raise ValueError("Mouvement de caméra inconnu.")
    if c["amplitude"] not in CAMERA_AMPLITUDES or c["vitesse"] not in CAMERA_VITESSES:
        raise ValueError("Amplitude ou vitesse de caméra inconnue.")
    if c["mouvement"] in _CAMERA_SANS_REGLAGE:
        c.update(amplitude="", vitesse="")
    return c


def phrase_camera(camera) -> str:
    """La phrase du guide : « The camera pushes in with small amplitude at slow speed. »"""
    c = lire_camera(camera)
    verbe = CAMERA_MOUVEMENTS[c["mouvement"]][1]
    if not verbe:
        return ""
    if c["mouvement"] == "fixe":
        return "The camera holds a static shot throughout."
    return ("The camera " + verbe
            + {"petite": " with small amplitude", "grande": " with large amplitude"}.get(c["amplitude"], "")
            + {"lente": " at slow speed", "rapide": " at fast speed"}.get(c["vitesse"], "") + ".")


def avec_camera(texte: str, phrase: str) -> str:
    """La phrase de caméra après la première phrase du plan (le cadre et les places), hors
    réplique ; le guide la veut dans le plan, pas en étiquette à la fin. Sans phrase finie
    hors réplique (« James demande « … » Léa répond « … » »), elle passe en tête."""
    if not phrase:
        return texte
    t = str(texte or "").strip()
    dedans = 0
    guillemet = False
    for i, ch in enumerate(t):
        if ch == "«":
            dedans += 1
        elif ch == "»":
            dedans = max(0, dedans - 1)
        elif ch in "\"“”":
            guillemet = not guillemet
        elif ch in ".!?" and not dedans and not guillemet and (i + 1 == len(t) or t[i + 1] == " "):
            return (t[:i + 1] + " " + phrase + " " + t[i + 1:].lstrip()).strip()
    return (phrase + (" " if t else "") + t).strip()


# 04/10, « Le robot perdu », clip déplié 1 : un homme que le texte ne nomme pas ramasse la capsule. Un clip
# déplié ne voit que son plan ; on y dit qu'il n'y a personne d'autre (pas au maître, proche des 4 000 signes).
PERSONNE_D_AUTRE = "Nobody else appears: only the characters named here are on screen."
SILENCE_IMAGE = "Nobody speaks: every person keeps their lips closed."
SILENCE_SON = "No dialogue, no voiceover, no singing, no individual voices."
# 03/10, « Le jardin de verre », clip 4 : « she laughs » et « gentle laughter » avec « lips closed » et
# « no individual voices » ; la consigne se contredisait, et H3 a fait dire « I'll be done! » (Whisper).
# Un son de voix sans paroles demandé (rire, soupir…) reste permis ; seuls les mots sont interdits.
# « hum » n'en est pas : un frigo, la ville, un néon bourdonnent aussi (« humming fridge »).
# Les formes du verbe seulement : essai I du 05/10, plan 3, « the sight of it » a été lu « sigh » et l'invite
# a dit « the only voice sound is the wordless sight described » (« sob\w* » prenait aussi « sober »).
_SONS_DE_VOIX = re.compile(r"\b(laugh(?:s|ed|ing|ter)?|giggl(?:e|es|ed|ing)|chuckl(?:e|es|ed|ing)|"
                           r"sigh(?:s|ed|ing)?|gasp(?:s|ed|ing)?|scream(?:s|ed|ing)?|sob(?:s|bed|bing)?|"
                           r"cr(?:y|ies|ied|ying)|yawn(?:s|ed|ing)?|whimper(?:s|ed|ing)?|squeal(?:s|ed|ing)?|"
                           r"shriek(?:s|ed|ing)?)\b", re.I)
SILENCE_SANS_MOTS_IMAGE = ("Nobody says a single word: the only voice sound is the wordless %s described; "
                           "no speech before or after it.")
SILENCE_SANS_MOTS_SON = "No dialogue, no words, no voiceover, no singing; only the wordless %s described."


def sons_de_voix(*textes) -> list:
    """Les sons de voix sans paroles (rire, soupir…) que demandent ces textes, dans l'ordre, sans doublon."""
    vus = []
    for t in textes:
        for m in _SONS_DE_VOIX.finditer(str(t or "")):
            mot = m.group(0).lower()
            if mot not in vus:
                vus.append(mot)
    return vus
# 02/10, film 4, plan 2 : une seule réplique (Tyler, à 7 s) ; Leila, qui venait de dire
# « Parfaite ! » dans le raccord, a parlé 4 s d'un anglais sans suite avant lui.
SEULES_REPLIQUES = ("Only the quoted lines are spoken, each by its speaker: before, between and after them, "
                    "nobody says anything and every other person keeps their lips closed.")


def invite(image_paroles: str, ambiance: str = "", musique: str = "",
           langue: str = LANGUE_PAROLES, locuteur: str = "(S1)", son: str = "Sound: ", champ: str = "",
           separateur: str = " ") -> str:
    """Une seule invite pour le modèle, à partir des trois cases de la page.

    H3 fabrique l'image ET le son à partir du même texte : la case « image et
    paroles » décrit ce qu'on voit et ce qui est dit (les paroles entre
    guillemets, balisées ici pour le modèle), les deux autres le reste de la
    bande son.

    La musique va dans le champ `non_diegetic_music` du guide de MiniMax
    (docs/VIDEO_PROMPT_WRITING_GUIDE_ref_en.md) ; case vide, il vaut `N/A` :
    sans rien dire, H3 ajoute une musique (entendue le 27/09, PLAN 18.9).

    `champ` : le nom du champ de la description (« integrated_multimodal_description: »),
    `separateur` : entre les champs (une ligne vide dans les guides de MiniMax).
    """
    morceaux = []
    image_paroles = balises_paroles(image_paroles, langue, locuteur)
    # Aucune réplique écrite : le silence se dit, chaque voie de parole fermée. 01/10,
    # « Leila et un martien », plan 4 : sans réplique, les deux prises ont parlé
    # (« You come, fakie… », « Anna come on peace »), en écho de la fin du plan 3
    # reprise par le raccord. « silent » seul ne suffit pas (guides de dialogue H3).
    muet = bool(" ".join(str(image_paroles or "").split())) and "<d>" not in image_paroles
    voix = " / ".join(sons_de_voix(image_paroles, ambiance)) if muet else ""
    silence_image = SILENCE_SANS_MOTS_IMAGE % voix if voix else SILENCE_IMAGE
    silence_son = SILENCE_SANS_MOTS_SON % voix if voix else SILENCE_SON
    # overall_soundscape (guide de MiniMax, base 4.6) : des sons seulement ; la parole n'y est pas
    # redite. Le silence se dit dans la description (SILENCE_IMAGE), plus dans ce champ (audit du 04/10,
    # « Le robot perdu » : « No dialogue… » dans les sons, et H3 a parlé quand même aux plans 3 et 5).
    sons_seuls = son == CHAMP_SONS
    for k, (texte, prefixe) in enumerate(((image_paroles, champ), (ambiance, son), (musique, "non_diegetic_music: "))):
        t = " ".join(str(texte or "").split())
        if k == 0 and t:
            t = (t if t[-1] in ".!?\"»>" else t + ".") + " " + (silence_image if muet else SEULES_REPLIQUES)
        if k == 1 and sons_seuls and not t and morceaux:
            t = AMBIANCE_SEULE
        if muet and k == 1 and not sons_seuls:
            t = (t if not t or t[-1] in ".!?\"»>" else t + ".") + (" " if t else "") + silence_son
        if t:
            if t[-1] not in ".!?\"»>":
                t += "."
            morceaux.append(prefixe + t)
    if morceaux and not " ".join(str(musique or "").split()):
        morceaux.append("non_diegetic_music: N/A")
    return separateur.join(morceaux)


# --- La syntaxe de H3 hors « Références » (04/10, propriétaire : « conform to h3 syntax in studio,
# mandatory ») -------------------------------------------------------------------------------------
# MiniMax, docs/VIDEO_PROMPT_WRITING_GUIDE_base_en.md (2.1, 2.2, cas 2 à 3) : la consigne d'alignement
# des images en première ligne, puis une ligne vide, puis les trois champs, chacun séparé d'une
# ligne vide ; la description commence par [Shot 1]. Jusque-là, le Studio envoyait « First frame: … »,
# le texte nu et « Sound: » (film 5, « Le robot perdu », maître f970b321 et ses clips).
CHAMP_DESCRIPTION = "integrated_multimodal_description: "
CHAMP_SONS = "overall_soundscape: "
# Plan sans ambiance écrite : le champ des sons reste, en une phrase de sons (base 4.6 : N/A seulement
# pour un silence complet demandé).
AMBIANCE_SEULE = "Only the quiet ambient sound of the place is heard."
# La piste son du lieu en <Audio N> (05/10) : phrase du guide de MiniMax (ref-en, overall_soundscape).
AMBIANCE_COPIEE = "The copied ambience layer from <Audio %d> continues throughout the target video."
AMBIANCE_REFERENCE = "The ambience of <Audio %d> continues throughout the target video."
# Le style ouvre [Shot 1] (base 4.1, « [Shot 1] Live-action, cinematic, … ») ; le Studio fait des images
# photo réalistes. Audit du 04/10 : aucune des 12 invites du film 5 ne le disait.
STYLE_H3 = "Live-action, cinematic."
# Mode Références : le style avant [Shot 1], en phrase (ref-en.txt, 5.2, « The target video is in a
# cinematic, literary music-video style… »).
STYLE_REFERENCES = "The target video is in a live-action, cinematic style."
# La limite de MiniMax (API, tous modes : « Prompt length limit ≤ 7000 characters ») ; l'encodeur de la
# carte d'ici (ComfyUI, text_encoders/minimax.py) n'en a pas plus bas et refuse plutôt que de couper.
# 4 000 avant le 05/10, choix de la V1 sans source : il forçait à condenser les textes des plans.
INVITE_MAX = 7000

SEPARATEUR_CHAMPS = "\n\n"
CONSIGNE_I2VA = "For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced."
CONSIGNE_FL2VA = ("How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the "
                  "0.00-second mark of the target video; Picture 2 (from Shot %d) aligns with the %.2f-second mark "
                  "of the target video.")


def consigne_images(mode: str, plans: int, duree_s: float) -> str:
    """La première ligne de l'invite d'un mode à images clefs ; vide pour « Texte seul »."""
    if mode == "premiere":
        return CONSIGNE_I2VA
    if mode == "premiere_derniere":
        return CONSIGNE_FL2VA % (max(1, plans), duree_s)
    return ""


_CONSIGNE_DE_L_IMAGE = re.compile(r"^\s*Photo réaliste,.*?la scène\s*:\s*")
_AMELIORATIONS = re.compile(r"\s*Améliorations demandées\s*:.*$", re.S)


def _description_pour_h3(texte) -> str:
    """Ce que l'image montre, sans ce qui ne s'adressait qu'au modèle d'image : le préfixe technique
    (PREFIXE_DEPART, PREFIXE_FIN, ceux de la page) et les améliorations demandées, en français."""
    t = _AMELIORATIONS.sub("", _CONSIGNE_DE_L_IMAGE.sub("", " ".join(str(texte or "").split())))
    return t.strip()


ANCRE_PREMIERE = "The shot begins from <Picture 1>, preserving its people, their appearance, the setting and the composition: "


def description_aux_images(texte: str, premiere: str = "", derniere: str = "") -> str:
    """Le texte du plan commencé par [Shot 1] ; ce que montrent les images clefs y est dit en
    ancre (guide de MiniMax, 3.1 et 3.2) : la première au début de [Shot 1], la dernière à la fin."""
    t = " ".join(str(texte or "").split())
    if not _MULTIPLAN.search(t):
        t = "[Shot 1] " + t
    # Ce qui précède [Shot 1] (la tête du maître, « The same place… ») passe dedans : la description
    # commence par [Shot 1].
    i = t.find("[Shot 1]")
    tete, t = (t[:i].strip(), t[i + len("[Shot 1]"):].strip()) if i >= 0 else (t, "")
    d = _description_pour_h3(premiere)
    # Une phrase, pas une étiquette (base, cas 2 : « the young woman shown in <Picture 1> remains …,
    # preserving her appearance… ») ; audit du 04/10 : « <Picture 1>: » suivi de fragments.
    ancre = (ANCRE_PREMIERE + d + ("" if d[-1] in ".!?" else ".")) if d else ""
    t = " ".join(x for x in ("[Shot 1]", STYLE_H3, ancre, tete, t) if x)
    d = _description_pour_h3(derniere)
    if d:
        t = ((t if t[-1] in ".!?\"»>" else t + ".") + " The shot ends on the composition established by "
             "Picture 2: " + d + ("" if d[-1] in ".!?" else "."))
    return t


# --- Le clip maître (03/10/2026, « Le jardin de verre ») -----------------------------
# Propriétaire : « l'erreur vient de l'inconsistance temporelle des images, l'image de fin
# n'est donc pas une bonne idée », puis « tu concentres l'histoire en un seul clip de 15 s,
# puis tu extrais les images intermédiaires pour une vidéo plus longue ». Toute l'histoire
# en UN clip de 362 images, un [Shot N] daté par coupe du scénario (format du guide MiniMax,
# « [Shot 2] At 00:02.500, the camera cuts to … », une caméra par plan) ; mesuré le même
# soir en mode « première image », 480p : 5 coupes demandées, 5 vues par ffmpeg, à 0,13 s
# près au plus. Puis chaque plan se tourne seul, de sa première à sa dernière image dans le
# maître (premiere_derniere) : deux images d'un même clip, cohérentes entre elles.
# Sans paroles (propriétaire : « on évite de mettre des paroles pour le clip maître ») :
# elles se disent dans les clips dépliés.
LONGUEUR_MAITRE = LONGUEURS[-1]
# Une coupe vue à plus de 0,6 s de sa date n'est pas la sienne. « Le jardin de verre » : 0,13 s au
# plus ; « Le phare », 03/10 : 0,44 s (11,75 s pour 11,312 s), refusée à 0,4. Les plans d'un maître de
# 15 s en 8 plans sont à 1,9 s l'un de l'autre : 0,6 s ne prend pas la coupe du voisin.
MAITRE_ECART_COUPE_S = 0.6
# Près d'une coupe DEMANDÉE, un changement d'image plus faible suffit. « Le robot perdu », film 5,
# 04/10 : trois maîtres refusés (« n'a pas fait la coupe du plan 2, 3 ») ; les coupes y étaient, à
# 1,83 et 3,63 s, mais entre deux plans de nuit (scene 0,27 et 0,29, sous le seuil de 0,3).
COUPE_SEUIL_ATTENDUE = 0.2
_MULTIPLAN = re.compile(r"\[Shot \d+\]")
# Ni « the girl » ni autre nom pour une personne que celui du plan : le 03/10, « the same … girl
# in every shot » en tête et « Mila » dans les plans, le dernier plan a montré deux fillettes.
# Sans « the same place » : audit du 04/10, « Le robot perdu » va du jardin à la colline, et les plans
# 5, 7 et 8 du maître sont restés au jardin. Chaque plan dit son lieu.
MAITRE_TETE = "The same people in every shot; each shot takes place where its own text says."
_VERBES_DE_PAROLE = re.compile(
    r"(?:,\s*|\s+)(?:and\s+|et\s+)?(?:says|said|murmurs|whispers|asks|replies|answers|shouts|calls|exclaims|"
    r"sings|adds|dit|murmure|chuchote|demande|répond|crie|chante|ajoute|s'exclame)\b[^.!?;«»<¶]*?(?=\s*[.!?;¶]|\s*$)",
    re.I)


def sans_repliques(texte: str) -> str:
    """Le plan sans ce qui est dit : répliques et verbes qui les annoncent ôtés ; une phrase
    qui n'avait que sa réplique (« Elle dit « Bonjour. » ») disparaît."""
    # La réplique ôtée finit sa phrase (¶) : le verbe qui l'annonce s'arrête là.
    t = _REPLIQUE_OU_BALISE.sub(" ¶ ", str(texte or ""))
    t = _VERBES_DE_PAROLE.sub("", t)
    t = re.sub(r"[\s:,]*¶[\s.!?;]*", ". ", t)
    phrases = [p.strip() for p in re.split(r"(?<=[.!?;])\s+", " ".join(t.split()))]
    t = " ".join(p for p in phrases if len(re.findall(r"\w+", p)) >= 2).strip()
    return t + "." if t and t[-1] not in ".!?;" else t


def _horodatage(s: float) -> str:
    ms = round(s * 1000)
    return "%02d:%02d.%03d" % (ms // 60000, ms // 1000 % 60, ms % 1000)


# La valeur de plan, dite dans la première phrase de chaque plan (consigne du découpage).
_VALEUR_DE_PLAN = re.compile(r"\b(extreme close-up|medium close-up|close-up|medium long shot|medium shot|"
                             r"full shot|long shot|wide shot|extreme wide shot)\b", re.IGNORECASE)


def valeur_de_plan(texte: str):
    m = _VALEUR_DE_PLAN.search(str(texte or "").split(".")[0])
    return m.group(1).lower() if m else None


def phrase_de_coupe(texte: str) -> str:
    """« the shot cuts to a close-up of Leila… » : la forme du guide de MiniMax (ref-en.md, 7). Un plan qui
    ouvre sur sa valeur (« Close-up of Leila… ») la prend dans la phrase de coupe ; sinon la valeur de sa
    première phrase est nommée devant (« the shot cuts to a wide shot. Leila… ») ; sans valeur, le plan
    est refusé dès le découpage (exiger_cadrages)."""
    t = str(texte or "").strip()
    valeur = valeur_de_plan(t)
    if not valeur:
        return "the shot cuts to a new shot. " + t
    article = "an" if valeur[0] in "aeiou" else "a"
    m = re.match(r"(?:an?\s+|the\s+)?" + re.escape(valeur) + r"\b", t, re.IGNORECASE)
    if m:
        return "the shot cuts to %s %s%s" % (article, valeur, t[m.end():])
    return "the shot cuts to %s %s. %s" % (article, valeur, t)


def exiger_cadrages(plans: list) -> list:
    """Chaque plan qui ouvre sur une coupe dit sa valeur de plan dans sa première phrase (consigne du
    découpage ; guide de MiniMax, 5.1 : « clearly establish the current composition »). Jalon 0 bis,
    clip 10 (05/10) : « The camera holds a static shot from the lawn », sans valeur ni orientation ;
    H3 a ouvert sur le gros plan de face de la photo, puis coupé. ValueError (« réessayez ») sinon."""
    for i, p in enumerate(plans):
        if (i == 0 or p.get("enchainement", "coupe") == "coupe") and not valeur_de_plan(p.get("image_paroles")):
            raise ValueError("Le plan %d ne dit pas sa valeur de plan dans sa première phrase (close-up, "
                             "medium shot, wide shot…) : réessayez." % (i + 1))
    return plans


_CADRAGE_ET_LIAISON = re.compile(_VALEUR_DE_PLAN.pattern + r"(?:\s+(?:of|on)\b)?\s*[,:.]?\s*", re.IGNORECASE)


def un_seul_cadrage(texte: str) -> str:
    """Le premier cadrage du texte reste, les autres valeurs de plan sont retirées (hors répliques) :
    la règle 18 tenue d'office quand plusieurs plans du découpage deviennent un seul plan (une
    séquence du film automatique ; film 5 relancé, 04/10 : « wide shot » puis « close-up »)."""
    premiere = None

    def retirer(m):
        nonlocal premiere
        premiere = premiere or m.group(1).lower()
        return m.group(0) if m.group(1).lower() == premiere else ""
    morceaux = _REPLIQUE_D.split(str(texte or ""))
    for k in range(0, len(morceaux), 2):
        t = _CADRAGE_ET_LIAISON.sub(retirer, morceaux[k])
        morceaux[k] = re.sub(r"(^|[.!?]\s+|\]\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(),
                             re.sub(r"[ \t]{2,}", " ", t))
    return "".join(morceaux).strip()


def suites_du_maitre(plans: list) -> list:
    """03/10, film « Le phare » : le plan 2, « suite » du plan 1, passait d'un plan large à un plan
    moyen et posait Oscar en haut de l'escalier ; sans coupe, H3 a fondu l'un dans l'autre (deux
    Oscar en transparence, refusé deux fois par le juge). Dans le maître, une suite qui change de
    valeur de plan devient une coupe ; les autres restent des suites."""
    rendu, avant = [], None
    for k, p in enumerate(plans):
        valeur = valeur_de_plan(p.get("image_paroles"))
        if k and p.get("enchainement") == "suite" and valeur and avant and valeur != avant:
            p = dict(p, enchainement="coupe")
        rendu.append(p)
        avant = valeur or avant
    return rendu


def payload_maitre(payload: dict, description_depart: str = "") -> dict:
    """Le maître part de son image de départ en « Première image », pas en « Références ».
    Mesuré le 03/10 (ffmpeg, scene > 0,3) : en Références (fiches + image de départ), 5 coupes
    franches sur 15 demandées, les autres fondues (le fondu montre Oscar deux fois) ; en Première
    image (« Le jardin de verre »), 5 sur 5. Les fiches ne donnent plus que les voix ; le visage
    vient de l'image de départ, faite d'après les fiches, et le juge le compare aux fiches."""
    if payload.get("mode") != "references" or not payload.get("depart_reference"):
        return payload
    return dict(payload, mode="premiere", images=[payload["depart_reference"]], depart_reference=None,
                visages_seuls=None, description_premiere=description_depart)


def texte_maitre(plans: list, longueur: int = LONGUEUR_MAITRE) -> dict:
    """Le texte du clip maître : {texte, ambiance, debuts_s, longueur}. Chaque plan prend du maître
    la part de sa propre durée ; une « coupe » est un [Shot N] daté, une « suite » continue le plan
    d'avant sans coupe."""
    if longueur not in LONGUEURS:
        raise ValueError("Durée hors de la grille du modèle.")
    durees = [p.get("longueur") or LONGUEUR_PAR_DEFAUT for p in plans]
    total, duree_s = sum(durees), longueur / IMAGES_PAR_SECONDE
    debuts, morceaux, n, cumul = [], [MAITRE_TETE], 0, 0
    for k, p in enumerate(plans):
        debut = round(cumul / total * duree_s, 3)
        cumul += durees[k]
        debuts.append(debut)
        camera = lire_camera(p.get("camera"))
        # « throughout » dirait tout le clip : ici, ce plan seulement.
        phrase = "The camera holds a static shot." if camera["mouvement"] == "fixe" else phrase_camera(camera)
        t = avec_camera(sans_repliques(p.get("image_paroles")), phrase)
        if k == 0:
            n = 1
            morceaux.append("[Shot 1] " + t)
        elif p.get("enchainement", "coupe") == "coupe":
            n += 1
            # Une coupe nommée avec sa valeur de plan (05/10, propriétaire : « la prochaine coupe franche
            # (web search) », puis « hard code studio pour éviter ces bugs ») : jalon 0 bis, clip 9, H3 a fondu
            # un plan dans l'autre. Guide de MiniMax (VIDEO_PROMPT_WRITING_GUIDE_ref_en.md, 5.2 et 7) :
            # « [Shot 2] At 00:03.000, the shot cuts to a close-up of <Subject 4>… » ; « hard cut to a new
            # shot », écrit d'abord, n'est pas dans le guide et ne disait pas vers quoi.
            morceaux.append("[Shot %d] At %s, %s" % (n, _horodatage(debut), phrase_de_coupe(t)))
        else:
            morceaux.append("From %s, without a cut: %s" % (_horodatage(debut), t))
    ambiances = []
    for p in plans:
        a = " ".join(str(p.get("ambiance") or "").split()).rstrip(".")
        if a and a not in ambiances:
            ambiances.append(a)
    # Des phrases, pas des fragments séparés de « ; » (base 4.6).
    return {"texte": " ".join(morceaux), "ambiance": " ".join(a[0].upper() + a[1:] + "." for a in ambiances),
            "debuts_s": debuts,
            "longueur": longueur}


def cles_du_maitre(plans: list, debuts_s: list, coupes_vues_s: list, images: int,
                   coupes_faibles_s: list = (), continus: Optional[list] = None) -> list:
    """La première et la dernière image de chaque plan dans le maître : [(premiere, derniere)].
    Une coupe prend la date où ffmpeg l'a vue, plus une image (pas de mélange des deux cadrages) ;
    une suite partage l'image de fin du plan d'avant, sans saut. ValueError si le maître n'a pas
    fait une coupe demandée : déplié, ce plan mélangerait deux cadrages. `coupes_faibles_s` : les
    changements vus au seuil COUPE_SEUIL_ATTENDUE, pris seulement là où une coupe est demandée.
    `continus` (une liste) : une coupe manquée devient une suite, à sa date prévue, et son numéro
    de plan y est ajouté — propriétaire, 04/10 : « si une coupe n'est pas faite, fais le clip en
    mode continu » (H3 avait enchaîné les plans 7 et 8 du « Robot perdu » d'une traite)."""
    debuts, manquees, coupes = [], [], []
    for k, (p, d) in enumerate(zip(plans, debuts_s)):
        vues = [c for c in coupes_vues_s if abs(c - d) <= MAITRE_ECART_COUPE_S]
        if not vues and k and p.get("enchainement", "coupe") == "coupe":
            vues = [c for c in coupes_faibles_s if abs(c - d) <= MAITRE_ECART_COUPE_S]
        # Une « suite » qui change de valeur de plan (« Medium shot ») : H3 y coupe quand même
        # (essai à blanc du 03/10, « Le phare », plan 2). Vue, elle se traite en coupe : l'image
        # partagée serait celle du changement de cadre.
        coupe = k > 0 and (p.get("enchainement", "coupe") == "coupe" or bool(vues))
        if coupe and not vues and continus is not None:
            continus.append(k + 1)
            coupe = False
        coupes.append(coupe)
        if k == 0:
            debuts.append(0)
        elif not coupe:
            debuts.append(round(d * IMAGES_PAR_SECONDE))
        else:
            if vues:
                debuts.append(round(min(vues, key=lambda c: abs(c - d)) * IMAGES_PAR_SECONDE) + 1)
            else:
                manquees.append(k + 1)
                debuts.append(None)
    if manquees:
        raise ValueError("Le clip maître n'a pas fait la coupe du plan %s : rejouez-le avant de le déplier."
                         % ", ".join(map(str, manquees)))
    cles = []
    for k, debut in enumerate(debuts):
        if k + 1 == len(debuts):
            fin = images - 1
        elif coupes[k + 1]:
            fin = debuts[k + 1] - 2
        else:
            fin = debuts[k + 1]
        if fin <= debut:
            raise ValueError("Le plan %d est trop court dans le clip maître pour être déplié." % (k + 1))
        cles.append((debut, fin))
    return cles


# --- La première et la dernière image, par l'image du Studio ------------------------

# Une taille paysage : le routeur la traduit en 16:9 pour Google (aspect_ratio
# de free-tier-manager). La page recadre ensuite en 832 x 480 sans déformer.
TAILLE_IMAGE_DEMANDEE = "1664x960"


AMELIORATIONS_MAX = 10


def texte_image(texte: str, ameliorations=()) -> str:
    """La description, suivie des améliorations demandées par le client sur les
    images précédentes. Demande du propriétaire, 28/09 : le client peut faire
    refaire l'image de départ en disant ce qui doit changer, jusqu'à la valider."""
    t = " ".join(str(texte or "").split())
    if not t:
        raise ValueError("Décrivez l'image à créer.")
    if not isinstance(ameliorations, (list, tuple)):
        raise ValueError("Améliorations illisibles.")
    ajouts = [a for a in (" ".join(str(x or "").split()) for x in ameliorations) if a]
    if len(ajouts) > AMELIORATIONS_MAX:
        raise ValueError("Dix améliorations au plus : reportez les premières dans la description.")
    if ajouts:
        t += " Améliorations demandées : " + " ; ".join(ajouts) + "."
    if len(t) > 2000:
        raise ValueError("Description d'image trop longue (2 000 caractères au plus).")
    return t


# L'image du Studio avec les photos des fiches (demande du propriétaire, 28/09 :
# « le portrait n'est pas suffisant ») : toutes les photos de chaque personnage,
# dans l'ordre, et chacun présenté par son nom et ses numéros d'images.
PHOTOS_IMAGE_MAX = 14   # le routeur (Gemini 3.1 Flash Lite Image) n'en prend pas plus
# L'image de départ place les figurants que H3 fera bouger : loin, jamais au bord
# ni à moitié cachés, car le modèle vidéo les perd (plan 2 du 28/09, CADRAGE).
# « S'il y a » : dit « les autres personnes », la consigne en a ajouté derrière un
# portrait sur fond uni (essai du 28/09).
FIGURANTS_IMAGE = ("S'il y a d'autres personnes que celles décrites (passants, clients), elles restent à distance, "
                   "au second plan, jamais au premier plan, au bord de l'image ou à moitié cachées ; "
                   "peu d'objets au premier plan.")
# 03/10, quatrième story-board du « Jardin de verre » : le juge voyait le défaut (un meuble ajouté
# au plan 7, Mila disparue à la fin du plan 5), mais le second dessin, demandé à l'identique, le
# refaisait. Le redessin reçoit les fautes du juge ; la description de l'image n'en garde rien.
CONSIGNE_A_EVITER = "Un premier dessin de cette image avait ces fautes, à ne pas refaire : %s. "
A_EVITER_MAX = 6


def _data_url(b64: str) -> str:
    """Une image en base64 nu (PNG, JPEG ou WebP) en data URL, son type lu dans ses octets."""
    octets = base64.b64decode(b64[:32] + "=" * (-len(b64[:32]) % 4))
    genre = next((g for debut, g in _EXTENSIONS.items() if octets.startswith(debut)), ".png")
    return f"data:{_TYPES[genre]};base64,{b64}"


# La coupe part de la dernière image du plan d'avant, retouchée (02/10). « Leila et un
# martien », plan 5 : parti de l'image de la coupe d'avant (plan 1, soucoupe encore dans
# le ciel), le télescope est passé à droite et la soucoupe posée a disparu. Essai réel du
# 02/10 avec cette consigne, deux images : soucoupe à droite et télescope à gauche gardés,
# cadrage changé. Gabarit de Google : « change only… Keep everything else… exactly the same ».
CONSIGNE_COUPE = ("L'image jointe %d est la dernière image du plan précédent : ceci est une COUPE vers le plan "
                  "suivant, au même endroit et au même instant. Garder exactement le même lieu, la même lumière, "
                  "le même style, et chaque objet du décor à la même place dans le lieu (ce qui est à gauche reste à "
                  "gauche, ce qui est à droite reste à droite, rien n'apparaît ni ne disparaît) ; seuls le cadrage, "
                  "l'angle de la caméra et la pose des personnes changent, comme la description le dit. ")
# Le décor a sa fiche (02/10, propriétaire : « les coupes doivent changer drastiquement
# l'image par rapport à celle de fin […] le décor doit avoir son id image pour la
# consistance »). Film 4, plan 2 : refait depuis la dernière image du plan 1, un gros
# plan, le lieu est sorti inventé (brique et terrasse de café au lieu de pierre beige).
# 03/10, « Le jardin de verre » : le canapé beige du décor est revenu en fauteuil à droite
# (plan 1), contre un autre mur ou au premier plan (plans 3, 4, 6) — « le fauteuil se
# balade », « le canapé aurait dû faire partie du décor id » (propriétaire). Les meubles
# sont nommés ici, et décrits dans la fiche (consigne_decor_du_texte).
CONSIGNE_LIEU = ("L'image jointe %d est le DÉCOR du film, vide de personnes : c'est le même lieu, avec les mêmes "
                 "bâtiments, le même sol, la même lumière et chaque élément fixe à la même place (ce qui est à "
                 "gauche reste à gauche, rien n'apparaît ni ne disparaît) ; les MEUBLES (canapé, fauteuil, table, "
                 "étagère…) sont exactement ceux du décor, même forme, même taille, même couleur, à la même place "
                 "contre les mêmes murs : aucun n'est ajouté, retiré, déplacé ni remplacé. Les personnes et les "
                 "objets se placent comme la description le dit. La caméra reste du côté d'où le décor est vu "
                 "(règle des 180°) : seul ce que le décor montre peut être à l'image, jamais le côté qui est "
                 "derrière elle. ")
# Les images de départ faites avant le tournage (03/10) : une coupe reçoit aussi l'image de la
# coupe d'avant, pour le lieu seulement — l'action a pu changer les objets entre les deux.
CONSIGNE_MEUBLES = ("L'image jointe %d est une image antérieure du même film, dans ce lieu : les murs, les fenêtres, "
                    "les portes et les MEUBLES y sont tels qu'ils doivent rester (même forme, taille, couleur et "
                    "place) ; les personnes et les objets, eux, suivent la description, pas cette image. ")
# 03/10, « la multiview est fausse », puis « on construira un décor 3d plus tard » (propriétaire) :
# l'image du Studio ne sait pas tourner autour d'un lieu (vues demandées une à une : trois fois le
# même mur). Plus de planche du décor ; la coupe change de valeur de plan ou d'angle sans passer
# derrière la caméra de la vue d'ensemble (règle des 180°).
CONSIGNE_COUPE_LIEU = ("Ceci est une COUPE : le cadrage et l'angle de la caméra sont NETTEMENT différents de ceux du "
                       "plan précédent (une autre valeur de plan, un autre angle du même côté), comme la description "
                       "le dit. ")
# 03/10, « Le jardin de verre », plan 2 : avec la fiche du décor, la coupe n'avait plus la
# dernière image du plan 1 ; le pot, haut et cylindrique près de Mila, est revenu en coupe
# basse devant un autre canapé. Propriétaire : une coupe part « des fiches et du plan final,
# mais avec un autre angle de vue ». Le décor donne le lieu, la dernière image l'instant.
CONSIGNE_ETAT_COUPE = ("L'image jointe %d est la dernière image du plan précédent : elle donne l'ÉTAT du lieu à cet "
                       "instant — où est chaque objet dans la pièce par rapport aux meubles et aux murs, sa forme, sa "
                       "taille, sa couleur, ce qu'il contient, et où sont les personnes. La nouvelle image montre ce "
                       "même instant, tout cela inchangé ; seuls le cadrage et l'angle de la caméra changent. ")
RACCORD_ESSAIS = 2   # une image de coupe au faux raccord est redessinée une fois, puis le film s'arrête


def consigne_raccord(description: str) -> str:
    """Pour le juge : la dernière image d'un plan (1) et l'image de départ de la coupe qui suit (2)."""
    return ("Image 1 is the last frame of a shot. Image 2 is the first frame of the next shot: a CUT to another "
            "framing of the same place at the same instant, described as: %s\n"
            "The framing and the camera angle are SUPPOSED to change: never count that as a fault, nor an element "
            "that is simply outside the new frame (a close-up on an object does not show the people around it: "
            "they are NOT missing). Check only, for what both images show: (a) the fixed elements "
            "of the place (walls, windows, doors, furniture) are the same ones, in the same positions relative to "
            "each other; (b) each object is the same — same shape, size, colour and content — and stands at the "
            "same place in the room relative to the furniture and the people; (c) nothing is in image 2 that was "
            "not in image 1. Answer JSON only: {\"ok\": true or false, \"fautes\": [\"one short sentence per "
            "fault, naming the element\"]}." % " ".join(str(description or "").split()))


def consigne_depart_conforme(texte: str) -> str:
    """Pour le juge : l'image de départ d'un plan, contre le texte du plan (film 5 relancé, 04/10 : une rue
    de ville pour « in the garden » ; le relecteur de la continuité l'a vu, après coup)."""
    return ("This image is the FIRST frame of a film shot. The shot is described below; what happens later in "
            "the shot (actions, things that fall, arrive or appear) must NOT be in the image yet. Check only: "
            "(a) the place and the setting; (b) the time of day and the light; (c) the framing; (d) the "
            "characters and objects that are there from the start, where they stand and face. Answer JSON only: "
            "{\"ok\": true or false, \"fautes\": [\"one short sentence per fault, saying what the image shows "
            "and what the text says\"]}.\n\nShot: " + sans_paroles(texte))


def consigne_retouche(noms: list, etats: str = "") -> str:
    """Pour le juge : l'image du maître (1), sa retouche (2), puis les photos des fiches, une par nom.
    `etats` : l'état de départ des éléments du plan (etats_au_debut) ; image 2 le suit, pas image 1."""
    photos = ", ".join("image %d is %s" % (k + 3, n) for k, n in enumerate(noms))
    e = (" (e) each element of image 2 is in this start state, even where image 1 shows it otherwise (a light "
         "switched off, an object held another way): %s A change of image 1 that brings an element to this state "
         "is not a fault; an element of image 2 in another state is one." % etats) if etats else ""
    return ("Image 1 is a frame of a film. Image 2 is the same frame redrawn so that each character looks exactly "
            "like their reference photo (%s). Check only: (a) image 2 keeps the framing, the camera, the place, the "
            "light, the objects, and where each character stands and faces, as in image 1 (a character redrawn may "
            "change size, shape and pose to become the one of their photo: that is not a fault); (b) each "
            "character of image 2 matches their photo (shape, size, material, colours, face, clothes); (c) nobody appears "
            "twice, and nobody is added or missing compared with image 1; (d) no object is added, moved or removed "
            "and nobody looks in another direction (an object on the ground in image 2 but not in image 1 is a "
            "fault).%s Answer JSON only: {\"ok\": true or false, "
            "\"fautes\": [\"one short sentence per fault, naming the character or element\"], "
            # Essais D et E du plan 6, 04/10 : Pixel remplacé par une fille, dessin gardé à égalité de fautes,
            # et H3 a fait deux Leila. Les personnages faux se disent à part (CONSIGNE : noms exacts).
            "\"faux\": [\"the exact name of each character who, in image 2, is missing, appears twice, is "
            "replaced by someone else or does not look like their photo\"]}." % (photos, e))


def lire_retouche(reponse: str, noms: list) -> tuple:
    """(fautes, faux) du juge de la retouche : `faux`, les noms (parmi `noms`) des personnages absents,
    doublés, remplacés ou qui ne ressemblent pas à leurs photos. ValueError si illisible."""
    fautes = lire_raccord(reponse)
    if not fautes:
        return [], []
    t = str(reponse)
    d = json.loads(t[t.find("{"):t.rfind("}") + 1])
    dits = {" ".join(str(n).split()).casefold() for n in d.get("faux") or [] if isinstance(n, str)}
    return fautes, [n for n in noms if n.casefold() in dits]


# 03/10, story-board du « Jardin de verre » : l'image de fin du plan 3 (l'arbre envahit la
# pièce) a changé de salon — bibliothèque remplie, lampe chaude, autre fenêtre, un second
# arbre — et les coupes 4 et 5, parties d'elle, en ont hérité. Seul le début d'une coupe
# était jugé ; la fin se juge contre le début du même plan, et contre le décor s'il y en a un.
def consigne_controle_fin(description: str, avec_decor: bool = False) -> str:
    """Pour le juge : la première image d'un plan (1), sa dernière image (2), le décor vide (3)."""
    decor = (" Image 3 is the empty set of the film: the walls, windows, doors and furniture of image 2 must "
             "be the ones of image 3 (same shape, colour and place)." if avec_decor else "")
    return ("Image 1 is the first frame of a shot and image 2 its LAST frame, same camera, after this action: "
            "%s\nWhat the action changes is SUPPOSED to change (what grows, appears, moves or leaves as "
            "described): never count that as a fault, nor a small camera move.%s Check only: (a) the place is the "
            "same room — same walls, windows, doors, light sources and furniture, same shapes and colours, at the "
            "same places; (b) every object the action does not change is the same and at the same place; (c) no "
            "person, animal or object is in image 2 that neither image 1 nor the action brings, and nothing is "
            "there twice. Answer JSON only: {\"ok\": true or false, \"fautes\": [\"one short sentence per fault, "
            "naming the element\"]}." % (" ".join(str(description or "").split()), decor))


def lire_raccord(reponse: str) -> list:
    """Les fautes de raccord ([] si tout va) ; ValueError si la réponse est illisible."""
    t = str(reponse or "")
    debut, fin = t.find("{"), t.rfind("}")
    try:
        d = json.loads(t[debut:fin + 1]) if debut >= 0 else None
    except ValueError:
        d = None
    if not isinstance(d, dict) or not isinstance(d.get("ok"), bool):
        raise ValueError("réponse du juge illisible pour le raccord")
    fautes = [" ".join(str(f).split()) for f in d.get("fautes") or [] if str(f).strip()]
    return [] if d["ok"] else (fautes or ["faux raccord (sans détail)"])


# 03/10, « Le jardin de verre » : « Google n'a renvoyé aucune image » sur l'image de départ du
# plan 3 (« Crystal trunks burst from the parquet… »), et le film s'arrêtait avant le premier
# plan, sans dire lequel. Un refus se redemande ; au dernier essai, la description est redite.
CONSIGNE_REFORMULER_DEPART = (
    "An image generator returned no image for this description (probably refused). Rewrite it so that it "
    "is accepted: same place, same framing, same characters and objects in the same positions, same "
    "action; plain, calm, concrete words; nothing violent or bodily, no ages. Keep the language of the "
    "description. Answer with the rewritten description only, one paragraph.\n\nDescription:\n%s")


def reformuler_depart(texte: str, reponse: str) -> str:
    """La description redite par le chat, préfixe de départ gardé ; `texte` si la réponse est vide ou hors sujet."""
    corps = str(texte or "")
    prefixe = PREFIXE_DEPART if corps.startswith(PREFIXE_DEPART) else ""
    redite = " ".join(str(reponse or "").split()).strip("\"'« »")
    if not redite or len(redite) > 3 * max(len(corps), 200):
        return corps
    return prefixe + (redite[len(prefixe):] if prefixe and redite.startswith(prefixe) else redite)


def demande_image(texte: str, ameliorations=(), fiches=(), decor=None, tenues=None, coupe: bool = False,
                  lieu=None, fin_de=None, meubles=None, a_eviter=(), retouche=None) -> tuple:
    """(demande au routeur, description de l'image). La description est ce que
    l'image montre, sans la présentation des photos : c'est elle qui passe à H3.

    `tenues` : {fiche: photo de la tenue du plan (base64)} ; cette fiche ne joint
    alors que son portrait de face et cette photo (29/09 : la même tenue sur
    l'image de départ que dans le plan tourné).

    `decor` : le numéro d'une image de départ déjà gardée (celle du plan d'avant),
    jointe en dernier pour garder le même lieu. Le 28/09, le plan 2 décrit par
    écrit seulement (« Le Chat Noir ») est sorti avec le même nom mais un autre
    auvent et une autre rue (remarque du propriétaire).

    `lieu` : la fiche « décor » du film ; son image remplace `decor` comme référence du
    lieu, et une coupe change alors franchement de cadrage (CONSIGNE_COUPE_LIEU).

    `a_eviter` : les fautes que le juge a trouvées au dessin précédent (CONSIGNE_A_EVITER)."""
    description = texte_image(texte, ameliorations)
    if not isinstance(a_eviter, (list, tuple)):
        raise ValueError("Fautes à éviter illisibles.")
    fautes = [f for f in (" ".join(str(x or "").split()).rstrip(".") for x in a_eviter) if f][:A_EVITER_MAX]
    if not isinstance(fiches, (list, tuple)) or len(set(map(str, fiches))) != len(fiches):
        raise ValueError("Liste de fiches illisible.")
    photos, presentation = [], []
    tenues = tenues or {}
    for fid in fiches:
        fiche = fiche_lire(fid)
        tenue = tenues.get(fid)
        urls = ([_data_url(b) for b in fiche_images(fid, visage_seul=True)] if tenue
                else [fiche_image_data_url(fid, a) for a in ANGLES if a in fiche["images"]])
        if not urls:
            raise ValueError(f"La fiche « {fiche['nom']} » n'a encore aucune image : créez-les d'abord.")
        planche = None if tenue else fiche_planche_data_url(fid)   # la planche montre l'ancienne tenue
        if planche:   # la même personne sous tous les angles (28/09)
            urls.append(planche)
        if tenue:
            urls.append(_data_url(tenue))
        n = len(photos)
        qui = {"objet": "l'objet", "pose": "la pose des mains"}.get(fiche.get("genre"), "la personne")
        presentation.append("%s est %s des images jointes %d à %d" % (fiche["nom"], qui, n + 1, n + len(urls))
                            if len(urls) > 1 else "%s est %s de l'image jointe %d" % (fiche["nom"], qui, n + 1))
        if tenue:
            presentation[-1] += ", vêtue exactement comme sur l'image jointe %d" % (n + len(urls))
        photos += urls
    # Les photos d'une fiche peuvent montrer plusieurs tenues : celle de la
    # description l'emporte (essai du 28/09 : photos en sweat et en débardeur).
    tete = ("; ".join(presentation) + " (mêmes visage et coiffure ; même tenue, sauf si la description en "
            "donne une). Chaque personne apparaît une seule fois. "
            # 03/10, « Le phare » : deux images de départ sur deux avaient une silhouette floue au
            # fond, que H3 a faite second Oscar (le juge : « Oscar apparaît dédoublé »).
            "Personne d'autre à l'image : ni passant, ni figurant, ni silhouette au fond, sauf si la "
            "description en demande. ") if photos else ""
    lieu_rang = None   # la plaque du lieu : <image1> de Qwen (retouche_qwen.depuis_demande_image)
    if lieu:
        photos.append(fiche_lieu_image(lieu))
        lieu_rang = len(photos)
        tete += CONSIGNE_LIEU % len(photos) + (CONSIGNE_COUPE_LIEU if coupe else "")
        if decor and coupe:   # et l'instant : la dernière image du plan d'avant (03/10)
            octets = depart_lire(decor)
            genre = next(g for debut, g in _EXTENSIONS.items() if octets.startswith(debut))
            photos.append(f"data:{_TYPES[genre]};base64," + base64.b64encode(octets).decode())
            tete += CONSIGNE_ETAT_COUPE % len(photos)
        elif meubles:   # une image antérieure du film : ses meubles, pas ses objets (03/10)
            octets = depart_lire(meubles)
            genre = next(g for debut, g in _EXTENSIONS.items() if octets.startswith(debut))
            photos.append(f"data:{_TYPES[genre]};base64," + base64.b64encode(octets).decode())
            tete += CONSIGNE_MEUBLES % len(photos)
    elif decor:
        octets = depart_lire(decor)
        genre = next(g for debut, g in _EXTENSIONS.items() if octets.startswith(debut))
        photos.append(f"data:{_TYPES[genre]};base64," + base64.b64encode(octets).decode())
        lieu_rang = len(photos)
        # Le 28/09, « garder le même lieu » a recopié la pelouse du plan 1 dans
        # un plan 2 voulu devant une résidence : le lieu précis suit la description.
        if coupe:   # `decor` est la dernière image du plan tourné juste avant (02/10)
            tete += CONSIGNE_COUPE % len(photos)
        else:
            tete += ("L'image jointe %d est le plan précédent : garder le même univers, la même lumière et le même "
                     "style ; l'endroit précis, le cadrage et la place des personnes suivent la description, et si "
                     "elle dit le même endroit, garder aussi le même décor et les mêmes enseignes. " % len(photos))
    if retouche:   # une image du maître (04/10), redessinée d'après les fiches (CONSIGNE_RETOUCHE)
        octets = depart_lire(retouche)
        genre = next(g for debut, g in _EXTENSIONS.items() if octets.startswith(debut))
        photos.append(f"data:{_TYPES[genre]};base64," + base64.b64encode(octets).decode())
        tete += CONSIGNE_RETOUCHE % len(photos)
    if fin_de:   # l'image de fin (03/10) : l'image de début du même plan, jointe en dernier
        octets = depart_lire(fin_de)
        genre = next(g for debut, g in _EXTENSIONS.items() if octets.startswith(debut))
        photos.append(f"data:{_TYPES[genre]};base64," + base64.b64encode(octets).decode())
        tete += CONSIGNE_FIN % len(photos)
    if len(photos) > PHOTOS_IMAGE_MAX:
        raise ValueError("Quatorze photos au plus sur une image (fiches et plan précédent) : retirez un personnage.")
    if fautes:
        tete += CONSIGNE_A_EVITER % " ; ".join(fautes)
    demande = {"prompt": tete + description + " " + FIGURANTS_IMAGE, "n": 1, "size": TAILLE_IMAGE_DEMANDEE}
    if photos:
        demande["image_reference"] = photos
    if lieu_rang:
        demande["lieu_jointe"] = lieu_rang   # retiré avant le routeur (_image_du_studio)
    return demande, description


# Les images de départ des plans d'un scénario : gardées sur le Studio, un plan
# n'en porte que le numéro (le scénario reste un petit fichier).
DOSSIER_DEPARTS = budget_modal.CONFIG_DIR / "h3-departs"
_ID_DEPART = re.compile(r"[0-9a-f]{24}")


def depart_poser(image: str) -> str:
    octets = base64.b64decode(_image(image, "Image de départ"))
    ext = next(e for debut, e in _EXTENSIONS.items() if octets.startswith(debut))
    did = hashlib.sha256(octets).hexdigest()[:24]
    DOSSIER_DEPARTS.mkdir(parents=True, exist_ok=True)
    (DOSSIER_DEPARTS / (did + ext)).write_bytes(octets)
    return did


def depart_lire(did) -> bytes:
    if not _ID_DEPART.fullmatch(str(did or "")):
        raise ValueError("Image de départ inconnue.")
    for chemin in DOSSIER_DEPARTS.glob(str(did) + ".*"):
        return chemin.read_bytes()
    raise ValueError("Image de départ introuvable sur ce Studio : recréez-la.")


# --- Les fiches de casting (PLAN 18.9, V2) ----------------------------------------
# Un personnage décrit une fois, et ses images, rejouées à chaque plan en mode
# « Références ». Demande du propriétaire, 28/09 : « tu automatises la création
# des images du casting à partir du texte, possibilité de rejouer ou supprimer
# certaines ». Le portrait de face part du texte ; les autres angles partent du
# portrait (image de départ envoyée à Google), pour garder le même visage.
# Le prompt suit le guide de MiniMax (docs/VIDEO_PROMPT_WRITING_GUIDE_ref_en.md) :
# `<Subject 1>` défini une fois par ses `<Picture N>`, `<Subject 1> (S1)` quand il parle.

DOSSIER_FICHES = budget_modal.CONFIG_DIR / "h3-fiches"
ANGLES = {   # l'ordre est celui des <Picture N>
    "face": ("De face", "portrait de face, cadré aux épaules, regard vers l'objectif"),
    "trois_quarts": ("Trois-quarts", "portrait de trois-quarts, cadré à la taille"),
    "pied": ("En pied", "en pied, de face, debout, tout le corps visible"),
    "profil": ("Profil", "de profil, cadré à la taille"),
}
ANGLE_DEPART = "face"
FICHE_NOM_MAX, FICHE_DESCRIPTION_MAX = 60, 800
DECOR_DESCRIPTION_MAX = 1400   # un décor décrit ses côtés et sa lumière (03/10, COTES_DU_LIEU)
TAILLE_IMAGE_FICHE = "1024x1024"
_ID_FICHE = re.compile(r"[0-9a-f]{12}")
_EXTENSIONS = {b"\x89PNG": ".png", b"\xff\xd8\xff": ".jpg", b"RIFF": ".webp"}
_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp"}


def _dossier_fiche(fid) -> Path:
    if not _ID_FICHE.fullmatch(str(fid or "")):
        raise ValueError("Fiche inconnue.")
    return DOSSIER_FICHES / str(fid)


def fiche_lire(fid) -> dict:
    try:
        return json.loads((_dossier_fiche(fid) / "fiche.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("Fiche inconnue.") from exc


def _fiche_ecrire(fiche: dict) -> None:
    dossier = _dossier_fiche(fiche["id"])
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / "fiche.json").write_text(json.dumps(fiche, ensure_ascii=False, indent=1), encoding="utf-8")


def fiches_liste() -> list:
    fiches = []
    for f in sorted(DOSSIER_FICHES.glob("*/fiche.json")) if DOSSIER_FICHES.is_dir() else []:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        fiches.append({"id": d["id"], "nom": d["nom"], "description": d["description"],
                       "angles": [a for a in ANGLES if a in d.get("images", {})], "cree_le": d["cree_le"],
                       "tenues": [t["tenue"] for t in (d.get("tenues") or {}).values()],
                       "genre": d.get("genre") or "personne", "voix": bool(d.get("voix"))})
    return sorted(fiches, key=lambda d: d["cree_le"])


# Une fiche peut être un OBJET (29/09, demande du propriétaire : « un nom comme
# <le ballon> pour le même objet tout le long du script »). Le guide de MiniMax
# (ref-en.txt) donne <Subject N> aux « people, animals, or objects… props », toujours
# rattaché à une image ; sans image, une étiquette est « non résolue ». L'objet a
# donc sa photo, comme un personnage : son nom dans le texte devient <Subject N>.
# Une POSE aussi (29/09, « améliorer les mains ») : le guide de MiniMax range « a pose »
# parmi les <Subject N> ; une image du geste des mains donne au modèle un geste réel
# à suivre au lieu de le deviner.
# Un DÉCOR aussi (02/10) : le lieu du film, vide de personnes, joint à chaque image de
# départ de coupe (`demande_image(lieu=)`). Il ne part jamais à H3 : réglage `decor` du
# scénario, hors de `fiches`, il ne compte pas dans les neuf images.
GENRES_FICHE = ("personne", "objet", "pose", "decor")


def fiche_est_objet(fiche: dict) -> bool:
    """Pas une personne (objet, pose ou décor) : ni réplique, ni tenue."""
    return fiche.get("genre") in ("objet", "pose", "decor")


def fiche_lieu_image(fid) -> str:
    """L'image (data URL) d'une fiche « décor ». ValueError si ce n'en est pas une, ou sans image."""
    fiche = fiche_lire(fid)
    if fiche.get("genre") != "decor":
        raise ValueError(f"« {fiche['nom']} » n'est pas une fiche de décor.")
    if ANGLE_DEPART not in (fiche.get("images") or {}):
        raise ValueError(f"Le décor « {fiche['nom']} » n'a pas encore d'image : créez-la d'abord.")
    return fiche_image_data_url(fid, ANGLE_DEPART)


SON_LIEU_MAX_OCTETS = 4 * 1024 * 1024   # ~20 s de WAV stéréo 48 kHz


def fiche_poser_son_lieu(fid, wav: bytes) -> dict:
    """La piste son d'un décor (03/10, propriétaire : « un son track id along the clip ») :
    un passage sans paroles du premier film tourné dans ce lieu ; le fond sonore des films
    suivants en est fait (montage.egaliser_ambiance)."""
    fiche = fiche_lire(fid)
    if fiche.get("genre") != "decor":
        raise ValueError(f"« {fiche['nom']} » n'est pas une fiche de décor.")
    if not (wav[:4] == b"RIFF" and wav[8:12] == b"WAVE") or len(wav) > SON_LIEU_MAX_OCTETS:
        raise ValueError("La piste son du lieu doit être un WAV de 4 Mo au plus.")
    (_dossier_fiche(fid) / "lieu.wav").write_bytes(wav)
    fiche["son_lieu"] = "lieu.wav"
    _fiche_ecrire(fiche)
    return fiche


def fiche_son_lieu(fid):
    """La piste son d'un décor (WAV), ou None."""
    try:
        fiche = fiche_lire(fid)
    except ValueError:
        return None
    if fiche.get("genre") != "decor" or not fiche.get("son_lieu"):
        return None
    try:
        return (_dossier_fiche(fid) / fiche["son_lieu"]).read_bytes()
    except OSError:
        return None


def fiche_creer(nom: str, description: str, genre: str = "personne") -> dict:
    if genre not in GENRES_FICHE:
        raise ValueError("Une fiche est une personne, un objet, une pose ou un décor.")
    nom, description = " ".join(str(nom or "").split()), " ".join(str(description or "").split())
    if not nom or len(nom) > FICHE_NOM_MAX:
        raise ValueError(f"Donnez un nom à la fiche ({FICHE_NOM_MAX} caractères au plus).")
    plafond = DECOR_DESCRIPTION_MAX if genre == "decor" else FICHE_DESCRIPTION_MAX
    if not description or len(description) > plafond:
        raise ValueError(f"Décrivez-la ({plafond} caractères au plus) : "
                         + ("âge, visage, coiffure, tenue." if genre == "personne" else
                            "forme, couleur, matière." if genre == "objet" else
                            "le lieu : bâtiments, sol, éléments fixes, lumière." if genre == "decor" else
                            "ce que fait chaque main et ses doigts."))
    fiche = {"id": os.urandom(6).hex(), "nom": nom, "description": description,
             "cree_le": time.strftime("%Y-%m-%d %H:%M:%S"), "images": {}}  # date-machine
    if genre != "personne":
        fiche["genre"] = genre
    _fiche_ecrire(fiche)
    return fiche


# --- Les objets clefs d'un scénario (02/10) -----------------------------------------
# « Leila et un martien », deuxième tournage : la soucoupe vire à la voiture des plans 3
# à 5, et « le biscuit est un élément clef aussi, il change entre plan » (le
# propriétaire). Seules les personnes avaient une fiche : H3 réinventait chaque objet à
# chaque plan. Un objet que le tableau des plans fait revenir reçoit une fiche d'objet,
# faite par l'image du Studio : une seule image, l'objet sous plusieurs angles (la
# « fiche multiface » demandée pour la soucoupe), qui ne coûte qu'une place sur les neuf.
CONSIGNE_OBJET_VUES = (
    "Planche de référence d'un seul et même objet, photographie réaliste, fond gris clair uni, lumière "
    "douce et égale : quatre vues côte à côte, à la même taille — de face, de profil, de dos et de "
    "trois-quarts au-dessus. Le même modèle exactement sur les quatre vues ; sans marque, logo ni texte, "
    "aucune personne.")
CADRE_DECOR = ("Vue d'ensemble large du lieu seul, à hauteur d'homme, cadrage paysage : tout le lieu visible, "
               "vide de personnes et d'animaux, sans texte ni enseigne lisible ; l'heure et la lumière de la "
               "description, photographie réaliste. Rien que ce que la description nomme : aucun objet ni plante "
               "en plus.")
# 03/10, « Le jardin de verre » : le décor tiré du texte montrait une pousse dans le pot que
# le plan 2 devait voir naître ; la règle 6 a arrêté le film, puis, forcé, l'effet a disparu.
# --- La fiche du décor D'APRÈS LE FILM (02/10) ---------------------------------------
# Film 4 : la fiche du décor, faite d'après la seule image de départ du plan 1 (gros plan)
# et la description « a round stone fountain with a carved central pillar », montrait une
# colonne sur un bassin bas ; le film, dès le plan 2, a une vasque à deux étages sur un
# bassin haut. La coupe du plan 5 a recopié la fiche, pas le film. Propriétaire : « la
# planche décor détaillée aussi dans studio, on l'utilise pour le plan 5 ». Elle part donc
# des images VRAIES du film (fins des plans tournés), décrites en détail par le juge, et
# porte une planche multi-vues faite d'elles.
DECOR_IMAGES_MAX = 4


def images_pour_decor(fins: list) -> list:
    """Les numéros d'image à lire : la dernière de chaque plan tourné, DECOR_IMAGES_MAX au
    plus, réparties du premier plan au dernier (le dernier toujours)."""
    dernieres = [f - 1 for f in fins if f > 0]
    if len(dernieres) <= DECOR_IMAGES_MAX:
        return dernieres
    pas = (len(dernieres) - 1) / (DECOR_IMAGES_MAX - 1)
    return sorted({dernieres[round(k * pas)] for k in range(DECOR_IMAGES_MAX)})


# Les côtés vus du lieu et sa lumière (03/10, « Le jardin de verre ») : ce que la description
# n'en disait pas, chaque coupe l'inventait autrement ; le décor était en plein jour pour un
# film au coucher du soleil, et les images passaient du jour blanc à l'orange d'un plan à l'autre.
COTES_DU_LIEU = ("Then describe the place side by side, as seen from its main viewpoint (the camera never goes "
                 "behind it): the FAR side facing it, the LEFT side and the RIGHT side; for each, what stands "
                 "along it, or that it is bare. Then the time of day and the light, as the script gives them at "
                 "its start (or one plausible light): where it comes from, its colour, how strong. ")


def consigne_decor_du_film(nombre: int) -> str:
    return ("The %d attached images are frames of one short film, all shot in the same place. Describe THE PLACE "
            "ONLY, for an image model that must redraw it empty of people: every fixed element you can see "
            "(fountains, statues, benches, steps, doors, windows, lamps, signs, trees, ground; indoors, every "
            "piece of furniture: sofa, armchair, table, shelf, rug), with its exact "
            "shape (how many tiers or levels, how high compared with a seated person, what material, what "
            "colour), and where it stands relative to the others (left, right, behind, in front). %s"
            "Prefer what several images agree on. Never describe people, animals, vehicles or anything held; "
            "never invent an element no image shows (a side no image shows is plain, consistent with the "
            "rest). Answer JSON only: {\"nom\": \"a short English name of the place, 2-5 words\", "
            "\"description\": \"the place in English, one paragraph, %d characters at most\"}."
            % (nombre, COTES_DU_LIEU, DECOR_DESCRIPTION_MAX - 50))


def lire_decor_du_film(reponse: str) -> dict:
    """{nom, description} ; ValueError si illisible."""
    t = str(reponse or "")
    debut, fin = t.find("{"), t.rfind("}")
    try:
        d = json.loads(t[debut:fin + 1]) if debut >= 0 else None
    except ValueError:
        d = None
    nom = " ".join(str((d or {}).get("nom") or "").split())[:FICHE_NOM_MAX] if isinstance(d, dict) else ""
    description = " ".join(str((d or {}).get("description") or "").split()) if isinstance(d, dict) else ""
    if not nom or len(description) < 80:
        raise ValueError("La description du décor n'a pas pu être lue : rien n'est créé.")
    return {"nom": nom, "description": description[:DECOR_DESCRIPTION_MAX]}


CONSIGNE_DECOR_DU_FILM = ("Les images jointes 1 à %d sont des images d'un film tourné dans ce lieu. Fais la vue "
                          "d'ensemble de CE lieu, exactement : chaque élément fixe avec sa forme, son nombre "
                          "d'étages, sa hauteur, sa matière et sa place, comme sur les images jointes et dans la "
                          "description ; sans aucune personne, aucun animal, aucun vélo ni objet tenu. ")
def demandes_decor_du_film(description: str, images: list) -> dict:
    """La demande de la vue d'ensemble, les images vraies jointes. Plus de planche du décor
    (03/10 : ses vues d'autres côtés étaient fausses, voir CONSIGNE_COUPE_LIEU)."""
    n = len(images)
    return {"prompt": CONSIGNE_DECOR_DU_FILM % n + f"Description : {description}. {CADRE_DECOR}", "n": 1,
            "size": TAILLE_IMAGE_DEMANDEE, "image_reference": list(images)}


# --- La fiche du décor D'APRÈS LE TEXTE (03/10) ---------------------------------------
# Propriétaire, 03/10 : « corrige la fontaine qui change entre les plans de façon
# générique ». Film 4 : sa fiche de décor n'est venue qu'au plan 5, faite d'après le film ;
# avant, chaque coupe redessinait le lieu d'après la fin du plan d'avant (un gros plan :
# fontaine hors champ, réinventée). Et H3 ne la recevait jamais (`decor_video`). Un
# scénario tourné dans un seul lieu reçoit donc sa fiche AVANT la première image, faite
# du texte : une vue vide large, puis la planche à quatre vues tirée de cette vue. Pas
# d'après l'image de départ du plan 1 : souvent un gros plan (le 02/10, colonne sur un
# bassin bas au lieu d'une vasque à deux étages).
def consigne_decor_du_texte(textes: list) -> str:
    plans = " ".join("[Shot %d] %s" % (k + 1, " ".join(str(t).split())) for k, t in enumerate(textes))
    return ("Here is the script of a short film, shot by shot: %s\n"
            "Does the whole film happen in ONE single place (the camera may move inside it)? If so, describe "
            "THE PLACE ONLY, for an image model that must draw it empty of people, so that every shot shows the "
            "same place: every fixed element the script names or implies (fountains, statues, benches, steps, "
            "doors, windows, lamps, trees, ground), each with ONE precise shape (how many tiers or levels, how "
            "many water jets, how high compared with a seated person, what material, what colour) and where it "
            "stands relative to the others (left, right, behind, in front). Indoors, also EVERY piece of "
            "furniture the room has, even if the script does not name it (sofa, armchair, table, shelf, rug, "
            "lamp), each with its shape, size, colour and the wall it stands against, and say there is no other "
            "furniture. %sWhere the script is vague, choose one "
            "plausible precise form consistent with it. Never describe people, animals, vehicles or anything "
            "held, nor the props the characters use or that the story is about (they have their own pictures "
            "and would be drawn twice). Describe the place as it is at the START of the film: nothing the story later makes appear, "
            "grow, break or transform (it would be there before its time); a container stays as it starts "
            "(an empty pot stays empty). Answer JSON only: {\"un_seul_lieu\": true or false, \"nom\": \"a short English name of the "
            "place, 2-5 words\", \"description\": \"the place in English, one paragraph, %d characters at most\"}."
            % (plans, COTES_DU_LIEU, DECOR_DESCRIPTION_MAX - 50))


def lire_decor_du_texte(reponse: str):
    """{nom, description}, ou None si le film change de lieu ; ValueError si illisible."""
    t = str(reponse or "")
    debut, fin = t.find("{"), t.rfind("}")
    try:
        d = json.loads(t[debut:fin + 1]) if debut >= 0 else None
    except ValueError:
        d = None
    if isinstance(d, dict) and d.get("un_seul_lieu") is False:
        return None
    if not isinstance(d, dict) or d.get("un_seul_lieu") is not True:
        raise ValueError("La description du décor n'a pas pu être lue : rien n'est créé.")
    return lire_decor_du_film(t)


def demandes_decor_du_texte(description: str) -> dict:
    """La demande de la vue d'ensemble vide ; la planche se fait ensuite d'elle
    (`demandes_decor_du_film(description, [vue])`)."""
    return {"prompt": f"{description}. {CADRE_DECOR}", "n": 1, "size": TAILLE_IMAGE_DEMANDEE}


OBJETS_CLEFS_PLANS_MIN = 2   # un objet d'un seul plan n'a pas de continuité à tenir


def consigne_objets(plans: list) -> str:
    """Pour le chat du Studio : les objets qui reviennent, tableau ou pas. Le biscuit de
    « Leila et un martien » n'est dans aucun tableau : on le tient, on le sort d'une
    poche, il n'est dit que dans les textes."""
    plans_txt = "\n".join(f"Shot {i + 1}: {p.get('image_paroles', '')}" for i, p in enumerate(plans))
    return ("Here are the shots of a short film. List the physical OBJECTS (never a person, an animal, a "
            "place, the sky, the ground or a body part) that are seen in at least two shots and must look "
            "exactly the same in each: props, vehicles, tools, food. For each, give \"nom\": the name "
            "copied EXACTLY as the shots write it (the longest form, with its article), \"plans\": the "
            "numbers of the shots where it is seen, \"bouge\": the numbers of the shots where it moves or "
            "is handled. Answer with the JSON array only, [] if none.\n\n" + plans_txt)


def lire_objets(texte: str, plans: list) -> list:
    """La réponse du chat, gardée seulement là où le nom se lit dans les plans qu'il cite."""
    m = re.search(r"\[.*\]", str(texte or ""), re.DOTALL)
    try:
        liste = json.loads(m.group(0)) if m else []
    except ValueError:
        return []
    sortie = []
    for o in liste if isinstance(liste, list) else []:
        nom = " ".join(str((o or {}).get("nom") or "").split()) if isinstance(o, dict) else ""
        if not nom:
            continue
        ecrit = {i for i, p in enumerate(plans) if _norme_replique(nom) in _norme_replique(p.get("image_paroles", ""))}
        nums = lambda k: {int(x) - 1 for x in (o.get(k) or []) if str(x).isdigit()} & ecrit   # noqa: E731
        if len(nums("plans")) >= OBJETS_CLEFS_PLANS_MIN:
            sortie.append({"nom": nom, "plans": nums("plans"), "bouge": nums("bouge")})
    return sortie


_ARTICLE = re.compile(r"^(?:the|a|an|le|la|les|un|une|des|l)\s+")


def cle_objet(nom: str) -> str:
    """Le nom d'un objet sans son article : 03/10, « Le jardin de verre », « pot of soil » et
    « the pot of soil » ont eu deux fiches (deux des neuf images de H3, et <Subject 4><Subject 3>
    dans le texte du plan 2)."""
    return _ARTICLE.sub("", _norme_replique(nom))


def objets_clefs(plans: list, exclus=(), place: int = 0, du_chat=()) -> list:
    """Les noms des objets à mettre en fiche, au plus `place` : ceux que le tableau
    d'au moins deux plans nomme, et ceux que le chat a lus dans les textes (`du_chat`,
    `lire_objets`), hors `exclus` (les fiches déjà là). D'abord ceux qui bougent dans
    le plus de plans (un objet qu'on prend, qui se pose, s'envole), puis les plus
    présents, puis le premier venu."""
    if place <= 0:
        return []
    deja = {cle_objet(str(n)) for n in exclus}
    vus = {}
    for o in du_chat:
        cle = cle_objet(o["nom"])
        if cle not in deja and o["plans"]:
            v = vus.setdefault(cle, {"nom": o["nom"], "plans": set(), "bouge": set(), "premier": min(o["plans"])})
            v["plans"] |= set(o["plans"])
            v["bouge"] |= set(o["bouge"])
            v["premier"] = min(v["premier"], min(o["plans"]))
            if len(o["nom"]) > len(v["nom"]):   # la forme longue, avec son article
                v["nom"] = o["nom"]
    for i, p in enumerate(plans or []):
        for e in (p.get("elements") or []) if isinstance(p, dict) else []:
            nom = " ".join(str((e or {}).get("nom") or "").split()) if isinstance(e, dict) else ""
            cle = cle_objet(nom)
            if not nom or cle in deja or (hors_champ(e.get("debut")) and hors_champ(e.get("fin"))):
                continue
            v = vus.setdefault(cle, {"nom": nom, "plans": set(), "bouge": set(), "premier": i})
            if len(nom) > len(v["nom"]):
                v["nom"] = nom
            v["plans"].add(i)
            if str(e.get("mouvement") or "").strip().lower().rstrip(".") not in _IMMOBILE:
                v["bouge"].add(i)
    gardes = [v for v in vus.values() if len(v["plans"]) >= OBJETS_CLEFS_PLANS_MIN]
    gardes.sort(key=lambda v: (-len(v["bouge"]), -len(v["plans"]), v["premier"]))
    return [v["nom"] for v in gardes[:place]]


def fiche_objet_clef(nom: str) -> dict:
    """La fiche d'objet clef de ce nom : celle d'un tournage d'avant si elle existe (même
    objet d'un film à l'autre, rien à refaire), sinon une neuve, encore sans image."""
    cle = cle_objet(nom)
    racine = DOSSIER_FICHES
    for dossier in sorted(racine.iterdir()) if racine.is_dir() else []:
        try:
            f = fiche_lire(dossier.name)
        except ValueError:
            continue
        if f.get("genre") == "objet" and f.get("vues") and cle_objet(f["nom"]) == cle:
            return f
    fiche = fiche_creer(nom[:FICHE_NOM_MAX], nom[:FICHE_DESCRIPTION_MAX], "objet")
    fiche["vues"] = True
    _fiche_ecrire(fiche)
    return fiche


def fiche_supprimer(fid) -> None:
    dossier = _dossier_fiche(fid)
    fiche_lire(fid)
    for f in dossier.iterdir():
        f.unlink()
    dossier.rmdir()


def _angle(angle: str) -> str:
    if angle not in ANGLES:
        raise ValueError("Angle inconnu.")
    return angle


def fiche_demande_image(fiche: dict, angle: str) -> dict:
    """Ce qu'on demande à l'image du Studio pour un angle : le texte, la taille,
    et le portrait de face comme image de départ pour les autres angles."""
    detail = ANGLES[_angle(angle)][1]
    # Un objet ou une pose n'a qu'une image, sa vue de face (29/09) : les autres
    # angles sont ceux d'une personne. Texte repris des deux fiches essayées le 29/09
    # (ballon uni, prise de tir) : une marque dessinée revenait dans le clip.
    genre = fiche.get("genre")
    if genre == "decor":   # 02/10 : le lieu seul, la référence des images de départ des coupes
        if angle != ANGLE_DEPART:
            raise ValueError("Un décor n'a qu'une image : sa vue d'ensemble.")
        return {"prompt": f"{fiche['description']}. {CADRE_DECOR}", "n": 1, "size": TAILLE_IMAGE_DEMANDEE}
    if genre in ("objet", "pose"):
        if angle != ANGLE_DEPART:
            raise ValueError("Un objet ou une pose n'a qu'une image : la vue de face.")
        if genre == "objet" and fiche.get("vues"):   # un objet clef (02/10) : ses vues sur une image
            return {"prompt": f"{CONSIGNE_OBJET_VUES} L'objet : {fiche['description']}.", "n": 1,
                    "size": TAILLE_IMAGE_FICHE}
        cadre = ("L'objet seul, entier, centré, sans marque, logo ni texte" if genre == "objet" else
                 "Gros plan sur les mains et les avant-bras seulement, cinq doigts bien formés à chaque "
                 "main, geste net, aucun visage")
        return {"prompt": f"{fiche['description']}. {cadre} ; fond gris clair uni, lumière douce, "
                          f"photographie réaliste, aucune autre personne.",
                "n": 1, "size": TAILLE_IMAGE_FICHE}
    fin = "fond neutre gris clair, lumière douce, photographie réaliste, une seule personne."
    if angle == ANGLE_DEPART:
        return {"prompt": f"{fiche['description']}. {detail}, {fin}", "n": 1, "size": TAILLE_IMAGE_FICHE}
    if ANGLE_DEPART not in fiche.get("images", {}):
        raise ValueError("Créez d'abord le portrait de face : les autres angles partent de lui.")
    return {"prompt": (f"La même personne que sur l'image jointe, mêmes visage, coiffure et tenue : "
                       f"{fiche['description']}. {detail}, {fin}"),
            "n": 1, "size": TAILLE_IMAGE_FICHE,
            "image_reference": fiche_image_data_url(fiche["id"], ANGLE_DEPART)}


def fiche_poser_image(fid, angle: str, image: str) -> dict:
    fiche = fiche_lire(fid)
    octets = base64.b64decode(_image(image, ANGLES[_angle(angle)][0]))
    ext = next(e for debut, e in _EXTENSIONS.items() if octets.startswith(debut))
    dossier = _dossier_fiche(fid)
    ancien = fiche["images"].get(angle)
    if ancien:
        (dossier / ancien).unlink(missing_ok=True)
    fiche["images"][angle] = angle + ext
    (dossier / (angle + ext)).write_bytes(octets)
    fiche.pop("etiquette_h3", None)   # écrite d'après les photos : à refaire
    _fiche_ecrire(fiche)
    return fiche


def fiche_retirer_image(fid, angle: str) -> dict:
    fiche = fiche_lire(fid)
    nom = fiche["images"].pop(_angle(angle), None)
    if nom:
        (_dossier_fiche(fid) / nom).unlink(missing_ok=True)
    fiche.pop("etiquette_h3", None)
    _fiche_ecrire(fiche)
    return fiche


# --- Le nom d'un personnage pour H3 hors « Références » (04/10) ---------------------------------
# Propriétaire : « conform to h3 syntax in studio, mandatory », puis, au choix posé : une courte
# description. Le guide de MiniMax (base, cas 2) ne nomme personne : « the young woman shown in
# <Picture 1> ». Une seule étiquette par personnage, jamais mêlée à son nom (03/10 : « the girl » et
# « Mila » ont fait deux fillettes) ; écrite d'après les photos de la fiche (les traits passent par
# les images, jamais par le texte), une fois, gardée dans la fiche jusqu'à ce qu'une photo change.
ETIQUETTE_MOTS_MAX = 8
CONSIGNE_ETIQUETTE = (
    "These pictures all show one and the same character. Write a short English label of at most six words "
    "that tells this character apart at a glance in a video, from what the pictures show (kind of being, "
    "age group, one or two striking visual traits), starting with \"the\": for example \"the girl with dark "
    "brown hair\" or \"the small spherical silver robot\". No name, no punctuation, nothing else: only the label.")


def etiquette_lire(texte: str) -> str:
    """L'étiquette rendue par le modèle, vérifiée ; ValueError si elle n'en est pas une."""
    t = " ".join(str(texte or "").strip().strip("\"'«»“”.").split()).rstrip(".")
    t = t[:1].lower() + t[1:]
    if not re.fullmatch(r"the [a-z][a-z' -]*", t) or len(t.split()) > ETIQUETTE_MOTS_MAX:
        raise ValueError("Étiquette illisible : « %s »." % str(texte)[:80])
    return t


def fiche_poser_etiquette(fid, etiquette: str) -> dict:
    fiche = fiche_lire(fid)
    fiche["etiquette_h3"] = etiquette_lire(etiquette)
    _fiche_ecrire(fiche)
    return fiche


def fiches_sans_etiquette(ids) -> list:
    """Les fiches (personnes et objets à photos) qui n'ont pas encore leur étiquette."""
    sortie = []
    for fid in ids or []:
        try:
            f = fiche_lire(fid)
        except ValueError:
            continue
        if f.get("genre") not in ("decor", "pose") and f.get("images") and not f.get("etiquette_h3"):
            sortie.append(fid)
    return sortie


_REPLIQUE_D = re.compile(r"(<d>.*?</d>)", re.S)
_PLAN_SUIVANT = re.compile(r"\[Shot (?!1\])\d+\]")


def noms_en_etiquettes(texte: str, fiches: list, ancrees=()) -> str:
    """Chaque nom de fiche devient son étiquette, hors des répliques (<d>…</d>, dites mot pour mot) ;
    la première fois, « … shown in <Picture 1> » pour les fiches de `ancrees` (sur l'image de départ).
    Une fiche sans étiquette garde son nom. Majuscule en début de phrase ou de plan."""
    vues = set()
    morceaux = _REPLIQUE_D.split(str(texte or ""))
    for f in sorted((f for f in fiches if f.get("etiquette_h3")), key=lambda f: -len(f["nom"])):
        motif = re.compile(r"(?<![\w<])" + re.escape(f["nom"]) + r"(?!\w)")
        for k in range(0, len(morceaux), 2):
            def remplacer(m, f=f):
                e = f["etiquette_h3"]
                if f["id"] in ancrees and f["id"] not in vues:
                    e += " shown in <Picture 1>"
                vues.add(f["id"])
                return e
            morceaux[k] = motif.sub(remplacer, morceaux[k])
    for k in range(0, len(morceaux), 2):
        morceaux[k] = re.sub(r"(^|[.!?]\s+|\]\s+|:\s+)the\b" if k == 0 else r"([.!?]\s+|\]\s+|:\s+)the\b",
                             lambda m: m.group(1) + "The", morceaux[k])
    return "".join(morceaux)


def fiche_image_data_url(fid, angle: str) -> str:
    nom = fiche_lire(fid)["images"].get(_angle(angle))
    if not nom:
        raise ValueError("Cette image n'existe pas.")
    octets = (_dossier_fiche(fid) / nom).read_bytes()
    return f"data:{_TYPES[Path(nom).suffix]};base64," + base64.b64encode(octets).decode()


# --- Le profil voix d'un personnage (29/09) ----------------------------------------
# Demande du propriétaire : « soit on donne un exemple de voix à cloner, soit on génère
# un clonage dans la langue du locuteur et on l'applique à tous les plans, c'est le
# profil voix du personnage ». Sans lui, H3 invente un timbre à chaque plan. Le son
# part en <Audio j> du mode « Références » (nœud de ComfyUI v0.37.0, `ref_audios`,
# 3 au plus), comme référence de timbre : le guide de MiniMax
# (docs/VIDEO_PROMPT_WRITING_GUIDE_ref_en.md) dit « <Audio N> is the voice-timbre
# reference for <Subject N> » et interdit d'en reprendre les mots.
VOIX_MIN_S, VOIX_MAX_S = 3.0, 15.0
VOIX_FICHIER = "voix.wav"
VOIX_MAX_OCTETS = 20_000_000
VOIX_PAR_PLAN = 3   # le nœud en prend trois
# Une phrase neutre par langue, lue par la voix du Studio quand on génère le profil.
PHRASE_VOIX = {
    "French": "Bonjour, je m'appelle comme sur ma fiche. Aujourd'hui il fait beau, et je vous raconte "
              "tranquillement ma journée, sans me presser.",
    "English": "Hello, my name is on my card. The weather is nice today, and I am calmly telling you "
               "about my day, without rushing.",
}


def fiche_poser_voix(fid, wav: bytes, duree_s: float, source: str, langue: str) -> dict:
    """Le profil voix, déjà mis au propre (montage.voix_de_reference), et sa langue :
    la règle 4 (30/09) refuse de tourner une réplique dont le locuteur n'a pas de voix
    dans la langue de cette réplique."""
    fiche = fiche_lire(fid)
    if fiche_est_objet(fiche):
        raise ValueError("Un objet ou une pose ne parle pas : la voix va sur la fiche d'une personne.")
    if source not in ("exemple", "generee"):
        raise ValueError("Source de voix inconnue.")
    if langue not in LANGUES_PAROLES:
        raise ValueError("Dites la langue de cette voix.")
    if duree_s < VOIX_MIN_S:
        raise ValueError(f"Voix trop courte : {VOIX_MIN_S:g} s de parole au moins "
                         f"({duree_s:g} s entendues après le silence du début).")
    (_dossier_fiche(fid) / VOIX_FICHIER).write_bytes(wav)
    fiche["voix"] = {"source": source, "duree_s": duree_s, "langue": langue,
                     "pose_le": time.strftime("%Y-%m-%d %H:%M:%S")}  # date-machine
    # Les voix des autres langues venaient de l'ancienne : elles ne lui ressemblent plus.
    _retirer_voix_langues(fiche)
    _fiche_ecrire(fiche)
    return fiche


# La même voix dans d'autres langues (30/09) : clonée par FireRedTTS3 (voix_langue.py)
# depuis la voix de la fiche. Leila parle anglais avec SON timbre ; l'Américain parle
# français avec le sien, accent compris. Une par langue, à côté de la voix d'origine.
def _fichier_voix_langue(langue: str) -> str:
    return "voix_%s.wav" % langue


def fiche_poser_voix_langue(fid, langue: str, wav: bytes, duree_s: float, infos: dict) -> dict:
    fiche = fiche_lire(fid)
    if not fiche.get("voix"):
        raise ValueError("La fiche n'a pas encore de voix : posez-la d'abord.")
    if langue not in LANGUES_PAROLES or langue == fiche["voix"].get("langue"):
        raise ValueError("Langue de voix inconnue.")
    if duree_s < VOIX_MIN_S:
        raise ValueError(f"Voix trop courte : {VOIX_MIN_S:g} s de parole au moins.")
    (_dossier_fiche(fid) / _fichier_voix_langue(langue)).write_bytes(wav)
    fiche.setdefault("voix_langues", {})[langue] = dict(
        infos, duree_s=duree_s, depuis=fiche["voix"].get("langue"),
        pose_le=time.strftime("%Y-%m-%d %H:%M:%S"))  # date-machine
    _fiche_ecrire(fiche)
    return fiche


def _retirer_voix_langues(fiche: dict, langue: str | None = None) -> None:
    for l in [langue] if langue else list(fiche.get("voix_langues") or {}):
        (_dossier_fiche(fiche["id"]) / _fichier_voix_langue(l)).unlink(missing_ok=True)
        (fiche.get("voix_langues") or {}).pop(l, None)
    if not fiche.get("voix_langues"):
        fiche.pop("voix_langues", None)


def fiche_retirer_voix_langue(fid, langue: str) -> dict:
    fiche = fiche_lire(fid)
    if langue not in (fiche.get("voix_langues") or {}):
        raise ValueError("Cette fiche n'a pas de voix dans cette langue.")
    _retirer_voix_langues(fiche, langue)
    _fiche_ecrire(fiche)
    return fiche


def fiche_retirer_voix(fid) -> dict:
    fiche = fiche_lire(fid)
    fiche.pop("voix", None)
    _retirer_voix_langues(fiche)
    (_dossier_fiche(fid) / VOIX_FICHIER).unlink(missing_ok=True)
    _fiche_ecrire(fiche)
    return fiche


def langues_de_voix(fiche: dict) -> list:
    """Les langues où la fiche a une voix : celle d'origine d'abord."""
    d = [fiche["voix"]["langue"]] if (fiche.get("voix") or {}).get("langue") else []
    return d + [l for l in (fiche.get("voix_langues") or {}) if l not in d]


def fiche_voix(fid, langue: str | None = None) -> bytes | None:
    """La voix d'origine ; avec `langue`, celle de cette langue (None s'il n'y en a pas)."""
    fiche = fiche_lire(fid)
    if not fiche.get("voix"):
        return None
    if langue and langue != fiche["voix"].get("langue"):
        if langue not in (fiche.get("voix_langues") or {}):
            return None
        chemin = _dossier_fiche(fid) / _fichier_voix_langue(langue)
    else:
        chemin = _dossier_fiche(fid) / VOIX_FICHIER
    return chemin.read_bytes() if chemin.is_file() else None


def voix_du_plan(dites: list, fiches: list) -> list:
    """Les voix qui partent avec un plan : [(rang, langue de la voix)], VOIX_PAR_PLAN au plus.
    `dites` : (rang, langue) de chaque réplique, dans l'ordre (attribuer_repliques, releve) ;
    `fiches` : dicts avec « voix » et « voix_langues ». Par personnage, dans l'ordre des
    fiches, la voix de chaque langue qu'il parle ; faute de celle-là, sa voix d'origine
    (une seule fois) — le timbre au moins, comme avant le 30/09."""
    choisies = []
    for k, fiche in enumerate(fiches):
        if not fiche.get("voix"):
            continue
        a = langues_de_voix(fiche) or [None]
        for _k, langue in [d for d in dites if d[0] == k]:
            voix = langue if langue in a else a[0]
            if (k, voix) not in choisies:
                choisies.append((k, voix))
    return choisies[:VOIX_PAR_PLAN]


# --- La planche de personnage : la même personne sous tous les angles (28/09) -----
# Demande du propriétaire : « ce qui permet de créer un personnage consistant ».
# Faite par l'image du Studio à partir de toutes les photos de la fiche ; jointe
# ensuite aux images que le Studio crée avec ce personnage. Elle ne part pas à H3 :
# six fois la même personne sur une image de référence risquerait de la dédoubler.
TAILLE_PLANCHE = TAILLE_IMAGE_DEMANDEE
CONSIGNE_PLANCHE = (
    "Planche de référence d'un personnage, style photo réaliste, fond blanc uni, lumière de studio douce et égale. "
    "La même personne que sur les photos jointes, avec exactement son visage, ses yeux, son nez, sa bouche, sa "
    "coiffure et sa couleur de cheveux ; la même tenue sur toutes les vues : celle de la description si elle en "
    "donne une, sinon celle de la photo en pied, sinon celle des photos. "
    "Rangée du haut, trois gros plans du visage, épaules et tenue visibles : de face, de trois-quarts, de profil "
    "strict. Rangée du bas, en pied, de la tête aux chaussures : de face, de profil, de dos. "
    "Expression neutre, bras le long du corps. Aucun texte, aucune légende.")


def fiche_demande_planche(fiche: dict) -> dict:
    urls = [fiche_image_data_url(fiche["id"], a) for a in ANGLES if a in fiche.get("images", {})]
    if not urls:
        raise ValueError("La fiche n'a encore aucune image : la planche part de ses photos.")
    return {"prompt": f"{CONSIGNE_PLANCHE} Description : {fiche['description']}", "n": 1,
            "size": TAILLE_PLANCHE, "image_reference": urls}


def fiche_poser_planche(fid, image: str) -> dict:
    fiche = fiche_lire(fid)
    octets = base64.b64decode(_image(image, "Planche de personnage"))
    ext = next(e for debut, e in _EXTENSIONS.items() if octets.startswith(debut))
    dossier = _dossier_fiche(fid)
    if fiche.get("planche"):
        (dossier / fiche["planche"]).unlink(missing_ok=True)
    fiche["planche"] = "planche" + ext
    (dossier / fiche["planche"]).write_bytes(octets)
    _fiche_ecrire(fiche)
    return fiche


def fiche_retirer_planche(fid) -> dict:
    fiche = fiche_lire(fid)
    nom = fiche.pop("planche", None)
    if nom:
        (_dossier_fiche(fid) / nom).unlink(missing_ok=True)
    _fiche_ecrire(fiche)
    return fiche


def fiche_planche_data_url(fid):
    """La planche en data URL ; None si la fiche n'en a pas."""
    nom = fiche_lire(fid).get("planche")
    if not nom:
        return None
    octets = (_dossier_fiche(fid) / nom).read_bytes()
    return f"data:{_TYPES[Path(nom).suffix]};base64," + base64.b64encode(octets).decode()


# --- Le visage : gros plan pour la fiche, comparaison avec l'image de départ -------
# Essai du 28/09 : sur des photos en pied, le visage est minuscule, et les images
# générées ne ressemblaient pas à la personne ; des gros plans du visage ont
# réglé l'essentiel. Le modèle qui voit du Studio situe le visage ; ffmpeg coupe.

def consigne_visage(qui: str = "", ou: str = "") -> str:
    """`qui` : la personne à trouver (nom et description de sa fiche), `ou` : sa place
    attendue. Sans eux, « le visage principal » : sur une image à deux personnes, le
    30/09, 8 comparaisons sur 9 ont recadré l'autre (« forte » et « faible » croisés)."""
    if qui:
        cible = ("Locate the face of ONE person only: %s%s. Several people may be in the image: pick the one "
                 "that matches this description and place, never another one. " % (
                     qui, (", expected " + ou) if ou else ""))
    else:
        cible = "Locate the face of the main person in this image. "
    return (cible + "Answer with JSON only: "
            '{"x0": ..., "y0": ..., "x1": ..., "y1": ...}, the box tight around the face (hairline to chin, '
            "ear to ear), as integers from 0 to 1000 relative to the image width (x) and height (y). "
            "If there is no face, answer {}.")


def lire_visage(reponse: str):
    """La boîte du visage (x0, y0, x1, y1), en fractions ; None si rien de lisible.
    Le modèle qui voit répond sur 0-1000 (sa convention, essai réel du 28/09 : la
    consigne demandait 0-1, il a rendu 0-1000) ; une réponse sur 0-1 est lue aussi."""
    t = str(reponse or "")
    debut, fin = t.find("{"), t.rfind("}")
    try:
        d = json.loads(t[debut:fin + 1]) if debut >= 0 else None
        x0, y0, x1, y1 = (float(d[k]) for k in ("x0", "y0", "x1", "y1"))
    except (ValueError, TypeError, KeyError):
        return None
    if max(x0, y0, x1, y1) > 1:
        x0, y0, x1, y1 = (v / 1000 for v in (x0, y0, x1, y1))
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1) or (x1 - x0) < 0.02 or (y1 - y0) < 0.02:
        return None
    return x0, y0, x1, y1


# --- Les mains (règle 16, 02/10) ---------------------------------------------------
# Propriétaire : « on fait quoi dans l'avenir pour les mains ? », puis « point 1 sur modal ».
# Banc du 02/10 (film 4, hors Studio) : Leila recadrée, chaque main demandée à part, sans le
# texte attendu : 12 réponses justes sur 12 quand la main se voit, et toutes inversées au
# miroir ; une main cachée, réponse au hasard (et « unsure » dit 2 fois sur 6 seulement).
# D'où : la main est décrite sans connaître le texte, puis comparée au texte sans image, et
# une main cachée ne se juge pas.
MAINS_MOTS = re.compile(r"\b(?:left|right|both)\s+hands?\b", re.I)


def attend_des_mains(ou: str) -> bool:
    """Le tableau dit-il quelle main tient quoi (« in her right hand », « both hands ») ?"""
    return bool(MAINS_MOTS.search(ou or ""))


def consigne_corps(qui: str, ou: str = "") -> str:
    return ("Locate ONE person only: %s%s. Several people may be in the image: pick the one that matches this "
            "description and place, never another one. Answer with JSON only: "
            '{"x0": ..., "y0": ..., "x1": ..., "y1": ...}, the box around the whole upper body of that person, '
            "both arms and hands included, and anything they hold, as integers from 0 to 1000 relative to the "
            "image width (x) and height (y). If the person is not in the image, answer {}."
            % (qui, (", expected " + ou) if ou else ""))


def zone_corps(boite: tuple) -> tuple:
    """Un peu d'air autour du corps : une main tendue dépasse souvent la boîte."""
    x0, y0, x1, y1 = boite
    w, h = x1 - x0, y1 - y0
    return (round(max(0.0, x0 - 0.15 * w), 4), round(max(0.0, y0 - 0.08 * h), 4),
            round(min(1.0, x1 + 0.15 * w), 4), round(min(1.0, y1 + 0.08 * h), 4))


CONSIGNE_MAINS = ("This is a close-up of one person. Look at each of THEIR OWN hands (their body's right and "
                  "left, as they would say it, NOT the side of the image). Answer JSON only: {\"main_droite\": "
                  "\"what their RIGHT hand holds or touches, in 1-6 words, or 'nothing', or 'hidden' if that hand "
                  "cannot be seen\", \"main_gauche\": \"the same for their LEFT hand\"}.")


def lire_mains(reponse: str) -> dict:
    """{main_droite, main_gauche} ; ValueError si illisible."""
    t = str(reponse or "")
    debut, fin = t.find("{"), t.rfind("}")
    try:
        d = json.loads(t[debut:fin + 1]) if debut >= 0 else None
    except ValueError:
        d = None
    if not isinstance(d, dict) or not all(isinstance(d.get(k), str) for k in ("main_droite", "main_gauche")):
        raise ValueError("Les mains n'ont pas pu être lues.")
    return {k: " ".join(d[k].split())[:80] for k in ("main_droite", "main_gauche")}


def consigne_mains_attendues(nom: str, attendu: str, vu: dict) -> str:
    return ("The script says where %s is at the start of a shot: \"%s\". On the image, seen on %s's own body: "
            "RIGHT hand: %s; LEFT hand: %s. Is there a CLEAR contradiction about which of %s's own hands holds "
            "or touches which object (the object in the other hand, or not held at all)? A hand that is "
            "'hidden', a hand the script does not mention, or different words for the same object are NOT a "
            "contradiction. Answer JSON only: {\"contradiction\": true or false, \"pourquoi\": \"in French, one "
            "short sentence, empty if none\"}."
            % (nom, attendu, nom, vu["main_droite"], vu["main_gauche"], nom))


def lire_contradiction(reponse: str) -> tuple:
    """(contradiction, pourquoi) ; ValueError si illisible."""
    t = str(reponse or "")
    debut, fin = t.find("{"), t.rfind("}")
    try:
        d = json.loads(t[debut:fin + 1]) if debut >= 0 else None
    except ValueError:
        d = None
    if not isinstance(d, dict) or not isinstance(d.get("contradiction"), bool):
        raise ValueError("La comparaison des mains n'a pas pu être lue.")
    return d["contradiction"], " ".join(str(d.get("pourquoi") or "").split())[:300]


# Sous cette largeur (pixels de l'image), un visage ne se compare pas à une fiche : la règle 7
# ne conclut pas. Mesuré le 02/10 (film 4) : 93-111 px, « faible » à tort ; 350 px, « forte ».
VISAGE_MIN_PX = 128
TROP_PETIT = "trop petit"


def zone_gros_plan(visage: tuple) -> tuple:
    """Du visage au gros plan : les cheveux au-dessus, le cou en dessous, un peu
    d'air sur les côtés (comme les recadrages faits à la main le 28/09)."""
    x0, y0, x1, y1 = visage
    w, h = x1 - x0, y1 - y0
    return (round(max(0.0, x0 - 0.45 * w), 4), round(max(0.0, y0 - 0.5 * h), 4),
            round(min(1.0, x1 + 0.45 * w), 4), round(min(1.0, y1 + 0.35 * h), 4))


def consigne_ressemblance(nombre_references: int) -> str:
    return ("The first %d image(s) are reference photos of a real person. The last image is a generated picture "
            "that should show the SAME person. Compare only the face: shape of the face, eyes (size, shape, "
            "openness, colour), nose, mouth, eyebrows, hair, skin. Answer with JSON only: "
            '{"ressemblance": "forte" | "moyenne" | "faible", "ecarts": "..."} where "ecarts" lists, in French, '
            "the visible differences (empty if none)." % nombre_references)


def lire_ressemblance(reponse: str) -> dict:
    t = str(reponse or "")
    debut, fin = t.find("{"), t.rfind("}")
    try:
        d = json.loads(t[debut:fin + 1]) if debut >= 0 else {}
    except ValueError:
        d = {}
    niveau = d.get("ressemblance") if isinstance(d, dict) else None
    if niveau not in ("forte", "moyenne", "faible"):
        return {"ressemblance": None, "ecarts": "L'avis sur la ressemblance n'a pas pu être lu."}
    return {"ressemblance": niveau, "ecarts": " ".join(str(d.get("ecarts") or "").split())}


def photos_avec_depart(ids: list):
    """Parti d'une image de départ, combien de photos des fiches l'accompagnent, et
    lesquelles : toutes si elles tiennent avec l'image (9 images au plus), sinon le
    portrait de face de chaque personne (les objets gardent les leurs). Rend
    (nombre, visages_seuls) ; nombre 0 ou trop grand : l'image part seule, sans fiche
    ni voix. Film parc2, 30/09 : trois fiches, 4 + 4 + 1 photos, la voix de Leila ne
    partait pas avec son plan « coupe »."""
    fiches = [fiche_lire(f) for f in ids]
    toutes = sum(_nombre_images_h3(f) for f in fiches)
    if 0 < toutes < MODES["references"]["images_max"]:
        return toutes, False
    faces = sum(len(f.get("images") or {}) if fiche_est_objet(f) or ANGLE_DEPART not in (f.get("images") or {})
                else 1 for f in fiches)
    return faces, True


def fiche_images(fid, visage_seul: bool = False) -> list:
    """Les images de la fiche, dans l'ordre des angles, en base64 nu. `visage_seul` :
    le portrait de face seulement, quand une autre tenue est jouée (les autres
    photos montrent l'ancienne) ; sans portrait de face, toutes."""
    fiche = fiche_lire(fid)
    angles = [a for a in ANGLES if a in fiche["images"]]
    if visage_seul and ANGLE_DEPART in angles:
        angles = [ANGLE_DEPART]
    return [fiche_image_data_url(fid, a).split(",", 1)[1] for a in angles]


def fiche_images_h3(fid, visage_seul: bool = False) -> list:
    """Les images d'une personne pour H3 : son portrait de face et sa planche, quand
    elle en a une ; sinon `fiche_images`. 01/10, « Leila et un martien » : de profil
    dans les six plans, et H3 ne recevait que ses quatre photos, dont aucun vrai
    profil et quatre tenues ; le visage dérivait. La planche, la même personne sous
    tous les angles, n'allait qu'aux images du Studio (« la multi vue aurait dû être
    envoyée », le propriétaire). Une autre tenue jouée garde l'ancien envoi : la
    planche montre l'ancienne."""
    fiche = fiche_lire(fid)
    planche = None if visage_seul else fiche_planche_data_url(fid)
    if not planche:
        return fiche_images(fid, visage_seul)
    face = [fiche_image_data_url(fid, ANGLE_DEPART).split(",", 1)[1]] if ANGLE_DEPART in fiche["images"] else []
    return face + [planche.split(",", 1)[1]]


def _nombre_images_h3(fiche: dict) -> int:
    if fiche_est_objet(fiche) or not fiche.get("planche"):
        return len(fiche.get("images") or {})
    return (ANGLE_DEPART in (fiche.get("images") or {})) + 1


# --- Les tenues d'un personnage : des variantes gardées sur sa fiche (29/09) ------
# Demande du propriétaire : « le profil du personnage dérive de la fiche de base,
# avec des attributs qui changent comme les vêtements, pour que la vidéo tienne au
# contexte ». Visage et coiffure restent ceux de la fiche ; chaque tenue a sa photo
# en pied, faite une fois, puis reprise telle quelle par tous les films qui la jouent.

def _cle_tenue(tenue: str) -> str:
    return _norme_replique(tenue)


def fiche_tenue_image(fid, tenue: str):
    """La photo (base64 nu) de cette tenue sur la fiche ; None si elle n'est pas encore faite."""
    variante = (fiche_lire(fid).get("tenues") or {}).get(_cle_tenue(tenue))
    if not variante:
        return None
    chemin = _dossier_fiche(fid) / variante["image"]
    return base64.b64encode(chemin.read_bytes()).decode() if chemin.is_file() else None


def fiche_poser_tenue(fid, tenue: str, image: str) -> dict:
    fiche = fiche_lire(fid)
    cle = _cle_tenue(tenue)
    if not cle:
        raise ValueError("Tenue vide.")
    octets = base64.b64decode(_image(image, "Photo de la tenue"))
    ext = next(e for debut, e in _EXTENSIONS.items() if octets.startswith(debut))
    nom = "tenue_" + hashlib.sha256(cle.encode()).hexdigest()[:10] + ext
    (_dossier_fiche(fid) / nom).write_bytes(octets)
    fiche.setdefault("tenues", {})[cle] = {"tenue": " ".join(tenue.split()), "image": nom}
    _fiche_ecrire(fiche)
    return fiche


# La tenue ÉCRITE, en plus de sa photo (29/09) : au plan du tir, Leila filmée de dos
# portait un sweat gris ; sa fiche dit « sweat jaune et veste violette », tenue que
# le plan suivant, de face, a respectée. De dos, H3 ne relie plus les photos au
# personnage. La tenue est lue sur la photo en pied (en anglais : c'est la langue de
# l'invite de H3, et l'image seule, sans la description, n'a pas de souci de filtre).
ANGLE_TENUE = "pied"


def consigne_tenue_photo() -> str:
    return ("Describe only the clothing the person in this photo wears: garments and colours, top to shoes, "
            "in English, in a few words (e.g. \"a yellow hoodie under an open purple jacket, black leggings\"). "
            "Answer with JSON only: {\"tenue\": \"...\"}.")


def lire_tenue_photo(reponse: str) -> str:
    t = str(reponse or "")
    debut, fin = t.find("{"), t.rfind("}")
    try:
        d = json.loads(t[debut:fin + 1]) if debut >= 0 else {}
    except ValueError:
        d = {}
    return " ".join(str(d.get("tenue") or "").split())[:200] if isinstance(d, dict) else ""


def fiche_photo_de_tenue(fid):
    """(nom du fichier, data URL) de la photo où lire la tenue de base ; None sans photo."""
    fiche = fiche_lire(fid)
    angle = ANGLE_TENUE if ANGLE_TENUE in fiche["images"] else next((a for a in ANGLES if a in fiche["images"]), None)
    return (fiche["images"][angle], fiche_image_data_url(fid, angle)) if angle else None


def fiche_tenue_de_base(fid):
    """La tenue de base lue sur la photo, si elle l'a été sur CETTE photo ; None sinon."""
    fiche, photo = fiche_lire(fid), fiche_photo_de_tenue(fid)
    lue = fiche.get("tenue_de_base") or {}
    return lue.get("tenue") if photo and lue.get("image") == photo[0] and lue.get("tenue") else None


def fiche_noter_tenue_de_base(fid, image: str, tenue: str) -> None:
    fiche = fiche_lire(fid)
    fiche["tenue_de_base"] = {"image": image, "tenue": tenue}
    _fiche_ecrire(fiche)


def tenues_par_plan(par_plan: dict, nombre: int) -> list:
    """{numéro de plan (1…) ou 0 pour tous : tenue} → la tenue de chaque plan. Un
    plan qui n'en nomme pas garde celle du plan d'avant (ou, au début, la
    première nommée) : un personnage ne se change pas hors champ."""
    tous = par_plan.get(0)
    liste = [par_plan.get(k + 1) or tous for k in range(nombre)]
    premiere = next((t for t in liste if t), None)
    courante, sortie = premiere, []
    for t in liste:
        courante = t or courante
        sortie.append(courante)
    return sortie


def sujets_des_fiches(nombres: list, tenues=(), ecrites=None, objets=(), voix=None,
                      presents=None, depart=None, parleurs=None, suite=False, au_depart=None,
                      planches=(), vues=(), legere=False, lieu=None, nb_plans=1, etiquettes=None,
                      son_lieu=None, son_lieu_suite=False) -> str:
    """Les personnages, désignés par leurs images seulement : `nombres` dit
    combien d'images a chaque fiche, dans l'ordre des <Subject N>. La
    description d'une fiche ne sert qu'à fabriquer ses images : mise dans
    l'invite, elle a été DITE par le personnage (essai du 28/09, « Femme de 35
    ans, cheveux bruns… »). `voix` : {rang de la fiche : numéro de son <Audio j>}.

    Rend `subject_definitions`, `summary` et `retention_analysis`, dans l'ordre du guide
    de MiniMax (VIDEO_PROMPT_WRITING_GUIDE_ref_en.md, 1 à 4 ; demande du propriétaire,
    30/09 : « ajoute summary et appears in »). `presents` : les rangs que le texte du
    plan nomme — eux seuls sont dits « (appears in [Shot 1]) », car toutes les fiches
    du scénario partent avec chaque plan (None : toutes). `depart` : le numéro de
    <Picture N> de l'image de départ, première image de [Shot 1]. `parleurs` : {rang :
    numéro x de son (Sx)} ; la définition de sa voix le reprend (ref-en.txt, 2.4 :
    « <Audio 1> is the voice-timbre reference for <Subject 1> (S1). »), sans en créer.
    `suite` : le plan continue <Video 1>, la fin du plan précédent (voie « raccord »).
    `au_depart` : les rangs que l'image de départ montre ; ils y sont nommés (« showing
    <Subject 1> »), sans quoi la personne de l'image n'est liée à aucune fiche.
    `lieu` : le numéro de <Picture N> de la vue vide du décor du scénario (03/10).
    `etiquettes` : {rang : étiquette lue sur ses photos} ; la fiche est définie par ce qu'elle est et ce
    qui la distingue (ref-en.txt, 2.1 : « the fluffy white Samoyed in <Picture 2>… with thick white
    fur… ») au lieu de « the person » : Pixel, un robot, était « the person in <Picture 3> » (05/10).
    `son_lieu` : le numéro de <Audio N> de la piste son du lieu (05/10) ; recopiée sur une coupe
    (« partially_copy »), simple référence sur une suite (guide de MiniMax : continuation)."""
    definitions, garde, premiere, voix_dites, garde_sons = [], [], 1, [], []
    presents = set(range(len(nombres))) if presents is None else set(presents)
    for k, nombre in enumerate(nombres):
        images = ", ".join(f"<Picture {premiere + i}>" for i in range(nombre))
        premiere += nombre
        ou = f"<Subject {k + 1}>" + (" (appears in [Shot 1])" if k in presents else "")
        if k in objets and (objets.get(k) if isinstance(objets, dict) else None) == "pose":
            definitions.append(f"<Subject {k + 1}> is the hand pose in {images}.")
            garde.append(f"{ou}: fully_preserved - a hand pose only: the hands and fingers take "
                         f"exactly the position of {images} when the text names it; it adds no person and no object.")
            continue
        # Forme du guide de MiniMax (VIDEO_PROMPT_WRITING_GUIDE_ref_en.md, 4.1) : une ligne par
        # étiquette, « <Subject N> (appears in [Shot 1]): fully_preserved - … ». Les images y
        # sont NOMMÉES (30/09, remarque du propriétaire) : « the reference pictures » ne disait
        # pas lesquelles, avec Leila en <Picture 1…4> et Tyler en <Picture 5…8>.
        if k in objets:
            definitions.append(f"<Subject {k + 1}> is the object in {images}"
                               # un objet clef (02/10) : ses vues sur une seule image
                               + (("; all angles." if legere else "; it shows this one same object from several "
                                   "angles.") if k in vues else "."))
            garde.append(f"{ou}: fully_preserved - same shape and colour; exactly one." if legere else
                         f"{ou}: fully_preserved - the shape, colour and size of the object in "
                         f"{images} are retained; there is exactly one of it in every frame where it appears.")
            continue
        etiquette = (etiquettes or {}).get(k)
        qui = etiquette or "the person"
        definitions.append(f"<Subject {k + 1}> is {qui} in {images}"
                           # Ce que chaque image apporte (guide de MiniMax, ref-en, 2.1) : la planche
                           # est sa dernière image (fiche_images_h3, 01/10).
                           + ((f"; <Picture {premiere - 1}> shows all angles." if legere else
                               f"; <Picture {premiere - 1}> shows this same {'character' if etiquette else 'person'} "
                               "from every angle: front, three-quarter, profile and back.") if k in planches else "."))
        j = (voix or {}).get(k)
        if isinstance(j, dict) and len(j) == 1:
            j = next(iter(j.values()))
        sx = f" (S{parleurs[k]})" if (parleurs or {}).get(k) else ""
        if isinstance(j, dict):   # une voix par langue parlée dans ce plan (30/09)
            for langue, n in j.items():
                definitions.append(f"<Audio {n}> is the voice-timbre reference for <Subject {k + 1}>{sx} "
                                   f"speaking {langue}.")
                garde_sons.append(f"<Audio {n}>: reference - its vocal timbre guides the spoken voice of "
                             f"<Subject {k + 1}> in every {langue} line; the words of <Audio {n}> are never said.")
                voix_dites.append(f"<Audio {n}> as the voice-timbre reference for <Subject {k + 1}> "
                                  f"speaking {langue}")
        elif j:   # le profil voix (29/09), dans la forme du guide de MiniMax
            definitions.append(f"<Audio {j}> is the voice-timbre reference for <Subject {k + 1}>{sx}.")
            voix_dites.append(f"<Audio {j}> as the voice-timbre reference for <Subject {k + 1}>")
            garde_sons.append(f"<Audio {j}>: reference - its vocal timbre guides the spoken voice of <Subject {k + 1}> "
                         f"in every line; the words of <Audio {j}> are never said.")
        # Une seule personne, dit ici et pas dans la description : le 28/09, une
        # phrase « In the foreground: only <Subject 1>… » plaçait Léa une première
        # fois, la description la replaçait à sa table, et H3 en a dessiné deux
        # (règle 1 du matin, retirée le soir ; remarque du propriétaire).
        ecrite = (ecrites or {}).get(k)
        if legere:   # 02/10 : une fois chaque chose ; la tenue écrite remplace « clothing retained »
            garde.append(f"{ou}: fully_preserved - one single person, same face and hair; "
                         + (f"wears {ecrite}." if ecrite else
                            f"clothing of <Picture {premiere - 1}>." if k in tenues else "same clothing."))
            continue
        # La tenue écrite, pour les plans où le visage ne se voit pas (de dos, 29/09).
        porte = (f" <Subject {k + 1}> wears {ecrite} in every frame, also when seen from behind, in profile "
                 "or from afar." if ecrite else "")
        if k in tenues:   # la dernière de ses images le montre dans la tenue du scénario (29/09)
            garde.append((f"{ou}: fully_preserved - the face or head, body shape and size of {etiquette} in "
                          f"{images} are retained, with the clothing of <Picture {premiere - 1}>, as one single "
                          "character." if etiquette else
                          f"{ou}: fully_preserved - the face and hair of the person in {images} "
                          f"are retained, with the clothing of <Picture {premiere - 1}>, as one single person.")
                         + porte)
            continue
        # Les traits à garder sont ceux de ce qu'il est (ref-en.txt, 4.1, « the Samoyed's thick white
        # fur… are retained ») : un robot n'a ni cheveux ni vêtements.
        garde.append((f"{ou}: fully_preserved - the whole look of {etiquette} in {images} is retained: face "
                      "or head, body shape and size, colours, clothing or surface, as one single character."
                      if etiquette else
                      f"{ou}: fully_preserved - the face, hair and clothing of the person in "
                      f"{images} are retained, as one single person.") + porte)
    if lieu:   # 03/10, film 4 : la fontaine changeait de jets et de statue d'un plan à l'autre
        definitions.append(f"<Picture {lieu}> is the setting of [Shot 1], shown empty of people.")
        garde.append(f"<Picture {lieu}>: fully_preserved - same place and fixed elements; no person from it."
                     if legere else
                     f"<Picture {lieu}> (setting): fully_preserved - the buildings, the ground and each fixed "
                     f"element keep the shape, size, number of parts and place they have in <Picture {lieu}>; "
                     "no person and no object is taken from it.")
    if depart:   # ref-en.txt, 2.2 et 4.1 : l'image elle-même est une ancre de plan
        # « <Picture 2> is the first frame of [Shot 1], showing a woman seated beside a café
        # window » (ref-en.txt, 2.2) ; « …, showing <Subject 1> holding… » (modèle Comfy-Org
        # multiframe). Sans ce lien, la Leila de l'image de départ n'était pas <Subject 1>,
        # et H3 en dessinait une seconde (01/10).
        vus_depart = [f"<Subject {k + 1}>" for k in sorted(au_depart or ())
                      if k < len(nombres) and (objets.get(k) if isinstance(objets, dict) else None) != "pose"]
        definitions.append(f"<Picture {depart}> is the first frame of [Shot 1]"
                           + (", showing " + _liste_anglaise(vus_depart) if vus_depart else "") + ".")
        garde.append(f"<Picture {depart}>: fully_preserved - the shot begins exactly on it." if legere else
                     f"<Picture {depart}> ([Shot 1] first frame): fully_preserved - the shot begins "
                     f"exactly on <Picture {depart}>: its framing, places and people.")
    if suite:   # guide de MiniMax : « video continuation », la source citée en <Video N>
        definitions.append("<Video 1> is the end of the previous shot.")
        garde.append(SUITE_GARDE_LEGERE if legere else SUITE_GARDE)
    if son_lieu:   # 05/10 : chaque clip réinventait son ambiance ; le fond du lieu part en référence
        definitions.append(f"<Audio {son_lieu}> is the ambience reference of the setting; it contains no speech.")
        garde_lieu = (f"<Audio {son_lieu}>: reference - its ambience guides the background sound of the target "
                      "video; no words." if suite or son_lieu_suite else
                      f"<Audio {son_lieu}>: partially_copy - its ambience layer is copied as the background of "
                      "the target video; no words.")
    # ref-en.txt, 3 : un préfixe de types entre crochets, puis les étiquettes déjà définies.
    types = (["video continuation"] if suite else []) + ["reference generation"] \
        + (["keyframe completion"] if depart else []) + (["audio reference"] if voix_dites or son_lieu else [])
    if legere:   # 02/10 : les voix et le raccord sont déjà dits plus haut ; une ligne pour tous les sons
        resume = f"[{' + '.join(types)}] " + (f"{nb_plans} shots joined by cuts." if nb_plans > 1 else "One single shot.")
        if garde_sons:
            garde_sons = ["Each voice <Audio> gives only a voice timbre; its words are never said."
                          if son_lieu else "Each <Audio> gives only a voice timbre; its words are never said."]
        if son_lieu:
            garde_sons.append(garde_lieu)
        return sections_references(definitions, resume, garde + garde_sons)
    vus =[f"<Subject {k + 1}>" for k in range(len(nombres)) if k in presents]
    # Un texte en plans (clip maître, 03/10) : « a single shot » le contredisait.
    resume = (f"[{' + '.join(types)}] The target video "
              + (f"has {nb_plans} shots joined by cuts" if nb_plans > 1 else "is a single shot")
              + (" with " + _liste_anglaise(vus) if vus else "")
              + (f", beginning from <Picture {depart}>" if depart else "")
              + (", continuing <Video 1> without a cut" if suite else "") + "."
              + (" It uses " + _liste_anglaise(voix_dites) + "." if voix_dites else ""))
    if son_lieu:
        garde_sons.append(garde_lieu)
    return sections_references(definitions, resume, garde + garde_sons)   # les sujets, puis les sons (exemple du guide)


def sections_references(definitions: list, resume: str, garde: list) -> str:
    """Les trois premières sections du mode Références, comme l'exemple du guide (ref-en.txt, 7) : le titre
    seul sur sa ligne, puis « Give each item its own line » (2) et « one line for each reference label »
    (4) ; une ligne vide entre deux sections. Tout tenait sur une ligne jusqu'au 05/10 (revue du guide)."""
    return ("subject_definitions:\n" + "\n".join(definitions) + "\n\nsummary:\n" + resume
            + "\n\nretention_analysis:\n" + "\n".join(garde))


# Le titre de la description, après les trois premières sections (ref-en.txt, 7).
TITRE_DESCRIPTION_REFERENCES = "\n\ndetailed_description:\n"


def _liste_anglaise(elements: list) -> str:
    """« a », « a and b », « a, b and c »."""
    return elements[0] if len(elements) == 1 else ", ".join(elements[:-1]) + " and " + elements[-1]


# --- La traduction en anglais, dans tous les modes ---------------------------------
# Essai du 28/09 (PLAN 18.9) : en mode « Références », le texte français hors
# guillemets est DIT par le personnage (la scène, l'ambiance), la réplique se
# perd. Décision du propriétaire, même jour : « oui traduis en anglais ». Tout ce
# qui n'est pas réplique part en anglais ; les répliques restent mot pour mot.
# D'abord réservé au mode « Références » ; le même jour, en « Première image »,
# la description française de l'image en tête (clip bfd5d22d) a fait dire à H3
# du français inventé, sans la réplique anglaise (entendu par le Whisper du
# Studio ; remarque du propriétaire : « le langage en anglais a disparu »).

CASES_TRADUITES = ("image_paroles", "ambiance", "musique", "description_premiere", "description_derniere")


def a_traduire(payload: dict) -> bool:
    return any(str(payload.get(k) or "").strip() for k in CASES_TRADUITES)


def repliques(texte: str) -> list:
    """Les répliques, dans l'ordre : entre guillemets, ou déjà balisées `<d>[langue] …</d>`
    (le 28/09, clip 841ec33e : balisées à la main, l'écoute n'en attendait aucune)."""
    return [langue_de_replique(next(g for g in m.groups() if g).strip(), "")[1]
            for m in _REPLIQUE_OU_BALISE.finditer(str(texte or ""))]


def consigne_traduction(payload: dict) -> str:
    cases = {k: " ".join(str(payload.get(k) or "").split()) for k in CASES_TRADUITES}
    return ("Translate the values of this JSON object into English, for a video-generation prompt. "
            "Text between quotation marks (« », “ ” or \" \") is spoken dialogue: copy it EXACTLY, "
            "untranslated, with its quotation marks. Empty values stay empty. Answer with the JSON "
            "object only, same keys, nothing else.\n" + json.dumps(cases, ensure_ascii=False))


def lire_traduction(reponse: str, payload: dict) -> dict:
    """Le JSON du modèle, contrôlé : mêmes cases, et les répliques intactes."""
    t = str(reponse or "").strip()
    if t.startswith("```"):
        t = t.strip("`").split("\n", 1)[-1] if "\n" in t else t.strip("`")
    debut, fin = t.find("{"), t.rfind("}")
    try:
        d = json.loads(t[debut:fin + 1]) if debut >= 0 else None
    except ValueError:
        d = None
    if not isinstance(d, dict) or not all(isinstance(d.get(k, ""), str) for k in CASES_TRADUITES):
        raise ValueError("La traduction en anglais n'a pas pu être lue.")
    for k in CASES_TRADUITES:
        if repliques(d.get(k, "")) != repliques(payload.get(k, "")):
            raise ValueError("La traduction en anglais a changé une réplique : rien n'est lancé.")
        if str(payload.get(k) or "").strip() and not d.get(k, "").strip():
            raise ValueError("La traduction en anglais a perdu une case : rien n'est lancé.")
        if reste_du_francais(d.get(k, "")):
            raise ValueError("La traduction en anglais a laissé du français : rien n'est lancé.")
    return dict(payload, **{k: d.get(k, "") for k in CASES_TRADUITES})


# Règle 0 (décision du propriétaire, 30/09 : « the hard code is to do all the post
# processing from the user initial prompt in english ») : l'histoire est traduite une
# fois, au début ; découpage, tableau, relectures et contrôles partent de l'anglais.
# Les deux films du 30/09 avaient un tableau aux noms français (« le cerf-volant
# jaune ») pour un texte anglais (« the yellow kite ») : rien ne pouvait les rapprocher.
def consigne_histoire_anglais(histoire: str) -> str:
    return ("Translate this story into English, for a film script. Text between quotation marks (« », “ ” or "
            "\" \") is spoken dialogue: copy it EXACTLY, untranslated, with its quotation marks, and keep any "
            "mark in square brackets in front of it ([language], [emotion] or [language, emotion]); when the "
            "story says in words how a line is said (happily, in tears, whispering…), keep that too. Keep "
            "every name of a person as it is written. Translate every other "
            "word, names of places and objects included. Answer with the translated story only, nothing else."
            "\n\n" + histoire)


def lire_histoire_anglais(reponse: str, histoire: str) -> str:
    """L'histoire en anglais, contrôlée : mêmes répliques, plus de français autour."""
    t = str(reponse or "").strip()
    if t.startswith("```"):
        t = t.strip("`").split("\n", 1)[-1] if "\n" in t else t.strip("`")
    t = t.strip()
    if not t:
        raise ValueError("La traduction de l'histoire en anglais est vide : rien n'est découpé.")
    if repliques(t) != repliques(histoire):
        raise ValueError("La traduction de l'histoire en anglais a changé une réplique : rien n'est découpé.")
    if reste_du_francais(t):
        raise ValueError("La traduction de l'histoire en anglais a laissé du français : rien n'est découpé.")
    return t


# Le 28/09 (clip 1180fae1), le chat du Studio a rendu une case « traduite » encore
# en français ; lire_traduction l'a acceptée. Des mots-outils français hors des
# répliques trahissent une case restée en français.
_MOTS_FRANCAIS = re.compile(r"(?<!\w)(le|la|les|des|du|une|et|sur|dans|avec|vers|sa|ses|au|aux|"
                            r"elle|il|ne|pas|qui|que)(?!\w)", re.I)


def reste_du_francais(texte: str) -> bool:
    hors_repliques = re.sub(r"<d>.*?</d>", " ", _PAROLES.sub(" ", str(texte or "")))
    return len(_MOTS_FRANCAIS.findall(hors_repliques)) >= 3


# --- Le scénario, monté après coup (PLAN 18.9) --------------------------------------
# Demande du propriétaire, 28/09 : « les clips générés devraient pouvoir se coller
# les uns aux autres suivant le scénario initial », puis « pas besoin de rejouer
# les clips de base, reconstruit le scénario a posteriori ». Rien n'est tourné ici :
# le Studio recolle, son compris, des clips H3 déjà réussis, dans l'ordre choisi.
# Le chat du Studio peut proposer cet ordre à partir du scénario ; gratuit.

SCENARIO_MAX = 2000
MONTAGE_CLIPS_MAX = 12


def verifier_ordre(ids) -> list:
    """Des numéros de clips, sans doublon, de 2 à MONTAGE_CLIPS_MAX."""
    if not isinstance(ids, list) or not all(isinstance(i, str) and re.fullmatch(r"[0-9a-f]{32}", i)
                                            for i in ids):
        raise ValueError("Liste de clips illisible.")
    if len(set(ids)) != len(ids):
        raise ValueError("Un même clip apparaît deux fois.")
    if not 2 <= len(ids) <= MONTAGE_CLIPS_MAX:
        raise ValueError(f"Choisissez de 2 à {MONTAGE_CLIPS_MAX} clips.")
    return ids


def consigne_ordre(scenario: str, clips: dict) -> str:
    """`clips` : numéro -> invite du clip. Le chat rend les numéros dans l'ordre du récit."""
    return ("Here is a film script, then video clips already made, each with the prompt that made it. "
            "Choose the clips that tell the script and put them in the order of the story. Leave out "
            "clips that do not belong. Answer with a JSON array of clip ids only.\n\nScript:\n"
            + scenario + "\n\nClips:\n" + json.dumps(clips, ensure_ascii=False))


def lire_ordre(reponse: str, permis) -> list:
    """L'ordre du chat, contrôlé : seulement des clips proposés, chacun une fois."""
    t = str(reponse or "")
    debut, fin = t.find("["), t.rfind("]")
    try:
        ids = json.loads(t[debut:fin + 1]) if debut >= 0 else None
    except ValueError:
        ids = None
    try:
        ids = verifier_ordre(ids)
    except ValueError as exc:
        raise ValueError("L'ordre proposé par le chat n'a pas pu être lu (" + str(exc) + ") : "
                         "réessayez, ou rangez les clips vous-même.") from exc
    if any(i not in permis for i in ids):
        raise ValueError("Le chat a proposé un clip qui n'est pas dans la liste : réessayez.")
    return ids


# --- Le scénario tourné plan par plan (PLAN 18.9) -----------------------------------
# Pour les scénarios neufs (« la partie tourner est à conserver pour les futurs
# scénarios », 28/09) : le chat du Studio découpe l'histoire en plans, le
# propriétaire les relit, puis le Studio les tourne l'un après l'autre et recolle
# chacun au film déjà tourné.

# 5 plans depuis le 30/09 (décision du propriétaire, film campus) : une histoire à six
# répliques perdait sa fin en 4 plans (découpage réel du jour). La limite mesurée des
# raccords reste : PLANS_MAX plans au plus d'affilée sans « coupe » (verifier_plans).
# 6 le soir même (« limite à 6 plans ») : une réplique par plan, coupée par le Studio
# (plans_a_scinder), et le film campus en a six.
# 8 le 02/10 (décision du propriétaire, film 4) : le plan 6 coupé en deux (6a, 6b) pour qu'une
# réplique remplisse chaque plan ; le 7e plan était refusé. PLANS_MAX reste la limite technique.
SCENARIO_PLANS_MAX = 8
ENCHAINEMENTS = {
    "coupe": "Nouveau plan (la fiche garde le personnage)",
    "suite": "Suite directe (repart de la dernière image du plan précédent)",
}
DOSSIER_SCENARIOS = budget_modal.CONFIG_DIR / "h3-scenarios"


# Règle 2 (28/09/2026) : les doublons de personnages sont venus de plans où
# l'un d'eux n'était qu'à moitié dans le cadre (gros plan à deux, plan par-dessus l'épaule).
CADRAGE = ("Framing: a close-up shows one character only; when two or more characters are in a shot, choose a "
           "medium or wide shot that shows each of them entirely, and never describe a character as only partly "
           "in frame or seen from behind. If a shot's framing breaks this rule, change the framing, never the "
           # Le 28/09, pour tenir la règle, une correction a retiré un personnage et son action.
           "characters in it or what they do. "
           # Le 28/09, un personnage placé deux fois (au premier plan, puis à sa table)
           # a été dessiné deux fois par H3 (remarque du propriétaire).
           "Place each character once: say where they are in a single place of the shot's text, and never "
           "repeat or restate that position later in the same shot. "
           # Le 28/09, un personnage qui s'approche d'une table s'y est assis de lui-même
           # avant la fin du plan : H3 invente la fin d'un mouvement qu'on ne décrit pas
           # (remarque du propriétaire : « il faut dire qu'il attend debout »).
           "When a character moves (walks, approaches, arrives, leaves), say how the movement ends: the "
           "posture they hold once arrived (standing, sitting…) and what they do until the end of the shot, "
           "as the story wants it at that moment. "
           # 01/10, plan 1 du film campus sur la 4090 : « walks in from off-frame at the left,
           # stops at the right » ; pour passer de gauche à droite, Tyler a traversé devant
           # Leila de dos, puis tourné sur lui-même. Le propriétaire : « simply say the start
           # and the end pose and leave H3 free to execute ». Règle 13 de regles.py.
           "A character who changes place: write only where they start and where they stop (place in the "
           "frame, posture, which way they face once arrived), never the route between: not the side they "
           "come in from, not passing in front of, behind or past someone, not crossing the frame. The video "
           "model chooses the path. "
           # 01/10 : la caméra a son menu ; une caméra écrite dans le texte le contredirait.
           "Never write a camera movement in the text (zoom, pan, push in, the camera follows or moves "
           "back): the camera is set apart, by the Studio. "
           # 01/10, même plan, caméra fixe, quatre graines : Tyler dit « Hey, are you lost? »
           # et Leila garde les yeux sur sa carte. Le texte ne disait rien d'elle après la
           # réplique ; H3 l'a laissée dans sa pose. Propriétaire : « on généralise comment ? »
           # Règle 14 de regles.py.
           "When a character speaks to another one who is in the shot, write right after the line what "
           "the listener does, as the story wants it (looks up at them, turns their head towards them, "
           "answers with a nod); only when the story says the listener ignores them, write that instead. "
           # Le 28/09, au plan 2, des clients au premier plan (journal, tasse) ont disparu
           # dans le clip : les modèles vidéo perdent ce qui est proche et à moitié caché
           # (défaut connu, sans correctif dans H3). La mise en scène l'évite.
           "Background people (passers-by, other customers) stay in the distance, never in the foreground, "
           "at the edge of the frame or partly hidden; when they move, they walk through and leave the frame. "
           "Keep few objects in the foreground. Never add or remove a character of the story for this. ")

# La physique écrite en entier (29/09, demande du propriétaire : « rebondir AU SOL,
# sinon il l'a fait en l'air ; H3 est faible en physique, sois générique »). H3 ne
# déduit rien : un contact non nommé n'a pas lieu, ou a lieu n'importe où.
PHYSIQUE = ("Physics is never implied, the video model is poor at it: for every object that moves, write what "
            "sets it moving (hand, foot, gravity), its path, EACH contact with a named surface (\"bounces once on "
            "the wooden floor\", never \"bounces\"; \"hits the backboard\"; \"lands on the table\"), and where it "
            "comes to rest and that it stays still there (\"then lies still on the floor at the right\"). Things "
            "fall DOWN to a named surface; nothing floats, rises, speeds up or changes direction on its own; a "
            "liquid pours into a named container; a door swings on its hinges. Give each moving object a count "
            "(\"the only ball\") so that no second one appears. "
            # 29/09, demande du propriétaire : « ne pas décrire un mouvement de deux façons » —
            # « face caméra », puis « se tourne vers la caméra » dans le même plan.
            "Describe each movement ONCE, in one way: the start of a shot gives the pose BEFORE the movement "
            "(\"seen in profile, facing right\"), never its result (\"facing the camera\" before \"turns to face "
            "the camera\"); never write the same gesture twice with other words. "
            # 29/09, demande du propriétaire (« améliorer les mains ») : les guides de
            # vidéo IA disent que le modèle devine un geste qu'on ne décrit pas, et que
            # c'est là que les mains se déforment. Le geste concret, un à la fois.
            "Hands: when hands act, say what each hand and its fingers do, concretely (\"both hands hold the "
            "ball, fingers spread on its sides\", \"her right hand grips the door handle\"), never an intention "
            "in place of the gesture; one simple, unhurried hand gesture at a time, hands not crossing each "
            "other. ")


# Le tableau des éléments clés (29/09, demande du propriétaire : « qualifier Leila,
# le ballon, le tir, avec place de départ, mouvement, place d'arrivée »). Le guide
# de MiniMax veut, par plan, « subject positions, actions, state changes ». Le tir
# rejoué de v3 venait d'un début non dit (« le ballon tombe sous le panier » : où,
# au début ?). Le tableau force le début, et la continuité d'un plan à l'autre se
# vérifie alors par le code, sans avis d'un modèle.
TABLEAU = ("For each shot, FIRST fill \"elements\", one entry per key element the shot shows (each character, "
           "every object that moves or that an action uses or aims at): {\"nom\": its name, written exactly as the shot's text names it, in English, \"debut\": where it is "
           "when the shot starts (place in the frame, which way it faces, standing or sitting, what it holds "
           "and how: which hand, which end of the object is up), "
           "\"mouvement\": what it does during the shot, step by step, each contact with a named surface, or "
           "\"none\" for an object only (a character always does something visible, even small, as the "
           "story wants it: adjusts the telescope, turns their head, smiles; a character who changes "
           "place: the action only, \"walks in and stops\", never the route), \"fin\": where it is when the shot ends}. Use the same name for an element in every shot. "
           "In a \"suite\" shot, each element's \"debut\" copies WORD FOR WORD its \"fin\" in the previous shot. "
           # 29/09, quai de gare rejoué : « tenant un parapluie fermé dans la main droite »
           # à la fin du plan 1, sans dire quel bout en haut ; le modèle l'a tenu crosse
           # en haut, et le plan suivant, qui part de cette image, l'a hérité. Le sens et
           # l'état d'un objet tenu s'écrivent donc au tableau, d'où la suite les copie.
           "An object held or carried: its \"debut\" and \"fin\", and the \"debut\" and \"fin\" of the "
           "character holding it, say which hand holds it, where, which end is up or in the hand, and its "
           "state (\"in her left hand, lens forward, switched off\", \"held upright by its neck, cap on, "
           "full\"). "
           # Mesuré le 29/09 (7 découpages) : un verre ou une carafe notés « none » au
           # départ surgissaient sur la table ou dans une main au plan 3 ou 4.
           "\"debut\" is never \"none\" or empty: an element not yet in the frame when the shot starts has "
           "\"debut\": \"off-frame\" (these exact English words, whatever the language) and its \"mouvement\" "
           "says only that it comes in (walks in, is handed over), never from which side; an object a character will take, "
           "fill or use is already in the table, at its place, in the first shot of that place; so is every place "
           # 29/09, quai de gare : le train, but de la marche finale, placé 1 fois sur 3.
           "or thing a character walks, runs, drives or looks toward (a train, a car, a door), even if it is "
           "reached only in the last shot. "
           # Même mesure : jusqu'à cinq actions dans un plan de 5 s (entrer, s'asseoir,
           # prendre, verser, reposer).
           "A shot lasts about 5 seconds: it holds ONE main action (one character, or two together in one "
           "shared gesture: a handshake, a hug), with at most three simple steps (lifts the glass, drinks, "
           "puts it down); a line of dialogue counts as a step. "
           # 29/09, quai de gare : « elle rit et répond, il ouvre le parapluie, elle prend
           # la valise » dans un seul plan, 2 fois sur 3.
           "Two characters each doing their own thing (she answers while he opens an umbrella) are TWO main "
           "actions, so two shots; in a shot, the other characters only listen, look or react with their face. "
           # 02/10, film 4, plan 6b : « Tyler part à vélo, Leila le salue et lui lance sa réplique »
           # refusé trois fois (« deux actions ») ; tourné forcé, réussi du premier coup, comme la
           # prise 2 du plan 6. Propriétaire : « on changera la règle si ça passe à nouveau ».
           "But a reaction TO the main action, as it happens, is part of it: the one who stays waves at, calls a line after or answers the one who leaves, arrives or acts (he rides away, she waves and calls goodbye: ONE main action). "
           # 29/09, demande du propriétaire : « une règle de cohérence entre le nombre
           # de plans et d'actions, exemple en 3 plans ». L'exemple n'est aucune des
           # histoires du banc (basket, cuisine, quai de gare), pour ne pas l'apprendre.
           "The NUMBER of shots follows the actions: first list the story's actions in order, then group them, "
           "one main action and its steps per shot; as many shots as groups, never more (no shot that only "
           "waits or repeats), never fewer than the maximum allows if actions are left over. When the actions "
           "still do not fit, keep those that carry the story (an arrival, a line, a result) and let a cut "
           "(\"coupe\") skip the minor steps (walking to a chair, filling a glass): the next shot starts after "
           "them, with the places they lead to. Example, in 3 shots: \"Marc waters the tomato plants, picks a "
           "ripe tomato, washes it at the tap, bites into it and calls to his daughter: « Viens goûter ! »\" "
           "gives shot 1: Marc waters the row of plants with a watering can; shot 2 (coupe, the washing is "
           "skipped): Marc picks a tomato and bites into it; shot 3 (suite): Marc turns to the house and calls "
           "« Viens goûter ! ». "
           "Then write \"image_paroles\" from this table: the start places, then each movement once, in order; "
           "never a start place that a movement of the shot only reaches. ")
HORS_CHAMP = ("off-frame", "off frame", "offframe", "off-screen", "off screen", "offscreen", "hors champ")
# Revue du 30/09 : la page ne reconnaissait que « off-frame » et « hors champ », le code
# toute la liste ; un « off-screen » partait donc dessiné sur l'image de départ, puis
# entrait dans le plan : deux fois à l'image. Une seule règle, ici, pour les deux.
_HORS_CHAMP_DEDANS = ("off frame", "offframe", "off screen", "offscreen", "hors champ", "out of frame",
                      "out of shot", "off camera", "not visible", "not yet visible", "unseen", "invisible")


def hors_champ(etat: str) -> bool:
    """L'état d'un élément le dit hors du cadre (« off-frame », « out of frame »…)."""
    t = f" {_norme_replique(str(etat or ''))} "
    return any(f" {_norme_replique(h)} " in t for h in HORS_CHAMP + _HORS_CHAMP_DEDANS)


PREFIXE_DEPART = "Photo réaliste, cadrage paysage 16:9, image nette, début de la scène : "
_PAROLES_ENTRE_GUILLEMETS = re.compile(r"«[^»]*»|\"[^\"]*\"")
_VERBE_DE_PAROLE = re.compile(r"\s*(?:,\s*)?(?:\bet\s+)?\b(?:dit|demande|crie|murmure|chuchote|répond)\s*:\s*",
                              re.IGNORECASE)


def sans_paroles(texte: str) -> str:
    """Les répliques ôtées d'une description d'image (règle de `sansParoles`, la page)."""
    t = _VERBE_DE_PAROLE.sub(" ", _PAROLES_ENTRE_GUILLEMETS.sub("", str(texte or "")))
    t = re.sub(r"\s+([,.])", r"\1", " ".join(t.split()))
    return t.rstrip(" ,;:").strip()


def texte_depart(plan: dict) -> str:
    """La description de l'image de départ d'un plan : son cadre, puis l'état « debut »
    de chaque élément dans le champ — la règle de `texteDepart` (la page), ici pour le
    Studio qui crée l'image seul. 02/10 : depuis le texte entier, Gemini a écrit la
    réplique « [English, enthusiasm] Delicious! » sur l'image.
    03/10, « Le jardin de verre », plan 2 : « close-up on the pot of soil: a transparent crystal
    sprout pierces the soil… into a glass shrub » tient en une phrase ; l'image de départ a
    dessiné l'arbuste déjà poussé, et l'effet du plan a disparu. Après les deux-points vient
    l'action : le cadre s'arrête avant, l'état du début vient du tableau."""
    presents = [e for e in (plan.get("elements") or []) if isinstance(e, dict) and e.get("nom")
                and e.get("debut") and not hors_champ(e.get("debut"))]
    texte = sans_paroles(plan.get("image_paroles") or "")
    if not presents:
        return PREFIXE_DEPART + texte
    return PREFIXE_DEPART + cadre_du_depart(texte, [e["nom"] for e in presents]) + ". " + " ".join(
        f"{e['nom']} : {e['debut']}." for e in presents)


def cadre_du_depart(texte: str, noms: list) -> str:
    """Le cadre du plan : sa première phrase, avant les deux-points (l'action vient après) ; puis,
    si le premier élément présent n'est nommé que plus loin, ce qui le précède (le lieu). Film 5
    relancé, 04/10 : « Wide shot, night. In the garden, Leila stands… » — la première phrase seule
    perdait le jardin, l'image de départ a dessiné une rue de ville, le maître a fondu de l'une à l'autre."""
    premiere = texte.split(".")[0]
    cadre = premiere.split(":")[0].strip()
    positions = [m.start() for n in noms if n
                 for m in [re.search(r"(?<!\w)" + re.escape(n) + r"(?!\w)", texte, re.IGNORECASE)] if m]
    if positions and min(positions) > len(premiere):
        lieu = texte[len(premiere) + 1:min(positions)].split(":")[0]
        lieu = re.sub(r"[\s,;.:]+(?:and|with|while|as)?\s*$", "", lieu.strip(), flags=re.IGNORECASE).strip()
        if lieu:
            cadre += ". " + lieu
    return cadre


# L'image de FIN d'un plan (03/10, propriétaire : « image de début + script = image de fin ») :
# l'image de début jointe, le texte du plan sans ses répliques, et l'état « fin » du tableau.
PREFIXE_FIN = "Photo réaliste, cadrage paysage 16:9, image nette, fin de la scène : "
# « Le robot perdu », film 5, 04/10 : le maître part de la seule image du plan 1, où Pixel n'est pas ;
# H3 l'a inventé d'après son nom (« robot blanc cubique » au lieu de la sphère de métal de sa fiche),
# et chaque plan déplié en partirait. L'image du maître est redessinée d'après les fiches.
# « garder EXACTEMENT la pose » laissait le cube (fautes restantes aux plans 3, 5, 6) ; « remplacé ENTIER »
# a rendu la sphère de la fiche, à sa place dans la capsule (essai sur l'image du plan 3, même jour).
# « Le robot perdu », 04/10, plan 6 : Pixel, petit robot rond sur sa fiche, était un grand humanoïde dans
# le maître ; « à la même taille » contredisait « proportions des photos », et trois dessins l'ont gardé
# humanoïde. La place et l'orientation restent ; la taille et la forme sont celles des photos.
CONSIGNE_RETOUCHE = ("L'image jointe %d est l'image à reprendre : garder son cadrage, sa caméra, son décor, sa "
                     "lumière, ses objets, et la place et l'orientation de chaque personnage. Un personnage qui ne "
                     "ressemble pas à ses photos est remplacé ENTIER par celui des photos — tête, corps, "
                     "proportions, matière, couleurs, visage, tenue — à la même place, tourné du même côté, à SA "
                     "taille et dans SA forme, celles des photos, même si l'ancien était plus grand ou d'une autre "
                     "forme : rien de l'ancien ne reste. Rien d'autre n'est ajouté ni retiré. ")
# Ce que la retouche reçoit comme description : qui reconnaître, jamais l'action du plan (qui se dessinerait).
TEXTE_RETOUCHE = ("Personnages à reconnaître dans l'image à reprendre : %s. C'est l'instant de cette image, ni "
                  "avant ni après : aucun objet, aucun geste, aucun regard nouveau. ")
# « Le robot perdu », 04/10, plan 6 : la lampe torche allumée dans l'image du maître, alors que le plan la
# veut éteinte au début (son tableau : « switched off ») ; deux clips l'ont gardée allumée, refusés par le
# juge. L'état de départ de chaque élément est l'instant même de l'image, pas l'action : la retouche le suit.
ETATS_RETOUCHE = "À cet instant, chaque élément est exactement dans cet état, même si l'image à reprendre le montre autrement : %s "
ETATS_RETOUCHE_MAX = 900


def etats_au_debut(plan: dict) -> str:
    """« nom : état de départ. » pour chaque élément du tableau du plan ; vide sans tableau."""
    morceaux = []
    for e in plan.get("elements") or ():
        if isinstance(e, dict) and e.get("nom") and e.get("debut") and not hors_champ(e.get("debut")):
            morceaux.append("%s : %s" % (" ".join(str(e["nom"]).split()),
                                         " ".join(str(e["debut"]).split()).rstrip(".") + "."))
    return " ".join(morceaux)[:ETATS_RETOUCHE_MAX]


# --- Le texte d'un plan déplié, développé (05/10) ----------------------------------------------
# Plan 3 du film 5 relu contre le guide de MiniMax (ref-en.txt, 5.2) : « detailed_description is
# normally 350-500 English words […] A single shot does not automatically justify a shorter
# description ». Le texte du plan, écrit pour ~1,9 s du maître (« Wide shot, starry night garden:
# Leila left, facing right, looks at open capsule right »), faisait 69 mots joués 15 s ; il disait
# Pixel « blue eyes dim » quand l'image de départ les montre allumés (écart 8 de l'audit du 04/10).
# Le chat le développe donc d'après l'image de départ retouchée, le tableau des éléments et la durée.
# Ni apparence (les traits passent par les images, 03/10 ; une description a été DITE le 28/09), ni
# caméra (phrase_camera la dit), ni son (champ des sons), ni réplique ajoutée.
# Essai H, plan 3 (05/10, juge ok) : « never he/she » a donné « <Subject 1> turns <Subject 1>'s head »,
# et le plan, presque sans action, a été rempli de « the capsule stays completely still » redits ; le
# guide écrit « She closes her lips » (ref-en.txt, 7) : le nom ouvre la phrase, le pronom la suit.
DEVELOPPE_MOTS = (350, 500)
DEVELOPPE_TOLERES = (250, 650)   # hors de là, le texte du plan part tel quel
CONSIGNE_DEVELOPPE = (
    "The attached image is the FIRST frame of a %.1f-second video shot. Rewrite the shot text below as the "
    "description of what happens in this shot, in %d to %d English words of complete sentences in the "
    "present tense, from this first frame to the end of the shot, in time order, so that the action fills "
    "the whole %.1f seconds at a natural pace. Start from what the image shows: where each character stands, "
    "faces and what state each object is in; where the shot text contradicts the image about the starting "
    "state, follow the image. Then tell, step by step, every action of the shot text, how each character "
    "and object moves (direction, speed, gestures, gaze, expression) and where it ends.\n"
    "Rules: name the characters exactly as written here (%s); start each sentence with a name, then use "
    "he, she, it, his, her or its inside that sentence instead of repeating the name (never \"Leila's\" "
    "for \"her\"); never describe their appearance, face, hair, clothes, colours or body (the pictures "
    "give it); add no person, animal or object that is neither in the image nor in the text; do not "
    "describe the camera, the framing changes or the sound; never repeat an idea already written, such "
    "as something staying still: when the action is short, tell its small steps once each (gaze, breath, "
    "gesture, light) at their moment; %s Output only the description, one paragraph, no title, no list."
    "\n\nShot text: %s%s")
DEVELOPPE_SANS_PAROLE = "nobody says anything: write no speech, no words in quotes."
DEVELOPPE_PAROLES = ("keep every line in quotes or <d>…</d> of the shot text exactly as written, said by the "
                     "same character at the same moment, and add no other speech.")


def consigne_developpe(plan: dict, noms: list, duree_s: float) -> str:
    texte = " ".join(str(plan.get("image_paroles") or "").split())
    lignes = []
    for e in plan.get("elements") or ():
        if isinstance(e, dict) and e.get("nom"):
            lignes.append("- %s : start %s ; movement %s ; end %s" % tuple(
                " ".join(str(e.get(c) or "—").split()) for c in ("nom", "debut", "mouvement", "fin")))
    tableau = ("\n\nElements of the shot (start, movement, end):\n" + "\n".join(lignes)) if lignes else ""
    return CONSIGNE_DEVELOPPE % (duree_s, DEVELOPPE_MOTS[0], DEVELOPPE_MOTS[1], duree_s,
                                 ", ".join(noms) if noms else "no named character",
                                 DEVELOPPE_PAROLES if _REPLIQUE_OU_BALISE.search(texte) else DEVELOPPE_SANS_PAROLE,
                                 texte, tableau)


def lire_developpe(reponse: str, original: str, noms: list) -> str:
    """Le texte développé, vérifié ; ValueError s'il ne tient pas (longueur, nom perdu, réplique
    changée ou ajoutée) : le plan part alors avec son texte d'origine."""
    t = " ".join(str(reponse or "").strip().strip("\"'").split())
    mots = len(t.split())
    if not DEVELOPPE_TOLERES[0] <= mots <= DEVELOPPE_TOLERES[1]:
        raise ValueError("Texte développé de %d mots, attendu %d à %d." % ((mots,) + DEVELOPPE_MOTS))
    for nom in noms:
        motif = r"(?<!\w)" + re.escape(nom) + r"(?!\w)"
        if re.search(motif, original) and not re.search(motif, t):
            raise ValueError("Le texte développé a perdu « %s »." % nom)
    dites = [m.group(0) for m in _REPLIQUE_OU_BALISE.finditer(original)]
    if any(d not in t for d in dites) or len(_REPLIQUE_OU_BALISE.findall(t)) > len(dites):
        raise ValueError("Le texte développé change ou ajoute une réplique.")
    return t


CONSIGNE_FIN = ("L'image jointe %d est la PREMIÈRE image de ce plan. Dessine sa DERNIÈRE image, une fois faite "
                "l'action décrite : même lieu, même caméra, même cadrage, même lumière ; mêmes personnes et mêmes "
                "objets aux mêmes places, sauf ce que l'action change (ce qui naît pendant le plan est là, ce qui "
                "part n'y est plus, chacun dans la pose et à la place de la fin). ")


def texte_fin(plan: dict) -> str:
    """La description de l'image de fin d'un plan : son texte sans les répliques, puis l'état « fin »
    de chaque élément resté dans le champ."""
    restes = [e for e in (plan.get("elements") or []) if isinstance(e, dict) and e.get("nom")
              and e.get("fin") and not hors_champ(e.get("fin"))]
    texte = sans_paroles(plan.get("image_paroles") or "").strip()
    if not restes:
        return PREFIXE_FIN + texte
    return PREFIXE_FIN + texte + " À la fin : " + " ".join(f"{e['nom']} : {e['fin']}." for e in restes)


def elements_a_la_fin(elements) -> list:
    """Le tableau vu depuis la fin du plan (le « debut » de chacun devient sa « fin ») : pour
    `fiches_au_depart`, qui retire alors ceux qui sont partis."""
    return [dict(e, debut=e.get("fin") or e.get("debut")) for e in elements or () if isinstance(e, dict)]


def fiches_au_depart(fiches: list, elements, texte: str = "") -> list:
    """Les fiches à joindre à l'image de départ : sans celles que le tableau du plan met
    hors champ au début. Film campus, 01/10 : Tyler, qui entre au plan 1, était joint et
    dessiné à côté de Leila (règle 6 : « doit être hors champ »). Ni celles que le plan ne
    nomme pas du tout, ni dans son tableau ni dans son texte : « Leila et un martien »,
    01/10, Zib n'arrive qu'au plan 2 et l'image du plan 1 le montrait déjà dans le jardin.
    Sans tableau, rien n'est retiré. Une fiche illisible reste : demande_image dira pourquoi."""
    tableau = [e for e in (elements or []) if isinstance(e, dict)]
    absents = {_norme_replique(str(e.get("nom") or "")) for e in tableau if hors_champ(e.get("debut"))}
    nommes = " ".join([_norme_replique(str(e.get("nom") or "")) for e in tableau]
                      + [_norme_replique(str(texte or ""))])
    gardees = []
    for fid in fiches:
        try:
            nom = fiche_lire(fid)["nom"]
        except ValueError:
            nom = None
        if nom is None:
            gardees.append(fid)
            continue
        n = _norme_replique(nom)
        if n not in absents and (not tableau or f" {n} " in f" {nommes} "):
            gardees.append(fid)
    return gardees


_SANS_DEPART = ("", "none", "aucun", "aucune", "rien", "n/a", "-", "null")
TABLEAU_MAX, TABLEAU_CHAMPS = 8, ("nom", "debut", "mouvement", "fin")
# 02/10, film 4, plan 5 : à 300, le cadrage en tête coupait « …with her right » avant « hand »,
# et la règle 16 ne voyait plus quelle main tient quoi.
TABLEAU_CHAMP_MAX = 600


def lire_tableau(elements) -> list:
    """Le tableau d'un plan, nettoyé ; illisible ou absent : [] (il n'est qu'une aide)."""
    propres = []
    for e in elements if isinstance(elements, list) else []:
        if isinstance(e, dict) and all(isinstance(e.get(k, ""), str) for k in TABLEAU_CHAMPS) \
                and " ".join(str(e.get("nom") or "").split()):
            propres.append({k: " ".join(str(e.get(k) or "").split())[:TABLEAU_CHAMP_MAX] for k in TABLEAU_CHAMPS})
    return propres[:TABLEAU_MAX]


def apparitions_du_tableau(plans: list) -> list:
    """Les éléments qui surgissent sans origine : un départ vide, ou, dans une
    « suite », un élément jamais vu avant qui n'entre pas depuis le hors-champ.
    Des problèmes de relecture, trouvés par le code.

    Remplace, le 29/09, la comparaison mot pour mot des fins et des départs : sur
    7 découpages, 59 raccords sur 60 étaient déjà justes, et ses 2 alertes étaient
    fausses (même état, mots dans un autre ordre). Le défaut réel de cette mesure
    était ailleurs : un verre, une carafe notés « none » au départ, qui surgissaient."""
    problemes, vus = [], set()
    for k, plan in enumerate(plans):
        for e in plan.get("elements") or []:
            nom, debut = _norme_replique(e["nom"]), _norme_replique(e["debut"])
            if debut in {_norme_replique(x) for x in _SANS_DEPART}:
                problemes.append({"plan": k + 1, "quoi": (
                    f"« {e['nom']} » n'a pas de place au début du plan : dites où il est, ou « off-frame » "
                    "et comment il entre ; un objet ne surgit pas.")[:300]})
            elif (k and plan.get("enchainement") == "suite" and nom not in vus
                  and not hors_champ(e["debut"])):
                problemes.append({"plan": k + 1, "quoi": (
                    f"« {e['nom']} » est là au début du plan sans avoir été vu avant : placez-le dès le premier "
                    "plan de ce lieu, ou faites-le entrer depuis le hors-champ.")[:300]})
            vus.add(nom)
    return problemes


def distribution(fiches) -> str:
    """Les noms des fiches du scénario, lus par le découpage. Propriétaire, 03/10 : « les attributs
    sont toujours avec des images, jamais en texte ». Avec la description de la fiche, le chat
    écrivait la tenue dans les plans, et le texte dérive (« Le jardin de verre » : pull crème
    au lieu du pull rayé) ; la photo de la fiche, jointe à chaque image, porte l'apparence."""
    # Le nom seul : « - Mila (personne) » a été recopié tel quel dans les plans (03/10).
    noms = [str(f["nom"]) for f in fiches or () if isinstance(f, dict) and f.get("genre") != "pose" and f.get("nom")]
    if not noms:
        return ""
    return ("The characters and objects of this film have reference pictures, joined to every image: they "
            "give how each one looks. Call them exactly: " + ", ".join(noms) + ".\n"
            "Never write their looks: no clothing, hair, face, age, size or colour of a character, nor the "
            "look of an object that has a picture.\n\n")


def consigne_decoupage(scenario: str, fiches=()) -> str:
    # Une action et une réplique courte par plan : l'essai du 27/09 (clip 2) a
    # montré qu'un plan chargé rend un son incompréhensible.
    return ("Split this short film script into at most %d shots of about 5 seconds each. "
            "Each shot shows ONE simple action and has at most ONE short line of dialogue. "
            # Le 29/09, un geste de deux secondes étalé sur trois plans : au plan
            # suivant, l'objet lancé avait disparu et le plan « regarde » a meublé
            # cinq secondes en inventant une marche vers la caméra.
            "A quick gesture and its immediate result (throwing and where the thrown thing lands, "
            "catching, sitting down…) stay together in ONE shot: never spread one gesture over several "
            "shots, and never write a shot that only waits for the result of the previous one. "
            # Même essai : un élément du lieu dont un plan tardif a besoin n'était pas
            # dans l'image de départ, et il est apparu d'un coup au dernier plan.
            "The first shot's text names every lasting element of the place that a later shot uses, "
            "so that it is already visible from the start. "
            # Même essai, remarque du propriétaire : « le positionnement est complètement
            # foldingue entre les plans, la balle part toute seule, [elle] est à 180° » —
            # face caméra, le personnage a tiré vers nous, puis s'est retourné vers une
            # cible surgie derrière lui.
            # Puis, demande du propriétaire : « il faut demander de clairement positionner
            # les éléments clefs du scénario ». Chaque plan part seul chez H3 : la
            # disposition doit être écrite dans CHAQUE plan, pas seulement au premier.
            "Before writing the shots, fix the STAGING of each place: the key elements of the story there "
            "(each character, every object or place an action uses or aims at) and where each one stands, "
            "seen from the camera: left, centre or right of the frame, foreground or background, and which "
            "way each character faces. Characters stand in the foreground or middle ground, never in the "
            "far background. Two key elements never share the same place in the frame. "
            # La règle « visages toujours visibles » a été retirée le 29/09 à la demande du
            # propriétaire : elle contredit une action qu'on doit suivre jusqu'à sa cible.
            "The camera stays on the same side of the scene in all its shots. "
            "Then every shot's text states the position of each key element it shows, with the same words "
            "as the staging, even when it did not change. "
            # 01/10, « Leila et un martien » : « at night under a starry sky » au plan 1
            # seulement ; le plan 2, lu seul par H3, est sorti en plein jour.
            "Every shot's text also says where and when it happens: the place and the time of day with "
            "its light (at night under a starry sky, in the morning sun…), with the same words in every "
            "shot of that place, even when it did not change. "
            # Remesure du 29/09 : un livre déjà sur la table avant d'y être posé, un
            # personnage « seul » alors que l'autre est arrivé.
            "These positions describe the START of the shot: a character or object appears in them only "
            "once it has arrived in the story, and a word that is no longer true (alone, empty, still in "
            "the hand…) is not repeated. "
            # 29/09 : « the basketball has just dropped through the net » en tête d'un
            # plan : H3 a rejoué le tir, avec un second ballon dans le filet.
            "A shot never tells again an action that ended before its start, not even as \"has just…\": "
            "the video model would play it a second time. It only says where things are now (the glass "
            "stands full on the table, the door is open). Each object is there once: no text lets a second one appear. "
            # 29/09, plan 3 retourné sans redite : le ballon encore en l'air sur l'image de
            # départ, sans suite écrite, H3 l'a relancé dans le filet.
            "An object still moving when a shot starts (falling, rolling, flying, swinging) gets its end "
            "written in that shot: where it goes and where it stops; then nothing repeats its path. "
            "The staging itself is not a separate part of the "
            "answer: it lives only in the shots' texts, as plain sentences. When an action aims at something, say where that "
            "thing is and that the character faces it. Describe a physical action step by step: what moves "
            "the object, where it goes, where it ends. "
            # 29/09, relecture des découpages : un personnage à gauche versait dans un
            # verre posé sur la table à droite, sans jamais s'en approcher.
            "A character who touches, takes, pours into or hands something is next to it: if it stands "
            "elsewhere in the frame, the text shows the character walking to it first, and gives the "
            "character's new place. "
            # Même essai : la caméra s'est approchée de plan en plan, jusqu'à
            # redessiner le visage du personnage.
            "Say the framing of each shot in its first sentence (close-up, medium shot, wide shot), and only "
            # 04/10, film 5, plan 2 : « Wide shot. … Medium shot. » dans un seul plan (règle 18).
            "there: one framing per shot, a new framing is a new shot; never "
            "write a camera movement (zoom, pan, push in, the camera follows): the camera is set apart, "
            "by the Studio. %s"
            "Write in the language of the script. Dialogue must be copied EXACTLY from the script, "
            "between « »; never invent dialogue. %s"
            "For each shot give \"elements\" (the table), "
            "\"image_paroles\" (what we see, "
            "then the line if any), \"ambiance\" (the sounds, a few words) and \"enchainement\": "
            # 01/10, propriétaire : « raccord par défaut sauf si le scénario veut un coupé ».
            # « Leila et un martien » : six « coupe » (une par mouvement de caméra), aucun raccord.
            "\"suite\" BY DEFAULT: the shot continues the previous one without a cut, and the Studio joins "
            "them smoothly, from the framing the previous shot ends on; a camera movement is not a reason "
            "for a cut. \"coupe\" only when the script wants a cut: another place, a jump in time, a new "
            # 02/10, propriétaire : la coupe sert aux changements de point de vue
            # significatifs ; sinon, le bout de vidéo d'avant (plans 3 → 4 recadrés).
            "scene, or a clearly different viewpoint (from a wide shot to a close-up, another angle from "
            "the same side: the camera never crosses to the side behind it, 180-degree rule). The first shot is "
            "\"coupe\"; never more than %d shots in a row without a \"coupe\" (put it where the story "
            "allows a cut best). Answer with the JSON array only.\n\n%s%s"
            % (SCENARIO_PLANS_MAX, CADRAGE + PHYSIQUE + TABLEAU, MARQUES, PLANS_MAX, distribution(fiches),
               scenario))


def borner_les_suites(plans):
    """01/10 : avec « suite » par défaut, le chat a enchaîné cinq « suite » et tout le
    découpage a été refusé (« 4 plans au plus d'affilée sans coupe »). Le Studio met
    lui-même la « coupe » là où la chaîne dépasse ; cette coupe partira de son image."""
    if not isinstance(plans, list) or not all(isinstance(p, dict) for p in plans):
        return plans
    derniere = 0
    for i, p in enumerate(plans):
        if p.get("enchainement") == "suite" and (i == 0 or i - derniere + 1 > PLANS_MAX):
            p["enchainement"] = "coupe"
        if p.get("enchainement") != "suite":
            derniere = i
    return plans


def formes_du_mot(mot: str) -> set:
    """Le mot au singulier et au pluriel."""
    formes = {mot, mot + "s", mot + "es"}
    if mot.endswith("ies"):
        formes.add(mot[:-3] + "y")
    if mot.endswith("y"):
        formes.add(mot[:-1] + "ies")
    if mot.endswith("es"):
        formes.add(mot[:-2])
    if mot.endswith("s"):
        formes.add(mot[:-1])
    return formes


# 03/10, « Le jardin de verre » : la pousse de cristal notée au début « emerging from a pot of
# soil », les papillons nés des éclats « at the centre » : présents au début pour le tableau,
# la règle 5 les voyait « déjà à l'image, et le plan les fait entrer », et l'image de départ
# les aurait dessinés avant l'effet. Ce qui naît pendant le plan part hors champ.
_NAIT_AU_DEBUT = re.compile(r"\b(?:emerging|sprouting|appearing|forming|materiali[sz]ing|being born|"
                            r"growing out|bursting out|hatching)\b", re.I)
_DEVIENT = re.compile(r"\b(?:transforms?|transforming|turns?|turning|changes?|changing|becomes?|becoming|"
                      r"morphs?|morphing|grows?|growing|branches? out|branching out)\s+(?:in)?to\b"
                      r"|\b(?:becomes?|becoming)\b", re.I)


def naissances(elements: list) -> list:
    """Le tableau, chaque élément qui naît pendant le plan mis hors champ au début : son début dit
    qu'il naît, ou le mouvement d'un autre le fait devenir (« transforms into a glass butterfly »)."""
    suites = []
    for e in elements:
        for m in _DEVIENT.finditer(str(e.get("mouvement") or "")):
            suites.append((e["nom"], " ".join(_mots(e["mouvement"][m.end():])[:6])))
    sortie = []
    for e in elements:
        debut = str(e.get("debut") or "")
        mots = [m for m in _mots(e["nom"]) if m not in ("the", "a", "an")]
        ne = bool(_NAIT_AU_DEBUT.search(debut)) or any(
            autre != e["nom"] and mots and all(formes_du_mot(m) & set(suite.split()) for m in mots)
            for autre, suite in suites)
        sortie.append(dict(e, debut="off-frame") if ne and not hors_champ(debut) else e)
    return sortie


def fixes_nommes(texte: str, elements: list) -> str:
    """Le texte, chaque élément immobile présent au début mais que le texte ne nomme pas ajouté
    avec sa place (03/10 : la fenêtre du tableau, absente du texte, règle 1)."""
    ajouts = []
    for e in elements:
        debut = str(e.get("debut") or "").strip()
        immobile = str(e.get("mouvement") or "").strip().lower() in ("", "none", "none.", "static", "still")
        mots = [m for m in _mots(e["nom"]) if m not in ("the", "a", "an")]
        nomme = mots and all(formes_du_mot(m) & set(_mots(texte)) for m in mots)
        if immobile and debut and not hors_champ(debut) and mots and not nomme:
            nom = e["nom"].strip()
            ajouts.append("%s%s : %s." % (nom[0].upper(), nom[1:], debut.rstrip(".")))
    if not ajouts:
        return texte
    # Après la première phrase (le cadre), jamais après une réplique.
    # Jamais en tête : la première phrase est le cadre (`texte_depart`).
    fin = texte.find(". ")
    if fin < 0 or fin > texte.find("«") >= 0:
        return texte.rstrip() + " " + " ".join(ajouts)
    return texte[:fin + 2] + " ".join(ajouts) + " " + texte[fin + 2:]


def verifier_plans(plans) -> list:
    """Les plans relus par le propriétaire : de 1 à SCENARIO_PLANS_MAX, le premier
    en « coupe » (il n'a pas de plan avant lui)."""
    if not isinstance(plans, list) or not plans:
        raise ValueError("Le scénario n'a aucun plan.")
    if len(plans) > SCENARIO_PLANS_MAX:
        raise ValueError(f"{SCENARIO_PLANS_MAX} plans au plus par scénario.")
    propres = []
    for i, p in enumerate(plans):
        if not isinstance(p, dict) or not all(isinstance(p.get(k, ""), str)
                                              for k in ("image_paroles", "ambiance", "enchainement")):
            raise ValueError(f"Plan {i + 1} illisible.")
        if not p.get("image_paroles", "").strip():
            raise ValueError(f"Plan {i + 1} : décrivez ce qu'on voit.")
        enchainement = p.get("enchainement") or "coupe"
        if enchainement not in ENCHAINEMENTS:
            raise ValueError(f"Plan {i + 1} : enchaînement inconnu.")
        propre = {"image_paroles": p["image_paroles"].strip(), "ambiance": p.get("ambiance", "").strip(),
                  "enchainement": "coupe" if i == 0 else enchainement}
        if lire_tableau(p.get("elements")):
            propre["elements"] = naissances(lire_tableau(p["elements"]))
            propre["image_paroles"] = fixes_nommes(propre["image_paroles"], propre["elements"])
        try:
            propre["camera"] = lire_camera(p.get("camera"))
            if lire_longueur_plan(p.get("longueur")):
                propre["longueur"] = lire_longueur_plan(p.get("longueur"))
        except ValueError as exc:
            raise ValueError(f"Plan {i + 1} : {exc}") from exc
        # Un plan « coupe » peut partir d'une image de départ validée (28/09).
        if p.get("image_depart") and propre["enchainement"] == "coupe":
            if not _ID_DEPART.fullmatch(str(p["image_depart"])):
                raise ValueError(f"Plan {i + 1} : image de départ inconnue.")
            description = " ".join(str(p.get("description_depart") or "").split())
            if len(description) > 2000:
                raise ValueError(f"Plan {i + 1} : description de l'image trop longue.")
            propre.update(image_depart=str(p["image_depart"]), description_depart=description)
        propres.append(propre)
        chaine = len(propres) - max(k for k, x in enumerate(propres) if x["enchainement"] == "coupe")
        if chaine > PLANS_MAX:
            raise ValueError(f"Plan {i + 1} : {PLANS_MAX} plans au plus d'affilée sans « coupe » "
                             "(au-delà, l'image se dégrade) : faites-en une coupe.")
    return propres


def lire_decoupage(reponse: str, scenario: str) -> list:
    """Le découpage du chat, contrôlé : aucune réplique qui ne soit dans le scénario."""
    t = str(reponse or "")
    debut, fin = t.find("["), t.rfind("]")
    try:
        plans = json.loads(t[debut:fin + 1]) if debut >= 0 else None
    except ValueError:
        plans = None
    try:
        plans = verifier_plans(borner_les_suites(plans))
    except ValueError as exc:
        raise ValueError("Le découpage du chat n'a pas pu être lu (" + str(exc) + ") : réessayez.") from exc
    # 29/09 : un plan commençait par « image_paroles: », le nom du champ recopié dans son texte.
    for p in plans:
        for k in ("image_paroles", "ambiance"):
            p[k] = re.sub(r"^\s*" + k + r"\s*:\s*", "", p[k])
            # 29/09 : des guillemets vides « » dans un scénario sans réplique, refusés comme inventés.
            p[k] = " ".join(re.sub(r"«\s*»|“\s*”", " ", p[k]).split())
    # Le 29/09, un découpage refusé sans dire quelle réplique : le chat avait pu
    # changer une virgule, une majuscule, ou couper une longue réplique en deux
    # plans (la consigne en veut une courte par plan). Ces deux cas passent ;
    # la réplique du scénario reprend alors sa ponctuation d'origine. Un mot
    # changé, ajouté ou perdu reste refusé, et le message le cite.
    originales = repliques(scenario)
    permises = [_norme_replique(r) for r in originales]
    for p in plans:
        for k in ("image_paroles", "ambiance"):
            p[k] = marques_du_chat(p[k], permises)
    morceaux: dict = {}
    for i, p in enumerate(plans):
        for r in repliques(p["image_paroles"] + " " + p["ambiance"]):
            n = _norme_replique(r)
            if n in permises:
                origine = originales[permises.index(n)]
                p["image_paroles"] = p["image_paroles"].replace(r, origine)
                continue
            j = next((k for k, ligne in enumerate(permises) if n and f" {n} " in f" {ligne} "), None)
            if j is None:
                raise ValueError(f"Le découpage a inventé ou changé une réplique (plan {i + 1} : « {r} » "
                                 "n'est pas dans le scénario) : réessayez.")
            morceaux.setdefault(j, []).append(n)
    for j, ms in morceaux.items():
        if " ".join(ms) != permises[j]:
            raise ValueError(f"Le découpage a coupé la réplique « {originales[j]} » sans la garder "
                             "entière : réessayez.")
    return plans


def _norme_replique(texte: str) -> str:
    """Une réplique sans ponctuation, majuscules ni espaces en trop : ce qui s'entend."""
    return " ".join(re.sub(r"[^\w]+", " ", texte.casefold()).split())


def _chemin_scenario(sid) -> Path:
    if not isinstance(sid, str) or not re.fullmatch(r"[0-9a-f]{32}", sid):
        raise ValueError("Scénario inconnu.")
    return DOSSIER_SCENARIOS / (sid + ".json")


def scenario_lire(sid) -> dict:
    chemin = _chemin_scenario(sid)
    if not chemin.is_file():
        raise ValueError("Scénario inconnu.")
    return json.loads(chemin.read_text(encoding="utf-8"))


def scenario_ecrire(sc: dict) -> dict:
    chemin = _chemin_scenario(sc["id"])
    chemin.parent.mkdir(parents=True, exist_ok=True)
    provisoire = chemin.with_suffix(".tmp")
    provisoire.write_text(json.dumps(sc, ensure_ascii=False), encoding="utf-8")
    provisoire.replace(chemin)
    return sc


def scenario_noter(sid: str, **champs) -> dict:
    sc = scenario_lire(sid)
    sc.update(champs)
    return scenario_ecrire(sc)


# --- Juger, corriger, rejouer un scénario tourné (28/09) ------------------------
# Demande du propriétaire : un bouton pour faire juger les plans, le scénario
# remis à jour d'après les retours (les changements en gras), un bouton pour
# rejouer. Essai du 28/09 : Gemini, par le routeur, a vu sur la planche du plan 2
# « Léa porte une veste grise au lieu de sa veste rouge » ; il n'a pas vu la
# silhouette de dos vers 6,5 s. Une aide, pas une garantie.

MODELE_JUGE = "free-ai-max"   # le modèle plus fort du routeur, gratuit, son propre quota

# 02/10, « Leila et un martien » : la fiche « adolescente de 15 ans » à côté d'une image
# réaliste, et Gemini refuse tout (content_filter: PROHIBITED_CONTENT, non réglable),
# deux modèles, à chaque essai ; sans le chiffre, le même contrôle répond. Compter ou
# reconnaître un personnage n'a pas besoin de son âge : il ne part pas aux juges d'image.
_AGE = re.compile(r"(?:\b(?:âgée?s?|aged?)\s+)?(?:\bde\s+)?\b\d{1,3}\s*(?:ans\b|-?\s*years?\s*-?\s*olds?\b)"
                  r"|\baged?\s+\d{1,3}\b", re.I)


def sans_age(texte: str) -> str:
    """Le texte sans âge chiffré (« de 15 ans », « 15-year-old », « aged 15 »)."""
    texte = _AGE.sub("", texte or "")
    return re.sub(r"\s+([,.;:)])", r"\1", re.sub(r"[ \t]{2,}", " ", texte)).strip()

# Le juge est trop zélé (29/09, remarque du propriétaire : « le LLM red team est trop
# pressé de trouver un problème ; s'il y a un problème majeur, le qualifier en détail,
# sinon dire que le clip est propre »). Banc de trois clips vérifiés à l'œil, 4 essais :
# juge principal, fausses alertes sur les deux propres 7/8 → 5/8 ; juge serré 3/8 → 3/8,
# le tir rejoué toujours vu 4/4, mieux décrit.
MAJEUR = ("Most clips are clean. Report a problem ONLY if it is a MAJOR one, that a viewer would notice at "
          "normal speed and that breaks the story or physics; then describe it in detail (what, where in the "
          "frame, which frames), once, at the first frame where it appears. A small doubt, a blur, a slight "
          "shift or something you are not sure of is not a problem: then say the clip is clean, verdict ok "
          "with an empty list. ")
# Les fausses alertes du même banc : un panoramique (tout glisse ensemble, lu « elle
# saute ») et un ballon caché par le corps, filmé de dos (lu « elle ne le tient pas »).
PAS_UN_DEFAUT = ("These are NOT problems: the camera panning, tilting or moving, so that characters, objects and "
                 "background all shift together; an object hidden behind a body, a hand or another object (a "
                 "character seen from behind hides what they hold), then seen again where it could have been "
                 "hidden. ")


def consigne_jugement(noms: list, texte: str = "", raccord: int = 0, depuis_s: float = 0.0) -> str:
    """`raccord` : le nombre de premières images de la planche qui sont la fin du
    plan d'avant. Le 29/09, jugé plan par plan, le juge n'a pas vu un personnage
    retourné de 180° ni un ballon disparu d'un plan à l'autre (remarque du propriétaire).
    `depuis_s` : l'heure, dans le clip, de la première image de cette planche (un clip
    plus long qu'une planche se juge en plusieurs, 03/10)."""
    refs = " ".join(f"Image {k + 1} shows {nom}, a reference picture." for k, nom in enumerate(noms))
    # 03/10, clip maître : coupes voulues ([Shot N] At …) ; une coupe n'est pas une apparition.
    plans = bool(re.search(r"\[Shot \d+\]", str(texte or "")))
    quoi = ("ONE video made of several shots joined by the planned cuts its text dates ([Shot N] At MM:SS); a "
            "change of framing at those times is NOT a fault, but the same people and places must remain "
            "across them" if plans else "ONE video shot")
    # « Le robot perdu », 04/10 : une coupe faite à 7,54 s pour « At 00:07.542 » jugée « changement de
    # plan non planifié » ; le juge lit des numéros d'image, pas des heures. On lui dit l'image.
    coupes = [int(m) * 60 + float(s) for m, s in re.findall(r"At (\d+):(\d+(?:\.\d+)?), the camera cuts",
                                                             str(texte or ""))]
    coupes = [t for t in coupes if t >= depuis_s]
    if coupes:
        quoi += (" (planned cuts here: " + ", ".join("%g s, about frame %d" % (round(t, 1), round((t - depuis_s) / 0.5) + 1)
                                                     for t in coupes)
                 + "; across a planned cut the framing, the camera angle and where each character stands may "
                 "all change: that is the cut, NOT a fault)")
    depuis = (" Frame 1 of this sheet is at %s s into the video." % ("%g" % round(depuis_s, 1))) if depuis_s else ""
    avant = (f" Frames 1 to {raccord} are the END OF THE PREVIOUS SHOT, the shot itself starts at frame "
             f"{raccord + 1}: also report any jump across that cut — a character suddenly elsewhere or "
             "facing another way, the camera jumping to the other side, an object held or present before "
             "the cut and gone after it." if raccord else "")
    # Le texte du plan : la vidéo doit faire ce qu'il dit, dans le même ordre (28/09).
    voulu = (" The shot is meant to show: «%s». Also say if the video does not show these actions, or not in "
             "this order." % " ".join(sans_age(texte).split()) + CAUSE) if texte.strip() else ""
    # Le modèle rend le NUMÉRO de l'image, le Studio en fait l'heure : le 28/09,
    # un départ mal annoncé dans la consigne a décalé sa réponse d'une seconde.
    return (refs + f" Image {len(noms) + 1} is a contact sheet of {quoi}: frames numbered from 1, "
            "one every 0.5 s, read left to right then top to bottom; black cells after the end are empty."
            + depuis + " "
            # Neutre, sans questions qui cherchent la faute : le 28/09, la consigne
            # d'avant faisait trouver un défaut même au plan repris tel quel.
            + ("Say whether the characters stay consistent with their reference pictures throughout the shot."
             if noms else "Say whether the characters stay consistent throughout the shot.")
            # Le 28/09, des clients du premier plan ont disparu dans le clip sans
            # sortir du cadre ; le juge ne regardait que les personnages des fiches.
            + " Also report any person or object that disappears or appears without leaving or entering "
            "the frame."
            # Règle 10 (« aucun personnage ni objet en double ») : le 03/10, une fillette dédoublée dans
            # le dernier plan du maître ; rien ne demandait au juge de compter.
            + " Report any person or object shown twice at the same time (a double or twin the text does not ask "
            "for)."
            # Le 29/09, un ballon est parti tout seul, au-dessus des mains, sans geste de lancer.
            + " Objects obey physics: report an object that moves, floats or flies away without something "
            "pushing it, or an action aimed at a target that is not where the action goes."
            # 29/09 (« améliorer les mains ») : le juge ne les regardait pas.
            + " Look at the hands: report a hand clearly deformed (extra, missing or merged fingers, a hand "
            "melting into an object) that a viewer would notice." + avant + voulu
            + " " + PAS_UN_DEFAUT + MAJEUR +
            "Answer in French, JSON only: {\"verdict\": \"ok\" or \"defaut\", "
            "\"defauts\": [{\"image\": frame number, \"quoi\": \"what is wrong\""
            + (", \"cause\": \"texte\" or \"video\"" if texte.strip() else "") + "}]}.")


# La cause d'un défaut (29/09, remarque du propriétaire : « tout défaut vient d'un
# mauvais script ») : le plus souvent oui, mais pas toujours. Le plan 3 v3 avait un
# texte juste, et H3 a rejoué le tir quand même. Réécrire un texte juste ne sert à
# rien : ce défaut-là se rejoue (autre graine) sans toucher au texte.
CAUSE = (" For each problem, give its cause: \"texte\" when the shot's text asks for it, allows it, or is vague "
         "about it (a movement without its surface or its end, an action told again, something not placed); "
         "\"video\" when the text is clear and right and the video does not follow it.")

# Le second regard, serré, sur le début du plan (29/09) : sur la planche à 0,5 s, le
# juge a dit « ok » au plan 3 v3 ; à 0,25 s puis zoomé à 1/8 s, l'agent a vu un
# second ballon traverser le filet entre 0,75 et 1 s. Les redites et les objets
# dédoublés naissent dans la première seconde, là où H3 raccorde l'image de départ.
DEBUT_SERRE_S, DEBUT_SERRE_PAS = 1.5, 0.125


# Banc du 29/09, trois débuts vérifiés à l'œil, 1/8 s (4 essais chacun) : l'ancienne
# consigne voyait le tir rejoué du plan 3 v3 1 fois sur 3 et criait au défaut 4 fois
# sur 6 sur les deux clips propres. Ses fausses alertes : un panoramique lent (tout
# glisse ensemble, lu « Leila saute ») et un ballon caché par le corps puis levé (lu
# « sorti de nulle part »). La nouvelle, qui part d'où le texte COMMENCE : 4 sur 4
# à 0,38 s, et 3 fausses alertes sur 8.
def consigne_debut(noms: list, texte: str = "") -> str:
    refs = " ".join(f"Image {k + 1} shows {nom}, a reference picture." for k, nom in enumerate(noms))
    voulu = (" The shot's text is: «%s»." % " ".join(texte.split()) + CAUSE) if texte.strip() else ""
    return (refs + f" Image {len(noms) + 1} is a contact sheet of the FIRST {DEBUT_SERRE_S:g} SECONDS of one video "
            f"shot, one frame every {DEBUT_SERRE_PAS:g} s, numbered from 1, read left to right then top to "
            "bottom. Frames this close change very little. "
            + ("First, read where the text says the shot STARTS: an action the text puts before the shot "
               "(something already thrown, fallen, opened, said) must not be performed again in these frames; "
               "if it is, that is a problem, at the frame where it starts again. " if texte.strip() else "")
            + "Count every object that moves (a ball, a glass, a door) in each frame. "
            "Report only what you clearly see: an object seen twice at once, an object that repeats a movement "
            "the text says is already over, an object that bounces or stops in mid-air instead of on a surface, "
            "an object that moves without anything moving it, a character that jumps to another place or pose "
            "between two neighbouring frames. " + PAS_UN_DEFAUT.rstrip() + voulu + " " + MAJEUR +
            "Answer in French, JSON only: {\"verdict\": \"ok\" or \"defaut\", \"defauts\": [{\"image\": frame "
            "number, \"quoi\": \"what is wrong\"" + (", \"cause\": \"texte\" or \"video\"" if texte.strip() else "")
            + "}]}.")


def lire_jugement(reponse: str, debut_s: float, nombre: int, pas: float = 0.5) -> dict:
    t = str(reponse or "")
    debut, fin = t.find("{"), t.rfind("}")
    try:
        d = json.loads(t[debut:fin + 1]) if debut >= 0 else None
    except ValueError:
        d = None
    if not isinstance(d, dict) or d.get("verdict") not in ("ok", "defaut"):
        raise ValueError("Le jugement du chat n'a pas pu être lu : réessayez.")
    defauts = []
    for x in d.get("defauts") or []:
        try:
            i = int(x.get("image"))
        except (AttributeError, TypeError, ValueError):
            continue
        quoi = " ".join(str(x.get("quoi") or "").split())[:300]
        if 1 <= i <= nombre and quoi:   # une image qui n'existe pas n'a rien montré
            defaut = {"t_s": round(debut_s + (i - 1) * pas, 2 if pas < 0.5 else 1), "quoi": quoi}
            if x.get("cause") in ("texte", "video"):
                defaut["cause"] = x["cause"]
            defauts.append(defaut)
    return {"verdict": d["verdict"], "defauts": defauts}


def _mots(texte: str) -> list:
    t = unicodedata.normalize("NFD", str(texte or "").lower())
    return re.findall(r"[a-z0-9]+", "".join(c for c in t if unicodedata.category(c) != "Mn"))


PAROLES_SEUIL = 0.7   # part des mots attendus qu'il faut entendre
# En dessous de PAROLES_SEUIL mais au-dessus de celui-ci : un mot déformé, pas une
# réplique perdue ; « à vérifier à l'oreille », pas un défaut (29/09, gare : « Tu es
# trempé » dit « trampé », entendu « trompé », 2 mots sur 3 ; le propriétaire l'a
# entendu dit). Choisi, pas mesuré : le corpus n'a aucune réplique vraiment perdue.
PAROLES_SEUIL_DEFAUT = 0.5
# Un segment que Whisper juge sans parole au-delà de ce seuil est écarté. Mesure du
# 29/09 sur 73 passages de 24 scénarios tournés (Groq whisper-large-v3) : les
# répliques vraies vont de 0,00 à 0,11, les mots inventés sur des pas, de la pluie
# ou un souffle (« Bye. », « Thank you. », « you ») de 0,43 à 0,88.
SANS_PAROLE_SEUIL = 0.3


def segments_parles(segments: list) -> tuple:
    """(texte gardé, textes écartés) : les segments que Whisper croit sans parole
    sont écartés — le « Bye. » de la gare (29/09) était un de ces mots inventés."""
    gardes, ecartes = [], []
    for s in segments or []:
        t = " ".join(str(s.get("text") or "").split())
        if not t:
            continue
        sans = s.get("no_speech_prob")
        (ecartes if isinstance(sans, (int, float)) and sans >= SANS_PAROLE_SEUIL else gardes).append(t)
    return " ".join(gardes), ecartes


def comparer_paroles(texte: str, entendu: str, sur: bool = True) -> dict:
    """Les répliques du texte (entre guillemets) comparées à ce que le Whisper du
    Studio a entendu. Le 28/09, un clip dont l'invite était juste (réplique
    balisée [English]) disait du français inventé : le juge, qui ne voit que les
    images, ne pouvait pas l'entendre. `ok` vaut None quand la réplique est
    entendue à moitié (`doute` : à l'oreille).

    Sans réplique écrite, `ok` vaut None si le clip se tait, False s'il parle
    (`inattendu`, 30/09 : « Bien. Jaffer, vous étiez… » dans un plan muet) ; `sur`
    faux (Whisper sans segments, mots inventés non écartés) en fait un doute."""
    attendues = repliques(texte)
    if not attendues:
        entendu = " ".join(str(entendu or "").split())
        parle = bool(_mots(entendu))
        return {"attendu": [], "entendu": entendu, "part": None,
                "ok": False if parle and sur else None, "doute": parle and not sur, "inattendu": parle}
    mots, entendus = _mots(" ".join(attendues)), set(_mots(entendu))
    part = (sum(m in entendus for m in mots) / len(mots)) if mots else None
    # Réplique par réplique : une réplique perdue en entier sur deux (4 mots sur 7)
    # reste un défaut, même quand la part globale tombe dans la zone de doute.
    parts = [sum(m in entendus for m in w) / len(w) for w in map(_mots, attendues) if w]
    manque = any(p < PAROLES_SEUIL_DEFAUT for p in parts)
    doute = not manque and any(p < PAROLES_SEUIL for p in parts)
    dits = tons_dits(entendu, attendues)
    return {"attendu": attendues, "entendu": " ".join(str(entendu or "").split()),
            "part": None if part is None else round(part, 2),
            "ok": False if dits else (None if part is None or doute else not manque), "doute": doute,
            **({"ton_dit": dits} if dits else {})}


def tons_dits(entendu: str, attendues=()) -> list:
    """Les tons de EMOTIONS que le clip PRONONCE. 01/10, « Leila et un martien », plan 6 :
    « shouts, joyfully: overjoyed, bursting with happiness, <d>… » ; H3 a dit « …overjoyed,
    bursting with happiness, reviens quand tu veux », et l'écoute disait « ok » (la
    réplique y était). Deux mots pleins du ton suffisent (Whisper a entendu « Brusting »),
    pourvu qu'ils ne soient pas dans la réplique elle-même."""
    entendus = set(_mots(entendu))
    dans_replique = set(_mots(" ".join(attendues)))
    dits = []
    for _nom, ton in EMOTIONS.values():
        pleins = [m for m in _mots(ton) if m not in _MOTS_VIDES_DU_TON and m not in dans_replique]
        if len(pleins) >= 2 and sum(m in entendus for m in pleins) >= 2:
            dits.append(ton)
    return dits


# 02/10, film 4, plan 2 : la réplique de Tyler entendue à 7,1 s, l'écoute disait « ok » ; de 0 à
# 4,3 s, Leila avait dit un anglais sans suite (« and all my postplasticity mark… »). Un passage
# parlé d'au moins PAROLES_EN_TROP_MOTS mots dont moins de PAROLES_EN_TROP_PART viennent des
# répliques est une parole non écrite. Choisi sur ce cas, pas mesuré sur un corpus.
PAROLES_EN_TROP_MOTS = 4
PAROLES_EN_TROP_PART = 0.3


def passages_en_trop(attendues, morceaux) -> list:
    """Les passages écoutés à part (`_ecouter`) qui ne disent aucune des répliques écrites."""
    ecrits = set(_mots(" ".join(attendues or [])))
    trop = []
    for m in morceaux or []:
        mots = _mots(m.get("entendu"))
        if len(mots) >= PAROLES_EN_TROP_MOTS and sum(x in ecrits for x in mots) / len(mots) < PAROLES_EN_TROP_PART:
            trop.append(m)
    return trop


# 05/10, jalon 0 bis, clip 7 (graine 207, ouverture épinglée) : écrit « Une dernière, juste une. », dit
# « Une dernière valeur SM, juste une. » (Whisper small ; medium : « fois l'RSM »). Tous les mots attendus
# y sont et le passage est surtout écrit : ni la part ni passages_en_trop ne le voyaient. Une suite d'au
# moins PAROLES_INSEREES_MOTS mots entendus qui ne s'alignent sur rien de la réplique est un ajout de H3 ;
# un mot seul mal entendu (« trompé » pour « trempé », 29/09) reste toléré. Choisi sur ce cas, PROVISOIRE.
PAROLES_INSEREES_MOTS = 2


def mots_inseres(attendues, entendus) -> list:
    """Les suites de mots entendus qui s'insèrent dans une réplique écrite (ajouts de H3), en texte."""
    import difflib
    ecrits, bords = [], {0}
    for replique in attendues or []:
        ecrits += _mots(replique)
        bords.add(len(ecrits))   # la fin d'une réplique est le début de la suivante
    ajouts = []
    for entendu in entendus or []:
        dits = _mots(entendu)
        if not ecrits or not dits:
            continue
        for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=ecrits, b=dits, autojunk=False).get_opcodes():
            # Un remplacement mot pour mot est une erreur d'oreille ; seul l'excédent est un ajout. Au bord d'une
            # réplique (« Excuse me, is this seat taken? » pour « Is this seat taken? »), entre deux répliques
            # comprises, c'est une tournure que le Studio laisse passer depuis le 28/09 ; seul ce qui coupe
            # une réplique en deux compte ici. Un nombre écrit en chiffres et dit en mots (« 1999 »,
            # « nineteen ninety-nine ») n'est pas un ajout (relecture du 05/10).
            if (op in ("insert", "replace") and i1 not in bords and i2 not in bords
                    and not any(re.search(r"\d", m) for m in ecrits[i1:i2])
                    and (j2 - j1) - (i2 - i1) >= PAROLES_INSEREES_MOTS):
                ajouts.append(" ".join(dits[j1:j2]))
    return ajouts


# Les défauts de defaut_de_paroles où le clip dit ce que personne n'a écrit (pas une réplique manquée).
PAROLES_EN_TROP = re.compile(r"^(?:Paroles non écrites|Aucune réplique écrite|Le clip prononce le ton)")


def defaut_de_paroles(paroles: dict, t_s: float):
    """Un défaut du jugement quand la réplique manque ; None sinon."""
    if paroles.get("ok") is not False:
        return None
    if paroles.get("en_trop"):
        m = paroles["en_trop"][0]
        return {"t_s": round(t_s + float(m.get("de_s") or 0), 1),
                "quoi": "Paroles non écrites : « %s » (%.1f-%.1f s du plan)." % (m["entendu"], m["de_s"], m["a_s"])}
    if paroles.get("inseres"):
        return {"t_s": round(t_s, 1), "quoi": "Mots ajoutés dans la réplique « %s » : « %s » ; le clip dit : « %s »."
                % (" / ".join(paroles.get("attendu") or []), " / ".join(paroles["inseres"]), paroles["entendu"])}
    if paroles.get("ton_dit"):
        return {"t_s": round(t_s, 1), "quoi": "Le clip prononce le ton écrit pour H3 (« %s ») ; il dit : « %s »."
                % (" / ".join(paroles["ton_dit"]), paroles["entendu"])}
    if not paroles.get("attendu"):
        return {"t_s": round(t_s, 1), "quoi": "Aucune réplique écrite ; le clip dit : « %s »." % paroles["entendu"]}
    return {"t_s": round(t_s, 1), "quoi": "Réplique attendue « %s » ; le clip dit : « %s »."
            % (" / ".join(paroles["attendu"]), paroles["entendu"] or "rien")}


# Jalon 0, 05/10 (PLAN 21.5) : le clip 4 de Leila (graine 104) s'éclaircit de 48,6 à 69 en 7 s, la maison
# noyée dans un halo, et le clip 5 qui en repart casse le décor ; la même entrée avec la graine 204 tient
# (47,2-49,1). Ni le juge ni l'écoute ne le voyaient. Écart à la première image, sur 16 clips du jalon :
# 1 à 11 % pour les bons, 21 et 42 % pour les deux ratés. Seuil PROVISOIRE (2 ratés), à revoir avec le
# propriétaire et les clips étiquetés (PLAN 21.2, point 4).
DERIVE_LUMIERE_MAX = 0.20
LUMIERE_PAR_SECONDE = 4
# Une lumière que le texte demande (une lampe qu'on allume, l'aube) n'est pas une dérive.
_LUMIERE_DEMANDEE = re.compile(r"\b(?:allum|éteint|eteint|aube|lever du soleil|coucher du soleil|éclair|"
                               r"turns? (?:on|off)|switch|lights? up|dawn|sunrise|sunset|lightning|flash)",
                               re.IGNORECASE)
# Les défauts de defaut_de_lumiere : une prise qui a dérapé, pas une faute de l'image de départ.
DERIVE_DE_LUMIERE = re.compile(r"^L'image s'(?:éclaircit|assombrit) de ")


# Les dates des coupes qu'un texte multiplan demande (« [Shot 2] At 00:03.000, … »).
_DATE_DE_COUPE = re.compile(r"\[Shot \d+\]\s*At (\d+):(\d+(?:\.\d+)?)")


def _plans_de_la_courbe(n: int, texte: str) -> list:
    """Les tranches [début, fin) de la courbe, une par plan demandé ; MAITRE_ECART_COUPE_S autour de
    chaque coupe n'appartient à aucun plan (la coupe peut tomber un peu à côté de sa date)."""
    coupes = sorted(int(m) * 60 + float(s) for m, s in _DATE_DE_COUPE.findall(texte or ""))
    bornes, debut = [], 0.0
    for c in coupes + [None]:
        fin = n / LUMIERE_PAR_SECONDE if c is None else c - MAITRE_ECART_COUPE_S
        i, j = int(round(debut * LUMIERE_PAR_SECONDE)), min(n, int(round(fin * LUMIERE_PAR_SECONDE)))
        if j - i >= 2:
            bornes.append((i, j))
        if c is not None:
            debut = c + MAITRE_ECART_COUPE_S
    return bornes


def defaut_de_lumiere(courbe: list, texte: str = "", t_s: float = 0.0):
    """Un défaut du jugement quand la luminosité moyenne du clip (`courbe`, LUMIERE_PAR_SECONDE mesures
    par seconde) s'écarte de plus de DERIVE_LUMIERE_MAX de la première image de son plan ; None sinon.
    Jalon 0 bis, essai A (05/10) : trois plans demandés dans un clip, 47 puis 71 puis 33 aux coupes ;
    chaque plan se compare à son propre début, jamais par-dessus une coupe demandée."""
    if len(courbe or []) < 2 or _LUMIERE_DEMANDEE.search(texte or ""):
        return None
    pire, debut, ecart = None, 0.0, 0.0
    for i, j in _plans_de_la_courbe(len(courbe), texte):
        if courbe[i] <= 0:
            continue
        k = max(range(i, j), key=lambda x: abs(courbe[x] - courbe[i]))
        e = (courbe[k] - courbe[i]) / courbe[i]
        if abs(e) > abs(ecart):
            pire, debut, ecart = k, courbe[i], e
    if pire is None or abs(ecart) <= DERIVE_LUMIERE_MAX:
        return None
    return {"t_s": round(t_s + pire / LUMIERE_PAR_SECONDE, 1), "cause": "video",
            "quoi": "L'image %s de %d %% en cours de plan (de %.0f à %.0f) : halo ou lumière qui bave, "
                    "la prise a dérapé." % ("s'éclaircit" if ecart > 0 else "s'assombrit", round(abs(ecart) * 100),
                                           debut, courbe[pire])}


def consigne_correction(plans: list, retours: str, histoire: str = "") -> str:
    # L'histoire vient du scénario initial : des plans déjà réécrits peuvent l'avoir
    # abîmée, et la correction ne voyait qu'eux (28/09/2026).
    reference = ("The story the shots must tell (what happens, in order; it must stay true, even where the shots "
                 "given have drifted from it): %s\n\n" % histoire) if histoire else ""
    return (reference + "Here are the shots of a short film (JSON) and the feedback after shooting them. Rewrite the shots "
            # 29/09 : la correction inventait des vêtements (t-shirt blanc sur une fiche en sweat) ;
            # une tenue ne vient que de l'histoire ou des plans, la même partout.
            "so that the feedback is fixed: be explicit about who is in the frame. Never write a character's "
            "clothing or looks (reference pictures give them), unless the story itself gives them. Keep the "
            "same number of shots in the same order, keep each \"enchainement\", and copy every line of "
            "dialogue between « » EXACTLY in its own shot; never add, move or remove dialogue. " + MARQUES
            + "Change only what "
            "the feedback requires; write in the language of the shots. "
            # Le 28/09, pour effacer un défaut d'image, la correction a fait asseoir un
            # personnage avant qu'on l'y invite : on change la façon de montrer, pas l'histoire.
            "Change how the scene is shown (framing, clothing, who else is in the frame), never what happens: "
            "keep every action of the characters, and their order, as in the story. Write each shot in the order "
            "things happen, lines of dialogue included: an action caused by a line comes after that line. "
            "If a problem cannot be "
            "fixed without changing what happens, leave that shot unchanged: it will be shot again. " + CADRAGE +
            PHYSIQUE + TABLEAU + "Keep \"elements\" true to the rewritten text. " +
            "Answer with the JSON array only.\n\n"
            "Shots: %s\n\nFeedback: %s" % (json.dumps(plans, ensure_ascii=False), retours))


# --- La tenue d'un personnage, quand le scénario change celle de sa fiche (29/09) ---
# Décision du propriétaire : « si on change les vêtements on le fait pour tous les
# plans et on rajoute une photo de référence pour la consistance ».

def consigne_tenues(plans: list, noms: list) -> str:
    """Les noms seuls, jamais la description de la fiche : le 29/09, l'âge d'une fiche
    (15 ans) à côté d'une question de vêtements a fait filtrer la demande par Gemini
    (« content_filter: PROHIBITED_CONTENT »), réponse vide. Toute tenue que les plans
    nomment reçoit sa photo, même si c'est celle de la fiche : sans danger. Plan par
    plan : un personnage peut changer de tenue au fil du film."""
    return ("Here are the shots of a short film, numbered from 1. For each character named below and each shot "
            "that names their clothing, say which clothing that shot gives them; skip the shots that name none. "
            # En anglais (29/09) : la tenue est aussi ÉCRITE dans l'invite de H3, où tout
            # ce qui n'est pas réplique doit être anglais (sinon le personnage le dit).
            "Answer with JSON only: {\"tenues\": [{\"nom\": \"...\", \"plan\": shot number, \"tenue\": "
            "\"...\"}]}, the clothing only, IN ENGLISH, in a few words, with the same words for the same "
            "clothing.\n\nCharacters: %s\n\nShots: %s"
            % (json.dumps(list(noms), ensure_ascii=False),
               json.dumps({k + 1: p["image_paroles"] for k, p in enumerate(plans)}, ensure_ascii=False)))


def lire_tenues(reponse: str, noms: list, nombre: int = 0) -> dict:
    """{nom: {plan: tenue}} pour les seuls personnages connus (plan 0 : tous les
    plans, quand le relevé n'en donne pas) ; illisible, rien ne change."""
    t = str(reponse or "")
    debut, fin = t.find("{"), t.rfind("}")
    try:
        d = json.loads(t[debut:fin + 1]) if debut >= 0 else {}
    except ValueError:
        d = {}
    tenues: dict = {}
    for x in (d.get("tenues") if isinstance(d, dict) else None) or []:
        if not (isinstance(x, dict) and x.get("nom") in noms and str(x.get("tenue") or "").strip()):
            continue
        try:
            plan = int(x.get("plan") or 0)
        except (TypeError, ValueError):
            continue
        if plan < 0 or (nombre and plan > nombre):
            continue
        tenues.setdefault(x["nom"], {})[plan] = " ".join(str(x["tenue"]).split())[:300]
    return tenues


def texte_photo_tenue(nom: str, tenue: str) -> str:
    return (f"Photo en pied de {nom}, debout, de face, sur un fond neutre et clair, vêtue de : {tenue}. "
            "Même visage et même coiffure que sur ses photos ; seule la tenue change.")


DEJA_FILMES = (
    # 02/10, film 4 : au rejeu du plan 2, le relecteur bloquait « le plan 1 s'achevait en
    # plan moyen » ; le plan 1 FILMÉ finit en gros plan, et c'est de cette image que la
    # suite repart. Il jugeait sur un texte que le film a démenti.
    "Shots marked \"deja_filme\": true are ALREADY FILMED and will not change; their text is only a summary, "
    "and the film may end in another framing (closer or wider) or another camera position. Never report a "
    "problem on them. The shot after one of them starts from its real last image: never judge that shot's "
    "starting framing, camera distance or camera position against the filmed shot's text; judge only who and "
    "what is there, and what they do. ")


def consigne_continuite(plans: list, histoire: str, deja_filmes=None, vues=(), departs=()) -> str:
    """Le texte des plans se tient-il ? Un état au début et à la fin de chaque
    plan (28/09/2026) : un plan part de l'état où le précédent s'arrête, et
    aucune action ne vient avant ce qui la cause. Rien n'est loué.
    `deja_filmes` : les numéros (1…) des plans repris d'un film (rejeu) ; `vues` :
    ceux dont la vraie dernière image est jointe, dans cet ordre ; `departs` : ceux dont
    l'image de départ est jointe, après les dernières images."""
    deja = set(deja_filmes or ())
    # Banc du 02/10 (texte du film 4, 4 relectures) : la marque seule laissait encore une
    # remarque sur le recul du plan 2, lue dans le « Medium shot » du texte du plan 1.
    jointes = ("The attached images, in order, are the REAL last images of shots %s, already filmed: they "
               "are the truth over those shots' text, and the next shot starts exactly from each of them. "
               % ", ".join(str(n) for n in vues)) if vues else ""
    # 03/10, « Le jardin de verre » : refus avant tournage, « l'arrosoir doit être visible dès le
    # début », alors qu'il l'était sur l'image de départ, que le relecteur ne voyait pas.
    # Propriétaire : « les attributs sont toujours avec des images, jamais en texte ».
    images_depart = ("The attached images %d to %d are the START images of shots %s, in this order, already made: "
                     "each shot is filmed from its image, which is the truth over that shot's text for what is "
                     "in the frame at its start (who and what is there, where, posture, what each hand holds, how "
                     "they look). Never report that something must be shown, placed or said at the start of such "
                     "a shot when its image shows it. "
                     % (len(vues) + 1, len(vues) + len(departs), ", ".join(str(n) for n in departs))) if departs else ""
    plans_json = [dict({k: p[k] for k in ("image_paroles", "enchainement")}, **({"deja_filme": True} if k in deja else {}))
                  for k, p in enumerate(plans, 1)]
    # Le 29/09, le relecteur du scénario complet (demande du propriétaire : « rajoute
    # un reviewer pour le scénario complet qui fera comme toi ») : les défauts que
    # l'agent a trouvés à la main en relisant les découpages s'y vérifient tous.
    return ("Here are the shots of a short film (JSON), in order, and the story they tell. Each shot is filmed "
            "ALONE by a video model that sees only that shot's text, so each text must be complete and true on "
            "its own. For each shot, write the state at its start and at its end: who and what is there, where "
            "in the frame (left, centre, right; foreground or background), which way each character faces, "
            "standing or sitting, what they wear, what they hold. "
            # 03/10, « Le jardin de verre » : « la tenue de Mila n'est décrite dans aucun plan »,
            # et la correction, sans la fiche, l'a habillée d'un pull crème.
            "Clothing that the text does not give is NEVER a fault: the characters' reference sheets give it. "
            "Then review the whole film like a careful script supervisor: "
            "(1) does each shot start in the state where the previous one ends (a cut may move on in time or "
            "place, but nothing may be undone without being shown), does every action come after what causes "
            "it, as in the story, and is every event of the story still shown in some shot (an arrival, a "
            "departure, a gesture), none missing and none invented? A minor step that a cut skips (walking to a "
            "chair, filling a glass) is not a missing event. "
            "(2) does every key element (character, object, place or target an action uses) keep the same "
            "place in the frame and the same words from shot to shot, unless a shot shows it moving; are two "
            "elements ever given the same place; does a shot contradict itself about where something is? "
            # Premier essai réel du relecteur (29/09) : un personnage à droite « tourné vers
            # la gauche » pendant qu'on lui parle depuis la droite n'a pas été vu.
            "Check every \"facing\": a character who talks to, looks at or acts toward someone or something "
            "must face the side of the frame where that one is (on their left: facing left). "
            "(3) does a shot show a character or object before it arrives in the story, or repeat a word that "
            "is no longer true (alone, empty, still in the hand)? Does a shot tell again, even as \"has "
            "just…\", an action that ended before it starts? The video model plays it again, and an object "
            "appears twice. Does an object still moving at the end of a shot get, in the next shot, where "
            "it goes and where it stops? "
            "(4) is a target of an action (where something is thrown, reached, given, or where a character walks, "
            "runs or looks: a train, a door, a car) placed and visible from "
            "the first shot of that place, with the character facing it when acting? "
            "(5) is a quick gesture spread over several shots, or a shot that only waits for the result of "
            "the previous one? is it said what moves an object and where it ends? does a character touch, "
            "take, pour into or hand something that stands elsewhere in the frame without walking to it? "
            "(6) does the camera stay on the same side and keep the framing written? "
            # 29/09 : « rebondit » sans surface, et H3 a fait rebondir le ballon en l'air.
            "(7) physics: for every moving object, are what moves it, each contact with a NAMED surface "
            "(bounces on the floor, not just bounces) and where it comes to rest all written? A shot that "
            "leaves one of them out is a problem: quote the vague words. Do the hands that act get their "
            "concrete gesture (what each hand and its fingers do), not an intention? "
            "(8) does the number of shots fit the actions: a shot with no action of its own (it only waits "
            "or repeats), or a shot holding more than about 5 seconds can show: more than one main action, or more than "
            "three steps? Count the characters who act in each shot: two characters each doing their own "
            "thing (one answers while the other opens an umbrella) are two main actions, a problem; a character "
            "who only listens, looks or reacts with the face does not count, and a reaction TO the main action, as it happens, is part of it: the one who stays waves at, calls a line after or answers the one who leaves, arrives or acts (he rides away, she waves and calls goodbye: ONE main action). Name the minor steps to leave out, skipped by the cut before the next shot: the "
            "number of shots never changes, never ask to split a shot. "
            "(9) is a movement described twice or in two ways in the same shot, or does a shot give, at its "
            "start, the pose that one of its own movements only reaches (\"facing the camera\", then \"turns "
            "to face the camera\")? Quote the words of the start pose. "
            # Même essai : trois alertes sur trois demandaient d'écrire ce qui était déjà écrit.
            "Report only real problems, each once, in one short sentence that says what to change. Before "
            "reporting that something is missing, read the shot again: if its text already says it, it is "
            "not a problem. For a wrong or contradictory text, \"citation\" copies EXACTLY the wrong words "
            "from the shot; for something missing, \"citation\" is empty. "
            # 29/09, remarque du propriétaire : « le seuil de déclenchement est trop bas,
            # pour la gare le seul défaut est le parapluie ». Relu sur 18 découpages : le
            # geste du parapluie sort « bloquant » 5 fois sur 5, les regards et les mains
            # « detail » ; seuls les bloquants font corriger le texte.
            "For each problem, give \"gravite\": \"bloquant\" or \"detail\". \"bloquant\" = the video model, "
            "reading this shot alone, will visibly get it wrong on screen: an object that is handled, opened "
            "or moved without the concrete gesture or its path written; a character or object that appears, "
            "vanishes, jumps to another place or changes between shots; an event of the story that no shot "
            "shows; a shot whose text contradicts itself; two characters each doing their own main action in "
            "one shot; two characters at the same place of the frame (same depth and same side) at the same "
            "moment; an action already completed in an earlier shot that happens again (something falls, "
            "enters or is picked up a second time) without the story asking for it; a character or object "
            "that starts a shot in a state other than the one it ended the previous shot in, with nothing "
            "shown to change it; a shot whose text does not say the time of day and its light (night, "
            "day, sunset…) or says another one than the previous shot of the same place, the story "
            "not having moved on. \"detail\" = a precision the video model usually gets right on its own or that barely "
            "shows: which way someone faces, looks or turns the head (always a detail), which hand, the exact "
            "side or depth in the frame, naming a target earlier, wording. When unsure, \"detail\". "
            "Answer in French, JSON only: {\"etats\": [{\"plan\": number, "
            "\"debut\": \"...\", \"fin\": \"...\"}], \"problemes\": [{\"plan\": number, \"citation\": \"...\", "
            "\"quoi\": \"...\", \"gravite\": \"bloquant|detail\"}]}; "
            "an empty \"problemes\" list if the shots hold together.\n\n%sStory: %s\n\nShots: %s"
            % (((DEJA_FILMES + jointes) if deja else "") + images_depart, histoire,
               json.dumps(plans_json, ensure_ascii=False)))


# 02/10, film 4, demande du propriétaire : « faire relire la vidéo précédente pour améliorer si
# besoin le prompt du clip suivant ». Le même jour, quatre corrections à la main du début d'une
# suite : le cadrage (gros plan, pas plan moyen), Tyler déjà arrêté, à cheval, deux mains au
# guidon. La dernière seconde du plan filmé fait foi ; seul le départ du texte suivant change.
# 02/10, film 4, plan 5 (une coupe) : écrit « l'appareil contre l'œil », alors qu'à la fin filmée du
# plan 4 Tyler l'avait déjà baissé devant sa poitrine. Le relecteur l'a vu, mais rien ne réécrivait
# une coupe : elle montre le même instant sous un autre cadrage, poses et mains comprises.
COUPE_DEPART = ("The text below is the NEXT shot (shot %d): it is a CUT, the same instant seen with a new framing. "
                "Keep its framing exactly as written (shot size, angle, what the frame shows); rewrite only the "
                "STARTING state of the characters and objects so that it matches the final frame: their pose "
                "(standing, sitting, astride…), which way they face, what each hand holds and how, and the "
                "left/right order of characters across the frame. ")
SUITE_DEPART = ("The text below is the NEXT shot (shot %d): a video model continues exactly from that final frame. "
                "Rewrite the text so that its STARTING state matches the final frame: where each character and "
                "object is, their pose (standing, sitting, astride…), which way they face, what each hand holds, "
                "the framing. ")


def consigne_depart_reel(numero: int, texte: str, coupe: bool = False) -> str:
    return ("The attached images, in order, are the last second of shot %d of a short film, already filmed; the "
            "last image is its final frame. " % numero + (COUPE_DEPART if coupe else SUITE_DEPART) % (numero + 1) +
            "Then fix any later action that the real start makes impossible or "
            "useless (walking to someone already next to them, taking with a hand that is busy), with the smallest "
            "change. If an action that the story expects to have happened is not visible in the images, do not "
            "assume it. Change only what the images show CLEARLY: when unsure (which hand of a character, his "
            # 02/10, plan 4, trois essais à blanc : une fois sur trois, les mains de Leila inversées à tort.
            "left or right), keep the text as written. "
            "Keep everything else exactly: every line of dialogue word for word with its « » and its "
            "[tags], the order of actions, the time of day, the names. If the text already matches, return it "
            "unchanged. Answer with JSON only: {\"texte\": \"the full text of shot %d\", \"changements\": \"what "
            "you changed and why, one short sentence in French, empty if nothing\"}.\n\nShot %d: %s"
            % (numero + 1, numero + 1, texte))


# 02/10, film 4 : le texte du plan 4 corrigé (Tyler à cheval sur le vélo, deux mains au
# guidon), son tableau disait encore « debout, une main ». La règle 7 cherchait Tyler à
# la place du tableau, et le tableau part dans l'invite de H3 : un texte changé fait
# réécrire son tableau.
def consigne_tableau_a_jour(texte: str, elements: list) -> str:
    return ("The text of a shot of a short film was rewritten; its table of key elements was not. Rewrite the "
            "table so that every entry is true to the NEW text: where each element is when the shot starts, "
            "what it does, where it is when it ends, which hand holds what. Keep the same names, and keep an "
            "entry unchanged when the text does not contradict it. " + TABLEAU +
            "Answer with JSON only: {\"elements\": [...]}.\n\nShot text: %s\n\nOld table: %s"
            % (texte, json.dumps(elements, ensure_ascii=False)))


def lire_tableau_a_jour(reponse: str) -> list:
    """Le tableau réécrit, nettoyé ; ValueError s'il est illisible ou vide."""
    t = str(reponse or "")
    debut, fin = t.find("{"), t.rfind("}")
    try:
        d = json.loads(t[debut:fin + 1]) if debut >= 0 else None
    except ValueError:
        d = None
    tableau = lire_tableau((d or {}).get("elements") if isinstance(d, dict) else None)
    if not tableau:
        raise ValueError("Le tableau du plan n'a pas pu être réécrit : l'ancien est gardé.")
    return tableau


def lire_depart_reel(reponse: str, texte: str) -> dict:
    """{texte, changements} ; ValueError si illisible, ou si une réplique a bougé."""
    t = str(reponse or "")
    debut, fin = t.find("{"), t.rfind("}")
    try:
        d = json.loads(t[debut:fin + 1]) if debut >= 0 else None
    except ValueError:
        d = None
    nouveau = " ".join(str((d or {}).get("texte") or "").split()) if isinstance(d, dict) else ""
    # 02/10, plan 5 : le texte rendu commençait par « Shot 5: », recopié de la consigne.
    nouveau = re.sub(r"^shot\s*\d+\s*:\s*", "", nouveau, flags=re.I)
    if not nouveau:
        raise ValueError("L'adaptation du départ n'a pas pu être lue.")
    if repliques(nouveau) != repliques(texte):
        raise ValueError("L'adaptation du départ a touché une réplique : le texte écrit est gardé.")
    if len(nouveau) < len(texte) // 2:
        raise ValueError("L'adaptation du départ a trop raccourci le texte : le texte écrit est gardé.")
    return {"texte": nouveau, "changements": " ".join(str(d.get("changements") or "").split())[:400]}


def lire_continuite(reponse: str, nombre: int, textes: list | None = None, deja_filmes=None) -> dict:
    """Avec les textes des plans, un problème qui cite des mots absents de son plan
    est écarté : premier essai réel (29/09), le relecteur réclamait ce qui était déjà écrit.
    Seuls les problèmes bloquants restent dans `problemes` (et font corriger) ; les
    détails vont dans `details`, affichés sans rien réécrire. Sans gravité lisible,
    un problème est bloquant, comme avant."""
    t = str(reponse or "")
    debut, fin = t.find("{"), t.rfind("}")
    try:
        d = json.loads(t[debut:fin + 1]) if debut >= 0 else None
    except ValueError:
        d = None
    if not isinstance(d, dict) or not isinstance(d.get("problemes"), list):
        raise ValueError("Le contrôle de continuité n'a pas pu être lu : réessayez.")
    problemes, details = [], []
    for x in d["problemes"]:
        try:
            plan = int(x["plan"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (1 <= plan <= nombre and str(x.get("quoi") or "").strip()) or plan in (deja_filmes or ()):
            continue   # un plan déjà filmé ne se corrige plus par son texte (02/10)
        citation = _norme_replique(str(x.get("citation") or ""))
        if citation and textes is not None and plan <= len(textes) \
                and f" {citation} " not in f" {_norme_replique(textes[plan - 1])} ":
            continue
        probleme = {"plan": plan, "quoi": " ".join(str(x["quoi"]).split())[:300]}
        if citation:
            probleme["citation"] = " ".join(str(x["citation"]).split())[:300]
        (details if str(x.get("gravite") or "").strip().lower() in ("detail", "détail") else problemes).append(probleme)
    etats = [e for e in d.get("etats") or [] if isinstance(e, dict)][:nombre]
    return {"ok": not problemes, "problemes": problemes, "details": details, "etats": etats}


# 03/10, « Le jardin de verre » : le relecteur a noté « la tenue de Mila n'est décrite dans
# aucun plan », et la correction, malgré sa consigne, l'a habillée d'un « cream sweater and
# dark trousers » dans tous les plans : l'image de départ a suivi, loin du pull rayé de sa
# fiche. Une tenue que ni l'histoire ni le plan d'origine ne donnent est retirée par le code.
_VETEMENT = re.compile(r"\b(?:wear(?:s|ing)?|dressed|sweaters?|jumpers?|pullovers?|cardigans?|hoodies?|"
                       r"sweatshirts?|t-shirts?|shirts?|blouses?|trousers|pants|jeans|shorts|skirts?|dress(?:es)?|"
                       r"overalls|dungarees|jackets?|coats?|scarf|scarves|socks|slippers|uniform)\b", re.I)
_PORTE_ENTRE = re.compile(r",\s*(?:wearing|dressed in)\b[^,.;:«]*,\s*", re.I)
_PORTE_FIN = re.compile(r",?\s*\b(?:wearing|dressed in)\b[^,.;:«]*", re.I)


def vetements(texte: str) -> set:
    return {m.lower() for m in _VETEMENT.findall(str(texte or ""))}


def sans_tenue_inventee(nouveaux: list, plans: list, histoire: str = "") -> tuple:
    """(plans, numéros retouchés) : dans chaque plan réécrit, la tenue qu'il ajoute sans que
    l'histoire ou le plan d'origine en parlent est retirée ; s'il reste un vêtement ajouté, le
    plan garde son texte d'origine."""
    sortie, touches = [], []
    for k, (n, p) in enumerate(zip(nouveaux, plans), 1):
        connus = vetements(p["image_paroles"] + " " + p.get("ambiance", "") + " " + histoire)
        champs = {}
        for c in ("image_paroles", "ambiance"):
            t = str(n.get(c) or "")
            if vetements(t) - connus:
                t = _PORTE_FIN.sub("", _PORTE_ENTRE.sub(" ", t))
            champs[c] = t
        if vetements(champs["image_paroles"] + " " + champs["ambiance"]) - connus:
            sortie.append(dict(n, image_paroles=p["image_paroles"], ambiance=p.get("ambiance", ""),
                               elements=p.get("elements", n.get("elements"))))
            touches.append(k)
        else:
            if champs["image_paroles"] != n["image_paroles"] or champs["ambiance"] != n.get("ambiance", ""):
                touches.append(k)
            sortie.append(dict(n, **champs))
    return sortie, touches


def sans_tenue_du_texte(plans: list, histoire: str = "") -> tuple:
    """(plans, numéros retouchés) : la tenue qu'un plan écrit sans que l'histoire la donne est
    retirée (« les attributs sont toujours avec des images, jamais en texte », 03/10)."""
    connus, sortie, touches = vetements(histoire), [], []
    for k, p in enumerate(plans, 1):
        champs = {}
        for c in ("image_paroles", "ambiance"):
            t = str(p.get(c) or "")
            if vetements(t) - connus:
                t = _PORTE_FIN.sub("", _PORTE_ENTRE.sub(" ", t))
            champs[c] = t
        if champs["image_paroles"] != p["image_paroles"] or champs["ambiance"] != p.get("ambiance", ""):
            touches.append(k)
            p = dict(p, **champs)
        sortie.append(p)
    return sortie, touches


def lire_correction(reponse: str, plans: list) -> list:
    """La correction du chat, contrôlée : mêmes plans, mêmes répliques à la même place."""
    nouveaux = lire_decoupage(reponse, " ".join(p["image_paroles"] + " " + p["ambiance"] for p in plans))
    if len(nouveaux) != len(plans):
        raise ValueError("La correction a changé le nombre de plans : réessayez.")
    for i, (n, p) in enumerate(zip(nouveaux, plans)):
        if repliques(n["image_paroles"] + " " + n["ambiance"]) != repliques(p["image_paroles"] + " " + p["ambiance"]):
            raise ValueError(f"La correction a déplacé ou retiré une réplique (plan {i + 1}) : réessayez.")
        if valeur_de_plan(p["image_paroles"]) and not valeur_de_plan(n["image_paroles"]):
            raise ValueError(f"La correction a retiré la valeur de plan (plan {i + 1}) : réessayez.")
    # La caméra et la durée sont des choix du propriétaire (menus) : la correction n'y touche pas.
    return [dict(n, enchainement=p["enchainement"], camera=lire_camera(p.get("camera")),
                 **{k: p[k] for k in ("image_depart", "description_depart", "longueur") if k in p})
            for n, p in zip(nouveaux, plans)]


# --- Un plan à plusieurs répliques, coupé en plans d'une réplique (30/09) ----------
# Film campus : le découpage a mis deux répliques (Leila, puis Tyler) dans le plan
# 5 malgré sa consigne ; la règle 2 l'a bloqué avant la location, et c'est à la main
# qu'il a été coupé en 5 et 6. Décision du propriétaire : « la découpe doit être
# hard codée (et proposée) dans le studio dans ce cas ». Le code trouve ces plans ;
# le chat les coupe (gratuit) ; la découpe est gardée seulement si chaque morceau
# a une seule réplique, toutes dans l'ordre et mot pour mot.

def plans_a_scinder(plans: list) -> list:
    """Les numéros (0…) des plans qui ont plus d'une réplique."""
    return [i for i, p in enumerate(plans)
            if len(repliques(p["image_paroles"] + " " + p.get("ambiance", ""))) > 1]


def consigne_scission(plan: dict) -> str:
    n = len(repliques(plan["image_paroles"] + " " + plan.get("ambiance", "")))
    return ("This shot of a short film has %d lines of dialogue; the video model renders one line per shot "
            "clearly, and two make the sound confused. Split it into exactly %d consecutive shots, one line each, "
            "in the same order. The first shot keeps the place and framing of the original; each following "
            "shot continues the previous one without a cut, from the same camera. Each shot's text says where "
            "each key element is, with the same words as the original, then the action around its line, then "
            "the line copied EXACTLY between « », its mark in square brackets included; a character who does not "
            "speak in that shot only reacts, silently. Never add, change or move dialogue, never invent an "
            "action the original does not have. " % (n, n)
            + TABLEAU + "For each shot give \"elements\", \"image_paroles\" and \"ambiance\" (the original "
            "sounds). Answer with the JSON array only.\n\nShot: %s" % json.dumps(plan, ensure_ascii=False))


def lire_scission(reponse: str, plan: dict) -> list:
    """La découpe du chat, contrôlée : une réplique par morceau, toutes, dans l'ordre."""
    texte = plan["image_paroles"] + " " + plan.get("ambiance", "")
    attendues = repliques(texte)
    # L'enchaînement des morceaux est posé plus bas, quoi que dise le chat : le 02/10 (« Leila et
    # l'appareil photo », plan 6), il avait écrit « fixe » (le mot de la caméra), et toute la découpe
    # était refusée pour « enchaînement inconnu ».
    t = str(reponse or "")
    debut, fin = t.find("["), t.rfind("]")
    try:
        brut = json.loads(t[debut:fin + 1]) if debut >= 0 else None
    except ValueError:
        brut = None
    if isinstance(brut, list):
        reponse = json.dumps([dict(m, enchainement="suite") if isinstance(m, dict) else m for m in brut],
                             ensure_ascii=False)
    morceaux = lire_decoupage(reponse, texte)
    if len(morceaux) != len(attendues):
        raise ValueError("La découpe n'a pas rendu un plan par réplique.")
    for k, m in enumerate(morceaux):
        dites = repliques(m["image_paroles"] + " " + m["ambiance"])
        if len(dites) != 1 or _norme_replique(dites[0]) != _norme_replique(attendues[k]):
            raise ValueError("La découpe a déplacé ou perdu une réplique (morceau %d)." % (k + 1))
    camera = lire_camera(plan.get("camera"))
    duree = {"longueur": plan["longueur"]} if plan.get("longueur") else {}
    premier = dict(morceaux[0], enchainement=plan["enchainement"], camera=camera, **duree,
                   **{c: plan[c] for c in ("image_depart", "description_depart") if c in plan})
    return [premier] + [dict(m, enchainement="suite", camera=camera, **duree) for m in morceaux[1:]]


def scinder(plans: list, i: int, morceaux: list) -> list:
    """Les plans, le plan i remplacé par ses morceaux ; ValueError si les limites ne tiennent pas
    (SCENARIO_PLANS_MAX, PLANS_MAX d'affilée sans coupe)."""
    return verifier_plans(borner_les_suites(plans[:i] + morceaux + plans[i + 1:]))


def _meme_texte(a, b) -> bool:
    return " ".join(str(a or "").split()) == " ".join(str(b or "").split())


def plans_initiaux_du_rejeu(initiaux: list, anciens: list, ecrits: list) -> list:
    """Le texte d'origine de chaque plan d'un rejeu, celui que le juge du plan tourné lit
    (règles 9 et 12) : l'origine héritée pour un plan au même texte (l'adaptation du départ
    ne la change pas) ; le texte ÉCRIT pour un plan au texte changé. Bug du 02/10, film 4 :
    le plan 6a, réécrit, était jugé sur le texte du plan 6 d'origine (réplique « fausse »,
    « Tyler encore là »)."""
    sortie = []
    for i, p in enumerate(ecrits):
        garde = (i < len(initiaux) and i < len(anciens)
                 and _meme_texte(p.get("image_paroles"), anciens[i].get("image_paroles")))
        sortie.append(initiaux[i] if garde else dict(p))
    return sortie


def plans_avec_coupes_refaites(nouveaux: list, anciens: list, departs_de_coupe: list) -> list:
    """Bug du 02/10, film 4 : au tournage, le Studio refait l'image de départ d'une coupe d'après
    le film et la met à la place de celle du découpage dans les plans du scénario. Un client qui
    renvoie SES plans au rejeu y laisse l'image du découpage : le plan semblait changé et
    repartait chez Modal (plan 5, arrêté au bout de ~3 min). Ici, un plan qui porte encore
    l'image du découpage d'une coupe refaite reprend l'image tournée : il est inchangé."""
    sortie = [dict(p) for p in nouveaux]
    for note in departs_de_coupe or []:
        i = int(note.get("plan") or 0) - 1
        decoupage = note.get("decoupage")
        if not (0 <= i < len(sortie) and i < len(anciens) and decoupage and note.get("garde") == note.get("depart")):
            continue
        if sortie[i].get("image_depart") == decoupage and anciens[i].get("image_depart") == note["garde"]:
            sortie[i].update(image_depart=anciens[i]["image_depart"],
                             description_depart=anciens[i].get("description_depart", ""))
    return sortie


def plans_a_reprendre(anciens: list, nouveaux: list, retourner=()) -> list:
    """Les numéros (0…) des plans repris tels quels au lieu d'être retournés :
    inchangés, non demandés, et, pour une « suite », après un plan repris
    (elle part de sa dernière image)."""
    repris = []
    for i, p in enumerate(nouveaux):
        pareil = i < len(anciens) and all(p.get(k) == anciens[i].get(k) for k in (
            "image_paroles", "ambiance", "enchainement", "image_depart", "description_depart", "longueur")) and (
            lire_camera(p.get("camera")) == lire_camera(anciens[i].get("camera")))
        if pareil and (i + 1) not in retourner and (p["enchainement"] == "coupe" or (i - 1) in repris):
            repris.append(i)
    return repris


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


def graphe(mode: str, texte: str, longueur: int, graine: int, nb_images: int = 0,
           definition: str = DEFINITION_PAR_DEFAUT, nb_sons: int = 0) -> dict:
    """Le graphe des essais du 27/09, pour un clip.

    Chargeurs, LoRA Turbo 4 étapes, échantillonneur `res_multistep`, ordonnanceur
    `simple`, puis image et son décodés et réunis en un MP4.
    """
    nom = lambda chemin: chemin.split("/")[1]  # noqa: E731
    f = fichiers_du_mode(mode)
    g = {
        "1": _n("UNETLoader", {"unet_name": nom(f[0]), "weight_dtype": "default"}),
        "2": _n("LoraLoaderModelOnly", {"model": ["1", 0], "lora_name": nom(f[4]),
                                         "strength_model": 1.0}),
        "3": _n("CLIPLoader", {"clip_name": nom(f[1]), "type": "minimax"}),
        "4": _n("VAELoader", {"vae_name": nom(f[2])}),
        "5": _n("VAELoader", {"vae_name": nom(f[3])}),
        "8": _n("KSamplerSelect", {"sampler_name": "res_multistep"}),
        "9": _n("BasicScheduler", {"model": ["2", 0], "scheduler": "simple", "steps": 4, "denoise": 1.0}),
    }
    largeur, hauteur = DEFINITIONS[definition]
    taille = {"width": largeur, "height": hauteur, "length": int(longueur)}
    images = noms_images(mode, nb_images)
    for i, fichier in enumerate(images):
        g[f"6{i}"] = _n("LoadImage", {"image": fichier})
    if mode == "references":
        entrees = {"clip": ["3", 0], "vae": ["4", 0], "audio_vae": ["5", 0], "prompt": texte,
                   "ref_image_size": "match", **taille}
        for i in range(len(images)):
            entrees[f"ref_images.ref_image_{i}"] = [f"6{i}", 0]
        for j in range(nb_sons):   # les profils voix, <Audio 1…3> (29/09)
            g[f"7{j}"] = _n("LoadAudio", {"audio": f"voix_{j}.wav"})
            entrees[f"ref_audios.ref_audio_{j}"] = [f"7{j}", 0]
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


NOEUDS_TRONCON = ("MiniMaxH3MotionContextLoadLatent", "MiniMaxH3MotionContext",
                  "MiniMaxH3MotionContextTrim")


def graphe_troncon(texte: str, longueur: int, graine: int, contexte: str) -> dict:
    """Le plan suivant par tronçon : le graphe de l'essai du 27/09 (branche b).

    Le latent du plan précédent est relu sur le disque Modal ; le nœud en épingle
    la fin (22 images, 1 s de son) au début du nouveau plan, puis Trim retire ces
    images reprises, et le son qui va avec, du plan livré.
    """
    return brancher_troncon(graphe("texte", texte, longueur, graine), contexte)


def brancher_troncon(g: dict, contexte: str) -> dict:
    """Le tronçon branché sur le nœud 10 du graphe, texte seul ou Références. Jalon 0 bis, clip 6
    (05/10) : en Références, les photos de la fiche et sa voix dans le clip enchaîné, la ressemblance à
    la fiche en fin de clip passe de 0,312 à 0,453 (ArcFace), même graine, même raccord."""
    g["30"] = _n("MiniMaxH3MotionContextLoadLatent", {"latent_path": contexte, "clip_index": 1})
    g["31"] = _n("MiniMaxH3MotionContext", {
        "conditioning": ["10", 0], "vae": ["4", 0], "latent": ["10", 1], "context_latent": ["30", 0],
        "audio_vae": ["5", 0], "context_length": CONTEXTE_IMAGES, "audio_context_length": CONTEXTE_SON})
    g["13"]["inputs"]["conditioning"] = ["31", 0]
    g["32"] = _n("MiniMaxH3MotionContextTrim", {"images": ["15", 0], "audio": ["16", 0],
                                                 "trim_frames": ["31", 1], "fps": float(IMAGES_PAR_SECONDE)})
    g["17"]["inputs"].update({"images": ["32", 0], "audio": ["32", 1]})
    return g


# --- Le raccord natif d'une suite en « Références » (30/09) -----------------------
# Le nœud Références n'a pas d'entrée first_frame : la dernière image du plan
# précédent n'y était qu'une <Picture N> de plus, et H3 recadrait (film campus,
# 30/09 : plan 2 parti en plan large après un plan moyen ; remarque du
# propriétaire). ComfyUI v0.37.0 a MiniMaxH3AddGuide, qui épingle des images ET
# leur son à une image donnée ; son exemple de continuation (PR Comfy-Org/ComfyUI
# #15439) : « feed the first 22 frames of an existing video plus its audio into one
# AddGuide at frame_idx 0 and the model generates the continuation of both streams ».
# Décision du propriétaire, 30/09 : « oui code-le ». Les 22 images reprises sont
# retirées au recollage ; le plan gagne 17 images pour ne pas raccourcir.
RACCORD_IMAGES = 22   # 17k+5, la longueur de l'exemple de la PR
NOEUDS_RACCORD = ("LoadVideo", "GetVideoComponents", "MiniMaxH3AddGuide")
# Film campus, plan 4 (30/09) : les 22 images épinglées au pixel près, puis H3 a
# COUPÉ vers le cadrage du texte (« Leila at the centre, facing the camera »), que
# la fin du plan 3 (Leila à gauche, de profil) contredisait. AddGuide ne passe
# rien au texte : H3 lisait deux ordres contraires. Remarque du propriétaire : « le
# placement est déjà câblé par les images du clip amont » ; décision : « hard code
# ça dans le studio ». Le guide de MiniMax a une tâche pour cela, « video
# continuation », la source citée en <Video N> : la fin du plan part aussi en
# ref_videos (ComfyUI v0.37.0, 3 au plus ; images, puis vidéos, puis sons : les
# <Audio j> des voix ne bougent pas, la vidéo part sans sa bande son), et le texte dit
# qu'en cas de désaccord sur les places, c'est <Video 1> qui a raison.
SUITE_GARDE = ("<Video 1> ([Shot 1] start): fully_preserved - [Shot 1] continues <Video 1> in one "
               "continuous take, with no cut: the same framing, and every person and object in the same "
               "place and facing the same way as at the end of <Video 1>. "
               # 02/10, « la voix change » quand le plan d'avant ne parle pas, ou qu'un autre y
               # parle : un guide de H3 écrit « The voice heard in Video 1 guides Speaker 1 ».
               "The sound of <Video 1> continues only as ambient sound: no voice heard in <Video 1> "
               "is a voice reference; each speaking person keeps the voice of their own <Audio> reference.")
# L'invite légère (02/10, propriétaire : « trop d'infos tue l'info ») : le raccord est déjà dit
# en tête de la description (SUITE_DEBUT) ; reste ce que celle-ci ne dit pas, la voix.
SUITE_GARDE_LEGERE = "<Video 1>: fully_preserved - no cut; voices heard in <Video 1> are not voice references."
SUITE_DEBUT = ("The shot continues <Video 1> without a cut: where each person and object stands and "
               "faces comes from the end of <Video 1>, even where the text below places them otherwise. ")


# 02/10, « Leila et un martien », plans 3 → 4 : le plan 3 finit sur un zoom avant ; le
# plan 4, une suite, redisait « Medium shot », le télescope au premier plan et Zib
# « starting in the middle ground » : H3 a suivi le texte, recadré et rejoué le salut.
# Remarque du propriétaire : la coupe sert aux vrais changements de point de vue ; une
# suite part de la fin du plan d'avant. Le texte d'une suite ne dit donc plus ni le
# cadrage, ni ce qui ne bouge pas, ni d'où partent ceux qui bougent : <Video 1> le montre.
_CADRAGE_EN_TETE = re.compile(
    r"^\s*(?:an?\s+)?(?:extreme\s+|very\s+|tight\s+|static\s+)?(?:close[- ]?up|medium(?:[- ]close(?:[- ]?up)?)?"
    r"(?:[- ]wide)?\s+shot|medium\s+close[- ]?up|wide\s+shot|long\s+shot|full\s+shot|establishing\s+shot|"
    r"over[- ]the[- ]shoulder\s+shot|two[- ]shot|gros\s+plan|plan\s+(?:large|moyen|rapproch[ée]|serr[ée]|"
    r"d'ensemble|am[ée]ricain))\b[^.!?]*[.!?]\s*", re.IGNORECASE)
# Une phrase : jusqu'à son point, une réplique « … » comprise avec ses propres points.
_PHRASES = re.compile(r"[^.!?«]*(?:«[^»]*»[^.!?«]*)*(?:[.!?]+\s*|$)")
_IMMOBILE = ("", "none", "no", "nothing", "static", "still", "aucun", "rien", "immobile")
# 02/10, « Leila et un martien », plan 1 : « mouvement : none » pour Leila, qui regarde
# dans le télescope ; H3 l'a figée tout le plan. Propriétaire : « il manque une indication
# d'action, leila est figée ». Une personne dans le cadre n'est jamais une statue.
VIVANT = ("{nom} stays alive, never frozen: {nom} breathes, blinks and makes small natural movements "
          "of the head and hands while keeping this pose.")


def phrases_vivants(elements, personnes) -> str:
    """Pour chaque personne du tableau, dans le cadre, sans mouvement écrit : la phrase qui
    la garde vivante. `personnes` : les noms des fiches de personnes (pas des objets)."""
    noms = {_norme_replique(n): n for n in personnes or ()}
    phrases = []
    for e in elements or ():
        if not isinstance(e, dict):
            continue
        nom = noms.get(_norme_replique(str(e.get("nom") or "")))
        if (nom and str(e.get("mouvement") or "").strip().lower().rstrip(".") in _IMMOBILE
                and not (hors_champ(e.get("debut")) and hors_champ(e.get("fin")))):
            phrases.append(VIVANT.format(nom=nom))
    return " ".join(phrases)


def texte_de_suite(texte: str, elements) -> str:
    """Le texte d'une « suite » sans ce que la fin du plan d'avant montre déjà : la
    phrase du cadrage en tête, les phrases sur les seuls éléments immobiles, et l'état
    de départ de chacun (« starting … », ou en tête de phrase). Les gestes,
    les arrivées et les répliques restent. Sans tableau, seul le cadrage part."""
    t = _CADRAGE_EN_TETE.sub("", str(texte or ""), count=1)
    tableau = [e for e in (elements or []) if isinstance(e, dict) and str(e.get("nom") or "").strip()]
    if not tableau:
        return t.strip() or str(texte or "").strip()
    bougent = [e for e in tableau if str(e.get("mouvement") or "").strip().lower().rstrip(".") not in _IMMOBILE]
    immobiles = [e for e in tableau if e not in bougent]
    noms = lambda es: [str(e["nom"]).strip() for e in es]   # noqa: E731
    contient = lambda p, n: re.search(r"(?<!\w)" + re.escape(n) + r"(?!\w)", p, re.IGNORECASE)   # noqa: E731
    gardees = []
    for p in _PHRASES.findall(t):
        if not p.strip():
            continue
        if "«" not in p and any(contient(p, n) for n in noms(immobiles)) \
                and not any(contient(p, n) for n in noms(bougent)):
            continue
        # Seulement l'état d'un élément que la phrase nomme ; et, en tête de phrase, le plus
        # long qui colle : Leila et le télescope partent tous deux « in the foreground,
        # left of the frame », la phrase « …, looking into the small telescope, Leila
        # turns » est celle de Leila. Un état de départ se reconnaît aussi par son début
        # seul (« …, standing, Leila looks at Zib » : sans « looking at Zib »).
        motifs = []
        for e in tableau:
            d = " ".join(str(e.get("debut") or "").split()).rstrip(" ,.")
            if d and not hors_champ(d) and contient(p, str(e["nom"]).strip()):
                parts = [x.strip() for x in d.split(",") if x.strip()]
                motifs += [(k, r"\s*,\s*".join(re.escape(x) for x in parts[:k])) for k in range(1, len(parts) + 1)]
        for _, debut in sorted(motifs, reverse=True):
            p = re.sub(r",?\s*starting\s+" + debut + r"\s*,", "", p, count=1, flags=re.IGNORECASE)
        for _, debut in sorted(motifs, reverse=True):
            court = re.sub(r"^\s*" + debut + r"\s*,\s*", "", p, count=1, flags=re.IGNORECASE)
            if court != p:
                p = court
                break
        p = p.lstrip()
        gardees.append(p[:1].upper() + p[1:])
    return " ".join(x.strip() for x in gardees).strip() or t.strip() or str(texte or "").strip()


def ajouter_raccord(demande: dict, fin_b64: str) -> dict:
    """Épingle `fin_b64` (mp4 : les RACCORD_IMAGES dernières images du plan
    précédent et leur son) à l'image 0 du plan : image et son continuent."""
    g = demande["graphe"]
    g["80"] = _n("LoadVideo", {"file": "raccord.mp4"})
    g["81"] = _n("GetVideoComponents", {"video": ["80", 0]})
    g["11"] = _n("MiniMaxH3AddGuide", {"positive": ["10", 0], "vae": ["4", 0], "audio_vae": ["5", 0],
                                        "latent": ["10", 1], "image": ["81", 0], "audio": ["81", 1],
                                        "frame_idx": 0})
    g["13"]["inputs"]["conditioning"] = ["11", 0]
    g["10"]["inputs"]["ref_videos.ref_video_0"] = ["81", 0]   # <Video 1>, lue par le texte
    demande["videos"] = {"raccord.mp4": fin_b64}
    demande["classes"] = list(demande["classes"]) + list(NOEUDS_RACCORD)
    return demande


NOEUDS_DEPART = ("MiniMaxH3AddGuide",)


def epingler_depart(demande: dict, rang: int) -> dict:
    """Épingle l'image de départ, déjà chargée en <Picture N> (nœud « 6<rang> »), à
    l'image 0 du plan. En <Picture N> seule, elle n'était qu'une référence de plus :
    film campus, 01/10, plan 1 parti de l'image 95015619 (Leila seule, au centre) ;
    dès l'image 0, H3 a recomposé un plan large avec DEUX Leila, celle des photos de
    sa fiche et celle de l'image. AddGuide prend une image fixe à frame_idx 0 (PR
    Comfy-Org/ComfyUI #15439), sans son : la bande son reste libre."""
    g = demande["graphe"]
    g["11"] = _n("MiniMaxH3AddGuide", {"positive": ["10", 0], "vae": ["4", 0], "audio_vae": ["5", 0],
                                        "latent": ["10", 1], "image": [f"6{rang}", 0], "frame_idx": 0})
    g["13"]["inputs"]["conditioning"] = ["11", 0]
    demande["classes"] = list(demande["classes"]) + [c for c in NOEUDS_DEPART if c not in demande["classes"]]
    return demande


def longueur_avec_raccord(longueur: int) -> int:
    """Le pas suivant de la grille : le raccord reprend 22 images, le plan en gagne 17."""
    plus = int(longueur) + 17
    return plus if plus in LONGUEURS else int(longueur)


def images_a_retirer(plan: dict) -> int:
    """Au recollage : 1 image (la dernière, montrée deux fois) par la dernière image,
    le raccord entier par raccord, rien par tronçon (déjà coupé sur la carte)."""
    return {"image": 1, "raccord": RACCORD_IMAGES}.get(plan["resume_public"].get("voie"), 0)


def garder_latent(demande: dict, jid: str) -> dict:
    """Option tronçon : le latent de ce clip reste sur le disque Modal, pour le
    plan qui le prolongera. Sans l'option, rien n'est ajouté au graphe."""
    if not motion_context_actif():
        return demande
    demande["graphe"]["19"] = _n("MiniMaxH3MotionContextSaveLatent", {
        "latent": ["14", 0], "filename_prefix": "h3_context/clip", "clip_index": 1})
    demande["classes"] = list(demande["classes"]) + ["MiniMaxH3MotionContextSaveLatent"]
    demande["latent_vers"] = f"{DOSSIER_CHAINES}/{jid}.safetensors"
    return demande


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


def personnes_du_plan(ids: list, payload: dict) -> list:
    """Les fiches d'un plan de scénario, sans les personnes qu'il ne nomme nulle part (ni son
    tableau d'éléments, ni son texte). 03/10, « Le jardin de verre », plan 2 (gros plan sur le
    pot) : la photo de Mila partait en <Subject 1> avec « wears … in every frame », et H3 l'a
    fait traverser le champ. Seulement avec un tableau (un plan de scénario) : un clip fait à
    la main dit souvent « she ». Il reste toujours au moins une fiche."""
    elements = payload.get("elements")
    if not isinstance(elements, list) or not elements:
        return ids
    nommes = " ".join([_norme_replique(str(e.get("nom") or "")) for e in elements if isinstance(e, dict)]
                      + [_norme_replique(str(payload.get(c) or "")) for c in ("image_paroles", "ambiance")])
    gardees = []
    for fid in ids:
        try:
            fiche = fiche_lire(fid)
        except ValueError:
            gardees.append(fid)   # illisible : la suite dira pourquoi
            continue
        nom = _norme_replique(str(fiche.get("nom") or ""))
        if fiche_est_objet(fiche) or fiche.get("genre") == "decor" or not nom or f" {nom} " in f" {nommes} ":
            gardees.append(fid)
    return gardees or ids


def preparer(payload: dict, graine_hasard=None) -> dict:
    """Vérifie la demande de la page et fabrique ce qui part sur la machine.

    Rend {"demande", "resume_public"} ou lève ValueError avec une phrase pour
    la page. Rien n'est loué ici.
    """
    mode = str(payload.get("mode") or "texte")
    if mode not in MODES:
        raise ValueError("Mode inconnu.")
    langue = str(payload.get("langue") or LANGUE_PAROLES)
    if langue not in LANGUES_PAROLES:
        raise ValueError("Langue des paroles inconnue.")
    # Une fiche (`fiche`) ou plusieurs (`fiches`, une par personnage, dans
    # l'ordre des <Subject N>) ; chacune peut parler sa langue (`langues`).
    ids = payload.get("fiches") or ([payload["fiche"]] if payload.get("fiche") else [])
    if not isinstance(ids, list) or len(set(map(str, ids))) != len(ids):
        raise ValueError("Liste de fiches illisible.")
    ids = personnes_du_plan(ids, payload)
    langues = payload.get("langues") or {}
    if not isinstance(langues, dict) or any(v not in LANGUES_PAROLES for v in langues.values()):
        raise ValueError("Langue d'un personnage inconnue.")
    # En « Première image », les fiches ne donnent que les voix : qui dit quelle
    # réplique, dans quelle langue (plan « coupe » parti de son image, 28/09).
    refs = mode == "references"
    tenues = payload.get("tenues") or {}
    ecrites = payload.get("tenues_ecrites") or {}
    if not isinstance(tenues, dict) or not isinstance(ecrites, dict) or not all(
            isinstance(t, str) and len(t) <= 300 for t in ecrites.values()):
        raise ValueError("Tenues illisibles.")
    fiches, de_la_fiche, nombres, avec_tenue, ecrites_k, avec_planche = [], [], [], set(), {}, set()
    voix_k, sons = {}, []   # le profil voix de chaque personnage qui en a un (29/09)
    candidates = []   # (rang, voix) ; seuls ceux qui parlent dans ce plan la gardent (30/09)
    objets = {}   # rang de la fiche -> "objet" ou "pose"
    for fid in ids:
        if mode not in ("references", "premiere", "premiere_derniere"):
            raise ValueError("Une fiche de casting se joue en mode « Références » ou « Première image ».")
        fiche = fiche_lire(fid)
        if fiche.get("genre") == "decor":
            raise ValueError(f"« {fiche['nom']} » est un décor : il se choisit comme décor du scénario, "
                             "pas parmi les fiches du plan.")
        fiches.append(fiche)
        if fiche_est_objet(fiche):
            objets[len(fiches) - 1] = fiche["genre"]
        if not refs:
            continue
        if fiche_est_objet(fiche):   # un objet n'a ni tenue ni tenue écrite
            images_fiche = fiche_images(fiche["id"])
            if not images_fiche:
                raise ValueError(f"La fiche « {fiche['nom']} » n'a encore aucune image : créez-les d'abord.")
            de_la_fiche += images_fiche
            nombres.append(len(images_fiche))
            continue
        # Une autre tenue : le visage de la fiche et la photo de la tenue, sans les photos
        # qui montrent l'ancienne (deux tenues à la fois, H3 choisissait au hasard).
        visage_seul = bool(tenues.get(fiche["id"])) or payload.get("visages_seuls") is True
        images_fiche = fiche_images_h3(fiche["id"], visage_seul=visage_seul)
        if not visage_seul and fiche.get("planche"):
            avec_planche.add(len(nombres))
        if not images_fiche:
            raise ValueError(f"La fiche « {fiche['nom']} » n'a encore aucune image : créez-les d'abord.")
        if tenues.get(fiche["id"]):
            images_fiche = images_fiche + [tenues[fiche["id"]]]
            avec_tenue.add(len(nombres))
        if " ".join(str(ecrites.get(fiche["id"]) or "").split()):
            ecrites_k[len(nombres)] = " ".join(ecrites[fiche["id"]].split())
        if fiche.get("voix"):
            candidates.append(len(nombres))
        de_la_fiche += images_fiche
        nombres.append(len(images_fiche))
    image_paroles, ambiance = payload.get("image_paroles", ""), payload.get("ambiance", "")
    # Une marque mal écrite (« [joyeus] ») serait DITE par le personnage (30/09).
    inconnues = marques_inconnues(image_paroles) + marques_inconnues(ambiance)
    if inconnues:
        raise ValueError("Marque de réplique inconnue : « [%s] ». Une marque donne la langue et/ou "
                         "l'émotion (menu « Langue et émotion d'une réplique »)." % inconnues[0])
    # Un texte en plans ([Shot N]) porte sa caméra plan par plan : la caméra fixe par défaut
    # la contredisait (03/10, clip maître, « The camera holds a static shot throughout »).
    camera = payload.get("camera") or ({"mouvement": "auto"} if _MULTIPLAN.search(image_paroles) else None)
    image_paroles = avec_camera(image_paroles, phrase_camera(camera))
    vivants = phrases_vivants(payload.get("elements"), [f["nom"] for f in fiches if not fiche_est_objet(f)])
    if vivants:
        image_paroles = (image_paroles.rstrip() + " " + vivants).strip()
    if fiches:
        sujets = [(f["nom"], langues.get(f["id"], langue)) for f in fiches]
        # Une voix ne part qu'avec qui parle dans ce plan : envoyée à un personnage muet,
        # H3 le faisait parler quand même (film du parc, 30/09, plan 3).
        # Et dans la langue de chaque réplique (30/09) : Leila en anglais avec sa voix anglaise.
        dites = []
        for t in (image_paroles, ambiance):
            attribuer_repliques(t, sujets, objets=objets, releve=dites)
        avec_voix = [f if k in candidates else {} for k, f in enumerate(fiches)]
        for k, langue in voix_du_plan(dites, avec_voix):
            son = fiche_voix(fiches[k]["id"], langue)
            if son:
                sons.append(base64.b64encode(montage.niveler_son(son, VOIX_REFERENCE_LUFS)).decode())
                voix_k.setdefault(k, {})[langue] = len(sons)
        # Chaque réplique nomme la voix de sa langue quand son personnage en a deux ici.
        audios = {k: dict(v, **{l: v.get(l, next(iter(v.values()))) for _k, l in dites if _k == k})
                  for k, v in voix_k.items()}
        image_paroles = attribuer_repliques(image_paroles, sujets, garder_noms=not refs, objets=objets,
                                            audios=audios if refs else None)
        ambiance = attribuer_repliques(ambiance, sujets, garder_noms=not refs, objets=objets,
                                       audios=audios if refs else None)
        # « holding the <Subject 3> » : la balise est le nom, sans article (guide MiniMax ;
        # remarque du propriétaire, 30/09).
        image_paroles, ambiance = (_SANS_ARTICLE.sub(r"\1", t) for t in (image_paroles, ambiance))
    # La piste son du lieu (fiche du décor, 03/10) part aussi en <Audio j> (05/10, propriétaire : « le fond
    # sonore devrait être dans les références », puis « ok fais 1 + 2 ») : chaque clip H3 réinventait son
    # ambiance. Guide de MiniMax : « The copied ambience layer from <Audio N> continues throughout the
    # target video » ; une suite la prend en simple référence. Seulement s'il reste une place de son.
    # Allumé par défaut (propriétaire, 05/10 : « allume decor_son par défaut ») ; `decor_son: false` l'éteint.
    son_lieu = None
    if refs and fiches and payload.get("decor") and payload.get("decor_son") is not False \
            and len(sons) < VOIX_PAR_PLAN:
        piste = fiche_son_lieu(payload["decor"])
        if piste:
            sons.append(base64.b64encode(piste).decode())
            son_lieu = len(sons)
            # Une suite (raccord, ou tronçon : `suite_latent`) prend la piste en référence, pas en copie.
            suite_son = payload.get("suite_video") or payload.get("suite_latent")
            ambiance = ((AMBIANCE_REFERENCE if suite_son else AMBIANCE_COPIEE) % son_lieu
                        + " " + " ".join(str(ambiance or "").split())).strip()
    images_clefs = mode in ("texte", "premiere", "premiere_derniere")
    if images_clefs and " ".join(str(image_paroles or "").split()):
        # Ce que montrent la première et la dernière image, quand le Studio les a créées : leur
        # description (améliorations comprises) passe aussi à H3, pour que le texte et l'image
        # disent la même scène (demande du propriétaire, 28/09) ; en ancre de [Shot 1] (04/10).
        bords = {"premiere": ("premiere",), "premiere_derniere": ("premiere", "derniere")}.get(mode, ())
        image_paroles = description_aux_images(
            image_paroles, payload.get("description_premiere") if "premiere" in bords else "",
            payload.get("description_derniere") if "derniere" in bords else "")
        # Les noms deviennent les étiquettes ; « shown in <Picture 1> » pour qui est sur l'image de
        # départ, sauf ceux que le tableau des éléments met hors champ au début.
        elements = payload.get("elements") if isinstance(payload.get("elements"), list) else []
        absents = {_norme_replique(str(e.get("nom") or "")) for e in elements
                   if isinstance(e, dict) and hors_champ(e.get("debut"))}
        # Et seulement ceux que le premier plan nomme : film 5 relancé, 04/10, Pixel, absent de l'image
        # de départ, était « shown in <Picture 1> » au plan 3 ; H3 lui a fait un visage d'écran noir.
        premier = _PLAN_SUIVANT.split(image_paroles, 1)[0]
        ancrees = {f["id"] for f in fiches if _norme_replique(f["nom"]) not in absents
                   and re.search(r"(?<![\w<])" + re.escape(f["nom"]) + r"(?!\w)", premier)} if bords else set()
        image_paroles = noms_en_etiquettes(image_paroles, fiches, ancrees)
        ambiance = noms_en_etiquettes(ambiance, fiches)
    texte = invite(image_paroles, ambiance, payload.get("musique", ""), langue, "(S1)",
                   # Rubriques du mode références, dans l'ordre de la consigne de MiniMax
                   # (skills/h3-prompt-writing/SKILL.md).
                   CHAMP_SONS if images_clefs or (refs and fiches) else "Sound: ",
                   champ=CHAMP_DESCRIPTION if images_clefs else "",
                   separateur=SEPARATEUR_CHAMPS if images_clefs or (refs and fiches) else " ")
    if not texte:
        raise ValueError("Décrivez au moins ce qu'on voit (première case).")
    # Image de départ ET photos des fiches (29/09, visage réinventé dans un plan parti
    # d'une image seule ; demande du propriétaire : « fais le ») : le nœud Références
    # n'a pas d'entrée first_frame, l'image part donc en dernière <Picture N>, désignée
    # comme le guide de MiniMax l'écrit (ref-en.txt, 2.2).
    depart = payload.get("depart_reference") if refs and fiches else None
    suite = bool(payload.get("suite_video")) and refs and bool(fiches)
    # Le décor du scénario part aussi à H3 (03/10, propriétaire : « corrige la fontaine qui
    # change entre les plans ») : sa vue vide en <Picture N>, juste avant l'image de départ.
    # Seulement s'il reste une place parmi les neuf images ; sinon le plan part sans.
    lieu = None
    if refs and fiches and payload.get("decor") and payload.get("decor_video") is True:
        utilisees = len(de_la_fiche) + len(payload.get("images") or []) + (1 if depart else 0)
        if utilisees < MODES["references"]["images_max"]:
            lieu = fiche_lieu_image(payload["decor"])
    if refs and fiches:
        # Le plan ne nomme pas toujours toutes les fiches du scénario : « (appears in
        # [Shot 1]) » n'est écrit que pour celles qu'il nomme (ref-en.txt, 4.1).
        nommes = image_paroles + " " + ambiance
        presents = {k for k in range(len(nombres)) if f"<Subject {k + 1}>" in nommes}
        parleurs = {}
        for s, x in _LOCUTEUR_NUMERO.findall(nommes):
            parleurs.setdefault(int(s) - 1, int(x))
        numero_lieu = sum(nombres) + 1 if lieu else None
        numero = sum(nombres) + 1 + (1 if lieu else 0) if depart else None
        # Qui l'image de départ montre : les fiches que le plan nomme, sauf celles que son
        # tableau d'éléments met hors champ au début (même règle que fiches_au_depart).
        elements = payload.get("elements") if isinstance(payload.get("elements"), list) else []
        absents = {_norme_replique(str(e.get("nom") or "")) for e in elements
                   if isinstance(e, dict) and hors_champ(e.get("debut"))}
        au_depart = {k for k in presents if _norme_replique(fiches[k]["nom"]) not in absents}
        texte = (sujets_des_fiches(nombres, avec_tenue, ecrites_k, objets, voix_k, presents, numero, parleurs,
                                   suite, au_depart, avec_planche,
                                   {k for k, f in enumerate(fiches) if f.get("vues")},
                                   legere=payload.get("invite_legere") is True, lieu=numero_lieu,
                                   nb_plans=len(_MULTIPLAN.findall(texte)) or 1,
                                   etiquettes={k: f["etiquette_h3"] for k, f in enumerate(fiches)
                                               if f.get("etiquette_h3")}, son_lieu=son_lieu,
                                   son_lieu_suite=bool(payload.get("suite_latent")))
                 # En mode Références, le style est dit AVANT [Shot 1], en une phrase (ref-en.txt, 5.2 :
                 # « Established in one or two English sentences before [Shot 1] » ; après [Shot 1],
                 # c'est la règle des autres modes, appliquée ici par erreur le 04/10). Un texte en
                 # plans porte déjà ses [Shot N] : pas un second [Shot 1] devant.
                 + TITRE_DESCRIPTION_REFERENCES + STYLE_REFERENCES + "\n"
                 + ("" if _MULTIPLAN.search(texte) else "[Shot 1] ")
                 + (f"The shot begins from <Picture {numero}>. " if numero else "")
                 + (SUITE_DEBUT if suite else "") + texte)
    try:
        longueur = int(payload.get("longueur") or LONGUEUR_PAR_DEFAUT)
    except (TypeError, ValueError) as exc:
        raise ValueError("Durée illisible.") from exc
    if longueur not in LONGUEURS:
        raise ValueError("Durée hors de la grille du modèle.")
    consigne = consigne_images(mode, len(_MULTIPLAN.findall(texte)), longueur / IMAGES_PAR_SECONDE)
    if consigne:
        texte = consigne + SEPARATEUR_CHAMPS + texte
    if len(texte) > INVITE_MAX:
        raise ValueError("Invite trop longue : %d caractères, %s au plus. Raccourcissez le texte du plan."
                         % (len(texte), f"{INVITE_MAX:,}".replace(",", " ")))
    try:
        coupe = float(payload.get("coupe_s") or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("Coupe du début illisible.") from exc
    if coupe not in COUPES:
        raise ValueError("Coupe du début non proposée.")
    definition = str(payload.get("definition") or DEFINITION_PAR_DEFAUT)
    if definition not in DEFINITIONS:
        raise ValueError("Définition non proposée.")
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
    brutes = de_la_fiche + brutes + ([lieu] if lieu else []) + ([depart] if depart else [])
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
        "graphe": graphe(mode, texte, longueur, graine, len(brutes), definition, len(sons)),
        "classes": [m["noeud"]],
        "images": images,
        "sons": {f"voix_{j}.wav": s for j, s in enumerate(sons)},
        "fichiers": list(fichiers_du_mode(mode)),
        "base_poids": POINT_DE_MONTAGE,
        "comfy": DOSSIER_COMFY,
        "comfy_version": COMFY_VERSION,
        "coupe_s": coupe,
        "delai_s": max(60, DUREE_MAX_S - 120),
        "longueur": longueur,
        "graine": graine,
    }
    if depart:
        epingler_depart(demande, len(brutes) - 1)
    return {
        "demande": demande,
        "resume_public": {
            "moteur": "MiniMax H3 (ComfyUI " + COMFY_VERSION + ")",
            "mode": mode,
            "mode_titre": m["titre"],
            "invite": texte,
            "langue": langue,
            "fiche": {"id": fiches[0]["id"], "nom": fiches[0]["nom"]} if fiches else None,
            "fiches": [{"id": f["id"], "nom": f["nom"]} for f in fiches],
            "decor_video": bool(lieu),   # la vue du décor est partie à H3 (03/10)
            "decor_son": bool(son_lieu),   # la piste son du lieu aussi (05/10)
            "images": longueur,
            "secondes": secondes_de(longueur),
            "coupe_s": coupe,
            "graine": graine,
            "taille": "%dx%d" % DEFINITIONS[definition],
            "carte": GPU,
            # Les durées ont été mesurées en 480p seulement.
            "prix_estime_usd": prix_estime(longueur) if definition == DEFINITION_PAR_DEFAUT else None,
            "cout_max_usd": pire_cas(),
        },
    }


def voie_prolonger(precedent: dict) -> str:
    """« troncon » si l'option est mise ET que le clip a gardé son latent ; sinon « image »."""
    v = precedent.get("video") or {}
    return "troncon" if motion_context_actif() and v.get("latent_vers") else "image"


def controler_suite(payload: dict) -> dict:
    """Le contrôle d'avant le premier sou d'une « suite » en Références : l'invite telle que le
    tournage la fabriquera (`preparer_prolonger`, voie « raccord ») — texte passé par
    `texte_de_suite`, en-tête SUITE_DEBUT et lignes <Video 1>. Bug du 02/10, film 4, plan 6 :
    le contrôle mesurait le texte nu, accepté ; au tournage, 4 015 caractères, refusé après
    tous les contrôles."""
    return preparer(dict(payload, mode="references", images=[], suite_video=True, depart_reference=None,
                         image_paroles=texte_de_suite(payload.get("image_paroles", ""), payload.get("elements"))))


def preparer_prolonger(payload: dict, precedent: dict, derniere_b64: Optional[str] = None,
                       graine_hasard=None, fin_b64: Optional[str] = None) -> dict:
    """Le plan qui suit un clip H3 réussi. Mêmes contrôles que `preparer` ;
    la page envoie les trois cases de la suite, la durée et la graine. `fin_b64` :
    les RACCORD_IMAGES dernières images du précédent, son compris (mp4), épinglées
    au début d'une suite en « Références » (voie « raccord »)."""
    v = precedent.get("video") or {}
    if not str(v.get("moteur", "")).startswith("MiniMax H3"):
        raise ValueError("Seul un clip H3 se prolonge ici.")
    if precedent.get("status") != "succeeded":
        raise ValueError("Ce clip n'est pas réussi : rien à prolonger.")
    plans = int(v.get("chaine") or v.get("plans") or 1)   # `chaine` : un plan de scénario (01/10)
    if plans >= PLANS_MAX:
        raise ValueError(f"Cette chaîne a déjà {PLANS_MAX} plans : au-delà, l'image se dégrade. "
                         "Repartez d'une image.")
    voie = voie_prolonger(precedent)
    base = dict(payload, coupe_s=0, image_paroles=texte_de_suite(payload.get("image_paroles", ""),
                                                                 payload.get("elements")))
    if voie == "troncon":
        # Les fiches restent dans le clip enchaîné (propriétaire, 05/10 : « tu n'as pas conservé les
        # images de référence des personnages dans les clips ») : Références sans première image, le
        # début vient du latent ; sans fiche, ou trop de photos, le texte seul comme avant.
        ids = base.get("fiches") or ([base["fiche"]] if base.get("fiche") else [])
        nb, visages_seuls = photos_avec_depart(ids) if ids else (0, False)
        if 0 < nb < MODES["references"]["images_max"]:
            # `suite_latent` : la piste du lieu y part en référence, pas en copie (relecture du 05/10).
            plan = preparer(dict(base, mode="references", images=[], visages_seuls=visages_seuls,
                                 suite_latent=True), graine_hasard)
            d = plan["demande"]
            brancher_troncon(d["graphe"], v["latent_vers"])
            d["classes"] = list(d["classes"]) + list(NOEUDS_TRONCON)
        else:
            plan = preparer(dict(base, mode="texte", images=[]), graine_hasard)
            d = plan["demande"]
            d["graphe"] = graphe_troncon(plan["resume_public"]["invite"], d["longueur"], d["graine"],
                                         v["latent_vers"])
            d["classes"] = [MODES["texte"]["noeud"], *NOEUDS_TRONCON]
        d["contexte"] = v["latent_vers"]
    else:
        if not derniere_b64:
            raise ValueError("La dernière image du clip est illisible.")
        # La suite garde ses fiches (30/09, question du propriétaire : « you do not
        # respect h3 rules to express character and dedicated object ? ») : mode
        # Références, la dernière image en « <Picture N> is the first frame », chaque
        # personne par son visage de face au moins, chaque objet par ses photos, les voix.
        # Sans fiche, ou trop de photos même réduites : la dernière image seule, comme avant.
        ids = base.get("fiches") or ([base["fiche"]] if base.get("fiche") else [])
        nb, visages_seuls = photos_avec_depart(ids) if ids else (0, False)
        if 0 < nb < MODES["references"]["images_max"]:
            if fin_b64:
                base["longueur"] = longueur_avec_raccord(base.get("longueur") or LONGUEUR_PAR_DEFAUT)
            # Avec le raccord, <Video 1> remplace la dernière image en <Picture N> : la
            # vraie première image est celle du raccord, 22 images plus tôt.
            depart = {"suite_video": True} if fin_b64 else {"depart_reference": derniere_b64}
            plan = preparer(dict(base, mode="references", images=[], visages_seuls=visages_seuls, **depart),
                            graine_hasard)
            if fin_b64:
                ajouter_raccord(plan["demande"], fin_b64)
                voie = "raccord"
        else:
            plan = preparer(dict(base, mode="premiere", images=[derniere_b64], fiche=None, fiches=None,
                                 langues=None), graine_hasard)
    plan["demande"]["mode"] = "prolonger"
    plan["resume_public"].update({
        "mode": "prolonger",
        "mode_titre": "Prolonger " + {"troncon": "par tronçon", "raccord": "par les %d dernières images"
                                      % RACCORD_IMAGES}.get(voie, "par la dernière image"),
        "voie": voie, "precedent": str(precedent.get("id", "")), "plans": plans + 1,
    })
    return plan


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

def phrase_d_echec(stderr: str, maison: bool = False) -> str:
    s = str(stderr or "")
    if "POIDS_ABSENTS" in s and maison:
        return ("Les poids de H3 ne sont pas tous dans le dossier des poids de cet ordinateur "
                "(" + s.split("POIDS_ABSENTS", 1)[1].strip()[:300] + ").")
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
    if "CONTEXTE_ABSENT" in s:
        return ("La fin du clip précédent n'est plus sur le disque Modal : prolongez-le par "
                "la dernière image (option « tronçon » éteinte), ou repartez d'une image.")
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
if D.get("contexte") and not Path(D["contexte"]).is_file():
    print("CONTEXTE_ABSENT " + D["contexte"], file=sys.stderr)
    sys.exit(10)
if D.get("contexte"):
    # Le nœud Motion-Context ne lit un latent que sous le dossier de sortie de
    # ComfyUI (« path must stay inside the ComfyUI output folder », jalon 0 du
    # 05/10) : le latent gardé sur le disque y est copié, le graphe pointe la copie.
    entree = Path("/tmp/sortie/contexte_entree") / Path(D["contexte"]).name
    entree.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(D["contexte"], entree)
    for n in D["graphe"].values():
        if n.get("class_type") == "MiniMaxH3MotionContextLoadLatent":
            n["inputs"]["latent_path"] = str(entree)

Path("/tmp/chemins.yaml").write_text(
    "h3:\n  base_path: " + str(BASE) + "\n  diffusion_models: diffusion_models\n"
    "  text_encoders: text_encoders\n  vae: vae\n  loras: loras\n")
(COMFY / "input").mkdir(exist_ok=True)
for nom, b64 in {**D["images"], **(D.get("sons") or {}), **(D.get("videos") or {})}.items():
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
latent_garde = False
if D.get("latent_vers"):
    # Le latent reste sur le disque Modal pour le plan suivant. Son absence
    # n'annule pas le clip : on ne pourra le prolonger que par la dernière image.
    latents = sorted(Path("/tmp/sortie/h3_context").glob("clip_*.safetensors"))
    if latents:
        Path(D["latent_vers"]).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(latents[-1], D["latent_vers"])
        subprocess.run(["sync"], check=False)
        latent_garde = True
    else:
        print("LATENT_NON_GARDE", file=sys.stderr)
(OUT / "resume.json").write_text(json.dumps({
    "moteur": "MiniMax H3, ComfyUI " + D["comfy_version"], "mode": D["mode"],
    "images": D["longueur"], "graine": D["graine"], "coupe_s": D["coupe_s"],
    "latent_garde": latent_garde,
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
    return _emballer(_SCRIPT_POIDS, {"fichiers": list(FICHIERS + FICHIERS_REFERENCES), "depot": HF,
                                     "revision": HF_REVISION,
                                     "base_poids": POINT_DE_MONTAGE})


# Le téléchargement : 52 Go sur processeur. Délai large, carte aucune.
POIDS_DUREE_MAX_S = int(os.getenv("H3_POIDS_TIMEOUT_SECONDS", "3600"))
POIDS_MEMOIRE_MB = 4096
POIDS_COEURS = 2.0


def pire_cas_poids() -> float:
    return round(budget_modal.prix_seconde(None, POIDS_MEMOIRE_MB, POIDS_COEURS) * POIDS_DUREE_MAX_S, 3)


# --- La page -----------------------------------------------------------------------

def aide_marques(cible: str) -> str:
    """Le menu « Langue et émotion d'une réplique » (30/09), fait depuis EMOTIONS : la page,
    le Studio et le chat du Studio lisent la même liste."""
    lignes = "".join("<tr><td>[%s]</td><td>%s</td></tr>" % (nom, html.escape(ton))
                     for nom, ton in EMOTIONS.values())
    options_l = '<option value="">— langue —</option>' + "".join(
        '<option value="%s">%s</option>' % (nom, nom) for nom in LANGUES_PAROLES.values())
    options_e = '<option value="">— émotion —</option>' + "".join(
        '<option value="%s">%s</option>' % (nom, nom) for nom, _ton in EMOTIONS.values())
    return ('<details class="note marques" data-cible="%s"><summary>Langue et émotion d\'une réplique</summary>'
            "<p>En tête d'une réplique, entre crochets, sa <b>langue</b> et/ou son <b>émotion</b> : "
            "« [anglais, joie] I made the team! », « [tristesse] Elle n'est pas venue… ». C'est <b>H3</b> qui "
            "joue l'émotion : le Studio lui écrit le ton ci-dessous à côté de la réplique, et lui envoie la voix "
            "du personnage dans la langue de la réplique. Sans marque, la réplique garde la langue du "
            "personnage et un ton neutre ; une émotion écrite en toutes lettres (« folle de joie, elle "
            "crie… ») est lue aussi. Le chat du Studio pose ces marques quand il découpe un scénario.</p>"
            "<p>Placez le curseur juste après « , puis : <select class=\"marque_langue\">%s</select> "
            "<select class=\"marque_emotion\">%s</select> <button type=\"button\" class=\"marque_inserer\">"
            "Insérer la marque</button></p>"
            "<table><tr><th>marque</th><th>ton demandé à H3</th></tr>%s</table></details>"
            % (cible, options_l, options_e, lignes))


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
  .occupe { background: #eef4ff; border-left: 4px solid #2b5fd9; padding: .5rem .7rem; font-weight: 600; }
  .rond { display: inline-block; width: .8rem; height: .8rem; border: 2px solid #2b5fd9; border-top-color: transparent;
          border-radius: 50%; animation: tourne 1s linear infinite; vertical-align: -1px; }
  @keyframes tourne { to { transform: rotate(360deg); } }
  button { font: inherit; padding: 8px 16px; margin-top: 12px; cursor: pointer; }
  video { width: 100%; margin-top: 10px; background: #000; }
  .image_bord { border-top: 1px solid #eee; margin-top: 12px; padding-top: 8px; }
  .image_bord label { font-weight: normal; }
  .apercu { display: block; max-width: 100%; margin-top: 8px; border: 1px solid #ccc; }
  .grille { display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: 10px; margin-top: 8px; }
  .grille img { display: block; width: 100%; border: 1px solid #ccc; margin: 4px 0; }
  .grille button { margin: 4px 4px 0 0; padding: 4px 10px; }
  .clip { display: flex; gap: 10px; align-items: flex-start; border-top: 1px solid #eee; padding: 8px 0; }
  .clip video { width: 200px; flex: none; margin: 0; }
  .clip button { margin: 0 4px 0 0; padding: 2px 10px; }
  .clip .note { flex: 1; overflow-wrap: anywhere; }
  pre { white-space: pre-wrap; font-size: .8rem; max-height: 240px; overflow: auto; background: #f3f3f3; padding: 8px; }
  [hidden] { display: none !important; }
  .barre { position: sticky; top: 0; z-index: 5; background: #fafafa; display: flex; flex-wrap: wrap; gap: 8px 14px;
           align-items: center; padding: 8px 0; border-bottom: 1px solid #ddd; }
  .barre h1 { margin: 0; font-size: 1.2rem; }
  .barre select { width: auto; flex: 1; min-width: 200px; font-weight: 600; }
  .barre a { text-decoration: none; }
  #banniere { font-size: .9rem; padding: 6px 10px; }
  details { margin-top: 10px; }
  details > summary { cursor: pointer; font-weight: 600; }
  details.plie { border-top: 1px solid #eee; padding-top: 8px; }
</style>
</head>
<body>
<nav class="barre">
  <a href="http://localhost:8000/studio">← Studio</a>
  <h1>🎞️ Vidéo H3</h1>
  <select id="section_choix" aria-label="Partie de la page">
    <option value="clip">🎬 Fabriquer un clip</option>
    <option value="casting">👤 Personnages (fiches de casting)</option>
    <option value="montage_bloc">🎥 Scénario et film</option>
    <option value="musique_bloc">🎵 Musique sous un film</option>
    <option value="reglages">⚙️ Licence et poids</option>
  </select>
  <span id="barre_alerte" class="refus" hidden></span>
</nav>

<div class="bloc" id="banniere">Lecture du budget…</div>
<div class="bloc" id="ou_bloc"><b>Où calculer les plans.</b> <span id="ou_choix">Lecture…</span>
  <p class="note" id="ou_note"></p></div>

<div class="section" id="reglages">
<p class="note">MiniMax H3 fabrique l'image <b>et</b> le son d'un clip, sur une machine louée chez Modal
(A100). Moteur : ComfyUI, lancé à part sur la machine louée.</p>
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
</div>

<div class="bloc section" id="casting">
  <b>Fiches de casting</b>
  <span class="note">un personnage, un objet ou une pose des mains décrit une fois, retrouvé d'un plan à
  l'autre (mode « Références ») : son nom dans le texte d'un plan le désigne.</span>
  <label for="fiche_choix">Fiche</label>
  <select id="fiche_choix"><option value="">Nouvelle fiche…</option></select>
  <label for="fiche_genre">Ce que décrit la fiche</label>
  <select id="fiche_genre">
    <option value="personne">Un personnage (quatre angles)</option>
    <option value="objet">Un objet, le même dans tout le film (une photo)</option>
    <option value="pose">Une pose des mains, pour un geste précis (une photo)</option>
    <option value="decor">Un décor, le lieu du film (une vue d'ensemble, sans personne)</option>
  </select>
  <label for="fiche_nom">Nom (celui qu'écrit le scénario : « Leila », « the basketball »)</label>
  <input type="text" id="fiche_nom" maxlength="60">
  <label for="fiche_description" id="fiche_description_titre">Description (âge, visage, coiffure, tenue)</label>
  <textarea id="fiche_description" maxlength="800"></textarea>
  <button id="fiche_creer">Créer la fiche et ses images</button>
  <button id="fiche_supprimer" hidden>Supprimer la fiche</button>
  <p class="note" id="fiche_etat"></p>
  <div id="fiche_images" class="grille"></div>
  <div id="fiche_planche"></div>
  <div id="fiche_voix"></div>
  <p class="note">Les images sont faites par l'image du Studio (clé Google, gratuite) : d'abord le
  portrait de face, d'après la description, puis les autres angles à partir de lui, pour garder le même
  visage. Rejouez ou supprimez celles qui ne vont pas.</p>
</div>

<div class="bloc section" id="clip">
  <label for="mode">Mode</label>
  <select id="mode"></select>
  <p class="note" id="mode_note"></p>
  <label for="image_paroles">1. Image et paroles (les paroles entre « guillemets »)</label>
  <textarea id="image_paroles">Une femme en manteau rouge marche sous la pluie à Paris, la nuit ; elle se retourne et dit : « On y est presque. »</textarea>
  <label for="langue">Langue des paroles</label>
  <select id="langue">__LANGUES__</select>
  <details class="note"><summary>Conseils pour les paroles</summary>
  Une réplique dans une autre langue la dit en tête : « Bonjour ! » puis
  « [anglais] Nice to meet you! » — même personnage, même voix (sa voix anglaise, si sa fiche en a une).
  Pour des paroles nettes : une seule personne parle, visage vers la caméra, une seule action par plan,
  et pas plus de 2 mots par seconde (une dizaine pour 5 s). Les textes sont des exemples : modifiez-les librement.
  </details>
  __AIDE_MARQUES_image_paroles__
  <details class="plie"><summary>2. Ambiance sonore et 3. musique</summary>
  <label for="ambiance">2. Ambiance sonore</label>
  <textarea id="ambiance">Pluie, circulation au loin.</textarea>
  <label for="musique">3. Musique (vide : aucune musique)</label>
  <textarea id="musique"></textarea>
  <p class="note">Case musique vide, le Studio demande au modèle
  de n'en mettre aucune : sinon il en ajoute une de lui-même.</p>
  </details>
  <label>Caméra</label>
  <div id="camera_clip"></div>

  <div class="image_bord" id="bord_premiere" hidden>
    <b>Première image</b>
    <label><input type="radio" name="source_premiere" value="creer" checked> La créer avec l'image du Studio (clé Google, gratuite)</label>
    <label><input type="radio" name="source_premiere" value="televerser"> La téléverser</label>
    <div class="creer">
      <label for="invite_premiere">Description de l'image (préremplie d'après la case 1, modifiable)</label>
      <textarea id="invite_premiere"></textarea>
      <span class="note">Personnages sur l'image (toutes les photos de leur fiche sont jointes) :</span>
      <div id="personnages_premiere"></div>
      <button id="creer_premiere">Créer l'image</button>
    </div>
    <div class="televerser" hidden><input type="file" id="fichier_premiere" accept="image/png,image/jpeg,image/webp"></div>
    <img id="apercu_premiere" class="apercu" alt="" hidden>
    <p class="note" id="etat_premiere"></p>
    <div id="comparer_premiere" hidden></div>
    <div class="ameliorer" id="ameliorer_bloc_premiere" hidden>
      <label for="amelioration_premiere">Améliorer cette image : dites ce qui doit changer</label>
      <input type="text" id="amelioration_premiere" maxlength="300">
      <button id="ameliorer_premiere">Refaire l'image avec cette amélioration</button>
      <ul id="ameliorations_premiere"></ul>
    </div>
  </div>
  <div class="image_bord" id="bord_derniere" hidden>
    <b>Dernière image</b>
    <label><input type="radio" name="source_derniere" value="creer" checked> La créer avec l'image du Studio (clé Google, gratuite)</label>
    <label><input type="radio" name="source_derniere" value="televerser"> La téléverser</label>
    <div class="creer">
      <label for="invite_derniere">Description de l'image (préremplie d'après la case 1, modifiable)</label>
      <textarea id="invite_derniere"></textarea>
      <span class="note">Personnages sur l'image (toutes les photos de leur fiche sont jointes) :</span>
      <div id="personnages_derniere"></div>
      <button id="creer_derniere">Créer l'image</button>
    </div>
    <div class="televerser" hidden><input type="file" id="fichier_derniere" accept="image/png,image/jpeg,image/webp"></div>
    <img id="apercu_derniere" class="apercu" alt="" hidden>
    <p class="note" id="etat_derniere"></p>
    <div id="comparer_derniere" hidden></div>
    <div class="ameliorer" id="ameliorer_bloc_derniere" hidden>
      <label for="amelioration_derniere">Améliorer cette image : dites ce qui doit changer</label>
      <input type="text" id="amelioration_derniere" maxlength="300">
      <button id="ameliorer_derniere">Refaire l'image avec cette amélioration</button>
      <ul id="ameliorations_derniere"></ul>
    </div>
  </div>
  <div id="references_bloc" hidden>
    <label for="fiche_ref">Personnage (fiche de casting)</label>
    <select id="fiche_ref"><option value="">Aucun : images téléversées seulement</option></select>
    <label for="images">Images de référence (en plus de la fiche, facultatif ; 9 au plus en tout)</label>
    <input type="file" id="images" accept="image/png,image/jpeg,image/webp" multiple>
  </div>

  <label for="longueur">Durée</label>
  <select id="longueur"></select>
  <p class="note" id="prix"></p>

  <details class="plie"><summary>Réglages avancés : définition, coupe du début, graine</summary>
  <label for="definition">Définition de l'image</label>
  <select id="definition">
    <option value="480p">480p (832 × 480), celle des prix mesurés</option>
    <option value="768p">768p (1344 × 768), plus nette, plus longue à calculer, prix non mesuré</option>
  </select>

  <label for="coupe">Couper le début</label>
  <select id="coupe">
    <option value="0">Ne rien couper</option>
    <option value="0.25">0,25 s</option>
    <option value="0.5">0,5 s</option>
  </select>
  <label for="graine">Graine (vide = au hasard ; la même graine refait le même tirage)</label>
  <input type="number" id="graine" min="0" step="1">
  </details>

  <button id="lancer">Fabriquer le clip</button>
  <p id="statut" class="note"></p>
  <div id="resultat" hidden>
    <video id="lecteur" controls playsinline></video>
    <p><a id="telecharger" href="#">Enregistrer le clip</a></p>
    <div id="clip_agrandir" class="agrandir"></div>
    <div id="clip_visages" class="agrandir"></div>
    <p class="note" id="fiche"></p>
    <button id="juger_clip">Faire juger ce clip (gratuit : images et répliques)</button>
    <p class="note" id="jugement_clip"></p>
    <div id="prolonger_bloc" hidden>
      <p class="note" id="prolonger_note"></p>
      <button id="prolonger">Prolonger ce clip</button>
    </div>
  </div>
  <pre id="journal" hidden></pre>
</div>

<div class="bloc section" id="montage_bloc">
  <label for="scenario">Scénario (le récit : découpé en plans pour un tournage neuf, ou pour ranger des clips déjà faits)</label>
  <textarea id="scenario" maxlength="2000"></textarea>
  __AIDE_MARQUES_scenario__
  <!-- Hors des parties repliables : le 29/09, replié avec le montage, le film tourné ne se voyait plus. -->
  <div id="montage_resultat" hidden>
    <b>🎬 Le film</b>
    <video id="montage_lecteur" controls playsinline></video>
    <p><a id="montage_telecharger" href="#">Enregistrer le film</a></p>
    <div id="montage_agrandir" class="agrandir"></div>
    <div id="montage_visages" class="agrandir"></div>
    <div id="montage_finaliser" class="agrandir"></div>
  </div>
  <details class="plie" open><summary>Tourner un scénario neuf</summary>
    <span class="note">le scénario, découpé en plans par le chat du Studio, puis tourné plan par plan
    (chaque plan se paie comme un clip : durée, graine, langue et musique sont celles de « Fabriquer un clip »).</span>
    <label for="scenario_fiche">Personnage (fiche de casting) et sa langue</label>
    <select id="scenario_fiche"><option value="">Choisissez une fiche…</option></select>
    <select id="scenario_langue1">__LANGUES__</select>
    <label for="scenario_fiche2">Second personnage (facultatif) et sa langue</label>
    <select id="scenario_fiche2"><option value="">Aucun</option></select>
    <select id="scenario_langue2">__LANGUES__</select>
    <span class="note">Objets et poses des mains du scénario (facultatif) :</span>
    <div id="scenario_objets"></div>
    <label for="scenario_decor">Décor du film (facultatif) : chaque coupe en garde le lieu et change de cadrage</label>
    <select id="scenario_decor"><option value="">Aucun</option></select>
    <label><input type="checkbox" id="scenario_plan_par_plan"> Plan par plan : le film s'arrête après chaque
    plan neuf pour que vous le validiez ; « Rejouer » reprend les plans faits sans rien louer</label>
    <label><input type="checkbox" id="scenario_invite_legere"> Invite courte (à l'essai) : chaque consigne
    dite une seule fois au modèle vidéo</label>
    <span class="note">Nommez le personnage qui parle dans la phrase de sa réplique : le Studio lui attribue
    la réplique et sa langue.</span>
    <label for="scenario_chanson">Musique de fond (une chanson du Studio, posée après le tournage)</label>
    <select id="scenario_chanson"><option value="">Aucune (musique décrite au clip)</option></select>
    <label for="scenario_musique_plan">à partir du plan</label>
    <input id="scenario_musique_plan" type="number" min="1" max="6" value="1">
    <button id="scenario_decouper">Découper en plans</button>
    <div id="plans_liste"></div>
    <button id="plan_ajouter" hidden>Ajouter un plan</button>
    <p class="note" id="scenario_prix"></p>
    <button id="scenario_scinder" hidden>Couper les plans à plusieurs répliques, une par plan (gratuit)</button>
    <button id="scenario_verifier" hidden>Vérifier les règles (gratuit)</button>
    <button id="scenario_tourner" hidden>Tourner le scénario</button>
    <button id="scenario_forcer" hidden>Tourner quand même</button>
    <div id="scenario_regles"></div>
    <button id="scenario_arreter" hidden>Arrêter le tournage</button>
    <p id="scenario_occupe" class="occupe" hidden><span class="rond"></span> <span id="scenario_occupe_texte"></span>
      <span id="scenario_chrono"></span></p>
    <p class="note" id="scenario_etat"></p>
  </details>
  <details class="plie" open><summary>Reprendre un scénario déjà tourné</summary>
    <label for="scenario_choix">Scénario</label>
    <select id="scenario_choix"><option value="">Choisissez un scénario…</option></select>
    <div id="scenario_suite" hidden>
      <label for="suite_action">Que faire ?</label>
      <select id="suite_action">
        <option value="auto">Corriger tout seul, avec pause avant de payer</option>
        <option value="juger">Faire juger les plans (gratuit)</option>
        <option value="corriger">Corriger le texte d'après mes remarques (gratuit)</option>
        <option value="rejouer">Rejouer les plans changés ou cochés (payant)</option>
        <option value="decor">Faire la fiche du décor d'après ce film (gratuit) : les coupes du rejeu en gardent le lieu</option>
        <option value="fond">Régler le fond sonore, plan par plan (gratuit)</option>
      </select>
      <div id="suite_auto_options">
        <select id="auto_tours"><option value="1">1 tour</option><option value="2" selected>2 tours au plus</option>
          <option value="3">3 tours au plus</option></select>
        <label><input type="checkbox" id="auto_sans_arret"> sans pause (chaque fausse alerte fait payer un plan)</label>
      </div>
      <div id="suite_fond_options" hidden>
        <p class="note">Le fond (eau, rue…) est déjà nivelé sur tout le film. Si un plan reste trop fort ou
          trop faible à l'écoute : montez ou baissez-le ici, en dB (de -12 à +12 ; 0 = le niveau commun).</p>
        <div id="fond_plans"></div>
      </div>
      <div id="suite_corriger_options" hidden>
        <label for="retours">Vos remarques</label>
        <textarea id="retours" maxlength="2000"></textarea>
      </div>
      <button id="suite_lancer">Lancer</button>
      <button id="rejouer_forcer" hidden>Rejouer quand même (payant)</button>
      <div id="jugement"></div>
      <div id="suite_pause" hidden>
        <p class="refus">Pause avant de payer : décochez les fausses alertes et relisez le texte en gras.</p>
        <button id="scenario_auto_payer">Rejouer les plans aux défauts cochés (payant)</button>
        <button id="scenario_auto_arreter">Arrêter ici</button>
      </div>
      <details class="note"><summary>Comment ça marche</summary>
        Le juge (Free AI Max, gratuit) compare chaque plan aux fiches et à l'histoire, sur une image toutes les
        0,5 s ; il se trompe parfois. La correction change la façon de montrer, pas l'histoire, et sa continuité est
        contrôlée. Le texte en <b>gras</b> a changé depuis le scénario initial (<s>barré</s> : retiré). Au rejeu,
        seuls les plans changés ou cochés sont tournés et payés, les autres sont repris, la musique est reposée.
      </details>
    </div>
  </details>
  <details class="plie"><summary>Monter des clips déjà faits</summary>
    <span class="note">rien n'est tourné de nouveau, rien n'est loué.</span>
    <p class="note">Cochez les clips du film. Rangez-les avec ↑ ↓, ou demandez l'ordre au chat du Studio
    d'après le scénario ; puis assemblez. Les clips sont recollés bout à bout, son compris, sans rien couper.</p>
    <div id="clips_liste"></div>
    <button id="scenario_ordonner">Ranger selon le scénario</button>
    <button id="montage_lancer">Assembler le film</button>
    <p class="note" id="montage_etat"></p>
  </details>
  <div id="films_hd_bloc" hidden>
    <b>Films en haute définition</b>
    <span class="note">les films finalisés et les clips agrandis (4K, 1080p) de ce Studio.</span>
    <div id="films_hd_liste"></div>
    <video id="films_hd_lecteur" controls hidden style="width:100%"></video>
  </div>
</div>

<div class="bloc section" id="musique_bloc">
    <b>Poser une musique sous un film</b>
    <span class="note">une chanson du Studio (page Chanson) sous le son du film, du début choisi à la fin, avec
    un decrescendo final ; rien n'est loué.</span>
    <label for="musique_film">Film</label>
    <select id="musique_film"></select>
    <label for="musique_chanson">Musique</label>
    <select id="musique_chanson"></select>
    <label><input id="musique_sous_paroles" type="checkbox" checked> Baisser la musique quand on parle</label>
    <details class="plie"><summary>Réglages : début, volume, point de départ dans la chanson, fondu</summary>
    <label for="musique_debut">Début de la musique (secondes)</label>
    <input id="musique_debut" type="number" min="0" step="0.01" value="0">
    <label for="musique_volume">Volume (de 0,05 à 1)</label>
    <input id="musique_volume" type="number" min="0.05" max="1" step="0.05" value="0.3">
    <label for="musique_depart">Prendre la chanson à partir de (secondes dans la chanson)</label>
    <input id="musique_depart" type="number" min="0" step="0.1" value="0">
    <span class="note">par exemple là où le chant commence, pour sauter une longue introduction.</span>
    <label for="musique_fondu">Fondu d'entrée (secondes)</label>
    <input id="musique_fondu" type="number" min="0" max="5" step="0.1" value="0.3">
    </details>
    <button id="musique_poser">Poser la musique</button>
    <button id="sous_titrer">Sous-titrer ce film en français</button>
    <span class="note">les répliques sont écoutées, traduites en français (chat gratuit du Studio) et écrites
    dans l'image ; rien n'est loué. Sous-titrez avant de poser la musique : elle gênerait l'écoute.</span>
    <p class="note" id="musique_etat"></p>
    <div id="musique_resultat" hidden>
      <video id="musique_lecteur" controls playsinline></video>
      <p><a id="musique_telecharger" href="#">Enregistrer le film en musique</a></p>
    </div>
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

// Première et dernière image : créées par l'image du Studio ou téléversées,
// puis recadrées à la taille du clip (sans déformation), ici, dans la page.
const IMAGES = {premiere: null, derniere: null};
const RETOUCHEE = {premiere: false, derniere: false};
const PREFIXE = {
  premiere: "Photo réaliste, cadrage paysage 16:9, image nette, début de la scène : ",
  derniere: "Photo réaliste, cadrage paysage 16:9, image nette, même personnage et même décor, fin de la scène : "};

function sansParoles(t){
  // La description de l'image n'a que faire des répliques entre guillemets.
  // Le verbe qui annonçait la réplique part avec elle (« … et dit : »).
  return t.replace(/«[^»]*»/g, "").replace(/"[^"]*"/g, "")
    .replace(/\s*(?:,\s*)?(?:\bet\s+)?\b(?:dit|demande|crie|murmure|chuchote|répond)\s*:\s*/gi, " ")
    .replace(/\s+/g, " ").replace(/\s+([,.])/g, "$1").replace(/[\s,;:]+$/, "").trim();
}

// L'image de départ est l'instant 0 du plan : le cadre, puis l'état « debut » de chaque
// élément du tableau. Mesuré le 30/09 (deux films, 28 images) : depuis le texte entier du
// plan, 6 images sur 14 montraient deux fois une personne ou un objet (l'action entière
// dessinée d'un coup) ; depuis l'état « debut », 0 sur 14.
// La même règle que le serveur (video_h3.hors_champ), sur la même liste.
const HORS_CHAMP = __HORS_CHAMP__;
function horsChamp(etat){
  const t = " " + String(etat || "").toLowerCase().replace(/[^\p{L}\p{N}_]+/gu, " ").trim() + " ";
  return HORS_CHAMP.some(h => t.includes(" " + h + " "));
}

function texteDepart(p){
  const presents = (p.elements || []).filter(e => e && e.nom && e.debut && !horsChamp(e.debut));
  if (!presents.length) return PREFIXE.premiere + sansParoles(p.image_paroles);
  return PREFIXE.premiere + cadreDuDepart(sansParoles(p.image_paroles), presents.map(e => e.nom)) + ". "
    + presents.map(e => e.nom + " : " + e.debut + ".").join(" ");
}

// Comme cadre_du_depart (le Studio) : la première phrase avant « : » (l'action vient après, 03/10),
// puis le lieu qui précède le premier élément s'il n'est nommé que plus loin (film 5, 04/10).
function cadreDuDepart(texte, noms){
  const premiere = texte.split(".")[0];
  let cadre = premiere.split(":")[0].trim();
  const echapper = s => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const positions = noms.filter(Boolean).map(n => texte.search(new RegExp("(?<![\\w])" + echapper(n) + "(?![\\w])", "i")))
    .filter(i => i >= 0);
  if (positions.length && Math.min(...positions) > premiere.length){
    const lieu = texte.slice(premiere.length + 1, Math.min(...positions)).split(":")[0].trim()
      .replace(/[\s,;.:]+(?:and|with|while|as)?\s*$/i, "").trim();
    if (lieu) cadre += ". " + lieu;
  }
  return cadre;
}

function majInvitesImages(){
  const base = sansParoles(document.getElementById("image_paroles").value);
  for (const nom of ["premiere", "derniere"]){
    if (!RETOUCHEE[nom]) document.getElementById("invite_" + nom).value = PREFIXE[nom] + base;
  }
}

function tailleChoisie(){
  const t = ETAT.definitions[document.getElementById("definition").value];
  return [t.largeur, t.hauteur];
}

function recadrer(src){
  return new Promise((ok, ko) => {
    const im = new Image();
    im.onload = () => {
      const [L, Ht] = tailleChoisie();
      const c = document.createElement("canvas");
      c.width = L; c.height = Ht;
      const s = Math.max(L / im.width, Ht / im.height);
      const w = im.width * s, h = im.height * s;
      c.getContext("2d").drawImage(im, (L - w) / 2, (Ht - h) / 2, w, h);
      ok(c.toDataURL("image/png"));
    };
    im.onerror = () => ko(new Error("image illisible"));
    im.src = src;
  });
}

function poserImage(nom, src){
  return recadrer(src).then(png => {
    IMAGES[nom] = png;
    const a = document.getElementById("apercu_" + nom);
    a.src = png;
    a.hidden = false;
    const [L, Ht] = tailleChoisie();
    document.getElementById("etat_" + nom).textContent = "Image prête, recadrée en " + L + " × " + Ht + ".";
    const zone = document.getElementById("comparer_" + nom);
    zone.innerHTML = "";
    zone.append(blocComparer(FICHES.map(f => f.id), "/video-h3/visage/comparer", {image: png}));
    zone.hidden = false;
  });
}

// Le visage d'une image à côté des photos d'une fiche, et l'avis du modèle qui
// voit (28/09) : pour toute image, tout mode, tout personnage.
function blocComparer(ids, adresse, corps){
  const zone = document.createElement("div");
  const sortie = document.createElement("div");
  for (const fid of ids){
    const f = FICHES.find(x => x.id === fid) || {};
    if (f.angles && !f.angles.length) continue;
    zone.append(bouton("Comparer au visage de « " + (f.nom || "la fiche") + " »", async () => {
      sortie.textContent = "Comparaison du visage (quelques secondes)…";
      const r = await fetch(adresse, {method: "POST", headers: H,
        body: JSON.stringify(Object.assign({fiche: fid}, corps))});
      const d = await r.json();
      sortie.innerHTML = "";
      if (!r.ok){ sortie.textContent = typeof d.detail === "string" ? d.detail : "Refusé."; return; }
      const img = document.createElement("img");
      img.className = "apercu";
      img.src = d.planche;
      img.alt = "Photos de la fiche, puis le visage de l'image";
      const avis = document.createElement("p");
      avis.className = "note";
      avis.textContent = "Avis du Studio — ressemblance " + (d.ressemblance || "?") + (d.ecarts ? " : " + d.ecarts : ".");
      sortie.append(img, avis);
    }));
  }
  zone.append(sortie);
  return zone;
}

function brancherBord(nom){
  for (const r of document.querySelectorAll('input[name="source_' + nom + '"]')){
    r.addEventListener("change", () => {
      const creer = document.querySelector('input[name="source_' + nom + '"]:checked').value === "creer";
      const bord = document.getElementById("bord_" + nom);
      bord.querySelector(".creer").hidden = !creer;
      bord.querySelector(".televerser").hidden = creer;
    });
  }
  document.getElementById("invite_" + nom).addEventListener("input", () => { RETOUCHEE[nom] = true; });
  document.getElementById("fichier_" + nom).addEventListener("change", async (e) => {
    const f = e.target.files[0];
    if (!f) return;
    await poserImage(nom, await lireFichier(f));
    // Une image téléversée n'a pas de description connue : rien n'est joint à H3.
    DESCRIPTION[nom] = "";
    document.getElementById("ameliorer_bloc_" + nom).hidden = true;
  });
  document.getElementById("creer_" + nom).addEventListener("click", () => creerImage(nom));
  document.getElementById("ameliorer_" + nom).addEventListener("click", async () => {
    const champ = document.getElementById("amelioration_" + nom);
    const voeu = champ.value.trim();
    if (!voeu) return;
    AMELIORATIONS[nom].push(voeu);
    if (await creerImage(nom)) champ.value = "";
    else AMELIORATIONS[nom].pop();
    listerAmeliorations(nom);
  });
}

// Le client fait refaire l'image en disant ce qui doit changer, jusqu'à la valider
// (demande du propriétaire, 28/09). Ses demandes s'ajoutent à la description ;
// le texte ainsi obtenu est aussi joint à la requête à H3.
const AMELIORATIONS = {premiere: [], derniere: []};
const DESCRIPTION = {premiere: "", derniere: ""};

function fichesCochees(nom){
  return Array.from(document.querySelectorAll("#personnages_" + nom + " input:checked")).map(c => c.value);
}

async function creerImage(nom){
  const etat = document.getElementById("etat_" + nom);
  etat.className = "note";
  etat.textContent = "Création de l'image (quelques secondes)…";
  const r = await fetch("/video-h3/image", {method: "POST", headers: H,
    body: JSON.stringify({texte: document.getElementById("invite_" + nom).value,
                          ameliorations: AMELIORATIONS[nom], fiches: fichesCochees(nom)})});
  const d = await r.json();
  if (!r.ok){ etat.className = "refus"; etat.textContent = d.detail || "Refusé."; return false; }
  await poserImage(nom, d.image);
  DESCRIPTION[nom] = d.texte;
  document.getElementById("ameliorer_bloc_" + nom).hidden = false;
  return true;
}

function listerAmeliorations(nom){
  const ul = document.getElementById("ameliorations_" + nom);
  ul.textContent = "";
  AMELIORATIONS[nom].forEach((a, i) => {
    const li = document.createElement("li");
    li.textContent = a + " ";
    const x = document.createElement("button");
    x.textContent = "retirer";
    x.title = "Retirée de la prochaine image";
    x.addEventListener("click", () => { AMELIORATIONS[nom].splice(i, 1); listerAmeliorations(nom); });
    li.appendChild(x);
    ul.appendChild(li);
  });
}

function majMode(){
  const cle = document.getElementById("mode").value;
  const m = ETAT.modes[cle];
  document.getElementById("mode_note").textContent = m.note + " Essayé le " + dateFr(m.essaye_le) + ".";
  document.getElementById("bord_premiere").hidden = !(cle === "premiere" || cle === "premiere_derniere");
  document.getElementById("bord_derniere").hidden = cle !== "premiere_derniere";
  document.getElementById("references_bloc").hidden = cle !== "references";
}

function majPrix(){
  const n = Number(document.getElementById("longueur").value);
  const d = ETAT.durees.find(x => x.images === n);
  const pire = "Au pire (la machine va jusqu'au bout de son délai) : " + fr(ETAT.pire_cas_usd, 2) + " $.";
  document.getElementById("prix").textContent = (d && d.prix_estime_usd !== null)
    ? "Estimé : " + fr(d.prix_estime_usd, 3) + " $, d'après " + fr(ETAT.secondes_mesurees, 0)
      + " s de location mesurées par le Studio le " + dateFr(ETAT.mesure_le)
      + ". Le tout premier clip coûte davantage : il lit les 52 Go de poids sur un disque neuf. " + pire
    : "Durée jamais essayée : pas d'estimation mesurée. " + pire;
  if (OU === "maison"){
    document.getElementById("prix").textContent = "Ici : 0 $, sur la carte de cet ordinateur. Chez Modal, ce serait : "
      + document.getElementById("prix").textContent;
  }
}

function afficherLicence(a){
  const e = document.getElementById("licence_etat");
  document.getElementById("licence_depot").hidden = a.presente;
  e.className = a.presente ? "" : "refus";
  e.textContent = a.presente
    ? "Copie de l'autorisation déposée le " + dateFr(a.deposee_le) + " (autorisation du "
      + dateFr(a.date_autorisation) + "). Les clips sont permis."
    : "Aucune copie d'autorisation sur ce Studio : les clips sont refusés tant qu'elle n'est pas déposée.";
  MANQUE.licence = !a.presente;
  alerteBarre();
}

// Ce qui empêche de tourner, rappelé dans la barre du haut quelle que soit la partie ouverte.
const MANQUE = {licence: false, poids: false};
function alerteBarre(){
  const manque = [];
  if (MANQUE.licence) manque.push("licence à déposer");
  if (MANQUE.poids) manque.push("poids à préparer");
  const b = document.getElementById("barre_alerte");
  b.hidden = !manque.length;
  b.textContent = "⚠ " + manque.join(", ") + " (voir « Licence et poids »)";
  b.style.cursor = "pointer";
}

function afficherPoids(p){
  document.getElementById("poids_etat").textContent = p.prets
    ? "Prêts sur le disque Modal « " + p.volume + " » (depuis le " + dateFr(p.le) + ")."
    : "Pas encore sur le disque Modal « " + p.volume + " ». Une fois pour toutes : environ "
      + ETAT.poids_go + " Go, téléchargés sur processeur (sans carte). Au pire " + fr(ETAT.pire_cas_poids_usd, 2) + " $.";
  document.getElementById("poids_preparer").hidden = p.prets;
  MANQUE.poids = !p.prets;
  alerteBarre();
}

// Où calculer (01/10) : « ici, sans urgence » sur la carte de cet ordinateur, gratuit, en
// file ; ou Modal tout de suite, payant. Sans carte, seul Modal est offert, et la page dit
// pourquoi. Le choix vaut pour un clip, un plan suivant et un scénario.
let OU = "modal";
function chargerOu(){
  return fetch("/video-h3/ou", {headers: H}).then(r => r.json()).then(d => {
    const zone = document.getElementById("ou_choix");
    zone.textContent = "";
    let voulu = null;
    try { voulu = localStorage.getItem("h3_ou"); } catch (e) {}
    OU = d.ici.possible && voulu !== "modal" ? "maison" : "modal";
    const choix = [["maison", "Ici, sans urgence (gratuit, sur la carte de cet ordinateur)", !d.ici.possible],
                   ["modal", "Chez Modal, tout de suite (payant, prix dit avant)", false]];
    for (const [val, texte, coupe] of choix){
      const l = document.createElement("label");
      const r = document.createElement("input");
      r.type = "radio"; r.name = "ou"; r.value = val; r.checked = OU === val; r.disabled = coupe;
      r.addEventListener("change", () => { OU = val; try { localStorage.setItem("h3_ou", val); } catch (e) {} if (ETAT) majPrix(); });
      l.append(r, " " + texte);
      zone.append(l);
    }
    document.getElementById("ou_note").textContent = d.ici.possible
      ? "Ici : le plan attend que la carte soit libre, sans limite de durée, et n'arrête jamais "
        + "ce qui la tient. " + (d.ici.occupation || "") + (d.ici.file ? " " + d.ici.file + " calcul(s) déjà en file." : "")
      : d.ici.motif;
    if (ETAT) majPrix();
  });
}

function rafraichir(){
  chargerOu();
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

// Agrandir un clip ou un film, visages compris (SeedVR2, 30/09) : le prix d'abord,
// puis la location sur un clic. La vidéo d'origine reste telle quelle.
async function blocAgrandir(ou, jid, sid){
  const b = document.getElementById(ou);
  b.textContent = "";
  const r = await fetch("/video-h3/agrandir/prix?job=" + jid, {headers: H});
  if (!r.ok) return;
  const d = await r.json();
  const titre = document.createElement("b");
  titre.textContent = "Agrandir (visages et détails plus nets)";
  b.appendChild(titre);
  const etat = document.createElement("p");
  etat.className = "note";
  for (const e of d.echelles){
    const k = document.createElement("button");
    if (e.refus){
      k.disabled = true;
      k.title = e.refus;
      k.textContent = e.titre + " : trop long";
    } else {
      k.textContent = e.titre + " — ≈ " + fr(e.estime_usd, 2) + " $ (au pire " + fr(e.pire_usd, 2)
        + " $), ≈ " + fr(e.secondes_estimees / 60, 0) + " min";
      k.addEventListener("click", () => lancerAgrandir(b, etat, jid, sid, e.echelle));
    }
    b.appendChild(k);
  }
  b.appendChild(etat);
}

async function lancerAgrandir(b, etat, jid, sid, echelle){
  b.querySelectorAll("button").forEach(k => k.disabled = true);
  etat.textContent = "Location de la machine…";
  const r = await fetch("/video-h3/agrandir", {method: "POST", headers: H,
    body: JSON.stringify({job: jid, echelle: echelle, scenario: sid})});
  const d = await r.json();
  if (!r.ok){
    etat.textContent = typeof d.detail === "string" ? d.detail : "Refusé.";
    b.querySelectorAll("button").forEach(k => k.disabled = !!k.title);
    return;
  }
  const debut = Date.now();
  const suivreAgrandi = async () => {
    const j = await (await fetch("/video/jobs/" + d.id, {headers: H})).json();
    if (j.status === "succeeded" && j.video_url){
      etat.textContent = "Agrandi en " + fr((Date.now() - debut) / 60000, 0) + " min. ";
      const a = document.createElement("a");
      a.href = j.video_url + "&telecharger=1&nom=agrandi-" + echelle;
      a.textContent = "Enregistrer la vidéo agrandie";
      etat.appendChild(a);
      const v = document.createElement("a");
      v.href = j.video_url;
      v.target = "_blank";
      v.textContent = " (la voir)";
      etat.appendChild(v);
      return;
    }
    if (j.status === "failed" || j.status === "cancelled"){
      etat.textContent = "Échec : " + (j.message || "voir le journal du travail " + d.id);
      return;
    }
    etat.textContent = "Agrandissement en cours… " + fr((Date.now() - debut) / 60000, 0) + " min écoulées.";
    setTimeout(suivreAgrandi, 15000);
  };
  suivreAgrandi();
}

// Refaire les visages petits d'un clip ou d'un film (FaceRefine, 30/09) : chaque
// visage est recadré, regénéré par H3 d'après les photos de sa fiche, puis recollé.
// Deux personnages au plus ; le prix d'abord, la location sur un clic.
const PLACES = {left_most: "le plus à gauche", right_most: "le plus à droite", centre_most: "au centre",
  largest_face: "le plus grand visage", largest_face_2: "le 2e plus grand visage",
  smallest_face: "le plus petit visage"};

async function blocVisages(ou, jid, sid){
  const b = document.getElementById(ou);
  b.textContent = "";
  const q = "/video-h3/visages/prix?job=" + jid + (sid ? "&scenario=" + sid : "");
  const r = await fetch(q, {headers: H});
  if (!r.ok) return;
  const d = await r.json();
  if (!d.fiches.length) return;
  const titre = document.createElement("b");
  titre.textContent = "Refaire les visages (petits ou flous)";
  b.appendChild(titre);
  const aide = document.createElement("p");
  aide.className = "note";
  aide.textContent = "Chaque visage est redessiné d'après les photos de sa fiche. Deux personnages au plus ; "
    + "dites où chacun se trouve dans l'image. Le clip d'origine n'est pas touché.";
  b.appendChild(aide);
  const lignes = d.fiches.map((f, i) => {
    const l = document.createElement("div");
    const c = document.createElement("input");
    c.type = "checkbox";
    c.checked = i < 2;
    const nom = document.createElement("span");
    nom.textContent = " " + f.nom + " : ";
    const place = document.createElement("select");
    for (const p of d.choix) place.add(new Option(PLACES[p] || p, p));
    place.value = d.choix[Math.min(i, 1)];
    l.append(c, nom, place);
    b.appendChild(l);
    return {fiche: f.id, c: c, place: place};
  });
  let plan = null;
  if (d.plans.length > 1){
    plan = document.createElement("select");
    plan.add(new Option("toute la vidéo", ""));
    for (const p of d.plans) plan.add(new Option("plan " + p.plan, p.plan));
    plan.value = d.plans[d.plans.length - 1].plan;
    const lp = document.createElement("div");
    lp.append("Passage : ", plan);
    b.appendChild(lp);
  }
  const k = document.createElement("button");
  const etat = document.createElement("p");
  etat.className = "note";
  b.append(k, etat);
  const choisis = () => lignes.filter(x => x.c.checked);
  const majPrixVisages = async () => {
    const n = choisis().length;
    k.disabled = true;
    if (n < 1 || n > 2){
      k.textContent = "Refaire les visages";
      etat.textContent = n ? "Deux personnages au plus par traitement." : "Cochez au moins un personnage.";
      return;
    }
    etat.textContent = "";
    const p = await (await fetch(q + "&sujets=" + n + (plan && plan.value ? "&plan=" + plan.value : ""),
      {headers: H})).json();
    if (p.devis.refus){
      k.textContent = "Refaire les visages : trop long";
      etat.textContent = p.devis.refus;
      return;
    }
    k.disabled = false;
    k.textContent = "Refaire les visages — ≈ " + fr(p.devis.estime_usd, 2) + " $ (au pire "
      + fr(p.devis.pire_usd, 2) + " $), ≈ " + fr(p.devis.secondes_estimees / 60, 0) + " min";
  };
  lignes.forEach(x => { x.c.addEventListener("change", majPrixVisages); });
  if (plan) plan.addEventListener("change", majPrixVisages);
  k.addEventListener("click", () => lancerVisages(b, etat, {job: jid, scenario: d.scenario,
    plan: plan && plan.value ? Number(plan.value) : null,
    sujets: choisis().map(x => ({fiche: x.fiche, choix: x.place.value}))}));
  majPrixVisages();
}

// Finaliser un film validé : visages refaits passage par passage, puis 4K, tout en même
// temps chez Modal (30/09/2026). Le Studio propose les passages (plans, coupes et fondus
// vus dans l'image) avec une vignette : on coche qui est visible dans chacun.
async function blocFinaliser(ou, jid, sid){
  const b = document.getElementById(ou);
  b.textContent = "";
  const titre = document.createElement("b");
  titre.textContent = "Finaliser le film (visages refaits, puis 4K)";
  const ouvrir = document.createElement("button");
  ouvrir.textContent = "Préparer la finalisation (gratuit : découpe et vignettes)";
  b.append(titre, document.createElement("br"), ouvrir);
  ouvrir.addEventListener("click", async () => {
    ouvrir.disabled = true;
    ouvrir.textContent = "Recherche des plans, coupes et fondus…";
    const r = await fetch("/video-h3/finaliser/prix", {method: "POST", headers: H,
      body: JSON.stringify({job: jid, scenario: sid})});
    const d = await r.json();
    if (!r.ok){ ouvrir.textContent = typeof d.detail === "string" ? d.detail : "Refusé."; return; }
    ouvrir.remove();
    dessinerFinaliser(b, jid, d);
  });
}

function dessinerFinaliser(b, jid, d){
  const aide = document.createElement("p");
  aide.className = "note";
  aide.textContent = "Par défaut, la 4K seule. Les visages ne se refont que si vous cochez un personnage "
    + "(machine louée chez Modal) : cochez ceux dont le VISAGE se voit dans le passage (pas de dos), deux au plus : un visage absent "
    + "serait pris sur quelqu'un d'autre. « Fondu » : le Studio a vu un changement de scène à cet endroit.";
  b.appendChild(aide);
  const lignes = d.plans.map((p, i) => {
    const l = document.createElement("div");
    l.className = "passage";
    const img = document.createElement("img");
    img.src = p.vignette;
    img.width = 160;
    const texte = document.createElement("div");
    texte.textContent = "Passage " + (i + 1) + " : " + fr(p.de / 24, 1) + " à " + fr(p.a / 24, 1) + " s"
      + (p.transition ? " (fondu)" : "");
    l.append(img, texte);
    const sujets = d.fiches.map((f, j) => {
      const c = document.createElement("input");
      c.type = "checkbox";
      // 01/10, propriétaire : « la remise en état des visages est inutile en mode automatique ».
      // Cochés d'office, ils partaient chez Modal et fermaient « ici » : rien n'est coché.
      c.checked = false;
      const place = document.createElement("select");
      for (const x of d.choix) place.add(new Option(PLACES[x] || x, x));
      place.value = j === 0 ? "largest_face" : "largest_face_2";
      const s = document.createElement("div");
      s.append(c, " " + f.nom + " : ", place);
      texte.appendChild(s);
      c.addEventListener("change", majPrixFinal);
      return {fiche: f.id, c: c, place: place};
    });
    b.appendChild(l);
    return {de: p.de, a: p.a, sujets: sujets};
  });
  const echelle = document.createElement("select");
  for (const e of d.echelles) echelle.add(new Option("puis " + e.titre, e.echelle));
  echelle.add(new Option("sans agrandissement", ""));
  echelle.value = "4k";
  const k = document.createElement("button");
  const etat = document.createElement("p");
  etat.className = "note";
  const le = document.createElement("div");
  le.append("Agrandissement : ", echelle);
  // Où (01/10) : la 4K seule peut se faire sur la carte d'ici, gratuitement, sans urgence.
  const ou = document.createElement("select");
  ou.add(new Option("chez Modal (payant, tout de suite)", "modal"));
  const ici = new Option("ici, sans urgence (4K seulement, sans visages, gratuit)", "maison");
  ici.disabled = !(d.ici && d.ici.possible);
  if (ici.disabled && d.ici) ici.textContent += " — " + d.ici.motif;
  ou.add(ici);
  const lou = document.createElement("div");
  lou.append("Où : ", ou);
  b.append(le, lou, k, etat);
  const corps = () => ({job: jid, echelle: echelle.value, ou: ou.value, plans: lignes.map(l => ({de: l.de, a: l.a,
    sujets: l.sujets.filter(s => s.c.checked).map(s => ({fiche: s.fiche, choix: s.place.value}))}))});
  async function majPrixFinal(){
    k.disabled = true;
    const p = await (await fetch("/video-h3/finaliser/prix", {method: "POST", headers: H,
      body: JSON.stringify(corps())})).json();
    if (p.devis.refus){ k.textContent = "Finaliser le film"; etat.textContent = p.devis.refus; return; }
    if (p.devis.ici){
      etat.textContent = "Sur la carte de cet ordinateur, en " + p.devis.locations + " fois, environ "
        + fr(p.devis.secondes_estimees / 60, 0) + " min de calcul quand la carte est libre.";
      k.disabled = false;
      k.textContent = "Finaliser le film ici — 0 $";
      return;
    }
    etat.textContent = "Il reste " + fr(p.budget.reste_usd, 2) + " $ ce mois-ci ; ce qui ne tient pas "
      + "attend le mois suivant, sans rien perdre de ce qui est fait.";
    k.disabled = false;
    k.textContent = "Finaliser le film — ≈ " + fr(p.devis.estime_usd, 2) + " $ (au pire "
      + fr(p.devis.pire_usd, 2) + " $)";
  }
  echelle.addEventListener("change", majPrixFinal);
  ou.addEventListener("change", majPrixFinal);
  k.addEventListener("click", async () => {
    b.querySelectorAll("button, input, select").forEach(x => x.disabled = true);
    const r = await fetch("/video-h3/finaliser", {method: "POST", headers: H, body: JSON.stringify(corps())});
    const f = await r.json();
    if (!r.ok){
      etat.textContent = typeof f.detail === "string" ? f.detail : "Refusé.";
      b.querySelectorAll("button, input, select").forEach(x => x.disabled = false);
      return;
    }
    suivreFinalisation(b, etat, f.id);
  });
  majPrixFinal();
}

async function montrerFilm(etat, jid, legende, nom){
  const j = await (await fetch("/video/jobs/" + jid, {headers: H})).json();
  if (!j.video_url) return;
  const t = document.createElement("p");
  t.textContent = legende;
  const v = document.createElement("video");
  v.src = j.video_url;
  v.controls = true;
  v.setAttribute("playsinline", "");
  const a = document.createElement("a");
  a.href = j.video_url + "&telecharger=1&nom=" + nom;
  a.textContent = "Enregistrer";
  etat.append(t, v, a);
}

async function suivreFinalisation(b, etat, fid){
  const debut = Date.now();
  const tour = async () => {
    const j = await (await fetch("/video/jobs/" + fid, {headers: H})).json();
    const f = j.finalisation || {};
    const dits = (j.avertissements || []).map(x => "⚠ " + x).join(" ");
    if (j.status === "succeeded"){
      etat.textContent = "Film finalisé en " + fr((Date.now() - debut) / 60000, 0) + " min. " + dits;
      if (f.film_visages && f.film_visages !== f.film)
        await montrerFilm(etat, f.film_visages, "Visages refaits (480p) :", "film-visages");
      await montrerFilm(etat, f.film, "Film finalisé :", "film-final");
      return;
    }
    if (j.status === "attente" || j.status === "failed"){
      etat.textContent = (j.status === "attente" ? "" : "Échec : ") + (j.message || "") + " " + dits;
      if (f.film_visages) await montrerFilm(etat, f.film_visages, "Déjà fait — visages refaits (480p) :",
                                            "film-visages");
      const reprendre = document.createElement("button");
      reprendre.textContent = "Reprendre là où elle s'est arrêtée";
      reprendre.addEventListener("click", async () => {
        const r = await fetch("/video-h3/finaliser/" + fid + "/reprendre", {method: "POST", headers: H});
        const d = await r.json();
        if (!r.ok){ etat.append(" " + (typeof d.detail === "string" ? d.detail : "Refusé.")); return; }
        suivreFinalisation(b, etat, fid);
      });
      etat.appendChild(reprendre);
      return;
    }
    etat.textContent = (f.etape || "En file") + "… " + fr((Date.now() - debut) / 60000, 0) + " min écoulées.";
    setTimeout(tour, 15000);
  };
  tour();
}

async function lancerVisages(b, etat, corps){
  b.querySelectorAll("button, input, select").forEach(k => k.disabled = true);
  etat.textContent = "Location de la machine…";
  const r = await fetch("/video-h3/visages", {method: "POST", headers: H, body: JSON.stringify(corps)});
  const d = await r.json();
  if (!r.ok){
    etat.textContent = typeof d.detail === "string" ? d.detail : "Refusé.";
    b.querySelectorAll("button, input, select").forEach(k => k.disabled = false);
    return;
  }
  const debut = Date.now();
  const suivreVisages = async () => {
    const j = await (await fetch("/video/jobs/" + d.id, {headers: H})).json();
    if (j.status === "succeeded" && j.video_url){
      etat.textContent = "Visages refaits en " + fr((Date.now() - debut) / 60000, 0) + " min. "
        + (j.avertissements || []).map(x => "⚠ " + x + " ").join("");
      const v = document.createElement("video");
      v.src = j.video_url;
      v.controls = true;
      v.setAttribute("playsinline", "");
      etat.appendChild(v);
      const a = document.createElement("a");
      a.href = j.video_url + "&telecharger=1&nom=visages";
      a.textContent = "Enregistrer la vidéo aux visages refaits";
      etat.appendChild(a);
      return;
    }
    if (j.status === "failed" || j.status === "cancelled"){
      etat.textContent = "Échec : " + (j.message || j.error || "voir le journal du travail " + d.id);
      return;
    }
    etat.textContent = "Visages en cours… " + fr((Date.now() - debut) / 60000, 0) + " min écoulées.";
    setTimeout(suivreVisages, 15000);
  };
  suivreVisages();
}

function suivre(jid){
  fetch("/video/jobs/" + jid, {headers: H}).then(r => r.json()).then(j => {
    const st = document.getElementById("statut");
    if (j.status === "succeeded" && j.video_url){
      st.textContent = "Clip prêt.";
      document.getElementById("resultat").hidden = false;
      document.getElementById("lecteur").src = j.video_url;
      document.getElementById("telecharger").href = j.video_url + "&telecharger=1&nom=clip-h3";
      if (CLIP_COURANT !== jid){ blocAgrandir("clip_agrandir", jid, ""); blocVisages("clip_visages", jid, ""); }
      const r = j.resume || {};
      const v = j.video || {};
      document.getElementById("fiche").textContent = "Graine " + r.graine + " ; " + fr(r.calcul_s, 0)
        + " s de calcul, " + fr(r.total_s, 0)
        + (j.fournisseur === "maison" ? " s en tout, sur la carte de cet ordinateur (0 $)." : " s de location.")
        + (v.plans ? " Chaîne de " + v.plans + " plans, " + fr(v.secondes, 1) + " s en tout." : "");
      majProlonger(jid, v, r);
      if (CLIP_COURANT !== jid) document.getElementById("jugement_clip").textContent = "";
      CLIP_COURANT = jid;
      rafraichir();
      chargerClips();
      return;
    }
    if (j.etape === "recollage"){
      st.textContent = "Plan rendu ; le Studio le recolle au clip précédent…";
      setTimeout(() => suivre(jid), 3000);
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
    if (j.status === "cancelled"){
      st.textContent = "Arrêté. " + (j.arret_detail || "");
      return;
    }
    st.textContent = j.attente_carte
      ? "En file pour la carte de cet ordinateur" + (j.file_position ? " (n° " + j.file_position + ")" : "")
        + " : " + (j.attente_motif || "") + " Le plan part dès qu'elle est libre ; rien n'est payé."
      : j.fournisseur === "maison"
        ? "En cours sur la carte de cet ordinateur… environ 4 min pour 5 s en 768p."
        : "En cours (" + j.status + ")… Le premier clip construit aussi la machine : plusieurs minutes.";
    setTimeout(() => suivre(jid), j.attente_carte ? 10000 : 4000);
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

// Prolonger : le clip affiché devient le début de la chaîne. Les trois cases,
// la durée et la graine décrivent le plan suivant.
let PRECEDENT = null;

function majProlonger(jid, v, r){
  const bloc = document.getElementById("prolonger_bloc");
  const plans = v.plans || 1, max = ETAT.prolonger.plans_max;
  PRECEDENT = jid;
  bloc.hidden = false;
  const btn = document.getElementById("prolonger");
  btn.disabled = plans >= max;
  const troncon = ETAT.prolonger.par_troncon && v.latent_vers && r.latent_garde;
  document.getElementById("prolonger_note").textContent = plans >= max
    ? "Cette chaîne a " + plans + " plans, le maximum : au-delà, l'image se dégrade. Repartez d'une image."
    : "Plan " + plans + " sur " + max + ". Réécrivez les trois cases pour la suite, puis prolongez. "
      + (troncon
        ? "Par tronçon : le plan suivant reprend 22 images et 1 s de son de celui-ci."
        : "Par la dernière image : le plan suivant part de la dernière image de celui-ci ; "
          + "le mouvement et le son ne sont pas repris à la jointure.")
      + " Même prix qu'un clip.";
}

document.getElementById("prolonger").addEventListener("click", async () => {
  const st = document.getElementById("statut");
  st.className = "note";
  document.getElementById("journal").hidden = true;
  const graine = document.getElementById("graine").value;
  const r = await fetch("/video-h3/prolonger", {method: "POST", headers: H, body: JSON.stringify({
    precedent: PRECEDENT,
    image_paroles: document.getElementById("image_paroles").value,
    ambiance: document.getElementById("ambiance").value,
    musique: document.getElementById("musique").value,
    langue: document.getElementById("langue").value,
    longueur: Number(document.getElementById("longueur").value),
    definition: document.getElementById("definition").value,
    camera: CAMERA_CLIP, ou: OU,
    graine: graine === "" ? null : Number(graine)})});
  const d = await r.json();
  if (!r.ok){ alerteTexte(typeof d.detail === "string" ? d.detail : "Refusé."); return; }
  document.getElementById("resultat").hidden = true;
  st.textContent = "Plan suivant lancé.";
  suivre(d.id);
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
  const images = [];
  if (m === "references"){
    for (const f of Array.from(document.getElementById("images").files)){ images.push(await lireFichier(f)); }
  } else {
    const noms = m === "premiere" ? ["premiere"] : m === "premiere_derniere" ? ["premiere", "derniere"] : [];
    for (const nom of noms){
      if (!IMAGES[nom]){
        alerteTexte("Il manque la " + (nom === "premiere" ? "première" : "dernière")
          + " image : créez-la ou téléversez-la.");
        return;
      }
      images.push(IMAGES[nom]);
    }
  }
  const graine = document.getElementById("graine").value;
  const r = await fetch("/video-h3/creer", {method: "POST", headers: H, body: JSON.stringify({
    mode: m, images: images,
    description_premiere: m === "references" ? "" : DESCRIPTION.premiere,
    description_derniere: m === "premiere_derniere" ? DESCRIPTION.derniere : "",
    fiches_image: m === "references" ? [] : fichesCochees("premiere"),
    image_paroles: document.getElementById("image_paroles").value,
    ambiance: document.getElementById("ambiance").value,
    musique: document.getElementById("musique").value,
    langue: document.getElementById("langue").value,
    fiche: m === "references" ? (document.getElementById("fiche_ref").value || null) : null,
    longueur: Number(document.getElementById("longueur").value),
    definition: document.getElementById("definition").value,
    coupe_s: Number(document.getElementById("coupe").value),
    camera: CAMERA_CLIP, ou: OU,
    graine: graine === "" ? null : Number(graine)})});
  const d = await r.json();
  if (!r.ok){ alerteTexte(typeof d.detail === "string" ? d.detail : "Refusé."); return; }
  st.textContent = "Lancé.";
  suivre(d.id);
});

// Fiches de casting (PLAN 18.9) : le Studio fabrique les images angle par angle ;
// chacune se rejoue ou se supprime.
let FICHES = [], ANGLES = {};
const GENRES = {objet: "objet", pose: "pose des mains", decor: "décor"};
const DESCRIPTIONS_GENRE = {personne: "Description (âge, visage, coiffure, tenue)",
  objet: "Description (forme, couleur, matière ; sans marque)",
  pose: "Description (ce que fait chaque main et ses doigts)",
  decor: "Description (le lieu : bâtiments, sol, éléments fixes, lumière)"};

function genreFiche(){ return document.getElementById("fiche_genre").value; }

document.getElementById("fiche_genre").addEventListener("change", () => {
  document.getElementById("fiche_description_titre").textContent = DESCRIPTIONS_GENRE[genreFiche()];
});

function objetsDuScenario(){
  return [...document.querySelectorAll("#scenario_objets input:checked")].map(c => c.value);
}

function ficheEtat(t, refus){
  const e = document.getElementById("fiche_etat");
  e.className = refus ? "refus" : "note";
  e.textContent = t || "";
}

// Le juge du Studio sur le clip seul : sa planche, et l'écoute de ses répliques (28/09).
let CLIP_COURANT = null;

function texteParoles(p){
  if (!p) return "";
  if (p.erreur) return "Écoute : " + p.erreur;
  if (p.doute) return "Écoute : « " + (p.entendu || "rien") + " », réplique entendue en partie : à vérifier à l'oreille.";
  if (p.ok === null) return "Écoute : aucune réplique attendue.";
  return "Écoute : « " + (p.entendu || "rien") + " »" + (p.ok ? ", réplique bien dite." : ", réplique manquante.");
}

document.getElementById("juger_clip").addEventListener("click", async () => {
  const zone = document.getElementById("jugement_clip");
  if (!CLIP_COURANT) return;
  zone.className = "note";
  zone.style.whiteSpace = "pre-line";
  zone.textContent = "Le juge du Studio regarde et écoute le clip (gratuit)…";
  const r = await fetch("/video-h3/jobs/" + CLIP_COURANT + "/juger", {method: "POST", headers: H, body: "{}"});
  const d = await r.json();
  if (!r.ok){ zone.className = "refus"; zone.textContent = typeof d.detail === "string" ? d.detail : "Refusé."; return; }
  zone.className = d.verdict === "ok" ? "note" : "refus";
  zone.textContent = ["Verdict du juge : " + (d.verdict === "ok" ? "ok." : "défaut.")]
    .concat(d.defauts.map(x => "À " + fr(x.t_s, 1) + " s : " + x.quoi), [texteParoles(d.paroles)])
    .filter(Boolean).join("\n");
});

function bouton(texte, action){
  const b = document.createElement("button");
  b.type = "button";
  b.textContent = texte;
  b.addEventListener("click", action);
  return b;
}

async function chargerFiches(choisir){
  const r = await fetch("/video-h3/fiches", {headers: H});
  if (!r.ok) return;
  const d = await r.json();
  FICHES = d.fiches;
  ANGLES = d.angles;
  const choix = document.getElementById("fiche_choix");
  const ref = document.getElementById("fiche_ref");
  let garde = choisir !== undefined ? choisir : choix.value;
  const gardeRef = ref.value;
  if (!FICHES.some(f => f.id === garde)) garde = "";
  choix.innerHTML = '<option value="">Nouvelle fiche…</option>';
  ref.innerHTML = '<option value="">Aucun : images téléversées seulement</option>';
  for (const f of FICHES){
    const n = f.angles.length;
    for (const sel of [choix, ref]){
      const o = document.createElement("option");
      o.value = f.id;
      // Les tenues gardées sur la fiche (29/09), reprises par chaque film qui les joue.
      o.textContent = f.nom + (GENRES[f.genre] ? " · " + GENRES[f.genre] : "")
        + " (" + n + " image" + (n > 1 ? "s" : "") + ")"
        + ((f.tenues || []).length ? " · tenues : " + f.tenues.join(", ") : "");
      sel.appendChild(o);
    }
  }
  choix.value = garde;
  ref.value = FICHES.some(f => f.id === gardeRef) ? gardeRef : "";
  for (const nom of ["premiere", "derniere"]){
    const zone = document.getElementById("personnages_" + nom);
    const coches = new Set(fichesCochees(nom));
    zone.innerHTML = "";
    for (const f of FICHES){
      if (!f.angles.length) continue;
      const c = document.createElement("input");
      c.type = "checkbox";
      c.value = f.id;
      c.checked = coches.has(f.id);
      const l = document.createElement("label");
      l.append(c, " " + f.nom + " ");
      zone.appendChild(l);
    }
  }
  for (const [idSel, vide] of [["scenario_fiche", "Choisissez une fiche…"], ["scenario_fiche2", "Aucun"]]){
    const sf = document.getElementById(idSel);
    const gardeSf = sf.value;
    sf.innerHTML = "";
    const v = document.createElement("option");
    v.value = "";
    v.textContent = vide;
    sf.appendChild(v);
    for (const f of FICHES.filter(x => x.angles.length && x.genre === "personne")){
      const o = document.createElement("option");
      o.value = f.id;
      o.textContent = f.nom;
      sf.appendChild(o);
    }
    sf.value = FICHES.some(f => f.id === gardeSf) ? gardeSf : "";
  }
  // Objets et poses (29/09) : jamais de réplique, donc ni langue ni place de personnage.
  const zoneObjets = document.getElementById("scenario_objets");
  const objetsCoches = new Set(objetsDuScenario());
  zoneObjets.innerHTML = "";
  // Un décor ne part pas à H3 (02/10) : il se choisit comme décor du scénario.
  const objets = FICHES.filter(x => x.angles.length && x.genre !== "personne" && x.genre !== "decor");
  for (const f of objets){
    const c = document.createElement("input");
    c.type = "checkbox";
    c.value = f.id;
    c.checked = objetsCoches.has(f.id);
    const l = document.createElement("label");
    l.append(c, " " + f.nom + " (" + GENRES[f.genre] + ") ");
    zoneObjets.appendChild(l);
  }
  if (!objets.length) zoneObjets.textContent = "aucun : créez une fiche « objet » ou « pose » plus haut.";
  // Le décor (02/10) : une fiche « décor », jointe à l'image de départ de chaque coupe.
  const sd = document.getElementById("scenario_decor"), gardeSd = sd.value;
  sd.innerHTML = '<option value="">Aucun</option>';
  for (const f of FICHES.filter(x => x.angles.length && x.genre === "decor")){
    const o = document.createElement("option");
    o.value = f.id;
    o.textContent = f.nom;
    sd.appendChild(o);
  }
  sd.value = FICHES.some(f => f.id === gardeSd) ? gardeSd : "";
  await montrerFiche();
}

async function montrerFiche(){
  const id = document.getElementById("fiche_choix").value;
  document.getElementById("fiche_images").innerHTML = "";
  document.getElementById("fiche_planche").innerHTML = "";
  document.getElementById("fiche_voix").innerHTML = "";
  document.getElementById("fiche_supprimer").hidden = !id;
  document.getElementById("fiche_creer").hidden = !!id;
  for (const champ of ["fiche_nom", "fiche_description"]){
    document.getElementById(champ).disabled = !!id;
    if (!id) document.getElementById(champ).value = "";
  }
  document.getElementById("fiche_genre").disabled = !!id;
  if (!id) return;
  const r = await fetch("/video-h3/fiches/" + id, {headers: H});
  const f = await r.json();
  if (!r.ok){ ficheEtat(f.detail, true); return; }
  document.getElementById("fiche_genre").value = f.genre || "personne";
  document.getElementById("fiche_description_titre").textContent = DESCRIPTIONS_GENRE[f.genre || "personne"];
  document.getElementById("fiche_nom").value = f.nom;
  document.getElementById("fiche_description").value = f.description;
  dessinerFiche(f);
}

function dessinerFiche(f){
  const grille = document.getElementById("fiche_images");
  grille.innerHTML = "";
  // Un objet ou une pose : une seule photo, sa vue de face (29/09).
  const personne = (f.genre || "personne") === "personne";
  const angles = personne ? Object.entries(ANGLES) : [["face", "Photo"]];
  for (const [angle, titre] of angles){
    const cas = document.createElement("div");
    const t = document.createElement("b");
    t.textContent = titre;
    cas.appendChild(t);
    if (f.images[angle]){
      const img = document.createElement("img");
      img.src = f.images[angle];
      img.alt = titre;
      cas.appendChild(img);
    }
    cas.appendChild(bouton(f.images[angle] ? "Rejouer" : "Créer", () => faireImage(f.id, angle)));
    if (f.images[angle]) cas.appendChild(bouton("Supprimer", () => retirerImage(f.id, angle)));
    // Une vraie photo de la personne ; le visage petit ne donne pas la ressemblance (28/09).
    const fichier = document.createElement("input");
    fichier.type = "file";
    fichier.accept = "image/png,image/jpeg,image/webp";
    fichier.setAttribute("aria-label", "Photo « " + titre + " »");
    const recadrer = document.createElement("input");
    recadrer.type = "checkbox";
    recadrer.checked = angle !== "pied";
    const coche = document.createElement("label");
    coche.append(recadrer, " recadrer sur le visage");
    if (!personne) recadrer.checked = false;
    fichier.addEventListener("change", () => {
      const f0 = fichier.files[0];
      if (!f0) return;
      const lecteur = new FileReader();
      lecteur.onload = () => poserPhoto(f.id, angle, lecteur.result, recadrer.checked);
      lecteur.readAsDataURL(f0);
    });
    cas.append(document.createElement("br"), "Ou une photo : ", fichier);
    if (personne) cas.appendChild(coche);
    grille.appendChild(cas);
  }
  if (personne) dessinerPlanche(f);
  document.getElementById("fiche_voix").innerHTML = "";
  if (personne) dessinerVoix(f);
}

// Le menu « Langue et émotion d'une réplique » (30/09) : insère la marque au curseur.
document.addEventListener("click", ev => {
  const b = ev.target.closest(".marque_inserer");
  if (!b) return;
  const d = b.closest("details");
  const t = document.getElementById(d.dataset.cible);
  const m = [d.querySelector(".marque_langue").value, d.querySelector(".marque_emotion").value].filter(Boolean).join(", ");
  if (!t || !m) return;
  const p = typeof t.selectionStart === "number" ? t.selectionStart : t.value.length;
  t.value = t.value.slice(0, p) + "[" + m + "] " + t.value.slice(p);
  t.focus();
  t.selectionStart = t.selectionEnd = p + m.length + 3;
});

// Le profil voix du personnage (29/09) : un exemple à cloner, ou une voix générée
// dans sa langue ; il part avec ses photos dans chaque plan en mode « Références ».
function dessinerVoix(f){
  const zone = document.getElementById("fiche_voix");
  const t = document.createElement("b");
  t.textContent = "Voix du personnage";
  const note = document.createElement("p");
  note.className = "note";
  note.textContent = "La même voix dans tous les plans où le personnage part avec sa fiche : H3 en reprend le "
    + "timbre, jamais les mots. De 3 à 15 s de parole claire, une seule personne, sans musique. "
    + "La voix générée est celle du Studio pour la langue choisie : deux personnages de même langue "
    + "auront alors le même timbre.";
  zone.append(t, note);
  if (f.voix){
    const lecteur = document.createElement("audio");
    lecteur.controls = true;
    lecteur.src = f.voix.son;
    zone.append(lecteur, document.createElement("br"),
      (f.voix.source === "generee" ? "Voix générée" : "Exemple cloné") + ", " + fr(f.voix.duree_s, 1) + " s, "
        + (f.voix.langue ? "en " + (([...document.getElementById("langue").options].find(o => o.value === f.voix.langue) || {}).textContent || f.voix.langue) + ". "
           : "langue non notée : reposez la voix pour pouvoir tourner. "),
      bouton("Retirer la voix", async () => {
        const r = await fetch("/video-h3/fiches/" + f.id + "/voix", {method: "DELETE", headers: H});
        if (r.ok) await chargerFiches(f.id);
      }), document.createElement("br"));
  }
  // La même voix dans l'autre langue (30/09) : Leila en anglais, l'Américain en français.
  if (f.voix && f.voix.langue){
    const nomLangue = v => (([...document.getElementById("langue").options].find(o => o.value === v) || {}).textContent || v);
    for (const [l, v] of Object.entries(f.voix_langues || {})){
      const lecteur = document.createElement("audio");
      lecteur.controls = true;
      lecteur.src = v.son;
      const ecoute = v.ecoute && v.ecoute.part != null ? " Le Studio y entend " + Math.round(100 * v.ecoute.part) + " % de la phrase." : "";
      zone.append(document.createElement("br"), "Sa voix en " + nomLangue(l) + " : ", lecteur, document.createElement("br"),
        "même timbre, clonée par FireRedTTS3 depuis sa voix en " + nomLangue(v.depuis) + ", " + fr(v.duree_s, 1) + " s." + ecoute + " ",
        bouton("Retirer", async () => {
          const r = await fetch("/video-h3/fiches/" + f.id + "/voix/langue/" + l, {method: "DELETE", headers: H});
          if (r.ok) await chargerFiches(f.id);
        }), document.createElement("br"));
    }
    for (const l of ["French", "English"]){
      if (l === f.voix.langue || (f.voix_langues || {})[l]) continue;
      zone.append(document.createElement("br"),
        bouton("Créer sa voix en " + nomLangue(l), () => voixLangue(f.id, l)),
        " même timbre, dite en " + nomLangue(l) + " (FireRedTTS3 sur Modal, quelques centimes, 1 à 5 min). "
        + "L'accent de sa langue d'origine reste en partie.", document.createElement("br"));
    }
  }
  const fichier = document.createElement("input");
  fichier.type = "file";
  fichier.accept = "audio/*,video/*";
  fichier.setAttribute("aria-label", "Exemple de voix à cloner");
  const droit = document.createElement("input");
  droit.type = "checkbox";
  const coche = document.createElement("label");
  coche.append(droit, " j'ai le droit d'utiliser cette voix (la mienne, ou celle d'une personne d'accord)");
  fichier.addEventListener("change", () => {
    const f0 = fichier.files[0];
    if (!f0) return;
    if (!droit.checked){ ficheEtat("Cochez d'abord « j'ai le droit d'utiliser cette voix ».", true); fichier.value = ""; return; }
    const lecteur = new FileReader();
    lecteur.onload = () => poserVoix(f.id, {son: lecteur.result, droit: true, langue: parle.value});
    lecteur.readAsDataURL(f0);
  });
  const langue = document.createElement("select");
  langue.setAttribute("aria-label", "Langue de la voix générée");
  for (const [v, titre] of [["French", "français"], ["English", "anglais"]]){
    const o = document.createElement("option");
    o.value = v;
    o.textContent = titre;
    langue.appendChild(o);
  }
  // La langue que parle l'exemple : la règle 4 la compare à celle des répliques (30/09).
  const parle = document.createElement("select");
  parle.setAttribute("aria-label", "Langue parlée dans l'exemple");
  parle.innerHTML = document.getElementById("langue").innerHTML;
  zone.append("Un exemple à cloner, parlé en ", parle, " : ", coche, " ", fichier, document.createElement("br"),
    "Ou une voix générée en ", langue, " ",
    bouton(f.voix ? "Remplacer par une voix générée" : "Générer la voix", () => poserVoix(f.id, {generer: langue.value})));
}

async function voixLangue(id, langue){
  ficheEtat("Voix clonée en cours chez Modal (1 à 5 min)…");
  const r = await fetch("/video-h3/fiches/" + id + "/voix/langue", {method: "POST", headers: H, body: JSON.stringify({langue})});
  let d = await r.json();
  if (!r.ok){ ficheEtat(typeof d.detail === "string" ? d.detail : "Refusé.", true); return; }
  while (["queued", "running"].includes(d.status)){
    await new Promise(ok => setTimeout(ok, 5000));
    const s = await fetch("/jobs/" + d.id, {headers: H});
    if (s.ok) d = await s.json();
  }
  if (d.status !== "succeeded" || d.error){ ficheEtat(d.error || "La voix clonée a échoué.", true); return; }
  ficheEtat("");
  await chargerFiches(id);
}

async function poserVoix(id, corps){
  ficheEtat(corps.generer ? "Voix du Studio en cours…" : "Mise au propre de la voix…");
  const r = await fetch("/video-h3/fiches/" + id + "/voix", {method: "POST", headers: H, body: JSON.stringify(corps)});
  const d = await r.json();
  if (!r.ok){ ficheEtat(typeof d.detail === "string" ? d.detail : "Refusé.", true); return; }
  ficheEtat("");
  await chargerFiches(id);
}

// La planche de personnage : la même personne sous tous les angles, faite à partir
// des photos de la fiche, puis jointe aux images que le Studio crée avec elle (28/09).
function dessinerPlanche(f){
  const zone = document.getElementById("fiche_planche");
  zone.innerHTML = "";
  const t = document.createElement("b");
  t.textContent = "Planche de personnage";
  const note = document.createElement("p");
  note.className = "note";
  note.textContent = "Face, trois-quarts et profil du visage ; de face, de profil et de dos en pied. Faite par "
    + "l'image du Studio (gratuite) à partir des photos ci-dessus, puis jointe aux images créées avec ce "
    + "personnage (première image, départ d'un plan) pour garder le même visage et la même tenue.";
  zone.append(t, note);
  if (f.planche){
    const img = document.createElement("img");
    img.className = "apercu";
    img.src = f.planche;
    img.alt = "Planche de personnage de « " + f.nom + " »";
    const lien = document.createElement("a");
    lien.href = f.planche;
    lien.download = "planche-" + f.nom + (f.planche.startsWith("data:image/png") ? ".png" : ".jpg");
    lien.textContent = "Télécharger la planche";
    zone.append(img, lien, " ");
  }
  const angles = Object.keys(f.images || {}).length;
  if (angles) zone.append(bouton(f.planche ? "Refaire la planche" : "Créer la planche de personnage", async () => {
    ficheEtat("Planche de personnage en cours (10 à 40 s)…");
    const r = await fetch("/video-h3/fiches/" + f.id + "/planche", {method: "POST", headers: H, body: "{}"});
    const d = await r.json();
    if (!r.ok){ ficheEtat(typeof d.detail === "string" ? d.detail : "Refusé.", true); return; }
    ficheEtat("");
    await chargerFiches(f.id);
  }));
  else zone.append("Ajoutez d'abord des photos : la planche part d'elles.");
  if (f.planche) zone.append(bouton("Supprimer la planche", async () => {
    const r = await fetch("/video-h3/fiches/" + f.id + "/planche", {method: "DELETE", headers: H});
    if (r.ok) await chargerFiches(f.id);
  }));
}

async function poserPhoto(id, angle, image, visage){
  ficheEtat(visage ? "Recherche du visage et recadrage…" : "Envoi de la photo…");
  const r = await fetch("/video-h3/fiches/" + id + "/images/" + angle, {method: "POST", headers: H,
    body: JSON.stringify({image: image, visage: visage})});
  const d = await r.json();
  if (!r.ok){ ficheEtat(typeof d.detail === "string" ? d.detail : "Refusé.", true); return; }
  ficheEtat("");
  await chargerFiches(id);
}

async function faireImage(id, angle){
  ficheEtat("Image « " + ANGLES[angle] + " » en cours (10 à 30 s)…");
  const r = await fetch("/video-h3/fiches/" + id + "/images/" + angle, {method: "POST", headers: H, body: "{}"});
  const d = await r.json();
  if (!r.ok){ ficheEtat(typeof d.detail === "string" ? d.detail : "Refusé.", true); return false; }
  ficheEtat("");
  await chargerFiches(id);
  return true;
}

async function retirerImage(id, angle){
  const r = await fetch("/video-h3/fiches/" + id + "/images/" + angle, {method: "DELETE", headers: H});
  const d = await r.json();
  if (!r.ok){ ficheEtat(typeof d.detail === "string" ? d.detail : "Refusé.", true); return; }
  await chargerFiches(id);
}

document.getElementById("fiche_choix").addEventListener("change", () => { ficheEtat(""); montrerFiche(); });

document.getElementById("fiche_creer").addEventListener("click", async () => {
  const r = await fetch("/video-h3/fiches", {method: "POST", headers: H, body: JSON.stringify({
    nom: document.getElementById("fiche_nom").value,
    description: document.getElementById("fiche_description").value, genre: genreFiche()})});
  const d = await r.json();
  if (!r.ok){ ficheEtat(typeof d.detail === "string" ? d.detail : "Refusé.", true); return; }
  const personne = genreFiche() === "personne";
  await chargerFiches(d.id);
  for (const angle of personne ? Object.keys(ANGLES) : ["face"]){
    if (!await faireImage(d.id, angle)) return;
  }
  ficheEtat(personne ? "Fiche prête : choisissez-la en mode « Références », champ « Personnage »."
    : "Fiche prête : cochez-la dans « Objets et poses du scénario », et écrivez son nom dans le texte des plans.");
});

document.getElementById("fiche_supprimer").addEventListener("click", async () => {
  const id = document.getElementById("fiche_choix").value;
  const f = FICHES.find(x => x.id === id);
  if (!f || !confirm("Supprimer la fiche « " + f.nom + " » et ses images ?")) return;
  const r = await fetch("/video-h3/fiches/" + id, {method: "DELETE", headers: H});
  if (!r.ok){ ficheEtat("Suppression refusée.", true); return; }
  ficheEtat("Fiche supprimée.");
  await chargerFiches("");
});

// Monter un scénario (PLAN 18.9) : des clips déjà faits, recollés dans l'ordre choisi.
let CLIPS = [], COCHES = new Set();

function quandLocal(ts){
  // L'heure du navigateur : le conteneur du Studio tourne en UTC.
  if (!ts) return "";
  const d = new Date(ts * 1000), p = n => String(n).padStart(2, "0");
  return dateFr(d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate())
    + " " + p(d.getHours()) + ":" + p(d.getMinutes()));
}

function montageEtat(t, refus){
  const e = document.getElementById("montage_etat");
  e.className = refus ? "refus" : "note";
  e.textContent = t || "";
}

async function chargerClips(){
  const r = await fetch("/video-h3/clips", {headers: H});
  if (!r.ok) return;
  const d = await r.json();
  const avant = CLIPS.map(c => c.id);
  // L'ordre déjà rangé est gardé ; les clips neufs arrivent en tête.
  CLIPS = d.clips.filter(c => !avant.includes(c.id))
    .concat(avant.map(id => d.clips.find(c => c.id === id)).filter(Boolean));
  COCHES = new Set([...COCHES].filter(id => CLIPS.some(c => c.id === id)));
  dessinerClips();
  dessinerFilmsHd(d.films_hd || []);
  for (const [idSel, vide] of [["scenario_chanson", "Aucune (musique décrite au clip)"], ["musique_chanson", ""]]){
    const sc = document.getElementById(idSel);
    const gardeSc = sc.value;
    sc.innerHTML = vide ? '<option value="">' + vide + '</option>' : "";
    for (const c of (d.chansons || [])){
      const o = document.createElement("option");
      o.value = c.id;
      o.textContent = c.titre + " (" + quandLocal(c.cree_a) + ")"
        + (c.voix_des_s != null ? " — voix possible dès " + c.voix_des_s + " s" : "");
      sc.appendChild(o);
    }
    if ((d.chansons || []).some(c => c.id === gardeSc)) sc.value = gardeSc;
  }
  const mf = document.getElementById("musique_film");
  const gardeMf = mf.value;
  mf.innerHTML = "";
  // Les films en haute définition d'abord : on les finit (sous-titres, musique) après la 4K.
  const films = (d.films_hd || []).map(f => ({id: f.id, cree_a: f.cree_a, secondes: f.secondes,
    invite: (f.echelle || "").toUpperCase() + " · " + (f.titre || "")})).concat(CLIPS);
  for (const c of films){
    const o = document.createElement("option");
    o.value = c.id;
    o.textContent = quandLocal(c.cree_a) + " · " + fr(c.secondes || 0, 1) + " s · " + (c.invite || "").slice(0, 60);
    mf.appendChild(o);
  }
  if (films.some(c => c.id === gardeMf)) mf.value = gardeMf;
}

document.getElementById("musique_poser").addEventListener("click", async () => {
  const e = document.getElementById("musique_etat");
  e.className = "note";
  e.textContent = "Pose de la musique…";
  const r = await fetch("/video-h3/musique", {method: "POST", headers: H, body: JSON.stringify({
    film: document.getElementById("musique_film").value, chanson: document.getElementById("musique_chanson").value,
    debut_s: Number(document.getElementById("musique_debut").value) || 0,
    volume: Number(document.getElementById("musique_volume").value) || 0.3,
    depart_chanson_s: Number(document.getElementById("musique_depart").value) || 0,
    fondu_s: Number(document.getElementById("musique_fondu").value) || 0,
    sous_paroles: document.getElementById("musique_sous_paroles").checked})});
  const j = await r.json();
  if (!r.ok){ e.className = "refus"; e.textContent = typeof j.detail === "string" ? j.detail : "Refusé."; return; }
  e.textContent = "Musique posée : le film est ci-dessous.";
  const lien = await fetch("/video/jobs/" + j.id, {headers: H}).then(x => x.json());
  document.getElementById("musique_resultat").hidden = false;
  document.getElementById("musique_lecteur").src = lien.video_url;
  document.getElementById("musique_telecharger").href = lien.video_url + "&telecharger=1&nom=film-h3";
  chargerClips();
});

document.getElementById("sous_titrer").addEventListener("click", async () => {
  const e = document.getElementById("musique_etat");
  e.className = "note";
  e.textContent = "Sous-titres : écoute des répliques…";
  const r = await fetch("/video-h3/sous-titres", {method: "POST", headers: H, body: JSON.stringify({
    film: document.getElementById("musique_film").value})});
  const j = await r.json();
  if (!r.ok){ e.className = "refus"; e.textContent = typeof j.detail === "string" ? j.detail : "Refusé."; return; }
  let d = null;
  for (;;){
    await new Promise(ok => setTimeout(ok, 4000));
    d = await fetch("/video/jobs/" + j.id, {headers: H}).then(x => x.json());
    if (d.status === "succeeded" || d.status === "failed") break;
    e.textContent = "Sous-titres : " + (d.etape || "en attente") + "…";
  }
  if (d.status === "failed"){ e.className = "refus"; e.textContent = d.message || "Les sous-titres ont échoué."; return; }
  e.textContent = "Film sous-titré : il est ci-dessous, et dans la liste des films pour y poser la musique.";
  document.getElementById("musique_resultat").hidden = false;
  document.getElementById("musique_lecteur").src = d.video_url;
  document.getElementById("musique_telecharger").href = d.video_url + "&telecharger=1&nom=film-sous-titre";
  await chargerClips();
  document.getElementById("musique_film").value = j.id;
});

function dessinerFilmsHd(films){
  document.getElementById("films_hd_bloc").hidden = !films.length;
  const liste = document.getElementById("films_hd_liste");
  liste.innerHTML = "";
  for (const f of films){
    const ligne = document.createElement("div");
    const texte = document.createElement("span");
    texte.textContent = quandLocal(f.cree_a) + " · " + (f.echelle || "").toUpperCase() + " · "
      + fr(f.secondes || 0, 1) + " s · " + (f.titre || "").slice(0, 80) + " "
      // La compression AV1 (30/09) : ce qu'elle a gagné, ou pourquoi elle n'a pas eu lieu.
      + (f.compression && f.compression.codec === "av1" && f.compression.mo
          ? "· AV1, " + fr(f.compression.mo, 1) + " Mo au lieu de " + fr(f.compression.avant_mo, 1) + " Mo "
          : f.compression && f.compression.raison ? "· non compressé : " + f.compression.raison + " " : "");
    const voir = document.createElement("button");
    voir.textContent = "Voir";
    voir.addEventListener("click", () => {
      const l = document.getElementById("films_hd_lecteur");
      l.hidden = false;
      l.src = f.video_url;
      l.play();
    });
    const tele = document.createElement("a");
    tele.textContent = "Télécharger";
    tele.href = f.video_url + "&telecharger=1&nom=film-" + (f.echelle || "hd");
    ligne.append(texte, voir, " ", tele);
    liste.appendChild(ligne);
  }
}

function dessinerClips(){
  const liste = document.getElementById("clips_liste");
  liste.innerHTML = "";
  if (!CLIPS.length){ liste.textContent = "Aucun clip H3 réussi sur ce Studio pour l'instant."; return; }
  CLIPS.forEach((c, i) => {
    const ligne = document.createElement("div");
    ligne.className = "clip";
    const coche = document.createElement("input");
    coche.type = "checkbox";
    coche.checked = COCHES.has(c.id);
    coche.addEventListener("change", () => { coche.checked ? COCHES.add(c.id) : COCHES.delete(c.id); });
    const vid = document.createElement("video");
    vid.src = c.video_url;
    vid.controls = true;
    vid.preload = "metadata";
    const texte = document.createElement("div");
    texte.className = "note";
    texte.textContent = quandLocal(c.cree_a) + " ; "
      + fr(c.secondes, 1) + " s" + (c.fiche ? " ; " + c.fiche : "") + " — " + c.invite.slice(0, 220);
    const outils = document.createElement("div");
    outils.appendChild(coche);
    outils.appendChild(bouton("↑", () => deplacer(i, -1)));
    outils.appendChild(bouton("↓", () => deplacer(i, 1)));
    ligne.append(outils, vid, texte);
    liste.appendChild(ligne);
  });
}

function deplacer(i, pas){
  const j = i + pas;
  if (j < 0 || j >= CLIPS.length) return;
  [CLIPS[i], CLIPS[j]] = [CLIPS[j], CLIPS[i]];
  dessinerClips();
}

function cochesDansLOrdre(){
  return CLIPS.filter(c => COCHES.has(c.id)).map(c => c.id);
}

document.getElementById("scenario_ordonner").addEventListener("click", async () => {
  montageEtat("Le chat du Studio range les clips…");
  const r = await fetch("/video-h3/scenario/ordonner", {method: "POST", headers: H, body: JSON.stringify({
    scenario: document.getElementById("scenario").value, clips: cochesDansLOrdre()})});
  const d = await r.json();
  if (!r.ok){ montageEtat(typeof d.detail === "string" ? d.detail : "Refusé.", true); return; }
  const laisses = cochesDansLOrdre().filter(id => !d.ordre.includes(id)).length;
  CLIPS = d.ordre.map(id => CLIPS.find(c => c.id === id)).concat(CLIPS.filter(c => !d.ordre.includes(c.id)));
  COCHES = new Set(d.ordre);
  dessinerClips();
  montageEtat("Rangés selon le scénario" + (laisses ? " ; " + laisses + " clip(s) laissé(s) de côté par le chat." : ".")
    + " Vérifiez, puis assemblez.");
});

document.getElementById("montage_lancer").addEventListener("click", async () => {
  montageEtat("Assemblage…");
  document.getElementById("montage_resultat").hidden = true;
  const r = await fetch("/video-h3/montage", {method: "POST", headers: H, body: JSON.stringify({
    scenario: document.getElementById("scenario").value, clips: cochesDansLOrdre()})});
  const d = await r.json();
  if (!r.ok){ montageEtat(typeof d.detail === "string" ? d.detail : "Refusé.", true); return; }
  const j = await (await fetch("/video/jobs/" + d.id, {headers: H})).json();
  montageEtat("Film assemblé : " + d.video.plans + " clips, " + fr(d.video.secondes, 1) + " s.");
  document.getElementById("montage_resultat").hidden = false;
  document.getElementById("montage_lecteur").src = j.video_url;
  document.getElementById("montage_telecharger").href = j.video_url + "&telecharger=1&nom=film-h3";
  blocAgrandir("montage_agrandir", d.id, "");
  blocVisages("montage_visages", d.id, "");
  blocFinaliser("montage_finaliser", d.id, "");
  chargerClips();
});

// Tourner un scénario neuf : le chat découpe, le propriétaire relit, le Studio tourne.
let PLANS = [], ENCHAINEMENTS = __ENCHAINEMENTS__, SCENARIO = null;
// Le menu « Caméra » (01/10) : mouvement, puis amplitude et vitesse quand elles ont un sens
// (format du guide de MiniMax : type + amplitude + vitesse). Fixe par défaut.
const CAMERA = __CAMERA__;
function menuCamera(cam, change){
  const zone = document.createElement("span");
  zone.className = "menu_camera";
  const choix = (valeurs, valeur, titre) => {
    const s = document.createElement("select");
    s.title = titre;
    for (const [cle, nom] of Object.entries(valeurs)){
      const o = document.createElement("option");
      o.value = cle;
      o.textContent = (cle === "" ? titre + " : " : "") + nom;
      s.appendChild(o);
    }
    s.value = valeur || "";
    return s;
  };
  const m = choix(CAMERA.mouvements, cam.mouvement || CAMERA.defaut.mouvement, "Mouvement");
  const a = choix(CAMERA.amplitudes, cam.amplitude, "Amplitude");
  const v = choix(CAMERA.vitesses, cam.vitesse, "Vitesse");
  const maj = () => {
    const sans = CAMERA.sans_reglage.includes(m.value);
    a.hidden = v.hidden = sans;
    if (sans){ a.value = ""; v.value = ""; }
    change({mouvement: m.value, amplitude: a.value, vitesse: v.value});
  };
  for (const s of [m, a, v]) s.addEventListener("change", maj);
  zone.append(m, a, v);
  maj();
  return zone;
}
let CAMERA_CLIP = Object.assign({}, CAMERA.defaut);
document.getElementById("camera_clip").appendChild(menuCamera(CAMERA_CLIP, c => { CAMERA_CLIP = c; }));
// Un scénario déjà tourné, repris : ses plans initiaux (pour le gras) et les plans à retourner.
let PLANS_INITIAUX = null, SCENARIO_TOURNE = null, RETOURNER = new Set();
let FOND = {plans_db: [], ambiance: null};

// Les mots du plan, en gras ce qui n'était pas dans le plan initial, barré ce qui en a été retiré.
function diffGras(avant, apres){
  const a = (avant || "").split(/\s+/).filter(Boolean), b = (apres || "").split(/\s+/).filter(Boolean);
  const L = Array.from({length: a.length + 1}, () => new Array(b.length + 1).fill(0));
  for (let i = a.length - 1; i >= 0; i--)
    for (let j = b.length - 1; j >= 0; j--)
      L[i][j] = a[i] === b[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
  const bloc = document.createElement("p");
  bloc.className = "note";
  const mot = (t, balise) => { const e = document.createElement(balise); e.textContent = t; bloc.append(e, " "); };
  let i = 0, j = 0;
  while (i < a.length || j < b.length){
    if (i < a.length && j < b.length && a[i] === b[j]){ mot(b[j], "span"); i++; j++; }
    else if (i < a.length && (j >= b.length || L[i + 1][j] >= L[i][j + 1])){ mot(a[i], "s"); i++; }
    else { mot(b[j], "b"); j++; }
  }
  return bloc;
}

function scenarioEtat(t, refus){
  const e = document.getElementById("scenario_etat");
  e.className = refus ? "refus" : "note";
  e.textContent = t || "";
}

// L'image de départ d'un plan « coupe » (demande du propriétaire, 28/09) : créée
// avec les photos des fiches du scénario, améliorée jusqu'à la valider ; le plan
// part alors de cette image, et sa description passe à H3.
const DEPART_APERCU = new WeakMap(), DEPART_AMELIORATIONS = new WeakMap();

function fichesDuScenario(){
  return [document.getElementById("scenario_fiche").value, document.getElementById("scenario_fiche2").value]
    .concat(objetsDuScenario()).filter((f, i, t) => f && t.indexOf(f) === i);
}

function blocDepart(p){
  const zone = document.createElement("div");
  const note = document.createElement("p");
  note.className = "note";
  note.textContent = p.image_depart
    ? "Image de départ : le plan part de cette image (mode « Première image »). Vérifiez-la avant de tourner."
    : "Sans image de départ, le plan part des photos des fiches (mode « Références »).";
  const texte = document.createElement("textarea");
  texte.value = p.texte_depart || texteDepart(p);
  texte.addEventListener("input", () => { p.texte_depart = texte.value; });
  const apercu = document.createElement("img");
  apercu.className = "apercu";
  apercu.hidden = true;
  if (DEPART_APERCU.get(p)){ apercu.src = DEPART_APERCU.get(p); apercu.hidden = false; }
  else if (p.image_depart){
    fetch("/video-h3/depart/" + p.image_depart, {headers: H}).then(r => r.ok ? r.json() : null).then(d => {
      if (d){ DEPART_APERCU.set(p, d.image); apercu.src = d.image; apercu.hidden = false; }
    });
  }
  const etat = document.createElement("p");
  etat.className = "note";
  if (!DEPART_AMELIORATIONS.has(p)) DEPART_AMELIORATIONS.set(p, []);
  const ameliorations = DEPART_AMELIORATIONS.get(p);
  async function creer(){
    etat.className = "note";
    etat.textContent = "Création de l'image (quelques secondes)…";
    // L'image du plan d'avant part aussi : même lieu, même décor (28/09).
    const avant = PLANS.slice(0, PLANS.indexOf(p)).reverse().find(q => q.image_depart);
    const r = await fetch("/video-h3/depart", {method: "POST", headers: H, body: JSON.stringify({
      texte: texte.value, ameliorations: ameliorations, fiches: fichesDuScenario(),
      decor: avant ? avant.image_depart : null, elements: p.elements || [],
      // La tenue de ce plan, relevée sur tout le film (29/09) : la même que dans le plan tourné.
      plans: PLANS.map(q => q.image_paroles), plan: PLANS.indexOf(p) + 1})});
    const d = await r.json();
    if (!r.ok){ etat.className = "refus"; etat.textContent = typeof d.detail === "string" ? d.detail : "Refusé."; return false; }
    p.image_depart = d.id;
    p.description_depart = d.texte;
    p.texte_depart = texte.value;
    DEPART_APERCU.set(p, d.image);
    return true;
  }
  const libelle = document.createElement("label");
  libelle.textContent = "Description de l'image de départ (les personnages du scénario y sont joints, "
    + "et l'image de départ du plan précédent, pour garder le même lieu)";
  zone.append(note, libelle, texte,
              bouton(p.image_depart ? "Refaire l'image" : "Créer l'image de départ",
                     async () => { if (await creer()) dessinerPlans(); }),
              apercu, etat);
  if (p.image_depart){
    const voeu = document.createElement("input");
    voeu.type = "text";
    voeu.maxLength = 300;
    const titre = document.createElement("label");
    titre.textContent = "Améliorer cette image : dites ce qui doit changer";
    const liste = document.createElement("ul");
    ameliorations.forEach((a, k) => {
      const li = document.createElement("li");
      li.append(a + " ", bouton("retirer", () => { ameliorations.splice(k, 1); dessinerPlans(); }));
      liste.appendChild(li);
    });
    zone.append(titre, voeu, bouton("Refaire l'image avec cette amélioration", async () => {
      const v = voeu.value.trim();
      if (!v) return;
      ameliorations.push(v);
      if (await creer()) dessinerPlans();
      else ameliorations.pop();
    }), liste, bouton("Retirer l'image de départ", () => {
      delete p.image_depart;
      delete p.description_depart;
      DEPART_APERCU.delete(p);
      dessinerPlans();
    }));
    zone.append(blocComparer(fichesDuScenario(), "/video-h3/depart/" + p.image_depart + "/comparer", {}));
  }
  return zone;
}

// Le tableau des éléments (29/09) : d'où part chaque élément clé, ce qu'il fait,
// où il finit. Écrit par le découpage ; un texte retouché à la main ne le change pas.
function tableauElements(elements){
  const zone = document.createElement("details");
  zone.className = "note";
  const titre = document.createElement("summary");
  titre.textContent = "Éléments du plan : départ, mouvement, arrivée (écrit par le découpage)";
  const table = document.createElement("table");
  const entete = table.insertRow();
  for (const x of ["Élément", "Départ", "Mouvement", "Arrivée"]){
    const th = document.createElement("th");
    th.textContent = x;
    entete.appendChild(th);
  }
  for (const e of elements){
    const ligne = table.insertRow();
    for (const champ of ["nom", "debut", "mouvement", "fin"]) ligne.insertCell().textContent = e[champ] || "";
  }
  zone.append(titre, table);
  return zone;
}

function dessinerPlans(){
  const liste = document.getElementById("plans_liste");
  liste.innerHTML = "";
  PLANS.forEach((p, i) => {
    const bloc = document.createElement("div");
    bloc.className = "image_bord";
    const t = document.createElement("b");
    t.textContent = "Plan " + (i + 1);
    const vue = document.createElement("textarea");
    vue.value = p.image_paroles;
    const son = document.createElement("input");
    son.type = "text";
    son.value = p.ambiance;
    son.placeholder = "Ambiance sonore";
    const ecart = document.createElement("div");
    const init = PLANS_INITIAUX && PLANS_INITIAUX[i];
    const majEcart = () => {
      ecart.innerHTML = "";
      if (init) ecart.append(diffGras(init.image_paroles, p.image_paroles), diffGras(init.ambiance, p.ambiance));
    };
    majEcart();
    vue.addEventListener("input", () => { p.image_paroles = vue.value; majEcart(); });
    son.addEventListener("input", () => { p.ambiance = son.value; majEcart(); });
    const ench = document.createElement("select");
    for (const [cle, titre] of Object.entries(ENCHAINEMENTS)){
      const o = document.createElement("option");
      o.value = cle;
      o.textContent = titre;
      ench.appendChild(o);
    }
    ench.value = p.enchainement;
    ench.disabled = i === 0;
    ench.addEventListener("change", () => {
      p.enchainement = ench.value;
      if (p.enchainement !== "coupe"){ delete p.image_depart; delete p.description_depart; }
      dessinerPlans();
    });
    const cam = document.createElement("label");
    cam.append("Caméra ", menuCamera(p.camera || CAMERA.defaut, c => { p.camera = c; }));
    // La durée du plan (01/10) : celle du scénario par défaut, ou la sienne.
    const duree = document.createElement("label");
    const sd = document.createElement("select");
    sd.add(new Option("comme le scénario", ""));
    for (const x of (ETAT ? ETAT.durees : [])) sd.add(new Option(fr(x.secondes, 1) + " s", x.images));
    sd.value = p.longueur ? String(p.longueur) : "";
    sd.addEventListener("change", () => {
      if (sd.value) p.longueur = Number(sd.value); else delete p.longueur;
      dessinerPlans();
    });
    duree.append(" Durée ", sd);
    bloc.append(t, vue, son, ecart, ench, cam, duree, bouton("Retirer ce plan", () => { PLANS.splice(i, 1); dessinerPlans(); }));
    if ((p.elements || []).length) bloc.appendChild(tableauElements(p.elements));
    if (SCENARIO_TOURNE){
      const coche = document.createElement("input");
      coche.type = "checkbox";
      coche.checked = RETOURNER.has(i + 1);
      coche.addEventListener("change", () => { coche.checked ? RETOURNER.add(i + 1) : RETOURNER.delete(i + 1); });
      const etiquette = document.createElement("label");
      etiquette.append(coche, " Retourner ce plan même inchangé");
      bloc.appendChild(etiquette);
    }
    if (p.enchainement === "coupe") bloc.appendChild(blocDepart(p));
    liste.appendChild(bloc);
  });
  const max = ETAT && ETAT.scenario ? ETAT.scenario.plans_max : 6;
  document.getElementById("plan_ajouter").hidden = !PLANS.length || PLANS.length >= max;
  // Un scénario repris se rejoue (plans changés seulement), il ne se retourne pas en entier.
  document.getElementById("scenario_tourner").hidden = !PLANS.length || !!SCENARIO_TOURNE;
  document.getElementById("scenario_verifier").hidden = !PLANS.length || !!SCENARIO_TOURNE;
  // Un plan à plusieurs répliques (30/09) : le Studio propose de le couper.
  document.getElementById("scenario_scinder").hidden = !PLANS.some(p =>
    ((p.image_paroles || "") + " " + (p.ambiance || "")).split("«").length > 2);
  document.getElementById("scenario_forcer").hidden = true;
  // Le prix plan par plan : chacun a sa durée, ou celle du scénario (01/10).
  const sl = document.getElementById("longueur").value;
  const prixDe = n => ETAT ? (ETAT.durees.find(x => String(x.images) === String(n)) || {}).prix_estime_usd : null;
  const prix = PLANS.map(p => prixDe(p.longueur || sl));
  const total = prix.every(x => x) ? prix.reduce((a, b) => a + b, 0) : null;
  document.getElementById("scenario_prix").textContent = PLANS.length
    ? PLANS.length + " plan(s) à tourner" + (total ? ", environ " + fr(total, 2) + " $ en tout." : ".")
    : "";
}

document.getElementById("scenario_decouper").addEventListener("click", async () => {
  scenarioEtat("Le chat du Studio découpe le scénario…");
  const r = await fetch("/video-h3/scenario/decouper", {method: "POST", headers: H,
    body: JSON.stringify({scenario: document.getElementById("scenario").value, fiches: fichesDuScenario()})});
  const d = await r.json();
  if (!r.ok){ scenarioEtat(typeof d.detail === "string" ? d.detail : "Refusé.", true); return; }
  PLANS = d.plans;
  PLANS_INITIAUX = null;
  SCENARIO_TOURNE = null;
  document.getElementById("scenario_suite").hidden = true;
  dessinerPlans();
  // Le relecteur du scénario complet (29/09) : ce qu'il a trouvé, et s'il l'a corrigé.
  const rl = d.relecture || {trouves: []};
  const vu = rl.trouves.length
    ? "Relecteur : " + (rl.corrige ? "corrigé avant de vous montrer les plans — " : "")
      + texteContinuite({problemes: rl.trouves}) + (rl.erreur ? " (" + rl.erreur + ")" : "") + ". "
    : "";
  const st = rl.second_tour;
  const vu2 = st && st.trouves.length
    ? "Seconde relecture : " + (st.corrige ? "corrigé aussi — " : "")
      + texteContinuite({problemes: st.trouves}) + (st.erreur ? " (" + st.erreur + ")" : "") + ". "
    : "";
  // Les détails (regard, main, place exacte) : montrés, jamais réécrits (29/09).
  const det = d.continuite && (d.continuite.details || []).length
    ? " Détails, sans correction : " + texteContinuite({problemes: d.continuite.details}) + "." : "";
  // Les marques [langue, émotion] posées par le chat (30/09) : un échec est dit.
  const mq = d.marques && d.marques.erreur
    ? " Langue et émotion des répliques non posées (" + d.marques.erreur + ") : ajoutez-les à la main." : "";
  const sc = (d.scissions || []).length ? " Découpe : " + texteScissions(d.scissions) + "." : "";
  const scMal = (d.scissions || []).some(n => !n.en);
  if (d.continuite && d.continuite.ok === false)
    scenarioEtat(vu + vu2 + "Reste à revoir avant de tourner : " + texteContinuite(d.continuite) + "." + det + mq + sc, true);
  else scenarioEtat(vu + vu2 + "Relisez les plans, puis tournez." + det + mq + sc, !!mq || scMal);
});

function texteScissions(s){
  return (s || []).map(n => "plan " + n.plan + (n.en ? " coupé en " + n.en + " (une réplique par plan)"
    : " garde ses répliques (" + n.erreur + ")")).join(" ; ");
}

document.getElementById("scenario_scinder").addEventListener("click", async () => {
  scenarioEtat("Le chat du Studio coupe les plans à plusieurs répliques…");
  const r = await fetch("/video-h3/scenario/scinder", {method: "POST", headers: H, body: JSON.stringify({plans: PLANS})});
  const d = await r.json();
  if (!r.ok){ scenarioEtat(typeof d.detail === "string" ? d.detail : "Refusé.", true); return; }
  PLANS = d.plans;
  dessinerPlans();
  scenarioEtat(texteScissions(d.scissions) + ". Relisez les plans, puis tournez.", d.scissions.some(n => !n.en));
});

function texteContinuite(c){
  return c.problemes.map(p => "plan " + p.plan + ", " + p.quoi).join(" ; ");
}

async function chargerScenarios(){
  const r = await fetch("/video-h3/scenarios", {headers: H});
  if (!r.ok) return;
  const sel = document.getElementById("scenario_choix");
  const garde = sel.value;
  sel.innerHTML = '<option value="">Choisissez un scénario…</option>';
  for (const s of (await r.json()).scenarios.filter(x => x.etat === "réussi")){
    const o = document.createElement("option");
    o.value = s.id;
    o.textContent = quandLocal(s.cree_a) + " · " + s.plans + " plans · " + s.debut;
    sel.appendChild(o);
  }
  sel.value = garde;
}

let DEFAUTS = [];

function dessinerJugement(jugement){
  const zone = document.getElementById("jugement");
  zone.innerHTML = "";
  DEFAUTS = [];
  // Les règles 9 à 12 du plan tourné (30/09), sous le même tableau que celles d'avant.
  const avecRegles = (jugement || []).filter(j => j.regles && j.regles.length);
  if (avecRegles.length) dessinerRegles(avecRegles.map(j => ({plan: j.plan, regles: j.regles})), "Plans tournés");
  for (const j of jugement || []){
    if (!j.defauts.length){
      const p = document.createElement("p");
      p.className = "note";
      p.textContent = "Plan " + j.plan + " : " + (j.verdict === "ok" ? "rien à signaler." : "défaut signalé sans image précise.")
        + (j.paroles ? " " + texteParoles(j.paroles) : "");
      zone.appendChild(p);
      continue;
    }
    for (const x of j.defauts){
      const d = {plan: j.plan, t_s: x.t_s, quoi: x.quoi, cause: x.cause, garde: true};
      DEFAUTS.push(d);
      const label = document.createElement("label");
      label.className = "refus";
      const c = document.createElement("input");
      c.type = "checkbox";
      c.checked = true;
      c.addEventListener("change", () => { d.garde = c.checked; });
      // La cause (29/09) : un texte fautif se réécrit ; un texte juste que la vidéo n'a pas suivi se rejoue tel quel.
      const cause = {texte: " (cause : le texte, il sera réécrit)",
                     video: " (cause : la vidéo, texte juste : le plan sera rejoué sans le réécrire)"}[x.cause] || "";
      label.append(c, " Plan " + j.plan + ", à " + fr(x.t_s, x.t_s % 0.5 ? 2 : 1) + " s : " + x.quoi + cause);
      zone.appendChild(label);
      zone.appendChild(document.createElement("br"));
    }
  }
}

async function ouvrirScenario(sid){
  const sc = await fetch("/video-h3/scenario/" + sid, {headers: H}).then(r => r.json());
  if (sc.etat !== "réussi") return;
  SCENARIO_TOURNE = sid;
  FOND = {plans_db: sc.ambiance_plans_db || [], ambiance: sc.ambiance || null};
  dessinerFond();
  PLANS = sc.plans.map(p => Object.assign({}, p));
  PLANS_INITIAUX = sc.plans_initiaux || sc.plans;
  RETOURNER = new Set();
  document.getElementById("scenario_suite").hidden = false;
  document.getElementById("scenario_choix").value = sid;
  dessinerJugement(sc.jugement);
  dessinerPlans();
  document.getElementById("scenario_tourner").hidden = true;
  if (sc.video_url){
    document.getElementById("montage_resultat").hidden = false;
    document.getElementById("montage_lecteur").src = sc.video_url;
    document.getElementById("montage_telecharger").href = sc.video_url + "&telecharger=1&nom=film-h3";
    const m = /\/video\/jobs\/([0-9a-f]{32})\//.exec(sc.video_url);
    if (m){ blocAgrandir("montage_agrandir", m[1], sid); blocVisages("montage_visages", m[1], sid); blocFinaliser("montage_finaliser", m[1], sid); }
  }
}

document.getElementById("scenario_choix").addEventListener("change", e => {
  if (e.target.value) ouvrirScenario(e.target.value);
});

// Pendant qu'une action tourne : un bandeau avec chronomètre, et les commandes
// verrouillées. Le 28/09, sans ce signe, un second clic a payé deux fois le même plan.
let CHRONO = null;
const LIBRES_PENDANT = new Set(["scenario_arreter", "scenario_auto_payer", "scenario_auto_arreter"]);

function verrouiller(oui){
  for (const e of document.querySelectorAll("#montage_bloc button, #montage_bloc select, #musique_bloc button, #musique_bloc select"))
    if (!LIBRES_PENDANT.has(e.id)) e.disabled = oui;
}

function occupe(texte){
  const b = document.getElementById("scenario_occupe");
  document.getElementById("scenario_occupe_texte").textContent = texte;
  scenarioEtat("");
  if (!b.hidden) return;
  b.hidden = false;
  const debut = Date.now();
  const maj = () => {
    const s = Math.round((Date.now() - debut) / 1000);
    document.getElementById("scenario_chrono").textContent = "· " + Math.floor(s / 60) + " min "
      + String(s % 60).padStart(2, "0") + " s";
  };
  maj();
  CHRONO = setInterval(maj, 1000);
  verrouiller(true);
}

function libre(){
  document.getElementById("scenario_occupe").hidden = true;
  document.getElementById("scenario_arreter").hidden = true;
  clearInterval(CHRONO);
  verrouiller(false);
}

async function actionJuger(){
  occupe("Le juge regarde chaque plan (gratuit)…");
  const j = await appeler("/video-h3/scenario/" + SCENARIO_TOURNE + "/juger");
  dessinerJugement(j.jugement);
  scenarioEtat("Jugement reçu : décochez les fausses alertes, puis corrigez le texte ou rejouez.");
}

async function actionCorriger(){
  occupe("Correction du texte et contrôle de continuité (gratuit)…");
  const d = await appeler("/video-h3/scenario/" + SCENARIO_TOURNE + "/corriger",
    {retours: document.getElementById("retours").value, defauts: DEFAUTS.filter(x => x.garde)});
  PLANS = d.plans;
  // Un plan dont le texte est juste se rejoue tel quel : coché d'office.
  for (const n of d.sans_texte || []) RETOURNER.add(n);
  dessinerPlans();
  const tels = (d.sans_texte || []).length ? " Plan(s) " + d.sans_texte.join(", ")
    + " : texte juste, cochés pour être rejoués tels quels." : "";
  if (d.continuite && d.continuite.ok === false)
    scenarioEtat("Texte corrigé, mais la continuité est à revoir : " + texteContinuite(d.continuite) + tels, true);
  else if (!d.retours) scenarioEtat("Aucun texte à réécrire." + tels + " Choisissez « Rejouer ».");
  else scenarioEtat("Texte corrigé : les changements sont en gras." + tels + " Relisez, puis choisissez « Rejouer ».");
}

// La fiche du décor d'après le film (02/10) : faite des images vraies, elle part au rejeu suivant.
let DECOR_REJEU;
async function actionDecor(){
  occupe("Fiche du décor d'après le film : description, vue d'ensemble et planche à quatre vues (gratuit)…");
  const f = await appeler("/video-h3/scenario/" + SCENARIO_TOURNE + "/decor", {});
  DECOR_REJEU = f.id;
  await chargerFiches();
  scenarioEtat("Fiche du décor « " + f.nom + " » créée d'après le film : vérifiez-la dans Fiches ; "
    + "les coupes du prochain rejeu en gardent le lieu.");
}

async function actionRejouer(forcer){
  occupe("Contrôle et traduction des plans à retourner…");
  const bouton = document.getElementById("rejouer_forcer");
  const rep = await fetch("/video-h3/scenario/" + SCENARIO_TOURNE + "/rejouer", {method: "POST", headers: H,
    body: JSON.stringify(Object.assign({plans: PLANS, retourner: [...RETOURNER], forcer: !!forcer, ou: OU},
      DECOR_REJEU ? {decor: DECOR_REJEU} : {}))});
  const r = await rep.json();
  if (!rep.ok){
    // Revue du 30/09 : le rejeu refusé par une règle n'offrait pas « quand même ».
    bouton.hidden = !(r.detail && r.detail.passe_droit);
    throw new Error(messageDeRefus(r));
  }
  bouton.hidden = true;
  const sc = await attendreScenario(r.id);
  if (sc.etat !== "réussi") return scenarioEtat("Rejeu " + sc.etat + (sc.erreur ? " : " + sc.erreur : "."), true);
  chargerClips();
  await chargerScenarios();
  await ouvrirScenario(r.id);
  scenarioEtat("Rejeu fini : " + (r.repris.length ? "plan(s) " + r.repris.join(", ") + " repris tels quels." : "tout a été retourné."));
}

// Le fond sonore réglé à la main, plan par plan (propriétaire, 02/10 : « un bouton d'ajustement
// manuel pour chaque clip si besoin »). Refait depuis le film brut : rien ne s'accumule.
function dessinerFond(){
  const zone = document.getElementById("fond_plans");
  zone.textContent = "";
  const mesures = (FOND.ambiance && FOND.ambiance.plans) || [];
  const n = Math.max(PLANS.length, mesures.length, FOND.plans_db.length);
  for (let i = 0; i < n; i++){
    const label = document.createElement("label");
    const champ = document.createElement("input");
    champ.type = "number"; champ.min = -12; champ.max = 12; champ.step = 1;
    champ.value = FOND.plans_db[i] || 0;
    champ.dataset.plan = i;
    champ.style.width = "5em";
    const m = mesures[i];
    const mesure = m && m.niveau_db !== null && m.niveau_db !== undefined
      ? " (mesuré " + fr(m.niveau_db, 1) + " dB" + (m.gain_db ? ", baissé de " + fr(-m.gain_db, 1) + " dB" : "") + ")" : "";
    label.append("Plan " + (i + 1) + " : ", champ, " dB" + mesure);
    zone.appendChild(label);
    zone.appendChild(document.createElement("br"));
  }
}

async function actionFond(){
  const plans_db = [...document.querySelectorAll("#fond_plans input")].map(c => Number(c.value) || 0);
  occupe("Le fond sonore est refait depuis le film brut (gratuit)…");
  const r = await appeler("/video-h3/scenario/" + SCENARIO_TOURNE + "/ambiance", {plans_db});
  FOND = {plans_db: r.plans_db, ambiance: r.ambiance};
  dessinerFond();
  document.getElementById("montage_resultat").hidden = false;
  document.getElementById("montage_lecteur").src = r.video_url;
  document.getElementById("montage_telecharger").href = r.video_url + "&telecharger=1&nom=film-h3";
  scenarioEtat("Fond sonore refait : écoutez le film ci-dessous.");
}

const ACTIONS = {
  auto: ["Lancer", () => corrigerToutSeul(SCENARIO_TOURNE, Number(document.getElementById("auto_tours").value),
                                          document.getElementById("auto_sans_arret").checked)],
  juger: ["Faire juger", actionJuger],
  corriger: ["Corriger le texte", actionCorriger],
  rejouer: ["Rejouer (payant)", actionRejouer],
  decor: ["Faire la fiche du décor", actionDecor],
  fond: ["Refaire le fond sonore", actionFond],
};

function majSuite(){
  const a = document.getElementById("suite_action").value;
  document.getElementById("suite_auto_options").hidden = a !== "auto";
  document.getElementById("suite_corriger_options").hidden = a !== "corriger";
  document.getElementById("suite_fond_options").hidden = a !== "fond";
  document.getElementById("suite_lancer").textContent = ACTIONS[a][0];
}
document.getElementById("suite_action").addEventListener("change", majSuite);
majSuite();

document.getElementById("suite_lancer").addEventListener("click", async () => {
  if (!SCENARIO_TOURNE) return;
  try {
    await ACTIONS[document.getElementById("suite_action").value][1]();
  } catch (e) {
    scenarioEtat(e.message, true);
  } finally {
    document.getElementById("suite_pause").hidden = true;
    libre();
  }
});

async function appeler(chemin, corps){
  const r = await fetch(chemin, {method: "POST", headers: H, body: JSON.stringify(corps || {})});
  const d = await r.json();
  if (!r.ok) throw new Error(messageDeRefus(d));
  return d;
}

// Un refus des règles (409, 30/09) porte le rapport : il s'affiche plan par plan.
function messageDeRefus(d){
  if (d && d.detail && typeof d.detail === "object"){
    if (d.detail.regles) dessinerRegles(d.detail.regles, "Avant le tournage");
    return d.detail.message || "Refusé.";
  }
  return typeof (d || {}).detail === "string" ? d.detail : "Refusé.";
}

// Les règles numérotées (30/09) : pour chaque plan, ✓ suivie, ✗ non suivie (avec
// la raison), – sans objet ou illisible. Demande du propriétaire : « a reviewer that
// say for each clip that rule n° 1 to xx are followed ».
function dessinerRegles(rapport, titre){
  const zone = document.getElementById("scenario_regles");
  zone.innerHTML = "";
  if (!rapport || !rapport.length) return;
  const b = document.createElement("b");
  b.textContent = "Règles — " + titre;
  zone.appendChild(b);
  const table = document.createElement("table");
  const numeros = [...new Set(rapport.flatMap(p => p.regles.map(x => x.n)))].sort((a, b) => a - b);
  const tete = table.insertRow();
  tete.insertCell().textContent = "Plan";
  const textes = {};
  for (const p of rapport) for (const x of p.regles) textes[x.n] = x.regle;
  for (const n of numeros){
    const c = tete.insertCell();
    c.textContent = n;
    c.title = textes[n] || "";
  }
  const fautes = [];
  for (const p of rapport){
    const ligne = table.insertRow();
    ligne.insertCell().textContent = p.plan;
    for (const n of numeros){
      const x = p.regles.find(y => y.n === n);
      const c = ligne.insertCell();
      c.textContent = !x ? "" : x.ok === true ? "✓" : x.ok === false ? "✗" : "–";
      if (x){
        c.title = x.regle + (x.pourquoi ? " — " + x.pourquoi : "");
        if (x.ok === false) fautes.push("Plan " + p.plan + ", règle " + n + " : " + x.pourquoi);
      }
    }
  }
  zone.appendChild(table);
  const liste = document.createElement("ul");
  for (const f of fautes){
    const li = document.createElement("li");
    li.className = "refus";
    li.textContent = f;
    liste.appendChild(li);
  }
  const regles = document.createElement("details");
  const s = document.createElement("summary");
  s.textContent = "Les règles";
  regles.appendChild(s);
  for (const n of numeros){
    const p = document.createElement("p");
    p.className = "note";
    p.textContent = n + ". " + (textes[n] || "");
    regles.appendChild(p);
  }
  zone.append(liste, regles);
}

async function attendreScenario(sid){
  SCENARIO = sid;
  document.getElementById("scenario_arreter").hidden = false;
  occupe("Tournage lancé (payant)…");
  for (;;){
    await new Promise(ok => setTimeout(ok, 10000));
    const sc = await fetch("/video-h3/scenario/" + sid, {headers: H}).then(r => r.json());
    if (sc.etat !== "en cours"){
      document.getElementById("scenario_arreter").hidden = true;
      return sc;
    }
    const faits = (sc.statuts || []).filter(s => s.status === "succeeded").length;
    const repris = (sc.repris || []).length;
    occupe("Tournage (payant) : " + faits + " plan(s) tourné(s) sur " + (sc.plans.length - repris)
      + (repris ? ", " + repris + " repris tel(s) quel(s)" : "") + "…");
  }
}

// L'accord du propriétaire avant de payer : une promesse que tient l'un des deux boutons.
function attendreAccord(){
  const pause = document.getElementById("suite_pause");
  const payer = document.getElementById("scenario_auto_payer"), arreter = document.getElementById("scenario_auto_arreter");
  pause.hidden = false;
  occupe("En pause : à vous de décider");
  return new Promise(ok => {
    const fin = oui => { pause.hidden = true; payer.onclick = arreter.onclick = null; ok(oui); };
    payer.onclick = () => fin(true);
    arreter.onclick = () => fin(false);
  });
}

async function corrigerTexte(sid, defauts){
  const c = await appeler("/video-h3/scenario/" + sid + "/corriger", {retours: "", defauts: defauts});
  PLANS = c.plans;
  dessinerPlans();
  return c.continuite && c.continuite.ok === false ? texteContinuite(c.continuite) : "";
}

// La boucle du propriétaire (28/09) : juger, corriger le texte des plans
// fautifs, ne rejouer qu'eux, recoller, rejuger ; au plus N tours. Le juge se
// trompe parfois (28/09 : au plan 1, plusieurs défauts qui n'y étaient pas) : sauf
// « sans arrêt », pause avant de payer, pour décocher les fausses alertes.
async function corrigerToutSeul(sid, tours, sansArret){
  for (let tour = 1; ; tour++){
    occupe("Tour " + tour + " : le juge regarde chaque plan (gratuit)…");
    const j = await appeler("/video-h3/scenario/" + sid + "/juger");
    dessinerJugement(j.jugement);
    const fautifs = j.jugement.filter(x => x.defauts.length);
    if (!fautifs.length) return scenarioEtat("Tout seul : aucun défaut vu après " + (tour - 1) + " rejeu(x). Film prêt.");
    if (tour > tours) return scenarioEtat("Tout seul : " + tours + " tour(s) faits, défauts restants aux plans "
      + fautifs.map(x => x.plan).join(", ") + ". À vous de voir.", true);
    occupe("Tour " + tour + " : correction du texte des plans " + fautifs.map(x => x.plan).join(", ") + " (gratuit)…");
    const corriges = JSON.stringify(DEFAUTS);
    let casse = await corrigerTexte(sid, DEFAUTS);
    // Rien n'est payé sur un texte qui ne se tient plus : la main revient au propriétaire.
    if (casse) return scenarioEtat("Tout seul, arrêté avant de rejouer : la correction casse la continuité ("
      + casse + "). Relisez les plans en gras.", true);
    if (!sansArret){
      if (!await attendreAccord()) return scenarioEtat("Tout seul : arrêté par vous, rien n'a été rejoué à ce tour.");
    }
    const gardes = DEFAUTS.filter(d => d.garde);
    if (!gardes.length) return scenarioEtat("Tout seul : aucun défaut gardé, rien à rejouer. Film prêt.");
    // Des fausses alertes décochées : le texte est refait sans elles (gratuit), avant de payer.
    if (JSON.stringify(gardes) !== corriges){
      occupe("Correction refaite avec les seuls défauts gardés (gratuit)…");
      casse = await corrigerTexte(sid, gardes);
      if (casse) return scenarioEtat("Tout seul, arrêté avant de rejouer : la correction casse la continuité ("
        + casse + "). Relisez les plans en gras.", true);
    }
    const retourner = [...new Set(gardes.map(d => d.plan))];
    const r = await appeler("/video-h3/scenario/" + sid + "/rejouer", {plans: PLANS, retourner: retourner, ou: OU});
    const sc = await attendreScenario(r.id);
    if (sc.etat !== "réussi") return scenarioEtat("Tout seul : rejeu " + sc.etat + (sc.erreur ? " : " + sc.erreur : "."), true);
    sid = r.id;
    chargerClips();
    await chargerScenarios();
    await ouvrirScenario(sid);
  }
}

document.getElementById("plan_ajouter").addEventListener("click", () => {
  PLANS.push({image_paroles: "", ambiance: "", enchainement: "suite"});
  dessinerPlans();
});

async function suivreScenario(sid){
  const sc = await attendreScenario(sid);
  chargerClips();
  rafraichir();
  if (sc.etat !== "réussi") return scenarioEtat("Scénario " + sc.etat + (sc.erreur ? " : " + sc.erreur : "."), true);
  await chargerScenarios();
  await ouvrirScenario(sid);
  scenarioEtat("Scénario tourné : " + sc.plans.length + " plans recollés.");
}

document.getElementById("scenario_tourner").addEventListener("click", async () => {
  try {
    await tournerScenario();
  } catch (e) {
    scenarioEtat(e.message, true);
  } finally {
    libre();
  }
});

function corpsScenario(){
  const graine = document.getElementById("graine").value;
  const f1 = document.getElementById("scenario_fiche").value, f2 = document.getElementById("scenario_fiche2").value;
  const l1 = document.getElementById("scenario_langue1").value, l2 = document.getElementById("scenario_langue2").value;
  const deux = f1 && f2 && f1 !== f2;
  // Les objets et poses cochés suivent les personnages : les personnages gardent
  // les premiers <Subject N>, et le premier parle par défaut.
  const toutes = f1 ? fichesDuScenario() : [];
  const plusieurs = toutes.length > 1;
  return {
    plans: PLANS, fiche: plusieurs ? null : (f1 || null), fiches: plusieurs ? toutes : null,
    langues: deux ? {[f1]: l1, [f2]: l2} : null,
    musique_chanson: document.getElementById("scenario_chanson").value || null,
    musique_a_partir_du_plan: Number(document.getElementById("scenario_musique_plan").value) || 1,
    langue: f1 ? l1 : document.getElementById("langue").value,
    musique: document.getElementById("musique").value,
    longueur: Number(document.getElementById("longueur").value),
    definition: document.getElementById("definition").value,
    decor: document.getElementById("scenario_decor").value || null,
    plan_par_plan: document.getElementById("scenario_plan_par_plan").checked,
    invite_legere: document.getElementById("scenario_invite_legere").checked,
    graine: graine === "" ? null : Number(graine)};
}

async function tournerScenario(forcer){
  occupe("Contrôle des règles et traduction des plans (gratuit)…");
  const r = await fetch("/video-h3/scenario/tourner", {method: "POST", headers: H,
                                                       body: JSON.stringify(Object.assign(corpsScenario(), {forcer: !!forcer, ou: OU}))});
  const d = await r.json();
  // La correction d'avant tournage (01/10) : les plans corrigés reviennent à la page,
  // refusés ou partis, pour que ce qui se voit soit ce qui se tourne.
  const corr = (d.detail && d.detail.correction) || d.correction;
  const corriges = (d.detail && d.detail.plans) || (corr && corr.corrige && d.plans);
  if (corr && corr.corrige && corriges){ PLANS = corriges; dessinerPlans(); }
  const dit = corr ? (corr.corrige ? "Le Studio a corrigé " + corr.trouvees + " remarque(s) avant de tourner. "
                                   : "Correction avant le tournage non gardée" + (corr.erreur ? " : " + corr.erreur : "") + ". ") : "";
  if (!r.ok){
    // Une règle non suivie : « Tourner quand même » est offert, sauf pour la voix (règle 4).
    document.getElementById("scenario_forcer").hidden = !(d.detail && d.detail.passe_droit);
    throw new Error(dit + messageDeRefus(d));
  }
  if (dit) scenarioEtat(dit);
  document.getElementById("scenario_forcer").hidden = true;
  if (d.regles) dessinerRegles(d.regles, "Avant le tournage");
  await suivreScenario(d.id);
  // Le juge gratuit passe de lui-même : le 29/09, un film fini sans jugement
  // cachait un visage qui ne ressemblait plus à sa fiche dès le deuxième plan.
  if (SCENARIO_TOURNE === d.id) await actionJuger();
}

document.getElementById("rejouer_forcer").addEventListener("click", async () => {
  if (!SCENARIO_TOURNE) return;
  try {
    await actionRejouer(true);
  } catch (e) {
    scenarioEtat(e.message, true);
  } finally {
    libre();
  }
});

document.getElementById("scenario_forcer").addEventListener("click", async () => {
  try {
    await tournerScenario(true);
  } catch (e) {
    scenarioEtat(e.message, true);
  } finally {
    libre();
  }
});

document.getElementById("scenario_verifier").addEventListener("click", async () => {
  occupe("Vérification des règles (gratuit)…");
  try {
    const d = await appeler("/video-h3/scenario/verifier", corpsScenario());
    dessinerRegles(d.rapport, "Avant le tournage");
    scenarioEtat(d.non_suivies.length ? d.non_suivies.length + " règle(s) non suivie(s) : corrigez les plans, "
                 + "ou tournez quand même." : "Toutes les règles vérifiables avant le tournage sont suivies.",
                 !!d.non_suivies.length);
  } catch (e) {
    scenarioEtat(e.message, true);
  } finally {
    libre();
  }
});

document.getElementById("scenario_arreter").addEventListener("click", async () => {
  if (!SCENARIO) return;
  await fetch("/video-h3/scenario/" + SCENARIO + "/arreter", {method: "POST", headers: H, body: "{}"});
  scenarioEtat("Arrêt demandé : aucun plan de plus.");
});

brancherBord("premiere");
brancherBord("derniere");
document.getElementById("image_paroles").addEventListener("input", majInvitesImages);
// Une seule partie de la page à la fois, choisie dans le menu du haut ; le choix
// est retenu pour ce navigateur seulement (sans lui, la page ouvre sur le clip).
function montrerSection(id){
  if (!document.getElementById(id)) id = "clip";
  for (const s of document.querySelectorAll(".section")) s.hidden = s.id !== id;
  document.getElementById("section_choix").value = id;
  try { localStorage.setItem("h3_section", id); } catch (e) {}
}
document.getElementById("section_choix").addEventListener("change", e => montrerSection(e.target.value));
let SECTION_DEPART = "clip";
try { SECTION_DEPART = localStorage.getItem("h3_section") || "clip"; } catch (e) {}
montrerSection(SECTION_DEPART);
document.getElementById("barre_alerte").addEventListener("click", () => montrerSection("reglages"));

rafraichir().then(majInvitesImages).then(() => chargerFiches("")).then(chargerClips).then(chargerScenarios);
</script>
</body>
</html>
""".replace("__AIDE_MARQUES_image_paroles__", aide_marques("image_paroles")).replace(
    "__AIDE_MARQUES_scenario__", aide_marques("scenario")).replace("__LANGUES__", "".join(
    f'<option value="{code}"{" selected" if code == LANGUE_PAROLES else ""}>{nom}</option>'
    for code, nom in LANGUES_PAROLES.items())).replace("__HORS_CHAMP__", json.dumps(
    sorted({_norme_replique(h) for h in HORS_CHAMP + _HORS_CHAMP_DEDANS}))).replace("__ENCHAINEMENTS__", json.dumps(ENCHAINEMENTS,
                                                                                      ensure_ascii=False)).replace(
    "__CAMERA__", json.dumps({"mouvements": {k: v[0] for k, v in CAMERA_MOUVEMENTS.items()},
                              "amplitudes": CAMERA_AMPLITUDES, "vitesses": CAMERA_VITESSES,
                              "sans_reglage": list(_CAMERA_SANS_REGLAGE), "defaut": CAMERA_DEFAUT},
                             ensure_ascii=False))
