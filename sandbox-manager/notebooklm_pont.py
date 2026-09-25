"""NotebookLM (« Gemini Notebook ») par la bibliotheque notebooklm-py (PLAN.md 17.5-17.6).

Decision du proprietaire, 23-24/09/2026 : la page /notebooklm cesse d'etre un
simple lien. Le Studio fabrique un carnet, y verse les documents, demande un
resume audio EN FRANCAIS, le rapatrie, et laisse le carnet ouvert dans le
compte de la personne pour qu'elle y pose ses questions.

CE QUE CA COUTE EN CONFIANCE -- a dire a la personne, pas a cacher :
  - notebooklm-py (MIT) pilote des API NON DOCUMENTEES de Google. Elles
    peuvent changer sans preavis ; la bibliotheque est epinglee (0.8.2) et
    `verifier()` le voit avant la personne.
  - La << session >> est un jeu de cookies de compte Google entier, pas une cle
    d'API. Elle est gardee FERMEE par le coffre du Studio (`coffre.chiffrer`),
    ne sort en clair que dans un dossier temporaire le temps d'un appel, et
    n'est jamais affichee ni renvoyee par une route.

Mesure du 24/09/2026 (session fausse, aucune donnee de compte) : une session
morte ne leve PAS AuthError a l'ouverture, mais une ValueError
(`_LoginRedirectError`) << Authentication expired or invalid >>. `traduire`
la reconnait a ce message.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable

import coffre

DOSSIER = Path(os.getenv("FREE_AI_CONFIG_DIR", "/config")) / "notebooklm"
FICHIER = DOSSIER / "session.coffre"
URL_CARNET = "https://notebook.google.com/notebook/%s"
# Les formats et longueurs de l'Audio Overview (notebooklm.AudioFormat /
# AudioLength, relus dans la 0.8.2 installee le 24/09/2026).
FORMATS = {"approfondi": "DEEP_DIVE", "bref": "BRIEF", "critique": "CRITIQUE", "debat": "DEBATE"}
LONGUEURS = {"court": "SHORT", "normal": "DEFAULT", "long": "LONG"}
# La documentation de la bibliotheque conseille 1 200 s pour l'audio ; son
# defaut Python (300 s) est trop court.
AUDIO_DELAI_S = int(os.getenv("NOTEBOOKLM_AUDIO_TIMEOUT_SECONDS", "1200"))
SOURCE_DELAI_S = 300.0
# Recherche web rapide de NotebookLM (research.start, mode fast) : son delai, et
# combien de pages trouvees entrent au plus dans le carnet.
RECHERCHE_DELAI_S = 300.0
RECHERCHE_MAX = 10
EXTENSIONS = (".pdf", ".txt", ".md", ".docx")
TEXTE_MAX = 500_000   # signes colles dans la page ; NotebookLM borne une source a 500 000 mots

PHRASE_ABSENTE = ("NotebookLM n’est pas encore branché : suivez « Brancher NotebookLM » "
                  "sur cette page (une seule fois).")
PHRASE_EXPIREE = ("La session NotebookLM a expiré ou a été refusée par Google. Essayez d’abord "
                  "« Réparer la session » ; si Google refuse encore, double-cliquez de nouveau sur "
                  "brancher-notebooklm.cmd (dossier du Studio), puis « J’ai fini, vérifier ». "
                  "Vos résumés déjà faits restent ci-dessous.")
PHRASE_IRREPARABLE = ("Google refuse encore la session gardée : il faut se reconnecter. "
                      "Double-cliquez sur brancher-notebooklm.cmd (dossier du Studio), puis "
                      "« J’ai fini, vérifier ».")
PHRASE_QUOTA = ("Google refuse pour l’instant : le quota de NotebookLM est atteint (l’offre "
                "gratuite annonce 3 résumés audio par jour). Réessayez demain.")

# Google perime __Secure-1PSIDTS s'il ne tourne pas : la bibliotheque conseille
# un `auth refresh` toutes les 15 a 20 minutes (docstring de la commande, 0.8.2).
# Vu en reel le 25/09/2026 : session du matin morte avant 08:33 sans entretien.
ENTRETIEN_S = int(os.getenv("NOTEBOOKLM_ENTRETIEN_SECONDES", "900"))
# Pendant un appel long (un resume attend jusqu'a 20 min), le client fait
# tourner lui-meme les cookies a ce rythme ; ecrits dans son fichier a la sortie.
ENTRETIEN_CLIENT_S = 600.0

log = logging.getLogger("sandbox-manager.notebooklm")
_verrou = threading.Lock()


def regler(dossier_config: Path) -> None:
    """Le service donne son dossier de configuration (volume persistant)."""
    global DOSSIER, FICHIER
    DOSSIER = Path(dossier_config) / "notebooklm"
    FICHIER = DOSSIER / "session.coffre"


class SessionAbsente(Exception):
    pass


class SessionExpiree(Exception):
    pass


class QuotaAtteint(Exception):
    pass


class NotebookLMEchec(Exception):
    pass


class CarnetsPleins(NotebookLMEchec):
    """Le compte a atteint le nombre maximal de carnets. La page propose alors
    de supprimer les plus anciens -- la personne choisit, rien ne part seul."""


# Decision du proprietaire, 25/09/2026 : un nom clair pour les carnets du
# Studio, et quand le compte est plein, la page DEMANDE lesquels supprimer.
PREFIXE = "Studio"
PHRASE_PLEIN = ("Votre NotebookLM est plein : Google n’accepte plus de nouveau carnet. "
                "Choisissez ci-dessous les anciens carnets à supprimer, puis relancez.")


# --- La session : fermee dans le coffre, ouverte le temps d'un appel ---------

def branchee() -> bool:
    return FICHIER.exists()


def _lire() -> str:
    if not FICHIER.exists():
        raise SessionAbsente(PHRASE_ABSENTE)
    return coffre.dechiffrer(FICHIER.read_text(encoding="utf-8"))


def _sceller(storage_state: str) -> None:
    DOSSIER.mkdir(parents=True, exist_ok=True)
    tmp = FICHIER.with_suffix(".tmp")
    tmp.write_text(coffre.chiffrer(storage_state), encoding="utf-8")
    os.replace(tmp, FICHIER)


def changements(avant: str, apres: str) -> str:
    """Ce qui a change dans la session, pour le journal : des NOMS de cookies
    et des nombres, jamais une valeur. Les doublons (meme nom sur deux
    domaines) sont signales : une ancienne valeur renvoyee apres une rotation
    peut faire fermer la session par Google (hypothese du 25/09, non verifiee)."""
    def carte(texte):
        try:
            cookies = json.loads(texte).get("cookies") or []
        except (ValueError, AttributeError):
            return None
        return {(c.get("name"), c.get("domain")): c.get("value") for c in cookies}
    a, b = carte(avant), carte(apres)
    if a is None or b is None:
        return "session illisible"
    tournes = sorted({n for (n, dom) in a.keys() & b.keys() if a[(n, dom)] != b[(n, dom)]})
    ajoutes = sorted({"%s@%s" % k for k in b.keys() - a.keys()})
    retires = sorted({"%s@%s" % k for k in a.keys() - b.keys()})
    noms = [n for (n, _dom) in b]
    doublons = sorted({n for n in noms if noms.count(n) > 1})
    return "%d -> %d cookies ; tournes : %s ; ajoutes : %s ; retires : %s ; doublons : %s" % (
        len(a), len(b), ", ".join(tournes) or "aucun", ", ".join(ajoutes) or "aucun",
        ", ".join(retires) or "aucun", ", ".join(doublons) or "aucun")


def entretenir(commande: str = "notebooklm") -> dict:
    """Garde la session vivante sans que la personne se reconnecte : la
    commande publique de la bibliotheque (`auth refresh --verify`) sur une
    copie en clair le temps de l'appel, puis la session tournee revient
    dans le coffre. Meme verrou que les appels : jamais deux rotations a la fois."""
    if not FICHIER.exists():
        return {"fait": False}
    with _verrou:
        etat = _lire()
        d = Path(tempfile.mkdtemp(prefix="nlm-entretien-"))
        try:
            chemin = d / "storage_state.json"
            chemin.write_text(etat, encoding="utf-8")
            os.chmod(chemin, 0o600)
            env = dict(os.environ, NOTEBOOKLM_HOME=str(d / "home"))
            env.pop("NOTEBOOKLM_AUTH_JSON", None)
            try:
                r = subprocess.run([commande, "--storage", str(chemin), "auth", "refresh",
                                    "--verify", "--quiet"],
                                   capture_output=True, text=True, env=env, timeout=120)
                code, message = r.returncode, " ".join((r.stderr or r.stdout or "").split())[-200:]
            except (OSError, subprocess.TimeoutExpired) as exc:
                code, message = -1, type(exc).__name__
            nouveau = chemin.read_text(encoding="utf-8") if chemin.exists() else etat
            # Ce qui a tourne chez Google est la seule version valable, meme si
            # la verification echoue ensuite : on garde toujours la plus neuve.
            with contextlib.suppress(ValueError):
                if nouveau != etat and json.loads(nouveau).get("cookies"):
                    _sceller(nouveau)
            diff = changements(etat, nouveau)
            if code:
                log.warning("NotebookLM entretien : ECHEC (code %s) %s ; %s", code, message, diff)
            else:
                log.info("NotebookLM entretien : ok ; %s", diff)
            return {"fait": True, "ok": code == 0, "changements": diff}
        finally:
            shutil.rmtree(d, ignore_errors=True)


def entretenir_sans_fin(attente=None) -> None:
    """Le fil du Studio : un entretien au demarrage (la machine a pu dormir),
    puis toutes les ENTRETIEN_S secondes. Ne s'arrete jamais sur une erreur."""
    attente = attente or time.sleep
    while True:
        try:
            entretenir()
        except Exception as exc:  # noqa: BLE001 -- le fil ne doit pas mourir
            log.warning("NotebookLM entretien : erreur %s", type(exc).__name__)
        attente(ENTRETIEN_S)


