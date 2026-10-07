"""Une musique instrumentale du Studio pour une vidéo hors du Studio (propriétaire, 06/10 : « oui avec musique » pour
le tour 360° en 4K). Même chemin que le film automatique : /chanson/creer (YuE2 + LoRA instrumentale, chez Modal),
appelé depuis le conteneur du routeur avec sa clé (jamais affichée). Le son rendu est copié ici ; la pose sous la
vidéo (fondus) se fait ensuite par ffmpeg (`poser`).

  python musique_ici.py creer "<style>" <sortie.(mp3|wav)> [titre]
  python musique_ici.py poser <video.mp4> <musique> <sortie.mp4> [début dans la musique, s]
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

CONTENEUR = "free-ai-studio-sandbox-manager"
ATTENTE_MAX_S = 1800


def dedans(style, titre):
    import httpx
    url = os.getenv("STUDIO_SELF_URL", "http://127.0.0.1:8000")
    h = {"Authorization": "Bearer " + os.environ.get("SANDBOX_MANAGER_KEY", "")}
    with httpx.Client(timeout=120) as c:
        r = c.post(url + "/chanson/creer", headers=h,
                   json={"style": style, "lora": True, "duree": "1", "titre": titre,
                         # MUSIQUE_OU=ici : la carte d'ici (propriétaire, 06/10 : « music local too »)
                         "ou": os.getenv("MUSIQUE_OU", "modal")})
        if r.status_code != 200:
            print(json.dumps({"erreur": r.status_code, "detail": r.text[:800]}, ensure_ascii=False), flush=True)
            return 1
        jid, t = r.json()["id"], time.time()
        while True:
            job = c.get(url + "/jobs/" + jid, headers=h).json()
            if job.get("status") not in ("queued", "running") or time.time() - t > ATTENTE_MAX_S:
                break
            time.sleep(10)
    # le son est l'artefact « …chanson.flac » du travail (app.chanson_fichiers)
    sons = sorted(str(p) for racine in (Path("/workspace/jobs") / jid, Path("/workspace/artifacts"))
                  if racine.exists() for p in racine.rglob("*chanson.flac")
                  if racine.name == jid or jid in str(p))
    print(json.dumps({"jid": jid, "status": job.get("status"), "s": round(time.time() - t, 1),
                      "error": job.get("error"), "sons": [str(p) for p in sons]}, ensure_ascii=False), flush=True)
    return 0 if job.get("status") == "succeeded" and sons else 1


def creer(style, sortie, titre="Tour 360 (musique)"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    env = dict(os.environ, MSYS_NO_PATHCONV="1")
    subprocess.run(["docker", "cp", str(Path(__file__).resolve()), CONTENEUR + ":/tmp/musique_ici.py"], check=True,
                   env=env)
    r = subprocess.run(["docker", "exec", "-e", "MUSIQUE_OU=" + os.getenv("MUSIQUE_OU", "modal"), CONTENEUR,
                        "python", "/tmp/musique_ici.py", "--dedans", style, titre],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    print(r.stdout[-3000:], r.stderr[-2000:], flush=True)
    lignes = [x for x in r.stdout.splitlines() if x.startswith("{")]
    d = json.loads(lignes[-1]) if lignes else {}
    if r.returncode or not d.get("sons"):
        print("ECHEC", flush=True)
        return 1
    son = next((s for s in d["sons"] if s.endswith(Path(sortie).suffix)), d["sons"][0])
    subprocess.run(["docker", "cp", CONTENEUR + ":" + son, str(Path(sortie).with_suffix(Path(son).suffix))],
                   check=True, env=env)
    print("FAIT", Path(sortie).with_suffix(Path(son).suffix), flush=True)
    return 0


def poser(video, musique, sortie, debut=0.0, fondu=1.5):
    duree = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                  video], capture_output=True, text=True).stdout.strip())
    filtre = "afade=t=in:st=0:d=%.2f,afade=t=out:st=%.3f:d=%.2f" % (fondu, duree - 2 * fondu, 2 * fondu)
    return subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", video, "-ss", str(debut), "-i", musique,
                           "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-af", filtre, "-c:a", "aac", "-b:a", "192k",
                           "-t", "%.3f" % duree, sortie]).returncode


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[0] == "--dedans":
        sys.exit(dedans(a[1], a[2]))
    if a[0] == "creer":
        sys.exit(creer(*a[1:4]))
    sys.exit(poser(a[1], a[2], a[3], *(float(x) for x in a[4:5])))
