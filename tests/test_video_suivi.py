"""Vidéo : pendant le suivi, la page dit CE qu'elle suit.

Signalé le 23/09/2026 : après « Suivre », seul « En cours depuis 1072 s »
s'affichait, sous un formulaire resté sur 5 secondes et Modal. Le travail suivi
était un clip de 1 s chez Kaggle (ebffade9), dont la fiche disait « carte L4 ».
"""
from __future__ import annotations

import json
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

CLE = {"Authorization": "Bearer cle-sandbox-de-test"}
LOCAL = "http://127.0.0.1:8020"


def attente(page: str, job: dict) -> str:
    debut = page.index("const NOMS_FOURNISSEURS")
    fin = page.index("function suivre(id)", debut)
    code = ("const enTexte = s => String(s).replace(/</g, '&lt;');\n"
            + page[debut:fin]
            + "\nconsole.log(enAttente(" + json.dumps(job) + "));\n")
    sortie = subprocess.run(["node", "-e", code], capture_output=True, text=True,
                            encoding="utf-8", timeout=20)
    assert sortie.returncode == 0, sortie.stderr
    return sortie.stdout.strip()


@pytest.fixture
def page(sandbox):
    if not shutil.which("node"):
        pytest.skip("node absent")
    return TestClient(sandbox.app, base_url=LOCAL).get("/video").text


def test_le_suivi_dit_titre_duree_et_fournisseur(page):
    import time
    texte = attente(page, {"titre": "test kaggle", "fournisseur": "kaggle",
                           "created_at": time.time() - 1072,
                           "video": {"secondes_video": 1, "carte": "T4 (Kaggle)"}})
    assert "« test kaggle »" in texte
    assert "clip de 1 s" in texte and "sur Kaggle" in texte and "T4 (Kaggle)" in texte
    assert "17 min" in texte, "1072 s affichees en secondes brutes"
    assert "une seule fois" not in texte, (
        "Kaggle retelecharge le modele a chaque clip : « une seule fois » y est faux."
    )


def test_le_suivi_modal_garde_son_message(page):
    texte = attente(page, {"fournisseur": "modal", "video": {"secondes_video": 5}})
    assert "sur Modal" in texte and "une seule fois" in texte


def test_un_titre_n_est_jamais_du_code(page):
    texte = attente(page, {"titre": "<img src=x>", "fournisseur": "modal"})
    assert "<img" not in texte


def test_une_video_kaggle_porte_la_carte_de_kaggle(sandbox, monkeypatch):
    monkeypatch.setattr(sandbox, "kaggle_configured", lambda: True)
    monkeypatch.setattr(sandbox, "run_video", lambda *a, **k: None)
    client = TestClient(sandbox.app, base_url=LOCAL)
    r = client.post("/video/creer", headers=CLE,
                    json={"ou": "kaggle", "description": "un phare", "ou_calculer": "toujours-modal"})
    assert r.status_code == 200, r.text
    jid = r.json()["id"]
    j = client.get("/video/jobs/" + jid, headers=CLE).json()
    assert j["video"]["carte"] == "T4 (Kaggle)"
    assert j["fournisseur"] == "kaggle"