def oublier() -> bool:
    if FICHIER.exists():
        FICHIER.unlink()
        return True
    return False


def compte() -> dict:
    """Ce qu'on peut dire de la session sans l'ouvrir chez Google."""
    if not FICHIER.exists():
        return {"branchee": False}
    info = {"branchee": True, "depuis": FICHIER.stat().st_mtime}
    try:
        etat = json.loads(_lire())
        compte_ = ((etat.get("notebooklm") or {}).get("account") or {})
        info["compte"] = compte_.get("email") or ""
        info["cookies"] = len(etat.get("cookies", []))
    except Exception:  # noqa: BLE001 -- une session illisible se dit, sans detail
        info["illisible"] = True
    return info


def enregistrer(export: str, commande: str = "notebooklm") -> dict:
    """Ferme dans le coffre la session collee par la personne.

    Accepte l'export JSON d'une extension de cookies (liste, ou {"cookies": [...]})
    ou un storage_state.json de `notebooklm login`. La normalisation, le tri
    des domaines (seuls ceux de Google restent) et le controle des cookies
    requis (SID, __Secure-1PSIDTS) sont ceux de la bibliotheque, par sa
    commande publique `notebooklm auth import-cookies`."""
    texte = (export or "").strip()
    if not texte:
        raise ValueError("Collez l’export des cookies (un texte qui commence par [ ou {).")
    try:
        json.loads(texte)
    except ValueError as exc:
        raise ValueError("Ce texte n’est pas un export JSON de cookies.") from exc
    d = Path(tempfile.mkdtemp(prefix="nlm-import-"))
    try:
        brut = d / "export.json"
        brut.write_text(texte, encoding="utf-8")
        env = dict(os.environ, NOTEBOOKLM_HOME=str(d / "home"))
        env.pop("NOTEBOOKLM_AUTH_JSON", None)
        r = subprocess.run([commande, "auth", "import-cookies", str(brut)], capture_output=True,
                           text=True, env=env, timeout=60)
        cible = d / "home" / "profiles" / "default" / "storage_state.json"
        if r.returncode or not cible.exists():
            # Le message de la bibliotheque dit QUEL cookie manque ; il ne
            # contient pas de valeur de cookie.
            raise ValueError("Export refusé : " + " ".join((r.stderr or r.stdout or "").split())[:400])
        etat = cible.read_text(encoding="utf-8")
        _sceller(etat)
        return {"cookies": len(json.loads(etat).get("cookies", []))}
    finally:
        shutil.rmtree(d, ignore_errors=True)


