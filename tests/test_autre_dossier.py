"""Le ZIP puis le clone : un second dossier du Studio est arrete AVANT de rien construire.

Essai a blanc du 23/09/2026 : deux dossiers aux noms differents font deux projets
Docker, mais les noms de conteneurs sont fixes ; le second demarrage echouait
sur un conflit que demarrer.ps1 ne reconnaissait pas.

Ces tests lisent les fichiers, ils ne lancent rien. Joue en reel le meme jour sur
ce PC : autre-dossier.ps1 ne rend rien depuis le dossier du Studio en marche
(y compris en changeant la casse et en ajoutant une barre finale), rend ce
dossier depuis un clone, et demarrer.ps1 lance depuis le clone s'arrete a la
verification 5 bis, conteneurs du Studio intacts."""
from __future__ import annotations

from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
PS1 = (RACINE / "scripts" / "demarrer.ps1").read_text(encoding="utf-8")
VERIF = (RACINE / "scripts" / "autre-dossier.ps1").read_text(encoding="utf-8")


def test_la_verification_passe_avant_les_reglages_et_la_construction():
    appel = PS1.index('"autre-dossier.ps1"')
    assert appel < PS1.index("Copy-Item (Join-Path $Racine \".env.example\")")
    assert appel < PS1.index('$argsCompose += @("up", "-d", "--build")')


def test_elle_lit_le_dossier_range_par_docker_et_ne_touche_a_rien():
    assert "com.docker.compose.project.working_dir" in VERIF
    for geste in ("rm", "stop", "down", "kill", "Remove-Item $Racine"):
        assert f'"{geste}"' not in VERIF, geste


def test_le_message_nomme_l_autre_dossier_et_ne_dit_pas_de_relancer_ici():
    bloc = PS1[PS1.index('"autre-dossier.ps1"'):PS1.index("# --- 6.")]
    assert '"Il tourne depuis : " + $autreDossier' in bloc
    assert "$null $true" in bloc  # sans << double-cliquez de nouveau >> ici


def test_le_conflit_de_noms_est_reconnu_s_il_passe_quand_meme():
    assert '"The container name .* is already in use"' in PS1
