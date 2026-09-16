"""Chaque module d'un service part-il vraiment dans son image ?

Le 16/09/2026, depenses.py a ete ajoute a sandbox-manager sans etre ajoute a la
ligne COPY de son Dockerfile, qui listait les fichiers un par un. Les 19 tests
passaient, ruff aussi, verifier-js.py aussi : ils tournent tous HORS conteneur.
Le defaut n'est apparu qu'au demarrage, en production, par un
ModuleNotFoundError qui a couche le service.

Ce fichier est le garde qui manquait. Il ne lance aucun conteneur : il lit les
Dockerfile et compare ce qui est sur le disque a ce qui est embarque.
"""
from __future__ import annotations

from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
SERVICES = ("free-tier-manager", "sandbox-manager", "sandbox-worker")


def modules_embarques(texte: str):
    """Ce qu'un Dockerfile emporte : le motif *.py, ou des noms cites.

    Le dernier morceau d'un COPY est la destination, jamais une source."""
    motif = False
    cites: set[str] = set()
    for ligne in texte.splitlines():
        propre = ligne.strip()
        if not propre.upper().startswith("COPY "):
            continue
        for source in propre.split()[1:-1]:
            if source == "*.py":
                motif = True
            elif source.endswith(".py"):
                cites.add(source)
    return motif, cites


@pytest.mark.parametrize("service", SERVICES)
def test_aucun_module_oublie(service):
    dossier = RACINE / service
    dockerfile = dossier / "Dockerfile"
    assert dockerfile.exists(), f"{service} n'a pas de Dockerfile."

    presents = {chemin.name for chemin in dossier.glob("*.py")}
    assert presents, f"{service} n'a aucun module Python."

    motif, cites = modules_embarques(dockerfile.read_text(encoding="utf-8"))
    if motif:
        return  # COPY *.py : rien ne peut etre oublie.

    oublies = sorted(presents - cites)
    assert not oublies, (
        f"{service} : ces modules existent mais ne sont pas copies dans l'image "
        f"({', '.join(oublies)}). Le conteneur demarrera sur un "
        f"ModuleNotFoundError. Ajoutez-les au COPY du Dockerfile, ou remplacez "
        f"la liste par « COPY *.py ./ »."
    )


def test_le_garde_refuse_la_ligne_du_16_09():
    """Preuve que ce garde mord.

    Un test vert sur un Dockerfile deja corrige ne demontre rien. Celui-ci
    rejoue la ligne exacte qui a couche le service, et verifie qu'elle est
    refusee."""
    avant = """FROM python:3.12-slim
COPY requirements.txt .
COPY app.py video.py chanson.py ./
"""
    motif, cites = modules_embarques(avant)
    presents = {"app.py", "video.py", "chanson.py", "depenses.py"}

    assert motif is False
    assert sorted(presents - cites) == ["depenses.py"]


@pytest.mark.parametrize("service", SERVICES)
def test_aucun_module_fantome(service):
    """L'inverse : un nom cite qui n'existe plus fait echouer la construction."""
    dossier = RACINE / service
    _, cites = modules_embarques((dossier / "Dockerfile").read_text(encoding="utf-8"))
    presents = {chemin.name for chemin in dossier.glob("*.py")}

    fantomes = sorted(cites - presents)
    assert not fantomes, (
        f"{service} : le Dockerfile copie des fichiers absents du dossier "
        f"({', '.join(fantomes)}). La construction de l'image echouera."
    )