def traduire(exc: BaseException) -> Exception:
    """Une erreur de la bibliotheque, dite a la personne. Par NOMS de classes :
    le module se teste sans la bibliotheque, et ses classes privees changent."""
    noms = {k.__name__ for k in type(exc).__mro__}
    texte = str(exc)
    if isinstance(exc, (SessionAbsente, SessionExpiree, QuotaAtteint, NotebookLMEchec)):
        return exc
    if "AuthError" in noms or "HeadlessLoginRequiredError" in noms or (
            isinstance(exc, ValueError) and "authentication expired" in texte.lower()):
        return SessionExpiree(PHRASE_EXPIREE)
    if "RateLimitError" in noms:
        return QuotaAtteint(PHRASE_QUOTA)
    if "NotebookLimitError" in noms:
        return CarnetsPleins(PHRASE_PLEIN)
    if "SourceProcessingError" in noms or "SourceAddError" in noms:
        return NotebookLMEchec("NotebookLM n’a pas su lire un des documents : %s" % texte[:300])
    if "ResearchError" in noms or "ResearchTimeoutError" in noms:
        return NotebookLMEchec("La recherche web de NotebookLM a échoué ou n’a pas fini à temps. "
                               "Réessayez, ou décochez « Chercher aussi sur le web ».")
    if "WaitTimeoutError" in noms or "SourceTimeoutError" in noms:
        return NotebookLMEchec("NotebookLM n’a pas fini à temps. Le travail continue peut-être "
                               "chez Google : ouvrez le carnet dans NotebookLM.")
    if "AuthExtractionError" in noms or "UnknownRPCMethodError" in noms:
        return NotebookLMEchec("Google a changé NotebookLM et la bibliothèque du Studio ne le "
                               "comprend plus : il faut mettre le Studio à jour. (%s)" % texte[:200])
    return NotebookLMEchec("NotebookLM a échoué : %s: %s" % (type(exc).__name__, texte[:300]))


@contextlib.asynccontextmanager
async def client():
    """Un client NotebookLM sur la session du coffre.

    La bibliotheque RECRIT les cookies qu'elle fait tourner dans son fichier ;
    ce fichier est relu a la sortie et referme dans le coffre, sinon la
    session vieillirait a chaque appel."""
    try:
        import notebooklm   # la bibliotheque n'est chargee qu'a l'usage
    except ImportError as exc:
        raise NotebookLMEchec("La bibliothèque notebooklm-py manque dans le Studio : "
                              "relancez demarrer.cmd pour reconstruire.") from exc

    etat = _lire()
    d = Path(tempfile.mkdtemp(prefix="nlm-"))
    chemin = d / "storage_state.json"
    try:
        chemin.write_text(etat, encoding="utf-8")
        os.chmod(chemin, 0o600)
        try:
            async with notebooklm.NotebookLMClient.from_storage(
                    path=str(chemin), keepalive=ENTRETIEN_CLIENT_S) as c:
                yield c
        except Exception as exc:  # noqa: BLE001
            dite = traduire(exc)
            if dite is exc:
                raise
            raise dite from exc
        finally:
            with contextlib.suppress(Exception):
                nouveau = chemin.read_text(encoding="utf-8")
                if nouveau != etat and json.loads(nouveau).get("cookies"):
                    _sceller(nouveau)
                log.info("NotebookLM appel : %s", changements(etat, nouveau))
    finally:
        shutil.rmtree(d, ignore_errors=True)


def executer(coro_fabrique: Callable) -> object:
    """Un appel a la fois : deux appels ecriraient chacun leur rotation de
    cookies, et le second effacerait le premier."""
    with _verrou:
        return asyncio.run(coro_fabrique())


# --- Les operations ------------------------------------------------------------

async def verifier() -> dict:
    """Un appel qui ne fabrique rien : la liste des carnets. C'est la fumee
    de SP-NOTEBOOKLM-PAR-API -- une API non documentee casse sans prevenir."""
    async with client() as c:
        carnets = await c.notebooks.list()
    return {"ok": True, "carnets": len(carnets)}


def _statut(s) -> str:
    return str(getattr(s, "status", "") or "")


def nom_du_carnet(titre: str = "", quand: str = "") -> str:
    """« Studio · Phares · 25/09/2026 08:40 ». L'heure vient de la page : le
    conteneur est a l'heure UTC, et un nom decale de deux heures tromperait."""
    quand = quand if re.fullmatch(r"\d{2}/\d{2}/\d{4} \d{2}:\d{2}", quand or "") else ""
    morceaux = [PREFIXE, " ".join((titre or "Résumé").split())[:70], quand]
    return " · ".join(m for m in morceaux if m)[:100]


def _horodatage(d) -> float | None:
    try:
        return d.timestamp() if d else None
    except (AttributeError, OSError, OverflowError, ValueError):
        return None


async def carnets() -> list[dict]:
    """Les carnets du compte, du PLUS ANCIEN au plus recent. Un carnet sans
    date connue va en fin de liste : on ne propose pas de supprimer ce qu'on ne
    sait pas dater. Les carnets partages par d'autres ne sont pas a nous."""
    async with client() as c:
        tous = await c.notebooks.list()
    sortie = [{"id": n.id, "titre": getattr(n, "title", "") or "(sans titre)",
               "cree": _horodatage(getattr(n, "created_at", None)),
               "sources": getattr(n, "sources_count", 0) or 0,
               "du_studio": (getattr(n, "title", "") or "").startswith(PREFIXE + " · ")}
              for n in tous if getattr(n, "is_owner", True)]
    sortie.sort(key=lambda n: (n["cree"] is None, n["cree"] or 0))
    return sortie


async def supprimer(ids: list[str]) -> dict:
    """Supprime ces carnets, DEFINITIVEMENT. Seuls ceux que la personne possede,
    relus chez Google au moment de supprimer : un identifiant venu de la page
    qui ne figure plus dans la liste n'est pas touche."""
    fait, refuse = [], []
    async with client() as c:
        possedes = {n.id for n in await c.notebooks.list() if getattr(n, "is_owner", True)}
        for i in ids:
            if i not in possedes:
                refuse.append(i)
                continue
            try:
                await c.notebooks.delete(i)
                fait.append(i)
            except Exception as exc:  # noqa: BLE001 -- un echec n'arrete pas les suivants
                dite = traduire(exc)
                if isinstance(dite, SessionExpiree):
                    raise dite from exc
                refuse.append(i)
    return {"supprimes": fait, "refuses": refuse}


