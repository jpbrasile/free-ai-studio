from __future__ import annotations
import os, subprocess, uuid
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="Free AI Studio Local Sandbox Worker", version="1.0.0", docs_url=None, redoc_url=None)
KEY = os.getenv("SANDBOX_WORKER_KEY", "").strip()
# /workspace dans le conteneur ; configurable pour charger le service hors
# conteneur (CI : scripts/verifier-imports.py, tests/).
ROOT = Path(os.getenv("SANDBOX_WORKSPACE", "/workspace")) / "jobs"
ROOT.mkdir(parents=True, exist_ok=True)
# Variables de l'environnement du conteneur laissees passer au script.
# VIDE par defaut, et c'est le point : le bac a sable sur processeur n'en a
# besoin d'aucune, et chacune est une chose de plus que le code utilisateur
# peut lire. Le worker GPU, lui, en declare quelques-unes dans sa surcouche :
# sans ce que le runtime NVIDIA pose dans le conteneur le script ne trouve pas
# la carte, et sans HF_HOME il retelechargerait 34 Go de modele a chaque clip.
PASSANTES = tuple(n.strip() for n in os.getenv("SANDBOX_ENV_PASSTHROUGH", "").split(",") if n.strip())
# Dossier dont la presence est exigee pour que ce bac a sable soit utile. Vide
# par defaut ; /health le rapporte quand il est pose (voir health()).
POIDS = os.getenv("SANDBOX_POIDS_REQUIS", "").strip()
MAX_CODE = int(os.getenv("SANDBOX_MAX_CODE_BYTES", "500000"))
MAX_OUTPUT = int(os.getenv("SANDBOX_MAX_OUTPUT_BYTES", "200000"))
TIMEOUT = int(os.getenv("SANDBOX_TIMEOUT_SECONDS", "120"))

class RunRequest(BaseModel):
    job_id: Optional[str] = None
    code: str = Field(min_length=1)


def auth(value: Optional[str]):
    if not KEY or value != f"Bearer {KEY}":
        raise HTTPException(401, "Unauthorized")

@app.get("/health")
def health():
    etat = {"ok": True, "network_policy": "compose-internal-only"}
    # Ce que ce bac a sable doit AVOIR pour servir a quelque chose. Vide par
    # defaut -- celui sur processeur n'exige rien. Celui de la carte, lui,
    # declare les 34 Go de poids du modele video : il n'a pas internet, donc
    # s'ils manquent il ne les trouvera jamais, et le gestionnaire doit router
    # ailleurs AVANT de lancer un clip qui echouerait dix minutes plus tard.
    if POIDS:
        etat["poids_chemin"] = POIDS
        etat["poids_presents"] = poids_complets()
    return etat


# Depuis le 20/09, le Studio telecharge ces poids LUI-MEME des qu'un clip les
# demande : le dossier existe donc pendant les vingt-deux minutes ou il se
# remplit. << Le dossier existe >> ne peut plus vouloir dire << pret >>, sans
# quoi le gestionnaire routerait un clip ici au bout de trois minutes et le
# perdrait -- et c'etait deja vrai d'un telechargement interrompu a la main.
# Deux marques, les memes que cote gestionnaire : aucun fichier `.incomplete`
# (huggingface_hub les nomme ainsi pendant qu'il ecrit) et au moins 98 % des
# 34 203 034 754 octets mesures le 20/09.
POIDS_OCTETS = int(os.getenv("SANDBOX_POIDS_OCTETS", "34203034754"))


def poids_complets() -> bool:
    dossier = Path(POIDS)
    if not dossier.is_dir():
        return False
    total = 0
    try:
        for f in dossier.rglob("*"):
            if f.name.endswith(".incomplete"):
                return False
            if f.is_file():
                total += f.stat().st_size
    except OSError:
        return False
    return total >= 0.98 * POIDS_OCTETS

@app.post("/run")
def run(req: RunRequest, authorization: Optional[str] = Header(default=None)):
    auth(authorization)
    raw = req.code.encode("utf-8")
    if len(raw) > MAX_CODE:
        raise HTTPException(413, "Code too large")
    job_id = req.job_id or uuid.uuid4().hex
    if not all(c.isalnum() or c in "-_" for c in job_id):
        raise HTTPException(400, "Invalid job id")
    job_dir = ROOT / job_id
    out_dir = job_dir / "output"
    job_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    script = job_dir / "main.py"
    script.write_text(req.code, encoding="utf-8")
    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONUNBUFFERED": "1",
        "HOME": str(job_dir),
        "FREE_AI_OUTPUT_DIR": str(out_dir),
    }
    for nom in PASSANTES:
        valeur = os.environ.get(nom)
        if valeur is not None:
            env[nom] = valeur
    try:
        proc = subprocess.run(
            ["python", "-I", str(script)], cwd=job_dir, env=env,
            text=True, capture_output=True, timeout=TIMEOUT
        )
        stdout = proc.stdout[-MAX_OUTPUT:]
        stderr = proc.stderr[-MAX_OUTPUT:]
        timed_out = False
        code = proc.returncode
    except subprocess.TimeoutExpired as exc:
        stdout = (exc.stdout or "")[-MAX_OUTPUT:] if isinstance(exc.stdout, str) else ""
        stderr = (exc.stderr or "")[-MAX_OUTPUT:] if isinstance(exc.stderr, str) else ""
        timed_out = True
        code = 124
    artifacts=[]
    for p in sorted(out_dir.rglob("*")):
        if p.is_file() and not p.is_symlink():
            rel=p.relative_to(out_dir).as_posix()
            artifacts.append({"name": rel, "size": p.stat().st_size})
    return {"job_id": job_id, "exit_code": code, "timed_out": timed_out,
            "stdout": stdout, "stderr": stderr, "artifacts": artifacts}
