"""Kaggle grise pour la version LoRA : l'option dit pourquoi.

Capture du proprietaire, 23/09/2026 : << Kaggle apparait mais n'est pas
selectionnable >>. C'etait voulu -- la LoRA n'a ete verifiee que sur Modal --
mais la raison n'etait ecrite qu'a la fin d'un long paragraphe.
"""
from __future__ import annotations

import importlib
import json
import shutil
import subprocess
import sys

import pytest

from conftest import RACINE

sys.path.insert(0, str(RACINE / "sandbox-manager"))
chanson = importlib.import_module("chanson")


def _option_kaggle(lora: bool, tmp_path, kaggle_permis=True) -> dict:
    if not shutil.which("node"):
        pytest.skip("node absent")
    page = chanson.PAGE_HTML
    debut = page.index('const KAGGLE_LIBELLE')
    fin = page.index('document.getElementById("modele").addEventListener("change", majModele);')
    programme = """
const kaggle = {disabled: false, textContent: "Kaggle — gratuit, plus lent"};
const els = {};
const document = {
  getElementById: id => els[id] || (els[id] = {hidden: false, disabled: false, value: "modal",
                                             textContent: "", innerHTML: "", placeholder: ""}),
  querySelector: () => kaggle,
};
let ETAT = {kaggle_permis: %s, lora: null};
const PAROLES_ORIGINE = "", STYLE_ORIGINE = "", STYLE_LORA = "";
function estLora(){ return %s; }
function majBouton(){}
function majOu(){}
""" % (json.dumps(kaggle_permis), json.dumps(lora)) + page[debut:fin] + """
majModele();
console.log(JSON.stringify(kaggle));
"""
    fichier = tmp_path / "kaggle.js"
    fichier.write_text(programme, encoding="utf-8")
    fait = subprocess.run(["node", str(fichier)], capture_output=True, text=True,
                          encoding="utf-8", timeout=20)
    assert fait.returncode == 0, fait.stderr
    return json.loads(fait.stdout)


def test_avec_la_LoRA_l_option_grisee_dit_pourquoi(tmp_path):
    k = _option_kaggle(True, tmp_path)
    assert k["disabled"] is True
    assert "Modal seulement" in k["textContent"]


def test_sans_la_LoRA_kaggle_redevient_normal(tmp_path):
    k = _option_kaggle(False, tmp_path)
    assert k["disabled"] is False
    assert k["textContent"] == "Kaggle — gratuit, plus lent"


def test_un_Studio_partage_garde_SA_raison(tmp_path):
    """Le Studio partage ferme Kaggle pour une autre raison : la LoRA ne doit
    pas la remplacer par la sienne."""
    k = _option_kaggle(True, tmp_path, kaggle_permis=False)
    assert "Modal seulement" not in k["textContent"]
