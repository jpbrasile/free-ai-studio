"""Le décor en 3D sous Blender (propriétaire, 05/10 : « oui lance l'essai Blender + AnyAngle, on part d'une image et
de son contre plan »).

La pièce en boîtes de maquette.py devient une scène : murs, baie vitrée (verre et montants), ouvertures du mur droit,
meubles, jardin dehors. Chaque surface reçoit en projection les photos sources (la plaque, de face ; le contrechamp,
retourné) ; ce qu'aucune ne voit reste en aplat ombré de sa couleur. Rendu Cycles (processeur) des caméras demandées :
c'est le « rendu grossier » que l'AnyAngle de Qwen-Image 2.1 reporte sur la photo.

  blender -b --factory-startup -noaudio -P scene_blender.py -- <scene.json> <dossier de sortie>

scene.json : {"geometrie": maquette.geometrie(), "taille": [L, H],
              "sources": [{"image": chemin, "lacet": degrés, "tangage": degrés, "f": px} | {"image": chemin, "type": "pano", "lacet": degrés}],
              "cameras": [{"nom": ..., "pos": [x, y, z], "lacet": degrés, "tangage": degrés, "f": px}],
              "controles": [[nom, u, v, distance attendue]]}   (tangage, lacet du pano, controles : facultatifs)
Repère du JSON = celui de maquette.py (x à droite, y vers le bas, z devant, caméra source à l'origine) ;
Blender : X = x, Y = z, Z = -y.
Occultation (05/10, travelling) : toutes les sources sont prises de l'origine ; une carte de profondeur
équirectangulaire vue de l'origine (lancer de rayons NumPy sur les boîtes, verre exclu, `profondeur.exr`) dit la
première surface de chaque rayon, et une source ne peint que celle-là. Sans elle, un montant de la photo se peignait
aussi sur la haie à 30 m, et la table sur le sol derrière elle : des fantômes qui glissent dès que la caméra bouge.
"""
import json
import math
import sys
from pathlib import Path

import bpy
import numpy as np

EP = 0.02          # épaisseur des murs, posés hors de la pièce
PROF_L, PROF_H = 4096, 2048     # carte de profondeur équirectangulaire (0,09° par pixel)
BOITES = []        # (lo, hi) en repère Blender de chaque boîte opaque : ce que la carte de profondeur voit


def vers_b(p):
    return (p[0], p[2], -p[1])


def cube(nom, pmin, pmax, mat, opaque=True):
    a, b = vers_b(pmin), vers_b(pmax)
    lo, hi = [min(a[i], b[i]) for i in range(3)], [max(a[i], b[i]) for i in range(3)]
    if opaque:
        BOITES.append((lo, hi))
    bpy.ops.mesh.primitive_cube_add(size=1, location=[(lo[i] + hi[i]) / 2 for i in range(3)])
    o = bpy.context.object
    o.name = nom
    o.scale = [max(hi[i] - lo[i], 1e-3) for i in range(3)]
    o.data.materials.append(mat)
    return o


class Noeuds:
    def __init__(self, mat):
        mat.use_nodes = True
        self.nt = mat.node_tree
        self.nt.nodes.clear()

    def n(self, genre, **reglages):
        nd = self.nt.nodes.new(genre)
        for k, v in reglages.items():
            setattr(nd, k, v)
        return nd

    def lier(self, sortie, entree):
        if isinstance(sortie, (int, float)):
            entree.default_value = sortie
        else:
            self.nt.links.new(sortie, entree)

    def m(self, op, a, b=0.0):
        nd = self.n("ShaderNodeMath", operation=op)
        self.lier(a, nd.inputs[0])
        self.lier(b, nd.inputs[1])
        return nd.outputs[0]


def directions_eq(largeur, hauteur):
    """Direction (repère Blender) du centre de chaque pixel de la carte équirectangulaire, rangée 0 en bas : la
    même correspondance que les nœuds de materiau() (lon = atan2(X, Y), lat = atan2(Z, |XY|))."""
    lon = ((np.arange(largeur, dtype=np.float32) + 0.5) / largeur - 0.5) * 2 * np.pi
    lat = ((np.arange(hauteur, dtype=np.float32) + 0.5) / hauteur - 0.5) * np.pi
    lon, lat = np.meshgrid(lon, lat)
    return np.cos(lat) * np.sin(lon), np.cos(lat) * np.cos(lon), np.sin(lat)


