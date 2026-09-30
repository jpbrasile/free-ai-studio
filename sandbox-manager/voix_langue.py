"""La voix d'un personnage dans une autre langue, clonée par FireRedTTS3 sur une carte louée.

Demande du propriétaire, 30/09/2026 : « Leila part d'une voix française et la transforme en
anglais, à l'inverse pour l'américain (il aura donc l'accent américain quand il parle
français) ». Le profil voix de la fiche (video_h3.fiche_voix) sert de référence ; le modèle
lit la phrase neutre de l'autre langue (video_h3.PHRASE_VOIX) avec ce timbre, et le résultat
devient la voix de la fiche dans cette langue : H3 la reçoit en <Audio j> pour les répliques
dites dans cette langue.

MESURÉ le 30/09 (travail 037ce6d8, L4, voix de Leila) : 14,1 Go de mémoire de carte au plus
fort ; ~10 s de calcul pour 6 s de parole ; poids chargés en 7,6 s depuis le disque Modal ;
premier téléchargement 100 s. Whisper (medium) a entendu les phrases françaises et anglaises
à 0-4,5 % de mots près, là où FireRedTTS-2 a sauté une phrase et en a inventé une autre.

PAS D'ÉMOTION ICI, et c'est voulu : le modèle de base n'en a aucun réglage (article des
auteurs, arXiv 2608.17492 ; leur code). L'émotion se joue dans le plan, par H3, qui prend le
TIMBRE de <Audio j> et le ton écrit à côté de la réplique (guide de MiniMax,
VIDEO_PROMPT_WRITING_GUIDE_ref_en.md). La référence doit donc rester neutre.

Licence : Apache-2.0, code et poids (dépôt et fiche Hugging Face des auteurs).
"""

from __future__ import annotations

import base64
import json
import os

import budget_modal

MODELE = {
    "hf": "FireRedTeam/FireRedTTS3",
    # Épinglés le 30/09/2026 : ceux de l'essai 037ce6d8, les seuls qui aient tourné ici.
    "revision": "dcf1bdcd1b8b25b382fa84c3e34eb82e3054a610",
    "code": "https://github.com/FireRedTeam/FireRedTTS3",
    "code_revision": "7a1f3a7282ff184cc1c7f070556baaf5f08b5216",
    "licence": "Apache-2.0 (code et poids)",
    "fiche": "https://huggingface.co/FireRedTeam/FireRedTTS3",
    "echantillonnage": 24000,
}
# Seul le modèle de base sert ici : 12,3 Go avec le décodeur. L'« Instruct » (8,5 Go de
# plus) ne clone pas avec émotion ; il n'est pas téléchargé.
FICHIERS_MODELE = ("campp/*", "fireredtts3_base/*", "redae/*", "text_tokenizer/*")
LANGUES = {  # nom du Studio (video_h3.LANGUES_PAROLES) -> balise du modèle
    "French": "French", "English": "English", "Spanish": "Spanish", "German": "German",
    "Italian": "Italian", "Portuguese": "Portuguese", "Arabic": "Arabic", "Chinese": "Chinese",
    "Japanese": "Japanese", "Korean": "Korean", "Russian": "Russian",
}

GPU_MODAL = os.getenv("VOIX_LANGUE_GPU", "L4")
MEMOIRE_MB = int(os.getenv("VOIX_LANGUE_MEMORY_MB", "24576"))
# Construction de l'image comprise la première fois ; ensuite ~2 min de bout en bout.
DUREE_MAX_S = int(os.getenv("VOIX_LANGUE_TIMEOUT_SECONDS", "900"))
VOLUME_MODELES = os.getenv("VIDEO_MODAL_VOLUME", "free-ai-studio-modeles")
CACHE_MODAL = "/modeles/hf"
USAGE = "dialogue"   # la parole a son compteur ; le plafond du mois est commun

# Le requirements.txt des auteurs, moins : flash_attn (remplacé par l'attention sdpa de
# PyTorch, pas de compilation), torchcodec (les WAV passent par la bibliothèque standard),
# fasttext (la langue est donnée) et faster-whisper (leur démo). Mesuré le 30/09 : suffit.
PAQUETS_MODAL = ("torch==2.8.0", "torchaudio==2.8.0", "transformers==5.6.2", "einops==0.8.2",
                 "python-dotenv", "regex", "wetext", "huggingface_hub", "numpy", "safetensors")
APT_MODAL = ("git",)
DOSSIER_CODE = "/opt/FireRedTTS3"
COMMANDES_MODAL = (
    "git clone " + MODELE["code"] + ".git " + DOSSIER_CODE,
    "cd " + DOSSIER_CODE + " && git checkout " + MODELE["code_revision"],
    "cd " + DOSSIER_CODE + " && grep -rl flash_attention_2 fireredtts3 | xargs sed -i s/flash_attention_2/sdpa/g",
)

BudgetDepasse = budget_modal.BudgetDepasse


def budget_verifier() -> dict:
    return budget_modal.verifier(USAGE, GPU_MODAL, DUREE_MAX_S, MEMOIRE_MB, quoi="La voix dans une autre langue")


def budget_consommer(secondes: float, cle: str | None = None) -> dict:
    return budget_modal.consommer(USAGE, GPU_MODAL, secondes, MEMOIRE_MB, cle=cle)


