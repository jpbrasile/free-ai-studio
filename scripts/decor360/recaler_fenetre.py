"""Recale le jardin du vitrage gauche sur celui du vitrage droit (propriétaire, 06/10 : « le problème de raccordement
du 360 se voit 2 s avant la fin sur les 2 pans de fenêtre »).

Les deux vitrages viennent de deux images différentes : sous le montant, le pied de haie est plus bas à gauche
(ligne ~1060) qu'à droite (~1037). Le vitrage gauche est étiré verticalement, par morceaux, pour que le pied de haie
tombe à la même ligne ; le haut et le bas du vitrage ne bougent pas.

  python recaler_fenetre.py <pano.png> <sortie.png> [pied_gauche pied_droit]
"""
import sys

import numpy as np
from PIL import Image

COLONNES = (1103, 1500)       # intérieur du vitrage gauche (entre ses deux montants)
HAUT, BAS = 390, 1375         # haut et bas du vitrage


def recaler(pano, pied_g=1060, pied_d=1037):
    g = pano.astype(np.float32).copy()
    c0, c1 = COLONNES
    y = np.arange(HAUT, BAS, dtype=np.float32)
    src = np.interp(y, [HAUT, pied_d, BAS], [HAUT, pied_g, BAS])
    y0 = np.floor(src).astype(int)
    t = (src - y0)[:, None, None]
    bloc = pano[:, c0:c1].astype(np.float32)
    g[HAUT:BAS, c0:c1] = bloc[y0] * (1 - t) + bloc[y0 + 1] * t
    return g.clip(0, 255).astype(np.uint8)


if __name__ == "__main__":
    p = np.asarray(Image.open(sys.argv[1]).convert("RGB"))
    args = [int(a) for a in sys.argv[3:5]]
    Image.fromarray(recaler(p, *args)).save(sys.argv[2])
    print("ok", sys.argv[2])
