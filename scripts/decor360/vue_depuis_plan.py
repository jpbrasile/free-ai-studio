"""Une vue EXACTE du lieu depuis une autre place que celle du panorama (propriétaire, 07/10 : « the ideal is to find
leila exact position than for the close up do a change in camera position consistent with the exact state »).

Le panorama a été peint d'un seul point (l'origine du plan) en suivant la maquette du plan au sol. Depuis une caméra
déplacée, chaque rayon est lancé dans les boîtes du plan (plan_piece.scene_du_plan : la pièce, ses éléments par
parties) ; le point touché prend la couleur que le panorama voit dans sa direction depuis l'origine. Ce que
l'origine ne voit pas (caché par un élément) est un trou : rendu en magenta dans `_trous.png`, rempli par le point du
panorama le plus proche dans la vue rendue.

Repère du plan (plan_piece) : x à droite, z devant, origine = caméra du panorama ; ici y vers le BAS, sol à
y = hauteur (geo["hauteur"]).

  python vue_depuis_plan.py <plan.json> <pano.png> <sortie.png> --pos x,z,hauteur_oeil --vise x,z,hauteur [--fx f]
         [--taille L,H] [--marque x,z,hauteur ...]
  --pos : la caméra (hauteur de l'œil au-dessus du sol) ; --vise : le point regardé ; --marque : un point de la
  pièce dessiné en croix (contrôle : la place d'un personnage).
"""
import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sandbox-manager"))
import plan_piece  # noqa: E402


def _boites(plan, geo):
    s = plan_piece.scene_du_plan(plan, geo)
    return np.array(s["boites"], np.float64).reshape(-1, 6), np.array(s["element"], int)


def _entree(o, d, b, indice=False):
    """Distance d'entrée de chaque rayon (o, d : (N,3)) dans chaque boîte (M,6) ; inf sinon. Rend (N,) ; avec
    `indice`, aussi la boîte touchée (-1 : aucune)."""
    inv = 1.0 / np.where(np.abs(d) < 1e-12, 1e-12, d)
    meilleur = np.full(len(o), np.inf)
    qui = np.full(len(o), -1)
    for k, (x0, x1, y0, y1, z0, z1) in enumerate(b):
        t1 = (np.array([x0, y0, z0]) - o) * inv
        t2 = (np.array([x1, y1, z1]) - o) * inv
        tmin = np.minimum(t1, t2).max(axis=1)
        tmax = np.maximum(t1, t2).min(axis=1)
        ok = (tmax >= np.maximum(tmin, 1e-6))
        t = np.where(tmin > 1e-6, tmin, np.inf)          # un rayon né dans une boîte ne la touche pas
        mieux = ok & (t < meilleur)
        meilleur = np.where(mieux, t, meilleur)
        qui = np.where(mieux, k, qui)
    return (meilleur, qui) if indice else meilleur


def _sortie_piece(o, d, piece, y_plafond, y_sol):
    x0, x1, z0, z1 = piece
    inv = 1.0 / np.where(np.abs(d) < 1e-12, 1e-12, d)
    t1 = (np.array([x0, y_plafond, z0]) - o) * inv
    t2 = (np.array([x1, y_sol, z1]) - o) * inv
    return np.maximum(t1, t2).min(axis=1)


def halos(plan, geo, noms, marge=0.1, dessus=0.45):
    """Les volumes des éléments nommés, grossis de ce qui est posé dessus (pichets, gobelets) : y vers le bas."""
    hc = float(geo["hauteur"])
    sortie = []
    for e in plan["elements"]:
        if e["nom"] in noms:
            x0, x1, z0, z1 = e["emprise"]
            sortie.append([x0 - marge, x1 + marge, hc - e["hauteur"][1] - dessus, hc, z0 - marge, z1 + marge])
    return np.array(sortie, np.float64).reshape(-1, 6)


def rendre(plan, geo, pano, pos, vise, fx, L, H, fantomes=None):
    """`fantomes` (boîtes, y vers le bas) : ce que le panorama montre de ces volumes ne doit pas être recollé
    ailleurs. Un pixel dont la couleur vient d'un rayon de l'origine qui les traverse avant son point (pichets et
    bancs peints sur le panorama, absents des boîtes du plan, qui finiraient en fantômes sur le mur) est compté
    comme caché."""
    hc = float(geo["hauteur"])
    y_sol, y_plafond = hc, hc - float(plan["plafond"])
    boites, element = _boites(plan, geo)
    c = np.array([pos[0], hc - pos[2], pos[1]])
    cible = np.array([vise[0], hc - vise[2], vise[1]])
    f = cible - c
    f /= np.linalg.norm(f)
    droite = np.cross(f, [0.0, -1.0, 0.0])              # y vers le bas : le haut est -y
    droite /= np.linalg.norm(droite)
    bas = np.cross(f, droite)
    u, v = np.meshgrid((np.arange(L) - L / 2 + 0.5) / fx, (np.arange(H) - H / 2 + 0.5) / fx)
    d = (u[..., None] * droite + v[..., None] * bas + f).reshape(-1, 3)
    d /= np.linalg.norm(d, axis=1, keepdims=True)
    o = np.broadcast_to(c, d.shape)
    tb, k = _entree(o, d, boites, indice=True)
    t = np.minimum(tb, _sortie_piece(o, d, plan["piece"], y_plafond, y_sol))
    qui = np.where((k >= 0) & (tb <= t), element[np.maximum(k, 0)], -1)     # l'élément touché, -1 : la pièce
    p = o + d * t[:, None]
    # vu de l'origine ? (le point touché, ou un élément devant lui)
    r = np.linalg.norm(p, axis=1)
    dir0 = p / r[:, None]
    t0 = np.minimum(_entree(np.zeros_like(p), dir0, boites),
                    _sortie_piece(np.zeros_like(p), dir0, plan["piece"], y_plafond, y_sol))
    cache = t0 < r - 0.03 * np.maximum(r, 1.0)
    if fantomes is not None and len(fantomes):
        cache |= _entree(np.zeros_like(p), dir0, fantomes) < r - 0.05
    lon = np.arctan2(p[:, 0], p[:, 2]) - math.radians(float(geo.get("lacet") or 0.0))
    lat = np.arctan2(-p[:, 1], np.hypot(p[:, 0], p[:, 2]))
    hp, lp = pano.shape[:2]
    x = (lon / (2 * np.pi) + 0.5) * lp - 0.5
    y = (0.5 - lat / np.pi) * hp - 0.5
    x0, y0 = np.floor(x).astype(int), np.clip(np.floor(y).astype(int), 0, hp - 2)
    dx, dy = (x - x0)[:, None], np.clip(y - y0, 0, 1)[:, None]
    x1 = (x0 + 1) % lp
    x0 %= lp
    q = pano.astype(np.float32)
    img = (q[y0, x0] * (1 - dx) + q[y0, x1] * dx) * (1 - dy) + (q[y0 + 1, x0] * (1 - dx) + q[y0 + 1, x1] * dx) * dy
    return (img.reshape(H, L, 3).clip(0, 255).astype(np.uint8), cache.reshape(H, L), t.reshape(H, L),
            (c, droite, bas, f), qui.reshape(H, L))


