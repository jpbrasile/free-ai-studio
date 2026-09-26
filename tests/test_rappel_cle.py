"""Le rappel « donner une clé » de demarrer.ps1 ne sort que s'il sert (27/09/2026).

Il s'affichait à chaque démarrage, clés déjà données comprises. Le lanceur
demande désormais au routeur (`/status`, comme scripts/self-test.py) quels
services de chat sont utilisables. Les trois cas ont été joués sous
PowerShell 5.1 sur la vraie fonction (routeur réel, aucun service, appel raté) ;
ce test, lui, tourne partout et garde la forme.
"""
import re
from pathlib import Path

LANCEUR = (Path(__file__).resolve().parent.parent / "scripts" / "demarrer.ps1").read_text(encoding="utf-8")


def _fin():
    return LANCEUR[LANCEUR.index("# --- 10. Ce qu'il reste a faire"):]


def test_le_rappel_n_est_plus_inconditionnel():
    fin = _fin()
    rappel = fin.index("IL RESTE UNE CHOSE")
    assert "$services = Services-De-Chat" in fin[:rappel]
    # Le rappel est dans la branche « sinon » : aucune ligne Write-Host nue.
    ligne = [l for l in fin.splitlines() if "IL RESTE UNE CHOSE" in l][0]
    assert ligne.startswith("        "), ligne


def test_le_routeur_est_interroge_avec_la_cle_interne_sans_l_afficher():
    fin = _fin()
    assert 'Uri "http://127.0.0.1:8010/status"' in fin
    assert "FREE_TIER_MANAGER_KEY" in fin
    assert not re.search(r"Write-Host[^\n]*\$m\b", fin)


def test_un_tableau_vide_reste_un_tableau():
    # Sans la virgule, PowerShell rend $null pour un tableau vide : « aucune
    # clé » passerait pour « on ne sait pas » et le rappel serait adouci à tort.
    assert "return ,@($etat.providers" in _fin()


def test_on_ne_sait_pas_garde_un_rappel_adouci():
    fin = _fin()
    assert "if ($null -eq $services)" in fin
    assert "SI CE N'EST PAS DEJA FAIT" in fin
