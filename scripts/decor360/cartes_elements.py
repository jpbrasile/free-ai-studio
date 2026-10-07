"""Cartes d'identité des éléments clés d'un lieu (propriétaire, 06/10 : « make an id card of key elements first, then use
it inside the room »).

Une carte = l'élément découpé dans la plaque (élément du plan) ou le panorama (le reste), sa description (une phrase, en anglais : elle part telle
quelle dans les consignes vidéo), son azimut vu de la caméra de la plaque (0° = devant la pièce, positif à droite) et,
s'il est au plan, son emprise au sol et sa hauteur. Le panorama (étape 2 de DECOR_360.md) a la plaque recollée en son
milieu : il montre tout le lieu d'un seul point, d'où les découpes.

Entrée, cartes.json à la main (sur le panorama quadrillé : python cartes_elements.py --grille <essai>) :
  [{"nom", "description", "plan": [noms d'éléments ou d'ouvertures du plan]}                     -> azimut calculé
   | {"nom", "description", "azimut": [a0, a1], "lignes": [haut, bas]}]                            (lignes du pano)
Sortie : <essai>/cartes/<nom>.png, <essai>/cartes/cartes_lieu.json, <essai>/cartes/planche_cartes.jpg ;
tour360_h3.py s'en sert pour dire à chaque tronçon ce qu'il traverse, et rien d'autre.

  python cartes_elements.py <essai> <plan.json> <cartes.json>
  python cartes_elements.py --grille <essai>
"""
import json
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw


def pano_de(essai):
    cfg = json.loads((essai / "scene.json").read_text(encoding="utf-8"))
    src = next(s for s in cfg["sources"] if s.get("type") == "pano")
    return Image.open(essai / src["image"]).convert("RGB"), src.get("lacet", 0.0)


def colonne(az, lacet, largeur):
    """Azimut de la pièce -> colonne du panorama (scene_blender.py : u = 0.5 + (lon - lacet) / 360°)."""
    return (((az - lacet) / 360.0 + 0.5) % 1.0) * largeur


def boites_du_plan(plan, noms):
    """Coins (x, hauteur au-dessus du sol, z) des éléments et ouvertures du plan dont le nom commence par un des noms."""
    coins = []
    for e in plan["elements"]:
        if any(e["nom"].startswith(n) for n in noms):
            x0, x1, z0, z1 = e["emprise"]
            coins += [(x, y, z) for x in (x0, x1) for z in (z0, z1) for y in e["hauteur"]]
    x_droit = plan["piece"]["x"][1]
    for o in plan["ouvertures_droite"]:
        if o["nom"] in noms:
            coins += [(x_droit, y, z) for z in o["z"] for y in (0.0, o["haut"])]
    return coins


def depuis_plan(plan, noms, plaque, marge=0.08):
    """Élément du plan : azimut, emprise, hauteur, et sa découpe dans la PLAQUE (sa caméra est mesurée ; le panorama a
    été peint avec l'ancienne caméra devinée, ses hauteurs ne tombent pas sur celles du plan)."""
    coins = boites_du_plan(plan, noms)
    if not coins:
        raise SystemExit("rien au plan pour %s" % noms)
    cam = plan["camera"]
    th, ph, f = math.radians(cam["lacet"]), math.radians(cam["tangage"]), cam["f"]
    W, H = plaque.size
    cols, rangs = [], []
    for x, y, z in coins:             # même projection que les sources à plat de scene_blender.py
        haut = y - cam["hauteur"]
        zh, xc = x * math.sin(th) + z * math.cos(th), x * math.cos(th) - z * math.sin(th)
        zc, yc = zh * math.cos(ph) + haut * math.sin(ph), haut * math.cos(ph) - zh * math.sin(ph)
        cols.append(W / 2 + xc * f / max(zc, 0.05))
        rangs.append(H / 2 - yc * f / max(zc, 0.05))
    c0, c1, r0, r1 = min(cols), max(cols), min(rangs), max(rangs)
    mc, mr = marge * (c1 - c0), marge * (r1 - r0)
    decoupe = plaque.crop((max(0, int(c0 - mc)), max(0, int(r0 - mr)), min(W, int(c1 + mc)), min(H, int(r1 + mr))))
    az = [math.degrees(math.atan2(x, z)) for x, _, z in coins]
    emprise = [min(c[0] for c in coins), max(c[0] for c in coins), min(c[2] for c in coins), max(c[2] for c in coins)]
    return [min(az), max(az)], decoupe, emprise, [min(c[1] for c in coins), max(c[1] for c in coins)]


