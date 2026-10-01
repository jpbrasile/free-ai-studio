"""Pont entre la file de la carte du Studio et la file d'attente de CE PC (dsh3, file_attente.py).

FACULTATIF, ÉTEINT PAR DÉFAUT, ABSENT CHEZ LE CLIENT (point 3 de la « mise en ordre » du 01/10/2026).
Le Studio n'en a pas besoin : sa file (`sandbox-manager/file_carte.py`) part dès que la carte est libre.
Sur ce PC, elle ne l'est jamais : llama-server tient 15,4 Go. Le pont la libère, au repos seulement.

    python scripts/pont_carte.py veiller     lancé par l'opérateur, tourne tant qu'on le laisse :
                                             le Studio attend la carte -> un travail « liberer » dans la file dsh3
    python scripts/pont_carte.py liberer     lancé PAR la file dsh3 (ressource gpu), jamais à la main :
                                             attend le repos, arrête llama, tient les places de verrou_gpu tant que
                                             le Studio a du travail pour la carte, puis relance llama
    python scripts/pont_carte.py garde ...   lancé détaché par `liberer` et par `maison_calcul.py`

Le défaut 0xC000013A (01/10, deux fois sur cinq) : le lanceur hôte est mort sans exécuter son `finally`, et
llama-server est resté arrêté. La relance ne dépend plus de sa survie : avant d'arrêter llama, il lance une GARDE
détachée (sans console, hors de son groupe et, si Windows le permet, hors de son Job Object). Quand le lanceur
disparaît, la garde attend que la carte soit rendue (le conteneur parti, ou le Studio sans travail), puis relance
llama s'il n'écoute pas. Si le lanceur a fini proprement, llama écoute déjà et la garde sort sans rien faire.

Rien n'est jamais tué : on attend le repos de llama (aucun slot au travail, aucun julia, aucune place tenue), et le
travail du Studio, lui, n'est pas un descendant de ce script.
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

ICI = os.path.dirname(os.path.abspath(__file__))
RACINE = os.path.dirname(ICI)
STUDIO = os.environ.get("FREE_AI_SANDBOX_URL", "http://127.0.0.1:8020").rstrip("/")
SERVEUR_DIR = os.environ.get("DSH3_SERVEUR_DIR", "C:/Users/test/Documents/dsh3/harness-3r/serveur")
FILE_DSH3 = os.environ.get("DSH3_FILE_ATTENTE", "C:/Users/test/Documents/dsh3/harness-3r/file_attente.py")
FILE_ETAT = os.environ.get("H3R_FILE", "C:/Users/test/h3r_runs/_file")
JOURNAL = os.environ.get("PONT_JOURNAL", os.path.expanduser("~/h3r_runs/studio_pont/pont.jsonl"))
NOM = "studio-pont-carte"
# « Sans urgence » : la file dsh3 passe d'abord ce qui est plus haut. `operateur` pour un essai suivi à l'écran.
PRIORITE = os.environ.get("PONT_PRIORITE", "normale")
SONDE_S = float(os.environ.get("PONT_SONDE_S", "20"))
# Entre deux plans d'un scénario, la file du Studio est vide quelques secondes (traduction, montage) :
# on ne rend pas la carte à llama pour la reprendre aussitôt.
GRACE_S = float(os.environ.get("PONT_GRACE_S", "180"))
TENIR_MAX_S = float(os.environ.get("PONT_TENIR_MAX_S", str(6 * 3600)))

DETACHE = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
HORS_JOB = 0x01000000              # CREATE_BREAKAWAY_FROM_JOB


def journal(**ligne):
    ligne = dict(t=time.strftime("%Y-%m-%dT%H:%M:%S"), **ligne)
    os.makedirs(os.path.dirname(JOURNAL), exist_ok=True)
    with open(JOURNAL, "a", encoding="utf-8") as f:
        f.write(json.dumps(ligne, ensure_ascii=False) + "\n")
    print(json.dumps(ligne, ensure_ascii=False), flush=True)


def _cle():
    """La clé du Studio, lue dans .env et jamais affichée."""
    try:
        with open(os.path.join(RACINE, ".env"), encoding="utf-8", errors="replace") as f:
            for l in f:
                if l.startswith("SANDBOX_MANAGER_KEY="):
                    return l.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return ""


def studio_file():
    """Travaux du Studio pour la carte (en attente + en cours) ; None si le Studio ne répond pas."""
    req = urllib.request.Request(STUDIO + "/video-h3/ou", headers={"Authorization": "Bearer " + _cle()})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return int(json.loads(r.read())["ici"].get("file") or 0)
    except (OSError, ValueError, KeyError, TypeError, urllib.error.URLError):
        return None


def tenir(lire, dormir=time.sleep, horloge=time.monotonic, grace_s=None, max_s=None, sonde_s=None):
    """Bloque tant que le Studio a du travail pour la carte. Rend (secondes tenues, motif de fin).

    Fin : file vide (ou Studio muet) depuis `grace_s`, ou `max_s` dépassé."""
    grace_s = GRACE_S if grace_s is None else grace_s
    max_s = TENIR_MAX_S if max_s is None else max_s
    sonde_s = SONDE_S if sonde_s is None else sonde_s
    t0 = horloge()
    vide_depuis = None
    while True:
        n = lire()
        t = horloge()
        if n:
            vide_depuis = None
        elif vide_depuis is None:
            vide_depuis = t
        if vide_depuis is not None and t - vide_depuis >= grace_s:
            return t - t0, ("Studio muet" if n is None else "plus rien pour la carte")
        if t - t0 >= max_s:
            return t - t0, "plafond de %d s atteint" % max_s
        dormir(sonde_s)


# --- veiller : côté opérateur -------------------------------------------------------------------------------

def pont_en_file(etat=None):
    """Un travail du pont attend ou tourne déjà dans la file dsh3 ?"""
    etat = etat or FILE_ETAT
    for d in ("attente", "encours"):
        try:
            if any(NOM in n for n in os.listdir(os.path.join(etat, d))):
                return True
        except OSError:
            pass
    return False


def deposer_liberer():
    cmd = [sys.executable, FILE_DSH3, "deposer", "--nom", NOM, "--ressources", "gpu", "--priorite", PRIORITE,
           "--sans-suspension", "--dossier", RACINE, "--", sys.executable, os.path.abspath(__file__), "liberer"]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=os.path.dirname(FILE_DSH3))
    return r.returncode, (r.stdout + r.stderr).strip()[-400:]


def veiller(lire=studio_file, deja=pont_en_file, deposer=deposer_liberer, dormir=time.sleep, tours=None):
    """Le Studio attend la carte et aucun pont n'est en file -> on en dépose un. `tours` : pour les tests."""
    journal(evenement="veille", priorite=PRIORITE, sonde_s=SONDE_S)
    i = 0
    while tours is None or i < tours:
        i += 1
        n = lire()
        if n and not deja():
            rc, sortie = deposer()
            journal(evenement="depot", travaux_studio=n, rc=rc, sortie=sortie)
        dormir(SONDE_S)


