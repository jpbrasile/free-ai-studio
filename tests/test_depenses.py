"""Depenses reelles : ce que le Studio demande a Modal, et ce qu'il en fait.

Aucun appel reseau : la CLI Modal n'est jamais lancee pour de vrai. Ce qui est
verifie ici, c'est le contrat du module -- il ne leve jamais, il ne lance rien
sans jeton, et il n'invente aucun montant quand la reponse est illisible -- plus
le fait que la route qui rend ces montants est authentifiee.
"""
from __future__ import annotations

import subprocess

import pytest
from fastapi.testclient import TestClient

CLE = {"Authorization": "Bearer cle-sandbox-de-test"}

# Reponse RELEVEE le 16/09/2026 sur l'espace de travail, copiee telle quelle.
# Une maquette inventee aurait valide les noms de champs que le module devinait
# -- et ils etaient faux. Ce qui suit est ce que Modal envoie vraiment.
REPONSE_DU_16_09 = """{
  "metered_cost": "1.08346824",
  "billed_cost": "0E-8",
  "adjustments": {
    "reservation_adjustment": "-0E-8",
    "plan_cost": "0E-8",
    "credits": "-0.70000000",
    "free_storage": "-0.38346824"
  },
  "metered_cost_breakdown": {
    "llm_tokens": "0E-8",
    "deployed_apps": "0.70356317",
    "volumes": "0.38346824"
  }
}"""


@pytest.fixture
def dep(sandbox):
    """Le module depenses, cache vide : il est partage entre les tests."""
    module = sandbox.depenses
    module._CACHE.clear()
    return module


def _fin(code=0, out="", err=""):
    return subprocess.CompletedProcess(args=["modal"], returncode=code, stdout=out, stderr=err)


def test_sans_jeton_rien_n_est_lance(dep, monkeypatch):
    """Pas de jeton : on le dit, et surtout on ne cree aucun processus."""
    appels = []
    monkeypatch.setattr(dep.subprocess, "run", lambda *a, **k: appels.append(a))

    etat = dep.etat()

    assert etat["disponible"] is False
    assert "jeton" in etat["raison"].lower()
    assert appels == []


def test_montants_reconnus_puis_caches(dep, monkeypatch):
    monkeypatch.setenv("MODAL_TOKEN_ID", "ak-factice")
    monkeypatch.setenv("MODAL_TOKEN_SECRET", "as-factice")
    appels = []

    def faux(cmd, **kw):
        appels.append(cmd)
        return _fin(out=REPONSE_DU_16_09)

    monkeypatch.setattr(dep.subprocess, "run", faux)

    etat = dep.etat()
    assert etat["disponible"] is True
    montants = etat["montants"]
    assert montants["facture"] == 0.0            # rien n'est paye : les credits couvrent
    assert montants["mesure"] == 1.08346824
    assert montants["calcul"] == 0.70356317      # sous metered_cost_breakdown
    assert montants["stockage"] == 0.38346824    # compte, puis offert ci-dessous
    assert montants["credits"] == -0.7           # sous adjustments
    assert montants["stockage_offert"] == -0.38346824
    assert "--json" in appels[0]

    # Un chiffre de facturation ne bouge pas a la seconde, et chaque appel cree
    # un processus : le second passage ne relance rien.
    encore = dep.etat()
    assert encore["depuis_cache"] is True
    assert len(appels) == 1


def test_echec_ne_leve_pas_et_garde_la_sortie(dep, monkeypatch):
    monkeypatch.setenv("MODAL_TOKEN_ID", "ak-factice")
    monkeypatch.setenv("MODAL_TOKEN_SECRET", "as-factice")
    monkeypatch.setattr(dep.subprocess, "run",
                        lambda *a, **k: _fin(code=1, err="Token missing."))

    etat = dep.etat()

    assert etat["disponible"] is False
    assert "Token missing." in etat["brut"]
    assert etat["montants"] == {}


def test_reponse_illisible_n_invente_aucun_montant(dep, monkeypatch):
    """Si Modal repond autre chose que du JSON, on rend sa sortie telle quelle
    plutot que de deviner un chiffre."""
    monkeypatch.setenv("MODAL_TOKEN_ID", "ak-factice")
    monkeypatch.setenv("MODAL_TOKEN_SECRET", "as-factice")
    monkeypatch.setattr(dep.subprocess, "run",
                        lambda *a, **k: _fin(out="Total Spend   $0.00"))

    etat = dep.etat()

    assert etat["disponible"] is False
    assert etat["montants"] == {}
    assert etat["brut"].startswith("Total Spend")


def test_delai_depasse_et_commande_absente(dep, monkeypatch):
    monkeypatch.setenv("MODAL_TOKEN_ID", "ak-factice")
    monkeypatch.setenv("MODAL_TOKEN_SECRET", "as-factice")

    def trop_long(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, dep.DELAI_S)

    monkeypatch.setattr(dep.subprocess, "run", trop_long)
    etat = dep.etat()
    assert etat["disponible"] is False and "pas répondu" in etat["raison"]

    dep._CACHE.clear()

    def absente(cmd, **kw):
        raise FileNotFoundError("modal")

    monkeypatch.setattr(dep.subprocess, "run", absente)
    etat = dep.etat()
    assert etat["disponible"] is False and "modal" in etat["raison"]


def test_lecture_des_montants():
    """Un montant peut arriver en nombre ou en texte ; le reste n'est pas
    converti, parce que ne pas savoir vaut mieux que se tromper de facteur."""
    import sys

    dep = sys.modules["depenses"]
    assert dep._nombre("$0.73") == 0.73
    assert dep._nombre("1,234.50") == 1234.5
    assert dep._nombre(2) == 2.0
    assert dep._nombre("gratuit") is None
    assert dep._nombre(True) is None
    assert dep._nombre(None) is None


def test_route_authentifiee(sandbox, monkeypatch):
    """Ces montants sont ceux d'un compte : /etat rend des booleens sans
    authentification, celle-ci non."""
    client = TestClient(sandbox.app)
    assert client.get("/depenses/etat").status_code in (401, 403)

    sandbox.depenses._CACHE.clear()
    reponse = client.get("/depenses/etat", headers=CLE)
    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["disponible"] is False  # aucun jeton dans les tests
    assert "jeton" in corps["raison"].lower()
