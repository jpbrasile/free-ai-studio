"""La cle du routeur hors des copies du chat (docs/SAUVEGARDES.md, proposition (1), 27/09/2026).

Open WebUI garde la cle interne du routeur en clair dans `webui.db` (table
`config`, quatre lignes, mesure du 26/09). scripts/cle_routeur_chat.py la
retire d'une COPIE avant l'archive et la remet a la restauration. Ici :
l'outil lui-meme sur de vraies bases SQLite (journal WAL comme Open WebUI), et
les deux scripts PowerShell relus comme du texte.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
OUTIL = RACINE / "scripts" / "cle_routeur_chat.py"
SAUVE = (RACINE / "scripts" / "sauvegarder.ps1").read_text(encoding="utf-8")
RESTAURE = (RACINE / "scripts" / "restaurer.ps1").read_text(encoding="utf-8")
REMETTRE_CHEMIN = RACINE / "scripts" / "remettre-cle-routeur.ps1"
REMETTRE = REMETTRE_CHEMIN.read_text(encoding="utf-8")

_spec = importlib.util.spec_from_file_location("cle_routeur_chat", OUTIL)
crc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(crc)

CLE = "a" * 20 + "0123456789abcdef" * 2 + "b" * 12   # 64 signes, comme la vraie
AUTRE = "c" * 64
LIGNES = {
    "openai.api_keys": json.dumps([CLE]),
    "image_generation.openai.api_key": json.dumps(CLE),
    "audio.stt.openai.api_key": json.dumps(CLE),
    "audio.tts.openai.api_key": json.dumps(CLE),
    "ui.title": json.dumps("Mon chat"),
}


def _base(dossier: Path, lignes=LIGNES) -> Path:
    """Une base comme celle d'Open WebUI : table config(key, value, updated_at), WAL."""
    base = dossier / "webui.db"
    con = sqlite3.connect(base)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE config (key TEXT PRIMARY KEY, value TEXT, updated_at INTEGER)")
    con.executemany("INSERT INTO config VALUES (?, ?, 1)", list(lignes.items()))
    con.commit()
    con.close()
    return base


def _valeurs(base: Path) -> dict:
    con = sqlite3.connect(base)
    d = dict(con.execute("SELECT key, value FROM config"))
    con.close()
    return d


def _lancer(mode: str, dossier: Path, cle: str | None = CLE):
    env = {k: v for k, v in os.environ.items() if k != "FAS_CLE_ROUTEUR"}
    if cle is not None:
        env["FAS_CLE_ROUTEUR"] = cle
    return subprocess.run([sys.executable, str(OUTIL), mode, str(dossier)],
                          capture_output=True, text=True, env=env)


# --- L'outil, sur de vraies bases -------------------------------------------