def profondeur(image):
    """Distance de l'origine à la première boîte opaque, par pixel de la carte, écrite dans `image` (float, RGBA).
    L'image garde le maximum des 3 x 3 voisins : un mur rasant ne s'occulte pas lui-même d'un pixel à l'autre.
    Rend la carte brute (pour le contrôle d'orientation)."""
    w, h = image.size
    d = [np.where(np.abs(c) < 1e-6, np.float32(1e-6), c) for c in directions_eq(w, h)]
    t = np.full((h, w), 1e4, dtype=np.float32)
    for lo, hi in BOITES:
        t0 = [np.minimum(lo[i] / d[i], hi[i] / d[i]) for i in range(3)]
        t1 = [np.maximum(lo[i] / d[i], hi[i] / d[i]) for i in range(3)]
        proche = np.maximum(np.maximum(t0[0], t0[1]), t0[2])
        loin = np.minimum(np.minimum(t1[0], t1[1]), t1[2])
        t = np.where((proche <= loin) & (proche > 0) & (proche < t), proche, t)
        del t0, t1, proche, loin
    plein = np.pad(t, ((1, 1), (0, 0)), mode="edge")
    m = t.copy()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            m = np.maximum(m, np.roll(plein, dx, axis=1)[1 + dy:1 + dy + h])
    px = np.repeat(m[..., None], 4, axis=2)
    px[..., 3] = 1.0
    image.pixels.foreach_set(px.ravel())
    image.update()
    return t


def materiau(nom, rgb, sources, taille, prof):
    """Aplat diffus de couleur rgb, remplacé par la photo d'une source (émission, couleur exacte) là où elle voit
    cette surface en premier (carte `prof`, vue de l'origine comme toutes les sources)."""
    mat = bpy.data.materials.new(nom)
    s = Noeuds(mat)
    diffus = s.n("ShaderNodeBsdfDiffuse")
    diffus.inputs["Color"].default_value = (*rgb, 1.0)
    shader = diffus.outputs[0]
    position = s.n("ShaderNodeNewGeometry").outputs["Position"]
    pos = s.n("ShaderNodeSeparateXYZ")
    s.lier(position, pos.inputs[0])
    px, py, pz = pos.outputs[0], pos.outputs[1], pos.outputs[2]
    w, h = taille
    # vue des sources : distance à l'origine au plus celle de la carte (+ 2 % et 3 cm)
    lon = s.m("ARCTAN2", px, py)
    lat = s.m("ARCTAN2", pz, s.m("SQRT", s.m("ADD", s.m("MULTIPLY", px, px), s.m("MULTIPLY", py, py))))
    uv_eq = s.n("ShaderNodeCombineXYZ")
    s.lier(s.m("ADD", 0.5, s.m("DIVIDE", lon, 2 * math.pi)), uv_eq.inputs[0])
    s.lier(s.m("ADD", 0.5, s.m("DIVIDE", lat, math.pi)), uv_eq.inputs[1])
    carte = s.n("ShaderNodeTexImage", extension="REPEAT", interpolation="Closest")
    carte.image = prof
    s.lier(uv_eq.outputs[0], carte.inputs["Vector"])
    rouge = s.n("ShaderNodeSeparateColor")
    s.lier(carte.outputs["Color"], rouge.inputs[0])
    longueur = s.n("ShaderNodeVectorMath", operation="LENGTH")
    s.lier(position, longueur.inputs[0])
    vu = s.m("LESS_THAN", longueur.outputs["Value"], s.m("ADD", s.m("MULTIPLY", rouge.outputs[0], 1.02), 0.03))
    # la première source l'emporte : on les empile de la dernière à la première
    for src in reversed(sources):
        pano = src.get("type") == "pano"
        if pano:
            # panorama équirectangulaire pris depuis l'origine, son milieu au `lacet` de la source : il couvre tout
            u = s.m("ADD", 0.5, s.m("DIVIDE", s.m("SUBTRACT", lon, math.radians(src.get("lacet", 0))),
                                    2 * math.pi))
            v = s.m("ADD", 0.5, s.m("DIVIDE", lat, math.pi))
            masque = vu
        else:
            # caméra tournée de `lacet` (vers la droite) puis inclinée de `tangage` (vers le haut si positif)
            th, ph = math.radians(src["lacet"]), math.radians(src.get("tangage", 0.0))
            zh = s.m("ADD", s.m("MULTIPLY", px, math.sin(th)), s.m("MULTIPLY", py, math.cos(th)))
            xc = s.m("SUBTRACT", s.m("MULTIPLY", px, math.cos(th)), s.m("MULTIPLY", py, math.sin(th)))
            zc = s.m("ADD", s.m("MULTIPLY", zh, math.cos(ph)), s.m("MULTIPLY", pz, math.sin(ph)))
            yc = s.m("SUBTRACT", s.m("MULTIPLY", pz, math.cos(ph)), s.m("MULTIPLY", zh, math.sin(ph)))
            zs = s.m("MAXIMUM", zc, 0.05)
            u = s.m("ADD", 0.5, s.m("DIVIDE", s.m("MULTIPLY", xc, src["f"] / w), zs))
            v = s.m("ADD", 0.5, s.m("DIVIDE", s.m("MULTIPLY", yc, src["f"] / h), zs))
            masque = s.m("MULTIPLY", vu, s.m("GREATER_THAN", zc, 0.05))
            for x in (u, v):
                masque = s.m("MULTIPLY", masque, s.m("GREATER_THAN", x, 0.0))
                masque = s.m("MULTIPLY", masque, s.m("LESS_THAN", x, 1.0))
        uv = s.n("ShaderNodeCombineXYZ")
        s.lier(u, uv.inputs[0])
        s.lier(v, uv.inputs[1])
        tex = s.n("ShaderNodeTexImage", extension="REPEAT" if pano else "CLIP")
        tex.image = src["bpy_image"]
        s.lier(uv.outputs[0], tex.inputs["Vector"])
        emis = s.n("ShaderNodeEmission")
        s.lier(tex.outputs["Color"], emis.inputs["Color"])
        mix = s.n("ShaderNodeMixShader")
        s.lier(masque, mix.inputs[0])
        s.lier(shader, mix.inputs[1])
        s.lier(emis.outputs[0], mix.inputs[2])
        shader = mix.outputs[0]
    sortie = s.n("ShaderNodeOutputMaterial")
    s.lier(shader, sortie.inputs["Surface"])
    return mat


