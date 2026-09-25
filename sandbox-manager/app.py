from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Dict, Optional

import httpx
from fastapi import FastAPI, File, Header, HTTPException, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field

import budget_modal
import chanson
# Le magasin de secrets garde les NOMS en clair et les VALEURS non. Ce qui a
# mordu le 22/09/2026 : un filtre de lecture sur la configuration a emporte les
# jetons Modal. Ce que cela ne ferme PAS est dit en tete du module.
import coffre
# Le carnet Colab ouvert dans le navigateur de la personne, pilote par
# cellules (PLAN.md 17.4). Rien n'y tourne sur cet ordinateur.
import colab_pont
import composite
import depenses
# Les derniers travaux de /video, /chanson et /dialogue : une page rechargee
# retrouve ce qu'elle suivait (friction du 23/09/2026).
import derniers
import dialogue
# Les montants et les dates s'ecrivent en francais -- virgule decimale, date en
# jour/mois/annee -- des deux cotes : ici en Python, et dans le JavaScript des
# pages via `format_fr.avec_formateurs`.
import format_fr
import garde_exposition
# Que faire d'un travail qu'un redemarrage a laisse sans personne
# derriere lui. Le raisonnement y est pur : il se teste sans reseau.
import reprise
# La sonde de la carte. Elle ne leve jamais : `vue` dit si une carte a ete
# MESUREE, `motif` dit pourquoi quand elle ne l'a pas ete. C'est ce qui permet
# a /essai de demander au lieu d'affirmer (releve du proprietaire, 20/09/2026).
import gpu_local
# Nettoyage du rendu de /dialogue. Au niveau du module, PAS au moment de
# l'appel : le Dockerfile prend tout le dossier (COPY *.py), donc un module
# absent serait une erreur de livraison, pas un alea d'execution -- et elle doit
# tomber bruyamment au demarrage plutot que degrader en silence un nettoyage
# annonce comme systematique. Bibliotheque standard seulement, rien a installer.
import nettoyage_dialogue
# NotebookLM par notebooklm-py : session Google fermee dans le coffre
# (PLAN.md 17.6). La bibliotheque elle-meme n'est chargee qu'a l'usage.
import notebooklm_pont
import ou_calculer
import poids_video
import video

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("sandbox-manager")

app = FastAPI(title="Free AI Studio Sandbox Manager", version="2.0.0")

KEY = os.getenv("SANDBOX_MANAGER_KEY", "").strip()
WORKER_KEY = os.getenv("SANDBOX_WORKER_KEY", "").strip()
WORKER_URL = os.getenv("SANDBOX_WORKER_URL", "http://sandbox-worker:8000").rstrip("/")
# Le bac a sable de la MAISON : le meme code, sur la carte graphique. Il
# n'existe que si la surcouche docker-compose.gpu.yml a ete appliquee, donc
# seulement si la machine a une carte. Vide = pas de carte, et le routage part
# chez Modal comme avant ce chantier.
WORKER_GPU_URL = os.getenv("SANDBOX_WORKER_GPU_URL", "").rstrip("/")
# /workspace dans le conteneur ; configurable pour charger le service hors
# conteneur (CI : scripts/verifier-imports.py, tests/).
ROOT = Path(os.getenv("SANDBOX_WORKSPACE", "/workspace"))
JOBS = ROOT / "jobs"
ART = ROOT / "artifacts"
JOBS.mkdir(parents=True, exist_ok=True)
ART.mkdir(parents=True, exist_ok=True)

# Le worker execute le code utilisateur sous un compte non privilegie (USER sandbox,
# uid 10001 dans sandbox-worker/Dockerfile) et partage ce volume avec le manager, qui
# tourne en root. Sans transfert de propriete, le worker ne peut ni ecrire main.py ni
# creer <job>/output dans un repertoire cree par le manager : POST /run rend 500.
WORKER_UID = int(os.getenv("SANDBOX_WORKER_UID", "10001"))

MAX_UPLOAD = int(os.getenv("SANDBOX_MAX_ARTIFACT_BYTES", str(100 * 1024 * 1024)))
MAX_JOB_CODE = int(os.getenv("SANDBOX_MAX_CODE_BYTES", "500000"))
MAX_OUTPUT = int(os.getenv("SANDBOX_MAX_OUTPUT_BYTES", "200000"))
COLAB_API_ENABLED = os.getenv("COLAB_API_ENABLED", "false").lower() == "true"

# --- Kaggle automatique : identifiants personnels, machine personnelle --------
# run_kaggle pousse du code sur Kaggle avec LES identifiants de la personne qui
# les a saisis. Sur son ordinateur, pour elle seule, c'est le but. Des qu'un
# Studio sert d'autres personnes, leurs calculs partiraient sur ce compte-la : le
# Sandbox coupe alors Kaggle automatique et ne laisse que le lien manuel.
# Ces signes sont des indices, pas une preuve : une instance exposee par un moyen
# qui n'en laisse aucun doit etre declaree avec STUDIO_HEBERGE=true.
STUDIO_HEBERGE = os.getenv("STUDIO_HEBERGE", "false").strip().lower() == "true"
MULTI_UTILISATEUR = os.getenv("WEBUI_AUTH", "false").strip().lower() == "true"
HOTES_LOCAUX = {"localhost", "127.0.0.1", "::1"}
KAGGLE_MANUEL = "https://www.kaggle.com/code"


def contexte_partage(request: Optional[Request] = None) -> Optional[str]:
    """La raison de couper Kaggle automatique, ou None sur un Studio personnel.

    19/09/2026 : la premiere branche n'est plus atteignable a l'import. Un
    STUDIO_HEBERGE=true fait desormais REFUSER le demarrage de ce service
    (garde_exposition.py) parce qu'il ecrit ses jetons en clair -- couper Kaggle
    ne suffisait pas. Elle reste ecrite et testee : elle reprendra du service le
    jour ou les cles seront chiffrees et le refus rouvert. Les deux autres
    branches, elles, sont vivantes.
    """
    if STUDIO_HEBERGE:
        return "STUDIO_HEBERGE=true : instance declaree hebergee"
    if MULTI_UTILISATEUR:
        return "WEBUI_AUTH=true : le Studio a plusieurs comptes"
    if request is None:
        return None
    if request.headers.get("x-forwarded-for") or request.headers.get("forwarded"):
        return "requete relayee par un proxy"
    hote = (request.url.hostname or "").strip("[]").lower()
    if hote not in HOTES_LOCAUX:
        return "page ouverte par l'adresse %s, pas par localhost" % hote
    return None


def refus_kaggle(raison: str) -> HTTPException:
    return HTTPException(
        403,
        "Kaggle automatique est coupe ici (%s) : il utiliserait les identifiants Kaggle "
        "personnels du proprietaire de cette machine. Ouvrez Kaggle vous-meme : %s"
        % (raison, KAGGLE_MANUEL),
    )

# --- Magasin de secrets ecrit par la page /cles ------------------------------
# Meme raison que cote routeur de chat : les variables arrivent par le compose au
# moment de la CREATION du conteneur, donc un jeton ajoute dans .env n'agit pas a
# chaud. Ce magasin est relu a chaud, ce qui permet de brancher Modal ou Kaggle
# depuis le navigateur, sans terminal.
CONFIG_DIR = Path(os.getenv("FREE_AI_CONFIG_DIR", "/config"))
KEYS_FILE = CONFIG_DIR / "sandbox-keys.json"
notebooklm_pont.regler(CONFIG_DIR)

# Meme refus que cote routeur, et pour la meme raison : ce magasin-ci tient les
# jetons Modal et les identifiants Kaggle, en clair. Le paragraphe 2.1 du plan ne
# nommait que config/keys.json ; il y en a DEUX, releve le 19/09/2026.
garde_exposition.verifier_ou_refuser(str(KEYS_FILE))
SECRET_NAMES = ("MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET", "KAGGLE_USERNAME", "KAGGLE_KEY")

# Photographie de l'environnement AVANT toute injection du magasin : sert a
# distinguer ce qui vient de .env (que l'interface ne doit pas pouvoir effacer)
# de ce qu'elle a elle-meme pose.
ENV_SECRETS = {name: os.getenv(name, "").strip() for name in SECRET_NAMES}

# Ce que le debutant doit comprendre de chaque backend, et ou aller chercher les
# identifiants. Les liens sont les pages officielles, pas des raccourcis maison.
SANDBOX_HELP = {
    "modal": {
        "titre": "Modal — machine distante",
        "role": "Prete un ordinateur puissant (CPU ou GPU) quand le votre ne suffit pas. Offre gratuite mensuelle, puis payant.",
        "url": "https://modal.com/settings/tokens",
        "repere": "Creez un compte, puis « New token ». Vous obtenez DEUX valeurs : un identifiant (ak-...) et un secret (as-...).",
        "champs": [
            {"nom": "MODAL_TOKEN_ID", "libelle": "Identifiant du jeton (ak-...)"},
            {"nom": "MODAL_TOKEN_SECRET", "libelle": "Secret du jeton (as-...)"},
        ],
    },
    "kaggle": {
        "titre": "Kaggle — GPU gratuit",
        "role": "GPU gratuit par tranches horaires, pour les travaux longs. Aucune facturation possible. "
                "Pilotage automatique reserve a votre machine, avec vos identifiants.",
        "url": "https://www.kaggle.com/settings",
        "repere": "Section « API », bouton « Create New Token » : un fichier kaggle.json se telecharge, contenant username et key.",
        "champs": [
            {"nom": "KAGGLE_USERNAME", "libelle": "Nom d'utilisateur Kaggle"},
            {"nom": "KAGGLE_KEY", "libelle": "Cle d'API (champ « key » du fichier)"},
        ],
    },
}


class JobRequest(BaseModel):
    provider: str = Field(default="auto", pattern="^(auto|modal|local|kaggle|colab)$")
    code: str = Field(min_length=1)
    title: str = "Free AI Studio job"
    gpu: bool = False
    internet: bool = False


class BackendUnavailable(RuntimeError):
    """Infrastructure/configuration failure where a fallback is appropriate."""


def auth(value: Optional[str]):
    if not KEY or value != f"Bearer {KEY}":
        raise HTTPException(401, "Unauthorized")


REFUS_AUTRE_SITE = ("Cette demande ne vient pas d'une page du Studio : refusee. "
                    "Ouvrez la page du Studio et recommencez.")


def exiger_page_du_studio(request) -> None:
    """Un bouton des pages du Sandbox, pas une page d'un autre site (16/09/2026).

    Les routes des cles n'ont pas de mot de passe : elles servent les pages
    ouvertes sur cet ordinateur. Sans cette garde, un site visite pouvait
    effacer les identifiants Modal ou Kaggle. Le navigateur dit d'ou vient la
    demande, et une page ne peut pas mentir sur ces deux en-tetes."""
    venue_de = request.headers.get("sec-fetch-site", "").strip().lower()
    if venue_de and venue_de not in ("same-origin", "none"):
        raise HTTPException(403, REFUS_AUTRE_SITE)
    origine = request.headers.get("origin", "").strip()
    if origine and origine.split("//", 1)[-1] != request.headers.get("host", ""):
        raise HTTPException(403, REFUS_AUTRE_SITE)


def exiger_json(request) -> None:
    """JSON exige : un autre site ne peut pas en envoyer sans une verification
    prealable du navigateur, que le Sandbox n'accepte pas."""
    if not request.headers.get("content-type", "").startswith("application/json"):
        raise HTTPException(415, "JSON attendu")


def clean_name(name: str) -> str:
    name = Path(name).name
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)[:180] or "artifact.bin"


def meta_path(jid: str) -> Path:
    return JOBS / jid / "job.json"


def read_job(jid: str) -> dict:
    p = meta_path(jid)
    if not p.exists():
        raise HTTPException(404, "Unknown job")
    return json.loads(p.read_text(encoding="utf-8"))


# Travaux effaces depuis la page alors qu'un fil les suivait encore. Sans
# cette liste, le fil reecrirait sa fiche a la fin -- write_job recree le
# dossier -- et le travail efface reviendrait dans << Vos travaux >>. En
# memoire seulement : les fils meurent avec le processus.
SUPPRIMES: set = set()


def write_job(jid: str, data: dict):
    if jid in SUPPRIMES:
        return
    d = JOBS / jid
    created = not d.exists()
    d.mkdir(parents=True, exist_ok=True)
    if created:
        # Le groupe reste inchange (-1) : le proprietaire suffit, et cela evite de
        # coder en dur le gid que useradd attribue dans l'image du worker.
        try:
            os.chown(d, WORKER_UID, -1)
        except OSError as exc:
            log.warning("chown %s -> uid %s impossible : %s", d, WORKER_UID, exc)
    tmp = d / "job.json.tmp"
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(meta_path(jid))


def truncate(value: str) -> str:
    raw = value.encode("utf-8", errors="replace")
    if len(raw) <= MAX_OUTPUT:
        return value
    return raw[:MAX_OUTPUT].decode("utf-8", errors="replace") + "\n[output truncated]"


def add_artifact(jid: str, path: Path, source: str) -> dict:
    if jid in SUPPRIMES:
        return {"name": path.name, "job_id": jid, "source": source,
                "skipped": True, "reason": "job_deleted"}
    if path.is_symlink() or not path.is_file():
        raise ValueError("Artifact must be a regular file")
    size = path.stat().st_size
    if size > MAX_UPLOAD:
        return {
            "name": path.name,
            "size": size,
            "job_id": jid,
            "source": source,
            "skipped": True,
            "reason": "artifact_too_large",
        }
    aid = uuid.uuid4().hex
    dest = ART / f"{aid}--{clean_name(path.name)}"
    shutil.copy2(path, dest)
    info = {
        "id": aid,
        "name": path.name,
        "size": dest.stat().st_size,
        "job_id": jid,
        "source": source,
        "created_at": time.time(),
        "path": dest.name,
    }
    (ART / f"{aid}.json").write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
    return info