async def resume_audio(sources: list[dict], dossier: Path, titre: str = "", consigne: str = "",
                       format_: str = "approfondi", longueur: str = "normal", langue: str = "fr",
                       quand: str = "",
                       progres: Callable[[str], None] = lambda t: None) -> dict:
    """Carnet neuf + sources + resume audio en francais, rapatrie dans `dossier`.

    `sources` : [{"titre": ..., "texte": ...}] ou [{"chemin": Path}]. Rend
    {"audio": Path, "carnet_id", "carnet_url", "sources": n}. Le carnet RESTE
    dans le compte de la personne : c'est la qu'elle pose ses questions."""
    import notebooklm

    if not sources:
        raise NotebookLMEchec("Aucun document ni texte à résumer.")
    fmt = getattr(notebooklm.AudioFormat, FORMATS.get(format_, "DEEP_DIVE"))
    lon = getattr(notebooklm.AudioLength, LONGUEURS.get(longueur, "DEFAULT"))
    async with client() as c:
        progres("Création du carnet dans NotebookLM…")
        carnet = await c.notebooks.create(nom_du_carnet(titre, quand))
        ids = []
        for i, s in enumerate(sources, 1):
            progres("Envoi du document %d sur %d, puis lecture par NotebookLM…" % (i, len(sources)))
            if "chemin" in s:
                src = await c.sources.add_file(carnet.id, Path(s["chemin"]), wait=True,
                                               wait_timeout=SOURCE_DELAI_S, title=s.get("titre"))
            else:
                src = await c.sources.add_text(carnet.id, s.get("titre") or "Texte collé", s["texte"],
                                               wait=True, wait_timeout=SOURCE_DELAI_S)
            ids.append(src.id)
        progres("NotebookLM fabrique le résumé audio (souvent 5 à 10 minutes)…")
        depart = await c.artifacts.generate_audio(carnet.id, source_ids=ids, language=langue,
                                                  instructions=consigne or None,
                                                  audio_format=fmt, audio_length=lon)
        if getattr(depart, "is_rate_limited", False):
            raise QuotaAtteint(PHRASE_QUOTA)
        if getattr(depart, "is_failed", False):
            raise NotebookLMEchec("NotebookLM a refusé le résumé audio : %s"
                                  % (getattr(depart, "error", "") or _statut(depart)))
        fin = await c.artifacts.wait_for_completion(carnet.id, depart.task_id, timeout=AUDIO_DELAI_S)
        artefact = None
        if not getattr(fin, "is_complete", False):
            # notebooklm-py 0.8.2, ticket #2432 (corrige apres la 0.8.2) : une
            # generation FINIE peut etre dite << removed >>. On regarde la
            # liste des audios du carnet avant de conclure a l'echec.
            prets = [a for a in await c.artifacts.list_audio(carnet.id)
                     if getattr(a, "is_completed", False)]
            if not prets:
                if getattr(fin, "is_rate_limited", False):
                    raise QuotaAtteint(PHRASE_QUOTA)
                raise NotebookLMEchec("Le résumé audio n’a pas abouti (%s)."
                                      % (getattr(fin, "error", "") or _statut(fin)))
            artefact = prets[-1].id
        progres("Rapatriement du fichier audio…")
        dossier.mkdir(parents=True, exist_ok=True)
        cible = dossier / "resume-notebooklm.m4a"
        await c.artifacts.download_audio(carnet.id, str(cible), artifact_id=artefact)
    if not cible.exists() or cible.stat().st_size == 0:
        raise NotebookLMEchec("NotebookLM a dit le résumé prêt, mais le fichier reçu est vide.")
    return {"audio": cible, "carnet_id": carnet.id, "carnet_url": URL_CARNET % carnet.id,
            "sources": len(ids)}


def version_opus(m4a: Path, commande: str = "ffmpeg") -> Path | None:
    """Le meme resume en Opus (Ogg), fabrique a la premiere ecoute puis garde.

    NotebookLM rend de l'AAC, qu'un navigateur sans codecs brevetes ne lit pas ;
    Opus se lit partout. Ajoute le 25/09/2026 sur la piste « VS Code ne lit pas
    l'AAC », que le proprietaire a dementie le meme jour (il fallait cliquer
    « Go Live ») : un repli, sans cas reel connu ou il serve.
    None si ffmpeg manque ou echoue : la page garde alors l'AAC seul."""
    cible = m4a.with_suffix(".opus")
    if cible.exists() and cible.stat().st_size:
        return cible
    if not shutil.which(commande):
        return None
    brouillon = cible.with_name(cible.name + ".partiel")
    r = subprocess.run([commande, "-nostdin", "-y", "-loglevel", "error", "-i", str(m4a), "-vn",
                        "-c:a", "libopus", "-b:a", "64k", "-f", "ogg", str(brouillon)],
                       capture_output=True, timeout=300)
    if r.returncode or not brouillon.exists() or not brouillon.stat().st_size:
        brouillon.unlink(missing_ok=True)
        return None
    os.replace(brouillon, cible)
    return cible


async def demander(carnet_id: str, question: str, web: bool = False) -> dict:
    """Une question aux sources d'un carnet ; la reponse et ses citations.

    web=True (demande du proprietaire, 25/09/2026 : « il n'a pas la reponse
    dans la source ») : d'abord la recherche web RAPIDE de NotebookLM sur la
    question (`research.start`, mode fast), puis les pages trouvees entrent
    dans le carnet (RECHERCHE_MAX au plus) avant la question. Elles y restent,
    comme dans NotebookLM ; la page le dit avant qu'on coche."""
    ajoutees, note = [], ""
    async with client() as c:
        if web:
            depart = await c.research.start(carnet_id, question, source="web", mode="fast")
            tache = await c.research.wait_for_completion(carnet_id, depart.task_id,
                                                         timeout=RECHERCHE_DELAI_S)
            statut = getattr(tache.status, "value", tache.status)
            trouvees = [s for s in (tache.sources or ()) if getattr(s, "url", "")][:RECHERCHE_MAX]
            if statut != "completed" or not trouvees:
                note = "La recherche web n’a rien trouvé : réponse avec les seules sources du carnet."
            else:
                importees = await c.research.import_sources(carnet_id, depart.task_id, trouvees)
                # Une page encore en lecture chez Google ne compterait pas dans
                # la reponse ; une page illisible n'empeche pas les autres.
                for s in importees or []:
                    with contextlib.suppress(Exception):
                        await c.sources.wait_until_ready(carnet_id, s["id"], timeout=SOURCE_DELAI_S)
                ajoutees = [{"titre": (s.title or s.url)[:200], "url": s.url} for s in trouvees]
        r = await c.chat.ask(carnet_id, question)
    return {"reponse": r.answer,
            "citations": [{"numero": getattr(x, "citation_number", None),
                           "extrait": (getattr(x, "cited_text", "") or "")[:500]}
                          for x in (getattr(r, "references", None) or [])],
            "web": ajoutees, "note": note}


PAGE_HTML = r"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NotebookLM — Free AI Studio</title>
<style>
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;max-width:900px;
 margin:34px auto;padding:0 18px;line-height:1.55}
