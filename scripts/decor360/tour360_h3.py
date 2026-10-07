"""Tour complet sur place en H3 (propriétaire, 05/10 : « do a 360° clip »).

Une rotation depuis le point de la photo est exacte : chaque vue vient de la plaque et du panorama sans erreur de
parallaxe. H3 ne prend qu'une première et une dernière image : le tour est coupé en tronçons de PAS degrés (8 x 45°,
assez de recouvrement entre deux vues voisines à fx 756), chacun un clip H3 « panoramique vers la droite » d'une
image clé à la suivante, puis les tronçons sont mis bout à bout (la première image d'un tronçon = la dernière du
précédent : retirée). Images clés : la plaque à 0° et 360°, les rendus `rendus/rendu_r<angle>.png` de scene_blender.py
entre les deux (cibles {"devant": 0, "droite": 0, "tourne": angle} du plan, scene_plan.py).

Avec les cartes d'identité du lieu (cartes_elements.py, <dossier>/cartes/cartes_lieu.json, prises d'office si
présentes), chaque tronçon reçoit la liste exacte de ce qu'il voit au départ, à l'arrivée et en passant, et
« rien d'autre » : sans elles, un mur nu laisse H3 inventer une autre pièce (05/10 : canapé gris, tableau, tapis).

  python tour360_h3.py <dossier de l'essai> [graine] [pas]      (lancer par la file : ressource gpu, ~3 min/tronçon)
  -> <dossier>/tour360_cartes/tour360_g<graine>.mp4 avec cartes, <dossier>/tour360/… sans (+ un mp4 par tronçon)
"""
import json
import math
import subprocess
import sys
from pathlib import Path

import cartes_elements
import travelling_h3

PAS = 45
CONSIGNE = {
    "mouvement": ("A slow, steady pan to the right: the camera stays in place at eye level and turns smoothly about "
                  "forty-five degrees on its axis, revealing the rest of the quiet living room in soft afternoon "
                  "daylight. Nothing in the room moves; only the garden leaves stir gently outside."),
    "premiere": "the living room, seen from where the camera stands.",
    "derniere": "the same living room, the camera turned further to the right.",
    "camera": {"mouvement": "pano_droite", "vitesse": "lente"},
}


NOMBRES = {30: "thirty", 45: "forty-five", 60: "sixty"}


def tourne(pas):
    return CONSIGNE["mouvement"].replace("forty-five", NOMBRES.get(pas, str(pas)))


def liste(fiches):
    return "; ".join(f["description"] for f in fiches) if fiches else "plain cream walls"


def consignes_cartes(dossier, n, pas):
    """Une consigne par tronçon, tirée des cartes : ce que montrent la première et la dernière image, et tout ce que
    la caméra croise entre les deux, rien de plus."""
    fiches = json.loads((dossier / "cartes" / "cartes_lieu.json").read_text(encoding="utf-8"))
    cfg = json.loads((dossier / "scene.json").read_text(encoding="utf-8"))
    cam = next(c for c in cfg["cameras"] if c["nom"] == "verif_plaque")
    demi = math.degrees(math.atan(cfg["taille"][0] / 2 / cam["f"]))
    sortie = []
    for k in range(n):
        a, b = cam["lacet"] + k * pas, cam["lacet"] + (k + 1) * pas
        chemin = cartes_elements.visibles(fiches, (a + b) / 2, demi + pas / 2)
        sortie.append(dict(CONSIGNE, **{
            "mouvement": tourne(pas) + " The camera only passes: " + liste(chemin) + ". There is nothing "
                         "else in this part of the room: no other furniture, no pictures on the walls, no rug, no "
                         "other room.",
            "premiere": "the living room, showing " + liste(cartes_elements.visibles(fiches, a, demi)) + ".",
            "derniere": "the same living room, the camera turned further right, showing "
                        + liste(cartes_elements.visibles(fiches, b, demi)) + "."}))
    return sortie


def main(dossier, graine=11, pas=PAS):
    dossier = Path(dossier).resolve()
    avec_cartes = (dossier / "cartes" / "cartes_lieu.json").is_file()
    sortie = dossier / (("tour360_cartes" if avec_cartes else "tour360") + ("" if pas == PAS else "_%d" % pas))
    sortie.mkdir(exist_ok=True)
    cles = [dossier / "plaque.png"] + [dossier / "rendus" / ("rendu_r%03d.png" % a) for a in range(pas, 360, pas)] \
        + [dossier / "plaque.png"]
    manque = [str(c) for c in cles if not c.is_file()]
    if manque:
        raise SystemExit("images clés absentes : " + ", ".join(manque))
    consignes = consignes_cartes(dossier, len(cles) - 1, pas) if avec_cartes else [dict(CONSIGNE, mouvement=tourne(pas))] * (len(cles) - 1)
    (sortie / "consignes.json").write_text(json.dumps(consignes, indent=1, ensure_ascii=False), encoding="utf-8")
    troncons = []
    for k in range(len(cles) - 1):
        f = sortie / ("troncon_%02d_g%d.mp4" % (k, graine))
        if not f.is_file():
            rc, _ = travelling_h3.clip(cles[k], cles[k + 1], f, graine, consigne=consignes[k])
            if rc:
                raise SystemExit("tronçon %d en échec (rc %d)" % (k, rc))
        troncons.append(f)
    final = sortie / ("tour360_g%d.mp4" % graine)
    bout_a_bout(troncons, final)
    print("FAIT", final, len(troncons), "tronçons", flush=True)


def bout_a_bout(troncons, final):
    """Chaque tronçon après le premier perd sa première image (la clé déjà montrée), son compris."""
    entrees, filtres = [], []
    for k, f in enumerate(troncons):
        entrees += ["-i", str(f)]
        coupe = "" if k == 0 else "trim=start_frame=1,setpts=PTS-STARTPTS,"
        filtres.append("[%d:v]%sformat=yuv420p[v%d];[%d:a]%sasetpts=PTS-STARTPTS[a%d]" % (
            k, coupe, k, k, "atrim=start=0.0417," if k else "", k))
    concat = "".join("[v%d][a%d]" % (k, k) for k in range(len(troncons))) + "concat=n=%d:v=1:a=1[v][a]" % len(troncons)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *entrees, "-filter_complex", ";".join(filtres) + ";" + concat,
                    "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-crf", "16", "-c:a", "aac", str(final)],
                   check=True)


if __name__ == "__main__":
    main(sys.argv[1], *(int(x) for x in sys.argv[2:4]))
