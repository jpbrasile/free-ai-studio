"""La maquette de l'étape 2 (panorama) tirée du PLAN mesuré, plus de la caméra devinée (propriétaire, 06/10 : « tu règles
à la main alors que l'on a un modèle en 3d » ; « oui lance l'option 1 » = refaire le panorama depuis le modèle).

maquette.py posait la pièce à l'œil (fx 904, caméra à 0,9 m, baie à x = -1) : le panorama né de ses arêtes a une
grande baie à deux vitrages que le plan MoGe-3 n'a pas, et ses deux jardins ne se raccordent pas sous le montant.
Ici la pièce, la baie, ses montants, les meubles et les ouvertures sont ceux de plan_salon_360.json ; la caméra
(hauteur, lacet, tangage, f) est celle du plan. Le panorama a son milieu dans l'axe de la plaque, horizon de niveau.
L'arrière, que la photo ne voit pas, reprend les décisions de maquette.py (bibliothèque au mur du fond, fauteuil et
lampe dans le coin droit, porte au mur droit, tapis), placées par rapport aux murs du plan.

Sorties (mêmes noms que maquette.py, pour maquette4_modal.py) : maquette_gris, _aretes, _profondeur, _plaque, _couleur,
_couleur_plaque, maquette_vue_000_calage (maquette rendue avec la caméra du plan, en fondu sur la plaque), camera.json.

  python maquette_plan.py <plan.json> <plaque.png> <dossier>
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

import maquette as mq

PL_L, PL_H = 1344, 768


def construire(plan):
    """Remplit les globales de maquette.py (repère : x à droite, y vers le BAS, z devant, caméra à l'origine) depuis le
    plan (x à droite, z devant, hauteurs au-dessus du sol), murs alignés sur les axes de la pièce."""
    h = plan["camera"]["hauteur"]
    (x0, x1), (z0, z1), haut = plan["piece"]["x"], plan["piece"]["z"], plan["piece"]["plafond"]
    mq.H_CAM = h
    mq.PIECE = ((x0, h - haut, z0), (x1, h, z1))

    def pose(ex0, ex1, ez0, ez1, dessus, dessous=0.0):
        return (ex0, h - dessus, ez0), (ex1, h - dessous, ez1)

    objets = [(e["nom"], *pose(*e["emprise"], e["hauteur"][1], e["hauteur"][0]), float(np.mean(e["rgb"])))
              for e in plan["elements"]]
    rgb = {e["nom"]: tuple(e["rgb"]) for e in plan["elements"]}
    # Les arêtes seules doivent dire ce qu'est chaque chose (06/10, essai 1 : baie lisse peinte en mur, bibliothèque
    # en boîte peinte en armoire, fauteuil en boîte peint en meuble bas) : la baie porte une traverse haute et un
    # seuil (des montants ajoutés au pas mesuré tombaient à 12 cm de la caméra : bande noire de 20°) ; bibliothèque
    # et fauteuil ont leurs parties.
    bz0, bz1 = plan["baie_gauche_z"]
    noir = (0.15, 0.15, 0.15)
    baie = [("baie_traverse", pose(x0 - 0.08, x0 + 0.04, bz0, bz1, haut, haut - 0.1), noir),
            ("baie_seuil", pose(x0 - 0.08, x0 + 0.04, bz0, bz1, 0.06), noir)]
    bois, gris = (0.59, 0.39, 0.22), (0.47, 0.47, 0.49)
    bx0, bx1, bp = x0 + 0.6, x0 + 2.2, z0 + 0.38          # bibliothèque du fond : côtés, dessus, étagères
    biblio = [("biblio_cote_g", pose(bx0, bx0 + 0.04, z0, bp, 2.1), bois),
              ("biblio_cote_d", pose(bx1 - 0.04, bx1, z0, bp, 2.1), bois),
              ("biblio_fond", pose(bx0, bx1, z0, z0 + 0.03, 2.1), bois)]
    biblio += [("biblio_etagere_%d" % k, pose(bx0, bx1, z0, bp, 0.03 + 0.42 * k, 0.42 * k), bois) for k in range(6)]
    fx0, fx1, fz0, fz1 = x1 - 1.0, x1 - 0.15, z0 + 0.25, z0 + 1.05
    fauteuil = [("fauteuil_assise", pose(fx0, fx1, fz0 + 0.2, fz1, 0.45), gris),
                ("fauteuil_dossier", pose(fx0, fx1, fz0, fz0 + 0.2, 0.9), gris),
                ("fauteuil_accoudoir_g", pose(fx0, fx0 + 0.15, fz0 + 0.2, fz1, 0.65, 0.45), gris),
                ("fauteuil_accoudoir_d", pose(fx1 - 0.15, fx1, fz0 + 0.2, fz1, 0.65, 0.45), gris)]
    # arrière décidé dans maquette.py, reporté contre les murs du plan (mur du fond z0, mur droit x1)
    arriere = baie + biblio + fauteuil + [
               ("lampe_pied", pose(x1 - 0.35, x1 - 0.15, z0 + 0.05, z0 + 0.25, 1.6), (0.24, 0.24, 0.24)),
               ("lampe_abat", pose(x1 - 0.5, x1, z0, z0 + 0.4, 1.75, 1.45), (0.94, 0.92, 0.86)),
               ("porte", ((x1 - 0.04, h - 2.1, z0 + 1.5), (x1, h, z0 + 2.4)), (0.63, 0.43, 0.24)),
               ("tapis", pose(x0 + 0.6, x0 + 2.6, z0 + 0.8, z0 + 2.4, 0.02), (0.70, 0.66, 0.58))]
    for nom, (bmin, bmax), c in arriere:
        objets.append((nom, bmin, bmax, float(np.mean(c))))
        rgb[nom] = c
    mq.OBJETS, mq.RGB_OBJETS = objets, rgb
    mq.OUVERTURES = [((x1 - 0.05, h - o["haut"], o["z"][0]), (o["fond_x"], h, o["z"][1]))
                     for o in plan["ouvertures_droite"]]


def vers_piece(d, lacet):
    """Directions du panorama (milieu = axe de la plaque) -> repère de la pièce : rotation de `lacet` vers la droite."""
    c, s = np.cos(np.radians(lacet)), np.sin(np.radians(lacet))
    return np.stack([c * d[..., 0] + s * d[..., 2], d[..., 1], -s * d[..., 0] + c * d[..., 2]], -1)


def coord_plaque(d, cam):
    """Directions du panorama -> (devant, u, v) dans la plaque : tangage du plan, f du plan."""
    t = -np.radians(cam["tangage"])      # y vers le bas : tangage < 0 (plaque vers le bas) = horizon au-dessus du milieu
    yc = d[..., 1] * np.cos(t) - d[..., 2] * np.sin(t)
    zc = d[..., 2] * np.cos(t) + d[..., 1] * np.sin(t)
    devant = zc > 1e-3
    zs = np.where(devant, zc, 1.0)
    return devant, cam["f"] * d[..., 0] / zs + PL_L / 2, cam["f"] * yc / zs + PL_H / 2


def coller(pano, plaque, cam):
    d = mq.directions_pano(mq.PANO_L, mq.PANO_H)
    devant, u, v = coord_plaque(d, cam)
    dedans = devant & (u >= 0) & (u < PL_L - 1) & (v >= 0) & (v < PL_H - 1)
    src = np.asarray(plaque.convert("RGB").resize((PL_L, PL_H)))
    out = np.asarray(pano).copy()
    out[dedans] = src[v[dedans].astype(int), u[dedans].astype(int)]
    return Image.fromarray(out)


def main(plan_chemin, plaque_chemin, dossier):
    plan = json.loads(Path(plan_chemin).read_text(encoding="utf-8"))
    cam = plan["camera"]
    dossier = Path(dossier)
    dossier.mkdir(parents=True, exist_ok=True)
    construire(plan)
    plaque = Image.open(plaque_chemin)
    d = vers_piece(mq.directions_pano(mq.PANO_L, mq.PANO_H), cam["lacet"])
    t, g, ident = mq.lancer(d)
    gris = mq.image_grise(t, g, ident)
    gris.save(dossier / "maquette_gris.png")
    bord = mq.aretes(ident, t)
    epais = bord.copy()
    epais[1:] |= bord[:-1]
    epais[:-1] |= bord[1:]
    epais[:, 1:] |= bord[:, :-1]
    epais[:, :-1] |= bord[:, 1:]
    Image.fromarray(epais.astype(np.uint8) * 255).convert("RGB").save(dossier / "maquette_aretes.png")
    prof = np.clip(255 * (1 - np.log(t / 0.5) / np.log(16)), 0, 255).astype(np.uint8)
    Image.fromarray(prof).save(dossier / "maquette_profondeur.png")
    coller(gris, plaque, cam).save(dossier / "maquette_plaque.png")
    _, coul, _ = mq.lancer(d, rgb=True)
    coul = Image.fromarray(np.clip(coul * 255, 0, 255).astype(np.uint8))
    coul.save(dossier / "maquette_couleur.png")
    coller(coul, plaque, cam).save(dossier / "maquette_couleur_plaque.png")
    # calage : la maquette vue par la caméra du plan doit tomber sur la plaque
    x, y = np.meshgrid(np.arange(PL_L) - PL_L / 2 + 0.5, np.arange(PL_H) - PL_H / 2 + 0.5)
    dc = np.stack([x / cam["f"], y / cam["f"], np.ones_like(x)], -1)
    tt = -np.radians(cam["tangage"])
    dn = np.stack([dc[..., 0], dc[..., 1] * np.cos(tt) + dc[..., 2] * np.sin(tt),
                   dc[..., 2] * np.cos(tt) - dc[..., 1] * np.sin(tt)], -1)
    dn = vers_piece(dn / np.linalg.norm(dn, axis=-1, keepdims=True), cam["lacet"])
    t, g, ident = mq.lancer(dn)
    face = mq.image_grise(t, g, ident)
    Image.blend(face, plaque.convert("RGB").resize((PL_L, PL_H)), 0.5).save(dossier / "maquette_vue_000_calage.png")
    (dossier / "camera.json").write_text(json.dumps({"f": cam["f"], "tangage": cam["tangage"]}), encoding="utf-8")
    plaque.convert("RGB").save(dossier / "plaque.png")
    print("ok", dossier)


if __name__ == "__main__":
    main(*sys.argv[1:4])
