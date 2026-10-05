"""scene.json pour scene_blender.py depuis un PLAN au sol (propriétaire, 05/10 : « partir du sol à plat, poser
l'emprise des éléments clés, puis ajouter la hauteur » ; « build from the plan »).

Le plan (JSON, mesuré sur le nuage MoGe-3 de la plaque : moge_plaque.py puis plan_moge.py) donne, dans le repère de
la pièce (x à droite, z devant, murs sur les axes, caméra de la plaque à l'origine) :
  camera   {hauteur, lacet, tangage, f}      la plaque : tournée de `lacet` par rapport aux murs, inclinée de
                                             `tangage` (négatif = vers le bas)
  piece    {x: [x0, x1], z: [z0, z1], plafond}
  baie_gauche_z [z0, z1]                     la vitre sur le mur x0
  elements [{nom, emprise: [x0, x1, z0, z1], hauteur: [bas, haut], rgb}]
  ouvertures_droite [{nom, z: [z0, z1], haut, fond_x}]
  cibles   [{nom, devant, droite, tourne}]   déplacement et rotation RELATIFS à la plaque
Sources : la plaque, le contrechamp et le panorama, tous pris de l'origine dans le repère de la plaque (tournés du
même lacet). Le contrechamp et le panorama ont été faits sur l'ancienne maquette : seuls les angles que la plaque ne
voit pas en dépendent.

  python scene_plan.py <plan.json> <plaque.png> <contrechamp.png> <pano.png> <scene.json>
"""
import json
import math
import shutil
import sys
from pathlib import Path

F_CONTRE = 875.7674505492903       # focale des vues de l'étape 2 (75°), celle du contrechamp
RGB_PIECE = {"sol": (0.78, 0.72, 0.62), "plafond": (0.96, 0.95, 0.93), "mur": (0.92, 0.88, 0.80),
             "baie": (0.47, 0.63, 0.35), "ouverture": (0.45, 0.42, 0.38)}


def scene(plan, plaque, contre, pano, sortie):
    p = json.loads(Path(plan).read_text(encoding="utf-8"))
    sortie = Path(sortie)
    sortie.parent.mkdir(parents=True, exist_ok=True)
    for src, nom in ((plaque, "plaque.png"), (contre, "contre.png"), (pano, "pano.png")):
        if Path(src).resolve() != (sortie.parent / nom).resolve():
            shutil.copyfile(src, sortie.parent / nom)
    cam = p["camera"]
    h = cam["hauteur"]
    (x0, x1), (z0, z1), plafond = p["piece"]["x"], p["piece"]["z"], p["piece"]["plafond"]

    def boite(emprise, bas, haut):    # repère de maquette.py : y vers le bas, sol à y = h
        ex0, ex1, ez0, ez1 = emprise
        return [ex0, h - haut, ez0], [ex1, h - bas, ez1]

    objets = []
    for e in p["elements"]:
        bmin, bmax = boite(e["emprise"], *e["hauteur"])
        objets.append({"nom": e["nom"], "min": bmin, "max": bmax, "rgb": e["rgb"]})
    ouvertures = [[[x1 - 0.05, h - o["haut"], o["z"][0]], [o["fond_x"], h, o["z"][1]]] for o in p["ouvertures_droite"]]
    geo = {"h_cam": h, "fx": cam["f"], "piece": [[x0, h - plafond, z0], [x1, h, z1]],
           "baie_z": p["baie_gauche_z"], "objets": objets, "ouvertures": ouvertures, "rgb_piece": RGB_PIECE}
    lacet, tangage = cam["lacet"], cam["tangage"]
    sources = [{"image": "plaque.png", "lacet": lacet, "tangage": tangage, "f": cam["f"]},
               {"image": "contre.png", "lacet": lacet + 180, "f": F_CONTRE},
               {"image": "pano.png", "type": "pano", "lacet": lacet}]
    cameras = [{"nom": "verif_plaque", "pos": [0, 0, 0], "lacet": lacet, "tangage": tangage, "f": cam["f"]}]
    a = math.radians(lacet)
    for c in p["cibles"]:            # devant / droite dans le repère de la plaque, ramenés à celui de la pièce
        pos = [c["droite"] * math.cos(a) + c["devant"] * math.sin(a), 0.0,
               -c["droite"] * math.sin(a) + c["devant"] * math.cos(a)]
        cameras.append({"nom": c["nom"], "pos": pos, "lacet": lacet + c["tourne"], "tangage": tangage,
                        "f": cam["f"]})
    # contrôles de la carte de profondeur (rayons horizontaux depuis l'origine, à hauteur de caméra)
    controles = [["sol", 0.5, 0.0, h], ["plafond", 0.5, 0.9999, plafond - h], ["droite", 0.75, 0.5, x1],
                 ["derriere", 0.0, 0.5, -z0]]
    cfg = {"geometrie": geo, "taille": [1344, 768], "sources": sources, "cameras": cameras, "controles": controles}
    sortie.write_text(json.dumps(cfg, indent=1), encoding="utf-8")
    print("ok", sortie, "; cibles :", ", ".join("%s %s lacet %.1f" % (c["nom"], [round(v, 2) for v in c["pos"]],
                                                                     c["lacet"]) for c in cameras))


if __name__ == "__main__":
    scene(*sys.argv[1:6])
