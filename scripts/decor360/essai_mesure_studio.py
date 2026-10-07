"""Essai réel de l'étape 1 du tour 360° tel que le Studio la fait (tour360.construire_mesure, chemin « ici ») sur la
4090, AVANT la reconstruction de l'image comfy-maison : MoGe est installé dans le conteneur jetable (cache pip
~/.cache/free-ai-studio/pip-moge, comme moge_plaque.py), les poids lus dans /poids comme le fera le Studio.

  python essai_mesure_studio.py <photo.png> <sortie>        (file dsh3, gpu)
  -> <sortie>/script.py, geometrie.json, grille.json, sortie.log
"""
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sandbox-manager"))
import tour360  # noqa: E402

POIDS = Path.home() / ".cache" / "free-ai-studio" / "poids"
PIP = Path.home() / ".cache" / "free-ai-studio" / "pip-moge"
MOGE = "git+https://github.com/microsoft/MoGe.git@74fbce054ebed49800de42d0ad0e83495065719a"


def main(photo, sortie):
    sortie = Path(sortie).resolve()
    sortie.mkdir(parents=True, exist_ok=True)
    (sortie / "script.py").write_text(tour360.construire_mesure(Path(photo).read_bytes(), maison=True),
                                      encoding="utf-8")
    t = time.time()
    r = subprocess.run(["docker", "run", "--rm", "--gpus", "all", "--user", "0", "--name", "essai-mesure-studio",
                        "-e", "FREE_AI_OUTPUT_DIR=/sortie", "-v", f"{POIDS}:/poids:ro", "-v", f"{sortie}:/sortie",
                        "-v", f"{PIP}:/root/.cache/pip", "--entrypoint", "sh", "free-ai-studio-comfy-maison", "-c",
                        f"pip install -q '{MOGE}' && python /sortie/script.py"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    (sortie / "sortie.log").write_text(r.stdout + "\n--- stderr ---\n" + r.stderr, encoding="utf-8")
    print("FAIT rc", r.returncode, round(time.time() - t, 1), "s", r.stdout[-600:], r.stderr[-1500:], flush=True)
    return r.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
