"""Vue de dessus du sol de la plaque (propriétaire, 05/10 : « pourquoi ne pas partir du sol à plat, poser l'emprise
des éléments clés, puis ajouter la hauteur »).

La caméra de la plaque est connue (fx = 904 px, à 0,9 m du sol, horizontale) : un pixel (u, v) du sol est le point
x = (u - 672) z / fx, z = fx h / (v - 384). On reporte donc la plaque sur le sol, vue de dessus, 1 cm par pixel :
ce qui touche le sol (pied de la baie, plinthes, seuils, pieds du canapé et de la table) y est à sa vraie place ;
ce qui est debout s'étire en s'éloignant de la caméra. Les emprises de maquette.py y sont tracées par-dessus.

  python plan_sol.py <plaque.png> <sortie.png>
"""
import sys

import numpy as np
from PIL import Image, ImageDraw

import maquette

X0, X1, Z0, Z1 = -2.5, 3.5, 0.0, 9.0      # étendue du plan (m)
PX = 100                                  # pixels par mètre


def vers_plan(x, z):
    return (x - X0) * PX, (Z1 - z) * PX     # z vers le haut de l'image : la caméra en bas


def plan(plaque):
    img = np.asarray(Image.open(plaque).convert("RGB")).astype(np.float32)
    hp, wp = img.shape[:2]
    cx, cy, f, h = wp / 2, hp / 2, maquette.FX, maquette.H_CAM
    w, hh = int((X1 - X0) * PX), int((Z1 - Z0) * PX)
    x = X0 + (np.arange(w) + 0.5) / PX
    z = Z1 - (np.arange(hh) + 0.5) / PX
    x, z = np.meshgrid(x, z)
    zs = np.maximum(z, 1e-3)
    u, v = cx + f * x / zs, cy + f * h / zs
    dedans = (z > 0.05) & (u >= 0) & (u < wp - 1) & (v >= 0) & (v < hp - 1)
    ui, vi = np.clip(u.astype(int), 0, wp - 1), np.clip(v.astype(int), 0, hp - 1)
    out = np.where(dedans[..., None], img[vi, ui], 40.0)
    sortie = Image.fromarray(out.astype(np.uint8))
    d = ImageDraw.Draw(sortie)
    # grille au mètre, caméra, champ
    for gx in range(int(X0), int(X1) + 1):
        d.line([vers_plan(gx, Z0), vers_plan(gx, Z1)], fill=(90, 90, 90))
    for gz in range(int(Z0), int(Z1) + 1):
        d.line([vers_plan(X0, gz), vers_plan(X1, gz)], fill=(90, 90, 90))
        d.text((vers_plan(X0, gz)[0] + 3, vers_plan(X0, gz)[1] - 12), "z=%d" % gz, fill=(200, 200, 200))
    c = vers_plan(0, 0)
    d.ellipse([c[0] - 6, c[1] - 6, c[0] + 6, c[1] + 6], fill=(255, 0, 0))
    # emprises actuelles de la maquette (pièce en jaune, objets en rouge, ouvertures en bleu)
    (px0, _, pz0), (px1, _, pz1) = maquette.PIECE
    d.rectangle([vers_plan(px0, pz1), vers_plan(px1, max(pz0, Z0))], outline=(255, 220, 0), width=2)
    for nom, bmin, bmax, _ in maquette.OBJETS:
        if bmax[2] > Z0:
            d.rectangle([vers_plan(bmin[0], bmax[2]), vers_plan(bmax[0], max(bmin[2], Z0))],
                        outline=(255, 40, 40), width=2)
            d.text(vers_plan(bmax[0], bmax[2]), nom, fill=(255, 80, 80))
    for omin, omax in maquette.OUVERTURES:
        d.rectangle([vers_plan(omin[0], omax[2]), vers_plan(omax[0], omin[2])], outline=(60, 140, 255), width=2)
    return sortie


if __name__ == "__main__":
    plan(sys.argv[1]).save(sys.argv[2])
    print("ok", sys.argv[2])
