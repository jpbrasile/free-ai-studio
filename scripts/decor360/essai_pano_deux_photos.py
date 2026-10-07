"""Le panorama d'un lieu depuis ses DEUX photos (propriétaire, 06/10 : « then paint the panoramas from the gemini
photos (front and back) ») : la photo de face et la vue à 180° (essai_image_gemini.py) collées dans la maquette du
plan tiré par un agent Claude de ces deux photos (essai_plan_claude.py), le reste peint comme le Studio
(tour360_pano, Union + couture + SeedVR2) sur la carte d'ici. Le repère est celui du plan : caméra de niveau à 1,6 m
en (0, 0), face = +z, champ de la photo (1376 px pour environ 80°, fx 820, comme l'ont mesuré les agents).

  python essai_pano_deux_photos.py <sortie gemini> [cas ...]   -> <cas>/pano/{pano.png, maquette.png, cle_*.png,
                                                                 carte_*.png, texte.txt, sortie.log}
"""
import base64
import json
import math
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sandbox-manager"))
import essai_mesure_studio  # noqa: E402
import plan_piece  # noqa: E402
import tour360  # noqa: E402
import video_h3  # noqa: E402
from essai_plans_texte import CAS  # noqa: E402
from essai_tour_texte import panorama_local  # noqa: E402
from PIL import Image  # noqa: E402

FX_80 = 820.0 / 1376          # fx par pixel de largeur (champ d'environ 80°)
# Ligne d'horizon (v, px sur 768) relevée à l'œil par les agents qui ont tiré les plans (06/10) : seulement
# imprimée à côté de la mesure MoGe, pour comparer.
HORIZON_AGENTS = {"plage": {"face": 425}, "rue": {"face": 410, "dos": 440}}


def R_tangage(deg):
    """La rotation caméra -> pièce d'une caméra levée (`deg` > 0, horizon sous le milieu) ou baissée, sans roulis."""
    t = math.radians(deg)
    c, s = math.cos(t), math.sin(t)
    return [[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]]


def tangage(d, quelle, photo):
    """Le tangage (degrés) de la caméra d'une photo, mesuré par MoGe-3 comme à l'étape « mesure » du Studio
    (essai_mesure_studio, GPU) ; 0 = de niveau si MoGe ne voit pas de sol (propriétaire, 06/10 : « measure the
    horizon with MoGe on both photos », défaut 0)."""
    sortie = d / ("mesure_" + quelle)
    geo = sortie / "geometrie.json"
    if not geo.is_file():
        essai_mesure_studio.main(photo, sortie)
    if not geo.is_file():
        return 0.0, None
    g = json.loads(geo.read_text(encoding="utf-8"))
    return float(g["tangage"]), g
TEXTE2 = Path("C:/Users/test/Desktop/leila_sf/tours_texte_2")


def texte(piece, plan, geo, dos=True):
    """La consigne du dessin sans ce que montrent les photos (devant, et derrière si `dos`)."""
    if not dos:
        return plan_piece.texte_panorama(piece, plan, geo, photo=True)
    demi = plan_piece.demi_champ_photo(geo) * 0.8
    reste = []
    for e in plan["elements"]:
        x = plan_piece.etendue(e, plan, geo)
        milieu = (x["a0"] + x["a1"]) / 2 % 360
        if min(milieu, 360 - milieu) > demi and abs(milieu - 180) > demi:
            reste.append(e)
    return plan_piece.texte_panorama(piece, dict(plan, elements=reste), geo, photo=True) \
        .replace("Behind the camera: ", "Also: ")


def main(sortie, noms, face=None):
    """`face` : dossier des lieux à deux photos ; on n'en prend que la face, le plan et sa mesure (la vue de dos,
    jugée incohérente par essai_coherence_photos.py, recopie la face : le dos se peint d'après le plan, dans le même
    panorama — « panorama d'abord »)."""
    for nom in noms or list(CAS):
        d = sortie / nom
        if face is not None and not (d / "claude").is_dir():
            d.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(face / nom / "photo.png", d / "photo.png")
            shutil.copytree(face / nom / "claude", d / "claude")
            if (face / nom / "mesure_face").is_dir():
                shutil.copytree(face / nom / "mesure_face", d / "mesure_face")
        if not (d / "claude" / "plan.json").is_file():
            print(json.dumps({"cas": nom, "pano": "pas de plan Claude"}), flush=True)
            continue
        if (d / "pano" / "pano.png").is_file():
            continue
        lu = json.loads((d / "claude" / "plan.json").read_text(encoding="utf-8"))
        plan, geo = lu["plan"], lu["geo"]
        avec_dos = face is None
        photo, dos = (d / "photo.png").read_bytes(), (d / "photo_dos.png").read_bytes() if avec_dos else None
        w, h = Image.open(d / "photo.png").size
        geo = dict(geo, taille=[w, h], fx=FX_80 * w)
        mesures = {"dos": {"tangage": 0.0}}
        for quelle, f in (("face", "photo.png"), ("dos", "photo_dos.png"))[:2 if avec_dos else 1]:
            t, g = tangage(d, quelle, d / f)
            v = HORIZON_AGENTS.get(nom, {}).get(quelle)
            mesures[quelle] = {"tangage": round(t, 2), "horizon_v": round(h / 2 + geo["fx"] * math.tan(math.radians(t))),
                               "agent_v": v, "fx_moge": round(g["fx"]) if g else None, "moge": g is not None}
        (d / "tangages.json").write_text(json.dumps(mesures, indent=1), encoding="utf-8")
        print(json.dumps({"cas": nom, "tangages": mesures}), flush=True)
        geo.update(R=R_tangage(mesures["face"]["tangage"]), R_dos=R_tangage(mesures["dos"]["tangage"]))
        try:
            piece = json.loads((TEXTE2 / nom / "tour.json").read_text(encoding="utf-8"))["consigne"]["piece"]
        except (OSError, KeyError, ValueError):
            piece = "the " + nom
        t = texte(piece, plan, geo, avec_dos)
        cartes = [{k: c[k] for k in ("nom", "a0", "a1", "haut", "bas")} for c in plan_piece.cartes_du_plan(plan, geo)]
        dem = tour360.demande(photo, t, tour360.GRAINE, tour360.PAS, geo, plan_piece.scene_du_plan(plan, geo), cartes)
        if avec_dos:
            dem["photo_dos"] = base64.b64encode(dos).decode()
        source = (Path(tour360.__file__).with_name("tour360_pano.py")).read_text(encoding="utf-8")
        script = video_h3._emballer(source + "\n\nprincipal()\n", dem)
        tour360.construire_script = lambda *a, **k: script        # panorama_local écrit ce script-là
        try:
            fichiers = panorama_local(d, "essai-pano-deux-" + nom)(photo, t, tour360.GRAINE, tour360.PAS)
            print(json.dumps({"cas": nom, "pano": "fait", "fichiers": len(fichiers), "cartes": len(cartes)}),
                  flush=True)
        except tour360.Arret as exc:
            print(json.dumps({"cas": nom, "pano": "echec", "erreur": str(exc)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    a = sys.argv[1:]
    face = None
    if "--face" in a:                       # --face <dossier à deux photos> : la face seule (dos d'après le plan)
        i = a.index("--face")
        face = Path(a[i + 1]).resolve()
        del a[i:i + 2]
    main(Path(a[0]).resolve(), a[1:], face)
