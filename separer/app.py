"""Le fond continu d'un lieu sous les plans d'un film : DeepFilterNet3 dans son propre conteneur.

POURQUOI UN SERVICE A PART (05/10/2026, comme `voix`). DeepFilterNet tire torch (CPU) : plus
d'un gigaoctet que le Studio n'a pas à porter, ni à importer. Le Studio (sandbox-manager)
l'appelle par HTTP, au montage, avec le son du film, la fin de chaque clip et le lieu de
chaque clip ; il reçoit le son remixé (`remix.remixer`) et le rapport.

DeepFilterNet 0.5.6 : licence MIT (métadonnées du paquet, lues le 05/10/2026) ; modèle
DeepFilterNet3, téléchargé à la construction de l'image.

Pas de clé : le port n'est publié nulle part, seul le réseau du compose le joint, et ce
qu'il rend est un son calculé à partir d'un son qu'on lui donne.
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import threading
import wave
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response

import remix

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("separer")

TAUX = 48_000          # le taux de DeepFilterNet3 : le Studio envoie déjà du 48 kHz
DUREE_MAX_S = 600      # 10 min ; un film automatique de 8 séquences en fait 2
_modele: Dict[str, Any] = {}
_verrou = threading.Lock()

app = FastAPI(title="Free AI Studio — fond continu")


def _charger():
    with _verrou:
        if not _modele:
            from df.enhance import init_df
            modele, etat, _ = init_df(log_file=None)   # conteneur en lecture seule
            _modele.update(modele=modele, etat=etat)
    return _modele["modele"], _modele["etat"]


def _lire_wav(octets: bytes):
    import numpy as np
    try:
        with wave.open(io.BytesIO(octets)) as w:
            sr, n, ch, larg = w.getframerate(), w.getnframes(), w.getnchannels(), w.getsampwidth()
            brut = w.readframes(n)
    except (wave.Error, EOFError) as exc:
        raise HTTPException(400, "Le son envoyé n'est pas un WAV lisible.") from exc
    if larg != 2 or sr != TAUX:
        raise HTTPException(400, "Le son doit être en WAV 16 bits à %d Hz." % TAUX)
    if n > DUREE_MAX_S * sr:
        raise HTTPException(413, "Le son dépasse %d minutes." % (DUREE_MAX_S // 60))
    return np.frombuffer(brut, "<i2").astype(np.float32).reshape(-1, ch) / 32768


def _ecrire_wav(x) -> bytes:
    import numpy as np
    sortie = io.BytesIO()
    with wave.open(sortie, "wb") as w:
        w.setnchannels(x.shape[1])
        w.setsampwidth(2)
        w.setframerate(TAUX)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    return sortie.getvalue()


def _remixer(octets: bytes, bornes: list, lieux: list):
    import torch
    from df.enhance import enhance
    film = _lire_wav(octets)
    modele, etat = _charger()
    voix = enhance(modele, etat, torch.from_numpy(film.T.copy())).numpy().T[:len(film)]
    return remix.remixer(film, voix, TAUX, bornes, lieux)


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/remixer")
async def remixer(request: Request):
    """Corps : le son du film (WAV 16 bits, 48 kHz). Paramètres : `bornes` (fin de chaque clip,
    en secondes, séparées par des virgules) et `lieux` (l'étiquette du lieu de chaque clip).
    Rend le son remixé ; le rapport est dans l'en-tête X-Rapport (JSON)."""
    try:
        bornes = [float(b) for b in request.query_params.get("bornes", "").split(",")]
    except ValueError as exc:
        raise HTTPException(400, "Bornes illisibles.") from exc
    lieux = request.query_params.get("lieux", "").split(",")
    octets = await request.body()
    try:
        sortie, rapport = await asyncio.to_thread(_remixer, octets, bornes, lieux)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return Response(_ecrire_wav(sortie), media_type="audio/wav",
                    headers={"X-Rapport": json.dumps(rapport)})