def projeter(pt, base, fx, L, H, hc):
    c, droite, bas, f = base
    q = np.array([pt[0], hc - pt[2], pt[1]]) - c
    z = q @ f
    return (L / 2 + fx * (q @ droite) / z, H / 2 + fx * (q @ bas) / z) if z > 0 else None


def main():
    a = argparse.ArgumentParser()
    a.add_argument("plan")
    a.add_argument("pano")
    a.add_argument("sortie")
    a.add_argument("--pos", required=True)
    a.add_argument("--vise", required=True)
    a.add_argument("--fx", type=float, default=904.0)
    a.add_argument("--taille", default="1344,768")
    a.add_argument("--marque", action="append", default=[])
    a.add_argument("--refaire", action="append", default=[], help="nom d'un élément à faire repeindre (masque)")
    a.add_argument("--personne", action="append", default=[],
                   help="x,z,largeur,hauteur : un personnage debout, son volume ajouté au masque à repeindre")
    a.add_argument("--emprise", action="append", default=[],
                   help="nom=x0,x1,z0,z1 : l'élément là où le panorama l'a peint (mesuré), le plan n'est pas modifié")
    x = a.parse_args()
    lu = json.loads(Path(x.plan).read_text(encoding="utf-8"))
    plan, geo = lu["plan"], lu["geo"]
    for m in x.emprise:
        nom, v = m.split("=")
        next(e for e in plan["elements"] if e["nom"] == nom)["emprise"] = [float(t) for t in v.split(",")]
    pano = np.asarray(Image.open(x.pano).convert("RGB"))
    L, H = (int(v) for v in x.taille.split(","))
    pos = [float(v) for v in x.pos.split(",")]
    vise = [float(v) for v in x.vise.split(",")]
    img, cache, prof, base, qui = rendre(plan, geo, pano, pos, vise, x.fx, L, H, halos(plan, geo, x.refaire))
    sortie = Path(x.sortie)
    Image.fromarray(img).save(sortie)
    # à repeindre par l'image : les trous, et les éléments nommés (vus de trop près, le panorama les étale)
    noms = [e["nom"] for e in plan["elements"]]
    refaire = cache | np.isin(qui, [noms.index(n) for n in x.refaire])
    masque = Image.fromarray((refaire * 255).astype(np.uint8))
    for m in x.personne:                     # le volume d'un personnage debout à sa place, à peindre
        px, pz, larg, haut = (float(v) for v in m.split(","))
        coins = [projeter([px + sx * larg / 2, pz + sz * larg / 2, h], base, x.fx, L, H, float(geo["hauteur"]))
                 for sx in (-1, 1) for sz in (-1, 1) for h in (0.0, haut)]
        coins = [c for c in coins if c]
        if coins:
            us, vs = [c[0] for c in coins], [c[1] for c in coins]
            ImageDraw.Draw(masque).rectangle([min(us), min(vs), max(us), max(vs)], fill=255)
    masque.save(sortie.with_name(sortie.stem + "_refaire.png"))
    trous = img.copy()
    trous[cache] = (255, 0, 255)
    im = Image.fromarray(trous)
    dr = ImageDraw.Draw(im)
    for m in x.marque:
        pt = [float(v) for v in m.split(",")]
        for h in (0.0, pt[2]):
            pp = projeter([pt[0], pt[1], h], base, x.fx, L, H, float(geo["hauteur"]))
            if pp:
                dr.line([pp[0] - 12, pp[1], pp[0] + 12, pp[1]], fill=(0, 255, 0), width=3)
                dr.line([pp[0], pp[1] - 12, pp[0], pp[1] + 12], fill=(0, 255, 0), width=3)
    im.save(sortie.with_name(sortie.stem + "_trous.png"))
    print(json.dumps({"sortie": str(sortie), "trous_pct": round(100 * float(cache.mean()), 1),
                      "profondeur_m": [round(float(np.percentile(prof, q)), 2) for q in (5, 50, 95)]}))


if __name__ == "__main__":
    main()
