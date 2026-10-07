"""Un clip passé en 4K sur la carte d'ici, hors du Studio, par le même chemin que la finalisation « Où : ici »
(agrandir.construire_script_maison : FlashVSR v1.1, morceaux de 32 images, envoyé à la machine comfy du Studio).
Propriétaire, 06/10 : « lance A sur 2 s maintenant » (A = 4K d'abord, puis GIMM-VFI à pas réguliers).

Le module app n'est pas importé dans le conteneur vivant (mémoire « jamais import app ») : seuls agrandir et
video_h3, puis un POST à la machine comfy comme maison_execute.

  python agrandir_ici.py <entree.mp4> <sortie.mp4>        (par la file dsh3, gpu)
"""
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

CONTENEUR = "free-ai-studio-sandbox-manager"


def dedans(entree):
    sys.path.insert(0, "/app")
    import httpx
    import agrandir
    import video_h3
    l, h = (int(x) for x in subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
         "-of", "csv=p=0", entree], capture_output=True, text=True).stdout.strip().split(","))
    n = int(subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                            "stream=nb_read_frames", "-of", "csv=p=0", entree],
                           capture_output=True, text=True).stdout.strip())
    coupes = agrandir.bornes(n, [n], agrandir.MORCEAU_MAX_MAISON)
    code = agrandir.construire_script_maison(Path(entree).read_bytes(), coupes, [n], l, h,
                                             delai_s=video_h3.MAISON_DUREE_MAX_S)
    jid = "agrandir-ici-" + uuid.uuid4().hex[:12]
    t = time.time()
    r = httpx.post(os.environ["SANDBOX_WORKER_COMFY_URL"].rstrip("/") + "/run",
                   headers={"Authorization": "Bearer " + os.environ.get("SANDBOX_WORKER_KEY", "")},
                   json={"job_id": jid, "code": code, "secondes": video_h3.MAISON_DUREE_MAX_S},
                   timeout=video_h3.MAISON_DUREE_MAX_S + 60)
    d = r.json()
    sortie = Path("/workspace/jobs") / jid / "output"
    films = sorted(p for p in sortie.rglob("*.mp4")) if sortie.exists() else []
    print(json.dumps({"jid": jid, "http": r.status_code, "rc": d.get("returncode", d.get("rc")),
                      "s": round(time.time() - t, 1), "images": n, "coupes": coupes,
                      "films": [str(p) for p in films], "stderr": str(d.get("stderr", ""))[-1500:],
                      "stdout": str(d.get("stdout", ""))[-1500:]}, ensure_ascii=False), flush=True)
    return 0 if films else 1


def lancer(entree, sortie):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    entree, sortie = Path(entree).resolve(), Path(sortie).resolve()
    env = dict(os.environ, MSYS_NO_PATHCONV="1")
    subprocess.run(["docker", "exec", CONTENEUR, "mkdir", "-p", "/tmp/agrandir_ici"], check=True, env=env)
    for src, dst in ((entree, "/tmp/agrandir_ici/entree.mp4"), (Path(__file__), "/tmp/agrandir_ici/a.py")):
        subprocess.run(["docker", "cp", str(src), CONTENEUR + ":" + dst], check=True, env=env)
    r = subprocess.run(["docker", "exec", CONTENEUR, "python", "/tmp/agrandir_ici/a.py", "--dedans",
                        "/tmp/agrandir_ici/entree.mp4"], capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    print(r.stdout[-4000:], r.stderr[-2000:], flush=True)
    lignes = [x for x in r.stdout.splitlines() if x.startswith("{")]
    if r.returncode or not lignes:
        print("ECHEC rc", r.returncode, flush=True)
        return 1
    film = json.loads(lignes[-1])["films"][-1]
    subprocess.run(["docker", "cp", CONTENEUR + ":" + film, str(sortie)], check=True, env=env)
    print("FAIT", sortie, flush=True)
    return 0


if __name__ == "__main__":
    a = sys.argv[1:]
    sys.exit(dedans(a[1]) if a[0] == "--dedans" else lancer(a[0], a[1]))
