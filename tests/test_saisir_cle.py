"""saisir-une-cle.cmd / scripts/saisir-cle.sh : une cle entre dans .env sans s'afficher.

C'est ce qui permet a un assistant d'installation d'aider sans jamais voir une
cle : la personne la saisit elle-meme, masquee. Si la saisie redevenait visible
ou si la valeur partait en argument, le README et le guide mentiraient."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
PS1 = (RACINE / "scripts" / "saisir-cle.ps1").read_text(encoding="utf-8")
SH = (RACINE / "scripts" / "saisir-cle.sh").read_text(encoding="utf-8")
CMD = (RACINE / "saisir-une-cle.cmd").read_text(encoding="utf-8")
MODELE = (RACINE / ".env.example").read_text(encoding="utf-8")


def test_la_saisie_est_masquee_des_deux_cotes():
    assert "Read-Host \"$nom\" -AsSecureString" in PS1
    assert "read -r -s -p" in SH
    # La valeur n'est jamais ecrite a l'ecran, seulement sa longueur.
    assert not re.search(r"Write-Host[^\n]*\$valeur(?!\.Length)", PS1)
    assert not re.search(r"echo[^\n]*\$valeur", SH)


def test_la_valeur_ne_passe_jamais_en_argument():
    # Un argument se lit dans la liste des processus ; l'environnement du seul python3, non.
    assert 'NOM="$1" VALEUR="$2" python3 -' in SH
    assert 'os.environ["VALEUR"]' in SH


def test_les_noms_proposes_existent_dans_env_example():
    for script, motif in ((PS1, r'@\("([A-Z0-9_]+)",'), (SH, r'^  "([A-Z0-9_]+)\|')):
        noms = re.findall(motif, script, re.M)
        assert len(noms) >= 10
        for nom in noms:
            assert re.search(rf"^{nom}=", MODELE, re.M), nom
    assert re.findall(r'@\("([A-Z0-9_]+)",', PS1) == re.findall(r'^  "([A-Z0-9_]+)\|', SH, re.M)


def test_le_double_clic_lance_le_script():
    assert r"scripts\saisir-cle.ps1" in CMD
    assert "-ExecutionPolicy Bypass" in CMD


def test_readme_et_guide_y_envoient():
    readme = (RACINE / "README.md").read_text(encoding="utf-8")
    guide = (RACINE / "docs" / "INSTALLER-AVEC-UN-ASSISTANT.md").read_text(encoding="utf-8")
    for texte in (readme, guide):
        assert "saisir-une-cle.cmd" in texte
        assert "scripts/saisir-cle.sh" in texte


@pytest.mark.skipif(shutil.which("bash") is None or shutil.which("python3") is None,
                    reason="bash et python3 requis")
def test_bout_en_bout_bash(tmp_path):
    (tmp_path / "scripts").mkdir()
    shutil.copy(RACINE / "scripts" / "saisir-cle.sh", tmp_path / "scripts")
    shutil.copy(RACINE / ".env.example", tmp_path / ".env.example")
    # D'abord une cle collee par erreur au menu : refusee SANS etre repetee.
    entree = "hf_ZQXW0collee\n5\nhf_ZQXW$1#x\no\nOPENROUTER_MANAGEMENT_KEY\nsk-or-ZQXW2\nn\nn\n"
    r = subprocess.run(["bash", "scripts/saisir-cle.sh"], cwd=tmp_path, input=entree,
                       capture_output=True, text=True, encoding="utf-8", timeout=60,
                       env={**os.environ, "MSYS_NO_PATHCONV": "1"})
    assert r.returncode == 0, r.stdout + r.stderr
    assert "ZQXW" not in r.stdout + r.stderr
    env = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "\nHF_TOKEN='hf_ZQXW$1#x'\n" in env
    assert "\nOPENROUTER_MANAGEMENT_KEY=sk-or-ZQXW2\n" in env
    # Le reste du fichier, commentaires accentues compris, est intact.
    garde = lambda t: [l for l in t.splitlines()
                       if not l.startswith(("HF_TOKEN=", "OPENROUTER_MANAGEMENT_KEY="))]
    assert garde(env) == garde(MODELE)
