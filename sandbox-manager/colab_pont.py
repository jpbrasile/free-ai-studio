"""Le carnet Colab OUVERT, pilote par le Studio (PLAN.md, point 17.3 et 17.4).

Pourquoi le carnet ouvert et pas une API : la FAQ de Colab interdit, sur l'offre
gratuite, de << contourner l'interface du carnet >>. Le Studio ne contourne
rien : la personne ouvre Colab dans SON navigateur, accepte la boite
« Connect to a local Colab MCP server », et le Studio ajoute et lance des
cellules sous ses yeux. Elle voit chaque cellule apparaitre.

Le protocole est celui de `googlecolab/colab-mcp` (Apache-2.0), relu le
24/09/2026 dans `websocket_server.py` et `session.py`, sans le reprendre comme
dependance (il exige Python 3.13, l'image est en 3.12) :
  - l'adresse du carnet porte `#mcpProxyToken=<jeton>&mcpProxyPort=<port>` ;
  - l'onglet Colab ouvre ws://localhost:<port> (sous-protocole << mcp >>), le
    jeton en `access_token` ou en `Authorization: Bearer`, Origin Colab ;
  - c'est l'ONGLET qui est le serveur MCP : le Studio est le client JSON-RPC,
    et les outils (add_code_cell, run_code_cell, update_cell, delete_cell,
    get_cells...) viennent de Colab. Leurs noms et reponses sont ceux que le
    fork xynogen a releves sur le vrai Colab (CHANGELOG, 19/06/2026).
Branchement vu en reel le 25/09/2026 (journal : << carnet Colab branche >>,
carnet vide, compte du proprietaire). **Non verifie de bout en bout** : un
travail rendu par le vrai Colab.

Rien de ce module n'execute de code sur CET ordinateur : il envoie du texte de
cellule a un carnet que la personne a ouvert et accepte, et relit des sorties.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Callable, Optional

ORIGINES = ("https://colab.research.google.com", "https://colab.google.com")
# Le carnet ouvert est celui du depot (notebooks/carnet-studio-colab.ipynb),
# pas un carnet vide : ses metadonnees demandent la carte T4 (accelerator GPU,
# gpuType T4), et Colab s'y branche d'emblee avec elle. Demande du 25/09/2026,
# « trop de réglage colab manuel » : la personne n'a plus a passer par
# « Exécution › Modifier le type d'exécution ». COLAB_CARNET remet un autre
# carnet (l'ancien : .../notebooks/empty.ipynb) si celui-ci venait a manquer.
CARNET = os.getenv(
    "COLAB_CARNET",
    "https://colab.research.google.com/github/jpbrasile/free-ai-studio/blob/main/"
    "notebooks/carnet-studio-colab.ipynb")
PROTOCOLE = "2025-06-18"
MARQUE = "@@FAIS@@"
# Un morceau de fichier par execution de cellule. 256 Kio bruts, 342 Kio en
# base64 : la borne de sortie d'une cellule que Colab rend par ce canal n'est
# pas connue ; ce morceau est choisi petit, pas mesure.
MORCEAU = 256 * 1024
# Au-dela, on ne rapatrie pas par des cellules : ce n'est plus un clip.
RAPATRIE_MAX = 200 * 1024 * 1024
SUIVI_S = 10.0
APPEL_S = 120.0


class ColabAbsent(Exception):
    """Aucun carnet branche : la personne n'a pas ouvert Colab, ou l'a ferme."""


class ColabOccupe(Exception):
    """Le carnet branche fait deja un travail : un seul a la fois."""


class ColabErreur(Exception):
    """Colab a repondu une erreur, ou le carnet s'est debranche en route."""


class ColabSansCarte(Exception):
    """Le carnet tourne sans carte graphique alors que le travail en demande une."""


PHRASE_SANS_CARTE = (
    "Votre carnet Colab tourne sans carte graphique. Dans Colab : menu "
    "« Exécution » › « Modifier le type d’exécution » › « GPU T4 », "
    "enregistrez, puis relancez depuis le Studio. La carte gratuite n’est pas "
    "garantie : Colab la refuse parfois, surtout l’après-midi.")
PHRASE_PAS_PRET = (
    "Votre carnet Colab n’a pas répondu en 5 minutes. Regardez l’onglet Colab : "
    "s’il affiche « Ce notebook n’a pas été créé par Google », cliquez « Exécuter "
    "quand même », puis relancez depuis le Studio.")
