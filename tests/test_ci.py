"""Ce que la CI doit RAPPORTER, pas seulement ce qu'elle doit executer.

Le 20/09/2026, la CI est repassee au vert apres 37 passages rouges, et son
journal disait << 440 passed, 1 skipped >>. Le sauté n'etait nomme nulle part :
il a fallu rejouer la suite sur une machine de developpement, torch cache
derriere un faux module, pour decouvrir qu'il s'agissait de
`test_dialogue.py:1226` -- un test qui fait tourner pour de vrai le bloc
d'ecriture du WAV et qui, faute de torch, ne protege que la machine de
developpement.

Un test sauté sans nom est pire qu'un test absent : le total se lit comme une
mesure. D'ou `-rs`, qui NOMME chaque saut avec sa raison.

Ces tests lisent le fichier de la CI. Ils ne lancent rien et n'appellent
personne.
"""
from __future__ import annotations

import re

from conftest import RACINE

WORKFLOW = RACINE / ".github" / "workflows" / "validate.yml"


def _etape(nom: str) -> str:
    """La commande `run:` de l'etape qui porte ce nom."""
    texte = WORKFLOW.read_text(encoding="utf-8")
    trouve = re.search(
        r"^\s*-\s*name:\s*%s\s*\n(?P<corps>(?:\s*\w+:.*\n|\s{10,}.*\n|\s*\n)*)"
        % re.escape(nom), texte, re.MULTILINE)
    assert trouve, "etape absente du workflow : %s" % nom
    return trouve.group("corps")


def test_la_ci_nomme_les_tests_qu_elle_saute():
    """Sans `-rs`, un saut disparait dans un total qui se lit comme une mesure."""
    corps = _etape("Tests")
    # -rs nomme les sauts, -ra nomme tout (sauts compris). Les deux conviennent ;
    # ecrits en clair plutot qu'en motif large, qui accepterait un `-r` seul --
    # invalide pour pytest -- et ferait passer ce test pour une garde.
    assert re.search(r"pytest\b[^\n]*\s-(?:rs|ra)\b", corps), \
        "l'etape Tests doit passer -rs a pytest, sinon un saut reste anonyme :\n" + corps


def test_la_ci_installe_les_trois_services_dans_un_seul_environnement():
    """La condition que `tests/test_dependances.py` protege.

    Si quelqu'un separait un jour les environnements, l'autre test deviendrait
    une contrainte sans objet -- plus severe que la realite, donc un rouge que
    l'on finirait par desactiver. Celui-ci le dira le jour ou cela arrive.
    """
    corps = _etape("Install service dependencies")
    for service in ("free-tier-manager", "sandbox-manager", "sandbox-worker"):
        assert "%s/requirements.txt" % service in corps, \
            "%s absent de l'installation de la CI :\n%s" % (service, corps)