# --- liberer : lancé par la file dsh3 ------------------------------------------------------------------------

class Machine:
    """Ce que le pont touche sur ce PC, réuni ici pour que les tests le remplacent."""

    def __init__(self):
        sys.path.insert(0, SERVEUR_DIR)
        import serveur  # noqa: E402 -- dsh3, importé sans le modifier
        self.s = serveur
        p = serveur.charger()
        self.url, self.port = "http://%s:%d" % (p["_hote"], p["_port"]), p["_port"]
        try:
            self.profil = json.load(open(serveur.ETAT, encoding="utf-8")).get("profil") or p["_repli"]
        except OSError:
            self.profil = p["_repli"]

    def attendre_repos(self):
        sys.path.insert(0, ICI)
        import maison_calcul  # noqa: E402
        return maison_calcul.attendre_repos(self.url, self.port)

    def llama_ecoute(self):
        return bool(self.s.ecouteurs(self.port))

    def arreter_llama(self):
        ok, texte, _ = self.s.arreter(self.port, self.url)
        return ok, texte

    def relancer_llama(self, profil):
        r = subprocess.run([sys.executable, os.path.join(SERVEUR_DIR, "serveur.py"), "lancer", profil],
                           capture_output=True, text=True)
        return {"rc": r.returncode, "fin": (r.stdout + r.stderr)[-600:]}

    def rendre(self, fds):
        self.s.rendre_places(fds)