PHRASE_ABSENT = (
    "Aucun carnet Colab n’est branché. Cliquez « Ouvrir Colab », acceptez la "
    "boîte « Connect to a local Colab MCP server », puis relancez.")


class Session:
    """Un onglet Colab branche. Vit dans la boucle asyncio du service."""

    def __init__(self, envoyer: Callable, boucle: asyncio.AbstractEventLoop):
        self._envoyer = envoyer
        self.boucle = boucle
        self._n = 0
        self._attentes: dict[int, asyncio.Future] = {}
        self.outils: list[str] = []
        self.serveur: dict = {}
        self.depuis = time.time()
        self.vivante = True

    async def appel(self, methode: str, params: dict | None = None, delai: float = APPEL_S) -> dict:
        if not self.vivante:
            raise ColabErreur("Le carnet Colab s'est débranché.")
        self._n += 1
        ident = self._n
        fut = self.boucle.create_future()
        self._attentes[ident] = fut
        try:
            await self._envoyer(json.dumps({"jsonrpc": "2.0", "id": ident, "method": methode,
                                            "params": params or {}}))
            return await asyncio.wait_for(fut, delai)
        except asyncio.TimeoutError as exc:
            raise ColabErreur("Colab n'a pas répondu à %s en %d s." % (methode, delai)) from exc
        finally:
            self._attentes.pop(ident, None)

    async def avis(self, methode: str, params: dict | None = None) -> None:
        await self._envoyer(json.dumps({"jsonrpc": "2.0", "method": methode, "params": params or {}}))

    async def recu(self, brut: str) -> None:
        try:
            m = json.loads(brut)
        except ValueError:
            return
        if not isinstance(m, dict):
            return
        if "method" in m and "id" in m:
            # Une question de Colab au client. Seul `ping` a une reponse utile.
            reponse = ({"jsonrpc": "2.0", "id": m["id"], "result": {}} if m["method"] == "ping" else
                       {"jsonrpc": "2.0", "id": m["id"],
                        "error": {"code": -32601, "message": "methode inconnue du Studio"}})
            await self._envoyer(json.dumps(reponse))
            return
        if m.get("method") == "notifications/tools/list_changed":
            asyncio.ensure_future(self.lister_outils())
            return
        fut = self._attentes.get(m.get("id"))
        if fut is not None and not fut.done():
            fut.set_result(m)

    async def initialiser(self) -> None:
        r = await self.appel("initialize", {
            "protocolVersion": PROTOCOLE, "capabilities": {},
            "clientInfo": {"name": "free-ai-studio", "version": "1"}})
        if "error" in r:
            raise ColabErreur("Colab a refusé l'ouverture : %s" % r["error"])
        self.serveur = (r.get("result") or {}).get("serverInfo") or {}
        await self.avis("notifications/initialized")
        await self.lister_outils()

    async def lister_outils(self) -> None:
        r = await self.appel("tools/list")
        self.outils = [t.get("name") for t in (r.get("result") or {}).get("tools", [])]

    def fermer(self) -> None:
        self.vivante = False
        for fut in self._attentes.values():
            if not fut.done():
                fut.set_exception(ColabErreur("Le carnet Colab s'est débranché en route."))


