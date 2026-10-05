"""Étape 1 de la maquette (propriétaire, 05/10 : « oui lance l'étape 1, montre-moi le panorama gris »).

Pièce en boîtes, calée à l'œil sur la plaque de jour (fx = 904 px sur 1344, MoGe-2 ; caméra à 0,9 m, déduite du canapé), arrière FERMÉ
décidé à la main : mur plein, bibliothèque, porte, fauteuil, lampe. Rendu par lancer de rayons (NumPy, processeur) :
  - maquette_gris.png       panorama 2048x1024 ombré, arêtes tracées
  - maquette_profondeur.png profondeur (clair = près)
  - maquette_plaque.png     le gris + la plaque collée à son vrai champ (ce que Qwen recevrait)
  - maquette_vue_000_calage.png  vue de face rendue et plaque en fondu 50 % (contrôle du calage)
  - maquette_vue_<lacet>.png     vues à plat (180 = contrechamp)
Repère : x à droite, y vers le BAS, z devant ; la caméra est à l'origine, le sol à y = +0,9.
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

FX, PL_L, PL_H = 904.0, 1344, 768
H_CAM = 0.9
PANO_L, PANO_H = 2048, 1024
CHAMP, VUE_L, VUE_H = 75.0, 1344, 768

# Pièce (intérieur) : x de -1,0 (baie vitrée à gauche) à 2,3 ; z de -3,0 (mur arrière) à 7,9 ; plafond à 2,6 m.
PIECE = ((-1.0, H_CAM - 2.6, -3.0), (2.3, H_CAM, 7.9))
# (nom, min, max, gris de base) ; y en repère caméra (bas positif) : un objet posé va de H_CAM - hauteur à H_CAM.
def pose(x0, x1, z0, z1, haut, base=0.0):
    return (x0, H_CAM - haut, z0), (x1, H_CAM - base, z1)

OBJETS = [
    # devant (déjà sur la plaque, pour la cohérence)
    ("canape", *pose(-0.7, 1.3, 3.95, 4.85, 0.85), 0.86),
    ("table", *pose(-0.05, 0.92, 2.86, 3.09, 0.38), 0.62),   # recalée sur la plaque le 05/10 (bords du plateau, pieds)
    ("biblio_fond", *pose(1.2, 1.6, 7.0, 7.4, 1.9), 0.58),
    # arrière décidé : mur plein + mobilier
    ("bibliotheque", *pose(-0.4, 1.2, -3.0, -2.62, 2.1), 0.55),
    ("fauteuil", *pose(1.3, 2.15, -2.75, -1.95, 0.9), 0.78),
    ("lampe_pied", *pose(1.95, 2.15, -2.95, -2.75, 1.6), 0.45),
    ("lampe_abat", *pose(1.8, 2.3, -3.0, -2.6, 1.75, 1.45), 0.92),
    ("porte", (2.26, H_CAM - 2.1, -1.5), (2.3, H_CAM, -0.6), 0.5),
    ("tapis", *pose(-0.4, 1.6, -2.2, -0.6, 0.02), 0.66),
    # montants de la baie (05/10, raccord à 300°) : sans eux, les arêtes ne disent pas « vitre » et le mur revient
    ("montant_0", *pose(-1.0, -0.93, 0.0, 0.08, 2.6), 0.3),
    ("montant_1", *pose(-1.0, -0.93, 0.9, 0.96, 2.6), 0.3),
]
# Ouvertures du mur droit lues sur la plaque (05/10, raccord à 60°) : (min, max) d'un renfoncement qui traverse le mur
# x = 2,3 ; le rayon qui touche le mur dans son contour continue jusqu'au fond. Couloir, puis grande baie intérieure.
OUVERTURES = [
    ((2.25, H_CAM - 2.1, 4.8), (3.8, H_CAM, 5.65)),
    ((2.25, H_CAM - 2.1, 3.2), (3.8, H_CAM, 4.0)),
]
COULEUR_PIECE = {"sol": 0.6, "plafond": 0.93, "mur": 0.82, "baie": 0.7, "ouverture": 0.5}
# Maquette en couleurs (essai suivant, 05/10) : les matières voulues, en aplats ombrés (RGB 0..1).
RGB_PIECE = {"sol": (0.78, 0.72, 0.62), "plafond": (0.96, 0.95, 0.93), "mur": (0.92, 0.88, 0.80),
             "baie": (0.47, 0.63, 0.35), "ouverture": (0.45, 0.42, 0.38)}
RGB_OBJETS = {"canape": (0.90, 0.88, 0.84), "table": (0.67, 0.47, 0.27), "biblio_fond": (0.67, 0.47, 0.27),
              "bibliotheque": (0.59, 0.39, 0.22), "fauteuil": (0.47, 0.47, 0.49), "lampe_pied": (0.24, 0.24, 0.24),
              "lampe_abat": (0.94, 0.92, 0.86), "porte": (0.63, 0.43, 0.24), "tapis": (0.70, 0.66, 0.58),
              "montant_0": (0.15, 0.15, 0.15), "montant_1": (0.15, 0.15, 0.15)}
LUMIERE = np.array([-0.5, -0.8, 0.4]) / np.linalg.norm([-0.5, -0.8, 0.4])


def boite(o, d, bmin, bmax):
    """Slabs : t d'entrée, axe d'entrée, t de sortie, axe de sortie (rayons d issus de o)."""
    inv = 1.0 / np.where(np.abs(d) < 1e-9, 1e-9, d)
    t0 = (np.array(bmin) - o) * inv
    t1 = (np.array(bmax) - o) * inv
    tn, tf = np.minimum(t0, t1), np.maximum(t0, t1)
    return tn.max(-1), tn.argmax(-1), tf.min(-1), tf.argmin(-1)


def lancer(d, rgb=False):
    """d : (..., 3) directions unitaires. Rend profondeur, gris (ou couleur si rgb), identifiant de surface."""
    o = np.zeros(3)
    _, _, t, axe = boite(o, d, *PIECE)
    p = d * t[..., None]
    ouv = np.full(t.shape, -1)
    for k, (bmin, bmax) in enumerate(OUVERTURES):
        dans = np.all((p >= np.array(bmin) - 1e-6) & (p <= np.array(bmax) + 1e-6), -1) & (ouv < 0)
        _, _, tf, af = boite(o, d, bmin, bmax)
        t, axe, ouv = np.where(dans, tf, t), np.where(dans, af, axe), np.where(dans, k, ouv)
    p = d * t[..., None]
    n = np.zeros_like(d)
    np.put_along_axis(n, axe[..., None], -np.sign(np.take_along_axis(d, axe[..., None], -1)), -1)
    piece = RGB_PIECE if rgb else COULEUR_PIECE
    c = lambda k: np.asarray(piece[k], float)                    # noqa: E731
    sol, haut = (d[..., 1] > 0)[..., None], (axe == 1)[..., None]
    gris = np.where(haut, np.where(sol, c("sol"), c("plafond")), c("mur"))
    baie = (axe == 0) & (d[..., 0] < 0) & (p[..., 2] > 0.0)       # baie vitrée : mur gauche, devant la caméra
    gris = np.where(baie[..., None], c("baie"), gris)
    gris = np.where((ouv >= 0)[..., None], c("ouverture"), gris)
    ident = np.where(axe == 1, np.where(d[..., 1] > 0, 1, 2), 3 + axe).astype(np.int32)
    ident = np.where(baie, 9, ident)
    ident = np.where(ouv >= 0, 10 + 3 * ouv + axe, ident)         # 10..15, sous les objets (20+)
    for k, (nom, bmin, bmax, g) in enumerate(OBJETS):
        tn, an, tf, _ = boite(o, d, bmin, bmax)
        touche = (tn > 1e-3) & (tn < tf) & (tn < t)
        t = np.where(touche, tn, t)
        nn = np.zeros_like(d)
        np.put_along_axis(nn, an[..., None], -np.sign(np.take_along_axis(d, an[..., None], -1)), -1)
        n = np.where(touche[..., None], nn, n)
        gris = np.where(touche[..., None], np.asarray(RGB_OBJETS[nom] if rgb else g, float), gris)
        ident = np.where(touche, 20 + 6 * k + an, ident)
    ombre = 0.55 + 0.45 * np.clip((n * -LUMIERE).sum(-1), 0, 1)
    ident = ident * 3 + np.where(axe == 1, 0, axe)               # sépare aussi les faces de la pièce
    gris = gris * ombre[..., None]
    return t, (gris if rgb else gris[..., 0]), ident


def aretes(ident, t):
    bord = np.zeros(ident.shape, bool)
    bord[:, 1:] |= ident[:, 1:] != ident[:, :-1]
    bord[1:, :] |= ident[1:, :] != ident[:-1, :]
    bord[:, 1:] |= np.abs(np.log(t[:, 1:] / t[:, :-1])) > 0.08
    bord[1:, :] |= np.abs(np.log(t[1:, :] / t[:-1, :])) > 0.08
    return bord


def image_grise(t, gris, ident):
    img = np.clip(gris * 255, 0, 255)
    img[aretes(ident, t)] = 40
    return Image.fromarray(img.astype(np.uint8)).convert("RGB")


def directions_pano(l, h):
    lon = ((np.arange(l) + 0.5) / l - 0.5) * 2 * np.pi
    lat = (0.5 - (np.arange(h) + 0.5) / h) * np.pi
    lon, lat = np.meshgrid(lon, lat)
    return np.stack([np.cos(lat) * np.sin(lon), -np.sin(lat), np.cos(lat) * np.cos(lon)], -1)


def directions_vue(lacet, f, l, h):
    x, y = np.meshgrid(np.arange(l) - l / 2 + 0.5, np.arange(h) - h / 2 + 0.5)
    d = np.stack([x / f, y / f, np.ones_like(x)], -1)
    c, s = np.cos(np.radians(lacet)), np.sin(np.radians(lacet))
    d = np.stack([c * d[..., 0] + s * d[..., 2], d[..., 1], -s * d[..., 0] + c * d[..., 2]], -1)
    return d / np.linalg.norm(d, axis=-1, keepdims=True)


def coller_plaque(pano, plaque):
    d = directions_pano(PANO_L, PANO_H)
    devant = d[..., 2] > 1e-3
    zs = np.where(devant, d[..., 2], 1.0)
    u = FX * d[..., 0] / zs + PL_L / 2
    v = FX * d[..., 1] / zs + PL_H / 2
    dedans = devant & (u >= 0) & (u < PL_L - 1) & (v >= 0) & (v < PL_H - 1)
    src = np.asarray(plaque.convert("RGB").resize((PL_L, PL_H)))
    out = np.asarray(pano).copy()
    out[dedans] = src[v[dedans].astype(int), u[dedans].astype(int)]
    return Image.fromarray(out)


def main(plaque_chemin, dossier):
    dossier = Path(dossier)
    dossier.mkdir(parents=True, exist_ok=True)
    plaque = Image.open(plaque_chemin)
    t, g, ident = lancer(directions_pano(PANO_L, PANO_H))
    gris = image_grise(t, g, ident)
    gris.save(dossier / "maquette_gris.png")
    # arêtes de la maquette, blanc sur noir (contrôle Lineart / MLSD de l'Union), épaissies d'un pixel
    bord = aretes(ident, t)
    epais = bord.copy()
    epais[1:] |= bord[:-1]
    epais[:-1] |= bord[1:]
    epais[:, 1:] |= bord[:, :-1]
    epais[:, :-1] |= bord[:, 1:]
    Image.fromarray(epais.astype(np.uint8) * 255).convert("RGB").save(dossier / "maquette_aretes.png")
    prof = np.clip(255 * (1 - np.log(t / 0.5) / np.log(16)), 0, 255).astype(np.uint8)
    Image.fromarray(prof).save(dossier / "maquette_profondeur.png")
    coller_plaque(gris, plaque).save(dossier / "maquette_plaque.png")
    _, coul, _ = lancer(directions_pano(PANO_L, PANO_H), rgb=True)
    coul = Image.fromarray(np.clip(coul * 255, 0, 255).astype(np.uint8))
    coul.save(dossier / "maquette_couleur.png")
    coller_plaque(coul, plaque).save(dossier / "maquette_couleur_plaque.png")
    t, g, ident = lancer(directions_vue(0, FX, PL_L, PL_H))
    face = image_grise(t, g, ident)
    Image.blend(face, plaque.convert("RGB").resize((PL_L, PL_H)), 0.5).save(dossier / "maquette_vue_000_calage.png")
    f = (VUE_L / 2) / np.tan(np.radians(CHAMP / 2))
    for lacet in (60, 120, 180, 240, 300):
        t, g, ident = lancer(directions_vue(lacet, f, VUE_L, VUE_H))
        image_grise(t, g, ident).save(dossier / ("maquette_vue_%03d.png" % lacet))
    print("ok", dossier)


def geometrie():
    """La même pièce pour scene_blender.py (JSON, repère de ce fichier)."""
    return {"h_cam": H_CAM, "fx": FX, "piece": PIECE, "baie_z": [0.0, PIECE[1][2]],
            "objets": [{"nom": nom, "min": bmin, "max": bmax, "rgb": RGB_OBJETS[nom]} for nom, bmin, bmax, _ in OBJETS],
            "ouvertures": OUVERTURES, "rgb_piece": RGB_PIECE}


if __name__ == "__main__":
    if sys.argv[1] == "--geometrie":
        import json
        Path(sys.argv[2]).write_text(json.dumps(geometrie(), indent=1), encoding="utf-8")
    else:
        main(sys.argv[1], sys.argv[2])
