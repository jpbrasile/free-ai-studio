"""Essai réel du script du Studio (sandbox-manager/fluide.py) sur la 4090, AVANT la reconstruction de l'image
comfy-maison : le nœud GIMM-VFI y est monté en lecture seule et ses dépendances installées au lancement (aux
versions épinglées dans comfy-maison/Dockerfile). Le script envoyé est exactement celui que le Studio enverra.

  python essai_fluide.py <film.mp4> <sortie.mp4> [chemin.mp4]        (par la file dsh3, gpu)
"""
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sandbox-manager"))
import fluide  # noqa: E402

NOEUD = Path.home() / ".cache" / "free-ai-studio" / "noeuds" / "ComfyUI-GIMM-VFI"
POIDS = Path.home() / ".cache" / "free-ai-studio" / "poids"
DEPS = "cupy-cuda13x[ctk]==14.2.0 timm==1.0.30 omegaconf==2.3.1 yacs==0.1.8 easydict==1.13"


def main(film, sortie, chemin=None):
    sortie = Path(sortie).resolve()
    travail = sortie.parent / (sortie.stem + "_travail")
    travail.mkdir(parents=True, exist_ok=True)
    (travail / "script.py").write_text(fluide.construire_script(Path(film).read_bytes(),
                                                                Path(chemin).read_bytes() if chemin else b""),
                                       encoding="utf-8")
    t = time.time()
    r = subprocess.run(["docker", "run", "--rm", "--gpus", "all", "--user", "0", "--name", "essai-fluide",
                        "-e", "FREE_AI_OUTPUT_DIR=/sortie/out", "-v", f"{POIDS}:/poids:ro",
                        "-v", f"{NOEUD}:{fluide.NOEUD}:ro", "-v", f"{travail}:/sortie",
                        "-v", f"{POIDS / 'gimm-vfi'}:/comfy/models/interpolation/gimm-vfi:ro",
                        "--entrypoint", "sh", "free-ai-studio-comfy-maison", "-c",
                        f"pip install -q {DEPS} && python /sortie/script.py"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    (travail / "sortie.log").write_text(r.stdout + "\n--- stderr ---\n" + r.stderr, encoding="utf-8")
    lignes = [x for x in r.stdout.splitlines() if x.startswith("FLUIDE ")]
    print("rc", r.returncode, round(time.time() - t, 1), "s", flush=True)
    if r.returncode or not lignes:
        print("ECHEC", fluide.phrase_d_echec(r.stderr), r.stderr[-1500:], flush=True)
        return 1
    (travail / "out" / "video.mp4").replace(sortie)
    print("FAIT", sortie, json.loads(lignes[-1][7:]), flush=True)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main(*sys.argv[1:4]))