def decouper(pano, lacet, azimut, lignes, marge=0.08):
    W, H = pano.size
    a0, a1 = azimut
    da = (a1 - a0) % 360 or 360
    c0 = colonne(a0 - marge * da, lacet, W)
    largeur = (1 + 2 * marge) * da / 360.0 * W
    dh = lignes[1] - lignes[0]
    r0, r1 = max(0, int(lignes[0] - marge * dh)), min(H, int(lignes[1] + marge * dh))
    # le panorama boucle : découpe sur deux copies côte à côte
    double = Image.new("RGB", (2 * W, H))
    double.paste(pano, (0, 0))
    double.paste(pano, (W, 0))
    return double.crop((int(c0), r0, int(c0 + largeur), r1))


def decouper_droit(pano, lacet, azimut, lignes, marge=0.08, cote=1024):
    """La carte en PERSPECTIVE (propriétaire, 06/10 : « il faut refaire la planche carte, les murs sont arrondis ») :
    une découpe directe du panorama garde sa projection équirectangulaire (baie en arche, sol courbe), et H3, qui
    reçoit la carte en <Subject N>, peut recopier ces courbes dans la pièce. Ici, une caméra virtuelle visée au
    centre de l'élément (cap et site), champ à sa mesure, droites droites. Le côté le plus long fait `cote` pixels."""
    import numpy as np
    W, H = pano.size
    a0, a1 = azimut
    da = ((a1 - a0) % 360 or 360) * (1 + 2 * marge)
    cap = math.radians(a0 + ((a1 - a0) % 360) / 2 - lacet)       # 0 = milieu du panorama (vues_pano.vue)
    lat = [(0.5 - (r + 0.5) / H) * 180 for r in lignes]           # site du haut et du bas de l'élément
    dl = (lat[0] - lat[1]) * (1 + 2 * marge)
    site = math.radians((lat[0] + lat[1]) / 2)
    tl, th = math.tan(math.radians(min(da, 150) / 2)), math.tan(math.radians(min(dl, 150) / 2))
    fx = cote / 2 / max(tl, th)
    lo, ho = int(2 * fx * tl), int(2 * fx * th)
    x, y = np.meshgrid((np.arange(lo) - lo / 2 + 0.5) / fx, (np.arange(ho) - ho / 2 + 0.5) / fx)
    # rayon caméra (x droite, y bas, z devant), relevé du site puis tourné du cap
    cs, ss = math.cos(site), math.sin(site)
    Y, Z = -y * cs + ss, y * ss + cs
    cc, sc = math.cos(cap), math.sin(cap)
    X, Z = x * cc + Z * sc, -x * sc + Z * cc
    lon, la = np.arctan2(X, Z), np.arctan2(Y, np.hypot(X, Z))
    u = ((lon / (2 * np.pi) + 0.5) * W - 0.5) % W
    v = np.clip((0.5 - la / np.pi) * H - 0.5, 0, H - 1)
    p = np.asarray(pano, np.float32)
    u0, v0 = np.floor(u).astype(int), np.clip(np.floor(v).astype(int), 0, H - 2)
    du, dv = (u - u0)[..., None], np.clip(v - v0, 0, 1)[..., None]
    u1 = (u0 + 1) % W
    haut = p[v0, u0] * (1 - du) + p[v0, u1] * du
    bas = p[v0 + 1, u0] * (1 - du) + p[v0 + 1, u1] * du
    return Image.fromarray((haut * (1 - dv) + bas * dv).clip(0, 255).astype(np.uint8))


def redresser(essai, cartes_json, pano_png, lacet):
    """Refait en perspective les cartes découpées dans le panorama (celles du plan viennent de la plaque, déjà
    droites) ; l'ancienne image est gardée en <nom>_courbe.png, la planche est refaite."""
    essai = Path(essai).resolve()
    sortie = essai / "cartes"
    pano = Image.open(pano_png).convert("RGB")
    fiches = json.loads((sortie / "cartes_lieu.json").read_text(encoding="utf-8"))
    entree = {c["nom"]: c for c in json.loads(Path(cartes_json).read_text(encoding="utf-8"))}
    for f in fiches:
        c = entree.get(f["nom"])
        if not c or "lignes" not in c:
            continue
        img = sortie / f["image"]
        garde = sortie / (f["nom"] + "_courbe.png")
        if not garde.is_file():
            img.replace(garde)
        decouper_droit(pano, float(lacet), c["azimut"], c["lignes"]).save(img)
        print("carte %-18s redressée" % f["nom"], flush=True)
    planche(sortie, fiches)


