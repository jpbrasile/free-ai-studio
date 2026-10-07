"""Recoud le panorama là où ses deux bords se rejoignent (propriétaire, 06/10 : « oui corrige la couture »).

Au raccord des bords (vue à 180°), murs, plafond et sol se suivent (écart ~0,8 comme deux colonnes voisines), mais
la bibliothèque n'y porte pas les mêmes livres de part et d'autre : aucun décalage ne recolle (écart 25-42). Le
compartiment coupé par la couture est remplacé par son voisin de gauche, mis à sa largeur : les planches sont aux
mêmes hauteurs (décalage vertical mesuré : 0), seuls les livres changent. Fondu de quelques pixels sur les bords.

  python recoudre_pano.py <pano.png> <sortie.png>
"""
import sys

import numpy as np
from PIL import Image

# panorama roulé d'un demi-tour (couture en colonne w/2) ; colonnes relatives à la couture, lignes absolues
SOURCE = (-177, -69)          # intérieur du compartiment de gauche
CIBLE = (-60, 91)             # intérieur du compartiment coupé par la couture
LIGNES = (750, 1222)          # du haut au bas de la bibliothèque
FONDU = 4


def recoudre(pano):
    h, w = pano.shape[:2]
    g = np.roll(pano, w // 2, axis=1).astype(np.float32)
    c = w // 2
    r0, r1 = LIGNES
    s = g[r0:r1, c + SOURCE[0]:c + SOURCE[1]]
    larg = CIBLE[1] - CIBLE[0]
    neuf = np.asarray(Image.fromarray(s.astype(np.uint8)).resize((larg, r1 - r0), Image.LANCZOS), np.float32)
    a = np.ones((r1 - r0, larg, 1), np.float32)
    for k in range(FONDU):
        t = (k + 1) / (FONDU + 1)
        a[:, k], a[:, -1 - k] = np.minimum(a[:, k], t), np.minimum(a[:, -1 - k], t)
        a[k], a[-1 - k] = np.minimum(a[k], t), np.minimum(a[-1 - k], t)
    zone = g[r0:r1, c + CIBLE[0]:c + CIBLE[1]]
    g[r0:r1, c + CIBLE[0]:c + CIBLE[1]] = zone * (1 - a) + neuf * a
    return np.roll(g, -(w // 2), axis=1).clip(0, 255).astype(np.uint8)


if __name__ == "__main__":
    p = np.asarray(Image.open(sys.argv[1]).convert("RGB"))
    Image.fromarray(recoudre(p)).save(sys.argv[2])
    print("ok", sys.argv[2])
