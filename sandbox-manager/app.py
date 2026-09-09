from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Dict, Optional

import httpx
from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("sandbox-manager")

app = FastAPI(title="Free AI Studio Sandbox Manager", version="2.0.0")

KEY = os.getenv("SANDBOX_MANAGER_KEY", "").strip()
WORKER_KEY = os.getenv("SANDBOX_WORKER_KEY", "").strip()
WORKER_URL = os.getenv("SANDBOX_WORKER_URL", "http://sandbox-worker:8000").rstrip("/")
ROOT = Path("/workspace")
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
KAGGLE_ENABLED = os.getenv("KAGGLE_ENABLED", "false").lower() == "true"
COLAB_API_ENABLED = os.getenv("COLAB_API_ENABLED", "false").lower() == "true"
MODAL_ENABLED = os.getenv("MODAL_ENABLED", "false").lower() == "true"


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


def modal_configured() -> bool:
    return MODAL_ENABLED and bool(os.getenv("MODAL_TOKEN_ID", "").strip()) and bool(
        os.getenv("MODAL_TOKEN_SECRET", "").strip()
    )


def kaggle_configured() -> bool:
    return KAGGLE_ENABLED and bool(os.getenv("KAGGLE_USERNAME", "").strip()) and bool(
        os.getenv("KAGGLE_API_TOKEN", "").strip() or os.getenv("KAGGLE_KEY", "").strip()
    )


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


def modal_execute(jid: str, code: str, gpu: bool, internet: bool) -> dict:
    if not modal_configured():
        raise BackendUnavailable("Modal is not configured")
    try:
        import modal
    except Exception as exc:
        raise BackendUnavailable(f"Modal SDK unavailable: {exc}") from exc

    timeout = max(1, int(os.getenv("MODAL_JOB_TIMEOUT_SECONDS", os.getenv("SANDBOX_TIMEOUT_SECONDS", "120"))))
    idle_timeout = max(1, int(os.getenv("MODAL_IDLE_TIMEOUT_SECONDS", "60")))
    cleanup_grace = max(15, int(os.getenv("MODAL_CLEANUP_GRACE_SECONDS", "60")))
    sandbox_lifetime = timeout + cleanup_grace
    cpu = float(os.getenv("MODAL_CPU", "1.0"))
    memory = int(os.getenv("MODAL_MEMORY_MB", "2048"))
    gpu_name = os.getenv("MODAL_GPU_DEFAULT", "T4").strip() if gpu else None
    app_name = os.getenv("MODAL_APP_NAME", "free-ai-studio-sandbox").strip() or "free-ai-studio-sandbox"
    sb = None
    local_out = JOBS / jid / "modal-output"
    local_out.mkdir(parents=True, exist_ok=True)

    try:
        modal_app = modal.App.lookup(app_name, create_if_missing=True)
        image = modal.Image.debian_slim(python_version="3.12")
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
            "error": "Modal requires MODAL_ENABLED=true plus MODAL_TOKEN_ID and MODAL_TOKEN_SECRET.",
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
                "error": "Kaggle orchestration requires KAGGLE_ENABLED=true plus KAGGLE_USERNAME and KAGGLE_API_TOKEN (or legacy KAGGLE_KEY).",
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
        "title": job["title"][:50],
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


def run_auto(jid: str, code: str, gpu: bool, internet: bool):
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

    if kaggle_configured():
        attempts.append({"provider": "kaggle", "result": "selected"})
        job = read_job(jid)
        job["fallback_attempts"] = attempts
        write_job(jid, job)
        run_kaggle(jid, code, gpu, internet)
        return
    attempts.append({"provider": "kaggle", "result": "not_configured"})

    attempts.append({"provider": "colab", "result": "handoff"})
    prepare_colab_handoff(jid, code, attempts)


@app.get("/health")
def health():
    return {"ok": True, "service": "sandbox-manager", "version": "2.0.0"}


@app.get("/providers")
def providers(authorization: Optional[str] = Header(default=None)):
    auth(authorization)
    return {
        "default": "auto",
        "automatic_order": ["modal", "local", "kaggle", "colab"],
        "modal": {
            "configured": modal_configured(),
            "enabled": MODAL_ENABLED,
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
            "direct_url": "https://www.kaggle.com/code",
            "automatic": True,
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
def create_job(req: JobRequest, authorization: Optional[str] = Header(default=None)):
    auth(authorization)
    if len(req.code.encode()) > MAX_JOB_CODE:
        raise HTTPException(413, "Code too large")
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
        threading.Thread(target=run_auto, args=(jid, req.code, req.gpu, req.internet), daemon=True).start()
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


@app.get("/", response_class=HTMLResponse)
def home():
    return HTMLResponse(
        """<!doctype html><html lang=fr><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<title>Sandbox — Free AI Studio</title><style>body{font-family:system-ui;max-width:980px;margin:35px auto;padding:0 18px;line-height:1.5}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:14px}.card{border:1px solid #aaa;border-radius:14px;padding:18px}.primary{border-width:2px}a.button{display:inline-block;border:1px solid #777;border-radius:9px;padding:9px 12px;text-decoration:none;margin:4px 4px 4px 0}.flow{padding:12px;border-radius:10px;background:#eee;font-family:ui-monospace,monospace}</style>
<h1>🧪 Sandbox</h1><p>L’agent utilise <strong>Modal en priorité lorsqu’il est configuré</strong>. En cas d’indisponibilité d’infrastructure, il peut basculer vers Local, Kaggle puis un handoff Colab. Une erreur dans votre code n’est jamais dupliquée automatiquement sur un autre fournisseur.</p>
<div class=flow>Agent → Modal → artefacts → Agent &nbsp; | &nbsp; fallback: Local → Kaggle → Colab</div>
<div class=grid>
<div class='card primary'><h2>⚡ Modal — principal</h2><p>Backend automatique distant. CPU/GPU selon le job; résultats récupérés comme ressources de l’agent.</p><a class=button href='https://modal.com/' target=_blank rel='noopener'>Ouvrir Modal ↗</a></div>
<div class=card><h2>Local</h2><p>Fallback Python isolé dans Docker, sans Internet ni secrets du Studio.</p></div>
<div class=card><h2>Kaggle</h2><p>Fallback automatisable si configuré, avec accès utilisateur direct toujours disponible.</p><a class=button href='https://www.kaggle.com/code' target=_blank rel='noopener'>Ouvrir Kaggle ↗</a></div>
<div class=card><h2>Colab</h2><p>Accès direct permanent. En dernier recours, le Studio génère un notebook prêt à ouvrir puis réimporte les résultats.</p><a class=button href='https://colab.research.google.com/' target=_blank rel='noopener'>Ouvrir Colab ↗</a></div>
</div><p><a href='/docs'>API Sandbox / Agent →</a></p></html>"""
    )
