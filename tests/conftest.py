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
# L'amorce du budget ne part pas sous test, POUR TOUTE LA SESSION : des tests
# chargent app.py sans la fixture `sandbox` (test_coffre, test_kaggle), et le
# fil parti a leur chargement lancait le VRAI `modal billing` avec le jeton
# factice d'un voisin, puis remplissait le cache des depenses sous
# test_sans_jeton_rien_n_est_lance (trace du 23/09/2026). Les tests de
# l'amorce appellent amorcer() eux-memes.
os.environ["SANDBOX_AMORCE_BUDGET"] = "false"
# Meme regle, meme cause, pour la reprise des travaux orphelins (24/09/2026).
# La fixture `sandbox` la coupait, mais test_kaggle, test_garde_exposition et
# test_magasin_cles chargent app.py sans elle : leur fil `reprise-travaux`
# parcourait les fiches du dossier COMMUN pendant les tests suivants, lisait
# une fiche en cours, la declarait orpheline et la reecrivait apres coup.
# C'etait l'echec intermittent de test_local_d_abord (vu les 23 et 24/09,
# jamais sur le meme test) : fil mesure vivant pendant ses quatre premiers
# tests, fiche finie chez Modal remise a << local >> en reproduction forcee.
# test_reprise.py appelle reprendre_les_travaux() lui-meme.
os.environ["SANDBOX_REPRISE_AU_DEMARRAGE"] = "false"
# La cle du coffre vit hors de config/ ; son defaut est /secrets/coffre.cle, qui
# sous Windows voudrait dire C:\secrets. Une suite de tests ne cree pas un
# dossier a la racine du disque. UNE seule cle pour toute la suite : deux tests
# qui s'ecrivent des cles differentes ne se reliraient pas.
os.environ.setdefault("STUDIO_COFFRE_FICHIER", str(_JETABLE / "coffre.cle"))

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
    # STUDIO_HEBERGE et STUDIO_ADRESSE_PUBLIEE : depuis le 19/09/2026 le routeur
    # REFUSE de charger si elles annoncent une instance exposee. Un poste dont le
    # .env les porte ferait echouer toute la suite pour une raison etrangere a ce
    # qui est teste. test_garde_exposition.py les pose explicitement.
    for nom in ("GEMINI_FREE_MODEL", "GEMINI_MAX_MODEL", "ENABLE_GEMINI", "ENABLE_GEMINI_MAX",
                "GROQ_API_KEY", "ALLOW_FREE_TIER_ACCOUNTS", "FREE_ONLY",
                "STUDIO_HEBERGE", "STUDIO_ADRESSE_PUBLIEE"):
        monkeypatch.delenv(nom, raising=False)
    monkeypatch.setenv("FREE_AI_CONFIG_DIR", str(_JETABLE / ("config-%d" % next(_numero))))
    return charger("free-tier-manager")


@pytest.fixture
def service_voix():
    """Le service de la voix (Piper, GPL), charge sans Piper : ses tests ne
    touchent ni au modele ni au calcul."""
    return charger("voix")


@pytest.fixture
def sandbox(monkeypatch):
    """Le gestionnaire de bacs a sable, sans Modal ni Kaggle configures."""
    monkeypatch.setenv("SANDBOX_MANAGER_KEY", "cle-sandbox-de-test")
    for nom in ("STUDIO_HEBERGE", "STUDIO_ADRESSE_PUBLIEE", "WEBUI_AUTH",
                "KAGGLE_ENABLED", "KAGGLE_USERNAME",
                "KAGGLE_KEY", "KAGGLE_API_TOKEN", "MODAL_ENABLED", "MODAL_TOKEN_ID",
                "MODAL_TOKEN_SECRET"):
        monkeypatch.delenv(nom, raising=False)
    monkeypatch.setenv("FREE_AI_CONFIG_DIR", str(_JETABLE / ("config-%d" % next(_numero))))
    # La reprise des travaux orphelins ne part PAS toute seule ici. La suite
    # charge ce module des dizaines de fois ; une reprise lancee a chaque
    # chargement ecrirait dans les fiches d'un autre test, et un test qui echoue
    # a cause de son voisin est pire qu'un test manquant. `test_reprise.py`
    # appelle `reprendre_les_travaux()` lui-meme : c'est ce qu'il verifie.
    monkeypatch.setenv("SANDBOX_REPRISE_AU_DEMARRAGE", "false")
    # write_job() donne le dossier du job au compte du worker (uid 10001) : sans
    # objet hors conteneur, et os.chown n'existe pas sous Windows.
    monkeypatch.setattr(os, "chown", lambda *args: None, raising=False)
    return charger("sandbox-manager")
