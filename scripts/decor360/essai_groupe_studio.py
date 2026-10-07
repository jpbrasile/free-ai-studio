"""Essai réel d'un groupe du tour 360° tel que le Studio le fait (tour360_chaine + tour360.invite_clip) sur la 4090,
AVANT la reconstruction de l'image comfy-maison : le nœud Motion-Context y est monté en lecture seule (comme
latent_chaine.local). Mêmes panorama et cartes que le tour v3 de l'atelier (06/10), pour comparer.

  python essai_groupe_studio.py <dossier essai (blender9)> <pano.png> <sortie> [groupe] [--sec]   (file dsh3, gpu)
  -> <sortie>/script.py, invite_<i>.txt, video.mp4 (les clips du groupe recollés), sortie.log
Les cartes de l'atelier ont leur azimut dans la pièce (cap du panorama + lacet de la plaque) : ramenées ici au cap
du panorama, celui des cartes du Studio.
"""
import json
import math
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sandbox-manager"))
import tour360  # noqa: E402
import tour360_chaine as chaine  # noqa: E402

POIDS = Path.home() / ".cache" / "free-ai-studio" / "poids"
NOEUD_MC = Path.home() / ".cache" / "free-ai-studio" / "h3_motion_context"      # clone au commit 5335715
CONSIGNE = {"piece": "the living room",
            "ambiance": "Quiet indoor room tone continues throughout, with birds singing faintly outside."}


def main(dossier, pano, sortie, groupe=0, sec=False):
    dossier, sortie = Path(dossier), Path(sortie).resolve()
    sortie.mkdir(parents=True, exist_ok=True)
    cam = json.loads((dossier / "scene.json").read_text(encoding="utf-8"))["cameras"][0]
    fiches = json.loads((dossier / "cartes" / "cartes_lieu.json").read_text(encoding="utf-8"))
    cartes = [{"nom": f["nom"], "description": f["description"], "a0": f["azimut"][0] - cam["lacet"],
               "a1": f["azimut"][1] - cam["lacet"]} for f in fiches]
    png = {f["nom"]: (dossier / "cartes" / f["image"]).read_bytes() for f in fiches}
    demi = math.degrees(math.atan(1344 / 2 / cam["f"]))
    clips = chaine.chemin(chaine.lire_camera(None))[groupe]
    faits = [tour360.invite_clip(CONSIGNE, cartes, c["a"], c["b"], demi, suite=i > 0, arret=c["arret"])
             for i, c in enumerate(clips)]
    for i, (texte, noms) in enumerate(faits, 1):
        (sortie / ("invite_%d.txt" % i)).write_text(texte, encoding="utf-8")
        print("clip", i, clips[i - 1], len(texte.split()), "mots", noms, flush=True)
    d = chaine.demande_groupe(clips, [t for t, _ in faits], [n for _, n in faits], png, Path(pano).read_bytes(),
                              cam["f"], 11, chaine.GROUPE_MAISON_S - 120)
    (sortie / "graphe.json").write_text(json.dumps(d["graphe"], indent=1), encoding="utf-8")
    (sortie / "script.py").write_text(chaine.construire_script(d), encoding="utf-8")
    print("PRET noeuds", len(d["graphe"]), "cartes", len(d["images"]), "vues", len(d["vues"]["caps"]), flush=True)
    if sec:
        return 0
    t = time.time()
    r = subprocess.run(["docker", "run", "--rm", "--gpus", "all", "--user", "0", "--name", "essai-groupe-studio",
                        "-e", "FREE_AI_OUTPUT_DIR=/sortie", "-v", f"{POIDS}:/poids:ro", "-v", f"{sortie}:/sortie",
                        "-v", f"{NOEUD_MC}:/comfy/custom_nodes/h3_motion_context:ro",
                        "--entrypoint", "sh", "free-ai-studio-comfy-maison", "-c",
                        "python /sortie/script.py; rc=$?; cp /tmp/comfy.log /sortie/comfy.log 2>/dev/null; exit $rc"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    (sortie / "sortie.log").write_text(r.stdout + "\n--- stderr ---\n" + r.stderr, encoding="utf-8")
    print("FAIT rc", r.returncode, round(time.time() - t, 1), "s", r.stdout[-300:], r.stderr[-1500:], flush=True)
    return r.returncode


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    a = [x for x in sys.argv[1:] if x != "--sec"]
    sys.exit(main(a[0], a[1], a[2], *(int(x) for x in a[3:4]), sec="--sec" in sys.argv))