def _magasin_brut() -> Dict[str, str]:
    """Le fichier tel qu'il est : valeurs FERMEES depuis le 22/09/2026."""
    try:
        data = json.loads(KEYS_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        log.warning("magasin de secrets illisible (%s) : %s", KEYS_FILE, exc)
        return {}
    return {k: v for k, v in data.items() if isinstance(v, str)}


def _ecrire_le_magasin(data: Dict[str, str]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(data, indent=2)
    tmp = CONFIG_DIR / "sandbox-keys.json.tmp"
    try:
        tmp.write_text(blob, encoding="utf-8")
        tmp.replace(KEYS_FILE)
    except OSError:
        KEYS_FILE.write_text(blob, encoding="utf-8")
    try:
        KEYS_FILE.chmod(0o600)
    except OSError:
        pass


def stored_keys() -> Dict[str, str]:
    """Les secrets EN CLAIR, pour le code qui en a besoin -- le SDK Modal et la
    CLI Kaggle lisent l'environnement, il faut bien leur donner la valeur.

    Le FICHIER, lui, ne les porte plus en clair : `coffre.py`. Une valeur que la
    cle presente n'ouvre pas est ecartee et dite, jamais devinee."""
    return coffre.ouvrir_le_magasin(_magasin_brut())


def store_key(name: str, value: str) -> None:
    """Ecrit un secret, FERME. Sans cle de coffre, `coffre.chiffrer` leve et rien
    n'est ecrit : retomber en clair << juste cette fois >> serait le defaut du
    22/09 refait en silence."""
    data = _magasin_brut()
    if value:
        data[name] = coffre.chiffrer(value)
    else:
        data.pop(name, None)
    _ecrire_le_magasin(data)
    apply_stored_secrets()


def migrer_le_magasin() -> bool:
    """Ferme en place un magasin d'avant le coffre. Rend True s'il a bouge.

    Tout se construit en memoire AVANT la moindre ecriture : si le chiffrement
    echoue, le fichier d'origine n'est pas touche. Sans cle, on laisse en clair
    et on le DIT -- effacer les cles de quelqu'un pour les proteger serait une
    reparation qui coute plus que le defaut."""
    brut = _magasin_brut()
    if not coffre.doit_migrer(brut):
        return False
    try:
        ferme = coffre.fermer_ce_qui_est_en_clair(brut)
    except coffre.CoffreSansCle as exc:
        log.warning("magasin laisse EN CLAIR, faute de cle de coffre : %s", exc)
        return False
    _ecrire_le_magasin(ferme)
    log.info("magasin de secrets ferme (%d valeur(s))", len(ferme))
    return True


def apply_stored_secrets() -> None:
    """Recopie les secrets du magasin dans l'environnement du processus, sans
    jamais ecraser une variable deja posee par .env.

    Le SDK Modal et la CLI Kaggle lisent leurs identifiants dans l'environnement.
    Passer par lui evite de reecrire chacun de leurs points d'appel, et garde
    une regle de priorite unique : .env d'abord, magasin ensuite."""
    for name, value in stored_keys().items():
        if value and not os.getenv(name, "").strip():
            os.environ[name] = value


def forget_secrets(names) -> None:
    """Retire les secrets du magasin ET de l'environnement du processus.

    Sans le second geste, le backend resterait actif jusqu'au prochain
    redemarrage du conteneur : apply_stored_secrets() a deja recopie la valeur
    dans os.environ. Une valeur venue de .env est restauree telle quelle : elle
    n'appartient pas a l'interface, qui ne doit pas pouvoir l'effacer."""
    for name in names:
        store_key(name, "")
        depuis_env = ENV_SECRETS.get(name, "")
        if depuis_env:
            os.environ[name] = depuis_env
        else:
            os.environ.pop(name, None)


def mask(value: str) -> str:
    """Ne rend jamais le secret : juste de quoi le reconnaitre."""
    return ("*" * 6 + value[-4:]) if len(value) >= 8 else "*" * 8


def poses_a_la_main_dans_le_env(*noms: str) -> bool:
    """Ces identifiants viennent-ils du .env, et de lui seul ? (22/09/2026)

    ENV_SECRETS est la photographie prise AVANT toute injection du magasin :
    c'est le seul endroit qui distingue << ecrit a la main dans .env >> de
    << pose par l'interface >>. Sans ce bras, les deux interrupteurs ci-dessous
    ne reconnaissaient qu'un jeton passe par l'interface. Un jeton ecrit dans
    .env, avec MODAL_ENABLED=false comme le depot le livre, donnait un Studio
    qui repond << non configure >> avec des identifiants valides sous la main --
    et vider le magasin de jetons REVOQUES eteignait le backend que .env tenait.
    """
    return all(ENV_SECRETS.get(nom, "").strip() for nom in noms)


def modal_enabled() -> bool:
    if os.getenv("MODAL_ENABLED", "false").strip().lower() == "true":
        return True
    # MODAL_ENABLED=false protege une installation fraiche d'un usage cloud
    # accidentel. Coller un jeton dans l'interface est tout sauf accidentel :
    # cet acte vaut activation, et le bouton << Oublier >> la revoque.
    # L'ecrire a la main dans .env ne l'est pas davantage : meme motif, meme
    # conclusion.
    if poses_a_la_main_dans_le_env("MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET"):
        return True
    keys = stored_keys()
    return bool(keys.get("MODAL_TOKEN_ID") and keys.get("MODAL_TOKEN_SECRET"))


def kaggle_enabled() -> bool:
    if os.getenv("KAGGLE_ENABLED", "false").strip().lower() == "true":
        return True
    if poses_a_la_main_dans_le_env("KAGGLE_USERNAME", "KAGGLE_KEY"):
        return True
    keys = stored_keys()
    return bool(keys.get("KAGGLE_USERNAME") and keys.get("KAGGLE_KEY"))


def modal_configured() -> bool:
    return modal_enabled() and bool(os.getenv("MODAL_TOKEN_ID", "").strip()) and bool(
        os.getenv("MODAL_TOKEN_SECRET", "").strip()
    )


def kaggle_configured() -> bool:
    return kaggle_enabled() and bool(os.getenv("KAGGLE_USERNAME", "").strip()) and bool(
        os.getenv("KAGGLE_API_TOKEN", "").strip() or os.getenv("KAGGLE_KEY", "").strip()
    )


# L'ordre du mode << auto >>. Ordre du proprietaire, 23/09/2026 : << local
# first before modal if ressources available >>. Le bac a sable local tourne sur
# processeur, sans Internet : il a la ressource d'un job qui ne demande ni carte
# ni reseau, et celui-la part donc ici d'abord, gratuitement. Un job qui demande
# une carte SANS Internet part sur la carte d'ici quand elle est libre
# (`ou_lancer_essai`, la meme sonde que le mode << local >>) : le bac a sable GPU
# ne lit plus le cache des modeles qu'en LECTURE SEULE (docker-compose.gpu.yml,
# decision du proprietaire du 23/09, option a). Un job qui demande Internet garde
# Modal en tete : aucun bac a sable d'ici n'a de reseau.
ORDRE_AUTO = ["modal", "local", "kaggle", "colab"]
ORDRE_AUTO_LOCAL_D_ABORD = ["local", "modal", "kaggle", "colab"]
ORDRE_AUTO_CARTE_D_ICI = ["maison", "modal", "local", "kaggle", "colab"]


def ordre_auto(gpu: bool, internet: bool) -> list[str]:
    if internet:
        return list(ORDRE_AUTO)
    return list(ORDRE_AUTO_CARTE_D_ICI if gpu else ORDRE_AUTO_LOCAL_D_ABORD)


def backend_automatique() -> str:
    """Ou part un job << auto >> ordinaire (ni carte, ni Internet) : ici. Kaggle
    n'est jamais la destination ordinaire, meme configure : il ne recoit que
    des jobs GPU, et apres Modal et le worker local."""
    return "local"


def backend_carte_ou_internet() -> str:
    """Ou part d'abord un job << auto >> qui demande Internet -- ou une carte,
    quand celle d'ici est occupee ou absente."""
    return "modal" if modal_configured() else "local"


# Au demarrage, DANS CET ORDRE : fermer d'abord ce qui traine en clair, puis
# rendre actif ce qui a ete saisi lors d'une session precedente. L'inverse
# laisserait une fenetre ou le magasin est encore lisible par un filtre.
migrer_le_magasin()
apply_stored_secrets()

# Puis, DANS UN FIL, le compteur Modal va chercher le vrai chiffre une fois.
# Sans cela il garde l'estimation locale jusqu'a la premiere depense, et le
# premier refus d'apres redemarrage se decide sur un nombre trop petit -- mesure
# le 20/09/2026 : `lire()` rendait encore 1,3878 $ alors que Modal en comptait
# 3,7971. Dans un fil parce que le releve dure environ 0,85 s quand Modal repond
# et jusqu'au delai d'attente quand il ne repond pas : le demarrage n'attend
# jamais un service distant. apply_stored_secrets() a deja pose le jeton, et si
# rien ne repond amorcer() rend None sans rien ecrire.
# Coupee sous test, comme la reprise : la suite charge ce module des dizaines de
# fois, et un fil parti a un chargement lancait le VRAI `modal billing` pendant
# le test suivant, puis ecrivait sa reponse dans le cache des depenses que ce
# test venait de vider (23/09/2026, test_sans_jeton_rien_n_est_lance).
if os.getenv("SANDBOX_AMORCE_BUDGET", "true").strip().lower() not in ("0", "false", "non"):
    threading.Thread(target=budget_modal.amorcer, name="amorce-budget",
                     daemon=True).start()


def collect_local_artifacts(jid: str, source: str) -> list[dict]:
    out = JOBS / jid / "output"
    arts: list[dict] = []
    if out.exists():
        for p in out.rglob("*"):
            if p.is_file() and not p.is_symlink():
                arts.append(add_artifact(jid, p, source))
    return arts


def local_execute(jid: str, code: str) -> dict:
    try:
        with httpx.Client(timeout=int(os.getenv("SANDBOX_TIMEOUT_SECONDS", "120")) + 30) as c:
            r = c.post(
                WORKER_URL + "/run",
                headers={"Authorization": f"Bearer {WORKER_KEY}"},
                json={"job_id": jid, "code": code},
            )
            r.raise_for_status()
            data = r.json()
    except Exception as exc:
        raise BackendUnavailable(f"Local worker unavailable: {type(exc).__name__}: {exc}") from exc
    data["artifacts"] = collect_local_artifacts(jid, "local")
    return data


def maison_execute(jid: str, code: str, secondes: int | None = None) -> dict:
    """Le meme appel que local_execute, vers le bac a sable qui a la carte.

    Deux differences, toutes les deux mesurees le 19/09/2026 :
      - l'attente. Un clip de 3 s a demande 412 s de calcul plus 24 s de
        chargement du modele ; le PREMIER clip ajoute le telechargement des
        34 Go. D'ou VIDEO_TIMEOUT_SECONDS (2400 s par defaut) et non les 120 s
        du bac a sable sur processeur ;
      - la source ecrite dans la fiche du fichier : << maison >>, pour que la
        page sache dire d'ou vient le clip.
    """
    if not WORKER_GPU_URL:
        raise BackendUnavailable("Aucun bac a sable GPU : la surcouche docker-compose.gpu.yml n'est pas appliquee.")
    # `secondes` RACCOURCIT, jamais ne rallonge : le bac a sable plafonne de
    # son cote, et la video garde ses 2 400 s en ne demandant rien.
    plafond = int(os.getenv("VIDEO_TIMEOUT_SECONDS", "2400"))
    demande = plafond if secondes is None else max(1, min(plafond, int(secondes)))
    attente = demande + 60
    try:
        with httpx.Client(timeout=attente) as c:
            r = c.post(
                WORKER_GPU_URL + "/run",
                headers={"Authorization": f"Bearer {WORKER_KEY}"},
                json={"job_id": jid, "code": code, "secondes": demande},
            )
            r.raise_for_status()
            data = r.json()
    except Exception as exc:
        raise BackendUnavailable(f"Maison worker unavailable: {type(exc).__name__}: {exc}") from exc
    data["artifacts"] = collect_local_artifacts(jid, "maison")
    return data


def modal_execute(
    jid: str,
    code: str,
    gpu: bool,
    internet: bool,
    *,
    gpu_type: Optional[str] = None,
    timeout_s: Optional[int] = None,
    memory_mb: Optional[int] = None,
    paquets: Optional[tuple] = None,
    apt: Optional[tuple] = None,
    commandes: Optional[tuple] = None,
    volume: Optional[str] = None,
    point_de_montage: str = "/modeles",
    usage: Optional[str] = "autonome",
) -> dict:
    """Execute du code sur une machine Modal.

    Les arguments nommes ne servent qu'aux travaux lourds (la video). Sans eux,
    le comportement est exactement celui d'avant. Ils permettent de demander une
    carte plus grosse, un delai plus long, une image ou les bibliotheques sont
    deja installees, des commandes de construction pour les depots que pip
    n'installe pas correctement, et un disque persistant ou garder les modeles
    telecharges d'un clip a l'autre.

    `usage` dit QUI paie, et son defaut est deliberement le bac a sable.
    Jusqu'au 19/09/2026, cette fonction etait le QUATRIEME depensier Modal du
    Studio, et le seul que personne ne comptait : run_auto() met << modal >>
    en tete de son ordre de repli, donc tout code envoye au bac a sable
    partait sur une carte louee a cote des trois compteurs. La video, la
    chanson et le dialogue, eux, comptent DEJA avant et apres leur appel --
    ils passent donc usage=None pour ne pas etre comptes deux fois.

    Le defaut va dans le sens du refus : un appelant qui oublie ce parametre
    est compte, il n'echappe pas au plafond. C'est l'inverse qui avait cours.

    CE QUE CE CHOIX SIMPLIFIE, et qu'il faut savoir : la meme route sert a un
    agent et a une personne qui envoie du code depuis la page. Le service ne
    sait pas les distinguer, donc les deux sont comptes sur << autonome >> et
    peuvent entamer la part reservee. C'est un defaut connu et ecrit, la ou
    l'etat d'avant etait de ne rien compter du tout.
    """
    if not modal_configured():
        raise BackendUnavailable("Modal is not configured")
    try:
        import modal
    except Exception as exc:
        raise BackendUnavailable(f"Modal SDK unavailable: {exc}") from exc

    timeout = timeout_s or max(1, int(os.getenv("MODAL_JOB_TIMEOUT_SECONDS", os.getenv("SANDBOX_TIMEOUT_SECONDS", "120"))))
    cleanup_grace = max(15, int(os.getenv("MODAL_CLEANUP_GRACE_SECONDS", "60")))
    sandbox_lifetime = timeout + cleanup_grace
    # Le delai d'inactivite est un filet contre une machine oubliee si CE service
    # meurt en cours de route. Il ne doit jamais etre plus court que le travail
    # lui-meme : la documentation de Modal ne dit pas si un calcul de vingt
    # minutes, qui n'echange rien pendant ce temps, compte comme inactif. Dans le
    # doute, on ne parie pas la reussite du clip dessus -- le vrai plafond reste
    # la duree absolue ci-dessus, qui, elle, est sans ambiguite.
    idle_timeout = max(1, int(os.getenv("MODAL_IDLE_TIMEOUT_SECONDS", "60")))
    if idle_timeout < sandbox_lifetime and timeout_s:
        idle_timeout = sandbox_lifetime
    cpu = float(os.getenv("MODAL_CPU", "1.0"))
    memory = memory_mb or int(os.getenv("MODAL_MEMORY_MB", "2048"))
    gpu_name = (gpu_type or os.getenv("MODAL_GPU_DEFAULT", "T4")).strip() if gpu else None
    app_name = os.getenv("MODAL_APP_NAME", "free-ai-studio-sandbox").strip() or "free-ai-studio-sandbox"

    # REFUSER AVANT DE LOUER. Le pire cas, c'est la machine qui va jusqu'au
    # bout de son delai sans rien rendre : c'est le seul chiffre honnete ici,
    # et il se calcule sur la carte et la memoire reellement demandees. Un
    # travail sans carte ne paie que le processeur et la memoire, ce que
    # budget_modal.prix_seconde() sait faire -- le compter au prix d'un H100
    # refuserait les travaux les moins chers du service.
    if usage:
        budget_modal.verifier(usage, gpu_name, sandbox_lifetime, memory,
                              quoi="Ce travail sur Modal")
    sb = None
    loue_depuis = None
    local_out = JOBS / jid / "modal-output"
    local_out.mkdir(parents=True, exist_ok=True)

    try:
        modal_app = modal.App.lookup(app_name, create_if_missing=True)
        image = modal.Image.debian_slim(python_version="3.12")
        if apt:
            image = image.apt_install(*apt)
        if paquets:
            # Modal garde l'image construite en cache : PyTorch n'est telecharge
            # qu'une fois, pas a chaque clip. La construction est facturee en
            # temps processeur, pas en temps de carte graphique.
            image = image.pip_install(*paquets)
        if commandes:
            # Pourquoi des commandes et pas seulement des paquets : certains
            # depots ne s'installent PAS correctement par pip, et le cas qui a
            # impose ce parametre est instructif. FireRedTTS-2 a un setup.py
            # reduit a find_packages(), et son sous-dossier fireredtts2/utils/
            # n'a PAS de __init__.py. find_packages() ne le voit donc pas, et
            # << pip install git+... >> livre un paquet AMPUTE : le travail meurt
            # sur ModuleNotFoundError: No module named 'fireredtts2.utils'.
            # Leurs auteurs ne peuvent pas voir ce trou : leur procedure est
            # << pip install -e . >> depuis un clone, et un editable met
            # l'arborescence entiere sur le sys.path, __init__.py ou pas.
            # Reproduire une procedure d'installation demande d'executer des
            # commandes ; l'approcher avec une liste de paquets est un pari.
            # Ces commandes tournent APRES pip_install, et l'ordre compte :
            # une version epinglee ci-dessus satisfait un requirements.txt sans
            # version, donc elle survit. L'inverse la remonterait en silence.
            image = image.run_commands(*commandes)
        volumes = {}
        if volume:
            volumes[point_de_montage] = modal.Volume.from_name(volume, create_if_missing=True)
        # A partir d'ici une machine est louee : le compteur encaissera le
        # temps passe, meme si la suite echoue.
        loue_depuis = time.time()
        sb = modal.Sandbox.create(
            "sleep",
            str(sandbox_lifetime),
            app=modal_app,
            image=image,
            timeout=sandbox_lifetime,
            idle_timeout=idle_timeout,
            cpu=cpu,
            memory=memory,
            gpu=gpu_name,
            block_network=not internet,
            volumes=volumes,
            tags={"free-ai-studio-job": jid},
        )
        sb.filesystem.make_directory("/tmp/free_ai_output")
        sb.filesystem.write_text(code, "/tmp/free_ai_job.py")
        proc = sb.exec(
            "python",
            "/tmp/free_ai_job.py",
            timeout=timeout,
            env={"FREE_AI_OUTPUT_DIR": "/tmp/free_ai_output"},
        )
        exit_code = proc.wait()
        stdout = truncate(proc.stdout.read() or "")
        stderr = truncate(proc.stderr.read() or "")

        # Ask Python in the remote sandbox to enumerate output paths safely as JSON.
        manifest_proc = sb.exec(
            "python",
            "-c",
            "import json,os; r='/tmp/free_ai_output'; print(json.dumps([os.path.join(dp,f) for dp,_,fs in os.walk(r) for f in fs]))",
            timeout=30,
        )
        manifest_code = manifest_proc.wait()
        paths = []
        if manifest_code == 0:
            try:
                paths = json.loads(manifest_proc.stdout.read() or "[]")
            except Exception:
                paths = []
        arts: list[dict] = []
        for idx, remote_path in enumerate(paths[:1000]):
            try:
                rel = str(remote_path).removeprefix("/tmp/free_ai_output/")
                safe = clean_name(rel.replace("/", "__"))
                target = local_out / f"{idx:04d}-{safe}"
                sb.filesystem.copy_to_local(str(remote_path), target)
                arts.append(add_artifact(jid, target, "modal"))
            except Exception as exc:
                arts.append({"name": str(remote_path), "source": "modal", "skipped": True, "reason": str(exc)[:300]})

        return {
            "exit_code": int(exit_code),
            "timed_out": False,
            "stdout": stdout,
            "stderr": stderr,
            "artifacts": arts,
            "remote_ref": getattr(sb, "object_id", None),
            "gpu": gpu_name,
        }
    except Exception as exc:
        # A process exit is returned above; exceptions here are treated as infrastructure failures.
        raise BackendUnavailable(f"Modal unavailable: {type(exc).__name__}: {str(exc)[:800]}") from exc
    finally:
        if usage and loue_depuis is not None:
            # Meme si le travail a echoue : la carte a ete louee pendant ce
            # temps-la. Ne compter que les reussites donnerait un compteur
            # menteur -- c'est deja la regle des trois autres usages.
            try:
                budget_modal.consommer(usage, gpu_name,
                                       time.time() - loue_depuis, memory)
            except Exception:
                # Un compteur qui ne sait pas s'ecrire ne doit pas faire perdre
                # le resultat d'un calcul qui, lui, a abouti.
                log.exception("budget Modal : encaissement impossible")
        if sb is not None:
            # Release cloud resources (including any GPU reservation) as soon as
            # stdout/stderr and artifacts have been collected. wait=True makes
            # cleanup deterministic before this function returns. Modal's
            # idle_timeout and absolute timeout remain server-side safety nets.
            try:
                sb.terminate(wait=True)
            except Exception:
                try:
                    sb.terminate(wait=False)
                except Exception:
                    pass


def finish_execution(jid: str, effective_provider: str, data: dict, attempts: list[dict] | None = None):
    job = read_job(jid)
    exit_code = int(data.get("exit_code", 1))
    # Un calcul tue par le bouton d'arret finit en erreur : c'est la preuve de
    # l'arret, pas un echec (meme lecon que terminer_en_echec, 17/09).
    arrete = bool(job.get("arret_demande")) and exit_code != 0
    job.update(
        {
            "provider_effective": effective_provider,
            "status": "cancelled" if arrete else "succeeded" if exit_code == 0 else "failed",
            "finished_at": time.time(),
            "exit_code": exit_code,
            "timed_out": bool(data.get("timed_out", False)),
            "stdout": data.get("stdout", ""),
            "stderr": data.get("stderr", ""),
            "artifacts": data.get("artifacts", []),
        }
    )
    if data.get("remote_ref"):
        job["remote_ref"] = data["remote_ref"]
    if data.get("gpu"):
        job["remote_gpu"] = data["gpu"]
    if attempts is not None:
        job["fallback_attempts"] = attempts
    write_job(jid, job)


def terminer_en_echec(jid: str, message: str) -> None:
    """Ecrit la fin d'un travail qui s'est mal passe -- SANS ecraser un arret voulu.

    Le 17/09/2026, le tout premier essai du bouton d'arret a affiche ceci, en
    rouge, sous le mot << Echec >> :

        Modal unavailable: NotFoundError: Modal Sandbox with container ID
        ta-... not found. This means this Sandbox has already shut down.

    C'etait pourtant la preuve que l'arret avait REUSSI : la machine n'existait
    plus parce qu'on venait de la terminer. Le fil de travail, qui ne savait
    rien de l'arret, ecrasait une seconde plus tard le << cancelled >> pose par
    la route -- et avec lui le compte-rendu (combien de machines arretees).
    Resultat : impossible pour l'utilisateur de distinguer son propre arret d'un
    plantage du service, et impossible pour moi de dire ce que le bouton avait
    fait. Un bouton dont on ne peut pas verifier l'effet ne vaut guere mieux
    qu'un bouton qui ment.

    Fonction PARTAGEE par tous les chemins d'execution. Il en existait cinq
    copies de trois lignes, une par fournisseur : corriger la seule qui avait
    mordu aurait laisse le piege arme sur les quatre autres.

    Le message d'echec est passe tel quel par l'appelant, et non reconstruit
    ici : chaque chemin formate deja le sien, et une panne ordinaire doit
    continuer de s'afficher mot pour mot comme avant ce correctif.
    """
    job = read_job(jid)
    if job.get("arret_demande"):
        job.update({
            "status": "cancelled",
            "finished_at": time.time(),
            # L'erreur brute est conservee, mais dans un champ technique : elle
            # explique le COMMENT, elle ne doit pas etre le message montre.
            "erreur_technique": message[:1000],
            "error": "Arrêté à votre demande.",
        })
    else:
        job.update({"status": "failed", "finished_at": time.time(), "error": message[:1000]})
    write_job(jid, job)


# Ce que /essai s'autorise a attendre quand le code part sur la carte. Le bac
# a sable GPU est regle a 2 400 s pour la video -- un clip de 3 s a demande
# 412 s de calcul le 19/09 -- mais ici c'est quelqu'un devant une page, et un
# code qui ne s'arrete pas tiendrait la carte quarante minutes. 600 s : de quoi
# charger un modele (25 s mesurees pour celui de la video) et calculer, pas de
# quoi immobiliser la carte de quelqu'un d'autre.
ESSAI_MAISON_S = int(os.getenv("ESSAI_MAISON_TIMEOUT_SECONDS", "600"))


# Les deux bacs a sable n'ont PAS les memes bibliotheques, et c'est voulu : celui
# du processeur est un `python:3.12-slim` (fastapi, uvicorn, pydantic), celui de
# la carte part d'une image `pytorch/pytorch:2.6.0-cuda12.4` de plusieurs Go.
# Sans cette phrase, un repli correct -- carte prise, voisin jamais interrompu --
# rendait `ModuleNotFoundError: No module named 'torch'`, une trace que personne
# ne relie au repli. Mesure du 21/09 sur les conteneurs en marche.
# Un test tient les DEUX bouts : cette phrase et les deux images. Le jour ou
# quelqu'un ajoute torch au bac a sable du processeur, il tombe, au lieu de
# laisser la page mentir.
SANS_TORCH = (" Attention : torch et CUDA n'y sont pas installes, "
              "un code qui les importe s'arretera la.")


def ou_lancer_essai() -> tuple[str, str]:
    """Carte ou processeur, decide a la seconde. Rend (ou, phrase a montrer).

    REG-1, tranche par le proprietaire le 21/09/2026 : on lance sur la carte si
    elle est LIBRE. La place qu'un code jamais vu prendra n'est pas connue et ne
    peut pas l'etre ; on ne la devine donc pas, on mesure l'occupation a
    l'instant. S'il deborde quand meme, CUDA l'arrete en quelques secondes dans
    un bac a sable -- l'echec est immediat et lisible, il ne contamine aucun
    resultat. C'est ce qui distingue ce cas de tous les autres chiffres du
    Studio, ou une valeur supposee se glisserait dans une mesure.
    """
    if not WORKER_GPU_URL:
        return "local", ("Aucun bac a sable GPU sur cette machine : la surcouche "
                         "docker-compose.gpu.yml n'est pas appliquee. Le code "
                         "tourne sur le processeur." + SANS_TORCH)
    libre, phrase, _ = gpu_local.libre_pour_un_code_inconnu()
    if libre:
        return "maison", phrase + " Le code tourne sur la carte."
    return "local", phrase + " Le code tourne sur le processeur." + SANS_TORCH


def run_local(jid: str, code: str, gpu: bool = False):
    """Le code du client sur SA machine : processeur, ou carte s'il l'a demandee."""
    job = read_job(jid)
    ou, phrase = ("local", "")
    if gpu:
        ou, phrase = ou_lancer_essai()
    job.update({"status": "running", "started_at": time.time(),
                "provider_effective": ou})
    if phrase:
        # La fiche PORTE la raison. Un repli silencieux sur le processeur
        # serait la meme faute que la case grisee sans explication : le client
        # croirait avoir utilise sa carte.
        job["placement"] = phrase
    write_job(jid, job)
    try:
        if ou == "maison":
            finish_execution(jid, "maison", maison_execute(jid, code, ESSAI_MAISON_S))
        else:
            finish_execution(jid, "local", local_execute(jid, code))
    except BackendUnavailable as exc:
        terminer_en_echec(jid, str(exc)[:1000])


def run_modal(jid: str, code: str, gpu: bool, internet: bool):
    job = read_job(jid)
    job.update({"status": "running", "started_at": time.time(), "provider_effective": "modal"})
    write_job(jid, job)
    if not modal_configured():
        job.update({
            "status": "needs_configuration",
            "finished_at": time.time(),
            "error": "Modal requires MODAL_TOKEN_ID and MODAL_TOKEN_SECRET (page /cles, or MODAL_ENABLED=true in .env).",
        })
        write_job(jid, job)
        return
    try:
        finish_execution(jid, "modal", modal_execute(jid, code, gpu, internet))
    except budget_modal.BudgetDepasse as exc:
        # Un refus de budget n'est pas une panne de Modal, et le message dit
        # deja quoi faire. Ici l'utilisateur a demande Modal explicitement :
        # on ne choisit pas un autre fournisseur a sa place.
        terminer_en_echec(jid, str(exc)[:1000])
    except BackendUnavailable as exc:
        terminer_en_echec(jid, str(exc)[:1000])


def kaggle_ref(jid: str):
    user = os.getenv("KAGGLE_USERNAME", "").strip()
    slug = f"free-ai-studio-{jid[:12]}"
    return user, slug, f"{user}/{slug}" if user else ""


# Le Studio attend Kaggle un peu plus longtemps que le delai qu'il lui donne, le
# temps d'une file d'attente : il voit ainsi l'arret decide par Kaggle.
KAGGLE_MARGE_S = 900


def journal_kaggle(jid: str, ref: str) -> str:
    """Rapatrie le journal d'execution du noyau, pour un travail Kaggle en echec.

    DEFAUT REEL du 17/09/2026. Le chemin Kaggle du dialogue est mort sur
    << kernelworkerstatus.error >> -- et c'etait TOUT ce que le Studio savait en
    dire. Une phrase d'etat, pas une ligne de ce qui s'est passe sur la machine.
    Le chemin Modal, lui, remonte un vrai journal ; le chemin gratuit ne
    remontait rien, alors que Kaggle garde ce journal et que la CLI sait le
    rendre. Il a fallu aller le chercher a la main pour y trouver, en clair, un
    ModuleNotFoundError survenu 83 s apres le demarrage.

    Un echec qu'on ne peut pas lire est un echec qu'on ne peut pas reparer, et
    c'est pire encore pour un debutant : il ne lui reste qu'a relancer au hasard,
    sur son quota.

    Rien ici ne peut aggraver la panne. Toute erreur de rapatriement est avalee
    et rendue comme texte ; le message d'echec reste celui de l'appelant.
    """
    try:
        d = JOBS / jid / "journal-kaggle"
        d.mkdir(parents=True, exist_ok=True)
        # La CLI n'a pas d'option << journal seul >> : elle descend tout le
        # dossier de travail, depot clone compris. D'ou le delai genereux, et
        # d'ou le fait que ceci ne tourne QUE sur un echec, jamais en routine.
        subprocess.run(["kaggle", "kernels", "output", ref, "-p", str(d), "--force"],
                       capture_output=True, text=True, timeout=180)
        fichiers = sorted(d.glob("*.log"))
        if not fichiers:
            return ""
        brut = fichiers[0].read_text(encoding="utf-8", errors="replace")
        # Le journal est une liste JSON d'evenements {stream_name, time, data}.
        # Le livrer tel quel serait tendre le probleme sans la reponse : on le
        # remet a plat, dans l'ordre, et on garde la FIN -- une trace d'erreur
        # se lit par le bas.
        try:
            lignes = [str(ev.get("data", "")).rstrip("\n") for ev in json.loads(brut)]
            plat = "\n".join(x for x in lignes if x)
        except Exception:
            plat = brut
        return plat[-4000:]
    except Exception as exc:
        return f"(journal Kaggle non recupere : {type(exc).__name__})"


def _echec_kaggle(jid: str, exc: BaseException) -> None:
    """La fin d'un travail Kaggle qui s'est mal passe. Un seul endroit.

    Le journal AVANT terminer_en_echec : celle-ci relit la fiche sur le
    disque et ne remplace que le statut, l'heure et le message. Ce qui est
    ecrit ici lui survit donc.

    PAS sur un arret demande : le noyau tourne encore, il n'y a pas de
    journal final a prendre, et faire patienter jusqu'a 180 s quelqu'un qui
    vient d'appuyer sur << Arret >> serait lui repondre par une attente. Un
    bouton d'arret doit s'arreter.
    """
    fiche = read_job(jid)
    if fiche.get("remote_ref") and not fiche.get("arret_demande"):
        texte = journal_kaggle(jid, fiche["remote_ref"])
        if texte:
            fiche = read_job(jid)
            fiche["journal_kaggle"] = texte
            write_job(jid, fiche)
    terminer_en_echec(jid, f"{type(exc).__name__}: {str(exc)[:1000]}")


def run_kaggle(jid: str, code: str, gpu: bool, internet: bool,
               machine_shape: Optional[str] = None, timeout_s: Optional[int] = None):
    """machine_shape et timeout_s ne servent qu'aux chansons ; sans eux, rien ne change."""
    job = read_job(jid)
    job.update({"status": "preparing", "provider_effective": "kaggle", "started_at": job.get("started_at", time.time())})
    write_job(jid, job)
    user, slug, ref = kaggle_ref(jid)
    if not kaggle_configured():
        job.update(
            {
                "status": "needs_configuration",
                "finished_at": time.time(),
                "error": "Kaggle orchestration requires KAGGLE_USERNAME and KAGGLE_KEY (page /cles, or KAGGLE_ENABLED=true in .env).",
            }
        )
        write_job(jid, job)
        return
    d = JOBS / jid / "kaggle"
    d.mkdir(parents=True, exist_ok=True)
    wrapped = (
        "import os\nfrom pathlib import Path\n"
        "os.environ.setdefault('FREE_AI_OUTPUT_DIR','/kaggle/working/free_ai_output')\n"
        "Path(os.environ['FREE_AI_OUTPUT_DIR']).mkdir(parents=True, exist_ok=True)\n" + code
    )
    (d / "job.py").write_text(wrapped, encoding="utf-8")
    metadata = {
        "id": ref,
        # Kaggle ne retient pas l'id tel quel : il fabrique le slug a partir du TITRE.
        # Avec un titre libre, le push avertit << your kernel title does not resolve to
        # the specified id >> puis cree le kernel sous un autre nom ; le manager
        # interrogeait alors un slug inexistant, recevait << cannot access kernel >> et
        # tournait jusqu'au delai d'une heure. Le titre est donc le slug lui-meme.
        # Le titre lisible choisi par l'appelant reste dans notre fiche de job.
        "title": slug,
        "code_file": "job.py",
        "language": "python",
        "kernel_type": "script",
        "is_private": True,
        "enable_gpu": bool(gpu),
        "enable_internet": bool(internet),
        "dataset_sources": [],
        "competition_sources": [],
        "kernel_sources": [],
        "model_sources": [],
    }
    if machine_shape:
        # Sans ce champ, Kaggle choisit la carte lui-meme.
        metadata["machine_shape"] = machine_shape
    (d / "kernel-metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    # Kaggle arrete lui-meme le notebook a ce delai (-t de << kaggle kernels push >>).
    # Sans lui, un Studio qui abandonnait l'attente laissait le notebook tourner
    # jusqu'a la limite de Kaggle, sur le quota de l'utilisateur. La CLI 2.2.4 n'a
    # pas de commande d'annulation, et l'API d'annulation demande un numero de
    # session qu'aucune reponse de l'envoi ni de l'etat ne donne.
    limite = int(timeout_s or os.getenv("KAGGLE_JOB_TIMEOUT_SECONDS", "3600"))
    # La limite entre DANS la fiche : une reprise apres redemarrage doit
    # recalculer l'echeance d'origine, et la variable d'environnement peut
    # avoir change entre-temps. Sans elle, la reprise devinerait.
    job["kaggle_limite_s"] = limite
    try:
        job["status"] = "submitting"
        job["remote_ref"] = ref
        write_job(jid, job)
        p = subprocess.run(["kaggle", "kernels", "push", "-p", str(d), "-t", str(limite)],
                           capture_output=True, text=True, timeout=90)
        if p.returncode:
            raise RuntimeError((p.stderr or p.stdout)[-1000:])
        job = read_job(jid)
        job["status"] = "running"
        job["submit_log"] = (p.stdout or "")[-1000:]
        write_job(jid, job)
    except Exception as exc:  # noqa: BLE001
        _echec_kaggle(jid, exc)
        return
    attendre_kaggle(jid, ref, time.time(), limite)


def attendre_kaggle(jid: str, ref: str, pousse: float, limite: float) -> None:
    """Surveille un notebook DEJA pousse, jusqu'a son echeance.

    Sortie de `run_kaggle` le 22/09/2026 pour qu'une reprise apres
    redemarrage emprunte la MEME boucle. La dupliquer garantirait qu'elles
    divergent : la garde du refus d'acces -- celle qui evite d'attendre une
    heure sur un slug inexistant -- a ete ajoutee apres coup a celle-ci, et
    c'est exactement le genre de correctif qui n'atterrit que d'un cote.

    `pousse` est l'heure de DEPART du notebook, pas celle de l'appel. Une
    reprise qui repartirait de maintenant offrirait une heure neuve a un
    travail deja vieux -- le cas mesure le 22/09 : une fiche Kaggle a
    `running` depuis 318 h, dont les deux delais (le `-t` remis a Kaggle et
    cette echeance-ci) n'avaient jamais pu jouer parce que tous deux
    vivaient dans le fil mort.
    """
    deadline = pousse + limite + KAGGLE_MARGE_S
    try:
        while time.time() < deadline:
            s = subprocess.run(["kaggle", "kernels", "status", ref], capture_output=True, text=True, timeout=30)
            text = ((s.stdout or "") + "\n" + (s.stderr or "")).lower()
            job = read_job(jid)
            job["remote_status_raw"] = text[-800:]
            write_job(jid, job)
            # Arret d'urgence demande depuis la page : on cesse d'attendre. On
            # n'annule RIEN chez Kaggle -- il n'existe pas de commande pour ca --
            # et le message le dit, pour que personne ne croie le quota libere.
            if job.get("arret_demande"):
                raise RuntimeError(
                    "Arrêt demandé depuis le Studio : le Studio a cessé d'attendre. "
                    "Kaggle n'a pas d'annulation, le notebook s'arrête de lui-même "
                    f"à l'échéance de {limite} s qu'il a reçue.")
            if "complete" in text:
                break
            # Un statut illisible n'est pas un statut << en cours >>. Sans cette ligne,
            # un refus d'acces faisait patienter une heure entiere sans rien dire.
            if s.returncode or "cannot access" in text or "not found" in text or "denied" in text:
                raise RuntimeError(text[-1000:])
            if any(x in text for x in ("error", "cancel", "failed")):
                if time.time() - pousse >= limite:
                    raise RuntimeError(f"Délai de {limite} s dépassé : Kaggle a sans doute arrêté "
                                       f"le notebook lui-même. " + text[-900:])
                raise RuntimeError(text[-1000:])
            time.sleep(15)
        else:
            raise TimeoutError(f"Kaggle job timeout ({limite} s, plus {KAGGLE_MARGE_S} s de file d'attente)")
        od = JOBS / jid / "output"
        od.mkdir(exist_ok=True)
        p = subprocess.run(["kaggle", "kernels", "output", ref, "-p", str(od), "--force"], capture_output=True, text=True, timeout=180)
        if p.returncode:
            raise RuntimeError((p.stderr or p.stdout)[-1000:])
        arts = [add_artifact(jid, p, "kaggle") for p in od.rglob("*") if p.is_file() and not p.is_symlink()]
        job = read_job(jid)
        job.update({"status": "succeeded", "finished_at": time.time(), "artifacts": arts})
        write_job(jid, job)
    except Exception as exc:  # noqa: BLE001
        _echec_kaggle(jid, exc)


def make_colab_bundle(jid: str, code: str) -> Path:
    d = JOBS / jid
    nb = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {"colab": {"name": f"Free AI Studio {jid[:8]}"}, "kernelspec": {"name": "python3", "display_name": "Python 3"}},
        "cells": [
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    "# Free AI Studio — Colab handoff\n",
                    "Exécutez les cellules. Placez les résultats à récupérer dans `/content/free_ai_output`, puis téléchargez le ZIP final et importez-le dans le Studio.\n",
                ],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "from pathlib import Path\n",
                    "import os\n",
                    "OUTPUT_DIR=Path('/content/free_ai_output')\n",
                    "OUTPUT_DIR.mkdir(exist_ok=True)\n",
                    "os.environ['FREE_AI_OUTPUT_DIR']=str(OUTPUT_DIR)\n",
                    "print('Dossier de sortie:', OUTPUT_DIR)\n",
                ],
            },
            {"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": [code]},
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "import shutil\n",
                    "archive=shutil.make_archive('/content/free-ai-studio-results','zip','/content/free_ai_output')\n",
                    "from google.colab import files\n",
                    "files.download(archive)\n",
                ],
            },
        ],
    }
    p = d / "free-ai-studio-colab.ipynb"
    p.write_text(json.dumps(nb, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def prepare_colab_handoff(jid: str, code: str, attempts: list[dict] | None = None):
    make_colab_bundle(jid, code)
    job = read_job(jid)
    job.update({
        "status": "handoff_ready",
        "provider_effective": "colab",
        "finished_at": time.time(),
        "notebook": "free-ai-studio-colab.ipynb",
        "direct_url": "https://colab.research.google.com/",
    })
    if attempts is not None:
        job["fallback_attempts"] = attempts
    write_job(jid, job)


# Le port que le NAVIGATEUR voit : celui que docker-compose publie (8020), pas
# celui du conteneur (8000). L'onglet Colab ouvre ws://localhost:<ce port>.
PORT_PUBLIE = int(os.getenv("SANDBOX_MANAGER_PORT_PUBLIE", "8020"))
COLAB_DELAI_S = int(os.getenv("COLAB_JOB_TIMEOUT_SECONDS", "3600"))


def colab_execute(jid: str, code: str, gpu: bool, delai_s: int = COLAB_DELAI_S) -> dict:
    """Le travail dans le carnet Colab branche, s'il y en a un.

    Meme forme de reponse que les autres executeurs. Toute impossibilite --
    pas de carnet, carnet occupe, pas de carte, carnet debranche -- devient
    BackendUnavailable avec sa phrase : ce n'est jamais l'erreur du code."""
    od = JOBS / jid / "output"

    def arret() -> bool:
        return bool(read_job(jid).get("arret_demande"))

    def progres(e: dict) -> None:
        job = read_job(jid)
        job["colab"] = e
        write_job(jid, job)

    try:
        data = colab_pont.executer(colab_pont.PONT, code, od, delai_s, gpu=gpu,
                                   arret=arret, progres=progres)
    except (colab_pont.ColabAbsent, colab_pont.ColabOccupe,
            colab_pont.ColabSansCarte, colab_pont.ColabErreur) as exc:
        raise BackendUnavailable(str(exc)) from exc
    data["artifacts"] = [add_artifact(jid, p, "colab") for p in data.pop("fichiers")]
    return data


def run_colab(jid: str, code: str, gpu: bool) -> None:
    """Un travail envoye au carnet ; sans carnet branche, le carnet a importer
    comme avant -- la personne a toujours une suite."""
    if not colab_pont.PONT.branche():
        prepare_colab_handoff(jid, code)
        return
    job = read_job(jid)
    job.update({"status": "running", "provider_effective": "colab", "started_at": job.get("started_at", time.time())})
    write_job(jid, job)
    try:
        data = colab_execute(jid, code, gpu)
    except BackendUnavailable as exc:
        terminer_en_echec(jid, str(exc)[:1000])
        return
    finish_execution(jid, "colab", data)


def _essayer_colab(jid: str, code: str, gpu: bool, attempts: list) -> bool:
    if not colab_pont.PONT.branche():
        attempts.append({"provider": "colab", "result": "not_connected"})
        return False
    try:
        job = read_job(jid)
        job.update({"status": "running", "provider_effective": "colab"})
        write_job(jid, job)
        data = colab_execute(jid, code, gpu)
        attempts.append({"provider": "colab", "result": "executed", "exit_code": data.get("exit_code")})
        finish_execution(jid, "colab", data, attempts)
        return True
    except BackendUnavailable as exc:
        attempts.append({"provider": "colab", "result": "unavailable", "detail": str(exc)[:500]})
    return False


def _essayer_modal(jid: str, code: str, gpu: bool, internet: bool, attempts: list) -> bool:
    if not modal_configured():
        attempts.append({"provider": "modal", "result": "not_configured"})
        return False
    try:
        job = read_job(jid)
        job.update({"status": "running", "provider_effective": "modal"})
        write_job(jid, job)
        data = modal_execute(jid, code, gpu, internet)
        attempts.append({"provider": "modal", "result": "executed", "exit_code": data.get("exit_code")})
        finish_execution(jid, "modal", data, attempts)
        return True
    except budget_modal.BudgetDepasse as exc:
        # Le plafond du mois est atteint : ce n'est pas une panne, c'est un
        # refus, et le mode auto a justement trois suites gratuites. Le
        # laisser remonter tuerait le fil et laisserait le travail en
        # << routing >> pour toujours.
        attempts.append({"provider": "modal", "result": "budget_exhausted", "detail": str(exc)[:500]})
    except BackendUnavailable as exc:
        attempts.append({"provider": "modal", "result": "unavailable", "detail": str(exc)[:500]})
    return False


def _essayer_local(jid: str, code: str, attempts: list) -> bool:
    try:
        job = read_job(jid)
        job.update({"status": "running", "provider_effective": "local"})
        write_job(jid, job)
        data = local_execute(jid, code)
        attempts.append({"provider": "local", "result": "executed", "exit_code": data.get("exit_code")})
        finish_execution(jid, "local", data, attempts)
        return True
    except BackendUnavailable as exc:
        attempts.append({"provider": "local", "result": "unavailable", "detail": str(exc)[:500]})
    return False


def _essayer_maison(jid: str, code: str, attempts: list) -> bool:
    """La carte d'ici, si la sonde la dit libre. Sinon la raison est ecrite dans
    la fiche : un passage chez Modal sans un mot laisserait croire la carte en
    panne."""
    ou, phrase = ou_lancer_essai()
    if ou != "maison":
        attempts.append({"provider": "maison", "result": "not_free", "detail": phrase[:500]})
        return False
    try:
        job = read_job(jid)
        job.update({"status": "running", "provider_effective": "maison", "placement": phrase})
        write_job(jid, job)
        data = maison_execute(jid, code, ESSAI_MAISON_S)
        attempts.append({"provider": "maison", "result": "executed", "exit_code": data.get("exit_code")})
        finish_execution(jid, "maison", data, attempts)
        return True
    except BackendUnavailable as exc:
        attempts.append({"provider": "maison", "result": "unavailable", "detail": str(exc)[:500]})
    return False


def run_auto(jid: str, code: str, gpu: bool, internet: bool, kaggle_permis: bool = True):
    attempts: list[dict] = []
    ordre = ordre_auto(gpu, internet)
    job = read_job(jid)
    job.update({"status": "routing", "started_at": time.time(), "fallback_order": ordre})
    write_job(jid, job)

    if ordre[0] == "local":
        if _essayer_local(jid, code, attempts) or _essayer_modal(jid, code, gpu, internet, attempts):
            return
    elif ordre[0] == "maison":
        if (_essayer_maison(jid, code, attempts) or _essayer_modal(jid, code, gpu, internet, attempts)
                or _essayer_local(jid, code, attempts)):
            return
    elif _essayer_modal(jid, code, gpu, internet, attempts) or _essayer_local(jid, code, attempts):
        return

    if not kaggle_permis:
        # Studio partage : les identifiants Kaggle presents sont ceux d'une seule
        # personne. On passe au notebook Colab, que chacun ouvre avec son compte.
        attempts.append({"provider": "kaggle", "result": "disabled_shared_context"})
    elif not gpu:
        # Politique d'usage de Kaggle : de la science des donnees, pas un code
        # quelconque. Le mode auto ne lui envoie que les jobs GPU (decision de
        # l'utilisateur du 11/09/2026, option b du PLAN).
        attempts.append({"provider": "kaggle", "result": "cpu_job_not_sent"})
    elif kaggle_configured():
        attempts.append({"provider": "kaggle", "result": "selected"})
        job = read_job(jid)
        job["fallback_attempts"] = attempts
        write_job(jid, job)
        run_kaggle(jid, code, gpu, internet)
        return
    else:
        attempts.append({"provider": "kaggle", "result": "not_configured"})

    # Un carnet Colab branche par la personne passe avant le fichier a importer.
    # Pas en Studio partage : le carnet est celui d'une seule personne, comme
    # les identifiants Kaggle.
    if kaggle_permis and _essayer_colab(jid, code, gpu, attempts):
        return
    attempts.append({"provider": "colab", "result": "handoff"})
    prepare_colab_handoff(jid, code, attempts)


@app.get("/colab/etat")
def colab_etat(request: Request, authorization: Optional[str] = Header(default=None)):
    """Le carnet Colab est-il branche ? Et l'adresse qui le branche.

    L'adresse porte le jeton du pont : elle ne sort que contre la cle du
    service, comme le reste des pages. En Studio partage, pas d'adresse du
    tout : le carnet serait celui d'une seule personne."""
    auth(authorization)
    raison = contexte_partage(request)
    etat = colab_pont.PONT.etat()
    etat["coupe"] = raison
    if raison is None:
        etat["adresse"] = colab_pont.PONT.adresse(PORT_PUBLIE)
    return etat


@app.websocket("/{chemin:path}")
async def colab_branchement(websocket: WebSocket, chemin: str = ""):
    """L'onglet Colab se branche ici (ws://localhost:8020, sous-protocole mcp).

    Trois gardes avant d'accepter : l'Origin est Colab, le jeton est celui de
    l'adresse donnee par /colab/etat, et aucun autre carnet n'est branche."""
    if contexte_partage() is not None:
        await websocket.close(code=1008)
        return
    auth_entete = websocket.headers.get("authorization", "")
    jeton = websocket.query_params.get("access_token") or (
        auth_entete[7:] if auth_entete.startswith("Bearer ") else "")
    refus = colab_pont.PONT.refus(websocket.headers.get("origin"), jeton)
    if refus:
        colab_pont.PONT.dernier_refus = refus
        log.warning("branchement Colab refuse : %s", refus)
        await websocket.close(code=1008)
        return
    await websocket.accept(subprotocol="mcp")
    log.info("carnet Colab branche")

    async def recevoir() -> str:
        return await websocket.receive_text()

    try:
        await colab_pont.PONT.servir(websocket.send_text, recevoir)
    except (WebSocketDisconnect, colab_pont.ColabErreur) as exc:
        log.info("carnet Colab debranche : %s", type(exc).__name__)
    except Exception:  # noqa: BLE001 -- un onglet qui part mal ne tue pas le service
        log.exception("carnet Colab debranche sur une erreur")


# --- NotebookLM (PLAN.md 17.6) -------------------------------------------------

NLM_ERREURS = (notebooklm_pont.SessionAbsente, notebooklm_pont.SessionExpiree,
               notebooklm_pont.QuotaAtteint, notebooklm_pont.NotebookLMEchec)


def _nlm_coupe(request: Request) -> None:
    raison = contexte_partage(request)
    if raison:
        raise HTTPException(403, "NotebookLM piloté est coupé ici (%s) : la session est celle du "
                                 "compte Google d'une seule personne. Ouvrez NotebookLM vous-même : "
                                 "https://notebook.google.com/" % raison)


@app.get("/notebooklm/etat")
def notebooklm_etat(request: Request, verifier: int = Query(default=0),
                    authorization: Optional[str] = Header(default=None)):
    """La session est-elle branchee ? Avec verifier=1, un appel qui ne fabrique
    rien (la liste des carnets) dit si Google l'accepte encore."""
    auth(authorization)
    raison = contexte_partage(request)
    if raison:
        return {"branchee": False, "coupe": raison}
    etat = notebooklm_pont.compte()
    etat["coupe"] = None
    if verifier and etat.get("branchee"):
        try:
            etat.update(notebooklm_pont.executer(notebooklm_pont.verifier))
        except NLM_ERREURS as exc:
            etat.update({"ok": False, "message": str(exc)})
    return etat


@app.post("/notebooklm/session")
async def notebooklm_session(request: Request, authorization: Optional[str] = Header(default=None)):
    """Ferme dans le coffre la session collee par la personne, puis l'essaie.
    Ni la reponse ni le journal ne portent une valeur de cookie."""
    auth(authorization)
    exiger_page_du_studio(request)
    exiger_json(request)
    _nlm_coupe(request)
    payload = await request.json()
    try:
        r = await asyncio.to_thread(notebooklm_pont.enregistrer, str(payload.get("export") or ""))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    try:
        v = await asyncio.to_thread(notebooklm_pont.executer, notebooklm_pont.verifier)
    except NLM_ERREURS as exc:
        return {"enregistree": True, "ok": False, "message": str(exc), **r}
    return {"enregistree": True, **r, **v}


@app.post("/notebooklm/oublier")
def notebooklm_oublier(request: Request, authorization: Optional[str] = Header(default=None)):
    auth(authorization)
    exiger_page_du_studio(request)
    return {"oubliee": notebooklm_pont.oublier()}


def run_notebooklm(jid: str, sources: list, reglages: dict) -> None:
    job = read_job(jid)
    job.update({"status": "running", "started_at": time.time(), "provider_effective": "notebooklm"})
    write_job(jid, job)

    def progres(texte: str) -> None:
        j = read_job(jid)
        j["etape"] = texte
        write_job(jid, j)

    try:
        r = notebooklm_pont.executer(lambda: notebooklm_pont.resume_audio(
            sources, JOBS / jid / "output", progres=progres, **reglages))
    except NLM_ERREURS as exc:
        terminer_en_echec(jid, str(exc)[:1000])
        if isinstance(exc, notebooklm_pont.CarnetsPleins):
            # La page ouvre alors la boite des anciens carnets a supprimer.
            job = read_job(jid)
            job["plein"] = True
            write_job(jid, job)
        return
    except Exception as exc:  # noqa: BLE001 -- jamais un fil mort sur une fiche << running >>
        log.exception("notebooklm")
        terminer_en_echec(jid, "NotebookLM a échoué : %s" % type(exc).__name__)
        return
    art = add_artifact(jid, r["audio"], "notebooklm")
    job = read_job(jid)
    job.update({"status": "succeeded", "finished_at": time.time(), "artifacts": [art],
                "carnet_id": r["carnet_id"], "carnet_url": r["carnet_url"], "etape": ""})
    write_job(jid, job)


@app.post("/notebooklm/resume")
async def notebooklm_resume(request: Request, authorization: Optional[str] = Header(default=None)):
    """Documents et/ou texte -> un carnet NotebookLM neuf -> un resume audio."""
    auth(authorization)
    exiger_page_du_studio(request)
    _nlm_coupe(request)
    if not notebooklm_pont.branchee():
        raise HTTPException(409, notebooklm_pont.PHRASE_ABSENTE)
    f = await request.form()
    jid = uuid.uuid4().hex
    dossier = JOBS / jid / "sources"
    dossier.mkdir(parents=True, exist_ok=True)
    sources: list[dict] = []
    for envoi in f.getlist("fichiers"):
        if not getattr(envoi, "filename", ""):
            continue
        nom = clean_name(envoi.filename)
        if not nom.lower().endswith(notebooklm_pont.EXTENSIONS):
            raise HTTPException(400, "« %s » : NotebookLM reçoit ici des PDF, .txt, .md ou .docx." % nom)
        contenu = await envoi.read()
        if len(contenu) > MAX_UPLOAD:
            raise HTTPException(413, "« %s » est trop gros (%s au plus)." % (
                nom, format_fr.en_memoire(MAX_UPLOAD // 2**20)))
        (dossier / nom).write_bytes(contenu)
        sources.append({"chemin": str(dossier / nom), "titre": nom})
    texte = str(f.get("texte") or "").strip()
    if texte:
        if len(texte) > notebooklm_pont.TEXTE_MAX:
            raise HTTPException(413, "Texte trop long (%d signes au plus)." % notebooklm_pont.TEXTE_MAX)
        sources.append({"titre": "Texte collé", "texte": texte})
    if not sources:
        raise HTTPException(400, "Donnez au moins un document ou un texte.")
    titre = str(f.get("titre") or "").strip()[:80]
    reglages = {
        "consigne": str(f.get("consigne") or "").strip()[:2000],
        "format_": str(f.get("format") or "approfondi"),
        "longueur": str(f.get("longueur") or "normal"),
        "langue": "fr",
        # Le nom du carnet : « Studio · <titre> · <heure de la page> ».
        "titre": titre or sources[0]["titre"],
        "quand": str(f.get("quand") or "")[:20],
    }
    write_job(jid, {"id": jid, "provider": "notebooklm", "title": "NotebookLM", "status": "queued",
                    "created_at": time.time(), "artifacts": [], "titre": titre or sources[0]["titre"],
                    "sources": [s["titre"] for s in sources]})
    threading.Thread(target=run_notebooklm, args=(jid, sources, reglages), daemon=True).start()
    return read_job(jid)


@app.get("/notebooklm/resumes")
def notebooklm_resumes(authorization: Optional[str] = Header(default=None)):
    """Les resumes NotebookLM deja faits, du plus recent au plus ancien.

    25/09/2026, le proprietaire : « toujours pas de son ». Le seul resume
    existant avait ete lance hors de la page ; la page ne montrait que le son
    d'un resume lance par elle, et le perdait au rechargement."""
    auth(authorization)
    sortie = []
    for p in sorted(JOBS.glob("*/job.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            job = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 -- une fiche illisible ne vide pas la liste
            continue
        if job.get("provider") == "notebooklm":
            sortie.append(_fiche_nlm(job))
            if len(sortie) >= 30:
                break
    return {"resumes": sortie}


@app.get("/notebooklm/jobs/{jid}")
def notebooklm_job(jid: str, authorization: Optional[str] = Header(default=None)):
    auth(authorization)
    job = read_job(jid)
    if job.get("provider") != "notebooklm":
        raise HTTPException(404, "Ce travail n'est pas un résumé NotebookLM")
    return _fiche_nlm(job)


def _fiche_nlm(job: dict) -> dict:
    jid = job.get("id") or ""
    sortie = {"id": jid, "status": job.get("status"), "etape": job.get("etape") or "",
              "created_at": job.get("created_at"), "titre": job.get("titre") or "",
              "message": job.get("error") or "", "carnet_url": job.get("carnet_url") or "",
              "carnet_id": job.get("carnet_id") or "", "plein": bool(job.get("plein"))}
    if any(a.get("path") for a in job.get("artifacts", [])):
        sortie["audio_url"] = "/notebooklm/jobs/%s/audio?cle=%s" % (jid, jeton_video(jid))
    return sortie


@app.get("/notebooklm/jobs/{jid}/audio")
def notebooklm_audio(jid: str, cle: str = Query(default=""), telecharger: int = Query(default=0)):
    attendu = jeton_video(jid)
    if not attendu or not hmac.compare_digest(cle, attendu):
        raise HTTPException(401, "Unauthorized")
    arts = [a for a in read_job(jid).get("artifacts", []) if a.get("path")]
    if not arts:
        raise HTTPException(404, "Pas de résumé audio pour ce travail")
    chemin = ART / arts[0]["path"]
    if not chemin.exists() or chemin.is_symlink():
        raise HTTPException(404, "Fichier absent")
    if telecharger:
        return FileResponse(chemin, media_type="audio/mp4", filename="resume-notebooklm.m4a")
    return FileResponse(chemin, media_type="audio/mp4")


@app.post("/notebooklm/demander")
async def notebooklm_demander(request: Request, authorization: Optional[str] = Header(default=None)):
    """Une question aux sources d'un carnet que le Studio a fabrique."""
    auth(authorization)
    exiger_page_du_studio(request)
    exiger_json(request)
    _nlm_coupe(request)
    p = await request.json()
    carnet, question = str(p.get("carnet_id") or ""), str(p.get("question") or "").strip()
    if not carnet or not question:
        raise HTTPException(400, "Il faut un carnet et une question.")
    try:
        return await asyncio.to_thread(notebooklm_pont.executer,
                                       lambda: notebooklm_pont.demander(carnet, question[:4000]))
    except NLM_ERREURS as exc:
        raise HTTPException(502, str(exc)) from exc


@app.get("/notebooklm/carnets")
def notebooklm_carnets(request: Request, authorization: Optional[str] = Header(default=None)):
    """Les carnets du compte, du plus ancien au plus recent (titre, date, sources)."""
    auth(authorization)
    _nlm_coupe(request)
    try:
        return {"carnets": notebooklm_pont.executer(notebooklm_pont.carnets)}
    except NLM_ERREURS as exc:
        raise HTTPException(502, str(exc)) from exc


@app.post("/notebooklm/carnets/supprimer")
async def notebooklm_carnets_supprimer(request: Request,
                                       authorization: Optional[str] = Header(default=None)):
    """Supprime DEFINITIVEMENT les carnets choisis dans la page. Exige
    {"ids": [...], "confirme": true} : la case cochee par la personne."""
    auth(authorization)
    exiger_page_du_studio(request)
    exiger_json(request)
    _nlm_coupe(request)
    p = await request.json()
    ids = [str(i) for i in (p.get("ids") or []) if str(i).strip()][:200]
    if p.get("confirme") is not True:
        raise HTTPException(400, "Rien n'est supprimé sans votre confirmation.")
    if not ids:
        raise HTTPException(400, "Aucun carnet choisi.")
    try:
        return await asyncio.to_thread(notebooklm_pont.executer,
                                       lambda: notebooklm_pont.supprimer(ids))
    except NLM_ERREURS as exc:
        raise HTTPException(502, str(exc)) from exc


@app.get("/notebooklm", response_class=HTMLResponse)
def notebooklm_page():
    return HTMLResponse(format_fr.avec_formateurs(notebooklm_pont.PAGE_HTML.replace("__CLE__", KEY)))


@app.get("/health")
def health():
    return {"ok": True, "service": "sandbox-manager", "version": "2.0.0"}


def verifier_modal(token_id: str, token_secret: str) -> Dict[str, object]:
    """Verifie le couple de jetons aupres de Modal. Client.verify n'ouvre aucune
    machine et ne consomme aucun credit : c'est une authentification seche."""
    try:
        from modal.client import Client
    except Exception as exc:
        return {"valide": False, "message": "SDK Modal indisponible dans le conteneur (%s)." % exc}
    url = os.getenv("MODAL_SERVER_URL", "https://api.modal.com")
    try:
        Client.verify(url, (token_id, token_secret))
    except Exception as exc:
        texte = str(exc)[:300]
        return {
            "valide": False,
            "message": "Modal a refuse ces jetons. Verifiez que l'identifiant commence par ak- et le secret par as-, "
                       "et qu'ils viennent du meme jeton. " + texte,
        }
    return {"valide": True, "message": "Jetons valides : Modal a repondu."}


def verifier_kaggle(username: str, key: str) -> Dict[str, object]:
    """Verifie les identifiants par un appel d'API authentifie et gratuit."""
    try:
        response = httpx.get(
            "https://www.kaggle.com/api/v1/datasets/list",
            auth=(username, key),
            params={"pageSize": 1},
            timeout=30,
        )
    except httpx.HTTPError as exc:
        return {"valide": False, "message": "Kaggle n'a pas repondu (%s). Verifiez votre connexion Internet." % type(exc).__name__}
    if response.status_code == 200:
        return {"valide": True, "message": "Identifiants valides : Kaggle a repondu."}
    if response.status_code in (401, 403):
        return {
            "valide": False,
            "message": "Kaggle a refuse ces identifiants. Le nom d'utilisateur est celui du fichier kaggle.json, "
                       "pas votre adresse e-mail.",
        }
    return {"valide": False, "message": "Refus de Kaggle (HTTP %d)." % response.status_code}


def secret_source(name: str) -> Optional[str]:
    if ENV_SECRETS.get(name):
        return "env"
    if stored_keys().get(name):
        return "interface"
    return None


@app.get("/cles/etat")
def cles_etat(request: Request):
    raison = contexte_partage(request)
    backends = []
    for nom, aide in SANDBOX_HELP.items():
        configure = modal_configured() if nom == "modal" else kaggle_configured()
        champs = []
        for champ in aide["champs"]:
            valeur = os.getenv(champ["nom"], "").strip()
            champs.append({
                "nom": champ["nom"],
                "libelle": champ["libelle"],
                "renseigne": bool(valeur),
                "indice": mask(valeur) if valeur else "",
                "source": secret_source(champ["nom"]),
            })
        backends.append({
            "nom": nom,
            "titre": aide["titre"],
            "role": aide["role"],
            "url": aide["url"],
            "repere": aide["repere"],
            "configure": configure,
            "champs": champs,
            # Un secret venu de .env n'appartient pas a l'interface : elle ne
            # propose pas de l'oublier, elle ne saurait pas le remettre.
            "oubliable": any(c["source"] == "interface" for c in champs),
            # Kaggle automatique coupe : la carte le dit, au lieu d'accepter des
            # identifiants qui serviraient a d'autres personnes.
            "coupe": raison if nom == "kaggle" else None,
        })
    return {"backends": backends, "backend_automatique": backend_automatique(),
            "backend_carte_ou_internet": backend_carte_ou_internet()}


@app.post("/cles/tester")
async def cles_tester(request: Request):
    exiger_page_du_studio(request)
    exiger_json(request)
    body = await request.json()
    nom = str(body.get("backend", "")).strip().lower()
    if nom not in SANDBOX_HELP:
        raise HTTPException(400, "Backend inconnu")
    if nom == "kaggle":
        raison = contexte_partage(request)
        if raison:
            # Refus AVANT tout appel a Kaggle : des identifiants de tiers ne sont
            # ni essayes ni gardes.
            raise refus_kaggle(raison)
    valeurs = body.get("valeurs") or {}
    attendus = [c["nom"] for c in SANDBOX_HELP[nom]["champs"]]
    fournis = {k: str(valeurs.get(k, "")).strip() for k in attendus}
    manquants = [k for k, v in fournis.items() if not v]
    if manquants:
        raise HTTPException(400, "Champ(s) vide(s) : " + ", ".join(manquants))

    if nom == "modal":
        resultat = verifier_modal(fournis["MODAL_TOKEN_ID"], fournis["MODAL_TOKEN_SECRET"])
    else:
        resultat = verifier_kaggle(fournis["KAGGLE_USERNAME"], fournis["KAGGLE_KEY"])

    if resultat["valide"]:
        for cle, valeur in fournis.items():
            store_key(cle, valeur)
        log.info("identifiants %s enregistres (source interface)", nom)
        deja_env = [k for k in attendus if ENV_SECRETS.get(k)]
        if deja_env:
            resultat["message"] += (
                " Attention : %s vient deja du fichier .env, et c'est cette valeur qui reste utilisee."
                % ", ".join(deja_env)
            )
    configure = modal_configured() if nom == "modal" else kaggle_configured()
    return {"valide": resultat["valide"], "message": resultat["message"],
            "enregistre": resultat["valide"], "configure": configure}


@app.post("/cles/oublier")
async def cles_oublier(request: Request):
    exiger_page_du_studio(request)
    exiger_json(request)
    body = await request.json()
    nom = str(body.get("backend", "")).strip().lower()
    if nom not in SANDBOX_HELP:
        raise HTTPException(400, "Backend inconnu")
    forget_secrets([c["nom"] for c in SANDBOX_HELP[nom]["champs"]])
    configure = modal_configured() if nom == "modal" else kaggle_configured()
    return {"oublie": True, "configure": configure}


CLES_SANDBOX_HTML = """
<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sandbox — vos identifiants</title>
<style>
:root{font-family:system-ui,sans-serif}
body{max-width:820px;margin:32px auto;padding:0 18px;line-height:1.5}
h1{margin-bottom:4px}.sous{opacity:.75;margin-top:0}
.banniere{padding:16px 18px;border-radius:14px;margin:18px 0;border:1px solid #bbb;background:#eef4fb}
.carte{border:1px solid #bbb;border-radius:16px;padding:18px;margin-bottom:16px}
.entete{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.entete h2{margin:0;font-size:1.15rem}
.pastille{font-size:.8rem;border-radius:999px;padding:3px 10px;border:1px solid #999;background:#f1f1f1}
.pastille.verte{background:#e8f6ec;border-color:#7fb98f}
.role{margin:8px 0 14px}.etape{margin:10px 0}
.num{display:inline-block;width:22px;height:22px;line-height:22px;text-align:center;
 border-radius:999px;background:#333;color:#fff;font-size:.78rem;margin-right:7px}
a.bouton,button{font:inherit;padding:9px 14px;border-radius:10px;border:1px solid #666;
 background:#fff;cursor:pointer;text-decoration:none;color:inherit;display:inline-block}
button.primaire{background:#222;color:#fff;border-color:#222}
button[disabled]{opacity:.5;cursor:default}
label{display:block;font-size:.86rem;margin:8px 0 3px 29px}
input{font:inherit;padding:9px 11px;border-radius:10px;border:1px solid #999;
 width:min(420px,100%);box-sizing:border-box;margin-left:29px}
.repere{font-size:.86rem;opacity:.75;margin:6px 0 0 29px}
.resultat{margin-top:10px;font-size:.92rem}.ok{color:#1d6b32}.ko{color:#9b2116}
.pied{margin-top:26px;padding-top:16px;border-top:1px solid #ddd;font-size:.9rem;opacity:.8}
</style></head><body>
<h1>Vos identifiants Sandbox</h1>
<p class="sous">Ces services executent votre code ailleurs que sur votre ordinateur.
Sans eux, tout tourne en local — ce qui suffit dans la plupart des cas.</p>

<div id="banniere" class="banniere">Verification en cours...</div>
<div id="cartes"></div>

<div class="pied">
Chaque valeur est essayee aupres du service avant d'etre gardee : une valeur refusee
n'est jamais enregistree. Elle prend effet tout de suite, sans rien relancer.
<br><a href="/">Retour au Sandbox</a>
</div>

<script>
function element(html){const d=document.createElement("div");d.innerHTML=html.trim();return d.firstChild;}

function carte(b){
  let champs = "";
  b.champs.forEach(c => {
    const venu = c.renseigne ? ' &nbsp;<span style="opacity:.7">actuel : '+c.indice+
      ' ('+(c.source==="env"?"fichier .env":"cette page")+')</span>' : '';
    champs += '<label>'+c.libelle+venu+'</label>'+
              '<input type="password" data-nom="'+c.nom+'" placeholder="Collez ici" autocomplete="off">';
  });
  const oubli = b.oubliable ? '<button class="oublier" style="margin-left:10px">Oublier</button>' : '';
  const c = element(
    '<div class="carte">'+
      '<div class="entete"><h2>'+b.titre+'</h2>'+
        '<span class="pastille'+(b.configure?" verte":"")+'">'+(b.configure?"actif":"pas configure")+'</span>'+
      '</div>'+
      '<p class="role">'+b.role+'</p>'+
      '<div class="etape"><span class="num">1</span>'+
        '<a class="bouton" href="'+b.url+'" target="_blank" rel="noopener">Ouvrir la page officielle</a>'+
        '<div class="repere">'+b.repere+'</div></div>'+
      '<div class="etape"><span class="num">2</span>Collez les valeurs :</div>'+
      champs+
      '<div class="etape" style="margin-top:14px"><span class="num">3</span>'+
        '<button class="primaire verifier">Verifier et enregistrer</button>'+oubli+'</div>'+
      '<div class="resultat"></div>'+
    '</div>');

  const sortie = c.querySelector(".resultat");
  const bouton = c.querySelector(".verifier");
  if(b.coupe){
    c.querySelector(".role").textContent = "Pilotage automatique coupe ici (" + b.coupe + ") : il utiliserait "
      + "les identifiants Kaggle personnels du proprietaire de la machine. Ouvrez Kaggle vous-meme : "
      + "https://www.kaggle.com/code";
    c.querySelectorAll("input").forEach(i => i.disabled = true);
    bouton.disabled = true;
  }
  bouton.addEventListener("click", async () => {
    const valeurs = {};
    let vide = false;
    c.querySelectorAll("input").forEach(i => {
      valeurs[i.dataset.nom] = i.value.trim();
      if(!i.value.trim()) vide = true;
    });
    if(vide){ sortie.className="resultat ko"; sortie.textContent="Remplissez les deux champs."; return; }
    bouton.disabled = true; sortie.className="resultat"; sortie.textContent="Verification aupres du service...";
    try{
      const r = await fetch("/cles/tester", {method:"POST", headers:{"Content-Type":"application/json"},
        body: JSON.stringify({backend: b.nom, valeurs: valeurs})});
      const d = await r.json();
      sortie.className = "resultat " + (d.valide ? "ok" : "ko");
      sortie.textContent = d.message || (d.detail || "Reponse inattendue.");
      if(d.valide){ c.querySelectorAll("input").forEach(i => i.value=""); setTimeout(charger, 600); }
    }catch(e){
      sortie.className="resultat ko"; sortie.textContent="Le Sandbox local n'a pas repondu : "+e;
    }finally{ bouton.disabled = false; }
  });

  const oublier = c.querySelector(".oublier");
  if(oublier){
    oublier.addEventListener("click", async () => {
      oublier.disabled = true;
      try{
        await fetch("/cles/oublier", {method:"POST", headers:{"Content-Type":"application/json"},
          body: JSON.stringify({backend: b.nom})});
        charger();
      }finally{ oublier.disabled = false; }
    });
  }
  return c;
}

async function charger(){
  const d = await (await fetch("/cles/etat")).json();
  const nom = {modal:"Modal, une machine distante", kaggle:"Kaggle", local:"votre ordinateur, isole dans Docker"}[d.backend_automatique];
  document.getElementById("banniere").textContent = "Actuellement, le code envoye au Sandbox s'execute sur : " + nom + "." + (d.backend_carte_ou_internet === "modal" ? " Un code qui demande une carte graphique passe sur la vôtre si elle est libre, sinon chez Modal ; un code qui demande Internet part chez Modal." : "");
  const zone = document.getElementById("cartes");
  zone.innerHTML = "";
  d.backends.forEach(b => zone.appendChild(carte(b)));
}
charger();
</script>
</body></html>
"""


@app.get("/cles", response_class=HTMLResponse)
def cles_page():
    return HTMLResponse(CLES_SANDBOX_HTML)


# --- Page d'essai ------------------------------------------------------------
# Sans elle, brancher Modal ne sert a rien pour qui n'a pas d'assistant de code :
# la seule facon de lancer un calcul est POST /jobs, qui reclame la cle Bearer,
# donc un terminal. La page est servie par ce meme service, publie sur 127.0.0.1
# seulement ; le serveur y depose la cle et le navigateur appelle l'API normale,
# celle qui est deja authentifiee. Aucune route d'execution sans cle n'est ouverte.

CODE_DEMO = """import os
import platform
import socket
from pathlib import Path

print("machine     :", platform.node())
print("systeme     :", platform.platform())
print("processeurs :", os.cpu_count())

total = sum(i * i for i in range(1, 1001))
print("somme des carres 1..1000 =", total, "(attendu 333833500)")

sortie = Path(os.environ["FREE_AI_OUTPUT_DIR"])
sortie.mkdir(parents=True, exist_ok=True)
(sortie / "preuve.txt").write_text(
    "execute sur %s, somme=%d" % (platform.node(), total), encoding="utf-8"
)
print("artefact ecrit : preuve.txt")

try:
    socket.setdefaulttimeout(5)
    socket.create_connection(("1.1.1.1", 443)).close()
    print("reseau      : disponible")
except Exception as exc:
    print("reseau      : bloque (%s)" % type(exc).__name__)
"""

ESSAI_HTML = r"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Essai - Sandbox</title>
<style>
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;max-width:900px;
 margin:34px auto;padding:0 18px;line-height:1.55}
h1{font-size:1.5rem;margin-bottom:4px}
.sous{opacity:.8;margin-top:0}
.banniere{padding:14px 16px;border-radius:14px;margin:16px 0;border:1px solid #bbb;background:#eef4fb}
.ligne{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:14px 0}
select,button{font:inherit;padding:9px 12px;border-radius:10px;border:1px solid #666;background:#fff}
button.primaire{background:#222;color:#fff;border-color:#222;cursor:pointer}
button[disabled]{opacity:.5;cursor:default}
textarea{font:13px ui-monospace,Consolas,monospace;width:100%;box-sizing:border-box;
 height:250px;padding:12px;border-radius:12px;border:1px solid #999}
pre{background:#f6f6f6;border:1px solid #ddd;border-radius:12px;padding:12px;
 overflow-x:auto;white-space:pre-wrap;word-break:break-word}
.ok{color:#1d6b32}.ko{color:#9b2116}
.avert{font-size:.86rem;opacity:.75}
.pied{margin-top:26px;padding-top:16px;border-top:1px solid #ddd;font-size:.9rem;opacity:.8}
</style></head><body>
<h1>Lancer un essai</h1>
<p class="sous">Le meme chemin que celui de l'agent, sans terminal : votre code part sur le
backend choisi, la reponse revient ici.</p>

<div id="banniere" class="banniere">Verification en cours...</div>

<div id="budget" class="banniere">Budget Modal : verification en cours...</div>

<div class="ligne">
  <label for="backend">Ou executer :</label>
  <select id="backend">
    <option value="auto">Automatique</option>
    <option value="modal">Modal - machine distante</option>
    <option value="local">Votre ordinateur, isole dans Docker</option>
    <option value="kaggle">Kaggle</option>
  </select>
  <label><input type="checkbox" id="gpu"> carte graphique</label>
  <button id="lancer" class="primaire">Lancer</button>
</div>
<!-- Cette phrase AFFIRMAIT << La carte graphique n'existe pas sur le backend
     local >>. Faux sur cet ordinateur depuis le 19/09/2026 : la carte y est, le
     bac a sable GPU tourne, et la page Video s'en sert. Releve du proprietaire
     le 20/09 : << affirmation fausse sur ce pc >>, puis << fais en sorte que le
     test soit fait, le client a ou pas de gpu >>. La page VERIFIE donc sur la
     machine (/essai/carte, sonde nvidia-smi reelle) au lieu de decreter. On ne
     DEMANDE a personne : un debutant ne sait pas si son PC a une carte, et
     c'est precisement pour lui que le Studio existe. -->
<p class="avert" id="carte">Carte graphique : verification en cours...</p>

<textarea id="code" spellcheck="false"></textarea>

<div id="etat" class="ligne"></div>
<pre id="sortie" hidden></pre>
<div id="artefacts" class="ligne"></div>

<div class="pied">Le code part au service local sur 127.0.0.1 ; il ne quitte votre machine
que si vous choisissez un backend distant.
<br><a href="/">Retour au Sandbox</a> &nbsp; <a href="/cles">Brancher Modal ou Kaggle</a></div>

<script>
const CLE = "__CLE__";
const DEMO = "__DEMO__";
const ENTETES = {"Authorization": "Bearer " + CLE, "Content-Type": "application/json"};
const OU = {modal:"Modal (machine distante)", local:"votre ordinateur, isole dans Docker",
            maison:"la carte de votre ordinateur, isolee dans Docker",
            kaggle:"Kaggle", colab:"Colab"};

document.getElementById("code").value = DEMO;

fetch("/etat").then(r => r.json()).then(d => {
  const b = document.getElementById("banniere");
  b.textContent = "En mode automatique, le code s'execute sur : "
    + (OU[d.backend_automatique] || d.backend_automatique) + "." + (d.backend_carte_ou_internet === "modal" ? " Un code qui demande une carte graphique passe sur la vôtre si elle est libre, sinon chez Modal ; un code qui demande Internet part chez Modal." : "");
  if(!d.modal.configure){ b.textContent += " Modal n'est pas branche : rien ne part sur une machine distante."; }
}).catch(() => {
  document.getElementById("banniere").textContent = "Etat non verifiable : le service Sandbox ne repond pas.";
});

// Le code envoye d'ici part sur Modal avec usage="autonome" : il DEPENSE, et
// cette page ne montrait aucun montant, alors que les pages video, chanson et
// dialogue en montrent un. Trouve le 20/09/2026 en validant les trois autres
// dans un navigateur. Meme fonction nommee que sur ces pages, pour que le test
// puisse l'executer dans node au lieu de relire le code.
function budgetTexte(b){
  const reel = (b.usd_reel !== null && b.usd_reel !== undefined
                && b.usd_reel >= b.usd_estime);
  return "Depense sur Modal ce mois-ci " + (reel ? "selon Modal" : "selon le Studio")
    + ", tous usages confondus : " + fr(b.usd, 2) + " $ sur "
    + fr(b.plafond_usd, 2) + " $. Ce que vous lancez ici est compte sur la part du "
    + "Sandbox : " + fr(b.reserve_autonome_usd, 2) + " $ que les pages video, chanson "
    + "et dialogue ne peuvent pas entamer, mais qui se depensent d'ici. "
    // Les 8 % decrivent la METHODE de comptage, pas le total affiche : ce total
    // court sur tout le mois et peut contenir des travaux comptes AVANT la
    // correction des tarifs du 20/09/2026, a des prix trop bas. Mesure faite ce
    // jour-la sur cette page : 1,39 $ estime contre 3,80 $ factures, soit 37 % --
    // annoncer << 8 % >> sur CE nombre-la serait faux de loin.
    + (reel
       ? "Chiffre releve chez Modal le " + dateFr(b.usd_reel_le) + " ; notre estimation locale dit "
         + fr(b.usd_estime, 2) + " $. La methode sous-compte d'environ 8 % (le processeur "
         + "reellement utilise depasse le coeur reserve), et ce total peut contenir des travaux "
         + "comptes avant le " + dateFr(b.prix_releve_le) + ", a des tarifs plus bas."
       : "Modal n'a pas repondu : c'est notre estimation locale. La methode sous-compte "
         + "d'environ 8 %, le processeur reellement utilise depassant le coeur reserve, et ce "
         + "total peut contenir des travaux comptes avant le " + dateFr(b.prix_releve_le)
         + ", a des tarifs plus bas.");
}

fetch("/budget/modal", {headers: ENTETES}).then(r => r.json()).then(d => {
  document.getElementById("budget").textContent = budgetTexte(d);
}).catch(() => {
  document.getElementById("budget").textContent =
    "Budget non verifiable : le service Sandbox ne repond pas.";
});

// La carte de CET ordinateur. La phrase d'avant decretait qu'il n'y en a pas ;
// celle-ci vient d'un nvidia-smi lance a l'instant.
const MODAL_PLUS_VITE = "Sur Modal, la carte consomme l'offre gratuite beaucoup "
  + "plus vite qu'un calcul sur processeur.";

function carteTexte(d){
  const c = (d && d.carte) || {};
  if(!c.vue){
    return "Cet ordinateur n'a pas de carte graphique utilisable par le Studio"
      + (c.motif ? " (" + c.motif + ")" : "")
      + ". Sur « Votre ordinateur », le code tourne sur le processeur. "
      + MODAL_PLUS_VITE;
  }
  return "Cet ordinateur a une carte : " + c.nom
    + (c.libre_mo !== null && c.libre_mo !== undefined
       ? " (" + moFr(c.libre_mo) + " libres sur " + moFr(c.totale_mo, "") + ")" : "")
    + ". La page Vidéo s'en sert pour fabriquer des clips gratuitement. "
    // Depuis le 21/09/2026 cette page s'en sert aussi. La phrase dit la regle
    // exacte, parce qu'une case qui marche << parfois >> sans dire quand est
    // aussi trompeuse qu'une case grisee sans raison.
    + "Cochez « carte graphique » et le code partira dessus, à une condition "
    + "vérifiée au moment du lancement : que personne d'autre ne la tienne. "
    + "Sinon il tourne sur le processeur, et la réponse vous dit laquelle des "
    + "deux a servi. Un calcul déjà en cours n'est jamais arrêté. "
    + MODAL_PLUS_VITE;
}

// La case a ete grisee du 20 au 21/09/2026 parce qu'elle ne faisait rien.
// Elle fait maintenant quelque chose : le code part sur la carte SI elle est
// libre a cet instant, et la fiche du travail dit ou il a tourne et pourquoi.
function accorderLaCase(){
  const case_ = document.getElementById("gpu");
  case_.disabled = false;
  case_.parentElement.title = document.getElementById("backend").value === "local"
    ? "Sur votre carte si elle est libre au moment du lancement ; sinon sur le "
      + "processeur, et la reponse vous dira laquelle."
    : "";
}

document.getElementById("backend").addEventListener("change", accorderLaCase);
accorderLaCase();

fetch("/essai/carte", {headers: ENTETES}).then(r => r.json()).then(d => {
  document.getElementById("carte").textContent = carteTexte(d);
}).catch(() => {
  document.getElementById("carte").textContent =
    "Carte graphique non verifiable : le service Sandbox ne repond pas.";
});

function afficher(d){
  const etat = document.getElementById("etat");
  const sortie = document.getElementById("sortie");
  const ou = OU[d.provider_effective] || d.provider_effective || "backend inconnu";
  // Kaggle ne rend pas de code de sortie : exiger exit_code === 0 affichait en rouge
  // une execution parfaitement reussie.
  const bien = d.status === "succeeded" && (d.exit_code === undefined || d.exit_code === null || d.exit_code === 0);
  etat.className = "ligne " + (bien ? "ok" : "ko");
  let texte = bien ? ("Termine sur " + ou) : ("Statut : " + d.status + " (" + ou + ")");
  if(d.exit_code !== undefined && d.exit_code !== null){ texte += " - code de sortie " + d.exit_code; }
  if(d.status === "needs_configuration"){ texte += ". Ce backend n'est pas branche : voir la page des cles."; }
  if(d.status === "handoff_ready"){ texte += ". Aucun backend automatique disponible : un notebook Colab a ete prepare."; }
  // La raison du placement, quand il y en a une. Sans elle, un repli sur le
  // processeur se lirait comme un lancement sur la carte.
  if(d.placement){ texte += ". " + d.placement; }
  etat.textContent = texte;

  let brut = d.stdout || "";
  if(d.stderr){ brut += "\n--- erreurs ---\n" + d.stderr; }
  if(d.error){ brut += "\n--- service ---\n" + d.error; }
  if(!brut && bien){
    // Kaggle n'expose pas la sortie standard dans la fiche du job : elle arrive
    // dans le fichier .log rapatrie avec les artefacts.
    brut = "Ce backend ne renvoie pas la sortie directement : elle est dans le fichier .log ci-dessous.";
  }
  sortie.hidden = !brut;
  sortie.textContent = brut;

  const arts = document.getElementById("artefacts");
  arts.innerHTML = "";
  (d.artifacts || []).forEach(a => {
    const b = document.createElement("button");
    b.textContent = "Telecharger " + a.name + " (" + a.size + " octets)";
    b.addEventListener("click", async () => {
      const r = await fetch("/artifacts/" + a.id, {headers: {"Authorization": "Bearer " + CLE}});
      const blob = await r.blob();
      const u = URL.createObjectURL(blob);
      const l = document.createElement("a");
      l.href = u; l.download = a.name; l.click();
      URL.revokeObjectURL(u);
    });
    arts.appendChild(b);
  });
}

document.getElementById("lancer").addEventListener("click", async () => {
  const bouton = document.getElementById("lancer");
  const etat = document.getElementById("etat");
  document.getElementById("sortie").hidden = true;
  document.getElementById("artefacts").innerHTML = "";
  bouton.disabled = true;
  etat.className = "ligne";
  etat.textContent = "Envoi...";
  try{
    const r = await fetch("/jobs", {method: "POST", headers: ENTETES, body: JSON.stringify({
      provider: document.getElementById("backend").value,
      code: document.getElementById("code").value,
      title: "Essai depuis la page Sandbox",
      gpu: document.getElementById("gpu").checked,
      internet: false
    })});
    if(!r.ok){
      const refus = await r.json().catch(() => ({}));
      etat.className = "ligne ko";
      etat.textContent = "Le service a refuse la demande (HTTP " + r.status + ")"
        + (typeof refus.detail === "string" ? " : " + refus.detail : ".");
      return;
    }
    let d = await r.json();
    const debut = Date.now();
    while(["queued", "routing", "running"].indexOf(d.status) >= 0){
      etat.textContent = "En cours (" + d.status + ", " + Math.round((Date.now() - debut) / 1000) + " s)...";
      await new Promise(f => setTimeout(f, 2000));
      const q = await fetch("/jobs/" + d.id, {headers: ENTETES});
      d = await q.json();
    }
    afficher(d);
  }catch(e){
    etat.className = "ligne ko";
    etat.textContent = "Le Sandbox local n'a pas repondu : " + e;
  }finally{
    bouton.disabled = false;
  }
});
</script>
</body></html>
"""


@app.get("/essai/carte")
def essai_carte(authorization: Optional[str] = Header(default=None)):
    """Cet ordinateur a-t-il une carte graphique ? Mesure, pas decret.

    La page AFFIRMAIT << La carte graphique n'existe pas sur le backend local >>.
    C'etait vrai le jour ou la phrase a ete ecrite, et faux depuis le 19/09/2026
    sur toute machine equipee : la surcouche `docker-compose.gpu.yml` donne la
    carte au gestionnaire ET un deuxieme bac a sable qui sait s'en servir. Un
    debutant lisait donc, sur un PC muni d'une 4090, que sa carte n'existe pas.

    Ce que cette route rend, et qui n'est pas la meme chose :
      - `carte` : le releve REEL de `nvidia-smi` a cette seconde (`vue` faux et
        `motif` rempli sur une machine sans carte -- jamais d'exception) ;
      - `bac_a_sable_gpu` : le deuxieme bac a sable est-il monte ;
      - `utilisee_par_cette_page` : vrai depuis le 21/09/2026 des qu'un bac a
        sable GPU est monte. Ce champ a ete faux du 20 au 21/09, et l'etait
        honnetement : la place qu'un code QUELCONQUE prendrait sur la carte
        n'est pas connue d'avance. Le proprietaire a tranche (REG-1) : on ne
        devine pas ce besoin -- il ne peut pas se mesurer -- on mesure
        l'OCCUPATION a l'instant du lancement. Un code qui deborde quand meme
        est arrete par CUDA en quelques secondes, dans un bac a sable, avec un
        message lisible ; il ne contamine aucun resultat. C'est ce qui separe
        ce cas d'un clip dont la duree n'a pas ete mesuree, ou un chiffre
        suppose se glisserait dans une mesure publiee.
    """
    auth(authorization)
    return {
        "carte": gpu_local.releve(),
        "bac_a_sable_gpu": bool(WORKER_GPU_URL),
        "utilisee_par_cette_page": bool(WORKER_GPU_URL),
    }


@app.get("/essai", response_class=HTMLResponse)
def essai_page():
    page = ESSAI_HTML.replace("__CLE__", KEY)
    # json.dumps rend un litteral JavaScript valide : guillemets, sauts de ligne et
    # antislashs du code de demonstration sont echappes au lieu d'etre colles tels quels.
    page = page.replace('"__DEMO__"', json.dumps(CODE_DEMO))
    return HTMLResponse(format_fr.avec_formateurs(page))


@app.get("/etat")
def etat(request: Request):
    """Etat reel des backends, sans secret ni authentification, pour que la page
    d'accueil dise ce qui marche au lieu d'annoncer Modal en principal alors
    qu'il est desactive et sans jeton. Ne rend que des booleens et, pour Kaggle,
    la raison d'une coupure."""
    raison = contexte_partage(request)
    return {
        "modal": {"configure": modal_configured(), "autorise": modal_enabled()},
        "local": {"disponible": True},
        "kaggle": {
            "configure": kaggle_configured(),
            "autorise": kaggle_enabled(),
            "automatique_permis": raison is None,
            "raison": raison,
            "acces_manuel": KAGGLE_MANUEL,
        },
        "colab": {"handoff": True},
        "backend_automatique": backend_automatique(),
        "backend_carte_ou_internet": backend_carte_ou_internet(),
    }


@app.get("/budget/modal")
def budget_modal_etat(authorization: Optional[str] = Header(default=None)):
    """Le compteur UNIQUE des depenses Modal, tous usages confondus.

    Les trois pages n'en montrent chacune qu'une tranche -- leur plafond, leur
    compte a elles. Celle-ci rend le total, la part reservee au bac a sable et
    la repartition par usage, qui est le seul endroit ou le quatrieme
    depensier devient visible.

    Authentifiee, comme /depenses/etat et contrairement a /etat : elle rend
    des montants, pas des booleens.

    Depuis le 20/09/2026 elle ne dit plus seulement l'estimation locale : `usd`
    est le plus grand de l'estimation (`usd_estime`) et du releve pris chez
    Modal (`usd_reel`, date dans `usd_reel_le`). Quand Modal ne repond pas,
    `usd_reel` vaut null et tout se passe comme avant, sur le plancher local.
    """
    auth(authorization)
    return budget_modal.lire()


@app.get("/depenses/etat")
def depenses_etat(
    forcer: bool = False,
    cycle: str = "this month",
    authorization: Optional[str] = Header(default=None),
):
    """Ce que Modal facture vraiment, demande a Modal.

    Authentifiee, contrairement a /etat : celle-ci ne rend pas des booleens mais
    des montants d'un compte. Separee de /chanson/etat a dessein : le bandeau du
    budget doit paraitre tout de suite, sans attendre un aller-retour reseau qui
    peut prendre des secondes ou echouer. La page appelle donc cette route
    ensuite, et se contente de l'estimation locale si elle ne repond pas.

    Ne remplace aucun garde-fou : budget_verifier() continue de refuser avant de
    lancer, hors ligne, sur l'estimation locale."""
    auth(authorization)
    return depenses.etat(cycle=cycle, forcer=forcer)


@app.get("/providers")
def providers(request: Request, authorization: Optional[str] = Header(default=None)):
    auth(authorization)
    raison = contexte_partage(request)
    return {
        "default": "auto",
        "automatic_order": ORDRE_AUTO_LOCAL_D_ABORD,
        "automatic_order_gpu_or_internet": ORDRE_AUTO,
        "automatic_order_gpu_without_internet": ORDRE_AUTO_CARTE_D_ICI,
        "modal": {
            "configured": modal_configured(),
            "enabled": modal_enabled(),
            "automatic": True,
            "primary_when_configured": "gpu_or_internet_jobs",
            "gpu_default": os.getenv("MODAL_GPU_DEFAULT", "T4"),
            "job_timeout_seconds": int(os.getenv("MODAL_JOB_TIMEOUT_SECONDS", "300")),
            "idle_timeout_seconds": int(os.getenv("MODAL_IDLE_TIMEOUT_SECONDS", "60")),
            "cleanup_grace_seconds": int(os.getenv("MODAL_CLEANUP_GRACE_SECONDS", "60")),
            "terminate_after_artifacts": True,
            "direct_url": "https://modal.com/",
        },
        "local": {
            "available": True,
            "automatic": True,
            "network": "disabled by worker",
            "timeout_seconds": int(os.getenv("SANDBOX_TIMEOUT_SECONDS", "120")),
        },
        "kaggle": {
            "configured": kaggle_configured(),
            "direct_url": KAGGLE_MANUEL,
            "automatic": raison is None,
            "disabled_reason": raison,
            # Kaggle n'accepte que la science des donnees : auto ne lui envoie
            # que les jobs gpu=true, et seulement si le worker local manque.
            "automatic_only_for": "gpu_jobs",
        },
        "colab": {
            "direct_url": "https://colab.research.google.com/",
            "api_beta_allowlist": True,
            "api_enabled": COLAB_API_ENABLED,
            # Vrai quand la personne a branche un carnet ouvert (/colab/etat).
            "automatic_execution": raison is None and colab_pont.PONT.branche(),
            "automatic_handoff": True,
            "note": "Direct access stays available; an open Colab notebook connected to the Studio runs jobs cell by cell; otherwise auto routing prepares a notebook handoff.",
        },
    }


@app.post("/jobs")
def create_job(req: JobRequest, request: Request, authorization: Optional[str] = Header(default=None)):
    auth(authorization)
    if len(req.code.encode()) > MAX_JOB_CODE:
        raise HTTPException(413, "Code too large")
    raison = contexte_partage(request)
    if req.provider == "kaggle" and raison:
        raise refus_kaggle(raison)
    jid = uuid.uuid4().hex
    job = {
        "id": jid,
        "provider": req.provider,
        "title": req.title,
        "gpu": req.gpu,
        "internet": req.internet,
        "status": "queued",
        "created_at": time.time(),
        "artifacts": [],
    }
    write_job(jid, job)
    if req.provider == "auto":
        threading.Thread(target=run_auto, args=(jid, req.code, req.gpu, req.internet),
                         kwargs={"kaggle_permis": raison is None}, daemon=True).start()
    elif req.provider == "modal":
        threading.Thread(target=run_modal, args=(jid, req.code, req.gpu, req.internet), daemon=True).start()
    elif req.provider == "local":
        threading.Thread(target=run_local, args=(jid, req.code, req.gpu), daemon=True).start()
    elif req.provider == "kaggle":
        threading.Thread(target=run_kaggle, args=(jid, req.code, req.gpu, req.internet), daemon=True).start()
    elif raison is None and colab_pont.PONT.branche():
        threading.Thread(target=run_colab, args=(jid, req.code, req.gpu), daemon=True).start()
    else:
        prepare_colab_handoff(jid, req.code)
    return read_job(jid)


@app.get("/jobs")
def list_jobs(authorization: Optional[str] = Header(default=None)):
    auth(authorization)
    out = []
    for p in sorted(JOBS.glob("*/job.json"), key=lambda x: x.stat().st_mtime, reverse=True)[:100]:
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            pass
    return out


def lien_de_telechargement(usage: str, jid: str) -> str:
    """L'adresse signee du fichier d'un travail fini, ou "" s'il n'en a pas."""
    if usage == "video":
        trouve, cle, jeton, ext = video_fichiers, "video", jeton_video, ".mp4"
    elif usage == "chanson":
        trouve, cle, jeton, ext = chanson_fichiers, "son", jeton_chanson, ".flac"
    else:
        trouve, cle, jeton, ext = dialogue_fichiers, "son", jeton_dialogue, ".wav"
    try:
        if not trouve(jid).get(cle):
            return ""
        nom = derniers.nom_de_fichier(read_job(jid).get("titre") or usage, ext)
    except HTTPException:
        return ""
    signe = jeton(jid)
    if not signe:
        return ""
    # Le fichier telecharge porte le titre du travail, pas « video.mp4 ».
    return "/%s/jobs/%s/fichier?cle=%s&telecharger=1&nom=%s" % (usage, jid, signe, nom)


def _route_derniers(usage: str):
    def derniers_travaux(authorization: Optional[str] = Header(default=None)):
        auth(authorization)
        return derniers.lister(JOBS, usage, lien=lambda jid: lien_de_telechargement(usage, jid))
    return derniers_travaux


def _route_suppression(usage: str):
    def supprimer_travail(jid: str, authorization: Optional[str] = Header(default=None)):
        """Efface un travail de cette page. En cours, il est d'abord arrete par
        la meme route que le bouton d'arret d'urgence, qui dit ce qu'elle a
        vraiment fait selon le fournisseur."""
        auth(authorization)
        if not derniers.id_sur(jid):
            raise HTTPException(404, "Travail inconnu.")
        job = read_job(jid)
        if usage not in job:
            raise HTTPException(404, "Ce travail n'est pas de cette page.")
        arret = ""
        if str(job.get("status") or "") in derniers.EN_COURS:
            arret = arreter_job(jid, authorization).get("detail", "")
        SUPPRIMES.add(jid)
        try:
            effaces = derniers.supprimer(JOBS, ART, usage, jid)
        except LookupError:
            raise HTTPException(404, "Travail inconnu.") from None
        except derniers.TravailEnCours:
            SUPPRIMES.discard(jid)
            raise HTTPException(409, "Ce travail tourne encore : il n'a pas pu être arrêté.") from None
        return {"id": jid, "supprime": True, "arret": arret, "effaces": len(effaces)}
    return supprimer_travail


for _usage in derniers.USAGES:
    app.get("/%s/derniers" % _usage, name="derniers_" + _usage)(_route_derniers(_usage))
    app.delete("/%s/jobs/{jid}" % _usage, name="supprimer_" + _usage)(_route_suppression(_usage))


@app.get("/jobs/{jid}")
def get_job(jid: str, authorization: Optional[str] = Header(default=None)):
    auth(authorization)
    return read_job(jid)


@app.get("/jobs/{jid}/colab-notebook")
def colab_notebook(jid: str, authorization: Optional[str] = Header(default=None)):
    auth(authorization)
    p = JOBS / jid / "free-ai-studio-colab.ipynb"
    if not p.exists():
        raise HTTPException(404, "No Colab notebook")
    return FileResponse(p, media_type="application/x-ipynb+json", filename=p.name)


def arreter_modal(jid: str) -> dict:
    """Termine les Sandbox Modal etiquetees par ce travail. Rend un constat.

    POURQUOI PAR ETIQUETTE, ET NON PAR remote_ref. modal_execute pose
    tags={"free-ai-studio-job": jid} a la CREATION de la machine, alors que
    remote_ref n'est ecrit dans la fiche qu'a la FIN. Le 17/09/2026, un fil est
    reste bloque 2335 s sans jamais atteindre son finally : la fiche n'avait
    donc aucun remote_ref -- et c'est exactement le cas ou l'on veut arreter.
    L'etiquette, elle, existe des la premiere seconde.

    La signature Sandbox.list(*, app_id, tags, client) a ete relevee sur le SDK
    installe (1.5.5) avant d'ecrire ceci : le filtrage par etiquette existe
    reellement, il n'est pas suppose.

    Aucune cle n'est manipulee : apply_stored_secrets() pose les jetons dans
    l'environnement du processus, comme pour depenses.py.
    """
    try:
        import modal
    except Exception as exc:  # noqa: BLE001
        return {"arretees": 0, "detail": f"SDK Modal indisponible : {type(exc).__name__}."}
    apply_stored_secrets()
    if not modal_configured():
        return {"arretees": 0, "detail": "Modal n'est pas branché ici : rien à arrêter."}
    nom = os.getenv("MODAL_APP_NAME", "free-ai-studio-sandbox").strip() or "free-ai-studio-sandbox"
    try:
        app_id = modal.App.lookup(nom, create_if_missing=False).app_id
        boites = list(modal.Sandbox.list(app_id=app_id, tags={"free-ai-studio-job": jid}))
    except Exception as exc:  # noqa: BLE001
        return {"arretees": 0, "detail": f"Modal n'a pas répondu ({type(exc).__name__}) : "
                                         "la machine n'a peut-être pas été arrêtée."}
    if not boites:
        return {"arretees": 0,
                "detail": "Aucune machine ne porte l'étiquette de ce travail chez Modal : "
                          "elle est déjà partie, rien n'est plus facturé."}
    arretees = 0
    for boite in boites:
        try:
            if boite.poll() is None:
                boite.terminate()
                arretees += 1
        except Exception:  # noqa: BLE001
            pass
    return {"arretees": arretees,
            "detail": f"{arretees} machine(s) arrêtée(s) chez Modal."}


# --- Reprendre ce qu'un redemarrage a laisse sans personne derriere lui -----
#
# DECISION DU PROPRIETAIRE, 22/09/2026 : readopter, et non arreter. Le fichier
# est deja paye ; on va le chercher.
#
# Le raisonnement -- quoi faire de quelle fiche, et avec quelle echeance -- est
# dans `reprise.py`, ou il se teste sans reseau. Ici, le branchement.

# Le demarrage peut lancer la reprise : c'est son seul point d'appel en
# production. Coupable par reglage, parce que la suite de tests charge ce module
# des dizaines de fois, chaque fois sur un dossier de travaux different -- une
# reprise qui partirait a chaque chargement ecrirait dans les fiches d'un autre
# test. Les tests appellent `reprendre_les_travaux()` eux-memes : c'est
# precisement ce qu'ils verifient.
REPRISE_AU_DEMARRAGE = os.getenv(
    "SANDBOX_REPRISE_AU_DEMARRAGE", "true").strip().lower() not in ("0", "false", "non")
# Entre deux coups de sonde dans une machine reprise. Quinze secondes : la meme
# cadence que la boucle Kaggle, et un `exec` distant n'est pas gratuit.
REPRISE_ATTENTE_S = float(os.getenv("SANDBOX_REPRISE_ATTENTE_SECONDS", "15"))
# Combien de temps on accepte d'attendre un calcul repris, compte depuis SON
# depart et non depuis la reprise. Le defaut suit la duree de vie d'une machine
# Modal : au-dela, elle n'existe plus, il n'y a plus rien a attendre.
REPRISE_LIMITE_S = float(os.getenv("SANDBOX_REPRISE_LIMITE_SECONDS", "3600"))

_MANIFESTE = ("import json,os; r='/tmp/free_ai_output'; "
              "print(json.dumps([os.path.join(dp,f) for dp,_,fs in os.walk(r) for f in fs]))")


def boites_du_travail(jid: str):
    """Les machines Modal etiquetees par ce travail.

    Rend une LISTE quand Modal a repondu -- vide si plus rien ne porte cette
    etiquette -- et None quand on n'a pas pu lui demander. La distinction n'est
    pas cosmetique : une liste vide fait conclure que la machine est partie et
    ferme le travail en echec, alors que None doit laisser la fiche tranquille.
    Un sondeur separe << pas ENCORE >> de << JAMAIS >>, et c'est ici la
    difference entre un travail perdu et un travail qu'on n'a pas su joindre.
    """
    try:
        import modal
    except Exception:  # noqa: BLE001
        return None
    apply_stored_secrets()
    if not modal_configured():
        return None
    nom = os.getenv("MODAL_APP_NAME", "free-ai-studio-sandbox").strip() or "free-ai-studio-sandbox"
    try:
        app_id = modal.App.lookup(nom, create_if_missing=False).app_id
        return list(modal.Sandbox.list(app_id=app_id, tags={"free-ai-studio-job": jid}))
    except Exception:  # noqa: BLE001
        return None


def processus_du_travail(boite) -> Optional[str]:
    """Le calcul du client tourne-t-il encore DANS la machine ?

    On ne demande pas a la machine : elle est creee avec `sleep` pour
    entrypoint, donc elle survit au calcul et `poll()` ne repondrait pas a la
    question. On cherche le processus. Rend la sortie de `pgrep`, ou None si la
    sonde elle-meme n'a pas repondu -- et None ne vaut pas << termine >>.
    """
    try:
        p = boite.exec("sh", "-c", "pgrep -f free_ai_job.py || true", timeout=30)
        p.wait()
        return p.stdout.read() or ""
    except Exception:  # noqa: BLE001
        return None


def ramasser_la_boite(boite, jid: str) -> list:
    """Descend ce que le calcul a laisse dans /tmp/free_ai_output.

    Meme chemin et meme nommage que `modal_execute`, pour qu'un fichier repris
    soit indiscernable d'un fichier rendu du premier coup.
    """
    local_out = JOBS / jid / "modal-output"
    local_out.mkdir(parents=True, exist_ok=True)
    try:
        mp = boite.exec("python", "-c", _MANIFESTE, timeout=30)
        mp.wait()
        chemins = json.loads(mp.stdout.read() or "[]")
    except Exception:  # noqa: BLE001
        chemins = []
    arts: list = []
    for idx, distant in enumerate(chemins[:1000]):
        try:
            rel = str(distant).removeprefix("/tmp/free_ai_output/")
            cible = local_out / ("%04d-%s" % (idx, clean_name(rel.replace("/", "__"))))
            boite.filesystem.copy_to_local(str(distant), cible)
            arts.append(add_artifact(jid, cible, "modal"))
        except Exception as exc:  # noqa: BLE001
            arts.append({"name": str(distant), "source": "modal", "skipped": True,
                         "reason": str(exc)[:300]})
    return arts


def _clore_par_ramassage(jid: str, boite) -> bool:
    """Ramasse, puis ecrit la fin. Rend True si un fichier est revenu.

    Le statut se DEDUIT de ce qu'on a ramasse, il ne se decide pas. Une machine
    vide ne devient pas un succes parce qu'on l'a retrouvee : on ne sait pas ce
    qui s'y est passe pendant notre absence, et le dire serait fabriquer un
    resultat.
    """
    arts = ramasser_la_boite(boite, jid)
    utiles = [a for a in arts if not a.get("skipped")]
    if not utiles:
        terminer_en_echec(jid, (
            "Reprise apres redemarrage : la machine a ete retrouvee, mais elle "
            "ne contenait aucun fichier. Ce qui s'y est passe pendant l'absence "
            "du Studio n'est pas connu."))
        return False
    job = read_job(jid)
    job.update({"status": "succeeded", "finished_at": time.time(),
                "artifacts": arts, "repris_apres_redemarrage": True})
    write_job(jid, job)
    return True


def _attendre_puis_ramasser(jid: str, boite, echeance: float) -> None:
    """Le fil de reprise d'un calcul qui tournait encore.

    Son echeance vient du DEPART du travail, pas de la reprise : offrir une
    horloge neuve a un travail deja vieux le ferait patienter pour rien. C'est
    la lecon du travail Kaggle reste << en cours >> 318 h.
    """
    while time.time() < echeance:
        if reprise.travail_fini_dans_la_boite(processus_du_travail(boite)):
            _clore_par_ramassage(jid, boite)
            return
        time.sleep(REPRISE_ATTENTE_S)
    terminer_en_echec(jid, (
        "Reprise apres redemarrage : le calcul tournait encore, et son delai "
        "d'origine est echu. Le Studio cesse d'attendre."))


def reprendre_les_travaux() -> dict:
    """Passe les fiches en revue et rend un constat chiffre.

    Ne touche jamais une fiche close, et ne promet jamais plus que ce qui est
    fait : `non_mesures` compte les travaux qu'on n'a pas su joindre, et ceux-la
    restent exactement comme ils etaient.
    """
    constat = {"repris": 0, "attendus": 0, "orphelins": 0,
               "non_mesures": 0, "laisses": 0}
    try:
        dossiers = sorted(p for p in JOBS.iterdir() if p.is_dir())
    except OSError:
        return constat
    for d in dossiers:
        jid = d.name
        try:
            fiche = read_job(jid)
        except Exception:  # noqa: BLE001
            continue
        quoi = reprise.que_faire(fiche)
        if quoi == reprise.RIEN:
            constat["laisses"] += 1
            continue
        if quoi == reprise.ORPHELIN:
            terminer_en_echec(jid, (
                "Reprise apres redemarrage : ce travail n'a plus personne "
                "derriere lui et rien ne permet de le retrouver. Il tournait "
                "sur cet ordinateur, ou bien il est parti sans laisser de "
                "reference."))
            constat["orphelins"] += 1
            continue
        if quoi == reprise.REPRENDRE_KAGGLE:
            limite = float(fiche.get("kaggle_limite_s")
                           or os.getenv("KAGGLE_JOB_TIMEOUT_SECONDS", "3600"))
            if reprise.echeance_depassee(fiche, limite=limite,
                                         marge=KAGGLE_MARGE_S,
                                         maintenant=time.time()):
                terminer_en_echec(jid, (
                    "Reprise après redémarrage : le délai d'origine de ce "
                    "travail Kaggle est échu depuis longtemps. Kaggle a arrêté "
                    "le notebook lui-même à l'échéance du -t qu'il avait reçu ; "
                    "seule la fiche disait encore « en cours »."))
                constat["orphelins"] += 1
            else:
                threading.Thread(target=run_kaggle_reprise, args=(jid,),
                                 name="reprise-kaggle-%s" % jid[:8],
                                 daemon=True).start()
                constat["attendus"] += 1
            continue
        # Modal.
        boites = boites_du_travail(jid)
        if boites is None:
            constat["non_mesures"] += 1
            continue
        if not boites:
            terminer_en_echec(jid, (
                "Reprise apres redemarrage : plus aucune machine ne porte "
                "l'etiquette de ce travail chez Modal. Elle s'est arretee "
                "pendant l'absence du Studio, et ce qu'elle a produit n'est "
                "plus accessible. Rien n'est plus facture."))
            constat["orphelins"] += 1
            continue
        boite = boites[0]
        if reprise.travail_fini_dans_la_boite(processus_du_travail(boite)):
            if _clore_par_ramassage(jid, boite):
                constat["repris"] += 1
            else:
                constat["orphelins"] += 1
            continue
        echeance = reprise.depart(fiche) + REPRISE_LIMITE_S
        threading.Thread(target=_attendre_puis_ramasser,
                         args=(jid, boite, echeance),
                         name="reprise-modal-%s" % jid[:8], daemon=True).start()
        constat["attendus"] += 1
    return constat


def run_kaggle_reprise(jid: str) -> None:
    """Reprend l'attente d'un notebook Kaggle deja pousse.

    On ne repousse RIEN : le notebook est chez Kaggle depuis le depart, et le
    relancer en ferait tourner deux sur le quota de l'utilisateur. On se
    contente de reprendre la surveillance, avec l'echeance d'origine.
    """
    fiche = read_job(jid)
    ref = str(fiche.get("remote_ref") or "").strip()
    if not ref:
        return
    limite = float(fiche.get("kaggle_limite_s")
                   or os.getenv("KAGGLE_JOB_TIMEOUT_SECONDS", "3600"))
    echeance = reprise.echeance_kaggle(fiche, limite=limite, marge=KAGGLE_MARGE_S)
    attendre_kaggle(jid, ref, echeance, limite)


def reprise_au_demarrage() -> dict:
    """Lance la reprise et ECRIT son constat au journal, toujours.

    Le constat etait calcule, rendu, puis jete par le fil qui l'appelait.
    Mesure le 22/09/2026 au premier redeploiement reel : le temoin Kaggle de
    318 h s'est bien ferme, sa fiche porte son motif, et le journal du
    gestionnaire ne disait rien. Une reprise qui ne trouve rien et une reprise
    qui n'a pas tourne rendaient donc le MEME silence -- et un fil daemon qui
    leve meurt sans un mot, ce qui ressemble trait pour trait a << il n'y
    avait rien a faire >>. Un sondeur separe << pas ENCORE >> de << JAMAIS >> ;
    un journal muet ne separe rien.

    Les cinq compteurs sont ecrits meme a zero : un zero est une reponse, et
    c'est celle qu'on lit les bons jours.
    """
    try:
        constat = reprendre_les_travaux()
    except Exception as exc:  # noqa: BLE001
        log.exception("Reprise au demarrage : elle a ECHOUE (%s). Les fiches "
                      "n'ont pas ete revues ; aucune n'a ete touchee.",
                      type(exc).__name__)
        return {"echec": type(exc).__name__}
    log.info("Reprise au demarrage : %d repris, %d attendus, %d orphelins, "
             "%d non mesures, %d laisses.",
             constat["repris"], constat["attendus"], constat["orphelins"],
             constat["non_mesures"], constat["laisses"])
    return constat


if REPRISE_AU_DEMARRAGE:
    # Dans un fil, meme regle que le compteur Modal plus haut : le demarrage
    # n'attend jamais un service distant.
    threading.Thread(target=reprise_au_demarrage, name="reprise-travaux",
                     daemon=True).start()


def arreter_maison(jid: str) -> dict:
    """Arrete le calcul sur la carte de cet ordinateur (24/09).

    Le bac a sable de la carte tue le script et tout ce qu'il a lance : la
    memoire de la carte est rendue. Un arret arrive avant le calcul est retenu
    la-bas, et le calcul ne part pas.
    """
    if not WORKER_GPU_URL:
        return {"arretees": 0,
                "detail": "Aucun bac à sable sur la carte de cet ordinateur : rien à arrêter."}
    try:
        with httpx.Client(timeout=15) as c:
            r = c.post(WORKER_GPU_URL + "/stop", headers={"Authorization": f"Bearer {WORKER_KEY}"},
                       json={"job_id": jid})
            r.raise_for_status()
            reponse = r.json()
    except Exception as exc:  # noqa: BLE001 -- l'echec de l'arret se DIT
        return {"arretees": 0,
                "detail": "Le calcul sur la carte de cet ordinateur n'a pas pu être arrêté "
                          f"({type(exc).__name__}) : il continue jusqu'à sa fin."}
    if reponse.get("en_cours"):
        return {"arretees": 1,
                "detail": "Le calcul sur la carte de cet ordinateur est arrêté : la carte est libérée."}
    return {"arretees": 0,
            "detail": "Le calcul n'avait pas encore commencé sur la carte de cet ordinateur : "
                      "il ne partira pas."}


@app.post("/jobs/{jid}/arreter")
def arreter_job(jid: str, authorization: Optional[str] = Header(default=None)):
    """Arret d'urgence d'un travail en cours.

    NE JAMAIS PROMETTRE PLUS QUE CE QUI EST FAIT. Le geste n'est pas le meme
    selon le fournisseur, et la reponse le dit mot pour mot :

    - Modal : la machine est reellement terminee (par etiquette). La facturation
      s'arrete.
    - Kaggle : il n'existe AUCUNE annulation. La CLI 2.2.4 n'a pas de commande
      pour ca, et l'API (cancel_kernel_session) reclame un numero de session
      qu'aucune reponse de l'envoi ni de l'etat ne donne (constat du 15/09,
      PLAN.md). Le Studio cesse donc d'attendre, et Kaggle arrete le notebook
      lui-meme a l'echeance du -t qu'il a recu. Le quota court jusque-la.
    - Local / Colab : rien a arreter a distance.

    ET DANS TOUS LES CAS, ON ECRIT LA FIN. C'est la lecon du 17/09 : un fil
    coince n'ecrit jamais son etat terminal, et la fiche reste << running >>
    pour toujours -- l'interface montre alors un travail qui n'existe plus.
    """
    auth(authorization)
    job = read_job(jid)
    statut = job.get("status")
    if statut not in ("queued", "running", "preparing", "submitting"):
        return {"id": jid, "status": statut, "deja_termine": True,
                "detail": "Ce travail est déjà terminé : rien n'a été arrêté."}

    fournisseur = (job.get("provider_effective") or job.get("provider") or "").strip()
    if fournisseur == "modal":
        constat = arreter_modal(jid)
    elif fournisseur == "kaggle":
        constat = {"arretees": 0,
                   "detail": "Kaggle n'a pas d'annulation : le Studio cesse d'attendre, "
                             "mais le notebook tourne jusqu'à l'échéance que Kaggle applique "
                             "lui-même, et votre quota court jusque-là."}
    elif fournisseur == "maison":
        constat = arreter_maison(jid)
    elif fournisseur == "colab":
        # Le fil du travail relit cette marque a chaque suivi (toutes les
        # colab_pont.SUIVI_S secondes) et tue le calcul dans le carnet.
        constat = {"arretees": 1 if colab_pont.PONT.branche() else 0,
                   "detail": ("Le calcul dans votre carnet Colab est tué à la prochaine vérification, "
                              "dans %d s au plus. Le carnet reste ouvert." % int(colab_pont.SUIVI_S))
                   if colab_pont.PONT.branche() else
                   "Le carnet Colab n'est plus branché : rien à arrêter depuis le Studio."}
    else:
        constat = {"arretees": 0,
                   "detail": f"Rien à arrêter à distance pour « {fournisseur or 'inconnu'} »."}

    job = read_job(jid)
    job.update({
        "status": "cancelled",
        "finished_at": time.time(),
        "arret_demande": True,
        # arret_detail vit dans une cle QUE PERSONNE D'AUTRE N'ECRIT. La fin de
        # travail reecrit status et error ; le 17/09 elle a ainsi detruit le
        # compte-rendu de cette route, et je n'ai plus pu dire si le bouton
        # avait termine une machine ou si elle etait morte seule.
        "arret_detail": constat["detail"],
        "error": "Arrêt demandé depuis le Studio. " + constat["detail"],
    })
    write_job(jid, job)
    return {"id": jid, "status": "cancelled", "deja_termine": False,
            "arretees": constat["arretees"], "detail": constat["detail"]}


@app.post("/jobs/{jid}/artifacts")
async def upload_job_artifact(jid: str, file: UploadFile = File(...), authorization: Optional[str] = Header(default=None)):
    auth(authorization)
    read_job(jid)
    name = clean_name(file.filename or "artifact.bin")
    tmp = JOBS / jid / ("upload-" + uuid.uuid4().hex + "-" + name)
    size = 0
    with tmp.open("wb") as f:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_UPLOAD:
                tmp.unlink(missing_ok=True)
                raise HTTPException(413, "Artifact too large")
            f.write(chunk)
    info = add_artifact(jid, tmp, "user-import")
    tmp.unlink(missing_ok=True)
    job = read_job(jid)
    job.setdefault("artifacts", []).append(info)
    write_job(jid, job)
    return info


@app.get("/artifacts")
def list_artifacts(authorization: Optional[str] = Header(default=None)):
    auth(authorization)
    out = []
    for p in sorted(ART.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            pass
    return out


@app.get("/artifacts/{aid}")
def download_artifact(aid: str, authorization: Optional[str] = Header(default=None)):
    auth(authorization)
    m = ART / f"{aid}.json"
    if not m.exists():
        raise HTTPException(404, "Unknown artifact")
    info = json.loads(m.read_text(encoding="utf-8"))
    p = ART / info["path"]
    if not p.exists() or p.is_symlink():
        raise HTTPException(404, "Missing artifact")
    return FileResponse(p, filename=info["name"], media_type="application/octet-stream")


# --- Video --------------------------------------------------------------------
# Seule fonction du Studio qui loue une carte graphique a la minute : elle a donc
# son compteur, son plafond, et un refus AVANT de lancer plutot qu'une facture
# apres coup. Le detail (modeles, prix, script envoye au GPU) est dans video.py.

# Bibliotheques installees une fois pour toutes dans l'image Modal : sans cela,
# chaque clip retelechargerait PyTorch pendant que la carte tourne a vide.
VIDEO_PAQUETS = (
    "torch", "torchvision", "diffusers>=0.35.0", "transformers", "accelerate",
    "sentencepiece", "protobuf", "ftfy", "imageio", "imageio-ffmpeg", "pillow",
)


def jeton_video(jid: str) -> str:
    """Laissez-passer pour UN fichier, a mettre dans une adresse sans danger.

    La balise <video> du navigateur ne sait pas envoyer d'en-tete : la
    permission doit donc voyager dans l'adresse. Y mettre la cle maitresse
    serait une faute -- une adresse se recopie, se retrouve dans l'historique du
    navigateur, dans un journal, dans un message ; celui qui la lit peut alors
    lancer n'importe quel calcul sur le compte Modal de l'utilisateur. Ce jeton
    n'ouvre qu'un seul fichier, en lecture, et ne dit rien de la cle qui l'a
    fabrique.
    """
    if not KEY:
        return ""
    return hmac.new(KEY.encode(), ("video:" + jid).encode(), hashlib.sha256).hexdigest()[:32]


def video_fichiers(jid: str) -> dict:
    """Retrouve la video et son resume parmi les artefacts du travail."""
    trouve = {}
    for art in read_job(jid).get("artifacts", []):
        nom = str(art.get("name", ""))
        if art.get("skipped") or not art.get("id"):
            continue
        if nom.endswith("video.mp4"):
            trouve["video"] = art
        elif nom.endswith("resume.json"):
            trouve["resume"] = art
    return trouve


def run_video(jid: str, code: str, gpu_type: str, ou: str):
    """Lance le clip, puis encaisse le temps de carte reellement consomme.

    Le temps est encaisse meme si le calcul echoue : une carte louee qui plante
    a la derniere minute a quand meme ete louee. Ne compter que les reussites
    donnerait un compteur menteur, donc un plafond qui ne tient pas.
    """
    debut = time.time()
    job = read_job(jid)
    job.update({"status": "running", "started_at": debut, "provider_effective": ou})
    write_job(jid, job)
    try:
        if ou == "maison":
            # La carte de cet ordinateur. Rien a encaisser : elle ne facture
            # rien. Le `finally` plus bas ne compte que la location, et c'est
            # pourquoi il teste `ou == "modal"` et non l'inverse.
            finish_execution(jid, "maison", maison_execute(jid, code))
            job = read_job(jid)
            if job.get("status") == "failed":
                # Qui tenait la carte A LA SECONDE de l'echec : relu plus tard,
                # a l'affichage, le voisin serait peut-etre deja parti.
                job["voisins_a_l_echec"] = gpu_local.voisins()
                write_job(jid, job)
            return
        if ou == "kaggle":
            # Kaggle ne facture rien : pas de compteur, mais un GPU plus petit et
            # un modele a retelecharger a chaque fois.
            run_kaggle(jid, code, True, True)
            return
        if ou == "colab":
            # Le carnet de la personne : rien a encaisser non plus. Sans carte
            # dans le carnet, l'echec dit quel menu ouvrir.
            finish_execution(jid, "colab", colab_execute(jid, code, True, video.DUREE_MAX_S))
            return
        donnees = modal_execute(
            jid, code, True, True,
            gpu_type=gpu_type,
            timeout_s=video.DUREE_MAX_S,
            memory_mb=int(os.getenv("VIDEO_MEMORY_MB", "16384")),
            paquets=VIDEO_PAQUETS,
            apt=("ffmpeg",),
            volume=video.VOLUME_MODELES,
            # Compte par video.budget_verifier()/budget_consommer(), juste
            # au-dessus et juste en dessous : pas deux fois.
            usage=None,
        )
        finish_execution(jid, "modal", donnees)
    except BackendUnavailable as exc:
        terminer_en_echec(jid, str(exc)[:1000])
    finally:
        if ou == "modal":
            reste = video.budget_consommer(gpu_type, time.time() - debut)
            job = read_job(jid)
            job["budget"] = reste
            write_job(jid, job)


def maison_prete() -> tuple[bool, str, bool]:
    """Le bac a sable de la carte a-t-il de quoi travailler, a cette seconde ?

    Il repond sur /health, qui dit aussi si les 34 Go de poids sont la. Ce
    detour vaut son appel : sans les poids, un clip routé << maison >>
    s'arrêterait au bout de dix minutes au lieu de partir tout de suite chez le
    loueur. Une demi-seconde d'attente contre dix minutes perdues.

    Rend trois choses, et la troisieme est nouvelle (20/09) : *est-ce que ca
    s'arrange tout seul ?* Une carte absente ne s'arrange pas -- le clip part
    chez le loueur, point. Des poids manquants, si : on LANCE le telechargement
    ici meme, et le client choisit d'attendre ou de payer. C'est la regle posee
    par le proprietaire -- << si on supprime, l'usage de la ressource demandee
    demarre par son telechargement >> -- et c'est ce qui rend le vidage de
    `scripts/ressources.*` sans danger."""
    if not WORKER_GPU_URL:
        return False, "Cet ordinateur n'a pas de carte branchee au Studio", False
    try:
        with httpx.Client(timeout=2.0) as c:
            etat = c.get(WORKER_GPU_URL + "/health").json()
    except Exception as exc:
        return False, "Le bac a sable de la carte ne repond pas (%s)" % type(exc).__name__, False
    if etat.get("poids_presents") is False:
        # Demarre, ou continue : `demarrer()` ne relance rien s'il tourne deja.
        e = poids_video.demarrer()
        if e["possible"]:
            return False, poids_video.phrase(e), True
        # Le decideur ne voit pas le cache (surcouche GPU incomplete) : on ne
        # peut pas telecharger a la place du client, on lui rend la commande.
        return False, ("Les 34 Go du modele video ne sont pas encore telecharges sur cet "
                       "ordinateur. Une seule fois, dans le dossier du Studio : "
                       + video.commande_telechargement()), False
    return True, "", False


def decider_ou_fabriquer(plan: dict, loueur: str, payload: dict) -> dict:
    """Ou ce clip se fabrique : la carte d'ici, ou la machine louee choisie.

    Trois choses arrivent de la page et n'ont rien a faire dans le module de
    decision, qui doit rester jugeable sans service autour :
      - `ou_calculer` : le reglage, quand le client vient de le changer dans la
        boite de dialogue sans le rendre permanent ;
      - `attendre` : le client a repondu << j'attends >> a une carte prise ; la
        demande revient ici avec cette marque et se comporte comme
        << toujours a la maison >>, c'est-a-dire qu'elle attend la carte ;
      - l'absence de bac a sable GPU : sans la surcouche compose, il n'y a rien
        a router, et la question ne se pose meme pas.
    """
    prete, motif, ca_s_arrange = maison_prete()
    if not prete and ca_s_arrange:
        # Les poids se telechargent MAINTENANT, parce que ce clip les demande.
        # Meme boite que pour une carte prise, et pour la meme raison : ce n'est
        # pas une panne, c'est une attente dont le client connait le prix. La
        # page relance toute seule toutes les 30 s ; quand les 34 Go sont la,
        # le clip part ici et ne coute rien.
        prix = video.prix_estime(plan["qualite"], plan["duree"])
        attendre = bool(payload.get("attendre"))
        return {
            "ou": ou_calculer.ATTENTE if attendre else ou_calculer.ON_DEMANDE,
            "reglage": ou_calculer.TOUJOURS_MAISON if attendre else ou_calculer.reglage_lu(),
            "titre": "Le modèle vidéo se télécharge",
            "pourquoi": motif + (
                " Attendre ne coûte rien ; louer chez %s coûte %s."
                % (loueur.capitalize(),
                   ("environ " + format_fr.en_dollars(prix, 3)) if prix is not None
                   else "ce que la page affiche")),
            "besoin_mo": None,
            "carte": {"vue": False, "motif": motif},
            "prix_estime_usd": prix,
            "sorties": [ou_calculer.ATTENTE, ou_calculer.MODAL, "annuler"],
        }
    reglage_demande = (ou_calculer.TOUJOURS_MAISON if payload.get("attendre")
                       else str(payload.get("ou_calculer") or "").strip()
                       or ou_calculer.reglage_lu())
    if not prete and reglage_demande == ou_calculer.TOUJOURS_MAISON:
        # << Toujours a la maison >> promet que rien ne part sans accord. Jusqu'au
        # 23/09/2026 ce chemin louait quand meme, avant meme de lire le reglage.
        # Rien ne part : le client choisit entre louer et annuler. Sans carte
        # (le cas de la plupart des clients), le reglage par defaut << maison si
        # libre >> ne passe pas ici et le clip part chez le loueur, prix dit.
        prix = video.prix_estime(plan["qualite"], plan["duree"])
        return {
            "ou": ou_calculer.ON_DEMANDE,
            "reglage": ou_calculer.TOUJOURS_MAISON,
            "titre": "Votre carte ne répond pas",
            "pourquoi": ("%s. Vous avez réglé « toujours à la maison » : rien n'est "
                         "parti, rien n'est facturé. Relancez le Studio pour réveiller "
                         "la carte, ou louez chez %s." % (motif, loueur.capitalize())),
            "besoin_mo": None,
            "carte": {"vue": False, "motif": motif},
            "prix_estime_usd": prix,
            "sorties": [ou_calculer.MODAL, "annuler"],
        }
    if not prete:
        return {
            "ou": ou_calculer.MODAL,
            "reglage": ou_calculer.TOUJOURS_MODAL,
            "pourquoi": "%s : le clip part chez %s." % (motif, loueur.capitalize()),
            "besoin_mo": None,
            "carte": {"vue": False, "motif": motif},
            "prix_estime_usd": video.prix_estime(plan["qualite"], plan["duree"]),
            "sorties": [],
        }
    reglage = str(payload.get("ou_calculer") or "").strip() or None
    if payload.get("attendre"):
        # << J'attends >> vaut, pour CETTE demande seulement, le reglage le plus
        # ferme : on reste sur la carte d'ici, quoi qu'il en coute en minutes.
        reglage = ou_calculer.TOUJOURS_MAISON
    return ou_calculer.decider(
        plan["resume_public"],
        video.images_maison(plan["duree"]),
        prix_estime_usd=video.prix_estime(plan["qualite"], plan["duree"]),
        reglage=reglage,
        loueur=loueur.capitalize(),
        # Une duree que le loueur ne sait pas faire ne doit jamais lui etre
        # proposee : elle y serait rabattue sur une plus courte, en silence.
        loueur_peut=video.loueur_sait_faire(plan["duree"]),
    )


@app.post("/video/enrichir")
async def video_enrichir(request: Request, authorization: Optional[str] = Header(default=None)):
    """La description allongee par le chat gratuit, pour que la page la MONTRE.

    Rien ne part au calcul d'ici : la page remplace le texte, la personne relit,
    puis lance. Un chat muet rend une phrase, jamais une description vide."""
    auth(authorization)
    exiger_json(request)
    exiger_page_du_studio(request)
    payload = await corps_json(request)
    texte = " ".join(str(payload.get("description") or "").split())[:2000]
    if not texte:
        raise HTTPException(400, "Il faut d'abord décrire la scène en quelques mots.")
    # La traduction en anglais est toujours faite ; l'enrichissement, sauf si
    # la case est decochee (24/09 : « en grisé si obligatoire […] ou
    # modifiable enrichissement »).
    enrichir = payload.get("enrichir", True) is not False
    try:
        brut = await asyncio.to_thread(composite.appeler_le_modele,
                                       video.consigne_de_preparation(texte, enrichir))
    except composite.CompositeRefuse as exc:
        raise HTTPException(503, exc.phrase) from exc
    except Exception as exc:  # noqa: BLE001 -- reseau, delai : une phrase, pas une trace
        raise HTTPException(503, "Le chat ne répond pas : la description n'a pas pu "
                                 "être préparée. Vous pouvez l'écrire vous-même en "
                                 "anglais.") from exc
    enrichie = video.nettoyer_preparee(brut, enrichir)
    if not enrichie:
        raise HTTPException(502, "Le chat a rendu une réponse inutilisable : la "
                                 "description reste la vôtre.")
    return {"originale": texte, "enrichie": enrichie, "enrichir": enrichir}


@app.get("/video/budget")
def video_budget(request: Request, authorization: Optional[str] = Header(default=None)):
    auth(authorization)
    raison = contexte_partage(request)
    return {
        "budget": video.budget_lire(),
        "modeles": video.MODELES,
        "durees": video.DUREES,
        "modal_configure": modal_configured(),
        "kaggle_configure": kaggle_configured(),
        "kaggle_permis": raison is None,
        "kaggle_raison": raison,
        # Le temps d'un clip sur Kaggle, par duree : la page le montre quand
        # Kaggle est choisi, pour qu'on le lance en tache de fond (24/09).
        "kaggle_temps": {d: video.secondes_kaggle(d) for d in video.DUREES},
    }


@app.get("/video/poids/etat")
def video_poids_etat(request: Request, authorization: Optional[str] = Header(default=None)):
    """Ou en sont les 34 Go du modele video, en chiffres.

    Sert a deux choses : la page, qui montre l'avancement pendant l'attente, et
    `scripts/ressources.*`, qui dit au client ce qu'il occupe et ce qu'il rend.
    Ne DEMARRE rien : consulter n'est pas demander."""
    auth(authorization)
    e = poids_video.etat()
    e["phrase"] = poids_video.phrase(e)
    return e


@app.get("/video/ou-calculer")
def video_ou_calculer_lire(request: Request, authorization: Optional[str] = Header(default=None)):
    """Le reglage du client, et de quoi le lui montrer sans qu'il devine."""
    auth(authorization)
    return {
        "reglage": ou_calculer.reglage_lu(),
        "reglages": list(ou_calculer.REGLAGES),
        "defaut": ou_calculer.REGLAGE_DEFAUT,
        "carte_possible": bool(WORKER_GPU_URL),
        "durees_maison": video.DUREES_MAISON,
        # TROIS listes differentes, et la page ne doit en confondre aucune :
        # ce que le menu OFFRE, les durees dont la PLACE a ete relevee sur un
        # vrai clip, et celles dont le TEMPS a ete chronometre aux 50 passes de
        # la production. La place a ete mesuree a 2 passes et n'en depend pas
        # (temoin du 21/09 a 0,1 %) ; le temps en depend du simple au double.
        "durees_mesurees": video.durees_mesurees(),
        "durees_chronometrees": video.durees_chronometrees(),
    }


@app.post("/video/ou-calculer")
async def video_ou_calculer_ecrire(request: Request, authorization: Optional[str] = Header(default=None)):
    auth(authorization)
    exiger_json(request)
    exiger_page_du_studio(request)
    payload = await corps_json(request)
    try:
        pose = ou_calculer.reglage_ecrit(str(payload.get("reglage") or ""))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"reglage": pose}


@app.post("/video/creer")
async def video_creer(request: Request, authorization: Optional[str] = Header(default=None)):
    auth(authorization)
    payload = await request.json()
    # `ou` ne dit plus OU le clip se fabrique : il dit quelle machine on LOUE si
    # la maison ne le prend pas. C'est `ou_calculer.decider()` qui tranche entre
    # la carte d'ici et cette location -- ou qui rend la question au client.
    ou = str(payload.get("ou") or "modal")
    if ou not in ("modal", "kaggle", "colab"):
        ou = "modal"
    if ou == "kaggle":
        raison = contexte_partage(request)
        if raison:
            raise refus_kaggle(raison)
    if ou == "colab":
        raison = contexte_partage(request)
        if raison:
            raise HTTPException(403, "Colab piloté est coupé ici (%s) : le carnet branché serait "
                                     "celui d'une seule personne." % raison)
        if not colab_pont.PONT.branche():
            raise HTTPException(503, colab_pont.PHRASE_ABSENT)
    try:
        plan = video.preparer(payload, pour_modal=(ou == "modal"))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    decision = decider_ou_fabriquer(plan, ou, payload)
    if decision["ou"] in (ou_calculer.ON_DEMANDE, ou_calculer.ATTENTE):
        # 409 et non 503 : rien n'est en panne. La carte est prise, et c'est le
        # client qui dit quoi faire -- attendre, louer, ou renoncer. La page
        # renvoie la meme demande avec `attendre: true` ou avec
        # `ou_calculer: "toujours-modal"`. L'attente vit dans la page et non
        # dans le service : une file cote serveur n'a pas ete chiffree, et on
        # ne promet pas ce qu'on n'a pas mesure.
        raise HTTPException(409, detail=decision)

    if decision["ou"] == ou_calculer.MAISON:
        try:
            plan = video.preparer(payload, pour_modal=False, maison=True)
        except ValueError as exc:
            # La maison a ete choisie puis s'est revelee incapable : on le dit,
            # on ne bascule pas en silence sur une location payante.
            raise HTTPException(400, str(exc)) from exc
        ou = "maison"

    if ou == "modal":
        if not modal_configured():
            raise HTTPException(503, "Modal n'est pas branche. Ouvrez la page « Brancher Modal "
                                     "ou Kaggle » et collez les deux valeurs du jeton Modal.")
        try:
            video.budget_verifier(plan["gpu"], video.DUREE_MAX_S)
        except video.BudgetDepasse as exc:
            raise HTTPException(429, str(exc)) from exc
    elif ou == "kaggle" and not kaggle_configured():
        raise HTTPException(503, "Kaggle n'est pas branche. Ouvrez la page « Brancher Modal "
                                 "ou Kaggle » et collez votre nom d'utilisateur et votre cle Kaggle.")

    code = video.construire_script(plan["demande"])
    fiche = dict(plan["resume_public"])
    if ou == "kaggle":
        # La table des modeles porte la carte LOUEE chez Modal ; Kaggle donne
        # un T4. La fiche disait « L4 » pour le clip Kaggle du 23/09.
        fiche["carte"] = "T4 (Kaggle)"
    elif ou == "colab":
        # La carte que Colab donnera n'est connue qu'au lancement ; la
        # cellule de depart la lit (`nvidia-smi -L`) et la fiche la reprend.
        fiche["carte"] = "celle de votre carnet Colab (T4 gratuite si Colab en donne une)"
    jid = uuid.uuid4().hex
    write_job(jid, {
        "id": jid,
        "provider": ou,
        "title": "Free AI Studio video",
        "gpu": True,
        "internet": True,
        "status": "queued",
        "created_at": time.time(),
        "artifacts": [],
        "video": fiche,
        "titre": derniers.titre(payload, "video"),
        # Pourquoi ce clip part la plutot qu'ailleurs, garde avec le travail :
        # la page le montre en deux mots, et un journal le relit six mois plus
        # tard sans avoir a refaire le raisonnement.
        "ou_calculer": decision,
    })
    threading.Thread(target=run_video, args=(jid, code, plan["gpu"], ou), daemon=True).start()
    return read_job(jid)


@app.get("/video/jobs/{jid}")
def video_job(jid: str, authorization: Optional[str] = Header(default=None)):
    auth(authorization)
    job = read_job(jid)
    fichiers = video_fichiers(jid)
    sortie = {
        "id": jid,
        "status": job.get("status"),
        "created_at": job.get("created_at"),
        "titre": job.get("titre") or "",
        "fournisseur": job.get("provider_effective") or job.get("provider"),
        "stdout": job.get("stdout", ""),
        "stderr": job.get("stderr", ""),
        "message": job.get("error") or (
            video.phrase_d_echec(job.get("stderr", ""),
                                 maison=bool((job.get("video") or {}).get("maison")),
                                 voisins=job.get("voisins_a_l_echec"))
            if job.get("status") == "failed" else ""),
        # Ce que le bouton d'arret a vraiment fait, dit par la page vidéo.
        "arret_detail": job.get("arret_detail") or "",
        "video": job.get("video"),
        # Ou ce clip a ete fabrique, et pourquoi la. Deux mots sur la page,
        # et de quoi ne pas refaire le raisonnement six mois plus tard.
        "ou_calculer": job.get("ou_calculer"),
    }
    if fichiers.get("video"):
        sortie["video_url"] = f"/video/jobs/{jid}/fichier?cle={jeton_video(jid)}"
    if fichiers.get("resume"):
        try:
            chemin = ART / fichiers["resume"]["path"]
            sortie["resume"] = json.loads(chemin.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    return sortie


@app.get("/video/jobs/{jid}/fichier")
def video_fichier(jid: str, cle: str = Query(default=""),
                  telecharger: int = Query(default=0), nom: str = Query(default="")):
    attendu = jeton_video(jid)
    # compare_digest compare en temps constant : le temps de reponse ne dit pas
    # combien de caracteres du jeton etaient bons.
    if not attendu or not hmac.compare_digest(cle, attendu):
        raise HTTPException(401, "Unauthorized")
    art = video_fichiers(jid).get("video")
    if not art:
        raise HTTPException(404, "Pas de video pour ce travail")
    chemin = ART / art["path"]
    if not chemin.exists() or chemin.is_symlink():
        raise HTTPException(404, "Fichier absent")
    if not telecharger:
        # Meme adresse pour lire et pour enregistrer, mais pas la meme reponse :
        # annoncer une piece jointe a un lecteur video, c'est lui demander de
        # ranger un fichier au lieu de le jouer. Sans le drapeau, on sert le
        # fichier tel quel et la balise <video> le lit.
        return FileResponse(chemin, media_type="video/mp4")
    # Le nom vient de la page, donc de la description tapee par l'utilisateur :
    # il passe par le meme nettoyage que tout nom de fichier venu du dehors.
    propre = clean_name(nom) if nom else ""
    if propre.lower().endswith(".mp4"):
        propre = propre[:-4]
    propre = propre.strip("._-")
    return FileResponse(chemin, media_type="video/mp4", filename=(propre or "video") + ".mp4")


@app.get("/video", response_class=HTMLResponse)
def video_page():
    # Le menu des durees est fabrique a chaque affichage : il suit la loi
    # memoire, qui suit les clips mesures. Un menu ecrit en dur se serait
    # perime des le premier clip plus long.
    return HTMLResponse(derniers.dans_la_page(format_fr.avec_formateurs(
        video.PAGE_HTML
        .replace("__OPTIONS_DUREE__", video.options_duree_html())
        .replace("__QUALITE_LOUEE__", video.QUALITE_LOUEE_PAR_DEFAUT)
        .replace("__CLE__", KEY)), "video"))


# --- Chanson ------------------------------------------------------------------
# Des paroles et un style, chantes par YuE2-3B. Meme principe que la video :
# Modal compte et refuse avant de lancer ; Kaggle est gratuit et reste coupe en
# contexte partage ; Colab recoit un carnet que la personne lance elle-meme.
# Le detail (modele, prix, script envoye au GPU, page) est dans chanson.py.


def jeton_chanson(jid: str) -> str:
    """Laissez-passer pour UN fichier, comme jeton_video : la balise <audio> ne
    sait pas envoyer d'en-tete, et la cle maitresse ne va jamais dans une adresse."""
    if not KEY:
        return ""
    return hmac.new(KEY.encode(), ("chanson:" + jid).encode(), hashlib.sha256).hexdigest()[:32]


def chanson_fichiers(jid: str) -> dict:
    """Retrouve le son, la partition et le resume parmi les artefacts du travail."""
    trouve = {}
    for art in read_job(jid).get("artifacts", []):
        nom = str(art.get("name", ""))
        if art.get("skipped") or not art.get("id"):
            continue
        for suffixe, cle in (("chanson.flac", "son"), ("partition.abc", "partition"), ("resume.json", "resume")):
            if nom.endswith(suffixe):
                trouve[cle] = art
    return trouve


def run_chanson(jid: str, code: str, ou: str):
    """Lance la chanson, puis encaisse le temps Modal reellement consomme, echec compris."""
    debut = time.time()
    job = read_job(jid)
    job.update({"status": "running", "started_at": debut, "provider_effective": ou})
    write_job(jid, job)
    try:
        if ou == "kaggle":
            run_kaggle(jid, code, True, True, machine_shape=chanson.KAGGLE_MACHINE,
                       timeout_s=chanson.KAGGLE_DELAI_S)
            return
        donnees = modal_execute(
            jid, code, True, True,
            gpu_type=chanson.GPU_MODAL,
            timeout_s=chanson.DUREE_MAX_S,
            memory_mb=chanson.MEMOIRE_MB,
            paquets=chanson.PAQUETS_MODAL,
            volume=chanson.VOLUME_MODELES,
            # Compte par chanson.budget_verifier()/budget_consommer(), juste
            # au-dessus et juste en dessous : pas deux fois.
            usage=None,
        )
        finish_execution(jid, "modal", donnees)
    except BackendUnavailable as exc:
        terminer_en_echec(jid, str(exc)[:1000])
    finally:
        if ou == "modal":
            reste = chanson.budget_consommer(chanson.GPU_MODAL, time.time() - debut)
            job = read_job(jid)
            job["budget"] = reste
            write_job(jid, job)


async def corps_json(request: Request) -> dict:
    try:
        payload = await request.json()
    except ValueError as exc:
        raise HTTPException(400, "Corps JSON attendu.") from exc
    if not isinstance(payload, dict):
        raise HTTPException(400, "Corps JSON attendu.")
    return payload


@app.get("/chanson/etat")
def chanson_etat(request: Request, authorization: Optional[str] = Header(default=None)):
    auth(authorization)
    raison = contexte_partage(request)
    return {
        "budget": chanson.budget_lire(),
        "modele": chanson.MODELE,
        # La LoRA est un CHOIX offert a la personne : sa licence doit voyager
        # avec l'option pour s'afficher la ou l'on choisit, pas en note de pied.
        "lora": chanson.LORA,
        "durees": chanson.DUREES,
        "carte_modal": chanson.GPU_MODAL,
        "cout_max_modal_usd": round(chanson.prix_seconde(chanson.GPU_MODAL) * chanson.DUREE_MAX_S, 3),
        "modal_configure": modal_configured(),
        "kaggle_configure": kaggle_configured(),
        "kaggle_permis": raison is None,
        "kaggle_raison": raison,
    }


@app.post("/chanson/creer")
async def chanson_creer(request: Request, authorization: Optional[str] = Header(default=None)):
    auth(authorization)
    payload = await corps_json(request)
    ou = str(payload.get("ou") or "modal")
    if ou not in ("modal", "kaggle"):
        ou = "modal"
    if ou == "kaggle":
        raison = contexte_partage(request)
        if raison:
            raise refus_kaggle(raison)
    try:
        plan = chanson.preparer(payload, ou)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    if ou == "modal":
        if not modal_configured():
            raise HTTPException(503, "Modal n'est pas branché. Ouvrez la page « Brancher Modal "
                                     "ou Kaggle » et collez les deux valeurs du jeton Modal.")
        try:
            chanson.budget_verifier(plan["gpu"], chanson.DUREE_MAX_S)
        except chanson.BudgetDepasse as exc:
            raise HTTPException(429, str(exc)) from exc
    elif not kaggle_configured():
        raise HTTPException(503, "Kaggle n'est pas branché. Ouvrez la page « Brancher Modal "
                                 "ou Kaggle » et collez votre nom d'utilisateur et votre clé Kaggle.")

    code = chanson.construire_script(plan["demande"])
    jid = uuid.uuid4().hex
    write_job(jid, {
        "id": jid,
        "provider": ou,
        "title": "Free AI Studio chanson",
        "gpu": True,
        "internet": True,
        "status": "queued",
        "created_at": time.time(),
        "artifacts": [],
        "chanson": plan["resume_public"],
        "titre": derniers.titre(payload, "chanson"),
    })
    threading.Thread(target=run_chanson, args=(jid, code, ou), daemon=True).start()
    return read_job(jid)


@app.post("/chanson/colab")
async def chanson_colab(request: Request, authorization: Optional[str] = Header(default=None)):
    """Le carnet part chez la personne, qui le lance sur SON compte Google : ni
    identifiant ni credit du proprietaire n'y est engage, d'ou l'absence de garde."""
    auth(authorization)
    payload = await corps_json(request)
    try:
        plan = chanson.preparer(payload, "colab")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    carnet = chanson.carnet_colab(plan["demande"])
    return Response(
        json.dumps(carnet, ensure_ascii=False, indent=1),
        media_type="application/x-ipynb+json",
        headers={"Content-Disposition": 'attachment; filename="chanson-colab.ipynb"'},
    )


@app.get("/chanson/jobs/{jid}")
def chanson_job(jid: str, authorization: Optional[str] = Header(default=None)):
    auth(authorization)
    job = read_job(jid)
    fichiers = chanson_fichiers(jid)
    sortie = {
        "id": jid,
        "status": job.get("status"),
        "created_at": job.get("created_at"),
        "titre": job.get("titre") or "",
        "stdout": job.get("stdout", ""),
        "stderr": job.get("stderr", ""),
        "message": job.get("error") or "",
        "arret_detail": job.get("arret_detail") or "",
        "chanson": job.get("chanson"),
        # Le bouton d'arret change selon le fournisseur : Kaggle n'a pas
        # d'annulation, la page ne doit pas promettre un arret (23/09/2026).
        "fournisseur": job.get("provider_effective") or job.get("provider") or "",
    }
    if fichiers.get("son"):
        sortie["son_url"] = f"/chanson/jobs/{jid}/fichier?cle={jeton_chanson(jid)}"
    try:
        if fichiers.get("resume"):
            sortie["resume"] = json.loads((ART / fichiers["resume"]["path"]).read_text(encoding="utf-8"))
        if fichiers.get("partition"):
            sortie["partition"] = (ART / fichiers["partition"]["path"]).read_text(encoding="utf-8")[:20000]
    except (OSError, ValueError):
        pass
    return sortie


@app.get("/chanson/jobs/{jid}/fichier")
def chanson_fichier(jid: str, cle: str = Query(default=""),
                    telecharger: int = Query(default=0), nom: str = Query(default="")):
    attendu = jeton_chanson(jid)
    if not attendu or not hmac.compare_digest(cle, attendu):
        raise HTTPException(401, "Unauthorized")
    art = chanson_fichiers(jid).get("son")
    if not art:
        raise HTTPException(404, "Pas de chanson pour ce travail")
    chemin = ART / art["path"]
    if not chemin.exists() or chemin.is_symlink():
        raise HTTPException(404, "Fichier absent")
    if not telecharger:
        return FileResponse(chemin, media_type="audio/flac")
    propre = clean_name(nom) if nom else ""
    if propre.lower().endswith(".flac"):
        propre = propre[:-5]
    propre = propre.strip("._-")
    return FileResponse(chemin, media_type="audio/flac", filename=(propre or "chanson") + ".flac")


@app.get("/chanson", response_class=HTMLResponse)
def chanson_page():
    return HTMLResponse(derniers.dans_la_page(format_fr.avec_formateurs(
        chanson.PAGE_HTML.replace("__CLE__", KEY)), "chanson"))


# abcjs 6.7.0 (MIT) : la bibliotheque qui dessine les portees sur /chanson.
# SERVIE PAR LE SERVICE, JAMAIS PAR UN CDN : le Studio doit marcher sans acces
# reseau, et une page qui depend d'un hebergeur tiers casse le jour ou il bouge.
# Aucun jeton exige, et c'est voulu : une balise <script src> ne peut pas porter
# d'en-tete Authorization. C'est du code public, au meme titre que la page
# /chanson elle-meme qui est deja servie sans jeton.
@app.get("/chanson/abcjs.js")
def chanson_abcjs():
    chemin = Path(__file__).with_name("abcjs-basic-min.js")
    if not chemin.is_file():
        # Arrive si le Dockerfile n'a pas copie le fichier. On le dit au lieu de
        # servir du vide : une page muette ferait chercher l'erreur ailleurs.
        raise HTTPException(status_code=404,
                            detail="abcjs-basic-min.js absent de l'image")
    return FileResponse(chemin, media_type="application/javascript")


# --- Dialogue -----------------------------------------------------------------
# Un script a plusieurs voix, rendu facon podcast par FireRedTTS-2. Meme
# principe que la chanson pour le compteur, le laissez-passer et l'arret
# d'urgence -- MAIS UN SEUL ENDROIT : Modal. Le chemin gratuit de la chanson
# (carte T4 de Kaggle) a ete essaye en vrai le 15/09 ; celui-ci ne l'a jamais
# ete nulle part, et proposer un endroit non verifie reviendrait a vendre un
# essai dont personne ne connait le resultat.
# Le detail (modele, licence, prix, script envoye au GPU, page) est dans
# dialogue.py.


def jeton_dialogue(jid: str) -> str:
    """Laissez-passer pour UN fichier, comme jeton_chanson : la balise <audio>
    ne sait pas envoyer d'en-tete, et la cle maitresse ne va jamais dans une
    adresse. Le prefixe differe de celui de la chanson, sinon un jeton obtenu
    sur une route ouvrirait le fichier de l'autre."""
    if not KEY:
        return ""
    return hmac.new(KEY.encode(), ("dialogue:" + jid).encode(), hashlib.sha256).hexdigest()[:32]


def dialogue_fichiers(jid: str) -> dict:
    """Retrouve le son et le resume parmi les artefacts du travail."""
    trouve = {}
    for art in read_job(jid).get("artifacts", []):
        nom = str(art.get("name", ""))
        if art.get("skipped") or not art.get("id"):
            continue
        # << dialogue-nettoye.wav >> ne finit PAS par << dialogue.wav >> : les
        # deux cles ne peuvent pas se marcher dessus, et l'original reste
        # atteignable apres le nettoyage. C'est voulu : rien n'est coupe en
        # douce, la personne doit pouvoir reecouter ce que le modele a rendu.
        for suffixe, cle in (("dialogue.wav", "son"),
                             ("dialogue-nettoye.wav", "son_nettoye"),
                             ("resume.json", "resume")):
            if nom.endswith(suffixe):
                trouve[cle] = art
    return trouve


ROUTEUR_INTERNE = os.getenv("SANDBOX_ROUTEUR_URL", "http://free-tier-manager:8000")


async def etat_des_cles() -> dict:
    """Ce qui est branche, pour que le verdict ne reclame que ce qui manque.

    Le routeur qui ne repond pas laisse son cote a None : le verdict dit alors
    << il faut un service deja branche >>, comme avant le 24/09, au lieu
    d'affirmer qu'il manque ou qu'il est la."""
    etat = {"routeur": None,
            "sandbox": {"modal": modal_configured(), "kaggle": kaggle_configured()}}
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            reponse = await client.get(ROUTEUR_INTERNE + "/cles/etat")
            reponse.raise_for_status()
            etat["routeur"] = {f["nom"]: bool(f["active"])
                               for f in reponse.json()["fournisseurs"]}
    except Exception:  # noqa: BLE001 -- un verdict ne casse pas faute de routeur
        pass
    return etat
# La transcription d'un dialogue de 147 s a pris 63 s sur le processeur (mesure
# du 17/09/2026). Le delai couvre largement cela, plus le telechargement du
# modele d'alignement a la toute premiere demande.
NETTOYAGE_DELAI_S = int(os.getenv("DIALOGUE_NETTOYAGE_TIMEOUT_SECONDS", "900"))


def marquer_nettoyage_en_cours(jid: str, en_cours: bool) -> None:
    """Pose ou retire le temoin que la page attend. Ne casse jamais le travail.

    La fiche peut etre illisible ou non ecrivable ; dans ce cas la page se
    rabattra sur sa propre borne d'attente plutot que de tourner sans fin.
    """
    try:
        job = read_job(jid)
        if en_cours:
            job["nettoyage_en_cours"] = True
        else:
            job.pop("nettoyage_en_cours", None)
        write_job(jid, job)
    except Exception as exc:  # noqa: BLE001 - un temoin n'a pas a faire echouer un rendu paye
        log.warning("Temoin de nettoyage du dialogue %s impossible : %s", jid, exc)


def nettoyer_dialogue(jid: str) -> None:
    """Retire du rendu la parole que personne n'a demandee. NE CASSE JAMAIS LE TRAVAIL.

    POURQUOI CE NETTOYAGE EXISTE. FireRedTTS-2 insere, en fin de replique, des
    bouts de parole absents du texte -- dont de l'ANGLAIS. Mesure du 17/09/2026
    sur 147,5 s : << I see. Enthusie, be impressed. >>, << What a >>, << tch. >>,
    << Voooh >>, << sans. >>. Cinq intrusions, sur un fond de 96,5 % de mots
    corrects. Elles sont INVISIBLES a toute mesure de signal (voisees, clarte
    0,92, pleine echelle) : seule la comparaison au texte envoye les designe.

    POURQUOI ICI, ET PAS AILLEURS. Modal passe par finish_execution, Kaggle
    ecrit la fiche en direct : les deux ne convergent pas cote ecriture. Cette
    fonction est appelee depuis run_dialogue, qui est le seul endroit que les
    deux chemins traversent. Cote lecture, ce serait pire : dialogue_fichiers
    sert un GET que la page interroge toutes les 5 s, et une transcription de
    60 s y serait un delai d'attente depasse, pas une fonctionnalite.

    POURQUOI RIEN NE PEUT ECHOUER ICI. Le rendu est deja fait, et sur Modal il
    est deja paye. Un routeur injoignable, une cle absente, un Whisper en panne
    ne doivent PAS transformer un travail reussi en echec : l'original reste,
    le travail reste << succeeded >>, et la fiche dit pourquoi le nettoyage n'a
    pas eu lieu. Un post-traitement qui peut casser un rendu paye serait une
    regression, pas une fonctionnalite.
    """
    def noter(motif: str) -> None:
        travail = read_job(jid)
        travail["nettoyage"] = {"fait": False, "motif": motif}
        write_job(jid, travail)

    try:
        job = read_job(jid)
        repliques = job.get("dialogue_repliques") or []
        if not repliques:
            noter("le texte envoyé n'a pas été conservé pour ce travail")
            return
        art = dialogue_fichiers(jid).get("son")
        if not art:
            noter("aucun fichier audio à nettoyer")
            return
        source = ART / art["path"]
        if not source.exists() or source.is_symlink():
            noter("le fichier audio est introuvable")
            return

        cle = os.getenv("FREE_TIER_MANAGER_KEY", "").strip()
        if not cle:
            noter("le routeur n'est pas joignable : la clé interne manque dans ce service")
            return

        with httpx.Client(timeout=NETTOYAGE_DELAI_S) as client:
            reponse = client.post(
                ROUTEUR_INTERNE + "/v1/audio/alignement",
                headers={"Authorization": "Bearer " + cle},
                files={"file": (source.name, source.read_bytes(), "audio/wav")},
            )
            reponse.raise_for_status()
            mots = reponse.json().get("mots") or []
        if not mots:
            noter("la transcription n'a rendu aucun mot")
            return

        cible = JOBS / jid / "dialogue-nettoye.wav"
        cible.parent.mkdir(parents=True, exist_ok=True)
        rapport = nettoyage_dialogue.nettoyer(str(source), str(cible), repliques, mots)
        rapport["fait"] = True
        if rapport.get("coupes"):
            ajout = add_artifact(jid, cible, "nettoyage")
            job = read_job(jid)
            job["artifacts"] = list(job.get("artifacts") or []) + [ajout]
        else:
            job = read_job(jid)
        job["nettoyage"] = rapport
        write_job(jid, job)
        log.info("Nettoyage du dialogue %s : %d coupe(s), %.2f s retirees",
                 jid, rapport.get("coupes", 0), rapport.get("secondes_retirees", 0.0))
    except Exception as exc:  # noqa: BLE001 - rien ne doit remonter jusqu'au travail
        log.warning("Nettoyage du dialogue %s impossible : %s", jid, exc)
        try:
            noter("%s: %s" % (type(exc).__name__, str(exc)[:200]))
        except Exception:  # la fiche elle-meme est illisible : on n'insiste pas
            pass


def run_dialogue(jid: str, code: str, ou: str):
    """Lance le dialogue, encaisse le temps Modal consomme, puis nettoie le rendu.

    Le finally encaisse meme en cas d'echec : une machine qui tombe a quand meme
    tourne, et le premier lancement telecharge environ 12,6 Go au tarif de la
    carte, puisque le compteur facture le temps d'horloge. Sur Kaggle il n'y a
    rien a encaisser -- c'est gratuit, et le compteur du mois ne suit que Modal.

    Le nettoyage vient APRES le finally, donc son temps de calcul n'entre pas
    dans la facture Modal : il tourne sur le processeur de cette machine-ci.
    """
    debut = time.time()
    job = read_job(jid)
    job.update({"status": "running", "started_at": debut, "provider_effective": ou})
    write_job(jid, job)
    try:
        if ou == "kaggle":
            run_kaggle(jid, code, True, True, machine_shape=dialogue.KAGGLE_MACHINE,
                       timeout_s=dialogue.KAGGLE_DELAI_S)
        else:
            donnees = modal_execute(
                jid, code, True, True,
                gpu_type=dialogue.GPU_MODAL,
                timeout_s=dialogue.DUREE_MAX_S,
                memory_mb=dialogue.MEMOIRE_MB,
                paquets=dialogue.PAQUETS_MODAL,
                apt=dialogue.APT_MODAL,
                commandes=dialogue.COMMANDES_MODAL,
                volume=dialogue.VOLUME_MODELES,
                # Compte par dialogue.budget_verifier()/budget_consommer(),
                # juste au-dessus et juste en dessous : pas deux fois.
                usage=None,
            )
            finish_execution(jid, "modal", donnees)
    except BackendUnavailable as exc:
        terminer_en_echec(jid, str(exc)[:1000])
    finally:
        if ou == "modal":
            reste = dialogue.budget_consommer(dialogue.GPU_MODAL, time.time() - debut)
            job = read_job(jid)
            job["budget"] = reste
            write_job(jid, job)
    # LE FILTRAGE NE SE DECLENCHE PLUS TOUT SEUL. Choix de l'utilisateur,
    # 18/09/2026 : << parfois le dialogue initial est ok >>. Il coutait une
    # transcription Whisper medium sur le processeur de la machine -- une
    # vingtaine de secondes pour 44 s d'audio -- a CHAQUE rendu, y compris ceux
    # que personne n'aurait voulu retoucher. Et la decision demande d'avoir
    # ecoute : elle ne peut donc pas se prendre ici, avant que quiconque ait
    # entendu le son. Elle se prend depuis la page, par /dialogue/jobs/{id}/nettoyer.
    return


def _nettoyage_en_arriere_plan(jid: str) -> None:
    """Le filtrage demande depuis la page, hors du fil qui repond a la requete.

    Le temoin se leve AVANT le fil : si on le posait dedans, la reponse pourrait
    partir la premiere et la page verrait une fiche sans temoin ni rapport --
    exactement l'etat << rien demande >>. Elle croirait son clic perdu.
    """
    try:
        nettoyer_dialogue(jid)
    finally:
        marquer_nettoyage_en_cours(jid, False)


@app.get("/dialogue/etat")
def dialogue_etat(request: Request, authorization: Optional[str] = Header(default=None)):
    auth(authorization)
    # La page doit savoir d'avance si Kaggle est coupe ici, pour griser l'option
    # plutot que de laisser cliquer sur un refus. Le verrou qui compte reste
    # celui du serveur, dans /dialogue/creer.
    raison = contexte_partage(request)
    return {
        "budget": dialogue.budget_lire(),
        # MODELE porte la licence ET la reserve des auteurs : les deux doivent
        # arriver jusqu'a la page, qui les affiche la ou le modele se choisit.
        "modele": dialogue.MODELE,
        "carte_modal": dialogue.GPU_MODAL,
        "cout_max_modal_usd": round(
            dialogue.prix_seconde(dialogue.GPU_MODAL) * dialogue.DUREE_MAX_S, 3),
        "locuteurs_max": dialogue.LOCUTEURS_MAX,
        "max_caracteres": dialogue.MAX_CARACTERES,
        "modal_configure": modal_configured(),
        "kaggle_configure": kaggle_configured(),
        "kaggle_permis": raison is None,
        "kaggle_raison": raison,
    }


@app.post("/dialogue/creer")
async def dialogue_creer(request: Request, authorization: Optional[str] = Header(default=None)):
    auth(authorization)
    payload = await corps_json(request)
    ou = str(payload.get("ou") or "modal")
    # ON REFUSE, ON NE DEVINE PAS. /chanson ramene un << ou >> inconnu a
    # << modal >> sans le dire : ici, une faute de frappe (<< kagle >>)
    # demarrerait une machine PAYANTE alors que la personne demandait la
    # gratuite. Le cout d'un refus est une phrase ; celui d'une supposition est
    # une facture que personne n'a voulue.
    if ou not in ("modal", "kaggle"):
        raise HTTPException(400, "Endroit inconnu : « %s ». Choisissez « modal » (machine "
                                 "louée) ou « kaggle » (gratuit)." % ou[:40])
    # LA GARDE DE CONTEXTE PARTAGE PASSE AVANT TOUT LE RESTE. Kaggle automatique
    # se sert des identifiants PERSONNELS du proprietaire de cette machine : des
    # que le Studio sert quelqu'un d'autre, il est coupe. Voir AGENTS.md.
    if ou == "kaggle":
        raison = contexte_partage(request)
        if raison:
            raise refus_kaggle(raison)
    # preparer() AVANT toute autre verification : un dialogue mal balise se
    # refuse meme quand Modal n'est pas branche, et surtout sans rien payer.
    try:
        plan = dialogue.preparer(payload, ou)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    if ou == "modal":
        if not modal_configured():
            raise HTTPException(503, "Modal n'est pas branché. Ouvrez la page « Brancher Modal "
                                     "ou Kaggle » et collez les deux valeurs du jeton Modal.")
        try:
            dialogue.budget_verifier(plan["gpu"], dialogue.DUREE_MAX_S)
        except dialogue.BudgetDepasse as exc:
            raise HTTPException(429, str(exc)) from exc
    elif not kaggle_configured():
        raise HTTPException(503, "Kaggle n'est pas branché. Ouvrez la page « Brancher Modal "
                                 "ou Kaggle » et collez votre nom d'utilisateur et votre clé Kaggle.")

    code = dialogue.construire_script(plan["demande"])
    jid = uuid.uuid4().hex
    write_job(jid, {
        "id": jid,
        "provider": ou,
        "title": "Free AI Studio dialogue",
        "gpu": True,
        "internet": True,
        "status": "queued",
        "created_at": time.time(),
        "artifacts": [],
        "dialogue": plan["resume_public"],
        "titre": derniers.titre(payload, "dialogue"),
        # LA VERITE TERRAIN DU NETTOYAGE. Sans le texte reellement envoye, il
        # est impossible de dire ce que le modele a AJOUTE : resume.json n'en
        # garde que le NOMBRE de repliques, ce qui ne sert a rien ici. Ce champ
        # reste dans la fiche interne et n'est pas publie par /dialogue/jobs.
        "dialogue_repliques": list(plan["demande"]["repliques"]),
    })
    threading.Thread(target=run_dialogue, args=(jid, code, ou), daemon=True).start()
    return read_job(jid)


@app.get("/dialogue/jobs/{jid}")
def dialogue_job(jid: str, authorization: Optional[str] = Header(default=None)):
    auth(authorization)
    job = read_job(jid)
    fichiers = dialogue_fichiers(jid)
    sortie = {
        "id": jid,
        "status": job.get("status"),
        "created_at": job.get("created_at"),
        "titre": job.get("titre") or "",
        "stdout": job.get("stdout", ""),
        "stderr": job.get("stderr", ""),
        # Le journal du noyau Kaggle, quand il y en a un. Le 17/09/2026, sur le
        # premier echec du chemin gratuit, stdout ET stderr etaient vides : la
        # page n'avait donc rien a montrer, alors que Kaggle gardait la trace
        # complete de la panne et que la CLI savait la rendre. Voir
        # journal_kaggle(), qui ne tourne que sur un echec.
        "journal_kaggle": job.get("journal_kaggle", ""),
        "message": job.get("error") or "",
        "arret_detail": job.get("arret_detail") or "",
        "dialogue": job.get("dialogue"),
        # Le bouton d'arret change selon le fournisseur : Kaggle n'a pas
        # d'annulation, la page ne doit pas promettre un arret (23/09/2026).
        "fournisseur": job.get("provider_effective") or job.get("provider") or "",
    }
    if fichiers.get("son"):
        jeton = jeton_dialogue(jid)
        sortie["son_url"] = f"/dialogue/jobs/{jid}/fichier?cle={jeton}"
        # Le nettoyage ne fait jamais disparaitre l'original : la page propose
        # les deux, et c'est ce qui rend la coupe acceptable. Une suppression
        # silencieuse serait invendable, meme si elle ameliore le son.
        if fichiers.get("son_nettoye"):
            sortie["son_original_url"] = (
                f"/dialogue/jobs/{jid}/fichier?cle={jeton}&version=origine")
    sortie["nettoyage"] = job.get("nettoyage")
    # LE TEMOIN DOIT TRAVERSER. Il est pose sur la fiche par le serveur et
    # attendu par la page ; cette ligne est le chainon entre les deux, et son
    # absence a rendu la correction du 18/09 entierement inerte -- ecrite,
    # testee des deux cotes, poussee, et morte. Les deux tests regardaient
    # chacun une moitie : l'un que la fiche porte le temoin, l'autre que la
    # page le lit. AUCUN ne passait par cette route. Le test
    # test_le_temoin_traverse_la_route_qui_le_sert ferme ce trou-la.
    sortie["nettoyage_en_cours"] = bool(job.get("nettoyage_en_cours"))
    try:
        if fichiers.get("resume"):
            sortie["resume"] = json.loads(
                (ART / fichiers["resume"]["path"]).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    return sortie


@app.post("/dialogue/jobs/{jid}/nettoyer")
def dialogue_nettoyer(jid: str, authorization: Optional[str] = Header(default=None)):
    """Filtre la voix D'UN RENDU DEJA FAIT, sur demande explicite de la page.

    POURQUOI CE N'EST PLUS AUTOMATIQUE. Choix de l'utilisateur, 18/09/2026 :
    << parfois le dialogue initial est ok >>. Le filtrage coute une
    transcription Whisper medium sur le processeur de la machine -- une
    vingtaine de secondes pour 44 s d'audio -- et il ne sert a rien quand le
    modele a bien dit le texte. Surtout, la decision demande d'avoir ECOUTE :
    elle ne peut pas se prendre a la fin du rendu, avant que quiconque ait
    entendu le son.

    REPOND TOUT DE SUITE, TRAVAILLE DERRIERE. Vingt secondes de transcription
    dans le fil de la requete, c'est un navigateur qui attend sans rien dire et
    un delai d'attente depasse au bout du compte. Le temoin est pose AVANT de
    lancer le fil, jamais dedans : sinon la reponse pourrait partir la premiere
    et la page verrait une fiche sans temoin ni rapport -- l'etat << rien
    demande >> -- et croirait son clic perdu.

    IDEMPOTENTE. Deux clics, ou un clic sur une page rechargee, ne lancent pas
    deux transcriptions : le rapport deja la est rendu tel quel, et un filtrage
    en cours est signale sans en demarrer un second.
    """
    auth(authorization)
    job = read_job(jid)
    if not job.get("dialogue"):
        raise HTTPException(404, "Ce travail n'est pas un dialogue.")
    if job.get("nettoyage"):
        return {"etat": "deja fait", "nettoyage": job["nettoyage"]}
    if job.get("nettoyage_en_cours"):
        return {"etat": "en cours"}
    if job.get("status") != "succeeded":
        raise HTTPException(409, "Le dialogue n'est pas encore rendu : rien à filtrer.")
    if not dialogue_fichiers(jid).get("son"):
        raise HTTPException(409, "Ce dialogue n'a pas de fichier son.")
    marquer_nettoyage_en_cours(jid, True)
    threading.Thread(target=_nettoyage_en_arriere_plan, args=(jid,), daemon=True).start()
    return {"etat": "lancé"}


@app.get("/dialogue/jobs/{jid}/fichier")
def dialogue_fichier(jid: str, cle: str = Query(default=""),
                     telecharger: int = Query(default=0), nom: str = Query(default=""),
                     version: str = Query(default="")):
    attendu = jeton_dialogue(jid)
    if not attendu or not hmac.compare_digest(cle, attendu):
        raise HTTPException(401, "Unauthorized")
    fichiers = dialogue_fichiers(jid)
    # Par defaut la version nettoyee, quand elle existe ; << version=origine >>
    # rend ce que le modele a produit, intact. Les deux restent servies.
    art = fichiers.get("son") if version == "origine" else (
        fichiers.get("son_nettoye") or fichiers.get("son"))
    if not art:
        raise HTTPException(404, "Pas de dialogue pour ce travail")
    chemin = ART / art["path"]
    if not chemin.exists() or chemin.is_symlink():
        raise HTTPException(404, "Fichier absent")
    if not telecharger:
        return FileResponse(chemin, media_type="audio/wav")
    propre = clean_name(nom) if nom else ""
    if propre.lower().endswith(".wav"):
        propre = propre[:-4]
    propre = propre.strip("._-")
    return FileResponse(chemin, media_type="audio/wav", filename=(propre or "dialogue") + ".wav")


@app.get("/dialogue", response_class=HTMLResponse)
def dialogue_page():
    return HTMLResponse(derniers.dans_la_page(format_fr.avec_formateurs(
        dialogue.PAGE_HTML.replace("__CLE__", KEY)), "dialogue"))


@app.get("/composite", response_class=HTMLResponse)
def composite_page():
    return HTMLResponse(format_fr.avec_formateurs(
        composite.PAGE_HTML.replace("__CLE__", KEY)))


def _refus_composite(exc: composite.CompositeRefuse) -> HTTPException:
    """Un refus du composite devient un refus HTTP qui porte SON motif.

    409 et non 500 : rien n'est casse. La chaine demandee ne tient pas, et la
    page a de quoi le dire en francais.
    """
    return HTTPException(409, exc.phrase, headers={"X-Composite-Ou": exc.ou,
                                                   "X-Composite-Motif": exc.motif})


async def _chaine_depuis(request: Request):
    """La phrase -> un graphe -> une chaine de briques nommees."""
    formulaire = await request.form()
    phrase = str(formulaire.get("phrase") or "")
    # Un reglage vient de changer sur la page : le verdict se refait sur les
    # briques MONTREES, sans relire la phrase (23/09, reglages de la chaine).
    briques = [b for b in str(formulaire.get("briques") or "").split(",") if b]
    if briques:
        chaine = composite.chaine_depuis_briques(briques, phrase=phrase)
        chaine["proprietes"] = composite.proprietes_lues(formulaire.get("proprietes"), chaine)
        composite.consignes_lues(formulaire.get("consignes"), chaine)
        return formulaire, chaine
    graphe = composite.compiler(phrase, composite.appeler_le_modele,
                                entree=composite.entree_lue(formulaire.get("entree")))
    chaine = composite.lier(graphe)
    chaine["proprietes"], chaine["proprietes_sans_effet"] = (
        composite.appliquer_proposees(chaine, graphe))
    return formulaire, chaine


@app.post("/composite/verdict")
async def composite_verdict(request: Request,
                            authorization: Optional[str] = Header(default=None)):
    """Dit AVANT de lancer si la chaine tient, et ce qu'elle coute au pire."""
    auth(authorization)
    try:
        formulaire, chaine = await _chaine_depuis(request)
        verdict = composite.verifier(chaine, entree=composite.entree_lue(formulaire.get("entree")),
                                     etat_cles=await etat_des_cles())
        # Le calcul a etabli les faits ; le modele les met en francais, et les
        # montants sont verrouilles dans `rediger`. Hors boucle : c'est un appel
        # reseau, il ne doit pas tenir le service pendant qu'il attend.
        verdict["phrase"] = await asyncio.to_thread(composite.rediger, verdict)
        # Les reglages que la page montre et laisse changer (23/09).
        verdict["proprietes"] = composite.proprietes_montrees(chaine)
        verdict["proprietes_sans_effet"] = chaine.get("proprietes_sans_effet", [])
        return JSONResponse(verdict)
    except composite.CompositeRefuse as exc:
        raise _refus_composite(exc) from exc


@app.post("/composite/lancer")
async def composite_lancer(request: Request,
                           authorization: Optional[str] = Header(default=None)):
    """Lance la chaine, noeud par noeud, et rend ce qu'elle a produit.

    Le verdict est RE-JOUE ici : la page peut avoir ete laissee ouverte, et une
    chaine refusee ne doit pas partir parce qu'un bouton etait deja actif.

    Mais la chaine n'est PAS recompilee. Jusqu'au 22/09/2026 cette route
    repassait par le modele, qui n'est pas deterministe : ce qui partait
    pouvait n'etre pas ce dont le client venait de lire le verdict. La page
    renvoie les briques qu'elle a montrees, on les rebatit depuis le registre,
    et c'est cette chaine-la -- la meme -- qui est reverifiee puis lancee.
    """
    auth(authorization)
    try:
        chaine, verdict, entree = await _preparer_le_lancement(request)
        trace = await asyncio.to_thread(
            composite.executer, chaine, composite.lancer_par_le_routeur, entree,
            verdict, pretraiter=composite.pretraiter_par_le_chat)
    except composite.CompositeRefuse as exc:
        raise _refus_composite(exc) from exc
    return JSONResponse(await asyncio.to_thread(_resultat_de_la_chaine, chaine, trace))


async def _preparer_le_lancement(request: Request):
    """La chaine MONTREE, rebatie, reglee et reverifiee : (chaine, verdict, entree)."""
    formulaire = await request.form()
    briques = [b for b in str(formulaire.get("briques") or "").split(",") if b]
    if not briques:
        raise composite.CompositeRefuse(
            "chaine_absente",
            "Cette demande n'a pas encore \u00e9t\u00e9 regard\u00e9e. Cliquez "
            "\u00ab Voir si c\u2019est possible \u00bb, puis \u00ab Lancer \u00bb.",
            ou=composite.CONTROLE)
    chaine = composite.chaine_depuis_briques(
        briques, phrase=str(formulaire.get("phrase") or ""))
    # Les reglages tels que la page les montre au moment du clic, VERIFIES.
    chaine["proprietes"] = composite.proprietes_lues(formulaire.get("proprietes"), chaine)
    # Et la consigne de chaque etape, telle qu'elle est montree (23/09).
    composite.consignes_lues(formulaire.get("consignes"), chaine)
    fichier = formulaire.get("fichier")
    # Le VRAI fichier decide ici, pas ce que la page a annonce : une
    # image ne part plus jamais comme du texte (23/09, 540 498 jetons).
    joint = (composite.type_d_entree(fichier.filename, fichier.content_type)
             if fichier is not None and not isinstance(fichier, str) else composite.SANS_FICHIER)
    verdict = composite.verifier(chaine, entree=joint, etat_cles=await etat_des_cles())
    if verdict["atteignable"] == composite.NON:
        raise composite.CompositeRefuse(
            ";".join(verdict["motifs"]) or "refuse", verdict["pourquoi"],
            ou=composite.CONTROLE)

    entree = await fichier.read() if fichier is not None and not isinstance(
        fichier, str) else None
    return chaine, verdict, entree


def _resultat_de_la_chaine(chaine: dict, trace: dict) -> dict:
    """Ce que la page montre d'une chaine finie ; HTTPException si elle n'a pas abouti."""
    if trace["resultat"] != "rendu":
        # La PHRASE d'abord : c'est elle que la page montre. Le motif reste,
        # dans l'en-tete, pour le journal. L'inverse etait en service jusqu'au
        # 22/09 au soir, et un client dont la carte etait prise lisait
        # << arbitrage_du_client >>.
        raise HTTPException(409,
                            trace.get("phrase") or trace["motif"]
                            or "La chaîne n'a pas abouti.",
                            headers={"X-Composite-Ou": trace["ou"] or "",
                                     "X-Composite-Motif": trace["motif"] or ""})

    sortie = trace["sortie"]
    # Toujours du JSON depuis le 23/09 (« on a la voix mais pas le texte ») :
    # les textes rendus en chemin voyagent avec le fichier final.
    textes = [{"fonction": e.get("fonction", e["brique"]), "texte": e["texte"]}
              for e in trace["etapes"] if e.get("texte")]
    derniere = chaine["etapes"][-1]["fonction"]
    if isinstance(sortie, (bytes, bytearray)):
        # Le type ANNONCE suit ce que les octets disent, et a defaut ce que la
        # derniere brique declare rendre. Il etait fige sur `audio/wav`, ce qui
        # ne se voyait pas tant qu'aucune chaine ne pouvait finir autrement.
        mime, nom = composite.type_de_sortie(sortie, chaine["etapes"][-1]["sorties"])
        # « une voix en anglais et un texte en français » (23/09) : le texte
        # dit, traduit a part, puisque la chaine finit par le son.
        traduction = composite.traduire_le_texte_dit(
            chaine, trace, composite.lancer_par_le_routeur)
        return {"fichier": base64.b64encode(bytes(sortie)).decode("ascii"),
                "type": mime, "nom": nom, "textes": textes,
                "derniere": derniere, "etapes": trace["etapes"],
                "ecoute": getattr(sortie, "ecoute", None),
                "traduction": traduction}
    return {"texte": str(sortie), "textes": textes, "derniere": derniere,
            "etapes": trace["etapes"]}


# --- Une chaine SUIVIE pas a pas, et arretable (24/09) ------------------------
# << enchainer : pas de visualisation intermediaire, ni d'abort button >>, puis
# << il faut les y mettre dans l'ui de pilotage >>. `/composite/lancer` rendait
# tout a la fin, en un bloc. Une COURSE tourne dans un fil ; la page lit son
# avancement, montre chaque sortie des qu'elle existe, et peut l'arreter.
# En memoire : une course ne survit pas a un redemarrage, et la page le dit.
COURSES: Dict[str, dict] = {}
COURSES_VERROU = threading.Lock()
COURSES_GARDEES = 20
PHRASE_ARRET = ("Arrêt demandé. Aucune étape de plus ne part. Un travail en cours (vidéo, "
                "chanson, dialogue) est arrêté tout de suite ; une autre étape déjà partie "
                "(chat, image, voix) finit d'abord, et son résultat reste montré.")


# Une pause oubliee ne tient pas un fil pour toujours : au-dela, la chaine
# s'arrete d'elle-meme, et le dit.
PAUSE_MAX_S = int(os.getenv("COMPOSITE_PAUSE_MAX_S", "3600"))


def _attendre_le_feu_vert(course: dict, chaine: dict, rang: int, etape: dict):
    """Mode pas a pas : la course attend « Continuer » ou « Arreter »."""
    course["continuer"].clear()
    course.pop("consigne_suivante", None)
    course["pause"] = {"avant": rang, "fonction": etape["fonction"],
                       "consigne": etape.get("demande") or ""}
    course["etapes"][rang] = dict(course["etapes"][rang], statut="pause")
    limite = time.monotonic() + PAUSE_MAX_S
    try:
        while not course["continuer"].is_set():
            if course["arret"].is_set():
                return None
            if time.monotonic() > limite:
                course["arret"].set()
                raise composite.CompositeRefuse(
                    composite.ARRETE_PAR_LE_CLIENT,
                    "En pause depuis plus de %d min sans suite : la chaîne s'est arrêtée "
                    "d'elle-même avant « %s ». Ce qui était déjà fait reste montré."
                    % (PAUSE_MAX_S // 60, etape["fonction"]), ou=composite.EXECUTION)
            course["continuer"].wait(0.25)
        retouchee = (course.pop("consigne_suivante", None) or "").strip()
        return retouchee if retouchee and retouchee != course["pause"]["consigne"] else None
    finally:
        course["pause"] = None


def _courir(course: dict, chaine: dict, verdict: dict, entree) -> None:
    def suivi(rang, statut, rendu, sortie):
        vue = {"fonction": chaine["etapes"][rang]["fonction"], "statut": statut}
        for cle in ("texte", "ecoute", "phrase", "pretraitement"):
            if rendu and rendu.get(cle):
                vue[cle] = rendu[cle]
        if isinstance(sortie, (bytes, bytearray)):
            mime, _ = composite.type_de_sortie(sortie, chaine["etapes"][rang]["sorties"])
            course["sorties"][rang] = (bytes(sortie), mime)
            vue["type"] = mime
        course["etapes"][rang] = vue

    try:
        pause = ((lambda rang, etape: _attendre_le_feu_vert(course, chaine, rang, etape))
                 if course.get("pas_a_pas") else None)
        trace = composite.executer(chaine, composite.lancer_par_le_routeur, entree, verdict,
                                   suivi=suivi, arret=course["arret"], pause=pause,
                                   pretraiter=composite.pretraiter_par_le_chat)
        course["resultat"] = _resultat_de_la_chaine(chaine, trace)
        course["etat"] = "rendu"
    except HTTPException as exc:
        entetes = exc.headers or {}
        course["erreur"] = {"detail": exc.detail, "ou": entetes.get("X-Composite-Ou", "")}
        course["etat"] = ("arrete" if entetes.get("X-Composite-Motif")
                          == composite.ARRETE_PAR_LE_CLIENT else "echec")
    except Exception as exc:  # noqa: BLE001 -- une course finit TOUJOURS, et le dit
        course["erreur"] = {"detail": "%s : %s" % (type(exc).__name__, exc),
                            "ou": composite.EXECUTION}
        course["etat"] = "echec"


def _course(cid: str) -> dict:
    course = COURSES.get(cid)
    if course is None:
        raise HTTPException(404, "Cette chaîne n'est plus suivie : le Studio a peut-être "
                                 "redémarré. Relancez-la.")
    return course


@app.post("/composite/demarrer")
async def composite_demarrer(request: Request,
                             authorization: Optional[str] = Header(default=None)):
    """Comme `/composite/lancer`, mais rend tout de suite un numero de course.

    `pas_a_pas` (formulaire) : la course attend « Continuer » avant chaque
    etape a partir de la deuxieme. Sans lui, elle va d'un trait.
    """
    auth(authorization)
    try:
        chaine, verdict, entree = await _preparer_le_lancement(request)
    except composite.CompositeRefuse as exc:
        raise _refus_composite(exc) from exc
    pas_a_pas = str((await request.form()).get("pas_a_pas") or "").strip().lower() in (
        "1", "true", "oui", "on")
    cid = uuid.uuid4().hex
    course = {"etat": "en_cours", "arret": threading.Event(), "sorties": {},
              "pas_a_pas": pas_a_pas, "continuer": threading.Event(), "pause": None,
              "etapes": [{"fonction": e["fonction"], "statut": "attente"}
                         for e in chaine["etapes"]],
              "resultat": None, "erreur": None, "cree": time.time()}
    with COURSES_VERROU:
        finies = sorted((c["cree"], k) for k, c in COURSES.items() if c["etat"] != "en_cours")
        for _, vieille in finies[:max(0, len(COURSES) + 1 - COURSES_GARDEES)]:
            COURSES.pop(vieille, None)
        COURSES[cid] = course
    threading.Thread(target=_courir, args=(course, chaine, verdict, entree),
                     name="composite-" + cid[:8], daemon=True).start()
    return {"id": cid}


@app.get("/composite/courses/{cid}")
def composite_course(cid: str, authorization: Optional[str] = Header(default=None)):
    auth(authorization)
    course = _course(cid)
    return {"etat": course["etat"], "etapes": course["etapes"], "erreur": course["erreur"],
            "resultat": course["resultat"], "arret_demande": course["arret"].is_set(),
            "pas_a_pas": course["pas_a_pas"], "pause": course["pause"]}


@app.get("/composite/courses/{cid}/etapes/{rang}")
def composite_sortie_d_etape(cid: str, rang: int,
                             authorization: Optional[str] = Header(default=None)):
    auth(authorization)
    sortie = _course(cid)["sorties"].get(rang)
    if sortie is None:
        raise HTTPException(404, "Cette étape n'a pas rendu de fichier.")
    return Response(content=sortie[0], media_type=sortie[1])


@app.post("/composite/courses/{cid}/arreter")
def composite_arreter(cid: str, authorization: Optional[str] = Header(default=None)):
    auth(authorization)
    course = _course(cid)
    if course["etat"] != "en_cours":
        return {"detail": "Cette chaîne est déjà finie : rien n'a été arrêté."}
    course["arret"].set()
    return {"detail": PHRASE_ARRET}


@app.post("/composite/courses/{cid}/continuer")
async def composite_continuer(cid: str, request: Request,
                              authorization: Optional[str] = Header(default=None)):
    """Pas a pas : laisse partir l'etape qui attend, avec sa consigne retouchee
    (champ `consigne`) si le client l'a changee."""
    auth(authorization)
    course = _course(cid)
    if course["etat"] != "en_cours" or not course["pause"]:
        raise HTTPException(409, "Cette chaîne n'attend pas de feu vert.")
    consigne = (await request.form()).get("consigne")
    if isinstance(consigne, str):
        course["consigne_suivante"] = consigne
    course["continuer"].set()
    return {"detail": "L'étape « %s » part." % course["pause"]["fonction"]}


@app.get("/", response_class=HTMLResponse)
def home():
    return HTMLResponse(
        """<!doctype html><html lang=fr><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<title>Sandbox — Free AI Studio</title><style>body{font-family:system-ui;max-width:980px;margin:35px auto;padding:0 18px;line-height:1.5}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:14px}.card{border:1px solid #aaa;border-radius:14px;padding:18px}.primary{border-width:2px}a.button{display:inline-block;border:1px solid #777;border-radius:9px;padding:9px 12px;text-decoration:none;margin:4px 4px 4px 0}.flow{padding:12px;border-radius:10px;background:#eee;font-family:ui-monospace,monospace}</style>
<h1>🧪 Sandbox</h1><p id=etat style='padding:12px;border-radius:10px;border:1px solid #bbb'>Vérification de l’état…</p>
<p>L’agent utilise <strong>votre ordinateur d’abord</strong> quand il suffit : un code qui ne demande ni carte graphique ni Internet s’exécute ici, gratuitement. Un code qui demande une carte graphique passe sur la vôtre si elle est libre, sinon chez Modal s’il est configuré ; un code qui demande Internet part chez Modal. En cas d’indisponibilité d’infrastructure, il bascule vers le suivant, puis Kaggle, puis un handoff Colab. Une erreur dans votre code n’est jamais dupliquée automatiquement sur un autre fournisseur.</p>
<div class=flow>Sans carte ni Internet : Local → Modal → Colab &nbsp; | &nbsp; Avec carte : votre carte si libre → Modal → Local → Kaggle → Colab &nbsp; | &nbsp; Avec Internet : Modal → Local → Kaggle → Colab</div>
<div class=grid>
<div class='card primary'><h2>Local <span id=b-local></span></h2><p>Premier choix. Python isolé dans Docker, sur le processeur de votre ordinateur, sans Internet ni secrets du Studio.</p></div>
<div class=card><h2>⚡ Modal <span id=b-modal></span></h2><p>Machine distante, pour ce qui demande une carte graphique ou Internet ; secours si votre ordinateur ne répond pas. Résultats récupérés comme ressources de l’agent.</p><a class=button href='https://modal.com/' target=_blank rel='noopener'>Ouvrir Modal ↗</a></div>
<div class=card><h2>Kaggle <span id=b-kaggle></span></h2><p>Fallback automatisable si configuré — sur votre machine seulement, avec vos identifiants. L’accès direct reste toujours disponible.</p><a class=button href='https://www.kaggle.com/code' target=_blank rel='noopener'>Ouvrir Kaggle ↗</a></div>
<div class=card><h2>Colab</h2><p>Accès direct permanent. En dernier recours, le Studio génère un notebook prêt à ouvrir puis réimporte les résultats.</p><a class=button href='https://colab.research.google.com/' target=_blank rel='noopener'>Ouvrir Colab ↗</a></div>
</div><p><a class=button href='/essai'>▶️ Lancer un essai</a> &nbsp; <a class=button href='/video'>🎬 Fabriquer une vidéo</a> &nbsp; <a class=button href='/chanson'>🎵 Faire chanter des paroles</a> &nbsp; <a class=button href='/dialogue'>🎙️ Faire parler deux voix</a> &nbsp;<a class=button href='/cles'>🔑 Brancher Modal ou Kaggle</a> &nbsp; <a href='/docs'>API Sandbox / Agent →</a></p>
<script>
(function(){
 var pastille = function(ok, oui, non){
   return "<span style='font-size:.72rem;border:1px solid #999;border-radius:999px;padding:2px 9px;vertical-align:middle;background:"
        + (ok ? "#e8f6ec" : "#f1f1f1") + "'>" + (ok ? oui : non) + "</span>";
 };
 fetch('/etat').then(function(r){return r.json();}).then(function(d){
   document.getElementById('b-modal').innerHTML  = pastille(d.modal.configure, 'actif', d.modal.autorise ? 'jeton manquant' : 'desactive');
   document.getElementById('b-local').innerHTML  = pastille(d.local.disponible, 'actif', 'indisponible');
   document.getElementById('b-kaggle').innerHTML = d.kaggle.automatique_permis
     ? pastille(d.kaggle.configure, 'actif', d.kaggle.autorise ? 'identifiants manquants' : 'desactive')
     : pastille(false, '', 'automatique coupe : Studio partage');
   var e = document.getElementById('etat');
   var nom = {modal:'Modal (machine distante)', kaggle:'Kaggle', local:'votre ordinateur, isole dans Docker'}[d.backend_automatique];
   e.style.background = '#e8f6ec'; e.style.borderColor = '#7fb98f';
   e.textContent = "Le code envoye ici s'execute sur : " + nom + "." + (d.backend_carte_ou_internet === "modal" ? " Un code qui demande une carte graphique passe sur la vôtre si elle est libre, sinon chez Modal ; un code qui demande Internet part chez Modal." : "")
     + (d.modal.configure ? "" : " Modal n'est pas configure : rien ne part sur une machine distante, et rien ne peut etre facture.");
 }).catch(function(){
   var e = document.getElementById('etat');
   e.style.background = '#fdf3e3'; e.style.borderColor = '#d9ad63';
   e.textContent = "Etat non verifiable : le service Sandbox ne repond pas.";
 });
})();
</script>
</html>"""
    )
