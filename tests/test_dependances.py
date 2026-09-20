"""Deux services, un paquet, deux versions : la CI ne peut plus s'installer.

Le defaut, mesure le 20/09/2026 : la CI installe les TROIS `requirements.txt`
dans UN SEUL environnement (`.github/workflows/validate.yml`), alors que chaque
image Docker installe le sien, isolee des autres. Le 15/09, `python-multipart`
est passe a 0.0.32 dans `free-tier-manager` et est reste a 0.0.20 dans
`sandbox-manager`. Les conteneurs n'ont rien vu ; pip, lui, a refuse :

    ERROR: Cannot install python-multipart==0.0.20 and python-multipart==0.0.32
    because these package versions have conflicting dependencies.

**36 passages rouges d'affilee, du 15/09 14:00 au 20/09**, sans que rien dans
le depot ne le dise. Le controle qui suit est ecrit sur les fichiers eux-memes,
pas sur une liste de paquets recopiee ici : une liste recopiee se tairait le
jour ou quelqu'un epinglerait un paquet qu'elle ne connait pas.

Aucun appel reseau, aucune installation : on lit trois fichiers texte.
"""
from __future__ import annotations

import re

from conftest import RACINE

SERVICES = ("free-tier-manager", "sandbox-manager", "sandbox-worker")
# nom==version, en ignorant les extras : `uvicorn[standard]==0.35.0`.
EPINGLE = re.compile(r"^\s*([A-Za-z0-9._-]+)\s*(?:\[[^\]]*\])?\s*==\s*([^\s#]+)")


def _epingles(service: str) -> dict[str, str]:
    fichier = RACINE / service / "requirements.txt"
    trouvees = {}
    for ligne in fichier.read_text(encoding="utf-8").splitlines():
        if ligne.lstrip().startswith("#"):
            continue
        trouve = EPINGLE.match(ligne)
        if trouve:
            trouvees[trouve.group(1).lower().replace("_", "-")] = trouve.group(2)
    return trouvees


def test_les_trois_services_s_installent_ensemble():
    """La condition exacte que pip refuse, verifiee sans installer.

    Elle n'est pas devinable a la lecture d'un seul fichier : il faut les trois
    a la fois, et c'est precisement pourquoi personne ne l'a vue pendant
    cinq jours.
    """
    versions: dict[str, dict[str, str]] = {}
    for service in SERVICES:
        for paquet, version in _epingles(service).items():
            versions.setdefault(paquet, {})[service] = version

    desaccords = {paquet: ou for paquet, ou in versions.items()
                  if len(set(ou.values())) > 1}
    assert not desaccords, (
        "la CI installe les trois requirements.txt dans un seul environnement, "
        "et pip refusera ceci :\n" + "\n".join(
            "  %s : %s" % (paquet, ", ".join("%s=%s" % (s, v) for s, v in sorted(ou.items())))
            for paquet, ou in sorted(desaccords.items())))


def test_chaque_service_a_bien_son_fichier():
    """Un fichier renomme rendrait le test precedent vert en ne lisant rien."""
    for service in SERVICES:
        fichier = RACINE / service / "requirements.txt"
        assert fichier.is_file(), "absent : %s" % fichier
        assert _epingles(service), "%s : aucune version epinglee" % service