class Pont:
    """Le seul carnet branche au Studio. Un seul a la fois, comme colab-mcp."""

    def __init__(self) -> None:
        self.jeton = secrets.token_urlsafe(16)
        self._session: Optional[Session] = None
        self._travail = threading.Lock()
        self.dernier_refus = ""

    def adresse(self, port: int) -> str:
        return "%s#mcpProxyToken=%s&mcpProxyPort=%d" % (CARNET, self.jeton, int(port))

    def refus(self, origine: str | None, jeton: str | None) -> str | None:
        """La raison de refuser ce branchement, ou None. Origine d'abord : un
        autre site que Colab ne se branche jamais, meme avec le bon jeton."""
        if (origine or "") not in ORIGINES:
            return "origine refusée : %s" % (origine or "aucune")
        if not jeton or not secrets.compare_digest(jeton, self.jeton):
            return "jeton refusé"
        if self._session is not None and self._session.vivante:
            return "un carnet est déjà branché"
        return None

    def branche(self) -> bool:
        return self._session is not None and self._session.vivante

    def etat(self) -> dict:
        s = self._session
        if s is None or not s.vivante:
            return {"branche": False, "occupe": False, "dernier_refus": self.dernier_refus}
        return {"branche": True, "depuis": s.depuis, "outils": list(s.outils),
                "occupe": self._travail.locked(), "serveur": s.serveur}

    async def servir(self, envoyer: Callable, recevoir: Callable) -> None:
        """Tient un onglet branche jusqu'a ce qu'il parte. `recevoir()` rend le
        texte suivant, et leve quand l'onglet se ferme."""
        s = Session(envoyer, asyncio.get_running_loop())

        async def lire() -> None:
            while True:
                await s.recu(await recevoir())

        lecteur = asyncio.ensure_future(lire())
        try:
            await s.initialiser()
            self._session = s
            await lecteur
        finally:
            s.fermer()
            lecteur.cancel()
            if self._session is s:
                self._session = None
            # Un nouveau jeton a chaque debranchement : une adresse qui a
            # traine (historique, capture d'ecran) ne rebranche plus rien.
            self.jeton = secrets.token_urlsafe(16)

    def outil(self, nom: str, arguments: dict, delai: float = APPEL_S) -> str:
        """Appelle un outil de Colab depuis un fil de travail ; rend le texte."""
        s = self._session
        if s is None or not s.vivante:
            raise ColabAbsent(PHRASE_ABSENT)
        fut = asyncio.run_coroutine_threadsafe(
            s.appel("tools/call", {"name": nom, "arguments": arguments}, delai), s.boucle)
        try:
            r = fut.result(delai + 5)
        except ColabErreur:
            raise
        except Exception as exc:  # noqa: BLE001 -- delai du fil, boucle fermee
            raise ColabErreur("Colab n'a pas répondu (%s)." % type(exc).__name__) from exc
        if "error" in r:
            raise ColabErreur("Colab a refusé %s : %s" % (nom, r["error"].get("message", r["error"])))
        res = r.get("result") or {}
        texte = "".join(c.get("text", "") for c in res.get("content", []) if c.get("type") == "text")
        if res.get("isError"):
            raise ColabErreur("Colab a refusé %s : %s" % (nom, texte[:500]))
        return texte

    def reserver(self) -> "Reservation":
        if not self.branche():
            raise ColabAbsent(PHRASE_ABSENT)
        if not self._travail.acquire(blocking=False):
            raise ColabOccupe("Le carnet Colab fait déjà un travail du Studio : un seul à la fois.")
        return Reservation(self._travail)


class Reservation:
    def __init__(self, verrou: threading.Lock):
        self._verrou = verrou

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._verrou.release()
        return False


PONT = Pont()


# ---------------------------------------------------------------------------
# Le travail : lancer un script dans le carnet, le suivre, rapatrier ses fichiers.
#
# Le script tourne en ARRIERE-PLAN dans la machine Colab (Popen depuis le
# noyau), et une petite cellule relancee toutes les SUIVI_S secondes le suit.
# Une seule longue cellule aurait ete plus simple, mais le delai de l'onglet
# sur un `run_code_cell` de dix minutes n'est pas connu, et elle rendait
# l'arret impossible : aucun outil de Colab n'interrompt une cellule.

# Vu le 25/09/2026 : la PREMIERE cellule lancee dans un carnet venu de GitHub
# attend que la personne clique « Exécuter quand même » (avertissement de
# Colab), et la machine peut encore demarrer ; run_code_cell rend alors une
# reponse VIDE. Une cellule sans effet est donc relancee jusqu'a ce qu'elle
# reponde, avant d'envoyer le travail.
_PRET = r'''
print("%(marque)s" + "{}")
'''
PRET_S = 300.0

_LANCER = r'''
import base64, json, os, shutil, subprocess, sys, time
from pathlib import Path
_d = Path("/content/free_ai_studio/%(n)s")
if _d.exists():
    shutil.rmtree(_d)
(_d / "free_ai_output").mkdir(parents=True)
(_d / "job.py").write_bytes(base64.b64decode("%(code)s"))
_carte = subprocess.run(["nvidia-smi", "-L"], capture_output=True, text=True).stdout.strip() if shutil.which("nvidia-smi") else ""
if %(gpu)s and not _carte:
    print("%(marque)s" + json.dumps({"carte": False}))
else:
    _env = dict(os.environ, FREE_AI_OUTPUT_DIR=str(_d / "free_ai_output"), PYTHONUNBUFFERED="1")
    _fais = globals().setdefault("_free_ai_studio", {})
    _fais["%(n)s"] = (subprocess.Popen([sys.executable, "job.py"], cwd=str(_d), env=_env,
                      stdout=open(_d / "stdout.txt", "wb"), stderr=open(_d / "stderr.txt", "wb")), time.time())
    print("%(marque)s" + json.dumps({"carte": _carte, "pid": _fais["%(n)s"][0].pid}))
'''

