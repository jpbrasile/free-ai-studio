from __future__ import annotations

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
from fastapi import FastAPI, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

import video

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("sandbox-manager")

app = FastAPI(title="Free AI Studio Sandbox Manager", version="2.0.0")

KEY = os.getenv("SANDBOX_MANAGER_KEY", "").strip()
WORKER_KEY = os.getenv("SANDBOX_WORKER_KEY", "").strip()
WORKER_URL = os.getenv("SANDBOX_WORKER_URL", "http://sandbox-worker:8000").rstrip("/")
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
    """La raison de couper Kaggle automatique, ou None sur un Studio personnel."""
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


def write_job(jid: str, data: dict):
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


def stored_keys() -> Dict[str, str]:
    try:
        data = json.loads(KEYS_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        log.warning("magasin de secrets illisible (%s) : %s", KEYS_FILE, exc)
        return {}
    return {k: v for k, v in data.items() if isinstance(v, str)}


def store_key(name: str, value: str) -> None:
    data = stored_keys()
    if value:
        data[name] = value
    else:
        data.pop(name, None)
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
    apply_stored_secrets()


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


def modal_enabled() -> bool:
    if os.getenv("MODAL_ENABLED", "false").strip().lower() == "true":
        return True
    # MODAL_ENABLED=false protege une installation fraiche d'un usage cloud
    # accidentel. Coller un jeton dans l'interface est tout sauf accidentel :
    # cet acte vaut activation, et le bouton << Oublier >> la revoque.
    keys = stored_keys()
    return bool(keys.get("MODAL_TOKEN_ID") and keys.get("MODAL_TOKEN_SECRET"))


def kaggle_enabled() -> bool:
    if os.getenv("KAGGLE_ENABLED", "false").strip().lower() == "true":
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


def backend_automatique() -> str:
    """Ou part un job << auto >> ordinaire. run_auto essaie le worker local
    avant Kaggle, et ne propose Kaggle qu'aux jobs GPU : Kaggle n'est donc
    jamais la destination ordinaire, meme configure."""
    return "modal" if modal_configured() else "local"


# Au demarrage : ce qui a ete saisi lors d'une session precedente redevient actif.
apply_stored_secrets()


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
    volume: Optional[str] = None,
    point_de_montage: str = "/modeles",
) -> dict:
    """Execute du code sur une machine Modal.

    Les arguments nommes ne servent qu'aux travaux lourds (la video). Sans eux,
    le comportement est exactement celui d'avant. Ils permettent de demander une
    carte plus grosse, un delai plus long, une image ou les bibliotheques sont
    deja installees, et un disque persistant ou garder les modeles telecharges
    d'un clip a l'autre.
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
    sb = None
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
        volumes = {}
        if volume:
            volumes[point_de_montage] = modal.Volume.from_name(volume, create_if_missing=True)
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
    job.update(
        {
            "provider_effective": effective_provider,
            "status": "succeeded" if exit_code == 0 else "failed",
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


def run_local(jid: str, code: str):
    job = read_job(jid)
    job.update({"status": "running", "started_at": time.time(), "provider_effective": "local"})
    write_job(jid, job)
    try:
        finish_execution(jid, "local", local_execute(jid, code))
    except BackendUnavailable as exc:
        job = read_job(jid)
        job.update({"status": "failed", "finished_at": time.time(), "error": str(exc)[:1000]})
        write_job(jid, job)


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
    except BackendUnavailable as exc:
        job = read_job(jid)
        job.update({"status": "failed", "finished_at": time.time(), "error": str(exc)[:1000]})
        write_job(jid, job)


def kaggle_ref(jid: str):
    user = os.getenv("KAGGLE_USERNAME", "").strip()
    slug = f"free-ai-studio-{jid[:12]}"
    return user, slug, f"{user}/{slug}" if user else ""


def run_kaggle(jid: str, code: str, gpu: bool, internet: bool):
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
    (d / "kernel-metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    try:
        job["status"] = "submitting"
        job["remote_ref"] = ref
        write_job(jid, job)
        p = subprocess.run(["kaggle", "kernels", "push", "-p", str(d)], capture_output=True, text=True, timeout=90)
        if p.returncode:
            raise RuntimeError((p.stderr or p.stdout)[-1000:])
        job = read_job(jid)
        job["status"] = "running"
        job["submit_log"] = (p.stdout or "")[-1000:]
        write_job(jid, job)
        deadline = time.time() + int(os.getenv("KAGGLE_JOB_TIMEOUT_SECONDS", "3600"))
        while time.time() < deadline:
            s = subprocess.run(["kaggle", "kernels", "status", ref], capture_output=True, text=True, timeout=30)
            text = ((s.stdout or "") + "\n" + (s.stderr or "")).lower()
            job = read_job(jid)
            job["remote_status_raw"] = text[-800:]
            write_job(jid, job)
            if "complete" in text:
                break
            # Un statut illisible n'est pas un statut << en cours >>. Sans cette ligne,
            # un refus d'acces faisait patienter une heure entiere sans rien dire.
            if s.returncode or "cannot access" in text or "not found" in text or "denied" in text:
                raise RuntimeError(text[-1000:])
            if any(x in text for x in ("error", "cancel", "failed")):
                raise RuntimeError(text[-1000:])
            time.sleep(15)
        else:
            raise TimeoutError("Kaggle job timeout")
        od = JOBS / jid / "output"
        od.mkdir(exist_ok=True)
        p = subprocess.run(["kaggle", "kernels", "output", ref, "-p", str(od), "--force"], capture_output=True, text=True, timeout=180)
        if p.returncode:
            raise RuntimeError((p.stderr or p.stdout)[-1000:])
        arts = [add_artifact(jid, p, "kaggle") for p in od.rglob("*") if p.is_file() and not p.is_symlink()]
        job = read_job(jid)
        job.update({"status": "succeeded", "finished_at": time.time(), "artifacts": arts})
        write_job(jid, job)
    except Exception as exc:
        job = read_job(jid)
        job.update({"status": "failed", "finished_at": time.time(), "error": f"{type(exc).__name__}: {str(exc)[:1000]}"})
        write_job(jid, job)


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


def run_auto(jid: str, code: str, gpu: bool, internet: bool, kaggle_permis: bool = True):
    attempts: list[dict] = []
    job = read_job(jid)
    job.update({"status": "routing", "started_at": time.time(), "fallback_order": ["modal", "local", "kaggle", "colab"]})
    write_job(jid, job)

    if modal_configured():
        try:
            job = read_job(jid)
            job.update({"status": "running", "provider_effective": "modal"})
            write_job(jid, job)
            data = modal_execute(jid, code, gpu, internet)
            attempts.append({"provider": "modal", "result": "executed", "exit_code": data.get("exit_code")})
            finish_execution(jid, "modal", data, attempts)
            return
        except BackendUnavailable as exc:
            attempts.append({"provider": "modal", "result": "unavailable", "detail": str(exc)[:500]})
    else:
        attempts.append({"provider": "modal", "result": "not_configured"})

    try:
        job = read_job(jid)
        job.update({"status": "running", "provider_effective": "local"})
        write_job(jid, job)
        data = local_execute(jid, code)
        attempts.append({"provider": "local", "result": "executed", "exit_code": data.get("exit_code")})
        finish_execution(jid, "local", data, attempts)
        return
    except BackendUnavailable as exc:
        attempts.append({"provider": "local", "result": "unavailable", "detail": str(exc)[:500]})

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

    attempts.append({"provider": "colab", "result": "handoff"})
    prepare_colab_handoff(jid, code, attempts)


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
    return {"backends": backends, "backend_automatique": backend_automatique()}


@app.post("/cles/tester")
async def cles_tester(request: Request):
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
  document.getElementById("banniere").textContent = "Actuellement, le code envoye au Sandbox s'execute sur : " + nom + ".";
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
<p class="avert">La carte graphique n'existe pas sur le backend local. Sur Modal, elle
consomme l'offre gratuite beaucoup plus vite qu'un calcul sur processeur.</p>

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
            kaggle:"Kaggle", colab:"Colab"};

document.getElementById("code").value = DEMO;

fetch("/etat").then(r => r.json()).then(d => {
  const b = document.getElementById("banniere");
  b.textContent = "En mode automatique, le code s'execute sur : "
    + (OU[d.backend_automatique] || d.backend_automatique) + ".";
  if(!d.modal.configure){ b.textContent += " Modal n'est pas branche : rien ne part sur une machine distante."; }
}).catch(() => {
  document.getElementById("banniere").textContent = "Etat non verifiable : le service Sandbox ne repond pas.";
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


@app.get("/essai", response_class=HTMLResponse)
def essai_page():
    page = ESSAI_HTML.replace("__CLE__", KEY)
    # json.dumps rend un litteral JavaScript valide : guillemets, sauts de ligne et
    # antislashs du code de demonstration sont echappes au lieu d'etre colles tels quels.
    page = page.replace('"__DEMO__"', json.dumps(CODE_DEMO))
    return HTMLResponse(page)


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
    }


@app.get("/providers")
def providers(request: Request, authorization: Optional[str] = Header(default=None)):
    auth(authorization)
    raison = contexte_partage(request)
    return {
        "default": "auto",
        "automatic_order": ["modal", "local", "kaggle", "colab"],
        "modal": {
            "configured": modal_configured(),
            "enabled": modal_enabled(),
            "automatic": True,
            "primary_when_configured": True,
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
            "automatic_execution": False,
            "automatic_handoff": True,
            "note": "Direct access stays available; auto routing can prepare a notebook handoff when other execution backends are unavailable.",
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
        threading.Thread(target=run_local, args=(jid, req.code), daemon=True).start()
    elif req.provider == "kaggle":
        threading.Thread(target=run_kaggle, args=(jid, req.code, req.gpu, req.internet), daemon=True).start()
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
        if ou == "kaggle":
            # Kaggle ne facture rien : pas de compteur, mais un GPU plus petit et
            # un modele a retelecharger a chaque fois.
            run_kaggle(jid, code, True, True)
            return
        donnees = modal_execute(
            jid, code, True, True,
            gpu_type=gpu_type,
            timeout_s=video.DUREE_MAX_S,
            memory_mb=int(os.getenv("VIDEO_MEMORY_MB", "16384")),
            paquets=VIDEO_PAQUETS,
            apt=("ffmpeg",),
            volume=video.VOLUME_MODELES,
        )
        finish_execution(jid, "modal", donnees)
    except BackendUnavailable as exc:
        job = read_job(jid)
        job.update({"status": "failed", "finished_at": time.time(), "error": str(exc)[:1000]})
        write_job(jid, job)
    finally:
        if ou == "modal":
            reste = video.budget_consommer(gpu_type, time.time() - debut)
            job = read_job(jid)
            job["budget"] = reste
            write_job(jid, job)


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
    }


@app.post("/video/creer")
async def video_creer(request: Request, authorization: Optional[str] = Header(default=None)):
    auth(authorization)
    payload = await request.json()
    ou = str(payload.get("ou") or "modal")
    if ou not in ("modal", "kaggle"):
        ou = "modal"
    if ou == "kaggle":
        raison = contexte_partage(request)
        if raison:
            raise refus_kaggle(raison)
    try:
        plan = video.preparer(payload, pour_modal=(ou == "modal"))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    if ou == "modal":
        if not modal_configured():
            raise HTTPException(503, "Modal n'est pas branche. Ouvrez la page « Brancher Modal "
                                     "ou Kaggle » et collez les deux valeurs du jeton Modal.")
        try:
            video.budget_verifier(plan["gpu"], video.DUREE_MAX_S)
        except video.BudgetDepasse as exc:
            raise HTTPException(429, str(exc)) from exc
    elif not kaggle_configured():
        raise HTTPException(503, "Kaggle n'est pas branche. Ouvrez la page « Brancher Modal "
                                 "ou Kaggle » et collez votre nom d'utilisateur et votre cle Kaggle.")

    code = video.construire_script(plan["demande"])
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
        "video": plan["resume_public"],
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
        "stdout": job.get("stdout", ""),
        "stderr": job.get("stderr", ""),
        "message": job.get("error") or "",
        "video": job.get("video"),
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
    return HTMLResponse(video.PAGE_HTML.replace("__CLE__", KEY))


@app.get("/", response_class=HTMLResponse)
def home():
    return HTMLResponse(
        """<!doctype html><html lang=fr><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<title>Sandbox — Free AI Studio</title><style>body{font-family:system-ui;max-width:980px;margin:35px auto;padding:0 18px;line-height:1.5}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:14px}.card{border:1px solid #aaa;border-radius:14px;padding:18px}.primary{border-width:2px}a.button{display:inline-block;border:1px solid #777;border-radius:9px;padding:9px 12px;text-decoration:none;margin:4px 4px 4px 0}.flow{padding:12px;border-radius:10px;background:#eee;font-family:ui-monospace,monospace}</style>
<h1>🧪 Sandbox</h1><p id=etat style='padding:12px;border-radius:10px;border:1px solid #bbb'>Vérification de l’état…</p>
<p>L’agent utilise <strong>Modal en priorité lorsqu’il est configuré</strong>. En cas d’indisponibilité d’infrastructure, il peut basculer vers Local, Kaggle puis un handoff Colab. Une erreur dans votre code n’est jamais dupliquée automatiquement sur un autre fournisseur.</p>
<div class=flow>Agent → Modal → artefacts → Agent &nbsp; | &nbsp; fallback: Local → Kaggle → Colab</div>
<div class=grid>
<div class='card primary'><h2>⚡ Modal <span id=b-modal></span></h2><p>Backend automatique distant. CPU/GPU selon le job; résultats récupérés comme ressources de l’agent.</p><a class=button href='https://modal.com/' target=_blank rel='noopener'>Ouvrir Modal ↗</a></div>
<div class=card><h2>Local <span id=b-local></span></h2><p>Fallback Python isolé dans Docker, sans Internet ni secrets du Studio.</p></div>
<div class=card><h2>Kaggle <span id=b-kaggle></span></h2><p>Fallback automatisable si configuré — sur votre machine seulement, avec vos identifiants. L’accès direct reste toujours disponible.</p><a class=button href='https://www.kaggle.com/code' target=_blank rel='noopener'>Ouvrir Kaggle ↗</a></div>
<div class=card><h2>Colab</h2><p>Accès direct permanent. En dernier recours, le Studio génère un notebook prêt à ouvrir puis réimporte les résultats.</p><a class=button href='https://colab.research.google.com/' target=_blank rel='noopener'>Ouvrir Colab ↗</a></div>
</div><p><a class=button href='/essai'>▶️ Lancer un essai</a> &nbsp; <a class=button href='/video'>🎬 Fabriquer une vidéo</a> &nbsp; <a class=button href='/cles'>🔑 Brancher Modal ou Kaggle</a> &nbsp; <a href='/docs'>API Sandbox / Agent →</a></p>
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
   e.textContent = "Le code envoye ici s'execute sur : " + nom + "."
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