def verre():
    mat = bpy.data.materials.new("verre")
    s = Noeuds(mat)
    mix = s.n("ShaderNodeMixShader")
    mix.inputs[0].default_value = 0.06
    s.lier(s.n("ShaderNodeBsdfTransparent").outputs[0], mix.inputs[1])
    s.lier(s.n("ShaderNodeBsdfGlossy").outputs[0], mix.inputs[2])
    s.lier(mix.outputs[0], s.n("ShaderNodeOutputMaterial").inputs["Surface"])
    return mat


def construire(geo, sources, taille, prof):
    h, (pmin, pmax) = geo["h_cam"], geo["piece"]
    x0, y0, z0 = pmin
    x1, y1, z1 = pmax
    rgb = geo["rgb_piece"]
    mats = {k: materiau(k, rgb[k], sources, taille, prof) for k in ("sol", "plafond", "mur", "ouverture")}
    mats["jardin"] = materiau("jardin", (0.35, 0.55, 0.25), sources, taille, prof)
    mats["fond"] = materiau("fond", (0.45, 0.55, 0.40), sources, taille, prof)
    cube("sol", (x0, y1, z0), (x1, y1 + EP, z1), mats["sol"])
    cube("plafond", (x0, y0 - EP, z0), (x1, y0, z1), mats["plafond"])
    cube("mur_arriere", (x0, y0, z0 - EP), (x1, y1, z0), mats["mur"])
    cube("mur_avant", (x0, y0, z1), (x1, y1, z1 + EP), mats["mur"])
    bz0, bz1 = geo["baie_z"]
    cube("mur_gauche", (x0 - EP, y0, z0), (x0, y1, bz0), mats["mur"])
    cube("baie", (x0 - EP, y0, bz0), (x0, y1, bz1), verre(), opaque=False)
    # mur droit : des pans entre les ouvertures, un linteau au-dessus de chacune, un renfoncement derrière
    z = z0
    for k, (omin, omax) in enumerate(sorted(geo["ouvertures"], key=lambda o: o[0][2])):
        cube("mur_droit_%d" % k, (x1, y0, z), (x1 + EP, y1, omin[2]), mats["mur"])
        cube("linteau_%d" % k, (x1, y0, omin[2]), (x1 + EP, omin[1], omax[2]), mats["mur"])
        xf = omax[0]
        cube("renf_sol_%d" % k, (x1, y1, omin[2]), (xf, y1 + EP, omax[2]), mats["ouverture"])
        cube("renf_haut_%d" % k, (x1 + EP, omin[1] - EP, omin[2]), (xf, omin[1], omax[2]), mats["ouverture"])
        cube("renf_fond_%d" % k, (xf, omin[1], omin[2]), (xf + EP, y1, omax[2]), mats["ouverture"])
        cube("renf_g_%d" % k, (x1 + EP, omin[1], omin[2] - EP), (xf, y1, omin[2]), mats["ouverture"])
        cube("renf_d_%d" % k, (x1 + EP, omin[1], omax[2]), (xf, y1, omax[2] + EP), mats["ouverture"])
        z = omax[2]
    cube("mur_droit_fin", (x1, y0, z), (x1 + EP, y1, z1), mats["mur"])
    # dehors, côté baie : pelouse et un fond de haie lointain
    cube("pelouse", (-60.0, y1, -200.0), (x0 - EP, y1 + EP, 400.0), mats["jardin"])
    cube("haie", (-30.0 - EP, y1 - 80.0, -200.0), (-30.0, y1, 400.0), mats["fond"])
    for o in geo["objets"]:
        cube(o["nom"], o["min"], o["max"], materiau("m_" + o["nom"], o["rgb"], sources, taille, prof))
    del h