_SUIVRE = r'''
import json, time
_p, _t0 = _free_ai_studio["%(n)s"]
_rc = _p.poll()
if _rc is None and time.time() - _t0 > %(delai)d:
    _p.kill(); _p.wait(); _rc = "delai"
print("%(marque)s" + json.dumps({"fini": _rc is not None, "code": _rc, "secondes": round(time.time() - _t0, 1)}))
'''

_ARRETER = r'''
import json
_p, _t0 = _free_ai_studio["%(n)s"]
if _p.poll() is None:
    _p.kill(); _p.wait()
print("%(marque)s" + json.dumps({"arrete": True}))
'''

_LIRE = r'''
import hashlib, json
from pathlib import Path
_d = Path("/content/free_ai_studio/%(n)s")
def _fin(p, n=200000):
    b = p.read_bytes() if p.exists() else b""
    return b[-n:].decode("utf-8", "replace")
_f = []
for _p in sorted((_d / "free_ai_output").rglob("*")):
    if _p.is_file() and not _p.is_symlink():
        _f.append({"nom": str(_p.relative_to(_d / "free_ai_output")), "taille": _p.stat().st_size,
                   "sha256": hashlib.sha256(_p.read_bytes()).hexdigest()})
print("%(marque)s" + json.dumps({"stdout": _fin(_d / "stdout.txt"), "stderr": _fin(_d / "stderr.txt"), "fichiers": _f}))
'''

_MORCEAU = r'''
import base64
with open("/content/free_ai_studio/%(n)s/free_ai_output/" + %(nom)r, "rb") as _h:
    _h.seek(%(debut)d)
    print("%(marque)s" + base64.b64encode(_h.read(%(taille)d)).decode())
'''


def sortie_de(texte: str) -> str:
    """La derniere ligne marquee de la reponse de run_code_cell.

    La reponse est un JSON {"outputs": [...]} au format des carnets ; une
    sortie << error >> leve avec le message Python."""
    try:
        d = json.loads(texte)
    except ValueError as exc:
        raise ColabErreur("Réponse illisible de Colab : %s" % texte[:300]) from exc
    morceaux = []
    for o in d.get("outputs", []) if isinstance(d, dict) else []:
        if o.get("output_type") == "error":
            raise ColabErreur("La cellule a échoué dans Colab : %s: %s"
                              % (o.get("ename", "?"), o.get("evalue", "")))
        if o.get("output_type") == "stream" and o.get("name") == "stdout":
            t = o.get("text", "")
            morceaux.append("".join(t) if isinstance(t, list) else str(t))
    for ligne in reversed("".join(morceaux).splitlines()):
        if ligne.startswith(MARQUE):
            return ligne[len(MARQUE):]
    raise ColabErreur("La cellule n'a rien rendu de lisible : %s" % "".join(morceaux)[-300:])


class Cellule:
    """Une cellule du Studio dans le carnet : ajoutee une fois, relancee au besoin."""

    def __init__(self, pont: Pont, code: str, index: int):
        self.pont = pont
        r = json.loads(pont.outil("add_code_cell", {"cellIndex": index, "code": code, "language": "python"}))
        self.ident = r["newCellId"]

    def changer(self, code: str) -> None:
        self.pont.outil("update_cell", {"cellId": self.ident, "content": code})

    def lancer(self, delai: float = APPEL_S) -> str:
        return sortie_de(self.pont.outil("run_code_cell", {"cellId": self.ident}, delai))

    def effacer(self) -> None:
        try:
            self.pont.outil("delete_cell", {"cellId": self.ident})
        except Exception:  # noqa: BLE001 -- ranger ne doit pas masquer l'issue du travail
            pass


