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


# --- Linux et macOS : le meme garde-fou dans install.sh et start.sh ----------
# Joue en reel le 23/09/2026 : sous Linux dans un docker:dind (aucun conteneur,
# meme dossier, meme dossier par un lien symbolique, autre dossier ; un conteneur
# d'un autre projet ignore), et sous Git Bash sur ce PC contre le Studio lance
# par demarrer.cmd (C:\... contre /c/..., casse et barre finale).
SH = (RACINE / "scripts" / "autre-dossier.sh").read_text(encoding="utf-8")
INSTALL = (RACINE / "install.sh").read_text(encoding="utf-8")
START = (RACINE / "start.sh").read_text(encoding="utf-8")
APPEL = './scripts/autre-dossier.sh --arreter "$(pwd)" || exit 1'


def test_install_et_start_verifient_avant_de_rien_ecrire_ni_construire():
    assert INSTALL.index(APPEL) < INSTALL.index("cp .env.example .env")
    assert INSTALL.index(APPEL) < INSTALL.index("docker compose pull")
    assert START.index(APPEL) < START.index("up -d --build")


def test_le_jumeau_lit_la_meme_etiquette_et_ne_touche_a_rien():
    assert "com.docker.compose.project.working_dir" in SH
    assert "name=^free-ai-studio-" in SH
    # << docker compose down >> n'apparait que dans le message, pour la personne.
    code = SH[:SH.index("cat <<MESSAGE")] + SH[SH.index("\nMESSAGE\n"):]
    for geste in ("docker rm", "docker stop", "compose down", "docker kill", "rm -rf"):
        assert geste not in code, geste


def test_le_message_linux_donne_les_deux_choix_et_arrete():
    message = SH[SH.index("cat <<MESSAGE"):SH.index("\nMESSAGE\n")]
    assert message.splitlines()[1].startswith("ARRET : ")  # le guide s'arrete sur ARRET
    assert "Il tourne depuis : $autre" in message
    assert "A. Garder l'ancien" in message and "B. Passer a ce dossier-ci" in message
    assert SH.rstrip().endswith("exit 1")
