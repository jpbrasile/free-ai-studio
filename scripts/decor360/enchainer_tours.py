"""Les tours du Studio l'un après l'autre (07/10) : chaque tour est repris par la route du Studio et suivi jusqu'à
« fini » ; un tour arrêté parce qu'un travail a attendu la carte trop longtemps est repris (3 fois au plus), une
autre erreur arrête la chaîne et la dit. Un plan à valider arrête aussi la chaîne : il se regarde avant de partir.

  python enchainer_tours.py <fiche>:<tour> ...      (côté hôte ; journal sur la sortie)
"""
import json
import subprocess
import sys
import time

C = "free-ai-studio-sandbox-manager"
APPEL = r'''import json, os, sys, httpx
m, chemin = sys.argv[1], sys.argv[2]
r = httpx.request(m, "http://127.0.0.1:8000" + chemin,
                  headers={"Authorization": "Bearer " + os.environ["SANDBOX_MANAGER_KEY"]}, timeout=120)
print(json.dumps({"code": r.status_code, "corps": r.json() if r.headers.get("content-type", "").startswith(
    "application/json") else r.text[:400]}))
'''
REPRISES_MAX = 3


def studio(m, chemin):
    r = subprocess.run(["docker", "exec", C, "python", "/tmp/enchainer_appel.py", m, chemin],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"code": 0, "corps": r.stderr[-400:]}


def dernier(fid, tid):
    tours = studio("GET", "/video-h3/fiches/%s/tour360" % fid)
    t = tours.get("corps") if tours.get("code") == 200 else None
    return t if t and t.get("id") == tid else None


def suivre(fid, tid):
    reprises = 0
    t = dernier(fid, tid)
    if t and t["statut"] == "arrete":
        print("REPREND", fid, tid, studio("POST", "/video-h3/fiches/%s/tour360/%s/reprendre" % (fid, tid))["code"],
              flush=True)
    while True:
        time.sleep(30)
        t = dernier(fid, tid)
        if t is None:
            print("ILLISIBLE", fid, tid, flush=True)
            continue
        if t["statut"] == "fini":
            print("FINI", fid, tid, t.get("film_final"), time.strftime("%H:%M"), flush=True)
            return True
        if t["statut"] == "plan_a_valider":
            print("PLAN A VALIDER", fid, tid, time.strftime("%H:%M"), flush=True)
            return False
        if t["statut"] == "arrete":
            print("ARRETE", fid, tid, t.get("etape"), t.get("erreur"), time.strftime("%H:%M"), flush=True)
            if "n'a pas fini en" in (t.get("erreur") or "") and reprises < REPRISES_MAX:
                reprises += 1
                studio("POST", "/video-h3/fiches/%s/tour360/%s/reprendre" % (fid, tid))
                continue
            return False


def main(paires):
    open("enchainer_appel.py", "w", encoding="utf-8").write(APPEL)
    subprocess.run(["docker", "cp", "enchainer_appel.py", C + ":/tmp/enchainer_appel.py"], check=True)
    for p in paires:
        fid, tid = p.split(":")
        print("TOUR", fid, tid, time.strftime("%H:%M"), flush=True)
        if not suivre(fid, tid):
            print("CHAINE ARRETEE sur", fid, tid, flush=True)
            return 1
    print("TOUS FINIS", time.strftime("%H:%M"), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