def executer(pont: Pont, code: str, sortie: Path, delai_s: int, gpu: bool = False,
             arret: Callable[[], bool] = lambda: False,
             progres: Callable[[dict], None] = lambda e: None) -> dict:
    """Fait tourner `code` dans le carnet branche ; ecrit ses fichiers dans `sortie`.

    Rend la meme forme que les autres executeurs du Studio : exit_code, stdout,
    stderr, timed_out, et `fichiers` (les chemins ecrits). Leve ColabAbsent,
    ColabOccupe, ColabSansCarte ou ColabErreur -- jamais un faux succes."""
    n = "t%d_%s" % (int(time.time()), secrets.token_hex(3))
    vars_ = {"n": n, "marque": MARQUE}
    with pont.reserver():
        cellules = json.loads(pont.outil("get_cells", {}) or "{}").get("cells", [])
        index = len(cellules)
        faites: list[Cellule] = []
        try:
            pret = Cellule(pont, _PRET % vars_, index)
            faites.append(pret)
            fin = time.time() + PRET_S
            while True:
                try:
                    pret.lancer(delai=90)
                    break
                except ColabErreur as exc:
                    # Vu en reel : reponse vide (a 55 s) OU pas de reponse du tout.
                    if not any(m in str(exc) for m in ("rien rendu de lisible", "n'a pas répondu")):
                        raise
                    if time.time() > fin or arret():
                        raise ColabErreur(PHRASE_PAS_PRET) from exc
                    progres({"etape": "attente"})
                    time.sleep(SUIVI_S)
            index += 1
            lancer = Cellule(pont, _LANCER % dict(vars_, code=base64.b64encode(code.encode("utf-8")).decode(),
                                                  gpu="True" if gpu else "False"), index)
            faites.append(lancer)
            depart = json.loads(lancer.lancer(delai=300))
            if depart.get("carte") is False:
                raise ColabSansCarte(PHRASE_SANS_CARTE)
            progres({"etape": "lance", "carte": depart.get("carte") or ""})
            suivre = Cellule(pont, _SUIVRE % dict(vars_, delai=int(delai_s)), index + 1)
            faites.append(suivre)
            arrete = False
            while True:
                etat = json.loads(suivre.lancer())
                progres({"etape": "calcul", "secondes": etat.get("secondes")})
                if etat.get("fini"):
                    break
                if arret():
                    arreter = Cellule(pont, _ARRETER % vars_, index + 2)
                    faites.append(arreter)
                    arreter.lancer()
                    arrete = True
                    etat = {"code": -9}
                    break
                time.sleep(SUIVI_S)
            lire = Cellule(pont, _LIRE % vars_, len(cellules) + len(faites))
            faites.append(lire)
            bilan = json.loads(lire.lancer())
            ecrits = rapatrier(pont, vars_, bilan.get("fichiers", []), sortie, len(cellules) + len(faites), faites)
            code_retour = etat.get("code")
            return {
                "exit_code": 124 if code_retour == "delai" else int(code_retour if code_retour is not None else 1),
                "timed_out": code_retour == "delai",
                "arrete": arrete,
                "stdout": bilan.get("stdout", ""),
                "stderr": bilan.get("stderr", ""),
                "fichiers": ecrits,
                "gpu": depart.get("carte") or "",
            }
        finally:
            for c in faites:
                c.effacer()


def rapatrier(pont: Pont, vars_: dict, fichiers: list[dict], sortie: Path, index: int,
              faites: list) -> list[Path]:
    total = sum(int(f.get("taille", 0)) for f in fichiers)
    if total > RAPATRIE_MAX:
        raise ColabErreur("Le travail a écrit %d Mo dans Colab : trop pour être rapatrié "
                          "par le carnet (%d Mo au plus)." % (total // 2**20, RAPATRIE_MAX // 2**20))
    sortie.mkdir(parents=True, exist_ok=True)
    racine = sortie.resolve()
    ecrits: list[Path] = []
    cellule = None
    for f in fichiers:
        nom, taille = str(f["nom"]), int(f["taille"])
        cible = (sortie / nom).resolve()
        # Un nom venu du carnet ne sort pas du dossier du travail.
        if racine not in cible.parents:
            raise ColabErreur("Nom de fichier refusé : %s" % nom)
        cible.parent.mkdir(parents=True, exist_ok=True)
        h = hashlib.sha256()
        with open(cible, "wb") as dest:
            for debut in range(0, max(taille, 1), MORCEAU):
                code = _MORCEAU % dict(vars_, nom=nom, debut=debut, taille=MORCEAU)
                if cellule is None:
                    cellule = Cellule(pont, code, index)
                    faites.append(cellule)
                else:
                    cellule.changer(code)
                bloc = base64.b64decode(cellule.lancer())
                h.update(bloc)
                dest.write(bloc)
        if h.hexdigest() != f.get("sha256"):
            raise ColabErreur("Le fichier %s est arrivé abîmé (empreinte différente)." % nom)
        ecrits.append(cible)
    return ecrits
