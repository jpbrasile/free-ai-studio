"""Le bouton d'arret ne promet pas un arret que Kaggle ne sait pas faire.

Remarque du proprietaire, 23/09/2026 : le bouton << Arret d'urgence >>
apparaissait pour une chanson lancee sur Kaggle. Or Kaggle n'a aucune
annulation (voir `arreter_job`) : le Studio cesse d'attendre, le calcul et le
quota courent jusqu'a l'echeance. Le bouton doit dire ce qu'il fait.
"""
from __future__ import annotations

import importlib
import json
import shutil
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from conftest import RACINE

sys.path.insert(0, str(RACINE / "sandbox-manager"))

CLE = {"Authorization": "Bearer cle-sandbox-de-test"}
LOCAL = "http://127.0.0.1:8020"


@pytest.mark.parametrize("usage", ["chanson", "dialogue"])
@pytest.mark.parametrize("fournisseur", ["kaggle", "modal"])
def test_l_etat_du_travail_dit_chez_qui_il_tourne(sandbox, monkeypatch, tmp_path, usage, fournisseur):
    monkeypatch.setattr(sandbox, "JOBS", tmp_path)
    (tmp_path / "j1").mkdir()
    (tmp_path / "j1" / "job.json").write_text(json.dumps(
        {"id": "j1", "status": "running", "provider": fournisseur, usage: {}}), encoding="utf-8")
    r = TestClient(sandbox.app, base_url=LOCAL).get("/%s/jobs/j1" % usage, headers=CLE)
    assert r.json()["fournisseur"] == fournisseur


def _bouton(usage: str, fournisseur: str, tmp_path) -> dict:
    if not shutil.which("node"):
        pytest.skip("node absent")
    page = importlib.import_module(usage).PAGE_HTML
    debut = page.index("// Kaggle n'a AUCUNE annulation")
    fin = page.index("function cacherArret(")
    programme = """
let travailEnCours = null;
let fournisseurEnCours = "";
const el = {arreter: {hidden: true, disabled: true, textContent: "", className: "danger"},
            "arreter-texte": {textContent: ""}};
const document = {getElementById: id => el[id]};
""" + page[debut:fin] + """
montrerArret("j1", %s);
console.log(JSON.stringify({libelle: el.arreter.textContent, classe: el.arreter.className,
  texte: el["arreter-texte"].textContent, visible: !el.arreter.hidden}));
""" % json.dumps(fournisseur)
    fichier = tmp_path / "arret.js"
    fichier.write_text(programme, encoding="utf-8")
    fait = subprocess.run(["node", str(fichier)], capture_output=True, text=True,
                          encoding="utf-8", timeout=20)
    assert fait.returncode == 0, fait.stderr
    return json.loads(fait.stdout)


@pytest.mark.parametrize("usage", ["chanson", "dialogue"])
def test_sur_kaggle_le_bouton_dit_NE_PLUS_ATTENDRE_et_que_le_quota_court(usage, tmp_path):
    vu = _bouton(usage, "kaggle", tmp_path)
    assert vu["visible"]
    assert vu["libelle"] == "Ne plus attendre"
    assert "urgence" not in vu["libelle"].lower()
    assert "quota" in vu["texte"] and "continue" in vu["texte"]
    assert vu["classe"] != "danger"


@pytest.mark.parametrize("usage", ["chanson", "dialogue"])
def test_sur_modal_l_arret_d_urgence_reste(usage, tmp_path):
    vu = _bouton(usage, "modal", tmp_path)
    assert vu["libelle"] == "⛔ Arrêt d’urgence"
    assert vu["classe"] == "danger" and vu["texte"] == ""
