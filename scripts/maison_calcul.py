"""Un calcul lourd du Studio sur la carte de ce PC, sans urgence (demande du proprietaire, 01/10/2026).

Lance par la file d'attente de la machine (dsh3/harness-3r/file_attente.py, ressource gpu), jamais en direct :

    python scripts/maison_calcul.py SCRIPT.py DOSSIER_SORTIE [--image free-ai-studio-comfy-maison]

1. attend que llama-server :8005 soit au repos (fonctions du lanceur dsh3, importees sans le modifier) et
   garde les places de verrou_gpu pendant tout le calcul : aucun pilote dsh3 ne part en meme temps ;
2. arrete llama-server s'il tourne (option 1 du proprietaire : seulement au repos, rien d'autre n'est touche) ;
3. execute SCRIPT.py dans l'image ComfyUI de ce PC, poids montes en lecture seule a /poids, comme sur Modal ;
4. releve le pic de VRAM (nvidia-smi) et de RAM du conteneur (docker stats), toutes les 2 s ;
5. rend les places et relance llama-server avec le profil qu'il avait, QUOI QU'IL ARRIVE ;
6. ecrit DOSSIER_SORTIE/resultat.json.
"""
import json
import os
import subprocess
import sys
import threading
import time

SERVEUR_DIR = os.environ.get("DSH3_SERVEUR_DIR", "C:/Users/test/Documents/dsh3/harness-3r/serveur")
POIDS = os.environ.get("STUDIO_POIDS_MAISON", "C:/Users/test/.cache/free-ai-studio/poids")
ATTENTE_MAX_S = int(os.environ.get("MAISON_ATTENTE_MAX_S", "21600"))

sys.path.insert(0, SERVEUR_DIR)
import serveur  # noqa: E402


def _mio(texte):
    """« 41.2GiB / 47GiB » -> 42189 (la partie avant le slash)."""
    v = texte.split("/")[0].strip()
    for suffixe, f in (("GiB", 1024), ("MiB", 1), ("KiB", 1 / 1024), ("GB", 1000 ** 3 / 2 ** 20),
                       ("MB", 1000 ** 2 / 2 ** 20), ("kB", 1000 / 2 ** 20), ("B", 1 / 2 ** 20)):
        if v.endswith(suffixe):
            return int(float(v[: -len(suffixe)]) * f)
    return None


class Releve(threading.Thread):
    def __init__(self, conteneur):
        super().__init__(daemon=True)
        self.conteneur, self.fin = conteneur, threading.Event()
        self.vram_max = self.ram_max = None
        self.vram_base = (serveur.vram() or {}).get("utilise_mio")

    def run(self):
        while not self.fin.is_set():
            v = serveur.vram()
            if v:
                self.vram_max = max(self.vram_max or 0, v["utilise_mio"])
            r = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", self.conteneur],
                               capture_output=True, text=True)
            m = _mio(r.stdout) if r.returncode == 0 and r.stdout.strip() else None
            if m is not None:
                self.ram_max = max(self.ram_max or 0, m)
            self.fin.wait(2)


def attendre_repos(url, port):
    t0, dit = time.time(), 0.0
    while True:
        raisons, fds = serveur.au_repos(url, port)
        if not raisons:
            return fds, time.time() - t0
        if time.time() - t0 >= ATTENTE_MAX_S:
            raise TimeoutError("pas au repos apres %d s : %s" % (time.time() - t0, "; ".join(raisons)))
        if time.time() - dit >= 300:
            print("attente du repos (%d s) : %s" % (time.time() - t0, "; ".join(raisons)), flush=True)
            dit = time.time()
        time.sleep(30)


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    script, sortie = os.path.abspath(argv[0]), os.path.abspath(argv[1])
    image = argv[argv.index("--image") + 1] if "--image" in argv else "free-ai-studio-comfy-maison"
    os.makedirs(sortie, exist_ok=True)
    p = serveur.charger()
    url, port = "http://%s:%d" % (p["_hote"], p["_port"]), p["_port"]
    try:
        profil = json.load(open(serveur.ETAT, encoding="utf-8")).get("profil") or p["_repli"]
    except OSError:
        profil = p["_repli"]
    res = {"script": script, "image": image, "debut": serveur.maintenant(), "profil_llama": profil}
    fds, arrete, rc = None, False, None
    try:
        fds, res["attente_repos_s"] = attendre_repos(url, port)
        if serveur.ecouteurs(port):
            ok, texte, _ = serveur.arreter(port, url)
            res["arret_llama"] = texte
            if not ok:
                raise RuntimeError(texte)
            arrete = True
        res["vram_avant_mio"] = serveur.vram()
        conteneur = "studio-maison-%d" % os.getpid()
        cmd = ["docker", "run", "--rm", "--name", conteneur, "--gpus", "all",
               "-v", "%s:/poids:ro" % POIDS, "-v", "%s:/out" % sortie, "-v", "%s:/s.py:ro" % script,
               "-v", "%s:/tmp" % os.path.join(sortie, "tmp"),  # garde comfy.log : dechargements, temps par etape
               "-e", "FREE_AI_OUTPUT_DIR=/out", image, "python", "/s.py"]
        rel = Releve(conteneur)
        rel.start()
        t0 = time.time()
        with open(os.path.join(sortie, "calcul.log"), "w", encoding="utf-8") as log:
            rc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT).returncode
        res["duree_s"] = round(time.time() - t0, 1)
        rel.fin.set()
        rel.join(10)
        res.update(rc=rc, vram_base_mio=rel.vram_base, vram_pic_mio=rel.vram_max, ram_pic_conteneur_mio=rel.ram_max)
    except Exception as e:  # noqa: BLE001 -- l'echec est ecrit, puis llama est relance
        res["erreur"] = "%s: %s" % (type(e).__name__, e)
    finally:
        serveur.rendre_places(fds)
        if arrete:
            r = subprocess.run([sys.executable, os.path.join(SERVEUR_DIR, "serveur.py"), "lancer", profil],
                               capture_output=True, text=True)
            res["relance_llama"] = {"rc": r.returncode, "fin": (r.stdout + r.stderr)[-600:]}
        res["fin"] = serveur.maintenant()
        res["fichiers"] = sorted(os.listdir(sortie))
        json.dump(res, open(os.path.join(sortie, "resultat.json"), "w", encoding="utf-8"), indent=1,
                  ensure_ascii=False)
        print(json.dumps(res, ensure_ascii=False, indent=1))
    return 0 if rc == 0 and "erreur" not in res else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
