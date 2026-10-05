"""Géométrie de la plaque par MoGe-3 (Microsoft, MIT ; propriétaire, 05/10 : « go with MoGe-2 if you don't find better
on the web » : MoGe-3 sorti en 07/2026, même dépôt, mêmes sorties en mieux ; « pourquoi pas dans le Docker du
Studio » : il tourne dans un conteneur jetable de l'image ComfyUI locale, comme anyangle_local.py).

Une image -> nuage de points métrique par pixel (repère OpenCV de la caméra : x à droite, y vers le bas, z devant),
masque de validité, normales, intrinsèques. Sert à poser le plan au sol (plan_sol.py) au lieu de caler les boîtes à
l'œil. Lancer par la file (ressource gpu) ; ViT-L sur une image 1344x768 : 2,5 Go de VRAM, ~20 s.

  python moge_plaque.py <plaque.png> <sortie.npz> [--etapes N]      (N : passes du raffineur, 3 par défaut)

La sortie est écrite à côté de la plaque (même dossier). Poids dans le cache Hugging Face de l'hôte, paquets pip
dans ~/.cache/free-ai-studio/pip-moge : rien n'est retéléchargé d'une fois sur l'autre.
"""
import subprocess
import sys
import time
from pathlib import Path

MODELE = "Ruicheng/moge-3-vitl"
MOGE = "git+https://github.com/microsoft/MoGe.git@74fbce054ebed49800de42d0ad0e83495065719a"
IMAGE = "free-ai-studio-comfy-maison"
CACHE = Path.home() / ".cache"


def dans_le_conteneur(plaque, sortie, etapes):
    import numpy as np
    import torch
    from moge.model.v3 import MoGeModel
    from PIL import Image
    image = np.asarray(Image.open(plaque).convert("RGB"))
    h, w = image.shape[:2]
    modele = MoGeModel.from_pretrained(MODELE).to("cuda").eval()
    entree = torch.tensor(image / 255.0, dtype=torch.float32, device="cuda").permute(2, 0, 1)
    with torch.no_grad():
        try:
            out = modele.infer(entree, refine_steps=etapes)
        except TypeError:                       # nom du réglage différent selon la version : défaut du modèle
            out = modele.infer(entree)
    res = {k: v.float().cpu().numpy() for k, v in out.items() if torch.is_tensor(v)}
    k = res["intrinsics"]                       # normalisée (fraction de largeur / hauteur)
    fx, fy, cx, cy = k[0, 0] * w, k[1, 1] * h, k[0, 2] * w, k[1, 2] * h
    np.savez_compressed(sortie, **res, taille=np.array([w, h]))
    print("MOGE %s : fx %.1f fy %.1f cx %.1f cy %.1f px ; points valides %.1f %% ; VRAM max %.2f Go" % (
        MODELE, fx, fy, cx, cy, 100 * res["mask"].mean(), torch.cuda.max_memory_allocated() / 2**30), flush=True)


def main(plaque, sortie, etapes=3):
    plaque, sortie = Path(plaque).resolve(), Path(sortie).resolve()
    if plaque.parent != sortie.parent:
        raise SystemExit("la sortie va dans le dossier de la plaque")
    pip = CACHE / "free-ai-studio" / "pip-moge"
    pip.mkdir(parents=True, exist_ok=True)
    t = time.time()
    r = subprocess.run(["docker", "run", "--rm", "--gpus", "all", "--user", "0", "--name", "moge-plaque",
                        "-v", f"{Path(__file__).resolve().parent}:/code:ro", "-v", f"{plaque.parent}:/travail",
                        "-v", f"{CACHE / 'huggingface'}:/root/.cache/huggingface", "-v", f"{pip}:/root/.cache/pip",
                        "--entrypoint", "sh", IMAGE, "-c",
                        f"pip install -q '{MOGE}' && python /code/moge_plaque.py --dedans "
                        f"/travail/{plaque.name} /travail/{sortie.name} {etapes}"])
    print("FAIT", sortie.name, r.returncode, round(time.time() - t, 1), flush=True)
    sys.exit(r.returncode)


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[0] == "--dedans":
        dans_le_conteneur(a[1], a[2], int(a[3]))
    else:
        n = 3
        if "--etapes" in a:
            i = a.index("--etapes")
            n = int(a[i + 1])
            del a[i:i + 2]
        main(a[0], a[1], n)