def test_retirer_ne_laisse_la_cle_dans_aucun_fichier_de_la_copie(tmp_path):
    _base(tmp_path)
    (tmp_path / "uploads").mkdir()
    (tmp_path / "uploads" / "note.txt").write_text("rien de secret")
    r = _lancer("retirer", tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.strip().splitlines()[-1] == "RESULTAT lignes=4 restes="
    assert crc.fichiers_qui_portent(tmp_path, CLE.encode()) == []
    v = _valeurs(tmp_path / "webui.db")
    assert json.loads(v["openai.api_keys"]) == [crc.MARQUE]
    assert json.loads(v["audio.tts.openai.api_key"]) == crc.MARQUE
    assert v["ui.title"] == LIGNES["ui.title"]           # le reste ne bouge pas
    assert CLE not in r.stdout and CLE not in r.stderr   # jamais affichee


def test_le_controle_rougit_sur_l_etat_d_avant(tmp_path):
    """Rouge d'abord : une copie faite comme avant le 27/09 porte la cle, et le
    controle la trouve -- dans la base ET dans une copie brute de son journal."""
    base = _base(tmp_path)
    assert crc.fichiers_qui_portent(tmp_path, CLE.encode()) == ["webui.db"]
    (tmp_path / "webui.db-wal.copie").write_bytes(base.read_bytes())
    assert "webui.db-wal.copie" in crc.fichiers_qui_portent(tmp_path, CLE.encode())


def test_une_cle_ailleurs_que_dans_la_base_arrete_la_sauvegarde(tmp_path):
    _base(tmp_path)
    (tmp_path / "cache").mkdir()
    (tmp_path / "cache" / "reglages.json").write_text(json.dumps({"k": CLE}))
    r = _lancer("retirer", tmp_path)
    assert r.returncode == 3
    assert r.stdout.strip().splitlines()[-1] == "RESULTAT lignes=4 restes=cache/reglages.json"
    assert CLE not in r.stdout


def test_la_cle_coupee_entre_deux_blocs_est_trouvee(tmp_path, monkeypatch):
    monkeypatch.setattr(crc, "BLOC", 7)
    (tmp_path / "f.bin").write_bytes(b"xx" + CLE.encode() + b"yy")
    assert crc.fichiers_qui_portent(tmp_path, CLE.encode()) == ["f.bin"]


def test_l_ancienne_valeur_ne_survit_pas_dans_une_page_liberee(tmp_path):
    """Sans secure_delete, un UPDATE peut laisser l'ancienne valeur lisible dans
    le fichier. Une base plus grosse, pour que la page change de place."""
    lignes = dict(LIGNES)
    lignes.update({"remplissage.%d" % i: json.dumps("x" * 900) for i in range(200)})
    _base(tmp_path, lignes)
    r = _lancer("retirer", tmp_path)
    assert r.returncode == 0, r.stdout
    assert crc.fichiers_qui_portent(tmp_path, CLE.encode()) == []


def test_remettre_rend_la_cle_de_la_cible_et_seulement_la_marque(tmp_path):
    _base(tmp_path)
    assert _lancer("retirer", tmp_path).returncode == 0
    # La cible a SA cle (un .env neuf) : c'est elle que son routeur attend.
    r = _lancer("remettre", tmp_path, cle=AUTRE)
    assert r.returncode == 0
    assert r.stdout.strip().splitlines()[-1] == "RESULTAT lignes=4 restes="
    v = _valeurs(tmp_path / "webui.db")
    assert json.loads(v["openai.api_keys"]) == [AUTRE]
    assert json.loads(v["image_generation.openai.api_key"]) == AUTRE
    assert v["ui.title"] == LIGNES["ui.title"]
    # Relancer ne fait rien de plus.
    assert _lancer("remettre", tmp_path, cle=AUTRE).stdout.strip().endswith("lignes=0 restes=")


@pytest.mark.parametrize("cle", [None, "", "court"])
def test_sans_cle_ou_avec_une_cle_trop_courte_rien_ne_change(tmp_path, cle):
    _base(tmp_path)
    avant = _valeurs(tmp_path / "webui.db")
    r = _lancer("retirer", tmp_path, cle=cle)
    assert r.returncode == 2
    assert _valeurs(tmp_path / "webui.db") == avant


# --- Les scripts PowerShell ---------------------------------------------------

def _code(texte: str) -> str:
    return "\n".join(l for l in texte.splitlines() if not l.lstrip().startswith("#"))


def test_la_cle_passe_au_conteneur_par_son_nom_jamais_par_sa_valeur():
    # La variable qui porte la cle du routeur, dans chaque script. ($Cle de
    # sauvegarder.ps1 est l'etat de la cle du COFFRE, dont l'empreinte s'affiche.)
    for texte, variable in ((SAUVE, r"\$CleRouteur\b"), (REMETTRE, r"\$Cle\b")):
        code = _code(texte)
        assert '"-e", "FAS_CLE_ROUTEUR",' in code
        assert not re.search(r'"-e",\s*\(?"FAS_CLE_ROUTEUR=', code)
        assert "Remove-Item Env:FAS_CLE_ROUTEUR" in code     # retiree apres, dans un finally
        for ligne in code.splitlines():
            if re.search(r"Write-Host|\b(Bon|Note|Souci|Arreter) ", ligne):
                assert not re.search(variable, ligne), ligne


def test_l_archive_et_les_empreintes_sont_faites_sur_la_copie_nettoyee():
    code = _code(SAUVE)
    i = code.index("mkdir /travail && cp -a /donnees/. /travail/")
    j = code.index("python /scripts/cle_routeur_chat.py retirer /travail && cd /travail && ")
    assert i < j
    # Le volume vivant n'est monte qu'en lecture.
    assert '($NomsVolumes[$court] + ":/donnees:ro")' in code
    # Un echec retire l'archive commencee et arrete la sauvegarde.
    assert 'Remove-Item -LiteralPath (Join-Path $Dossier ($court + ".tar")) -Force' in code
    assert "n'a pas pu etre copie sans la cle du routeur." in code
    assert "cle_du_routeur = $CleRouteurEtat" in code


def test_la_restauration_remet_la_cle_ou_dit_comment():
    code = _code(RESTAURE)
    assert "$Manifeste.cle_du_routeur.retiree" in code
    assert 'Join-Path $PSScriptRoot "remettre-cle-routeur.ps1"' in code
    assert "sans elle, le chat restaure est refuse par son routeur" in code


def test_remettre_ne_lit_que_le_env_de_la_cible_et_refuse_un_chat_en_marche():
    code = _code(REMETTRE)
    assert '$cheminEnv = Join-Path $Dossier ".env"' in code
    assert "'^FREE_TIER_MANAGER_KEY=(.*)$'" in code
    assert "GetEnvironmentVariable" not in code
    assert "tourne." in code and "Rien n'a ete ecrit." in code


def test_remettre_suit_les_regles_des_scripts_du_depot():
    brut = REMETTRE_CHEMIN.read_bytes()
    assert not brut.startswith(b"\xef\xbb\xbf")
    assert not [c for c in brut if c > 127]
    code = _code(REMETTRE)
    assert code.index('$ErrorActionPreference = "Stop"') < code.index("function ")
    assert "2>&1" not in code and "Out-File" not in code
