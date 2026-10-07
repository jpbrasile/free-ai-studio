"""Contrôle d'un tour (skill h3-syntaxe : « cap réel de la 1re et de la dernière image de chaque tronçon contre
vues_pano.vue ») : pour chaque tronçon, le cap du panorama dont la vue exacte ressemble le plus à sa première et à sa
dernière image (recherche au demi-degré, écart quadratique sur des vues réduites), contre le cap voulu.

  python controle_caps.py <pano.png> <dossier des tronçons> [pas 60] [fx 904]
  -> une ligne par tronçon : caps voulus, caps trouvés, écarts (degrés) ; controle_caps.json à côté des tronçons
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

import vues_pano

PETIT = (336, 192)


def image(video, derniere):
    args = ["ffmpeg", "-v", "error"] + (["-sseof", "-0.1"] if derniere else []) + \
        ["-i", str(video), "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"]
    import io
    return Image.open(io.BytesIO(subprocess.run(args, capture_output=True, check=True).stdout)).convert("RGB")


def cap_trouve(pano, img, autour, fx, demi=20.0):
    cible = np.asarray(img.resize(PETIT), np.float32)
    meilleur = None
    for cap in np.arange(autour - demi, autour + demi + 0.01, 0.5):
        v = np.asarray(Image.fromarray(vues_pano.vue(pano, cap, fx)).resize(PETIT), np.float32)
        e = float(((v - cible) ** 2).mean())
        if meilleur is None or e < meilleur[1]:
            meilleur = (float(cap), e)
    return meilleur


def main(pano_png, dossier, pas=60, fx=vues_pano.FX):
    pano = np.asarray(Image.open(pano_png).convert("RGB"))
    lignes = []
    for k, f in enumerate(sorted(Path(dossier).glob("troncon_*.mp4"))):
        voulu = [k * pas, (k + 1) * pas]
        trouve = [cap_trouve(pano, image(f, d), c, fx) for d, c in ((False, voulu[0]), (True, voulu[1]))]
        l = {"troncon": f.name, "voulu": voulu, "trouve": [t[0] for t in trouve],
             "ecart": [round(t[0] - c, 1) for t, c in zip(trouve, voulu)], "erreur_quad": [round(t[1]) for t in trouve]}
        print(json.dumps(l), flush=True)
        lignes.append(l)
    (Path(dossier) / "controle_caps.json").write_text(json.dumps(lignes, indent=1), encoding="utf-8")


if __name__ == "__main__":
    a = sys.argv[1:]
    main(a[0], a[1], *(int(x) for x in a[2:3]), *(float(x) for x in a[3:4]))