def liberer(m=None, lancer=None, lire=studio_file, **tenir_kw):
    m = m or Machine()
    lancer = lancer or lancer_garde
    res, fds, arrete = {"evenement": "liberer", "profil_llama": m.profil}, None, False
    try:
        fds, res["attente_repos_s"] = m.attendre_repos()
        if not lire():  # annulé pendant qu'on attendait le repos : llama reste comme il est
            res["fin_tenue"] = "plus rien pour la carte avant l'arrêt"
            return 0
        if m.llama_ecoute():
            res["garde"] = lancer(os.getpid(), m.profil)  # AVANT l'arrêt : la relance ne dépend pas de moi
            ok, texte = m.arreter_llama()
            res["arret_llama"] = texte
            if not ok:
                raise RuntimeError(texte)
            arrete = True
        s, res["fin_tenue"] = tenir(lire, **tenir_kw)
        res["tenu_s"] = round(s, 1)
    except Exception as e:  # noqa: BLE001 -- l'échec est écrit, puis llama est relancé
        res["erreur"] = "%s: %s" % (type(e).__name__, e)
    finally:
        m.rendre(fds)
        if arrete:
            res["relance_llama"] = m.relancer_llama(m.profil)
        journal(**res)
    return 0 if "erreur" not in res else 1


# --- garde : détachée, survit au lanceur ---------------------------------------------------------------------

def _cree(pid):
    import psutil
    try:
        return psutil.Process(pid).create_time()
    except psutil.Error:
        return None


def vivant(pid, cree):
    """Le même processus (le PID peut resservir sous Windows : on compare l'heure de création)."""
    c = _cree(pid)
    return c is not None and (cree is None or abs(c - cree) < 1e-3)


def conteneur_present(nom):
    r = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", nom], capture_output=True, text=True)
    return r.returncode == 0 and r.stdout.strip() == "true"


def lancer_garde(pid, profil, conteneur=None):
    cmd = [sys.executable, os.path.abspath(__file__), "garde", "--pid", str(pid), "--cree", repr(_cree(pid)),
           "--profil", profil] + (["--conteneur", conteneur] if conteneur else [])
    kw = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
    try:
        p = subprocess.Popen(cmd, creationflags=DETACHE | HORS_JOB, **kw)
    except OSError:
        p = subprocess.Popen(cmd, creationflags=DETACHE, **kw)
    return p.pid


def garde(pid, cree, profil, conteneur=None, m=None, en_vie=vivant, present=conteneur_present,
          lire=studio_file, dormir=time.sleep, **tenir_kw):
    while en_vie(pid, cree):
        dormir(10)
    if conteneur:
        while present(conteneur):
            dormir(15)
        attendu = "conteneur %s parti" % conteneur
    else:
        _, attendu = tenir(lire, dormir=dormir, **tenir_kw)
    m = m or Machine()
    if m.llama_ecoute():
        return 0  # le lanceur a fini proprement : rien à faire
    journal(evenement="garde", lanceur=pid, constat="lanceur disparu, llama arrêté", attendu=attendu,
            relance_llama=m.relancer_llama(profil))
    return 0


def main(argv):
    if not argv or argv[0] not in ("veiller", "liberer", "garde"):
        print(__doc__)
        return 2
    if argv[0] == "veiller":
        veiller()
        return 0
    if argv[0] == "liberer":
        return liberer()
    a = dict(zip(argv[1::2], argv[2::2]))
    cree = a.get("--cree")
    return garde(int(a["--pid"]), None if cree in (None, "None") else float(cree), a["--profil"], a.get("--conteneur"))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
