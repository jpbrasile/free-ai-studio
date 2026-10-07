"""Le panorama 360° d'un lieu et les images clés d'un tour sur place, sur une carte louée (Modal).

Propriétaire, 06/10 : « adapt studio to automate that » — la recette d'atelier de docs/DECOR_360.md, sans main :
  1. MoGe-3 (Microsoft, MIT) mesure la photo du lieu : focale, hauteur et inclinaison de la caméra, sol, murs ;
  2. la pièce devient une boîte (sol, murs alignés, plafond, mur du fond fermé derrière la caméra), dans un repère
     HORIZONTAL tourné vers la photo ; ses arêtes, en projection équirectangulaire, guident le dessin ;
  3. Qwen-Image 2.1 + Union (contrôle Lineart sur les arêtes) peint tout ce que la photo ne montre pas, à 2048×1024 ;
     la couture (demi-tour, bande de ±25°) est repeinte ; SeedVR2 ×2 ; la photo recollée à pleine résolution ;
  4. les images clés du tour, découpées dans ce SEUL panorama, horizontales, tous les PAS degrés (la clé 0 comprise :
     mêler la photo et le panorama faisait sauter sol et plinthes au raccord, 06/10).
La photo est recollée en retrait de RETRAIT sur ses bords : un objet coupé par le cadre (arête brillante d'une vitre
tout près, salon de Leila, 06/10) est repeint avec le reste au lieu de flotter dans le tour ; à gauche et à droite,
le retrait s'élargit tant que la profondeur MoGe du bord dit un objet tout près (retraits_bords).

PLAN 21.6 étapes 1 à 3 : D["mode"] == "mesure" ne fait que l'étape 1 (MoGe -> geometrie.json, grille.json : le
Studio y lit la pièce et les points sous chaque cadre pour proposer le plan) ; ici (carte de cet ordinateur, poids
sur /poids) ou chez Modal. Le panorama reçoit ensuite cette géométrie (D["geo"]), la maquette PAR PARTIES du plan
validé (D["scene"], plan_piece.scene_du_plan) et les cartes à découper (D["cartes"]).

Ce fichier est envoyé tel quel sur la machine louée (tour360.construire_script) ; rien de ComfyUI n'y est importé.
Les fonctions de géométrie n'ont besoin que de NumPy et PIL : la suite de tests les essaie sur une pièce connue.
"""
import base64
import json
import math
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

PANO_L, PANO_H = 2048, 1024
MARGE = 12            # px du panorama : le masque déborde de la photo d'autant (raccord repeint)
BANDE = 25.0          # degrés de part et d'autre de la couture repeinte
ENROULE = 128         # px recopiés de l'autre bord avant SeedVR2 (le panorama boucle)
FONDU = 24            # px de fondu de la photo recollée à pleine résolution
RETRAIT = 0.025       # part de la largeur de la photo laissée au panorama, sur chaque bord
VUE_L, VUE_H = 1344, 768
PLAFOND_DEFAUT, PLAFOND_MIN, PLAFOND_MAX = 2.5, 2.1, 4.5
FOND_MIN = 1.5        # le mur derrière la caméra : au moins à 1,5 m


# --- Géométrie : de la mesure MoGe à la boîte de la pièce ---------------------------------------------------------

def plan_sol(points, normales, valide, essais=400, tolerance=0.02, graine=0):
    """Plan du sol par RANSAC sur les points à normale « vers le haut » (y OpenCV négatif) : (n, d, part),
    n·p + d = 0, n orienté du sol vers la caméra ; None si la photo n'a pas de sol."""
    import numpy as np
    rng = np.random.default_rng(graine)
    p = points[valide & (normales[..., 1] < -0.8)]
    if len(p) < 200:
        return None
    meilleur, n_best, d_best = 0, None, None
    for _ in range(essais):
        a, b, c = p[rng.choice(len(p), 3, replace=False)]
        n = np.cross(b - a, c - a)
        if np.linalg.norm(n) < 1e-9:
            continue
        n /= np.linalg.norm(n)
        if n[1] > 0:
            n = -n
        d = -n @ a
        ok = int((np.abs(p @ n + d) < tolerance).sum())
        if ok > meilleur:
            meilleur, n_best, d_best = ok, n, d
    if n_best is None:
        return None
    q = p[np.abs(p @ n_best + d_best) < tolerance]
    c = q.mean(0)
    n = np.linalg.svd(q - c, full_matrices=False)[2][-1]      # full_matrices=False : sinon N×N (215 Gio, 05/10)
    if n[1] > 0:
        n = -n
    return n, float(-n @ c), len(q) / len(p)


def plafond_estime(p, nn, hauteur):
    """Hauteur du plafond au-dessus du sol : médiane des points à normale vers le bas, bornée."""
    import numpy as np
    bas = nn[:, 1] > 0.8
    plafond = float(np.median(hauteur - p[bas, 1])) if bas.sum() > 100 else PLAFOND_DEFAUT
    return min(max(plafond, PLAFOND_MIN, hauteur + 0.3), PLAFOND_MAX)


