"""Vues à plat d'un tour sur place, tirées du SEUL panorama (propriétaire, 06/10 : « le sol ou les plinthes ne sont
pas à la même hauteur »).

Les rendus Blender du tour mêlaient la plaque, posée avec sa caméra mesurée (fx 756, inclinée de 2,38°), et le
panorama, peint autour d'elle avec la caméra devinée de l'étape 2 (fx 904, horizontale) : au raccord, le sol et les
plinthes sautent. Pour une rotation sur place, la géométrie métrique ne sert pas : seule compte la cohérence. Toutes
les vues sont donc découpées dans le panorama avec la caméra qui l'a fait, la vue 0 comprise (la plaque y est
recollée : écart moyen ~4 / 255 ; l'originale est gardée en plaque_origine.png).

  python vues_pano.py <pano.png> <plaque.png> <dossier de sortie> [lacet de la plaque dans la pièce] [pas] [fx]
  -> plaque.png, rendus/rendu_r<angle>.png, scene.json (caméra verif_plaque : lacet, f), pour tour360_h3.py
"""
import json
import math
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image

FX, L, H = 904.0, 1344, 768            # caméra de maquette4_modal.py, avec laquelle le panorama a été peint


def vue(pano, cap, fx=FX):
    """Vue perspective horizontale de cap `cap` degrés (0 = milieu du panorama, positif à droite), bilinéaire."""
    hp, lp = pano.shape[:2]
    x, y = np.meshgrid((np.arange(L) - L / 2 + 0.5) / fx, (np.arange(H) - H / 2 + 0.5) / fx)
    c, s = math.cos(math.radians(cap)), math.sin(math.radians(cap))
    X, Z = x * c + s, -x * s + c
    lon = np.arctan2(X, Z)
    lat = np.arctan2(-y, np.hypot(X, Z))
    u = (lon / (2 * np.pi) + 0.5) * lp - 0.5
    v = (0.5 - lat / np.pi) * hp - 0.5
    u0, v0 = np.floor(u).astype(int), np.clip(np.floor(v).astype(int), 0, hp - 2)
    du, dv = (u - u0)[..., None], np.clip(v - v0, 0, 1)[..., None]
    u1 = (u0 + 1) % lp
    u0 %= lp
    p = pano.astype(np.float32)
    haut = p[v0, u0] * (1 - du) + p[v0, u1] * du
    bas = p[v0 + 1, u0] * (1 - du) + p[v0 + 1, u1] * du
    return (haut * (1 - dv) + bas * dv).clip(0, 255).astype(np.uint8)


def main(pano, plaque, sortie, lacet=0.0, pas=45, fx=FX):
    sortie = Path(sortie)
    (sortie / "rendus").mkdir(parents=True, exist_ok=True)
    p = np.asarray(Image.open(pano).convert("RGB"))
    # la clé 0 vient aussi du panorama : une retouche du panorama (gommer_bande.py) vaut pour tout le tour
    shutil.copyfile(plaque, sortie / "plaque_origine.png")
    zero = vue(p, 0, fx)
    Image.fromarray(zero).save(sortie / "plaque.png")
    ecart = np.abs(zero.astype(int) - np.asarray(Image.open(plaque).convert("RGB")).astype(int))[40:-40, 40:-40].mean()
    print("vue 0 contre la plaque : écart moyen %.1f / 255 (bords exclus)" % ecart, flush=True)
    for a in range(pas, 360, pas):
        Image.fromarray(vue(p, a, fx)).save(sortie / "rendus" / ("rendu_r%03d.png" % a))
    cfg = {"taille": [L, H], "cameras": [{"nom": "verif_plaque", "pos": [0, 0, 0], "lacet": lacet, "f": fx}],
           "_source": "vues_pano.py : vues tirées du seul panorama " + str(pano)}
    (sortie / "scene.json").write_text(json.dumps(cfg, indent=1), encoding="utf-8")
    print("ok", sortie, flush=True)


if __name__ == "__main__":
    a = sys.argv[1:]
    main(a[0], a[1], a[2], *(float(x) for x in a[3:4]), *(int(x) for x in a[4:5]), *(float(x) for x in a[5:6]))
