"""scene.json pour scene_blender.py : la géométrie de maquette.py, les deux photos sources (plaque de face, contrechamp
retourné) et les caméras à rendre (vérifications aux points des sources, puis les cibles).

  python preparer_scene.py <plaque.png> <contrechamp.png> <scene.json> [<pano équirectangulaire>]
Avec un panorama (pris du même point), tout ce que les deux photos ne voient pas en reçoit la couleur.
Les chemins d'images sont écrits relatifs au dossier de scene.json (les photos y sont copiées).
"""
import json
import math
import shutil
import sys
from pathlib import Path

import maquette

F_VUE = (maquette.VUE_L / 2) / math.tan(math.radians(maquette.CHAMP / 2))      # vues à 75° (pano -> vues)
CIBLES = [
    {"nom": "v060", "pos": [0, 0, 0], "lacet": 60, "f": F_VUE},
    {"nom": "v300", "pos": [0, 0, 0], "lacet": 300, "f": F_VUE},
    {"nom": "avance", "pos": [0.4, 0, 1.5], "lacet": 15, "f": F_VUE},          # travelling avant, parallaxe
    {"nom": "recul", "pos": [0.5, 0, -1.0], "lacet": 195, "f": F_VUE},         # vers la bibliothèque, de plus près
]


def scene(plaque, contre, sortie, pano=None):
    sortie = Path(sortie)
    sortie.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(plaque, sortie.parent / "plaque.png")
    shutil.copyfile(contre, sortie.parent / "contre.png")
    sources = [{"image": "plaque.png", "lacet": 0, "f": maquette.FX},
               {"image": "contre.png", "lacet": 180, "f": F_VUE}]
    if pano:
        shutil.copyfile(pano, sortie.parent / "pano.png")
        sources.append({"image": "pano.png", "type": "pano"})
    verifs = [{"nom": "verif_plaque", "pos": [0, 0, 0], "lacet": 0, "f": maquette.FX},
              {"nom": "verif_contre", "pos": [0, 0, 0], "lacet": 180, "f": F_VUE}]
    cfg = {"geometrie": maquette.geometrie(), "taille": [maquette.PL_L, maquette.PL_H], "sources": sources,
           "cameras": verifs + CIBLES}
    sortie.write_text(json.dumps(cfg, indent=1), encoding="utf-8")
    print("ok", sortie)


if __name__ == "__main__":
    scene(*sys.argv[1:5])
