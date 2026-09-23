"""La voix du bouton << lire a haute voix >> : Piper, dans son propre conteneur.

POURQUOI UN SERVICE A PART (decision du proprietaire, PLAN.md point 15, 23/09/2026).
Piper 1.8.0 est sous GPL-3.0-or-later -- lu dans les metadonnees du paquet
installe le 23/09/2026, `License: GPL-3.0-or-later` -- et embarque espeak-ng.
Jusqu'a ce jour, le routeur (MIT) l'importait dans son propre processus. Il
l'appelle desormais par HTTP, comme les autres moteurs, et n'importe plus rien
de GPL. Ce n'est pas un avis juridique : le montage reduit le risque, il ne le
tranche pas.

Ce service ne fait que trois choses : garder les voix (telechargees a une
revision fixe, empreinte verifiee), les charger, et lire UN morceau de texte
dans UNE langue. Le nettoyage du texte, le decoupage par langue et le collage
des morceaux restent au routeur.

Pas de cle : le port n'est publie nulle part, seul le reseau du compose le
joint, et ce qu'il rend est un son a partir d'un texte qu'on lui donne.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import os
import threading
import wave
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("voix")

# Essai du 15/09/2026 dans un conteneur python:3.12-slim jetable, 4 coeurs :
# chargement 1,7 s ; 7,2 s de parole calculees en 0,6 s ; 313 Mo de memoire.
# Depot rhasspy/piper-voices a une revision fixe, et empreintes SHA-256 relevees
# sur Hugging Face : les fichiers ne changent pas sous nos pieds.
VOIX_REVISION = "1162a9173d0ce503555aed757976b7a9912eae4c"
DEPOT_VOIX = "https://huggingface.co/rhasspy/piper-voices/resolve/%s/" % VOIX_REVISION
# Une voix par langue. Les deux sonnent a 22 050 Hz, en mono 16 bits : le
# routeur colle donc les morceaux bout a bout sans conversion.
VOIX = {
    # Base SIWIS (Universite d'Edimbourg), CC BY 4.0. Relevee le 15/09/2026.
    "fr": {"nom": "fr_FR-siwis-medium", "dossier": "fr/fr_FR/siwis/medium/",
           "sha256": "641d1ab097da2b81128c076810edb052b385decc8be3381814802a64a73baf99",
           "octets": 63_201_294},
    # Enregistrements LibriVox, domaine public, entrainee de zero. Relevee le
    # 16/09/2026. Les autres voix anglaises de Piper sont soit dans le domaine
    # de la licence Blizzard (lessac), soit non commerciales (hfc_female).
    "en": {"nom": "en_US-norman-medium", "dossier": "en/en_US/norman/medium/",
           "sha256": "b9739443232a80a59c7d18810dd856899bf16a7964725f5ab81ea49b1351cb71",
           "octets": 63_531_379},
}
# Le meme dossier qu'avant le 23/09 : les voix deja telechargees par le routeur
# servent telles quelles (volume partage, voir docker-compose.yml).
VOIX_DOSSIER = Path(os.getenv("VOIX_DIR", "/modeles/piper"))
VOIX_MAX_CARACTERES = 10_000
_voix: Dict[str, Any] = {}
_voix_verrou = threading.Lock()


def _telecharger(url: str, cible: Path, sha256: Optional[str] = None) -> None:
    """A cote puis renomme : un telechargement coupe ne laisse jamais un fichier
    a moitie ecrit a la place de la voix."""
    partiel = cible.with_name(cible.name + ".partiel")
    empreinte = hashlib.sha256()
    try:
        with httpx.Client(follow_redirects=True,
                          timeout=httpx.Timeout(60.0, connect=15.0)) as client:
            with client.stream("GET", url) as r:
                r.raise_for_status()
                with open(partiel, "wb") as f:
                    for bout in r.iter_bytes(1 << 20):
                        empreinte.update(bout)
                        f.write(bout)
        if sha256 and empreinte.hexdigest() != sha256:
            raise RuntimeError("voix telechargee abimee : empreinte differente de celle relevee")
        partiel.replace(cible)
    finally:
        partiel.unlink(missing_ok=True)


def telecharger_voix(langue: str = "fr") -> Path:
    """La voix d'une langue, telechargee une fois (63 Mo) ; rend son chemin."""
    voix = VOIX[langue]
    url = DEPOT_VOIX + voix["dossier"]
    VOIX_DOSSIER.mkdir(parents=True, exist_ok=True)
    modele = VOIX_DOSSIER / ("%s.onnx" % voix["nom"])
    reglages = VOIX_DOSSIER / ("%s.onnx.json" % voix["nom"])
    if not reglages.exists():
        _telecharger(url + reglages.name, reglages)
    if not modele.exists():
        _telecharger(url + modele.name, modele, voix["sha256"])
    return modele


