"""Tout chemin qui relance le Studio pose la surcouche GPU quand une carte repond.

PLAN.md, SP-CARTE-DEBRANCHEE-AU-REDEMARRAGE, ouvert le 22/09/2026. Un
`docker compose up -d` nu, sur une machine AVEC carte, recree le gestionnaire
sans `SANDBOX_WORKER_GPU_URL` : le Studio dit calmement << pas de carte
branchee >> pendant que `sandbox-worker-gpu` tourne a cote, et le clip part
chez le loueur. Mesure le 22/09 : ~0,24 $ pour un clip que la carte d'ici
aurait fait pour rien.

`start.sh` ecrivait que << les deux lanceurs doivent rester copie conforme >>.
Ils ne l'etaient pas, et l'inventaire du 22/09 en avait compte quatre chemins.
Le releve du 26/09, fait en ecrivant ce test, en a trouve SIX qui lancent un
`up` : `start.sh`, `start.ps1`, `scripts/demarrer.ps1`,
`scripts/mettre-a-jour.ps1` (le bouton << Mettre a jour >>) et les deux
`scripts/saisir-cle.*`. Quatre ne posaient pas la surcouche.

Ces tests lisent les scripts comme du texte, ils ne lancent rien : ni Docker,
ni nvidia-smi. Le lancement reel, avec et sans carte, reste non verifie.

Ce qu'ils tiennent :
- tout script suivi qui lance un `compose ... up` est trouve, et la liste
  trouvee est comparee a la liste connue : un septieme chemin se fait voir ;
- aucun d'eux n'appelle `compose up` sans `-f` ;
- chacun pose `docker-compose.gpu.yml` dans une branche qui suit la question
  `nvidia-smi --query-gpu=name`, et teste la REPONSE (code de retour ou texte
  non vide), jamais la seule presence du binaire ;
- la ligne a recopier de docs/DEPANNAGE.md donne les deux formes ;
- les anciennes lignes, gardees ici en temoins, sont bien refusees : le
  controle mord.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]

# Les chemins connus au 26/09/2026. Un script qui lance un `up` et n'est pas
# ici fait tomber `test_la_liste_des_lanceurs_est_complete` : on l'ajoute, et
# il passe alors sous les memes controles.
LANCEURS = {
    "start.sh",
    "start.ps1",
    "scripts/demarrer.ps1",
    "scripts/mettre-a-jour.ps1",
    "scripts/saisir-cle.ps1",
    "scripts/saisir-cle.sh",
}

# `compose` suivi directement de `up` : `docker compose up`, ou
# `'compose', 'up'` dans un tableau d'arguments PowerShell.
UP_NU = re.compile(r"""\bcompose['",\s]*\bup\b""")
# Un `up` lance, sous l'une ou l'autre ecriture.
LANCE_UP = re.compile(r"""\bcompose\b.*\bup\b|["']up["']""")
QUESTION = "nvidia-smi --query-gpu=name --format=csv,noheader"
SURCOUCHE = "docker-compose.gpu.yml"


def _code(texte: str) -> list[str]:
    """Les lignes qui s'executent : sans commentaires ni messages affiches.

    Le texte d'un Write-Host ou d'un echo peut nommer `docker compose up -d`
    pour dire ce qui a echoue ; ce n'est pas un appel."""
    lignes = []
    for ligne in texte.splitlines():
        if not ligne.strip() or ligne.lstrip().startswith("#"):
            continue
        lignes.append(re.split(r"Write-Host|\becho\b", ligne)[0])
    return lignes


def defauts(nom: str, texte: str) -> list[str]:
    """Ce qui manque a un lanceur pour ne pas debrancher la carte. Vide = bon."""
    code = _code(texte)
    fautes = [f"{nom} : `compose up` sans -f : {l.strip()}" for l in code if UP_NU.search(l)]
    if not any(LANCE_UP.search(l) for l in code):
        fautes.append(f"{nom} : aucun `up` trouve")
    questions = [i for i, l in enumerate(code) if QUESTION in l]
    poses = [i for i, l in enumerate(code) if SURCOUCHE in l]
    if not questions:
        fautes.append(f"{nom} : ne demande pas a nvidia-smi si une carte repond")
    if not poses:
        fautes.append(f"{nom} : ne pose jamais {SURCOUCHE}")
    for i in poses:
        # dans une branche (ligne en retrait) qui suit la question
        if not code[i].startswith((" ", "\t")):
            fautes.append(f"{nom} : {SURCOUCHE} pose hors de toute condition")
        if not questions or questions[0] > i:
            fautes.append(f"{nom} : {SURCOUCHE} pose avant la question a la carte")
    # la reponse, pas la presence du binaire
    if nom.endswith(".ps1") and "$LASTEXITCODE -eq 0" not in texte:
        fautes.append(f"{nom} : le code de retour de nvidia-smi n'est pas teste")
    if nom.endswith(".sh") and "[ -n " not in texte:
        fautes.append(f"{nom} : la reponse de nvidia-smi n'est pas testee")
    return fautes


def _suivis() -> list[str]:
    sortie = subprocess.run(
        ["git", "ls-files", "*.ps1", "*.sh", "*.cmd", "*.bat"],
        cwd=RACINE, capture_output=True, text=True, check=True,
    ).stdout
    return [l for l in sortie.splitlines() if l and not l.startswith("tests/")]


def test_la_liste_des_lanceurs_est_complete():
    trouves = set()
    for nom in _suivis():
        texte = (RACINE / nom).read_text(encoding="utf-8", errors="replace")
        if any(LANCE_UP.search(l) for l in _code(texte)):
            trouves.add(nom)
    assert trouves == LANCEURS, (
        f"nouveaux : {sorted(trouves - LANCEURS)} ; disparus : {sorted(LANCEURS - trouves)}"
    )


@pytest.mark.parametrize("nom", sorted(LANCEURS))
def test_chaque_lanceur_pose_la_surcouche_si_une_carte_repond(nom):
    texte = (RACINE / nom).read_text(encoding="utf-8")
    assert defauts(nom, texte) == []


def test_la_ligne_a_recopier_du_depannage_donne_les_deux_formes():
    """docs/DEPANNAGE.md, section << Avec un terminal >> : la ligne qu'on
    recopie JUSTEMENT quand quelque chose ne va pas."""
    doc = (RACINE / "docs" / "DEPANNAGE.md").read_text(encoding="utf-8")
    # Les blocs de code, fence par fence : une ligne qui ouvre, une qui ferme.
    blocs, dedans = [], None
    for ligne in doc.splitlines():
        if ligne.lstrip().startswith("```"):
            if dedans is None:
                dedans = []
            else:
                blocs.append("\n".join(dedans))
                dedans = None
        elif dedans is not None:
            dedans.append(ligne)
    ups = [l for b in blocs for l in _code(b) if LANCE_UP.search(l)]
    assert ups, "plus aucune ligne `up` dans les blocs de DEPANNAGE.md"
    assert not [l for l in ups if UP_NU.search(l)], ups
    assert any(SURCOUCHE in l for l in ups), ups
    assert any(SURCOUCHE not in l for l in ups), "la forme sans carte a disparu"
    assert any(QUESTION in l for b in blocs for l in _code(b))


# --- Les temoins : les lignes telles qu'elles etaient au 26/09/2026 ---------
# Le controle doit les refuser, sinon il ne controle rien. Recopiees de
# `git show HEAD:<fichier>` avant la correction.
ANCIENS = {
    "start.ps1": 'if (-not (Test-Path ".env")) {\n    throw ".env absent"\n}\n\ndocker compose up -d\ndocker compose ps\n',
    "scripts/mettre-a-jour.ps1": "    $build = Lancer 'docker' @('compose', 'up', '-d', '--build')\n",
    "scripts/saisir-cle.ps1": (
        "    # up -d ne recree que les conteneurs dont la configuration a change.\n"
        "    docker compose up -d\n"
        '    if ($LASTEXITCODE -ne 0) { Write-Host "ARRET : docker compose up -d a echoue"; exit 1 }\n'
    ),
    "scripts/saisir-cle.sh": (
        '# up -d ne recree que les conteneurs dont la configuration a change.\n'
        'docker compose up -d || { echo "ARRET : docker compose up -d a echoue."; exit 1; }\n'
    ),
}


@pytest.mark.parametrize("nom", sorted(ANCIENS))
def test_l_ancienne_ligne_est_refusee(nom):
    fautes = defauts(nom, ANCIENS[nom])
    assert any("sans -f" in f for f in fautes), fautes
    assert any(SURCOUCHE in f for f in fautes), fautes


def test_une_presence_du_binaire_ne_suffit_pas():
    """`command -v nvidia-smi` seul : mesure du 20/09, le binaire injecte dans
    une image musl existe et ne s'execute pas. La machine se croirait equipee."""
    faux = (
        'compose_args=(-f docker-compose.yml)\n'
        f'if command -v nvidia-smi >/dev/null; then  # {QUESTION}\n'
        '  compose_args+=(-f docker-compose.gpu.yml)\n'
        'fi\n'
        'docker compose "${compose_args[@]}" up -d\n'
    )
    assert defauts("faux.sh", faux)
