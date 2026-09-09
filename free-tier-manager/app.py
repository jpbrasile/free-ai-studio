import os
import time
import json
import logging
from typing import Any, Dict, List, Optional

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse, HTMLResponse

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("free-tier-manager")

app = FastAPI(
    title="Free AI Studio - Free Tier Manager",
    version="1.1.0",
    docs_url="/docs",
)

INTERNAL_KEY = os.getenv("FREE_TIER_MANAGER_KEY", "").strip()
FREE_ONLY = os.getenv("FREE_ONLY", "true").lower() == "true"
ALLOW_PAID = os.getenv("ALLOW_PAID_MODELS", "false").lower() == "true"
ALLOW_FREE_TIER_ACCOUNTS = os.getenv("ALLOW_FREE_TIER_ACCOUNTS", "true").lower() == "true"

AUTO_MODEL = "free-ai-auto"
BOOST_MODEL = os.getenv("OPENROUTER_BOOST_MODEL", "openrouter/auto")
BOOST_RESERVE_USD = float(os.getenv("OPENROUTER_PROTECTED_RESERVE_USD", "10"))
BOOST_TOTAL_BUDGET_USD = float(os.getenv("OPENROUTER_BOOST_TOTAL_BUDGET_USD", "5"))
BOOST_DEFAULT_CAP_USD = float(os.getenv("OPENROUTER_BOOST_DEFAULT_CAP_USD", "0.50"))
BOOST_MAX_SINGLE_USD = float(os.getenv("OPENROUTER_BOOST_MAX_SINGLE_USD", "1.00"))
BOOST_SESSION_MINUTES = int(os.getenv("OPENROUTER_BOOST_SESSION_MINUTES", "60"))
boost_state: Dict[str, Any] = {
    "enabled": False,
    "activated_at": 0.0,
    "expires_at": 0.0,
    "session_cap_usd": 0.0,
    "session_spent_usd": 0.0,
    "total_spent_usd": 0.0,
}

PROVIDERS = {
    "openrouter": {
        "key_env": "OPENROUTER_API_KEY",
        "base_url": "https://openrouter.ai/api/v1",
        "model": os.getenv("OPENROUTER_FREE_MODEL", "openrouter/free"),
        "strict_zero": True,
    },
    "groq": {
        "key_env": "GROQ_API_KEY",
        "base_url": "https://api.groq.com/openai/v1",
        "model": os.getenv("GROQ_FREE_MODEL", "openai/gpt-oss-20b"),
        "strict_zero": False,
    },
    "gemini": {
        "key_env": "GEMINI_API_KEY",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": os.getenv("GEMINI_FREE_MODEL", "gemini-3.8-flash"),
        "strict_zero": False,
    },
}

provider_cooldown_until: Dict[str, float] = {p: 0.0 for p in PROVIDERS}
openrouter_credit_cache: Dict[str, Any] = {"checked_at": 0.0, "data": None, "error": None}

stats: Dict[str, Dict[str, Any]] = {
    p: {"attempts": 0, "successes": 0, "failures": 0, "last_status": None, "last_error": None}
    for p in PROVIDERS
}



