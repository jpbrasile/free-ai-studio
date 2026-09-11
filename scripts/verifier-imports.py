#!/usr/bin/env python3
"""Charge chaque service FastAPI du depot comme son conteneur le fait.

py_compile ne dit rien d'un import qui manque, d'un nom mal orthographie au
niveau du module, d'une dependance absente de requirements.txt : ces pannes-la
n'apparaissent qu'au demarrage du conteneur, apres dix minutes de construction,
chez quelqu'un qui ne sait pas lire un journal Docker. Ce script les fait
apparaitre en CI.

Un service = un dossier de premier niveau qui contient app.py. La liste n'est
ecrite nulle part : un service ajoute demain sera charge sans qu'on y pense.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]


def charger(dossier: Path):
    # Dans le conteneur, le dossier du service est le repertoire de travail :
    # << import video >> y marche parce que video.py est a cote. Meme chose ici.
    sys.path.insert(0, str(dossier))
    try:
        nom = dossier.name.replace("-", "_") + "_app"
        spec = importlib.util.spec_from_file_location(nom, dossier / "app.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(dossier))


def main() -> int:
    # Les services ecrivent sous /config et /workspace, qui n'existent que dans
    # le conteneur. On leur donne un dossier jetable.
    jetable = Path(tempfile.mkdtemp(prefix="free-ai-imports-"))
    os.environ.setdefault("FREE_AI_CONFIG_DIR", str(jetable / "config"))
    os.environ.setdefault("SANDBOX_WORKSPACE", str(jetable / "workspace"))

    from fastapi import FastAPI

    services = sorted(p.parent for p in RACINE.glob("*/app.py"))
    if not services:
        print("ECHEC : aucun service trouve (aucun */app.py).")
        return 1
    echecs = 0
    for dossier in services:
        try:
            module = charger(dossier)
            if not isinstance(getattr(module, "app", None), FastAPI):
                raise TypeError("app.py ne definit pas d'objet FastAPI nomme << app >>")
            print(f"ok     {dossier.name} : {len(module.app.routes)} routes")
        except Exception as exc:  # toutes les pannes d'abord, un seul verdict ensuite
            echecs += 1
            print(f"ECHEC  {dossier.name} : {type(exc).__name__}: {exc}")
    return 1 if echecs else 0


if __name__ == "__main__":
    sys.exit(main())
