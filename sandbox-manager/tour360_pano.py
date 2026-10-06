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
tout près, salon de Leila, 06/10) est repeint avec le reste au lieu de flotter dans le tour.

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
    de `retrait` × largeur sur chaque bord."""
    import numpy as np
    dc = vers_camera(d, geo)
    w, h = geo["taille"]
    devant = dc[..., 2] > 1e-3
    zs = np.where(devant, dc[..., 2], 1.0)
    u = geo["fx"] * dc[..., 0] / zs + w / 2
    v = geo["fx"] * dc[..., 1] / zs + h / 2
    m = retrait * w
    return devant & (u >= m) & (u < w - m) & (v >= m) & (v < h - m), u, v


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


def maquette(photo, geo, l=PANO_L, h=PANO_H):
    """Ce que reçoit le dessin : {maquette (boîte grise, photo collée), aretes, masque (à peindre)} en tableaux."""
    import numpy as np
    d = directions_pano(l, h)
    t, ident = boite(vers_piece(d, geo), geo)
    gris = np.vectorize(GRIS_FACE.get)(ident).astype(np.float32)
    gris = gris * (0.85 + 0.15 * np.clip(1 - np.log(t) / 3, 0, 1))
    base = np.repeat((gris * 255)[..., None], 3, -1)
    bord = aretes(ident)
    base[bord] = 40
    dedans, u, v = coord_photo(d, geo, RETRAIT)
    base[dedans] = echantillonner(np.asarray(photo), u[dedans], v[dedans])
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
    dedans, u, v = coord_photo(d, geo, RETRAIT)
    pw, ph = geo["taille"]
    m = RETRAIT * pw
    bord = np.minimum.reduce([u - m, pw - m - u, v - m, ph - m - v])
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

    try:
        for p in D["poids"]:
            _telecharger(p["depot"], p["revision"], p["fichiers"], p["base"])
        subprocess.run(["sync"], check=False)
    except Exception as exc:  # noqa: BLE001
        echouer(3, "POIDS_ABSENTS", repr(exc))
    temps["poids_s"] = round(time.time() - t0, 1)
    photo_png = base64.b64decode(D["photo"])
    photo = _lire_png(photo_png)
    try:
        pts, nor, val, fx, (w, h) = mesurer(photo_png, D["moge"])
        geo = repere(pts, nor, val, fx, w, h)
    except ValueError as exc:
        echouer(9, "PIECE_ILLISIBLE", exc)
    temps["mesure_s"] = round(time.time() - t0 - temps["poids_s"], 1)
    (OUT / "geometrie.json").write_text(json.dumps(dict(geo, fx_vue=fx_vue(geo), pas=D["pas"])))
    print("PIECE " + json.dumps({k: geo[k] for k in ("hauteur", "plafond", "piece", "lacet", "tangage", "fx")}),
          flush=True)

    entree = Path(D["comfy"], "input")
    entree.mkdir(parents=True, exist_ok=True)
    mq = maquette(photo, geo)
    demi = lambda img, sens=1: np.roll(img, sens * PANO_L // 2, 1)          # noqa: E731
    bande = masque_bande()
    for nom, img in (("maquette.png", mq["maquette"]), ("aretes.png", mq["aretes"]),
                     ("aretes_tourne.png", demi(mq["aretes"])), ("masque.png", mq["masque"]),
                     ("bande.png", bande), ("plaque.png", photo)):
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
    grand = recoller_photo(grand, photo, geo)
    (OUT / "pano.png").write_bytes(_png(grand))
    f = fx_vue(geo)
    for cap in range(0, 360, D["pas"]):
        (OUT / ("cle_%03d.png" % cap)).write_bytes(_png(vue(grand, cap, f)))
    temps["total_s"] = round(time.time() - t0, 1)
    (OUT / "temps.json").write_text(json.dumps(temps))
    print("PANORAMA " + json.dumps(temps), flush=True)
