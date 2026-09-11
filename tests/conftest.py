"""Chargement des services pour les tests, hors conteneur."""
from __future__ import annotations

import importlib.util
import itertools
import os
import sys
import tempfile
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]

# Les services ecrivent sous /config et /workspace, qui n'existent que dans le
# conteneur. Pose AVANT tout chargement : ils lisent ces chemins a l'import.
_JETABLE = Path(tempfile.mkdtemp(prefix="free-ai-tests-"))
os.environ.setdefault("FREE_AI_CONFIG_DIR", str(_JETABLE / "config"))
os.environ.setdefault("SANDBOX_WORKSPACE", str(_JETABLE / "workspace"))

_numero = itertools.count()


def charger(dossier: str):
    """Charge <dossier>/app.py dans un module NEUF.

    Les services lisent leur configuration a l'import : un module neuf par test
    evite qu'un reglage pose par un test deborde sur le suivant."""
    chemin = RACINE / dossier
    sys.path.insert(0, str(chemin))
    try:
        nom = "%s_%d" % (dossier.replace("-", "_"), next(_numero))
        spec = importlib.util.spec_from_file_location(nom, chemin / "app.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(chemin))


@pytest.fixture
def routeur(monkeypatch):
    """Le routeur de chat, avec une cle Gemini et une cle OpenRouter factices."""
    monkeypatch.setenv("FREE_TIER_MANAGER_KEY", "cle-interne-de-test")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-factice")
    monkeypatch.setenv("OPENROUTER_API_KEY", "openrouter-factice")
    monkeypatch.setenv("FREE_PROVIDER_ORDER", "gemini,openrouter,groq")
    monkeypatch.setenv("ENABLE_GROQ", "false")
    for nom in ("GEMINI_FREE_MODEL", "GROQ_API_KEY", "ALLOW_FREE_TIER_ACCOUNTS", "FREE_ONLY"):
        monkeypatch.delenv(nom, raising=False)
    monkeypatch.setenv("FREE_AI_CONFIG_DIR", str(_JETABLE / ("config-%d" % next(_numero))))
    return charger("free-tier-manager")


@pytest.fixture
def sandbox(monkeypatch):
    """Le gestionnaire de bacs a sable, sans Modal ni Kaggle configures."""
    monkeypatch.setenv("SANDBOX_MANAGER_KEY", "cle-sandbox-de-test")
    for nom in ("STUDIO_HEBERGE", "WEBUI_AUTH", "KAGGLE_ENABLED", "KAGGLE_USERNAME",
                "KAGGLE_KEY", "KAGGLE_API_TOKEN", "MODAL_ENABLED", "MODAL_TOKEN_ID",
                "MODAL_TOKEN_SECRET"):
        monkeypatch.delenv(nom, raising=False)
    monkeypatch.setenv("FREE_AI_CONFIG_DIR", str(_JETABLE / ("config-%d" % next(_numero))))
    # write_job() donne le dossier du job au compte du worker (uid 10001) : sans
    # objet hors conteneur, et os.chown n'existe pas sous Windows.
    monkeypatch.setattr(os, "chown", lambda *args: None, raising=False)
    return charger("sandbox-manager")