def lumieres():
    monde = bpy.data.worlds.new("ciel")
    bpy.context.scene.world = monde
    monde.use_nodes = True
    fond = monde.node_tree.nodes["Background"]
    fond.inputs["Color"].default_value = (0.75, 0.85, 1.0, 1.0)
    fond.inputs["Strength"].default_value = 0.45
    soleil = bpy.data.objects.new("soleil", bpy.data.lights.new("soleil", type="SUN"))
    soleil.data.energy = 1.2
    soleil.rotation_euler = (math.radians(50), 0, math.radians(-60))
    bpy.context.scene.collection.objects.link(soleil)
    lampe = bpy.data.objects.new("plafonnier", bpy.data.lights.new("plafonnier", type="AREA"))
    lampe.data.energy = 40
    lampe.data.size = 3
    lampe.location = (0.6, 1.0, 1.6)
    bpy.context.scene.collection.objects.link(lampe)


def main(scene_json, dossier):
    cfg = json.loads(Path(scene_json).read_text(encoding="utf-8"))
    dossier = Path(dossier)
    dossier.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    w, h = cfg["taille"]
    sources = []
    for s in cfg["sources"]:
        s = dict(s)
        s["bpy_image"] = bpy.data.images.load(str((Path(scene_json).parent / s["image"]).resolve()))
        sources.append(s)
    prof = bpy.data.images.new("profondeur", PROF_L, PROF_H, float_buffer=True)
    prof.colorspace_settings.name = "Non-Color"
    construire(cfg["geometrie"], sources, (w, h), prof)
    t = profondeur(prof)
    prof.filepath_raw = str(dossier / "profondeur.exr")
    prof.file_format = "OPEN_EXR"
    prof.save()
    # contrôle de la correspondance pixel <-> direction (la scène peut donner les siens : scene_plan.py)
    (x0, y0, z0), (x1, y1, z1) = cfg["geometrie"]["piece"]
    controles = cfg.get("controles") or [
        ("devant", 0.5, 0.5, z1), ("droite", 0.75, 0.5, x1), ("derriere (bibliotheque)", 0.0, 0.5, 2.62),
        ("sol", 0.5, 0.0, y1), ("plafond", 0.5, 0.9999, -y0)]
    for quoi, i, j, attendu in controles:
        lu = float(t[min(int(j * PROF_H), PROF_H - 1), min(int(i * PROF_L), PROF_L - 1)])
        print("PROFONDEUR %-24s %.2f m (attendu %.2f)" % (quoi, lu, attendu), flush=True)
        if abs(lu - attendu) > 0.05:
            raise SystemExit("carte de profondeur mal orientée (%s)" % quoi)
    lumieres()
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.cycles.samples = 128
    sc.cycles.use_denoising = True
    sc.cycles.max_bounces = 4
    sc.cycles.transparent_max_bounces = 8
    sc.render.resolution_x, sc.render.resolution_y = w, h
    sc.render.resolution_percentage = 100
    sc.render.image_settings.file_format = "PNG"
    sc.view_settings.view_transform = "Standard"
    sc.view_settings.look = "None"
    for c in cfg["cameras"]:
        cam = bpy.data.cameras.new(c["nom"])
        cam.sensor_fit = "HORIZONTAL"
        cam.sensor_width = 36.0
        cam.lens = c["f"] * 36.0 / w
        cam.clip_start = 0.05
        cam.clip_end = 200.0
        obj = bpy.data.objects.new(c["nom"], cam)
        sc.collection.objects.link(obj)
        obj.location = vers_b(c["pos"])
        obj.rotation_euler = (math.pi / 2 + math.radians(c.get("tangage", 0.0)), 0.0, -math.radians(c["lacet"]))
        sc.camera = obj
        sc.render.filepath = str(dossier / ("rendu_%s.png" % c["nom"]))
        bpy.ops.render.render(write_still=True)
        print("RENDU", c["nom"], flush=True)


if __name__ == "__main__":
    args = sys.argv[sys.argv.index("--") + 1:]
    main(args[0], args[1])
