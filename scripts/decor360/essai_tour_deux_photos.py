"""Le tour vidéo 360° d'un lieu peint depuis ses deux photos (essai_pano_deux_photos.py), seul de bout en bout
(propriétaire, 06/10 : « you are alone tonight with priority access to the gpu, can you go through the whole video
plan alone »). Prépare le dossier d'essai que lisent tour360_latent.py / latent_chaine.py — clés tirées du SEUL
panorama (vues_pano, fx 904, comme les vues exactes épinglées), cartes d'identité = cartes du plan (azimuts
calculés, découpées par la machine du panorama), puis lance le tour 30 s (--pas 60 --par-groupe 3, --pano).

  python essai_tour_deux_photos.py <sortie gemini> <cas> [graine]     (par la file : gpu)
  -> <cas>/essai/{plaque.png, rendus/, scene.json, cartes/}, <cas>/essai/tour360_latent/tour360_latent_g<graine>.mp4
"""
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sandbox-manager"))
import plan_piece  # noqa: E402
import tour360_latent  # noqa: E402
import vues_pano  # noqa: E402

PAS, PAR_GROUPE = 60, 3


def preparer(d):
    essai = d / "essai"
    pano = d / "pano" / "pano.png"
    vues_pano.main(pano, d / "pano" / "cle_000.png", essai, 0.0, PAS)
    lu = json.loads((d / "claude" / "plan.json").read_text(encoding="utf-8"))
    geo = json.loads((d / "pano" / "geometrie.json").read_text(encoding="utf-8"))   # le repère du panorama peint
    (essai / "cartes").mkdir(parents=True, exist_ok=True)
    fiches = []
    for c in plan_piece.cartes_du_plan(lu["plan"], geo):
        src = d / "pano" / ("carte_%s.png" % c["nom"])
        if not src.is_file():
            print("carte absente", c["nom"], flush=True)
            continue
        shutil.copyfile(src, essai / "cartes" / (c["nom"] + ".png"))
        fiches.append({"nom": c["nom"], "description": c["description"], "azimut": [c["a0"], c["a1"]],
                       "image": c["nom"] + ".png"})
    (essai / "cartes" / "cartes_lieu.json").write_text(json.dumps(fiches, indent=1, ensure_ascii=False),
                                                      encoding="utf-8")
    print("ESSAI", essai, len(fiches), "cartes", flush=True)
    return essai, pano


def main(sortie, nom, graine=11):
    d = sortie / nom
    essai, pano = preparer(d)
    tour360_latent.main(essai, graine, pano=str(pano), pas=PAS, par_groupe=PAR_GROUPE)


if __name__ == "__main__":
    if sys.argv[1] == "--preparer":          # le dossier d'essai seul, sans GPU (contrôle)
        preparer(Path(sys.argv[2]).resolve() / sys.argv[3])
    else:
        main(Path(sys.argv[1]).resolve(), sys.argv[2], *(int(x) for x in sys.argv[3:4]))
