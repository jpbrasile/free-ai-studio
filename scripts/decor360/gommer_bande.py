"""Gomme une bande verticale du panorama en y prolongeant ce qui est à côté (propriétaire, 06/10 : « do it »).

Cas du salon : le bord droit de la plaque porte une arête brillante (vitre ou miroir tout près de la caméra) ; le
panorama de l'étape 2 l'a gardée dans la plaque recollée mais ne l'a pas prolongée dessous : au tour sur place, une
baguette flotte en l'air à 45°. On remplace ses colonnes par le miroir des colonnes voisines du côté `cote`, fondu
de quelques pixels sur les bords ; la source (plaque) n'est pas touchée.

  python gommer_bande.py <pano.png> <sortie.png> <colonne début> <colonne fin> <ligne haut> <ligne bas> [droite|gauche]
"""
import sys

import numpy as np
from PIL import Image

FONDU = 3


def gommer(pano, c0, c1, r0, r1, cote="droite"):
    p = pano.astype(np.float32).copy()
    n = c1 - c0
    if cote == "droite":
        voisin = p[r0:r1, c1:c1 + n][:, ::-1]
    else:
        voisin = p[r0:r1, c0 - n:c0][:, ::-1]
    # fondu en colonnes (bords gauche/droit de la bande) et en lignes (haut/bas)
    a = np.ones((r1 - r0, n), np.float32)
    for k in range(FONDU):
        w = (k + 1) / (FONDU + 1)
        a[:, k] = np.minimum(a[:, k], w)
        a[:, n - 1 - k] = np.minimum(a[:, n - 1 - k], w)
        a[k, :] = np.minimum(a[k, :], w)
        a[r1 - r0 - 1 - k, :] = np.minimum(a[r1 - r0 - 1 - k, :], w)
    p[r0:r1, c0:c1] = p[r0:r1, c0:c1] * (1 - a[..., None]) + voisin * a[..., None]
    return p.clip(0, 255).astype(np.uint8)


if __name__ == "__main__":
    a = sys.argv[1:]
    src = np.asarray(Image.open(a[0]).convert("RGB"))
    Image.fromarray(gommer(src, *(int(x) for x in a[2:6]), *a[6:7])).save(a[1])
    print("ok", a[1])