def repere(points, normales, valide, fx, largeur, hauteur_img):
    """La pièce mesurée, dans un repère x à droite, y vers le BAS, z devant, murs sur les axes, caméra à l'origine :
    {R (caméra -> pièce, 3×3), hauteur, plafond, piece: [x0, x1, z0, z1], lacet (degrés, cap de la photo dans la
    pièce), tangage, fx, taille}. ValueError si la photo ne montre pas de sol."""
    import numpy as np
    sol = plan_sol(points, normales, valide)
    if sol is None:
        raise ValueError("MoGe ne voit pas de sol sur la photo du lieu : pas de pièce à mesurer.")
    n, hauteur, _ = sol
    y2 = -n
    z2 = np.array([0.0, 0.0, 1.0]) - y2[2] * y2
    z2 /= np.linalg.norm(z2)
    R = np.stack([np.cross(y2, z2), y2, z2])
    nn = normales[valide] @ R.T
    horiz = np.abs(nn[:, 1]) < 0.2
    a4 = 0.0
    if horiz.sum() > 100:
        ang = np.arctan2(nn[horiz, 0], nn[horiz, 2])
        a4 = float(np.angle(np.exp(4j * ang).mean()) / 4)      # moyenne circulaire modulo 90°
    c, s = math.cos(-a4), math.sin(-a4)
    R = np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]]) @ R
    p = points[valide] @ R.T
    nn = normales[valide] @ R.T
    au_sol = np.abs(p[:, 1] - hauteur) < 0.03
    if au_sol.sum() < 100:
        raise ValueError("Trop peu de sol mesuré sur la photo du lieu.")
    fs = p[au_sol]
    # Chaque mur : là où MoGe voit un mur tourné vers la caméra (normale le long de l'axe) ; sinon là où le sol
    # s'arrête (une baie vitrée laisse voir le jardin, pas de mur ; le sol, lui, s'arrête). Le sol seul allait
    # trop loin : vu par une porte, il continue dans la pièce d'à côté (salon de Leila : 4,2 m au lieu de 3,59).
    debout = (hauteur - p[:, 1] > 0.3) & (hauteur - p[:, 1] < plafond_estime(p, nn, hauteur) - 0.3)

    def mur(axe, signe, repli):
        vers = debout & (signe * p[:, axe] > 0) & (-signe * nn[:, axe] > 0.85)
        # le mur est derrière les meubles qui lui font face : le haut de la répartition, pas la médiane
        return float(signe * np.percentile(signe * p[vers, axe], 70)) if vers.sum() > 300 else repli

    x0 = mur(0, -1, float(np.percentile(fs[:, 0], 1)))
    x1 = mur(0, 1, float(np.percentile(fs[:, 0], 99)))
    z1 = mur(2, 1, float(np.percentile(fs[:, 2], 99)))
    plafond = plafond_estime(p, nn, hauteur)
    x0, x1 = min(x0, -0.3), max(x1, 0.3)
    z1 = max(z1, 1.0)
    z0 = -max(FOND_MIN, 0.6 * z1)
    devant = R @ np.array([0.0, 0.0, 1.0])
    return {"R": R.tolist(), "hauteur": float(hauteur), "plafond": plafond, "piece": [x0, x1, z0, z1],
            "lacet": math.degrees(math.atan2(devant[0], devant[2])),
            "tangage": math.degrees(math.asin(max(-1.0, min(1.0, -devant[1])))),
            "fx": float(fx), "taille": [int(largeur), int(hauteur_img)]}


def directions_pano(l, h):
    """Directions (h, l, 3) du panorama : x à droite, y vers le bas, z devant ; milieu = devant."""
    import numpy as np
    lon = ((np.arange(l) + 0.5) / l - 0.5) * 2 * np.pi
    lat = (0.5 - (np.arange(h) + 0.5) / h) * np.pi
    lon, lat = np.meshgrid(lon, lat)
    return np.stack([np.cos(lat) * np.sin(lon), -np.sin(lat), np.cos(lat) * np.cos(lon)], -1)


def lacet_y(deg):
    import numpy as np
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def vers_piece(d, geo):
    """Directions du panorama (horizontal, son milieu au cap de la photo) -> repère de la pièce."""
    return d @ lacet_y(geo["lacet"]).T


def vers_camera(d, geo):
    """Directions du panorama -> repère de la caméra de la photo (inclinée)."""
    import numpy as np
    return vers_piece(d, geo) @ np.asarray(geo["R"])          # R : caméra -> pièce ; R.T inverse, appliqué à droite


def boite(d, geo):
    """Lancer de rayons de l'origine dans la boîte de la pièce : (distance, identifiant de face 0..5)."""
    import numpy as np
    x0, x1, z0, z1 = geo["piece"]
    bmin = np.array([x0, geo["hauteur"] - geo["plafond"], z0])
    bmax = np.array([x1, geo["hauteur"], z1])
    inv = 1.0 / np.where(np.abs(d) < 1e-9, 1e-9, d)
    t = np.maximum(bmin * inv, bmax * inv)                    # l'origine est dans la boîte : sortie par chaque axe
    axe = t.argmin(-1)
    signe = np.take_along_axis(d, axe[..., None], -1)[..., 0] > 0
    return t.min(-1), axe * 2 + signe


