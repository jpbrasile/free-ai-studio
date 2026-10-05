"""Tour complet sur place en H3 (propriétaire, 05/10 : « do a 360° clip »).

Une rotation depuis le point de la photo est exacte : chaque vue vient de la plaque et du panorama sans erreur de
parallaxe. H3 ne prend qu'une première et une dernière image : le tour est coupé en tronçons de PAS degrés (8 x 45°,
assez de recouvrement entre deux vues voisines à fx 756), chacun un clip H3 « panoramique vers la droite » d'une
image clé à la suivante, puis les tronçons sont mis bout à bout (la première image d'un tronçon = la dernière du
précédent : retirée). Images clés : la plaque à 0° et 360°, les rendus `rendus/rendu_r<angle>.png` de scene_blender.py
entre les deux (cibles {"devant": 0, "droite": 0, "tourne": angle} du plan, scene_plan.py).

  python tour360_h3.py <dossier de l'essai> [graine] [pas]      (lancer par la file : ressource gpu, ~3 min/tronçon)
  -> <dossier>/tour360/tour360_g<graine>.mp4 (+ un mp4 par tronçon)
"""
import subprocess
import sys
from pathlib import Path

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


def main(dossier, graine=11, pas=PAS):
    dossier = Path(dossier).resolve()
    sortie = dossier / "tour360"
    sortie.mkdir(exist_ok=True)
    cles = [dossier / "plaque.png"] + [dossier / "rendus" / ("rendu_r%03d.png" % a) for a in range(pas, 360, pas)] \
        + [dossier / "plaque.png"]
    manque = [str(c) for c in cles if not c.is_file()]
    if manque:
        raise SystemExit("images clés absentes : " + ", ".join(manque))
    troncons = []
    for k in range(len(cles) - 1):
        f = sortie / ("troncon_%02d_g%d.mp4" % (k, graine))
        if not f.is_file():
            rc, _ = travelling_h3.clip(cles[k], cles[k + 1], f, graine, consigne=CONSIGNE)
            if rc:
                raise SystemExit("tronçon %d en échec (rc %d)" % (k, rc))
        troncons.append(f)
    # bout à bout : chaque tronçon après le premier perd sa première image (la clé déjà montrée)
    entrees, filtres = [], []
    for k, f in enumerate(troncons):
        entrees += ["-i", str(f)]
        coupe = "" if k == 0 else "trim=start_frame=1,setpts=PTS-STARTPTS,"
        filtres.append("[%d:v]%sformat=yuv420p[v%d];[%d:a]%sasetpts=PTS-STARTPTS[a%d]" % (
            k, coupe, k, k, "atrim=start=0.0417," if k else "", k))
    concat = "".join("[v%d][a%d]" % (k, k) for k in range(len(troncons))) + "concat=n=%d:v=1:a=1[v][a]" % len(troncons)
    final = sortie / ("tour360_g%d.mp4" % graine)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *entrees, "-filter_complex", ";".join(filtres) + ";" + concat,
                    "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-crf", "16", "-c:a", "aac", str(final)],
                   check=True)
    print("FAIT", final, len(troncons), "tronçons", flush=True)


if __name__ == "__main__":
    main(sys.argv[1], *(int(x) for x in sys.argv[2:4]))
