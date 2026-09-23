"""Ou vont les donnees de chaque etape d'une chaine (PLAN.md, 15.5 et 16.2).

Le client lit, AVANT de lancer, ce qui quitte sa machine et chez qui. Chaque
phrase est une promesse : ces tests tiennent la table contre les routes qui
existent, et contre ce que le code des routes fait vraiment.
"""
from __future__ import annotations

import importlib
import sys

import pytest

from conftest import RACINE

sys.path.insert(0, str(RACINE / "sandbox-manager"))
composite = importlib.import_module("composite")


@pytest.fixture(scope="module")
def apps():
    return composite.charger_registre()


def test_chaque_brique_chainable_dit_ou_vont_ses_donnees():
    """Une brique qui a une route sans phrase serait montree << inconnu >>."""
    assert set(composite.DONNEES) == set(composite.ROUTES), (
        set(composite.ROUTES) ^ set(composite.DONNEES))


@pytest.mark.parametrize("brique", ["document_lecture", "dictee_locale",
                                    "voix_fr", "voix_en"])
def test_ce_qui_reste_sur_l_ordinateur_le_dit(brique):
    d = composite.donnees_de(brique)
    assert d["sort"] == "non" and d["vers"] == []
    assert "votre ordinateur" in d["phrase"] and "ne sort pas" in d["phrase"]


@pytest.mark.parametrize("brique", ["chat_auto", "chat_max", "image_lecture"])
def test_le_chat_nomme_les_TROIS_fournisseurs_de_sa_chaine(brique):
    """Un fournisseur qui echoue passe la main au suivant : les trois recoivent."""
    d = composite.donnees_de(brique)
    assert d["sort"] == "oui"
    assert d["vers"] == ["Google", "OpenRouter", "Groq"]
    for nom in d["vers"]:
        assert nom in d["phrase"], (nom, d["phrase"])


def test_la_chaine_du_chat_est_celle_de_la_table():
    """Si le routeur change l'ordre de sa chaine Auto, la phrase ment."""
    source = (RACINE / "free-tier-manager" / "app.py").read_text(encoding="utf-8")
    assert '"gemini,openrouter,groq"' in source


@pytest.mark.parametrize("brique", ["chanson", "dialogue"])
def test_chanson_et_dialogue_d_une_chaine_partent_chez_Modal(brique):
    """Une chaine n'envoie pas `ou` : la route prend son defaut, Modal."""
    d = composite.donnees_de(brique)
    assert d["sort"] == "oui" and d["vers"] == ["Modal"]


def test_video_maison_ne_promet_PAS_plus_que_ce_que_le_code_tient():
    """Sans carte joignable, `decider_ou_fabriquer` rend Modal (FRICTIONS.md)."""
    d = composite.donnees_de("video_maison")
    assert d["sort"] == "selon la carte"
    assert "Modal" in d["phrase"]


def test_une_brique_inconnue_est_dite_inconnue_pas_locale():
    d = composite.donnees_de("brique_de_demain")
    assert d["sort"] == "inconnu"
    assert "ne sort pas" not in d["phrase"]


def test_donnees_de_rend_une_COPIE():
    """Un appelant qui modifie sa copie ne doit pas reecrire la table."""
    composite.donnees_de("chat_auto")["vers"].append("Personne")
    assert composite.DONNEES["chat_auto"]["vers"] == ["Google", "OpenRouter", "Groq"]


def test_le_verdict_porte_les_donnees_de_CHAQUE_etape(apps):
    chaine = composite.chaine_depuis_briques(["document_lecture", "chat_auto"], apps)
    verdict = composite.verifier(chaine, sonde_budget=lambda _e: None)
    assert [e["donnees"]["sort"] for e in verdict["etapes"]] == ["non", "oui"]


def test_la_page_montre_la_phrase_et_dit_que_la_demande_part_d_abord():
    """Le compilateur envoie la phrase au chat gratuit AVANT toute etape."""
    page = composite.PAGE_HTML
    assert "e.donnees.phrase" in page
    assert "id=phrase-sort" in page and "Google (Gemini)" in page