def aretes(ident):
    import numpy as np
    bord = np.zeros(ident.shape, bool)
    bord[:, 1:] |= ident[:, 1:] != ident[:, :-1]
    bord[1:, :] |= ident[1:, :] != ident[:-1, :]
    bord[:, 0] |= ident[:, 0] != ident[:, -1]               # le panorama boucle
    epais = bord.copy()
    epais[1:] |= bord[:-1]
    epais[:-1] |= bord[1:]
    epais[:, 1:] |= bord[:, :-1]
    epais[:, :-1] |= bord[:, 1:]
    return epais


GRIS_FACE = {0: 0.82, 1: 0.82, 2: 0.93, 3: 0.6, 4: 0.82, 5: 0.82}   # x-, x+, plafond, sol, z-, z+


def coord_photo(d, geo, retrait=0.0):
    """(dedans, u, v) : où chaque direction du panorama tombe sur la photo (pixels), et si elle y est, en retrait
    de `retrait` × largeur sur chaque bord ; `retrait` = [gauche, droite, haut, bas] pour des bords différents."""
    import numpy as np
    if geo.get("dos"):            # la vue à 180° : la même caméra tournée d'un demi-tour sur la verticale
        d = d * np.array([-1.0, 1.0, -1.0])
    dc = vers_camera(d, geo)
    w, h = geo["taille"]
    devant = dc[..., 2] > 1e-3
    zs = np.where(devant, dc[..., 2], 1.0)
    u = geo["fx"] * dc[..., 0] / zs + w / 2
    v = geo["fx"] * dc[..., 1] / zs + h / 2
    g, dr, ha, ba = (r * w for r in (retrait if isinstance(retrait, (list, tuple)) else [retrait] * 4))
    return devant & (u >= g) & (u < w - dr) & (v >= ha) & (v < h - ba), u, v


def retraits_bords(points, valide, geo, pas=0.025, plus=0.15, rapport=0.7):
    """Le retrait de la photo à gauche et à droite, d'après la profondeur MoGe (PLAN 21.6 étape 2) : tant que la
    bande du bord est nettement plus proche que l'intérieur de la photo de ce côté (un objet coupé par le cadre,
    tout près), le retrait s'élargit, jusqu'à `plus`. Rend [gauche, droite, haut, bas] (parts de la largeur).
    Seuil `rapport` posé, pas encore mesuré sur une vraie photo."""
    import numpy as np
    dist = np.where(valide, np.linalg.norm(points, axis=-1), np.nan)
    w = dist.shape[1]

    def mediane(a, b):
        a, b = max(0, int(a * w)), min(w, max(int(a * w) + 1, int(b * w)))
        v = dist[:, a:b]
        return float(np.nanmedian(v)) if np.isfinite(v).any() else float("nan")

    sortie = []
    for miroir in (False, True):
        col = (lambda a, b: mediane(1 - b, 1 - a)) if miroir else mediane
        r = RETRAIT
        interieur = col(plus + pas, 0.45)
        while r < plus and col(r, r + pas) < rapport * interieur:
            r += pas
        sortie.append(round(r, 3))
    return sortie + [RETRAIT, RETRAIT]


def grille_points(points, valide, geo, colonnes=96):
    """Les points MoGe, en repère de la pièce (y vers le bas), sur une grille de `colonnes` de large : ce que le
    Studio lit sous le cadre d'un élément (plan_piece.depuis_cadre), sans NumPy."""
    import numpy as np
    h, w = valide.shape
    lignes = max(1, round(colonnes * h / w))
    vs = ((np.arange(lignes) + 0.5) * h / lignes).astype(int)
    us = ((np.arange(colonnes) + 0.5) * w / colonnes).astype(int)
    p = points[vs][:, us] @ np.asarray(geo["R"]).T
    ok = valide[vs][:, us]
    return {"l": colonnes, "h": lignes,
            "points": [[round(float(c), 3) for c in p[i, j]] if ok[i, j] else None
                       for i in range(lignes) for j in range(colonnes)]}