def analyze_boost_need(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Cheap local heuristic: no extra model call, so recommending Boost never costs money.
    It intentionally errs on the conservative side.
    """
    messages = payload.get("messages") or []
    text_parts = []
    image_like = 0
    for m in messages:
        content = m.get("content", "")
        if isinstance(content, str):
            text_parts.append(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict):
                    if part.get("type") in ("image_url", "input_image", "image"):
                        image_like += 1
                    t = part.get("text")
                    if isinstance(t, str):
                        text_parts.append(t)
    text = "\n".join(text_parts)
    lower = text.lower()
    score = 0
    reasons = []

    if len(text) > 12000:
        score += 3
        reasons.append("contexte très long")
    elif len(text) > 5000:
        score += 2
        reasons.append("contexte long")

    code_markers = text.count("```") + sum(lower.count(x) for x in (
        "traceback", "exception", "docker", "typescript", "python", "javascript",
        "refactor", "repository", "fichier", "files", "codebase"
    ))
    if code_markers >= 5:
        score += 3
        reasons.append("travail de code important")
    elif code_markers >= 2:
        score += 1
        reasons.append("analyse de code")

    reasoning_terms = (
        "raisonnement", "démontrer", "preuve", "analyse approfondie", "compare en détail",
        "architecture", "optimise", "debug", "diagnosti", "plan complexe", "multi-étapes",
        "research", "deep research"
    )
    hits = sum(1 for t in reasoning_terms if t in lower)
    if hits >= 3:
        score += 3
        reasons.append("raisonnement multi-étapes")
    elif hits >= 1:
        score += 1

    if image_like >= 3:
        score += 2
        reasons.append("plusieurs éléments visuels")

    if len(messages) >= 18:
        score += 2
        reasons.append("conversation très longue")

    if score >= 6:
        gain = "élevé"
        suggested = min(BOOST_DEFAULT_CAP_USD, BOOST_MAX_SINGLE_USD)
    elif score >= 3:
        gain = "moyen"
        suggested = min(0.25, BOOST_MAX_SINGLE_USD)
    else:
        gain = "faible"
        suggested = 0.0

    return {
        "gain_expected": gain,
        "score": score,
        "reasons": reasons or ["la tâche semble adaptée au mode gratuit"],
        "boost_recommended": gain in ("moyen", "élevé"),
        "suggested_max_cost_usd": round(suggested, 2),
    }


def boost_active() -> bool:
    if not boost_state["enabled"]:
        return False
    if time.time() >= boost_state["expires_at"]:
        boost_state["enabled"] = False
        return False
    if boost_state["session_spent_usd"] >= boost_state["session_cap_usd"]:
        boost_state["enabled"] = False
        return False
    if boost_state["total_spent_usd"] >= BOOST_TOTAL_BUDGET_USD:
        boost_state["enabled"] = False
        return False
    return True


async def available_openrouter_balance() -> Optional[float]:
    management_key = os.getenv("OPENROUTER_MANAGEMENT_KEY", "").strip()
    if not management_key:
        return None
    tier = await get_openrouter_credit_tier()
    if tier.get("status") == "unknown":
        return None
    purchased = float(tier.get("total_credits_purchased_usd") or 0)
    usage = float(tier.get("total_usage_usd") or 0)
    return max(0.0, purchased - usage)


async def can_activate_boost(cap_usd: float) -> Dict[str, Any]:
    if cap_usd <= 0 or cap_usd > BOOST_MAX_SINGLE_USD:
        return {"ok": False, "reason": f"Le plafond doit être entre 0 et {BOOST_MAX_SINGLE_USD:.2f} $."}

    remaining_total = max(0.0, BOOST_TOTAL_BUDGET_USD - boost_state["total_spent_usd"])
    if cap_usd > remaining_total:
        return {"ok": False, "reason": "Le budget Boost global restant est insuffisant."}

    balance = await available_openrouter_balance()
    if balance is None:
        return {
            "ok": False,
            "reason": "Solde OpenRouter non vérifiable. Ajoutez OPENROUTER_MANAGEMENT_KEY pour activer un Boost protégé."
        }
    if balance - cap_usd < BOOST_RESERVE_USD:
        return {
            "ok": False,
            "reason": f"Activation refusée : la réserve protégée de {BOOST_RESERVE_USD:.2f} $ serait entamée."
        }
    return {"ok": True, "balance_usd": round(balance, 4), "remaining_total_usd": round(remaining_total, 4)}


async def record_openrouter_usage(response_json: Dict[str, Any]) -> float:
    usage = response_json.get("usage") or {}
    cost = usage.get("cost")
    try:
        return max(0.0, float(cost or 0))
    except Exception:
        return 0.0

def provider_order() -> List[str]:
    raw = os.getenv("FREE_PROVIDER_ORDER", "gemini,openrouter,groq")
    names = [x.strip().lower() for x in raw.split(",") if x.strip()]
    return [x for x in names if x in PROVIDERS]


def configured(name: str) -> bool:
    return bool(os.getenv(PROVIDERS[name]["key_env"], "").strip())


def enabled(name: str) -> bool:
    env_name = f"ENABLE_{name.upper()}"
    # Gemini Free Tier is the normal first choice; OpenRouter Free is the
    # strict-zero fallback. Groq remains an optional third fallback.
    default = "true" if name in ("gemini", "openrouter") else "false"
    return os.getenv(env_name, default).lower() == "true"


def provider_allowed(name: str) -> bool:
    p = PROVIDERS[name]
    if not enabled(name) or not configured(name):
        return False

    # In FREE_ONLY mode, OpenRouter's openrouter/free is strict-zero.
    # Gemini/Groq are free-tier-account routes and require ALLOW_FREE_TIER_ACCOUNTS.
    if FREE_ONLY and not p["strict_zero"] and not ALLOW_FREE_TIER_ACCOUNTS:
        return False
    return True



async def get_openrouter_credit_tier() -> Dict[str, Any]:
    """
    Optional visibility helper.
    OpenRouter documents /api/v1/credits as requiring a management key.
    No management key is needed for normal inference.
    """
    management_key = os.getenv("OPENROUTER_MANAGEMENT_KEY", "").strip()
    if not management_key:
        return {
            "status": "unknown",
            "reason": "management-key-not-configured",
            "free_requests_per_day": None,
            "free_requests_per_minute": 20,
        }

    now = time.time()
    if openrouter_credit_cache["data"] is not None and now - openrouter_credit_cache["checked_at"] < 300:
        return openrouter_credit_cache["data"]

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                "https://openrouter.ai/api/v1/credits",
                headers={"Authorization": f"Bearer {management_key}"}
            )
        if response.status_code != 200:
            result = {
                "status": "unknown",
                "reason": f"credits-api-http-{response.status_code}",
                "free_requests_per_day": None,
                "free_requests_per_minute": 20,
            }
        else:
            payload = response.json().get("data", {})
            total_credits = float(payload.get("total_credits") or 0)
            total_usage = float(payload.get("total_usage") or 0)
            enhanced = total_credits >= 10.0
            result = {
                "status": "enhanced" if enhanced else "standard",
                "total_credits_purchased_usd": round(total_credits, 4),
                "total_usage_usd": round(total_usage, 4),
                "free_requests_per_day": 1000 if enhanced else 50,
                "free_requests_per_minute": 20,
            }
        openrouter_credit_cache.update({"checked_at": now, "data": result, "error": None})
        return result
    except Exception as exc:
        result = {
            "status": "unknown",
            "reason": type(exc).__name__,
            "free_requests_per_day": None,
            "free_requests_per_minute": 20,
        }
        openrouter_credit_cache.update({"checked_at": now, "data": result, "error": str(exc)[:200]})
        return result


def provider_on_cooldown(name: str) -> bool:
    return time.time() < provider_cooldown_until.get(name, 0.0)


def apply_rate_limit_cooldown(name: str, response: httpx.Response) -> None:
    if response.status_code != 429:
        return
    retry_after = response.headers.get("retry-after")
    try:
        seconds = max(5, min(int(float(retry_after)), 300)) if retry_after else 30
    except Exception:
        seconds = 30
    provider_cooldown_until[name] = time.time() + seconds

def auth_ok(auth: Optional[str]) -> bool:
    # Refuse protected endpoints when no local key exists instead of falling
    # back to an implicit shared default. /health remains intentionally public.
    return bool(INTERNAL_KEY) and auth == f"Bearer {INTERNAL_KEY}"


async def safe_status() -> Dict[str, Any]:
    providers = []
    for name in provider_order():
        p = PROVIDERS[name]
        providers.append({
            "name": name,
            "configured": configured(name),
            "enabled": enabled(name),
            "eligible": provider_allowed(name),
            "mode": "strict-zero" if p["strict_zero"] else "free-tier-account",
            "model": p["model"],
            "cooldown_seconds": max(0, int(provider_cooldown_until.get(name, 0.0) - time.time())),
            "stats": stats[name],
        })
    openrouter_tier = await get_openrouter_credit_tier()
    return {
        "openrouter_free_tier": openrouter_tier,
        "free_only": FREE_ONLY,
        "allow_paid_models": ALLOW_PAID,
        "allow_free_tier_accounts": ALLOW_FREE_TIER_ACCOUNTS,
        "public_model": AUTO_MODEL,
        "boost": {
            "active": boost_active(),
            "protected_reserve_usd": BOOST_RESERVE_USD,
            "global_budget_usd": BOOST_TOTAL_BUDGET_USD,
            "total_spent_usd": round(boost_state["total_spent_usd"], 6),
            "session_cap_usd": boost_state["session_cap_usd"],
            "session_spent_usd": round(boost_state["session_spent_usd"], 6),
        },
        "providers": providers,
    }


@app.get("/health")
async def health():
    return {"ok": True, "service": "free-tier-manager", "free_only": FREE_ONLY}


@app.get("/status")
async def status(authorization: Optional[str] = Header(default=None)):
    if not auth_ok(authorization):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return await safe_status()








@app.get("/studio", response_class=HTMLResponse)
async def studio_home():
    html = """
<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Free AI Studio</title>
<style>
:root{font-family:system-ui,sans-serif} body{max-width:960px;margin:32px auto;padding:0 18px;line-height:1.45}
.hero{padding:24px;border:1px solid #bbb;border-radius:18px;margin-bottom:18px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:14px}
.card{display:block;border:1px solid #bbb;border-radius:16px;padding:18px;text-decoration:none;color:inherit}
.card:hover{transform:translateY(-1px)} .status{font-weight:700}.muted{opacity:.72}
.pill{display:inline-block;border:1px solid #999;border-radius:999px;padding:5px 10px;margin:3px}
</style></head><body>
<div class="hero">
<h1>Free AI Studio</h1>
<p>Votre studio IA local. Le chat est prêt après configuration d’au moins un fournisseur gratuit ; les fonctions média restent optionnelles et nécessitent un backend dédié.</p>
<p class="status">🟢 Gratuit par défaut</p>
<span class="pill">Pas de dépense automatique</span>
<span class="pill">Fallback strictement contrôlé</span>
<span class="pill">Boost volontaire et plafonné</span>
</div>
<div class="grid">
<a class="card" href="http://localhost:3000/" target="_blank"><h2>💬 Chat</h2><p>Questions, rédaction, raisonnement, vision et conversation.</p></a>
<div class="card"><h2>🎨 Image — optionnel</h2><p>Non installé par défaut. À activer dans Open WebUI avec un backend d’image compatible.</p></div>
<div class="card"><h2>🎬 Vidéo — optionnel</h2><p>Non installé par défaut. Nécessite par exemple ComfyUI et un workflow vidéo compatible.</p></div>
<div class="card"><h2>🎤 Voix — optionnel</h2><p>Les capacités audio dépendent de la configuration Open WebUI et des moteurs choisis.</p></div>
<a class="card" href="/notebooklm"><h2>📚 Étudier</h2><p>Documents, sources, citations, quiz, cartes mentales et résumés avec NotebookLM.</p></a>
<a class="card" href="http://localhost:3000/" target="_blank"><h2>💻 Code</h2><p>Demander de l'aide pour coder ; les résultats Sandbox peuvent devenir des ressources de travail de l'agent.</p></a>
<a class="card" href="http://localhost:8020/" target="_blank"><h2>🧪 Sandbox</h2><p>Local isolé, Kaggle automatisable et Colab direct. Les sorties sont conservées comme artefacts réutilisables.</p></a>
</div>
<div class="hero" style="margin-top:18px">
<h2>⚡ Besoin de plus de puissance ?</h2>
<p>Le Boost reste désactivé tant que vous ne le demandez pas. Free AI Studio peut expliquer le gain attendu avant toute dépense.</p>
<a href="/boost">Voir le Boost et mes limites →</a>
<p class="muted">Les noms techniques des fournisseurs sont volontairement masqués dans cette page débutant.</p>
</div>
</body></html>
"""
    return HTMLResponse(html)


@app.get("/notebooklm", response_class=HTMLResponse)
async def notebooklm_page():
    html = """
<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Free AI Studio — Étudier avec NotebookLM</title>
<style>
body{font-family:system-ui;max-width:780px;margin:40px auto;padding:0 18px;line-height:1.5}
.card{border:1px solid #bbb;border-radius:14px;padding:18px;margin:16px 0}
a.button{display:inline-block;padding:12px 18px;border:1px solid #777;border-radius:10px;text-decoration:none}
small{opacity:.75}
</style></head><body>
<h1>📚 Étudier avec NotebookLM</h1>
<p>NotebookLM complète Free AI Studio pour apprendre, analyser et explorer vos propres sources.</p>
<div class="card">
<h3>Particulièrement utile pour</h3>
<p>📄 PDF et documents · 🌐 pages Web · ▶️ vidéos YouTube · 🎧 audio · 🧠 questions avec citations · 🗺️ cartes mentales · 📝 quiz et flashcards · 🎙️ résumés audio · 📊 rapports et supports d'étude</p>
</div>
<div class="card">
<h3>Gratuit, avec limites</h3>
<p>NotebookLM possède une offre gratuite, mais certaines fonctions ont des quotas journaliers ou mensuels. Ces limites peuvent évoluer : consultez l'aide officielle Google pour les valeurs actuelles.</p>
</div>
<p><a class="button" href="https://notebooklm.google.com/" target="_blank" rel="noopener noreferrer">Ouvrir NotebookLM ↗</a></p>
<p><small>NotebookLM reste un service Google externe. Free AI Studio ne transmet pas vos clés API ni vos documents automatiquement à NotebookLM.</small></p>
</body></html>
"""
    return HTMLResponse(html)


@app.get("/boost", response_class=HTMLResponse)
async def boost_page():
    active = boost_active()
    remaining = max(0.0, BOOST_TOTAL_BUDGET_USD - boost_state["total_spent_usd"])
    html = f"""
<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Free AI Studio — Boost</title>
<style>
body{{font-family:system-ui;max-width:760px;margin:40px auto;padding:0 18px;line-height:1.45}}
.card{{border:1px solid #bbb;border-radius:14px;padding:18px;margin:16px 0}}
button{{padding:12px 18px;border-radius:10px;border:1px solid #888;cursor:pointer}}
.good{{font-weight:700}} small{{opacity:.75}}
</style></head><body>
<h1>⚡ Boost ponctuel</h1>
<p>Le Boost sert uniquement aux tâches où un modèle plus puissant peut apporter un gain réel.</p>
<div class="card">
<b>Mode actuel :</b> {"BOOST ACTIF" if active else "GRATUIT"}<br>
Réserve protégée : {BOOST_RESERVE_USD:.2f} $<br>
Budget Boost global restant : {remaining:.2f} $<br>
Plafond conseillé par session : {BOOST_DEFAULT_CAP_USD:.2f} $
</div>
<div class="card">
<h3>Quand le Boost peut aider</h3>
<p>🧠 raisonnement difficile · 💻 gros travail de code · 📄 contexte très long · 🔬 analyse complexe</p>
<p><b>Peu utile :</b> questions courantes, traduction simple, petit résumé, conversation normale.</p>
</div>
<p><small>L'activation réelle nécessite une Management Key OpenRouter afin de vérifier que la réserve protégée reste disponible.</small></p>
</body></html>"""
    return HTMLResponse(html)


@app.post("/boost/analyze")
async def boost_analyze(request: Request, authorization: Optional[str] = Header(default=None)):
    if not auth_ok(authorization):
        raise HTTPException(status_code=401, detail="Unauthorized")
    payload = await request.json()
    if boost_active():
        # Exact budget accounting is prioritized over streaming during a paid Boost.
        payload["stream"] = False
    result = analyze_boost_need(payload)
    result["boost_active"] = boost_active()
    result["protected_reserve_usd"] = BOOST_RESERVE_USD
    result["boost_budget_remaining_usd"] = round(max(0.0, BOOST_TOTAL_BUDGET_USD - boost_state["total_spent_usd"]), 4)
    return result


@app.post("/boost/activate")
async def boost_activate(request: Request, authorization: Optional[str] = Header(default=None)):
    if not auth_ok(authorization):
        raise HTTPException(status_code=401, detail="Unauthorized")
    body = await request.json()
    try:
        cap = float(body.get("max_cost_usd", BOOST_DEFAULT_CAP_USD))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid max_cost_usd")
    check = await can_activate_boost(cap)
    if not check["ok"]:
        raise HTTPException(status_code=403, detail=check["reason"])
    now = time.time()
    boost_state.update({
        "enabled": True,
        "activated_at": now,
        "expires_at": now + BOOST_SESSION_MINUTES * 60,
        "session_cap_usd": cap,
        "session_spent_usd": 0.0,
    })
    return {
        "ok": True,
        "mode": "boost",
        "max_cost_usd": cap,
        "expires_in_minutes": BOOST_SESSION_MINUTES,
        "protected_reserve_usd": BOOST_RESERVE_USD,
    }


@app.post("/boost/disable")
async def boost_disable(authorization: Optional[str] = Header(default=None)):
    if not auth_ok(authorization):
        raise HTTPException(status_code=401, detail="Unauthorized")
    boost_state["enabled"] = False
    return {"ok": True, "mode": "free"}


@app.get("/boost/status")
async def boost_status(authorization: Optional[str] = Header(default=None)):
    if not auth_ok(authorization):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return {
        "active": boost_active(),
        "model": BOOST_MODEL if boost_active() else AUTO_MODEL,
        "session_cap_usd": boost_state["session_cap_usd"],
        "session_spent_usd": round(boost_state["session_spent_usd"], 6),
        "total_spent_usd": round(boost_state["total_spent_usd"], 6),
        "global_budget_usd": BOOST_TOTAL_BUDGET_USD,
        "protected_reserve_usd": BOOST_RESERVE_USD,
        "expires_at": boost_state["expires_at"] if boost_active() else None,
    }


@app.get("/v1/models")
async def models(authorization: Optional[str] = Header(default=None)):
    if not auth_ok(authorization):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return {
        "object": "list",
        "data": [{
            "id": AUTO_MODEL,
            "object": "model",
            "created": 0,
            "owned_by": "free-ai-studio",
            "name": "Free AI Auto",
        }],
    }


def clean_payload(payload: Dict[str, Any], upstream_model: str) -> Dict[str, Any]:
    out = dict(payload)
    out["model"] = upstream_model

    # Do not allow callers to smuggle provider routing or pricing parameters.
    for key in (
        "provider", "route", "transforms", "models", "fallback_models",
        "max_price", "pricing", "cost_limit"
    ):
        out.pop(key, None)

    return out


async def open_upstream(client: httpx.AsyncClient, name: str, payload: Dict[str, Any]):
    p = PROVIDERS[name]
    key = os.getenv(p["key_env"], "").strip()
    url = p["base_url"].rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "User-Agent": "Free-AI-Studio/1.0",
    }
    if name == "openrouter":
        headers["X-Title"] = "Free AI Studio"

    upstream_model = BOOST_MODEL if (name == "openrouter" and boost_active()) else p["model"]
    clean = clean_payload(payload, upstream_model)
    if name == "openrouter" and boost_active():
        clean["usage"] = {"include": True}
    request = client.build_request("POST", url, headers=headers, json=clean)
    return await client.send(request, stream=True)


@app.post("/v1/chat/completions")
async def chat_completions(request: Request, authorization: Optional[str] = Header(default=None)):
    if not auth_ok(authorization):
        raise HTTPException(status_code=401, detail="Unauthorized")

    payload = await request.json()
    if boost_active():
        # Exact budget accounting is prioritized over streaming during a paid Boost.
        payload["stream"] = False
    requested_model = payload.get("model", AUTO_MODEL)

    # The beginner-facing API exposes only the automatic free route.
    if requested_model not in (AUTO_MODEL, "auto", "free"):
        if FREE_ONLY or not ALLOW_PAID:
            raise HTTPException(
                status_code=403,
                detail="Paid or direct model selection is blocked. Use 'free-ai-auto'."
            )

    candidates = [name for name in provider_order() if provider_allowed(name) and not provider_on_cooldown(name)]
    if boost_active() and "openrouter" in candidates:
        candidates = ["openrouter"] + [x for x in candidates if x != "openrouter"]

    if not candidates:
        raise HTTPException(
            status_code=503,
            detail="No eligible free provider is configured. Add an API key in .env."
        )

    stream = bool(payload.get("stream", False))
    errors = []
    client = httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=15.0))

    for name in candidates:
        stats[name]["attempts"] += 1
        try:
            response = await open_upstream(client, name, payload)
            stats[name]["last_status"] = response.status_code

            if response.status_code >= 400:
                apply_rate_limit_cooldown(name, response)
                body = (await response.aread())[:800].decode("utf-8", errors="replace")
                await response.aclose()
                stats[name]["failures"] += 1
                stats[name]["last_error"] = f"HTTP {response.status_code}: {body[:300]}"
                errors.append(f"{name}: HTTP {response.status_code}")
                log.warning("Provider %s failed with HTTP %s", name, response.status_code)
                continue

            stats[name]["successes"] += 1
            stats[name]["last_error"] = None

            if stream:
                async def iterator(resp=response, cli=client):
                    try:
                        async for chunk in resp.aiter_raw():
                            yield chunk
                    finally:
                        await resp.aclose()
                        await cli.aclose()

                media_type = response.headers.get("content-type", "text/event-stream")
                return StreamingResponse(iterator(), media_type=media_type)

            data = await response.aread()
            media_type = response.headers.get("content-type", "application/json")
            await response.aclose()
            await client.aclose()
            parsed = json.loads(data)
            if name == "openrouter" and boost_active():
                spent = await record_openrouter_usage(parsed)
                boost_state["session_spent_usd"] += spent
                boost_state["total_spent_usd"] += spent
                if (boost_state["session_spent_usd"] >= boost_state["session_cap_usd"] or
                    boost_state["total_spent_usd"] >= BOOST_TOTAL_BUDGET_USD):
                    boost_state["enabled"] = False
            return JSONResponse(
                content=parsed,
                status_code=200,
                headers={
                    "X-Free-AI-Provider": name,
                    "X-Free-AI-Mode": "boost" if boost_active() else "free",
                },
                media_type=media_type.split(";")[0],
            )

        except Exception as exc:
            stats[name]["failures"] += 1
            stats[name]["last_error"] = str(exc)[:300]
            errors.append(f"{name}: {type(exc).__name__}")
            log.exception("Provider %s raised an error", name)

    await client.aclose()
    raise HTTPException(
        status_code=503,
        detail={"message": "All configured free providers failed.", "attempts": errors}
    )
