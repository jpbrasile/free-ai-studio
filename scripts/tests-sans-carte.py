#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rejoue la suite comme si cet ordinateur n'avait pas de carte graphique.

POURQUOI. Le runner de la CI n'a pas de carte ; la machine de developpement en
a une. Un test qui interroge la vraie carte rend donc deux verdicts selon
l'endroit ou il tourne, et il passe ici en echouant la-bas. C'est arrive le
22/09/2026 : le cliquet des verdicts de `composite` -- celui qui compte quels
etats une chaine d'une seule brique peut atteindre -- lisait la carte. Ici,
<< 24138 Mo libres >> : trois etats. Sur le runner, aucune carte :
`video_maison` rend `partiel`, quatre etats, rouge. La faute etait sur `main`
avant d'etre vue.

USAGE. `python scripts/tests-sans-carte.py` -- puis les arguments de pytest.
    python scripts/tests-sans-carte.py tests/test_composite.py -q

CE QUE CE N'EST PAS. Ce n'est pas une garde et rien ne l'appelle tout seul :
c'est une sonde, a lancer avant de pousser quand on a touche a quelque chose
qui regarde la carte. La vraie garde reste la CI, qui tourne pour de bon sur
une machine sans carte -- et qu'il faut LIRE avant de fusionner.
"""
import os
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
GREFFON = RACINE / "scripts" / "_greffon_sans_carte.py"

ABSENTE = """# -*- coding: utf-8 -*-
# Engendre par tests-sans-carte.py. Greffon pytest : plus de carte ici.
import sys

VUE = {"vue": False, "nom": None, "totale_mo": None, "libre_mo": None,
       "marge_mo": 0, "motif": "simulation : pas de carte sur cette machine"}
PHRASE = "Aucune carte sur cette machine (simulation)."


def pytest_configure(config):
    sys.path.insert(0, %r)
    import gpu_local
    gpu_local.utilisable = lambda mo, *a, **k: (False, PHRASE, dict(VUE))
    gpu_local.releve = lambda *a, **k: dict(VUE)
    gpu_local.libre_pour_un_code_inconnu = lambda *a, **k: (False, PHRASE, dict(VUE))
    print("\\n[sans-carte] la carte est simulee ABSENTE")
""" % str(RACINE / "sandbox-manager")


def main() -> int:
    GREFFON.write_text(ABSENTE, encoding="utf-8", newline="\n")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(RACINE / "scripts") + os.pathsep + env.get("PYTHONPATH", "")
    try:
        return subprocess.call(
            [sys.executable, "-m", "pytest", "-p", "_greffon_sans_carte",
             *(sys.argv[1:] or ["-q", "--no-header"])],
            cwd=str(RACINE), env=env)
    finally:
        GREFFON.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