def prechauffer_voix() -> None:
    """Telecharge les voix au demarrage : le premier 🔊 n'attend pas les 63 Mo."""
    for langue, voix in VOIX.items():
        try:
            telecharger_voix(langue)
        except Exception as exc:  # reseau coupe, disque plein
            log.warning("Voix non telechargee d'avance (%s) : %s", voix["nom"], exc)
            continue
        log.info("Voix prete (%s)", voix["nom"])


def synthetiser(langue: str, texte: str, vitesse: float) -> bytes:
    """Un WAV 16 bits mono. Un calcul a la fois : deux lectures simultanees se
    partageraient les memes coeurs."""
    from piper import PiperVoice, SynthesisConfig  # lourd : importe seulement ici

    reglages = SynthesisConfig(length_scale=1.0 / vitesse)
    with _voix_verrou:
        if _voix.get(langue) is None:
            _voix[langue] = PiperVoice.load(str(telecharger_voix(langue)))
        tampon = io.BytesIO()
        with wave.open(tampon, "wb") as w:
            _voix[langue].synthesize_wav(texte, w, syn_config=reglages)
    return tampon.getvalue()


@asynccontextmanager
async def demarrage_et_arret(_app: FastAPI):
    # Dans un fil a part : le telechargement ne bloque pas le service.
    asyncio.create_task(asyncio.to_thread(prechauffer_voix))
    yield


app = FastAPI(title="Free AI Studio - Voix", docs_url=None, redoc_url=None,
              lifespan=demarrage_et_arret)


def refus(statut: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=statut, content={"detail": message})


@app.get("/health")
async def sante():
    return {"ok": True, "voix": {langue: v["nom"] for langue, v in VOIX.items()}}


@app.post("/lire")
async def lire(request: Request):
    """{"langue": "fr"|"en", "texte": ..., "vitesse": 0.5..2.0} -> audio/wav."""
    try:
        corps = await request.json()
        langue = str(corps.get("langue") or "")
        texte = str(corps.get("texte") or "")
        vitesse = float(corps.get("vitesse") or 1.0)
    except (ValueError, AttributeError, TypeError):
        return refus(400, "demande illisible")
    if langue not in VOIX:
        return refus(400, "langue inconnue : %r" % langue)
    if not texte.strip():
        return refus(400, "rien a lire")
    if len(texte) > VOIX_MAX_CARACTERES:
        return refus(400, "texte trop long : %d caracteres au plus" % VOIX_MAX_CARACTERES)
    vitesse = min(max(vitesse, 0.5), 2.0)
    try:
        son = await asyncio.to_thread(synthetiser, langue, texte, vitesse)
    except Exception as exc:  # voix absente, paquet absent, memoire
        log.warning("Lecture en echec (%s) : %s", langue, exc)
        return refus(503, "la voix n'a pas pu lire : %s" % type(exc).__name__)
    # Le journal dit combien et dans quelle langue, jamais quoi.
    log.info("Lecture : %s, %d caracteres", VOIX[langue]["nom"], len(texte))
    return Response(content=son, media_type="audio/wav")
