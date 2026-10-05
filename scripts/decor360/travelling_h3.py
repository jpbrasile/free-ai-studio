"""Clip H3 d'un mouvement de caméra dans un décor : première image = la photo, dernière = la vue rendue par
anyangle_local.py (propriétaire, 05/10 : « fais le clip H3 du travelling »).

La demande est fabriquée par video_h3.preparer, comme depuis la page (mode « Première et dernière image »,
invite, graphe Turbo 4 étapes) ; le script du Studio tourne dans un conteneur jetable de l'image ComfyUI locale.
Lancer par la file (ressource gpu).

  python travelling_h3.py <premiere.png> <derniere.png> <sortie.mp4> [graine] [longueur] [--consigne c.json]
c.json (facultatif) remplace tout ou partie de CONSIGNE : {"mouvement", "premiere", "derniere", "ambiance",
"camera": {"mouvement": clé de video_h3.CAMERA_MOUVEMENTS, "vitesse": ...}} ; sans lui, le travelling avant du salon.
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
CONSIGNE = {
    "mouvement": ("A slow, smooth dolly-in through an empty, quiet living room in soft afternoon daylight: the camera "
                  "glides forward about one and a half metres and turns slightly to the right, past the cream sofa "
                  "and the wooden coffee table, towards the doorway to the hallway. The room stays still; only the "
                  "garden leaves move gently behind the glass wall."),
    "premiere": ("a bright living room with a floor-to-ceiling glass wall on the left opening onto a garden, a cream "
                 "sofa and a wooden coffee table, a bookshelf and a doorway to the hallway at the back."),
    "derniere": "the same living room seen from closer, the cream sofa in the foreground, the hallway doorway on the right.",
    "ambiance": "Quiet room tone, birds faintly outside in the garden.",
    "camera": {"mouvement": "avance", "vitesse": "lente"},
}


def clip(premiere, derniere, sortie, graine=11, longueur=124, consigne=None):
    """Un clip H3 de premiere.png à derniere.png ; rend (code de retour, durée en s)."""
    c = dict(CONSIGNE, **(consigne or {}))
    b64 = lambda p: base64.b64encode(Path(p).read_bytes()).decode()  # noqa: E731
    prep = video_h3.preparer({"mode": "premiere_derniere", "image_paroles": c["mouvement"], "ambiance": c["ambiance"],
                              "description_premiere": c["premiere"], "description_derniere": c["derniere"],
                              "images": [b64(premiere), b64(derniere)], "definition": "768p",
                              "longueur": longueur, "graine": graine, "camera": c["camera"]})
    d = prep["demande"]
    d["delai_s"] = 1800                       # la 4090 déleste en 768p : plus lente que l'A100
    sortie = Path(sortie).resolve()
    travail = sortie.parent / ("travail_" + sortie.stem)
    travail.mkdir(parents=True, exist_ok=True)
    (travail / "invite.txt").write_text(prep["resume_public"]["invite"], encoding="utf-8")
    (travail / "script.py").write_text(video_h3.construire_script(d), encoding="utf-8")
    t = time.time()
    r = subprocess.run(["docker", "run", "--rm", "--gpus", "all", "--user", "0", "--name", "travelling-h3",
                        "-e", "FREE_AI_OUTPUT_DIR=/sortie", "-v", f"{POIDS}:/poids:ro", "-v", f"{travail}:/sortie",
                        "--entrypoint", "sh", "free-ai-studio-comfy-maison", "-c",
                        "python /sortie/script.py; rc=$?; cp /tmp/comfy.log /sortie/comfy.log 2>/dev/null; exit $rc"],
                       capture_output=True, text=True)
    (travail / "sortie.log").write_text(r.stdout + "\n--- stderr ---\n" + r.stderr, encoding="utf-8")
    if r.returncode == 0 and (travail / "video.mp4").is_file():
        (travail / "video.mp4").replace(sortie)
    duree = round(time.time() - t, 1)
    print("FAIT", sortie.name, r.returncode, duree, json.dumps(prep["resume_public"]["taille"]), flush=True)
    return r.returncode, duree


if __name__ == "__main__":
    a = sys.argv[1:]
    consigne = None
    if "--consigne" in a:
        i = a.index("--consigne")
        consigne = json.loads(Path(a[i + 1]).read_text(encoding="utf-8"))
        del a[i:i + 2]
    sys.exit(clip(*a[:3], *(int(x) for x in a[3:5]), consigne=consigne)[0])