def scene(d, geo, sc):
    """La maquette par parties (plan_piece.scene_du_plan) en rayons : (distance, identifiant). Faces de la pièce
    0..5 ; le jour d'un trou dans un mur : 10 + trou ; la face d'une boîte : 100 + 8 × boîte + face. Les arêtes
    naissent des changements d'identifiant : chaque partie, chaque face, chaque jour a ses bords."""
    import numpy as np
    t, ident = boite(d, geo)
    p = d * t[..., None]
    for k, (face, a0, a1, y0, y1) in enumerate(sc["trous"]):
        long = p[..., 2] if face in (0, 1) else p[..., 0]
        dans = (ident == face) & (long >= a0) & (long <= a1) & (p[..., 1] >= y0) & (p[..., 1] <= y1)
        ident = np.where(dans, 10 + k, ident)
    inv = 1.0 / np.where(np.abs(d) < 1e-9, 1e-9, d)
    for j, (x0, x1, y0, y1, z0, z1) in enumerate(sc["boites"]):
        b0, b1 = np.array([x0, y0, z0]), np.array([x1, y1, z1])
        if np.all(b0 < 0) and np.all(b1 > 0):
            continue                                  # la caméra dans la boîte : ignorée
        ta, tb = b0 * inv, b1 * inv
        entre = np.minimum(ta, tb)
        tmin, tmax = entre.max(-1), np.maximum(ta, tb).min(-1)
        touche = (tmax >= tmin) & (tmin > 1e-4) & (tmin < t)
        if not touche.any():
            continue
        axe = entre.argmax(-1)
        signe = np.take_along_axis(d, axe[..., None], -1)[..., 0] > 0
        t = np.where(touche, tmin, t)
        ident = np.where(touche, 100 + 8 * j + axe * 2 + signe, ident)
    return t, ident


def vue_cadree(pano, cap, fx, l, h, y0):
    """Vue à plat de cap `cap`, l × h pixels, dont la première ligne est à y0 pixels au-dessus (négatif) ou
    au-dessous de l'horizon : la découpe d'une carte (même projection que `vue`)."""
    import numpy as np
    hp, lp = pano.shape[:2]
    x, y = np.meshgrid((np.arange(l) - l / 2 + 0.5) / fx, (np.arange(h) + y0 + 0.5) / fx)
    c, s = math.cos(math.radians(cap)), math.sin(math.radians(cap))
    X, Z = x * c + s, -x * s + c
    lon = np.arctan2(X, Z)
    lat = np.arctan2(-y, np.hypot(X, Z))
    return echantillonner(pano, (lon / (2 * np.pi) + 0.5) * lp, (0.5 - lat / np.pi) * hp, boucle=True) \
        .clip(0, 255).astype(np.uint8)


def decoupe_carte(pano, carte, fx, marge=4.0, demi_max=55.0):
    """La carte d'un élément : la vue en perspective (jamais une bande du panorama : H3 en recopie les courbes,
    06/10) qui couvre ses caps [a0, a1] et ses sites [bas, haut], avec une marge."""
    demi = min((carte["a1"] - carte["a0"]) / 2 + marge, demi_max)
    cap = (carte["a0"] + carte["a1"]) / 2
    l = int(_borne_px(2 * fx * math.tan(math.radians(demi))))
    cd = math.cos(math.radians(demi))
    th, tb = math.tan(math.radians(carte["haut"] + 2)), math.tan(math.radians(carte["bas"] - 2))
    y_haut = min(-fx * th, -fx * th / cd)
    y_bas = max(-fx * tb, -fx * tb / cd)
    h = int(_borne_px(y_bas - y_haut))
    return vue_cadree(pano, cap, fx, l, h, (y_haut + y_bas) / 2 - h / 2)


def _borne_px(v, a=96, b=2048):
    return max(a, min(b, v))


def flou(masque, rayon):
    import numpy as np
    from PIL import Image, ImageFilter
    return np.asarray(Image.fromarray(masque).filter(ImageFilter.GaussianBlur(rayon)))


def dilater(b, n):
    out = b.copy()
    for _ in range(n):
        o = out.copy()
        o[1:] |= out[:-1]
        o[:-1] |= out[1:]
        o[:, 1:] |= out[:, :-1]
        o[:, :-1] |= out[:, 1:]
        out = o
    return out


def echantillonner(img, u, v, boucle=False):
    """Bilinéaire de img (h, w, 3) aux pixels (u, v) ; bords répétés, ou bouclés en largeur."""
    import numpy as np
    h, w = img.shape[:2]
    u, v = u - 0.5, np.clip(v - 0.5, 0, h - 1.001)
    u0, v0 = np.floor(u).astype(int), np.floor(v).astype(int)
    du, dv = (u - u0)[..., None], (v - v0)[..., None]
    if boucle:
        u1, u0 = (u0 + 1) % w, u0 % w
    else:
        u0 = np.clip(u0, 0, w - 1)
        u1 = np.clip(u0 + 1, 0, w - 1)
        du = np.where((u < 0)[..., None] | (u > w - 1)[..., None], 0, du)
    v1 = np.clip(v0 + 1, 0, h - 1)
    p = img.astype(np.float32)
    return (p[v0, u0] * (1 - du) + p[v0, u1] * du) * (1 - dv) + (p[v1, u0] * (1 - du) + p[v1, u1] * du) * dv


def geo_dos(geo, photo_dos):
    """Le repère de la vue à 180° (propriétaire, 06/10 : « paint the panoramas from the gemini photos (front and
    back) ») : même place, même tangage, même champ que la photo de face ; retrait par défaut sur ses bords."""
    h, w = photo_dos.shape[:2]
    return dict(geo, taille=[w, h], fx=geo["fx"] * w / geo["taille"][0], retraits=[RETRAIT] * 4, dos=True,
                R=geo.get("R_dos") or geo["R"])           # son propre tangage s'il est donné


