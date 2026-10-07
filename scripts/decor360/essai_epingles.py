"""Essai : un tronçon du tour 360° en mode Références (Ref2VA), première ET dernière image épinglées par
MiniMaxH3AddGuide (frame_idx 0 et -1), les cartes des éléments croisés en <Subject N> (propriétaire, 06/10 :
« h3 syntax … rely on id instead », « we also use latent trick », « go ahead, run the test »).

Le nœud, lu dans ComfyUI v0.37.0 (comfy_extras/nodes_minimax_h3.py) : « Anchor an image … at any frame … Chain
several nodes to anchor several frames » ; frame_idx négatif = compté depuis la fin.

  python essai_epingles.py <dossier_essai> <invite.txt> <sortie.mp4> <premiere.png> <derniere.png> <sujet.png>...
       [--graine 11] [--longueur 124] [--sec]     (--sec : écrit la demande et le script sans lancer)
"""
import base64
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sandbox-manager"))
import video_h3  # noqa: E402

POIDS = Path.home() / ".cache" / "free-ai-studio" / "poids"


def demande(invite, images, graine, longueur):
    b64 = [base64.b64encode(Path(p).read_bytes()).decode() for p in images]
    prep = video_h3.preparer({"mode": "references", "images": b64, "image_paroles": "placeholder",
                              "definition": "768p", "longueur": longueur, "graine": graine})
    d = prep["demande"]
    g = d["graphe"]
    g["10"]["inputs"]["prompt"] = invite
    # première image en 60 -> image 0 ; dernière en 61 -> dernière image du clip
    g["11"] = {"class_type": "MiniMaxH3AddGuide", "inputs": {"positive": ["10", 0], "vae": ["4", 0], "latent": ["10", 1],
                                                              "image": ["60", 0], "frame_idx": 0}}
    g["19"] = {"class_type": "MiniMaxH3AddGuide", "inputs": {"positive": ["11", 0], "vae": ["4", 0], "latent": ["10", 1],
                                                              "image": ["61", 0], "frame_idx": -1}}
    g["13"]["inputs"]["conditioning"] = ["19", 0]
    d["classes"] = list(d["classes"]) + ["MiniMaxH3AddGuide"]
    d["delai_s"] = 1800
    return d, prep


def main(a):
    sec = "--sec" in a
    a = [x for x in a if x != "--sec"]
    opts = {"--graine": 11, "--longueur": 124}
    for k in list(opts):
        if k in a:
            i = a.index(k)
            opts[k] = int(a[i + 1])
            del a[i:i + 2]
    _, invite, sortie, images = Path(a[0]), Path(a[1]).read_text(encoding="utf-8"), Path(a[2]).resolve(), a[3:]
    d, prep = demande(invite, images, opts["--graine"], opts["--longueur"])
    return lancer(d, invite, sortie, sec)


def lancer(d, invite, sortie, sec=False):
    """La demande `d` (graphe déjà retouché au besoin) dans le ComfyUI de la 4090 ; rend le code de retour."""
    sortie = Path(sortie).resolve()
    travail = sortie.parent / ("travail_" + sortie.stem)
    travail.mkdir(parents=True, exist_ok=True)
    (travail / "invite.txt").write_text(invite, encoding="utf-8")
    (travail / "graphe.json").write_text(json.dumps(d["graphe"], indent=1), encoding="utf-8")
    (travail / "script.py").write_text(video_h3.construire_script(d), encoding="utf-8")
    print("images", [k for k in d if "image" in k.lower()], "noeuds", sorted(d["graphe"]), flush=True)
    if sec:
        return 0
    t = time.time()
    r = subprocess.run(["docker", "run", "--rm", "--gpus", "all", "--user", "0", "--name", "essai-epingles",
                        "-e", "FREE_AI_OUTPUT_DIR=/sortie", "-v", f"{POIDS}:/poids:ro", "-v", f"{travail}:/sortie",
                        "--entrypoint", "sh", "free-ai-studio-comfy-maison", "-c",
                        "python /sortie/script.py; rc=$?; cp /tmp/comfy.log /sortie/comfy.log 2>/dev/null; exit $rc"],
                       capture_output=True, text=True)
    (travail / "sortie.log").write_text(r.stdout + "\n--- stderr ---\n" + r.stderr, encoding="utf-8")
    if r.returncode == 0 and (travail / "video.mp4").is_file():
        (travail / "video.mp4").replace(sortie)
    print("FAIT", sortie.name, r.returncode, round(time.time() - t, 1), flush=True)
    return r.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