def demande(reference_wav: bytes, texte_reference: str, langue_reference: str,
            texte: str, langue: str) -> dict:
    """La demande du travail. Refuse avant toute location ce que le modèle ne sait pas faire."""
    if langue not in LANGUES or langue_reference not in LANGUES:
        raise ValueError("Cette langue n'est pas prévue pour la voix clonée.")
    if langue == langue_reference:
        raise ValueError("La voix est déjà dans cette langue.")
    if not reference_wav:
        raise ValueError("La fiche n'a pas encore de voix : posez-la d'abord.")
    if not str(texte_reference or "").strip():
        raise ValueError("Le texte dit dans la voix de référence est inconnu.")
    return {"modele": MODELE["hf"], "revision": MODELE["revision"], "fichiers": list(FICHIERS_MODELE),
            "cache": CACHE_MODAL, "reference_b64": base64.b64encode(reference_wav).decode("ascii"),
            "texte_reference": " ".join(str(texte_reference).split()), "texte": " ".join(texte.split()),
            "langue": LANGUES[langue]}


def construire_script(d: dict) -> str:
    charge = base64.b64encode(json.dumps(d, ensure_ascii=False).encode("utf-8")).decode("ascii")
    return _SCRIPT.replace("__DEMANDE__", charge)


_SCRIPT = r'''# -*- coding: utf-8 -*-
"""Clone une voix dans une autre langue avec FireRedTTS3. Généré par Free AI Studio."""
import base64, json, os, sys, time, wave
import numpy as np

D = json.loads(base64.b64decode("__DEMANDE__").decode("utf-8"))
SORTIE = os.environ.get("FREE_AI_OUTPUT_DIR", "/tmp/free_ai_output")
os.makedirs(SORTIE, exist_ok=True)
os.makedirs(D["cache"], exist_ok=True)
os.environ["HF_HOME"] = D["cache"]
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
TEMPS, DEBUT = {}, time.time()

import torch
from huggingface_hub import snapshot_download

if not torch.cuda.is_available():
    print("ECHEC : aucune carte graphique sur cette machine.", file=sys.stderr)
    sys.exit(2)

t0 = time.time()
DOSSIER = snapshot_download(D["modele"], revision=D["revision"], allow_patterns=list(D["fichiers"]))
TEMPS["poids"] = round(time.time() - t0, 1)
sys.path.insert(0, "/opt/FireRedTTS3")
from fireredtts3.core import FireRedTTS3

# Lecture et écriture des WAV par la bibliothèque standard : torchaudio récent délègue à
# torchcodec, absent de l'image (le 17/09, un rendu de FireRedTTS-2 a été perdu ainsi).
chemin = os.path.join(SORTIE, "reference.wav")
with open(chemin, "wb") as f:
    f.write(base64.b64decode(D["reference_b64"]))
with wave.open(chemin, "rb") as w:
    sr, n, c, l = w.getframerate(), w.getnframes(), w.getnchannels(), w.getsampwidth()
    brut = w.readframes(n)
os.remove(chemin)
if l != 2:
    print("ECHEC : la voix de référence n'est pas un WAV 16 bits.", file=sys.stderr)
    sys.exit(3)
x = np.frombuffer(brut, dtype="<i2").astype(np.float32).reshape(-1, c).mean(axis=1) / 32768.0
invite = torch.from_numpy(x).unsqueeze(0)

t0 = time.time()
try:
    tts = FireRedTTS3(DOSSIER, use_fasttext=False, use_wetext=True)
except Exception as exc:
    print("AVERTISSEMENT : normalisation wetext indisponible (%r), texte pris tel quel." % exc, flush=True)
    tts = FireRedTTS3(DOSSIER, use_fasttext=False, use_wetext=False)
TEMPS["chargement"] = round(time.time() - t0, 1)

t0 = time.time()
onde, sr_sortie = tts.generate(text=D["texte"], language=D["langue"], prompt_text=D["texte_reference"],
                               prompt_audio=invite, prompt_audio_sr=sr)
TEMPS["rendu"] = round(time.time() - t0, 1)

onde = onde.detach().to("cpu", torch.float32)
if onde.dim() == 1:
    onde = onde.unsqueeze(0)
onde = onde[:1]
crete = float(onde.abs().max()) if onde.numel() else 0.0
if 1.0 < crete < float("inf"):
    onde = onde / crete
entiers = (onde.clamp(-1.0, 1.0) * 32767.0).round().to(torch.int16)
with wave.open(os.path.join(SORTIE, "voix.wav"), "wb") as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(int(sr_sortie))
    w.writeframes(entiers.t().contiguous().numpy().tobytes())
resume = {"duree_s": round(onde.shape[-1] / float(sr_sortie), 2), "temps": TEMPS,
          "vram_max_go": round(torch.cuda.max_memory_allocated() / 1024 ** 3, 2),
          "carte": torch.cuda.get_device_name(0), "modele": "%s@%s" % (D["modele"], D["revision"][:12])}
with open(os.path.join(SORTIE, "resume.json"), "w", encoding="utf-8") as f:
    json.dump(resume, f)
print("VOIX_OK " + json.dumps(resume), flush=True)
'''