h1{font-size:1.5rem;margin-bottom:4px}
h2{font-size:1.15rem;margin:26px 0 6px}
.sous{opacity:.8;margin-top:0}
.banniere{padding:14px 16px;border-radius:14px;margin:16px 0;border:1px solid #bbb;background:#eef4fb}
.carte{padding:14px 16px;border-radius:14px;margin:14px 0;border:1px solid #bbb}
.ligne{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:14px 0}
select,button,input{font:inherit;padding:9px 12px;border-radius:10px;border:1px solid #666;background:#fff}
button.primaire{background:#222;color:#fff;border-color:#222;cursor:pointer}
button[disabled]{opacity:.5;cursor:default}
textarea{font:inherit;width:100%;box-sizing:border-box;height:150px;padding:12px;
 border-radius:12px;border:1px solid #999}
label.titre{display:block;font-weight:600;margin:16px 0 6px}
audio{width:100%;margin-top:12px}
.ok{color:#1d6b32}.ko{color:#9b2116}
.avert{font-size:.86rem;opacity:.8}
.donnees{padding:10px 14px;border-radius:12px;border:1px solid #d9ad63;background:#fdf6e8;font-size:.9rem}
.pied{margin-top:26px;padding-top:16px;border-top:1px solid #ddd;font-size:.9rem;opacity:.8}
ol li{margin:4px 0}
</style>
</head><body>
<h1>📚 Résumé audio avec NotebookLM</h1>
<p class="sous">Donnez vos documents : le Studio les dépose dans un carnet NotebookLM neuf, à votre
nom, demande un résumé audio en français (deux voix, façon podcast) et vous le rapporte ici. Le
carnet reste dans votre NotebookLM pour y poser vos questions.</p>

<div id="banniere" class="banniere">Vérification en cours…</div>

<!-- Session dans le coffre mais refusée (Studio arrêté longtemps, PC en veille) :
     d'abord réparer depuis le coffre, sans se reconnecter (demande du 25/09/2026). -->
<div id="reparer" class="carte" hidden>
  <p>Une session est gardée dans le coffre du Studio. Le Studio peut essayer de la
  <b>réparer auprès de Google, sans vous reconnecter</b>.</p>
  <div class="ligne"><button id="btReparer" class="primaire">Réparer la session</button>
    <span id="etatReparer"></span></div>
</div>

<div id="brancher" class="carte" hidden>
  <h2>Brancher NotebookLM (une seule fois)</h2>
  <p class="donnees"><b>À savoir avant de commencer.</b> NotebookLM n’a pas d’accès officiel pour les
  programmes. Le Studio passe par la bibliothèque libre <i>notebooklm-py</i>, qui utilise la connexion
  de votre compte Google : ce que vous collez ci-dessous <b>ouvre votre compte Google entier</b>.
  Le Studio le garde chiffré sur cet ordinateur, ne l’affiche jamais et ne l’envoie qu’à Google.
  « Oublier » l’efface. Si vous le pouvez, utilisez un compte Google réservé à cet usage.
  Google peut changer NotebookLM sans prévenir : le Studio le vérifie à chaque ouverture de la page.</p>
  <ol>
    <li>Dans le dossier du Studio, double-cliquez sur <b><code>brancher-notebooklm.cmd</code></b>
      (à côté de <code>demarrer.cmd</code>). La première fois, il installe son outil : 1 à 3 minutes.</li>
    <li>Une fenêtre Chrome (ou Edge) s’ouvre : <b>connectez-vous à Google</b> et attendez que
      NotebookLM s’affiche. Elle se ferme seule.</li>
    <li>La fenêtre noire écrit « OK : NotebookLM est branché ». Revenez ici :
      <button id="btRevoir">J’ai fini, vérifier</button></li>
  </ol>
  <p class="avert">Rien à copier ni à coller : le fichier envoie la session au Studio, puis efface
  lui-même ce qui a servi (le fichier de session et la fenêtre de navigateur restée connectée).
  Il demande Python 3.10 ou plus ; sans Python, prenez l’autre chemin ci-dessous.</p>
  <details>
    <summary>Autre chemin, sans Python : une extension de cookies</summary>
    <ol>
      <li>Ajoutez à votre navigateur une extension qui exporte les cookies en JSON
        (par exemple « Cookie-Editor »), et autorisez-la en navigation privée.</li>
      <li>Ouvrez une <b>fenêtre de navigation privée</b>, connectez-vous à Google, puis ouvrez
        <a href="https://notebook.google.com/" target="_blank" rel="noopener noreferrer">notebook.google.com</a>.</li>
      <li>Dans l’extension : « Exporter » › « JSON ». L’export est copié.</li>
      <li>Fermez la fenêtre privée <b>sans vous déconnecter</b> (se déconnecter tuerait la session).
        La fenêtre privée sert à ça : votre navigateur habituel ne remplace pas cette session.</li>
      <li>Collez l’export ici, puis « Brancher ».</li>
    </ol>
    <textarea id="export" spellcheck="false" placeholder="[{&quot;domain&quot;: &quot;.google.com&quot;, &quot;name&quot;: &quot;SID&quot;, …}]"></textarea>
    <div class="ligne"><button id="btBrancher" class="primaire">Brancher</button><span id="etatBrancher"></span></div>
  </details>
</div>

<div id="travail" hidden>
  <h2>Vos documents</h2>
  <label class="titre" for="fichiers">Fichiers (PDF, .txt, .md, .docx)</label>
  <input id="fichiers" type="file" multiple accept=".pdf,.txt,.md,.docx">
  <label class="titre" for="texte">ou un texte collé</label>
  <textarea id="texte" placeholder="Collez ici un article, des notes, un chapitre…"></textarea>
  <label class="titre" for="consigne">Consigne pour le résumé (facultatif)</label>
  <input id="consigne" style="width:100%;box-sizing:border-box" maxlength="2000"
    placeholder="Par exemple : pour un public de lycéens, insister sur les dates">
  <div class="ligne">
    <label>Forme <select id="format">
      <option value="approfondi" selected>Discussion approfondie</option>
      <option value="bref">Bref</option>
      <option value="critique">Critique</option>
      <option value="debat">Débat</option></select></label>
    <label>Durée <select id="longueur">
      <option value="court">Courte</option>
      <option value="normal" selected>Normale</option>
      <option value="long">Longue</option></select></label>
    <button id="btFabriquer" class="primaire">Fabriquer le résumé audio</button>
  </div>
  <p class="donnees">Vos documents partent chez Google (NotebookLM), dans votre compte. L’offre
  gratuite annonce 3 résumés audio par jour ; comptez souvent 5 à 10 minutes.</p>
  <div id="etat" class="ligne"></div>
  <div id="resultat" hidden>
    <audio id="lecteur" controls></audio>
    <div class="ligne"><a id="telecharger" href="#">Enregistrer le fichier audio</a>
      <a id="carnet" href="#" target="_blank" rel="noopener noreferrer">Ouvrir le carnet dans NotebookLM ↗</a></div>
    <h2>Poser une question à vos documents</h2>
    <div class="ligne"><input id="question" style="flex:1" placeholder="Que dit le document sur… ?">
      <button id="btDemander">Demander</button></div>
    <label class="avert"><input type="checkbox" id="web"> Chercher aussi sur le web : NotebookLM
      ajoute à ce carnet les pages qu’il trouve (10 au plus, elles y restent), puis répond.
      Compter 1 à 3 minutes.</label>
    <div id="reponse"></div>
  </div>
  <div id="place" class="carte" hidden>
    <h2>Faire de la place dans NotebookLM</h2>
    <p id="placeTexte"></p>
    <div class="ligne">
      <label>Cocher les <input id="nbAnciens" type="number" min="1" max="200" value="10" style="width:5em">
        plus anciens</label>
      <button id="btCocher">Cocher</button>
      <button id="btDecocher">Tout décocher</button>
    </div>
    <div id="listeCarnets" style="max-height:360px;overflow:auto;border:1px solid #ddd;border-radius:10px;padding:6px 10px"></div>
    <p class="donnees">La suppression est <b>définitive</b> : le carnet, ses sources, ses notes et ses
    résumés disparaissent de NotebookLM. Les carnets dont le nom commence par « Studio · » ont été créés
    par le Studio.</p>
    <label><input id="confirmeSuppr" type="checkbox"> Je comprends que c’est définitif.</label>
    <div class="ligne"><button id="btSupprimer" class="primaire" disabled>Supprimer les carnets cochés</button>
      <span id="etatSuppr"></span></div>
  </div>
  <p class="ligne"><button id="btPlace">Faire de la place dans NotebookLM</button>
    <button id="btOublier">Oublier la session NotebookLM</button></p>
</div>

<!-- Hors de « travail » : les résumés sont sur le disque du Studio, pas chez
     Google. Session expirée le 25/09/2026 : la page les cachait, on ne pouvait
     plus ni les écouter ni les supprimer. -->
<div id="historique">
  <h2>Vos résumés</h2>
  <div id="resumes"><p class="avert">Aucun résumé pour l’instant.</p></div>
</div>

<div class="pied">Bibliothèque : notebooklm-py 0.8.2 (licence MIT), qui pilote des accès non documentés
de Google. <a href="/">Retour au Sandbox</a></div>

<script>
const CLE = "__CLE__";
const H = {"Authorization": "Bearer " + CLE};
let CARNET = "";
let SESSION_OK = false;
function el(i){ return document.getElementById(i); }
function texte(i, t, classe){ const e = el(i); e.textContent = t; e.className = classe || ""; }

async function charger(){
  const r = await fetch("/notebooklm/etat?verifier=1", {headers: H});
  const e = await r.json();
  const b = el("banniere");
  if(e.coupe){
    b.textContent = "NotebookLM piloté est coupé ici (" + e.coupe + ") : ouvrez NotebookLM vous-même.";
    return;
  }
  el("brancher").hidden = !!(e.branchee && e.ok);
  el("travail").hidden = !(e.branchee && e.ok);
  SESSION_OK = !!(e.branchee && e.ok);
  el("reparer").hidden = !(e.branchee && !e.ok);
  // Branché ou non : les résumés déjà faits s'écoutent et se suppriment.
  listerResumes();
  // textContent seulement : le message peut porter un texte venu de Google.
  b.className = "banniere";
  if(!e.branchee){
    b.textContent = "NotebookLM n’est pas encore branché.";
  } else if(e.ok){
    b.textContent = "✅ NotebookLM branché" + (e.compte ? " (" + e.compte + ")" : "")
      + " — " + e.carnets + " carnet(s) dans ce compte.";
    b.classList.add("ok");
  } else {
    b.textContent = "⚠️ " + (e.message || "Session refusée.");
    b.classList.add("ko");
  }
}

// La réponse de NotebookLM est en Markdown (25/09/2026 : « l'affichage de la
// réponse est en markdown brut »). Titres, listes, gras, italique, code : des
// NŒUDS créés un à un, jamais de HTML injecté -- le texte vient de Google.
function enLigne(parent, t){
  const motif = /(\*\*[^*]+\*\*|__[^_]+__|\*[^*\s][^*]*\*|`[^`]+`)/g;
  let i = 0, m;
  while((m = motif.exec(t))){
    if(m.index > i) parent.appendChild(document.createTextNode(t.slice(i, m.index)));
    const s = m[0], gras = s.startsWith("**") || s.startsWith("__");
    const n = document.createElement(gras ? "strong" : s.startsWith("`") ? "code" : "em");
    n.textContent = gras ? s.slice(2, -2) : s.slice(1, -1);
    parent.appendChild(n);
    i = m.index + s.length;
  }
  if(i < t.length) parent.appendChild(document.createTextNode(t.slice(i)));
}
function markdown(div, texte){
  let liste = null, para = null;
  for(const brute of String(texte || "").split("\n")){
    const l = brute.replace(/\s+$/, "");
    if(!l.trim()){ liste = null; para = null; continue; }
    const titre = l.match(/^\s*(#{1,6})\s+(.*)$/);
    if(titre){
      liste = null; para = null;
      const h = document.createElement("h" + Math.min(6, titre[1].length + 2));
      enLigne(h, titre[2]);
      div.appendChild(h);
      continue;
    }
    const puce = l.match(/^\s*(?:[-*+•]|(\d+)[.)])\s+(.*)$/);
    if(puce){
      para = null;
      const sorte = puce[1] ? "ol" : "ul";
      if(!liste || liste.tagName.toLowerCase() !== sorte){
        liste = document.createElement(sorte);
        div.appendChild(liste);
      }
      const li = document.createElement("li");
      enLigne(li, puce[2]);
      liste.appendChild(li);
      continue;
    }
    liste = null;
    if(para){ para.appendChild(document.createElement("br")); }
    else { para = document.createElement("p"); div.appendChild(para); }
    enLigne(para, l);
  }
}

// Après brancher-notebooklm.cmd : la session est déjà dans le coffre, on relit l'état.
el("btRevoir").onclick = async () => {
  el("btRevoir").disabled = true;
  try { await charger(); } finally { el("btRevoir").disabled = false; }
};

el("btReparer").onclick = async () => {
  el("btReparer").disabled = true;
  texte("etatReparer", "Réparation auprès de Google…");
  let d = {};
  try {
    const r = await fetch("/notebooklm/reparer", {method: "POST", headers: H});
    d = await r.json();
    if(!r.ok){ d = {ok: false, message: d.detail}; }
  } catch(e) { d = {ok: false, message: "Le Studio ne répond pas."}; }
  el("btReparer").disabled = false;
  if(d.ok){ texte("etatReparer", "Réparée.", "ok"); await charger(); return; }
  texte("etatReparer", d.message || "Google refuse encore.", "ko");
};

el("btBrancher").onclick = async () => {
  el("btBrancher").disabled = true;
  texte("etatBrancher", "Vérification auprès de Google…");
  try {
    const r = await fetch("/notebooklm/session", {method: "POST",
      headers: Object.assign({"Content-Type": "application/json"}, H),
      body: JSON.stringify({export: el("export").value})});
    const d = await r.json();
    if(!r.ok){ texte("etatBrancher", d.detail || "Refusé.", "ko"); return; }
    el("export").value = "";
    if(d.ok){ texte("etatBrancher", "Branché.", "ok"); await charger(); }
    else { texte("etatBrancher", d.message || "Google a refusé la session.", "ko"); }
  } finally { el("btBrancher").disabled = false; }
};

el("btOublier").onclick = async () => {
  await fetch("/notebooklm/oublier", {method: "POST", headers: H});
  await charger();
};

function suivre(id){
  fetch("/notebooklm/jobs/" + id, {headers: H}).then(r => r.json()).then(j => {
    if(j.status === "succeeded"){
      texte("etat", "✅ Résumé prêt.", "ok");
      montrer(j);
      el("btFabriquer").disabled = false;
      listerResumes();
      return;
    }
    if(j.status === "failed" || j.status === "cancelled"){
      texte("etat", "Échec : " + (j.message || "sans détail."), "ko");
      el("btFabriquer").disabled = false;
      if(j.plein){ ouvrirPlace(true); }
      listerResumes();
      return;
    }
    const t = Math.round(Date.now()/1000 - (j.created_at || Date.now()/1000));
    texte("etat", "⏳ " + (j.etape || "En file…") + " (depuis " + t + " s)");
    setTimeout(() => suivre(id), 4000);
  });
}

el("btFabriquer").onclick = async () => {
  const f = new FormData();
  for(const x of el("fichiers").files){ f.append("fichiers", x); }
  f.append("texte", el("texte").value);
  f.append("consigne", el("consigne").value);
  f.append("format", el("format").value);
  f.append("longueur", el("longueur").value);
  f.append("quand", quandFr(Date.now() / 1000));   // l'heure d'ici, pour le nom du carnet
  el("btFabriquer").disabled = true;
  el("resultat").hidden = true;
  texte("etat", "Envoi…");
  const r = await fetch("/notebooklm/resume", {method: "POST", headers: H, body: f});
  const d = await r.json();
  if(!r.ok){ texte("etat", d.detail || "Refusé.", "ko"); el("btFabriquer").disabled = false; return; }
  suivre(d.id);
};

el("btDemander").onclick = async () => {
  const q = el("question").value.trim();
  if(!q || !CARNET) return;
  const web = el("web").checked;
  texte("reponse", web ? "NotebookLM cherche sur le web, ajoute les pages trouvées au carnet, puis répond (1 à 3 minutes)…"
                       : "NotebookLM lit vos documents…");
  el("btDemander").disabled = true;
  let r, d;
  try {
    r = await fetch("/notebooklm/demander", {method: "POST",
      headers: Object.assign({"Content-Type": "application/json"}, H),
      body: JSON.stringify({carnet_id: CARNET, question: q, web: web})});
    d = await r.json();
  } catch(e) { d = {detail: "Le Studio ne répond pas."}; r = {ok: false}; }
  el("btDemander").disabled = false;
  if(!r.ok){ texte("reponse", d.detail || "Refusé.", "ko"); return; }
  const div = el("reponse");
  div.textContent = "";
  if(d.note){
    const n = document.createElement("p");
    n.className = "avert";
    n.textContent = d.note;
    div.appendChild(n);
  }
  markdown(div, d.reponse);
  for(const c of d.citations || []){
    const q2 = document.createElement("p");
    q2.className = "avert";
    q2.textContent = "[" + c.numero + "] « " + c.extrait + " »";
    div.appendChild(q2);
  }
  if((d.web || []).length){
    const t = document.createElement("p");
    t.textContent = "Pages du web ajoutées au carnet :";
    div.appendChild(t);
    const ul = document.createElement("ul");
    for(const s of d.web){
      const li = document.createElement("li");
      const a = document.createElement("a");
      a.textContent = s.titre;
      // Seules les adresses web deviennent des liens (jamais javascript: ou autre).
      if(/^https?:\/\//i.test(s.url)){ a.href = s.url; a.target = "_blank"; a.rel = "noopener noreferrer"; }
      li.appendChild(a);
      ul.appendChild(li);
    }
    div.appendChild(ul);
  }
};

// Deux sources : l'AAC de NotebookLM, puis la même chose en Opus. Un navigateur
// qui ne lirait pas l'AAC passe à la seconde (repli, voir version_opus).
function brancherSon(a, url){
  a.removeAttribute("src");
  a.textContent = "";
  for(const [suffixe, type] of [["", 'audio/mp4; codecs="mp4a.40.2"'],
                                ["&format=opus", 'audio/ogg; codecs="opus"']]){
    const s = document.createElement("source");
    s.src = url + suffixe; s.type = type;
    a.appendChild(s);
  }
  a.load();
}

// --- Vos résumés : ils restent là après un rechargement ---------------------
function montrer(j){
  el("resultat").hidden = false;
  brancherSon(el("lecteur"), j.audio_url);
  el("telecharger").href = j.audio_url + "&telecharger=1";
  el("carnet").href = j.carnet_url;
  CARNET = j.carnet_id;
  texte("reponse", "");
  el("resultat").scrollIntoView({behavior: "smooth"});
}
// Supprimer un résumé : le son, sa copie, vos documents et la fiche, ici.
// Le carnet chez Google reste (« Faire de la place » le supprime). Deux clics,
// comme sur /video : le premier demande, le second efface.
function boutonSupprimer(j){
  const b = document.createElement("button");
  const sage = "🗑️ Supprimer du Studio";
  b.textContent = sage;
  b.onclick = async () => {
    if(b.dataset.arme !== "1"){
      b.dataset.arme = "1";
      b.textContent = "Confirmer : effacer pour de bon";
      setTimeout(() => { b.dataset.arme = ""; b.textContent = sage; }, 5000);
      return;
    }
    b.disabled = true;
    const r = await fetch("/notebooklm/jobs/" + encodeURIComponent(j.id), {method: "DELETE", headers: H});
    const d = await r.json().catch(() => ({}));
    if(!r.ok){ b.disabled = false; b.textContent = "✖ " + (d.detail || ("HTTP " + r.status)); return; }
    if(CARNET && CARNET === j.carnet_id){ el("resultat").hidden = true; CARNET = null; }
    await listerResumes();
  };
  return b;
}

let SUIVI = false;
async function listerResumes(){
  const r = await fetch("/notebooklm/resumes", {headers: H});
  if(!r.ok) return;
  const liste = (await r.json()).resumes || [];
  const boite = el("resumes");
  boite.textContent = "";
  if(!liste.length){
    const vide = document.createElement("p");
    vide.className = "avert"; vide.textContent = "Aucun résumé pour l’instant.";
    boite.appendChild(vide);
    return;
  }
  for(const j of liste){
    const c = document.createElement("div");
    c.className = "carte";
    const t = document.createElement("div");
    const etat = j.status === "succeeded" ? "" : j.status === "failed" ? " — échec : " + (j.message || "")
      : " — en cours : " + (j.etape || "en file");
    t.textContent = (j.titre || "Résumé") + " — " + quandFr(j.created_at) + etat;
    c.appendChild(t);
    const l = document.createElement("div");
    l.className = "ligne";
    if(j.audio_url){
      const a = document.createElement("audio");
      // « metadata » : la durée s'affiche tout de suite, dès que le navigateur
      // a trouvé une source qu'il sait lire (voir brancherSon).
      a.controls = true; a.preload = "metadata";
      brancherSon(a, j.audio_url);
      c.appendChild(a);
      const dl = document.createElement("a");
      dl.href = j.audio_url + "&telecharger=1"; dl.textContent = "Enregistrer le fichier audio";
      const nb = document.createElement("a");
      nb.href = j.carnet_url; nb.target = "_blank"; nb.rel = "noopener noreferrer";
      nb.textContent = "Ouvrir le carnet dans NotebookLM ↗";
      const q = document.createElement("button");
      q.textContent = "Poser une question";
      q.onclick = () => montrer(j);
      // Une question passe par Google : sans session, le bouton n'aboutirait pas.
      l.append(dl, nb);
      if(SESSION_OK){ l.appendChild(q); }
    }
    if(j.status !== "queued" && j.status !== "running"){
      l.appendChild(boutonSupprimer(j));
    }
    c.appendChild(l);
    boite.appendChild(c);
    // Un résumé encore en cours après un rechargement : on le suit de nouveau.
    if(!SUIVI && (j.status === "queued" || j.status === "running")){
      SUIVI = true;
      el("btFabriquer").disabled = true;
      suivre(j.id);
    }
  }
}

// --- Faire de la place : la personne choisit, rien ne part seul --------------
function deux(n){ return (n < 10 ? "0" : "") + n; }
function quandFr(ts){
  if(!ts) return "";
  const d = new Date(ts * 1000);
  return deux(d.getDate()) + "/" + deux(d.getMonth() + 1) + "/" + d.getFullYear()
    + " " + deux(d.getHours()) + ":" + deux(d.getMinutes());
}
let CARNETS = [];
function coches(){ return Array.from(document.querySelectorAll("#listeCarnets input:checked")).map(x => x.value); }
function majSuppr(){
  const n = coches().length;
  el("btSupprimer").textContent = "Supprimer " + n + " carnet" + (n > 1 ? "s" : "") + " coché" + (n > 1 ? "s" : "");
  el("btSupprimer").disabled = !(n && el("confirmeSuppr").checked);
}
async function ouvrirPlace(plein){
  el("place").hidden = false;
  el("confirmeSuppr").checked = false;
  texte("etatSuppr", "");
  texte("placeTexte", "Lecture de vos carnets…");
  const r = await fetch("/notebooklm/carnets", {headers: H});
  const d = await r.json();
  if(!r.ok){ texte("placeTexte", d.detail || "Lecture impossible.", "ko"); return; }
  CARNETS = d.carnets;
  texte("placeTexte", (plein ? "Votre NotebookLM est plein. " : "")
    + CARNETS.length + " carnets à vous, du plus ancien au plus récent. Cochez ceux à supprimer.");
  const liste = el("listeCarnets");
  liste.textContent = "";
  for(const c of CARNETS){
    const l = document.createElement("label");
    l.style.display = "block";
    const b = document.createElement("input");
    b.type = "checkbox"; b.value = c.id; b.onchange = majSuppr;
    l.appendChild(b);
    l.appendChild(document.createTextNode(" " + c.titre + " — "
      + (c.cree ? quandFr(c.cree) : "date inconnue") + " — " + c.sources + " source(s)"));
    liste.appendChild(l);
  }
  if(plein){ el("nbAnciens").value = 10; cocherAnciens(); }
  majSuppr();
  el("place").scrollIntoView({behavior: "smooth"});
}
function cocherAnciens(){
  const n = Math.max(0, parseInt(el("nbAnciens").value, 10) || 0);
  // Seuls les carnets DATES : on ne propose pas ce qu'on ne sait pas dater.
  const boites = document.querySelectorAll("#listeCarnets input");
  boites.forEach((b, i) => { b.checked = i < n && !!CARNETS[i].cree; });
  majSuppr();
}
el("btPlace").onclick = () => ouvrirPlace(false);
el("btCocher").onclick = cocherAnciens;
el("btDecocher").onclick = () => { document.querySelectorAll("#listeCarnets input").forEach(b => b.checked = false); majSuppr(); };
el("confirmeSuppr").onchange = majSuppr;
el("btSupprimer").onclick = async () => {
  const ids = coches();
  if(!ids.length || !el("confirmeSuppr").checked) return;
  el("btSupprimer").disabled = true;
  texte("etatSuppr", "Suppression de " + ids.length + " carnet(s)…");
  const r = await fetch("/notebooklm/carnets/supprimer", {method: "POST",
    headers: Object.assign({"Content-Type": "application/json"}, H),
    body: JSON.stringify({ids: ids, confirme: true})});
  const d = await r.json();
  if(!r.ok){ texte("etatSuppr", d.detail || "Refusé.", "ko"); majSuppr(); return; }
  await ouvrirPlace(false);
  texte("etatSuppr", d.supprimes.length + " carnet(s) supprimé(s)"
    + (d.refuses.length ? ", " + d.refuses.length + " non supprimé(s)" : "") + ".", d.refuses.length ? "ko" : "ok");
};

charger();
</script>
</body></html>
"""
