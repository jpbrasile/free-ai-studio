"""Correctif 1 (propriétaire, 05/10 : « oui fais les deux ») : la plaque d'origine (1344x768) recollée à pleine
résolution dans un panorama 4096, avec un fondu de bord, puis six vues à plat (NumPy + PIL ; le cv2 de l'hôte est
cassé par NumPy 2).

  python recoller_plaque.py <pano_4096.png> <plaque.png> <dossier> <nom>
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

FX, PL_L, PL_H = 904.0, 1344, 768
FONDU = 24          # px de plaque sur lesquels la plaque se fond dans le panorama
LACETS = (0, 60, 120, 180, 240, 300)
CHAMP, VUE_L, VUE_H = 75.0, 1344, 768


def bilineaire(img, u, v, enroule=False):
    """img (H, W, 3) float ; u, v en pixels (centres à +0,5 près) ; enroule = le bord gauche touche le droit."""
    h, w = img.shape[:2]
    u, v = u - 0.5, np.clip(v - 0.5, 0, h - 1)
    u0, v0 = np.floor(u).astype(int), np.floor(v).astype(int)
    du, dv = (u - u0)[..., None], (v - v0)[..., None]
    if enroule:
        u0, u1 = u0 % w, (u0 + 1) % w
    else:
        u0, u1 = np.clip(u0, 0, w - 1), np.clip(u0 + 1, 0, w - 1)
    v1 = np.clip(v0 + 1, 0, h - 1)
    return (img[v0, u0] * (1 - du) * (1 - dv) + img[v0, u1] * du * (1 - dv)
            + img[v1, u0] * (1 - du) * dv + img[v1, u1] * du * dv)


def recoller(pano, plaque):
    h, w = pano.shape[:2]
    lon = ((np.arange(w) + 0.5) / w - 0.5) * 2 * np.pi
    lat = (0.5 - (np.arange(h) + 0.5) / h) * np.pi
    lon, lat = np.meshgrid(lon, lat)
    x, y, z = np.cos(lat) * np.sin(lon), -np.sin(lat), np.cos(lat) * np.cos(lon)
    devant = z > 1e-3
    zs = np.where(devant, z, 1.0)
    u, v = FX * x / zs + PL_L / 2, FX * y / zs + PL_H / 2
    bord = np.minimum.reduce([u, PL_L - u, v, PL_H - v])
    a = np.where(devant, np.clip(bord / FONDU, 0, 1), 0.0)
    a = (a * a * (3 - 2 * a))[..., None]                         # fondu doux
    # la plaque est réduite (~830 px pour 1344) : un pré-filtrage à la bonne échelle évite le crénelage
    echelle = (w / (2 * np.pi)) / FX
    petite = np.asarray(Image.fromarray(plaque).resize((round(PL_L * echelle), round(PL_H * echelle)),
                                                       Image.LANCZOS), float)
    src = bilineaire(petite, u * echelle, v * echelle)
    return (pano * (1 - a) + src * a).clip(0, 255).astype(np.uint8)


def vue(pano, lacet):
    h_p, l_p = pano.shape[:2]
    f = (VUE_L / 2) / np.tan(np.radians(CHAMP / 2))
    x, y = np.meshgrid(np.arange(VUE_L) - VUE_L / 2 + 0.5, np.arange(VUE_H) - VUE_H / 2 + 0.5)
    d = np.stack([x / f, y / f, np.ones_like(x)], -1)
    c, s = np.cos(np.radians(lacet)), np.sin(np.radians(lacet))
    xr, zr = c * d[..., 0] + s * d[..., 2], -s * d[..., 0] + c * d[..., 2]
    lon = np.arctan2(xr, zr)
    lat = -np.arctan2(d[..., 1], np.hypot(xr, zr))
    u = (lon / (2 * np.pi) + 0.5) * l_p
    v = (0.5 - lat / np.pi) * h_p
    return bilineaire(pano.astype(float), u, v, enroule=True).clip(0, 255).astype(np.uint8)


def main(pano_chemin, plaque_chemin, dossier, nom):
    dossier = Path(dossier)
    pano = np.asarray(Image.open(pano_chemin).convert("RGB"), float)
    plaque = np.asarray(Image.open(plaque_chemin).convert("RGB").resize((PL_L, PL_H)))
    out = recoller(pano, plaque)
    Image.fromarray(out).save(dossier / ("pano_%s_4096.png" % nom))
    for lacet in LACETS:
        Image.fromarray(vue(out, lacet)).save(dossier / ("vue_%s_%03d.png" % (nom, lacet)))
    print("ok", dossier, nom)


if __name__ == "__main__":
    main(*sys.argv[1:5])