def maquette(photo, geo, l=PANO_L, h=PANO_H, sc=None, photo_dos=None):
    """Ce que reçoit le dessin : {maquette (pièce grise, photo collée), aretes, masque (à peindre)} en tableaux.
    Avec `sc` (plan_piece.scene_du_plan) : la pièce et ses éléments par parties ; sans : la boîte seule.
    `photo_dos` : la vue à 180° du même endroit, collée aussi."""
    import numpy as np
    d = directions_pano(l, h)
    if sc:
        t, ident = scene(vers_piece(d, geo), dict(geo, piece=sc["piece"], plafond=sc["plafond"]), sc)
    else:
        t, ident = boite(vers_piece(d, geo), geo)
    gris = np.array([GRIS_FACE[i] for i in range(6)], np.float32)[np.minimum(ident, 5)]
    gris = np.where((ident >= 10) & (ident < 100), 0.35, gris)
    gris = np.where(ident >= 100, 0.55 + 0.05 * ((ident - 100) % 8 // 2), gris).astype(np.float32)
    gris = gris * (0.85 + 0.15 * np.clip(1 - np.log(t) / 3, 0, 1))
    base = np.repeat((gris * 255)[..., None], 3, -1)
    bord = aretes(ident)
    base[bord] = 40
    if photo is None:             # lieu sans photo (PLAN 21.6 étape 6) : tout se peint d'après la maquette
        return {"maquette": base.clip(0, 255).astype(np.uint8), "aretes": (bord * 255).astype(np.uint8),
                "masque": np.full(bord.shape, 255, np.uint8)}
    dedans, u, v = coord_photo(d, geo, geo.get("retraits") or RETRAIT)
    base[dedans] = echantillonner(np.asarray(photo), u[dedans], v[dedans])
    if photo_dos is not None:
        dd, u, v = coord_photo(d, geo_dos(geo, photo_dos), RETRAIT)
        base[dd] = echantillonner(np.asarray(photo_dos), u[dd], v[dd])
        dedans = dedans | dd
    masque = flou((dilater(~dedans, MARGE) * 255).astype(np.uint8), 4)
    return {"maquette": base.clip(0, 255).astype(np.uint8), "aretes": (bord * 255).astype(np.uint8),
            "masque": masque}


def masque_bande(l=PANO_L, h=PANO_H):
    import numpy as np
    lon = ((np.arange(l) + 0.5) / l - 0.5) * 360.0
    m = np.repeat((np.abs(lon) <= BANDE).astype(np.uint8)[None, :] * 255, h, axis=0)
    return flou(m, 10)


def recoller_photo(pano, photo, geo):
    """La photo à pleine résolution dans le panorama, en retrait, fondu doux sur FONDU px de panorama."""
    import numpy as np
    h, w = pano.shape[:2]
    d = directions_pano(w, h)
    r = geo.get("retraits") or [RETRAIT] * 4
    dedans, u, v = coord_photo(d, geo, r)
    pw, ph = geo["taille"]
    bord = np.minimum.reduce([u - r[0] * pw, pw - r[1] * pw - u, v - r[2] * pw, ph - r[3] * pw - v])
    echelle = (w / (2 * np.pi)) / geo["fx"]                  # pixels de panorama par pixel de photo
    a = np.where(dedans, np.clip(bord * echelle / FONDU, 0, 1), 0.0)
    a = (a * a * (3 - 2 * a))[..., None]
    src = np.zeros_like(pano, dtype=np.float32)
    src[dedans] = echantillonner(np.asarray(photo), u[dedans], v[dedans])
    return (pano * (1 - a) + src * a).clip(0, 255).astype(np.uint8)


def vue(pano, cap, fx, l=VUE_L, h=VUE_H):
    """Vue à plat horizontale de cap `cap` degrés (0 = milieu du panorama, positif à droite)."""
    import numpy as np
    hp, lp = pano.shape[:2]
    x, y = np.meshgrid((np.arange(l) - l / 2 + 0.5) / fx, (np.arange(h) - h / 2 + 0.5) / fx)
    c, s = math.cos(math.radians(cap)), math.sin(math.radians(cap))
    X, Z = x * c + s, -x * s + c
    lon = np.arctan2(X, Z)
    lat = np.arctan2(-y, np.hypot(X, Z))
    return echantillonner(pano, (lon / (2 * np.pi) + 0.5) * lp, (0.5 - lat / np.pi) * hp, boucle=True) \
        .clip(0, 255).astype(np.uint8)


def fx_vue(geo):
    """La focale des images clés : même champ horizontal que la photo, sur VUE_L pixels."""
    return geo["fx"] * VUE_L / geo["taille"][0]


# --- Un personnage peint dans le panorama (07/10) ------------------------------------------------------------------
# Propriétaire : « the 360° shall be done continuously as before ; the 2d layout shall include Leila ». Sans elle dans
# le panorama, son secteur restait sans épingle et H3 y inventait la pièce (une seconde cheminée, et Leila à deux
# places, château du 07/10). La vue à son cap est découpée (`vue`), l'image du Studio l'y ajoute, et seul ce qui a
# changé (une bande verticale autour d'elle) revient dans le panorama : les épingles la montrent ensuite.
SEUIL_CHANGE = 28.0       # écart moyen (0-255) d'un pixel changé par l'image du Studio
PART_BANDE = 0.25         # une colonne fait partie de la bande tant que sa part de pixels changés dépasse ça du pic


def vers_vue(lp, hp, cap, fx, l=VUE_L, h=VUE_H):
    """L'inverse de `vue` : pour chaque pixel d'un panorama lp × hp, sa place (u, v) dans la vue de cap `cap`, et
    `dedans` (devant la caméra et dans le cadre)."""
    import numpy as np
    lon = ((np.arange(lp) + 0.5) / lp - 0.5) * 2 * np.pi
    lat = (0.5 - (np.arange(hp) + 0.5) / hp) * np.pi
    LON, LAT = np.meshgrid(lon, lat)
    X, Y, Z = np.cos(LAT) * np.sin(LON), -np.sin(LAT), np.cos(LAT) * np.cos(LON)
    c, s = math.cos(math.radians(cap)), math.sin(math.radians(cap))
    xc, zc = X * c - Z * s, X * s + Z * c
    devant = zc > 0.05
    zs = np.where(devant, zc, 1.0)
    u, v = xc / zs * fx + l / 2, Y / zs * fx + h / 2
    return u, v, devant & (u >= 0) & (u < l) & (v >= 0) & (v < h)


def bande_changee(avant, apres, seuil=SEUIL_CHANGE, part=PART_BANDE):
    """(masque 0-1 flou des pixels changés dans la bande de colonnes autour du plus grand changement, colonne
    centrale, demi-largeur en colonnes) ; ValueError si rien n'a changé."""
    import numpy as np
    ecart = flou(np.abs(apres.astype(np.int16) - avant.astype(np.int16)).mean(-1).clip(0, 255).astype(np.uint8), 3)
    change = ecart > seuil
    colonnes = change.mean(0)
    pic = int(colonnes.argmax())
    if colonnes[pic] < 0.02:
        raise ValueError("Rien n'a été ajouté à la vue.")
    g = d = pic
    while g > 0 and colonnes[g - 1] > part * colonnes[pic]:
        g -= 1
    while d < len(colonnes) - 1 and colonnes[d + 1] > part * colonnes[pic]:
        d += 1
    m = max(4, round(0.02 * len(colonnes)))
    g, d = max(0, g - m), min(len(colonnes) - 1, d + m)
    garde = np.zeros_like(change)
    garde[:, g:d + 1] = dilater(change, 6)[:, g:d + 1]
    masque = flou((garde * 255).astype(np.uint8), 5).astype(np.float32) / 255
    return masque, (g + d) / 2, (d - g) / 2


def coller(pano, avant, apres, cap, fx):
    """Le panorama avec ce que l'image du Studio a ajouté à la vue `avant` (devenue `apres`, même taille), et
    {cap, demi} : le cap du milieu de l'ajout et sa demi-largeur, en degrés."""
    import numpy as np
    masque, milieu, demi = bande_changee(avant, apres)
    l, h = avant.shape[1], avant.shape[0]
    melange = avant * (1 - masque[..., None]) + apres * masque[..., None]
    u, v, dedans = vers_vue(pano.shape[1], pano.shape[0], cap, fx, l, h)
    m = np.zeros(pano.shape[:2], np.float32)
    m[dedans] = echantillonner(masque[..., None].repeat(3, -1) * 255, u[dedans], v[dedans])[:, 0] / 255
    sortie = pano.astype(np.float32)
    sortie[dedans] = sortie[dedans] * (1 - m[dedans, None]) + echantillonner(melange, u[dedans], v[dedans]) \
        * m[dedans, None]
    angle = lambda x: math.degrees(math.atan((x + 0.5 - l / 2) / fx))      # noqa: E731
    info = {"cap": round(cap + angle(milieu), 1),
            "demi": round(max(angle(milieu + demi) - angle(milieu), angle(milieu) - angle(milieu - demi)), 1)}
    return sortie.clip(0, 255).astype(np.uint8), info


# --- Sur la machine louée ---------------------------------------------------------------------------------------

def _png(tableau):
    import io

    from PIL import Image
    b = io.BytesIO()
    Image.fromarray(tableau).save(b, "PNG")
    return b.getvalue()


def _lire_png(octets):
    import io

    import numpy as np
    from PIL import Image
    return np.asarray(Image.open(io.BytesIO(octets)).convert("RGB"))


def _taille(img, l, h):
    import numpy as np
    from PIL import Image
    return np.asarray(Image.fromarray(img).resize((l, h), Image.LANCZOS))


def _telecharger(depot, revision, fichiers, base):
    from huggingface_hub import hf_hub_download
    for f in fichiers:
        if not Path(base, f).is_file():
            hf_hub_download(depot, f, revision=revision, local_dir=base)


def mesurer(photo_png, modele, etapes=3):
    """MoGe-3 sur la photo : (points, normales, valide, fx)."""
    import torch
    from moge.model.v3 import MoGeModel
    image = _lire_png(photo_png)
    h, w = image.shape[:2]
    m = MoGeModel.from_pretrained(modele).to("cuda").eval()
    entree = torch.tensor(image / 255.0, dtype=torch.float32, device="cuda").permute(2, 0, 1)
    with torch.no_grad():
        try:
            out = m.infer(entree, refine_steps=etapes)
        except TypeError:
            out = m.infer(entree)
    res = {k: v.float().cpu().numpy() for k, v in out.items() if torch.is_tensor(v)}
    del m
    torch.cuda.empty_cache()
    return res["points"], res["normal"], res["mask"] > 0.5, float(res["intrinsics"][0, 0] * w), (w, h)


def principal():
    import numpy as np
    D = json.loads(base64.b64decode("__DEMANDE_B64__").decode())
    OUT = Path(os.environ.get("FREE_AI_OUTPUT_DIR", "/tmp/free_ai_output"))
    OUT.mkdir(parents=True, exist_ok=True)
    t0, temps = time.time(), {}

    def echouer(code, mot, detail=""):
        print(mot + " " + str(detail)[:3000], file=sys.stderr)
        log = Path("/tmp/comfy.log")
        if log.is_file():
            print("--- journal ComfyUI ---\n" + log.read_text(errors="replace")[-4000:], file=sys.stderr)
        sys.exit(code)

    if D.get("mode") in ("vue", "coller"):      # un personnage peint dans le panorama : NumPy seul, sans poids
        pano = _lire_png(base64.b64decode(D["pano"]))
        avant = vue(pano, D["cap"], D["fx"])
        if D["mode"] == "vue":
            (OUT / "vue.png").write_bytes(_png(avant))
            print("VUE", flush=True)
            return
        try:
            grand, info = coller(pano, avant, _taille(_lire_png(base64.b64decode(D["image"])), VUE_L, VUE_H),
                                 D["cap"], D["fx"])
        except ValueError as exc:
            echouer(10, "RIEN_AJOUTE", exc)
        (OUT / "pano.png").write_bytes(_png(grand))
        (OUT / "ajout.json").write_text(json.dumps(info))
        print("COLLE " + json.dumps(info), flush=True)
        return

    try:
        for p in D["poids"]:
            _telecharger(p["depot"], p["revision"], p["fichiers"], p["base"])
        subprocess.run(["sync"], check=False)
    except Exception as exc:  # noqa: BLE001
        echouer(3, "POIDS_ABSENTS", repr(exc))
    temps["poids_s"] = round(time.time() - t0, 1)
    photo_png = base64.b64decode(D["photo"]) if D.get("photo") else None
    photo = _lire_png(photo_png) if photo_png else None
    if D.get("geo"):              # mesurée avant le plan (mode « mesure ») : le même repère que le plan validé
        geo = D["geo"]
    else:
        try:
            pts, nor, val, fx, (w, h) = mesurer(photo_png, D["moge"])
            geo = repere(pts, nor, val, fx, w, h)
            geo["retraits"] = retraits_bords(pts, val, geo)
        except ValueError as exc:
            echouer(9, "PIECE_ILLISIBLE", exc)
    temps["mesure_s"] = round(time.time() - t0 - temps["poids_s"], 1)
    if D.get("mode") == "mesure":
        (OUT / "geometrie.json").write_text(json.dumps(geo))
        (OUT / "grille.json").write_text(json.dumps(grille_points(pts, val, geo)))
        print("MESURE " + json.dumps({k: geo[k] for k in ("hauteur", "plafond", "piece", "lacet", "tangage", "fx",
                                                          "retraits")} | temps), flush=True)
        return
    (OUT / "geometrie.json").write_text(json.dumps(dict(geo, fx_vue=fx_vue(geo), pas=D["pas"])))
    print("PIECE " + json.dumps({k: geo[k] for k in ("hauteur", "plafond", "piece", "lacet", "tangage", "fx")}),
          flush=True)

    entree = Path(D["comfy"], "input")
    entree.mkdir(parents=True, exist_ok=True)
    photo_dos = _lire_png(base64.b64decode(D["photo_dos"])) if D.get("photo_dos") else None
    mq = maquette(photo, geo, sc=D.get("scene"), photo_dos=photo_dos)
    demi = lambda img, sens=1: np.roll(img, sens * PANO_L // 2, 1)          # noqa: E731
    bande = masque_bande()
    if photo_dos is not None:     # la couture passe dans la vue à 180° : n'y repeindre que ses bords
        bande = np.minimum(bande, demi(mq["masque"]))
    for nom, img in (("maquette.png", mq["maquette"]), ("aretes.png", mq["aretes"]),
                     ("aretes_tourne.png", demi(mq["aretes"])), ("masque.png", mq["masque"]),
                     ("bande.png", bande), ("plaque.png", mq["maquette"] if photo is None else photo)):
        (entree / nom).write_bytes(_png(img))
    (OUT / "maquette.png").write_bytes(_png(mq["maquette"]))
    Path("/tmp/chemins.yaml").write_text(
        "q:\n  base_path: %s\n  diffusion_models: diffusion_models\n  text_encoders: text_encoders\n  vae: vae\n"
        "  controlnet: controlnet\ns:\n  base_path: %s\n  diffusion_models: diffusion_models\n  vae: vae\n"
        % (D["base_qwen"], D["base_seedvr"]))
    journal = open("/tmp/comfy.log", "w")
    proc = subprocess.Popen([sys.executable, "main.py", "--listen", "127.0.0.1", "--port", "8188",
                             "--extra-model-paths-config", "/tmp/chemins.yaml", "--output-directory", "/tmp/sortie"],
                            cwd=D["comfy"], stdout=journal, stderr=subprocess.STDOUT)

    def lire(chemin, corps=None):
        req = urllib.request.Request("http://127.0.0.1:8188" + chemin, data=corps,
                                     headers={"Content-Type": "application/json"} if corps else {})
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())

    for _ in range(300):
        try:
            lire("/system_stats")
            break
        except Exception:  # noqa: BLE001
            if proc.poll() is not None:
                echouer(7, "COMFY_ARRETE", "au démarrage")
            time.sleep(1)
    else:
        echouer(7, "COMFY_ARRETE", "pas de réponse en 300 s")
    absents = [x for x in D["classes"] if x not in lire("/object_info")]
    if absents:
        echouer(4, "NOEUD_ABSENT", absents)

    def tourner(nom, g):
        t1 = time.time()
        try:
            rep = lire("/prompt", json.dumps({"prompt": g, "client_id": "free-ai-studio"}).encode())
        except urllib.error.HTTPError as e:
            echouer(5, "GRAPHE_REFUSE", e.read().decode(errors="replace"))
        if rep.get("node_errors") or "prompt_id" not in rep:
            echouer(5, "GRAPHE_REFUSE", json.dumps(rep))
        pid = rep["prompt_id"]
        while True:
            hist = lire("/history/" + pid)
            if pid in hist:
                break
            if proc.poll() is not None:
                echouer(7, "COMFY_ARRETE", nom)
            if time.time() - t0 > D["delai_s"] - 60:
                echouer(8, "DELAI", nom)
            time.sleep(1)
        if hist[pid].get("status", {}).get("status_str") != "success":
            echouer(6, "CALCUL_ECHOUE", nom + " " + json.dumps(hist[pid].get("status", {}).get("messages", []))[-3000:])
        images = hist[pid].get("outputs", {}).get("43", {}).get("images", [])
        if not images:
            echouer(6, "CALCUL_ECHOUE", nom + " : aucune image")
        temps[nom + "_s"] = round(time.time() - t1, 1)
        return _lire_png(Path("/tmp/sortie", images[0].get("subfolder", ""), images[0]["filename"]).read_bytes())

    m = (mq["masque"].astype(np.float32) / 255)[..., None]
    mb = (bande.astype(np.float32) / 255)[..., None]
    pano = (mq["maquette"] * (1 - m) + _taille(tourner("dessin", D["graphe_dessin"]), PANO_L, PANO_H) * m)
    tourne = demi(pano.astype(np.uint8))
    (entree / "tourne.png").write_bytes(_png(tourne))
    pano = demi((tourne * (1 - mb) + _taille(tourner("couture", D["graphe_couture"]), PANO_L, PANO_H) * mb)
                .astype(np.uint8), -1)
    (entree / "a_agrandir.png").write_bytes(_png(np.concatenate([pano[:, -ENROULE:], pano, pano[:, :ENROULE]], 1)))
    g = tourner("agrandi", D["graphe_agrandi"])
    e = round(ENROULE * g.shape[1] / (PANO_L + 2 * ENROULE))
    grand = _taille(np.ascontiguousarray(g[:, e:g.shape[1] - e]), 2 * PANO_L, 2 * PANO_H)
    proc.kill()
    if photo is not None:
        grand = recoller_photo(grand, photo, geo)
    if photo_dos is not None:
        grand = recoller_photo(grand, photo_dos, geo_dos(geo, photo_dos))
    (OUT / "pano.png").write_bytes(_png(grand))
    f = fx_vue(geo)
    for cap in range(0, 360, D["pas"]):
        (OUT / ("cle_%03d.png" % cap)).write_bytes(_png(vue(grand, cap, f)))
    for c in D.get("cartes") or []:        # PLAN 21.6 étape 3 : cartes calculées depuis la maquette du plan
        (OUT / ("carte_%s.png" % c["nom"])).write_bytes(_png(decoupe_carte(grand, c, f)))
    temps["total_s"] = round(time.time() - t0, 1)
    (OUT / "temps.json").write_text(json.dumps(temps))
    print("PANORAMA " + json.dumps(temps), flush=True)
