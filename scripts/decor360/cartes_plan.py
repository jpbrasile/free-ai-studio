"""Cartes d'identité des éléments tirées de la MAQUETTE du plan (propriétaire, 06/10 : « tu règles à la main alors
que l'on a un modèle en 3d » ; « fais tout ça »).

cartes_elements.py prenait l'azimut et les lignes des éléments hors plan à la main, sur le panorama quadrillé. Ici
chaque carte nomme des boîtes de maquette_plan.py (préfixes de noms) ; azimut et lignes viennent de leurs coins, vus de
la caméra ; la découpe est la vue en perspective du panorama né de cette maquette (cartes_elements.decouper_droit).
Les descriptions viennent du cartes.json donné ; les cartes qu'il n'a pas sont ignorées.

  python cartes_plan.py <plan.json> <cartes.json (descriptions)> <pano.png> <essai>
Sortie : <essai>/cartes/<nom>.png, cartes_lieu.json, planche_cartes.jpg (lus par tour360_ref.py et latent_chaine.py).
"""
import json
import math
import sys
from pathlib import Path

from PIL import Image

import cartes_elements as ce
import maquette as mq
import maquette_plan as mp

# carte -> préfixes des boîtes de la maquette ; "baie" et "mur_gauche_fond" sont des pans de mur, pas des boîtes
BOITES = {"baie_jardin": ["baie"], "canape": ["canape"], "table_basse": ["table"],
          "portes_droite": ["ouverture"], "etagere_coin": ["bibliotheque"], "porte_bois": ["porte"],
          "fauteuil": ["fauteuil"], "lampe": ["lampe"], "grande_bibliotheque": ["biblio_"],
          "mur_nu": ["mur_gauche_fond"]}
SITE_MAX = 40.0       # degrés : la baie passe à 16 cm de la caméra, elle irait du sol au zénith ; la carte s'arrête là


def coins(plan, prefixes):
    """Coins (x, y vers le bas, z) des boîtes de la maquette dont le nom commence par un des préfixes."""
    (x0, _), (z0, _) = plan["piece"]["x"], plan["piece"]["z"]
    h, haut = plan["camera"]["hauteur"], plan["piece"]["plafond"]
    boites = [(b0, b1) for nom, b0, b1, _ in mq.OBJETS if any(nom.startswith(p) for p in prefixes)]
    if "ouverture" in prefixes:
        boites += [(b0, (b0[0] + 0.05, b1[1], b1[2])) for b0, b1 in mq.OUVERTURES]
    if "baie" in prefixes:
        bz0, bz1 = plan["baie_gauche_z"]
        boites.append(((x0, h - haut, bz0), (x0, h, bz1)))
    if "mur_gauche_fond" in prefixes:
        boites.append(((x0, h - haut, z0), (x0, h, min(plan["baie_gauche_z"]))))
    return [(x, y, z) for b0, b1 in boites for x in (b0[0], b1[0]) for y in (b0[1], b1[1]) for z in (b0[2], b1[2])]


def azimut_lignes(pts, haut_pano):
    az = [math.degrees(math.atan2(x, z)) for x, _, z in pts]
    ref = az[0]
    az = [ref + ((a - ref + 180) % 360 - 180) for a in az]          # déroulé autour du premier coin (fond à 180°)
    lat = [max(-SITE_MAX, min(SITE_MAX, math.degrees(math.atan2(-y, math.hypot(x, z))))) for x, y, z in pts]
    lignes = [(0.5 - la / 180) * haut_pano for la in (max(lat), min(lat))]
    return [min(az), max(az)], [round(lignes[0]), round(lignes[1])]


def main(plan_json, cartes_json, pano_png, essai):
    plan = json.loads(Path(plan_json).read_text(encoding="utf-8"))
    mp.construire(plan)
    lacet = plan["camera"]["lacet"]
    pano = Image.open(pano_png).convert("RGB")
    sortie = Path(essai) / "cartes"
    sortie.mkdir(parents=True, exist_ok=True)
    fiches = []
    for c in json.loads(Path(cartes_json).read_text(encoding="utf-8")):
        if c["nom"] not in BOITES:
            continue
        pts = coins(plan, BOITES[c["nom"]])
        if not pts:
            raise SystemExit("rien dans la maquette pour %s" % c["nom"])
        az, lignes = azimut_lignes(pts, pano.size[1])
        ce.decouper_droit(pano, lacet, az, lignes).save(sortie / (c["nom"] + ".png"))
        fiches.append({"nom": c["nom"], "description": c["description"], "azimut": [round(a, 1) for a in az],
                       "lignes": lignes, "image": c["nom"] + ".png"})
        print("carte %-20s azimut %7.1f .. %7.1f  lignes %d..%d" % (c["nom"], *az, *lignes), flush=True)
    (sortie / "cartes_lieu.json").write_text(json.dumps(fiches, indent=1, ensure_ascii=False), encoding="utf-8")
    ce.planche(sortie, fiches)


if __name__ == "__main__":
    main(*sys.argv[1:5])
