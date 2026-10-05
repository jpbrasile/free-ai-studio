"""Plan au sol de la plaque depuis le nuage MoGe-3 (moge_plaque.py) : propriétaire, 05/10, « partir du sol à plat, poser
l'emprise des éléments clés, puis ajouter la hauteur ».

1. Sol : plan ajusté (RANSAC) sur les points dont la normale pointe vers le haut -> hauteur et inclinaison réelles
   de la caméra.
2. Murs : direction dominante des normales horizontales -> la pièce est tournée pour que ses murs suivent les axes.
3. Vue de dessus, 1 cm par pixel : à gauche la couleur du point le plus haut de chaque case, à droite sa hauteur
   au-dessus du sol (le sol en sombre, les meubles en couleur, les murs en clair) ; caméra en rouge.

Repère du résultat (celui de maquette.py) : x à droite, y vers le BAS, z devant, caméra à l'origine, sol à y = h.

  python plan_moge.py <moge.npz> <plaque.png> <dossier de sortie>
  -> plan_moge.png, repere_moge.json (rotation, hauteur, inclinaison, lacet des murs, fx)
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

PX = 100                     # pixels par mètre
rng = np.random.default_rng(0)


def plan_sol(points, normales, valide):
    """RANSAC d'un plan sur les points à normale « vers le haut » (y OpenCV négatif). Rend (n, d), n·p + d = 0,
    n orienté vers le haut (du sol vers la caméra)."""
    haut = valide & (normales[..., 1] < -0.8)
    p = points[haut]
    meilleur, n_best, d_best = 0, None, None
    for _ in range(400):
        a, b, c = p[rng.choice(len(p), 3, replace=False)]
        n = np.cross(b - a, c - a)
        if np.linalg.norm(n) < 1e-9:
            continue
        n /= np.linalg.norm(n)
        if n[1] > 0:
            n = -n
        d = -n @ a
        ok = np.abs(p @ n + d) < 0.02
        if ok.sum() > meilleur:
            meilleur, n_best, d_best = ok.sum(), n, d
    # moindres carrés sur les inliers
    q = p[np.abs(p @ n_best + d_best) < 0.02]
    c = q.mean(0)
    n = np.linalg.svd(q - c, full_matrices=False)[2][-1]
    if n[1] > 0:
        n = -n
    return n, -n @ c, len(q) / len(p)


def main(npz, plaque, dossier):
    dossier = Path(dossier)
    m = np.load(npz)
    pts, nor, val = m["points"], m["normal"], m["mask"] > 0.5
    w, h = (int(x) for x in m["taille"])
    fx = float(m["intrinsics"][0, 0] * w)
    couleurs = np.asarray(Image.open(plaque).convert("RGB").resize((w, h)))
    n, d, part = plan_sol(pts, nor, val)
    hauteur = float(d)                                      # distance caméra -> sol (n·0 + d)
    # nouveau repère : y' = -n (vers le bas), z' = l'axe optique projeté sur le sol, x' = y' x z'
    y2 = -n
    z2 = np.array([0.0, 0.0, 1.0]) - (np.array([0.0, 0.0, 1.0]) @ y2) * y2
    z2 /= np.linalg.norm(z2)
    x2 = np.cross(y2, z2)
    R = np.stack([x2, y2, z2])                              # lignes : nouveaux axes dans le repère caméra
    # murs : normales presque horizontales, angle dans le plan du sol, modulo 90°
    nn = nor[val] @ R.T
    horiz = np.abs(nn[:, 1]) < 0.2
    ang = np.arctan2(nn[horiz, 0], nn[horiz, 2])
    a4 = np.angle(np.exp(4j * ang).mean()) / 4              # moyenne circulaire modulo 90°
    c, s = np.cos(-a4), np.sin(-a4)
    Ry = np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])       # tourne la pièce pour aligner ses murs sur x et z
    R = Ry @ R
    # points volants : sur une rupture de profondeur, MoGe étale des points le long du rayon (traînées en diagonale
    # sur le plan) ; on écarte ceux dont la profondeur s'écarte de plus de 3 % d'un voisin
    z = pts[..., 2]
    saut = np.zeros_like(z, dtype=bool)
    for dz in (np.abs(np.diff(z, axis=0)), np.abs(np.diff(z, axis=1))):
        r = dz / np.maximum(z[:dz.shape[0], :dz.shape[1]], 1e-3) > 0.03
        saut[:r.shape[0], :r.shape[1]] |= r
        saut[-r.shape[0]:, -r.shape[1]:] |= r
    val = val & ~saut
    p = pts[val] @ R.T
    col = couleurs[val]
    haut_sol = hauteur - p[:, 1]                            # hauteur au-dessus du sol (m)
    plafond = float(np.median(haut_sol[(nor[val] @ R.T)[:, 1] > 0.8]))   # normale vers le bas
    tangage = float(np.degrees(np.arcsin(np.clip(-n[2], -1, 1))))   # >0 : la caméra regarde vers le haut
    roulis = float(np.degrees(np.arctan2(n[0], -n[1])))
    # vue de dessus
    x0, x1 = np.percentile(p[:, 0], [0.5, 99.5])
    z0, z1 = 0.0, np.percentile(p[:, 2], 99.5)
    x0, x1, z1 = np.floor(x0) - 0.5, np.ceil(x1) + 0.5, np.ceil(z1) + 0.5
    W, H = int((x1 - x0) * PX), int((z1 - z0) * PX)
    i = ((p[:, 0] - x0) * PX).astype(int)
    j = ((z1 - p[:, 2]) * PX).astype(int)
    dans = (i >= 0) & (i < W) & (j >= 0) & (j < H) & (haut_sol < plafond - 0.15)   # le plafond couvrirait tout
    ordre = np.argsort(haut_sol[dans])                      # le plus haut écrit en dernier
    ii, jj, hh, cc = i[dans][ordre], j[dans][ordre], haut_sol[dans][ordre], col[dans][ordre]
    img = np.full((H, W, 3), 30, np.uint8)
    img[jj, ii] = cc
    carte = np.full((H, W), np.nan, np.float32)
    carte[jj, ii] = hh
    teinte = np.full((H, W, 3), 30, np.uint8)
    k = ~np.isnan(carte)
    v = np.clip(carte[k] / plafond, 0, 1)
    teinte[k] = (np.stack([v, 1 - np.abs(v - 0.4) * 1.6, 1 - v], 1).clip(0, 1) * 230 + 25).astype(np.uint8)
    teinte[k & (carte < 0.05)] = (70, 70, 70)
    vues = []
    for a in (img, teinte):
        im = Image.fromarray(a)
        dr = ImageDraw.Draw(im)
        for gx in range(int(np.ceil(x0)), int(x1) + 1):
            dr.line([((gx - x0) * PX, 0), ((gx - x0) * PX, H)], fill=(110, 110, 110))
            dr.text(((gx - x0) * PX + 2, H - 12), "x=%d" % gx, fill=(220, 220, 220))
        for gz in range(0, int(z1) + 1):
            dr.line([(0, (z1 - gz) * PX), (W, (z1 - gz) * PX)], fill=(110, 110, 110))
            dr.text((2, (z1 - gz) * PX - 12), "z=%d" % gz, fill=(220, 220, 220))
        cx, cz = (0 - x0) * PX, (z1 - 0) * PX
        dr.ellipse([cx - 7, cz - 7, cx + 7, cz + 7], fill=(255, 0, 0))
        vues.append(im)
    out = Image.new("RGB", (2 * W + 10, H), (0, 0, 0))
    out.paste(vues[0], (0, 0))
    out.paste(vues[1], (W + 10, 0))
    out.save(dossier / "plan_moge.png")
    rep = {"R_camera_vers_piece": R.tolist(), "hauteur_camera_m": hauteur, "plafond_m": plafond, "tangage_deg": tangage,
           "roulis_deg": roulis, "lacet_murs_deg": float(np.degrees(a4)), "fx": fx, "part_sol_inliers": part,
           "plan_px_par_m": PX, "plan_origine": [float(x0), float(z1)]}
    (dossier / "repere_moge.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print("REPERE plafond %.2f m, hauteur %.2f m, tangage %.1f°, roulis %.1f°, murs tournés de %.1f°, fx %.1f ; sol : %.0f %% "
          "d'inliers ; plan %dx%d" % (plafond, hauteur, tangage, roulis, np.degrees(a4), fx, 100 * part, W, H))


if __name__ == "__main__":
    main(*sys.argv[1:4])