def cartes(essai, plan_json, cartes_json):
    essai = Path(essai).resolve()
    plan = json.loads(Path(plan_json).read_text(encoding="utf-8"))
    pano, lacet = pano_de(essai)
    plaque = Image.open(essai / "plaque.png").convert("RGB")
    sortie = essai / "cartes"
    sortie.mkdir(exist_ok=True)
    fiches = []
    for c in json.loads(Path(cartes_json).read_text(encoding="utf-8")):
        fiche = {"nom": c["nom"], "description": c["description"]}
        if "plan" in c:
            az, decoupe, emprise, haut = depuis_plan(plan, c["plan"], plaque)
            fiche.update({"emprise": [round(v, 2) for v in emprise], "hauteur": [round(v, 2) for v in haut]})
        else:
            az = c["azimut"]
            decoupe = decouper(pano, lacet, az, c["lignes"])
        fiche["azimut"] = [round(az[0], 1), round(az[1], 1)]
        decoupe.save(sortie / (c["nom"] + ".png"))
        fiche["image"] = c["nom"] + ".png"
        fiches.append(fiche)
        print("carte %-18s azimut %7.1f .. %7.1f %s" % (c["nom"], az[0], az[1],
                                                         "plan" if "emprise" in fiche else "pano"), flush=True)
    (sortie / "cartes_lieu.json").write_text(json.dumps(fiches, indent=1, ensure_ascii=False), encoding="utf-8")
    planche(sortie, fiches)


def planche(sortie, fiches, case=(360, 300)):
    cw, ch = case
    n = len(fiches)
    cols = 4
    p = Image.new("RGB", (cols * cw, ((n + cols - 1) // cols) * (ch + 70)), "white")
    d = ImageDraw.Draw(p)
    for i, f in enumerate(fiches):
        im = Image.open(sortie / f["image"])
        im.thumbnail(case)
        x, y = (i % cols) * cw, (i // cols) * (ch + 70)
        p.paste(im, (x + (cw - im.width) // 2, y))
        texte = "%s  az %s..%s%s" % (f["nom"], *f["azimut"], "  (plan)" if "emprise" in f else "")
        d.text((x + 6, y + ch + 4), texte, fill="black")
        mots, ligne, yy = f["description"].split(), "", y + ch + 20
        for m in mots:               # description repliée sur la largeur de la case
            if len(ligne) + len(m) > 56:
                d.text((x + 6, yy), ligne, fill=(70, 70, 70))
                ligne, yy = "", yy + 13
            ligne += m + " "
        d.text((x + 6, yy), ligne, fill=(70, 70, 70))
    p.save(sortie / "planche_cartes.jpg", quality=88)


def grille(essai):
    """Panorama quadrillé (azimut tous les 15°, lignes du pano tous les 128 px) pour écrire cartes.json."""
    essai = Path(essai).resolve()
    pano, lacet = pano_de(essai)
    W, H = pano.size
    im = pano.resize((W // 2, H // 2))
    d = ImageDraw.Draw(im)
    for az in range(-180, 181, 15):
        x = colonne(az, lacet, W) / 2
        d.line([(x, 0), (x, H // 2)], fill=(255, 0, 0) if az % 45 == 0 else (255, 160, 160))
        d.text((x + 3, 4 + (az % 45 != 0) * 14), str(az), fill="red")
    for r in range(0, H, 128):
        d.line([(0, r / 2), (W / 2, r / 2)], fill=(0, 120, 255))
        d.text((3, r / 2 + 2), str(r), fill="blue")
    im.save(essai / "pano_grille.jpg", quality=85)
    print("ok", essai / "pano_grille.jpg")


def visibles(fiches, cap, demi_champ):
    """Cartes dont l'azimut recoupe [cap - demi_champ, cap + demi_champ] (degrés, boucle sur 360)."""
    def recoupe(a0, a1):
        milieu, demi = (a0 + (a1 - a0) / 2), (a1 - a0) / 2
        ecart = abs((milieu - cap + 180) % 360 - 180)
        return ecart <= demi + demi_champ
    return [f for f in fiches if recoupe(*f["azimut"])]


if __name__ == "__main__":
    if sys.argv[1] == "--grille":
        grille(sys.argv[2])
    elif sys.argv[1] == "--redresser":      # --redresser <essai> <cartes.json> <pano.png> <lacet>
        redresser(*sys.argv[2:6])
    else:
        cartes(*sys.argv[1:4])
