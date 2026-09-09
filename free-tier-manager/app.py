import asyncio
import os
import re
import time
import json
import logging
from pathlib import Path
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

# --- Magasin de cles ecrit par la page /cles --------------------------------
# Le conteneur recoit ses variables par env_file, evaluees a sa CREATION : une
# cle ajoutee dans .env n'a aucun effet sur un conteneur deja lance, et
# `docker compose restart` ne suffit pas non plus. Un debutant sans terminal ne
# peut donc pas se depanner. Les cles saisies dans l'interface sont conservees
# ici et relues a chaque appel, ce qui les rend actives immediatement.
# Une variable d'environnement non vide reste prioritaire : le .env garde le
# dernier mot pour qui sait s'en servir.
CONFIG_DIR = Path(os.getenv("FREE_AI_CONFIG_DIR", "/config"))
KEYS_FILE = CONFIG_DIR / "keys.json"

# Ce que le debutant doit comprendre de chaque fournisseur, et ou aller chercher
# la cle. L'ordre d'essai reel reste FREE_PROVIDER_ORDER.
PROVIDER_HELP = {
    "gemini": {
        "titre": "Gemini (Google)",
        "role": "Le choix par defaut : il repond aux questions, lit vos images et sait resumer un long texte.",
        "url": "https://aistudio.google.com/apikey",
        "repere": "Connectez-vous avec votre compte Google, puis cliquez sur « Create API key ». La cle commence par AIza.",
    },
    "openrouter": {
        "titre": "OpenRouter",
        "role": "Le filet de secours quand Gemini a atteint sa limite du jour. Route sans aucun cout.",
        "url": "https://openrouter.ai/settings/keys",
        "repere": "Creez un compte, puis « Create Key ». La cle commence par sk-or-.",
    },
    "groq": {
        "titre": "Groq",
        "role": "Optionnel. Tres rapide, utile si les deux autres sont satures.",
        "url": "https://console.groq.com/keys",
        "repere": "Creez un compte, puis « Create API Key ». La cle commence par gsk_.",
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


def stored_keys() -> Dict[str, str]:
    try:
        data = json.loads(KEYS_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        log.warning("magasin de cles illisible (%s) : %s", KEYS_FILE, exc)
        return {}
    return {k: v for k, v in data.items() if isinstance(v, str)}


def store_key(env_name: str, value: str) -> None:
    data = stored_keys()
    if value:
        data[env_name] = value
    else:
        data.pop(env_name, None)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(data, indent=2)
    tmp = CONFIG_DIR / "keys.json.tmp"
    try:
        tmp.write_text(blob, encoding="utf-8")
        tmp.replace(KEYS_FILE)
    except OSError:
        # Le renommage atomique echoue sur certains montages Windows ; le fichier
        # est petit et n'a qu'un ecrivain, l'ecriture directe reste acceptable.
        KEYS_FILE.write_text(blob, encoding="utf-8")
    try:
        KEYS_FILE.chmod(0o600)
    except OSError:
        pass


def provider_key(name: str) -> str:
    env_name = PROVIDERS[name]["key_env"]
    value = os.getenv(env_name, "").strip()
    if value:
        return value
    return stored_keys().get(env_name, "").strip()


def key_source(name: str) -> Optional[str]:
    env_name = PROVIDERS[name]["key_env"]
    if os.getenv(env_name, "").strip():
        return "env"
    if stored_keys().get(env_name, "").strip():
        return "interface"
    return None


def mask(value: str) -> str:
    """Ne rend jamais la cle : juste de quoi la reconnaitre."""
    return ("*" * 6 + value[-4:]) if len(value) >= 8 else "*" * 8


def configured(name: str) -> bool:
    return bool(provider_key(name))


def enabled(name: str) -> bool:
    env_name = f"ENABLE_{name.upper()}"
    # Gemini Free Tier is the normal first choice; OpenRouter Free is the
    # strict-zero fallback. Groq remains an optional third fallback.
    default = "true" if name in ("gemini", "openrouter") else "false"
    if os.getenv(env_name, default).lower() == "true":
        return True
    # Coller une cle dans /cles est un acte delibere : il vaut activation, comme
    # les jetons Modal/Kaggle cote Sandbox. Sans cela, ENABLE_GROQ=false rendrait
    # la saisie sans effet et la page annoncerait une cle qui ne sert jamais.
    # Le bouton << Oublier >> revoque.
    return bool(stored_keys().get(PROVIDERS[name]["key_env"], "").strip())


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


# --- Reglages d'Open WebUI, poses une seule fois -----------------------------
# Open WebUI garde ses reglages dans SA base. Les variables du docker-compose ne
# sont lues qu'au tout premier demarrage : ensuite la base gagne, en silence.
# Mesure du 09/09 : ENABLE_WEB_SEARCH=true etait bien dans le conteneur et
# << web.search.enable >> valait quand meme false en base. Resultat pour le
# debutant : le bouton de recherche web n'existait nulle part, et rien
# n'expliquait pourquoi.
#
# Ce reglage est donc pose par un appel a l'API d'administration, UNE SEULE
# FOIS : le temoin ecrit dans /config dit que c'est fait. Sans ce temoin, une
# personne qui coupe volontairement la recherche web la verrait revenir a chaque
# redemarrage.
WEBUI_URL = os.getenv("OPEN_WEBUI_INTERNAL_URL", "http://open-webui:8080")
WEBUI_ADMIN_EMAIL = "admin@localhost"
WEBUI_ADMIN_PASSWORD = "admin"
REGLAGES_FAITS = CONFIG_DIR / "open-webui-regle.json"
IMAGE_SIZE_DEFAUT = "1024x1024"

# Les six exemples proposes sur la page d'accueil du chat. Ceux d'origine sont en
# anglais, sur une interface qu'on vient de mettre en francais : le debutant lit
# << Overcome procrastination >> comme premier contact.
SUGGESTIONS = [
    {"title": ["Expliquer simplement", "ce qu'est la méthanisation"],
     "content": "Explique en trois phrases simples ce qu'est la méthanisation."},
    {"title": ["Résumer un texte", "que je vais coller"],
     "content": "Je vais coller un texte. Résume-le en cinq points, en français simple."},
    {"title": ["Écrire un courriel", "poli et bref"],
     "content": "Aide-moi à écrire un courriel poli et bref pour demander un rendez-vous."},
    {"title": ["Fabriquer une image", "à partir d'une description"],
     "content": "Active « Image » dans les intégrations (le bouton en forme de rouage sous la zone de saisie), puis décris l'image voulue. Exemple : un phare breton sous un ciel d'orage, peinture à l'huile."},
    {"title": ["Chercher sur le Web", "et citer les sources"],
     "content": "Active « Recherche Web » dans les intégrations (le bouton en forme de rouage sous la zone de saisie), puis pose ta question. Exemple : quel est le prix du gaz naturel en France cette semaine ?"},
    {"title": ["Comprendre une photo", "que je joins"],
     "content": "Je joins une photo avec le bouton +. Dis-moi ce qu'elle montre et ce qui mérite attention."},
]


async def webui_jeton(client: httpx.AsyncClient) -> Optional[str]:
    """Ouvre une session d'administration. Avec WEBUI_AUTH=false, Open WebUI
    cree et accepte admin@localhost/admin ; avec un vrai compte, il refuse et
    les reglages restent a faire a la main, ce que le journal dit."""
    try:
        r = await client.post(
            f"{WEBUI_URL}/api/v1/auths/signin",
            json={"email": WEBUI_ADMIN_EMAIL, "password": WEBUI_ADMIN_PASSWORD},
        )
    except httpx.HTTPError:
        return None
    if r.status_code != 200:
        return None
    return r.json().get("token")


async def reparer_connexion_webui(client: httpx.AsyncClient, entetes: Dict[str, str]) -> None:
    """Remet d'aplomb la liaison entre le chat et le routeur, a CHAQUE demarrage.

    Open WebUI recopie OPENAI_API_KEY dans sa propre base au tout premier
    demarrage, puis n'ecoute plus la variable d'environnement. Le jour ou la cle
    interne change -- un second dossier clone par megarde, un .env efface et
    refait, une reinstallation qui garde l'ancien volume -- les deux cotes ne
    parlent plus de la meme cle. Le routeur repond alors 401, et Open WebUI
    affiche simplement une liste de modeles VIDE, sans un mot d'explication.
    Impossible a deviner pour un debutant : il vient de coller une cle de
    fournisseur et croit que c'est elle qui ne marche pas.

    On ne peut donc pas poser cette liaison une fois pour toutes comme les
    reglages de confort : elle se verifie a chaque demarrage. On n'ecrit que si
    la valeur gardee differe, pour ne rien deranger dans le cas normal.
    """
    if not INTERNAL_KEY:
        return
    interne = os.getenv("FREE_TIER_MANAGER_INTERNAL_URL",
                        "http://free-tier-manager:8000/v1")
    try:
        r = await client.get(f"{WEBUI_URL}/openai/config", headers=entetes)
        cfg = r.json()
        cfg.pop("status", None)
        urls = list(cfg.get("OPENAI_API_BASE_URLS") or [])
        cles = list(cfg.get("OPENAI_API_KEYS") or [])

        if interne in urls:
            rang = urls.index(interne)
        else:
            urls.append(interne)
            rang = len(urls) - 1
        # Open WebUI apparie les deux listes par leur rang : une cle manquante
        # decalerait toutes les suivantes.
        while len(cles) < len(urls):
            cles.append("")

        if cles[rang] == INTERNAL_KEY and cfg.get("ENABLE_OPENAI_API"):
            return

        cles[rang] = INTERNAL_KEY
        cfg["ENABLE_OPENAI_API"] = True
        cfg["OPENAI_API_BASE_URLS"] = urls
        cfg["OPENAI_API_KEYS"] = cles
        r = await client.post(f"{WEBUI_URL}/openai/config/update",
                              headers=entetes, json=cfg)
        r.raise_for_status()
        log.info("Liaison chat -> routeur remise d'aplomb (la cle gardee par "
                 "Open WebUI ne correspondait plus).")
    except (httpx.HTTPError, ValueError, IndexError) as exc:
        log.warning("Liaison chat -> routeur non verifiee : %s", exc)


async def poser_reglages_webui() -> None:
    faits: List[str] = []
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
        # Open WebUI demarre apres nous : on attend, sans jamais bloquer le
        # routeur lui-meme (cette fonction tourne dans une tache de fond).
        for _ in range(120):
            try:
                r = await client.get(f"{WEBUI_URL}/health")
                if r.status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            await asyncio.sleep(5)
        else:
            log.info("Open WebUI n'a pas repondu : reglages remis a plus tard.")
            return

        jeton = await webui_jeton(client)
        if not jeton:
            log.info("Open WebUI demande un compte : recherche web et image a "
                     "activer depuis ses parametres d'administration.")
            return
        entetes = {"Authorization": f"Bearer {jeton}"}

        # 0. La liaison elle-meme, verifiee a chaque demarrage. Elle passe AVANT
        #    le temoin ci-dessous : sans elle, il n'y a aucun modele dans le chat
        #    et tout le reste est sans objet.
        await reparer_connexion_webui(client, entetes)

        # Les reglages de confort, eux, ne se posent qu'une fois : ce que
        # l'utilisateur y change ensuite lui appartient.
        if REGLAGES_FAITS.exists():
            return

        # 1. Appel d'outils << legacy >>. Sans cela, les interrupteurs
        #    << Recherche Web >> et << Image >> ne declenchent RIEN : Open WebUI
        #    se contente alors de proposer l'outil au modele, qui decide seul --
        #    et avec le routeur gratuit, la reponse revenait vide (mesure du
        #    09/09 : bulle vide, aucun appel a /v1/images/generations). En
        #    << legacy >>, c'est Open WebUI lui-meme qui fabrique l'image ou
        #    lance la recherche des que l'interrupteur est mis. Ce que le
        #    debutant coche se produit.
        try:
            r = await client.get(f"{WEBUI_URL}/api/v1/configs/models", headers=entetes)
            cfg = r.json()
            cfg.pop("status", None)
            params = dict(cfg.get("DEFAULT_MODEL_PARAMS") or {})
            if params.get("function_calling") != "legacy":
                params["function_calling"] = "legacy"
                cfg["DEFAULT_MODEL_PARAMS"] = params
                r = await client.post(f"{WEBUI_URL}/api/v1/configs/models",
                                      headers=entetes, json=cfg)
                r.raise_for_status()
                faits.append("interrupteurs d'integrations effectifs")
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("Appel d'outils non regle : %s", exc)

        # 2. Exemples de depart en francais, l'interface l'etant deja.
        try:
            r = await client.post(f"{WEBUI_URL}/api/v1/configs/suggestions",
                                  headers=entetes, json={"suggestions": SUGGESTIONS})
            r.raise_for_status()
            faits.append("exemples de depart en francais")
        except httpx.HTTPError as exc:
            log.warning("Exemples de depart non poses : %s", exc)

        # 3. Recherche web. DuckDuckGo ne demande ni cle ni compte.
        try:
            r = await client.get(f"{WEBUI_URL}/api/v1/retrieval/config", headers=entetes)
            cfg = r.json()
            cfg.pop("status", None)
            web = cfg.get("web") or {}
            if not web.get("ENABLE_WEB_SEARCH") or not web.get("WEB_SEARCH_ENGINE"):
                web["ENABLE_WEB_SEARCH"] = True
                web["WEB_SEARCH_ENGINE"] = os.getenv("WEB_SEARCH_ENGINE", "duckduckgo")
                cfg["web"] = web
                r = await client.post(f"{WEBUI_URL}/api/v1/retrieval/config/update",
                                      headers=entetes, json=cfg)
                r.raise_for_status()
                faits.append("recherche web (%s)" % web["WEB_SEARCH_ENGINE"])
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("Recherche web non activee : %s", exc)

        # 4. Fabrication d'images, adressee a NOTRE route /v1/images/generations.
        #    La cle Google reste ainsi au seul endroit ou le debutant la saisit.
        try:
            r = await client.get(f"{WEBUI_URL}/api/v1/images/config", headers=entetes)
            cfg = r.json()
            cfg.pop("status", None)
            if not cfg.get("ENABLE_IMAGE_GENERATION"):
                cfg["ENABLE_IMAGE_GENERATION"] = True
                cfg["IMAGE_GENERATION_ENGINE"] = "openai"
                cfg["IMAGES_OPENAI_API_BASE_URL"] = os.getenv(
                    "FREE_TIER_MANAGER_INTERNAL_URL", "http://free-tier-manager:8000/v1")
                cfg["IMAGES_OPENAI_API_KEY"] = INTERNAL_KEY
                cfg["IMAGE_GENERATION_MODEL"] = IMAGE_MODEL
                cfg["IMAGE_SIZE"] = IMAGE_SIZE_DEFAUT
                r = await client.post(f"{WEBUI_URL}/api/v1/images/config/update",
                                      headers=entetes, json=cfg)
                r.raise_for_status()
                faits.append("fabrication d'images")
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("Fabrication d'images non activee : %s", exc)

    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        REGLAGES_FAITS.write_text(
            json.dumps({
                "pose_le": time.strftime("%Y-%m-%d %H:%M:%S"),
                "reglages": faits,
                "note": "Tant que ce fichier existe, Free AI Studio ne retouche plus "
                        "les reglages d'Open WebUI : ce que vous y changez reste. "
                        "Supprimez ce fichier et redemarrez pour les reposer.",
            }, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError as exc:
        log.warning("Temoin de reglages non ecrit (%s) : %s", REGLAGES_FAITS, exc)
    log.info("Reglages Open WebUI poses : %s", ", ".join(faits) or "rien a changer")


@app.on_event("startup")
async def demarrage() -> None:
    asyncio.create_task(poser_reglages_webui())


@app.get("/health")
async def health():
    return {"ok": True, "service": "free-tier-manager", "free_only": FREE_ONLY}


@app.get("/status")
async def status(authorization: Optional[str] = Header(default=None)):
    if not auth_ok(authorization):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return await safe_status()








async def verify_key(name: str, key: str) -> Dict[str, Any]:
    """Essaie vraiment la cle chez le fournisseur. Une cle n'est jamais declaree
    bonne sans qu'un appel ait abouti : un `max_tokens: 1` coute zero sur les
    plans gratuits et evite d'annoncer un chat qui ne repondra pas."""
    p = PROVIDERS[name]
    url = p["base_url"].rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "User-Agent": "Free-AI-Studio/1.0",
    }
    if name == "openrouter":
        headers["X-Title"] = "Free AI Studio"
    payload = {
        "model": p["model"],
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
        "stream": False,
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(url, headers=headers, json=payload)
    except httpx.HTTPError as exc:
        return {
            "valide": False,
            "message": "Le fournisseur n'a pas repondu (%s). Verifiez votre connexion Internet." % type(exc).__name__,
        }

    # Les trois fournisseurs ne rendent pas la meme forme : OpenRouter et Groq un
    # objet {"error": {"message": ...}}, Gemini parfois une LISTE d'objets. Un
    # acces direct .get() plantait le point d'entree et le navigateur n'affichait
    # qu'un « Internal Server Error » illisible au lieu du motif du refus.
    def message_erreur(body: Any) -> str:
        if isinstance(body, list):
            body = body[0] if body else None
        if not isinstance(body, dict):
            return ""
        err = body.get("error")
        if isinstance(err, dict):
            return str(err.get("message") or "")
        if isinstance(err, str):
            return err
        return str(body.get("message") or "")

    try:
        detail = message_erreur(response.json())
    except ValueError:
        detail = ""
    detail = (detail or response.text)[:300]

    if response.status_code == 200:
        return {"valide": True, "message": "Cle valide : le fournisseur a repondu."}
    if response.status_code == 429:
        return {
            "valide": True,
            "message": "Cle valide, mais le quota du moment est atteint. Elle est enregistree et servira des que le quota repart. " + detail,
        }
    if response.status_code in (401, 403):
        return {
            "valide": False,
            "message": "Cle refusee. Verifiez que vous l'avez copiee en entier, sans espace au debut ni a la fin. " + detail,
        }
    return {
        "valide": False,
        "message": "Refus du fournisseur (HTTP %d). %s" % (response.status_code, detail),
    }


@app.get("/cles/etat")
async def cles_etat():
    fournisseurs = []
    for name in provider_order():
        aide = PROVIDER_HELP.get(name, {})
        key = provider_key(name)
        fournisseurs.append({
            "nom": name,
            "titre": aide.get("titre", name),
            "role": aide.get("role", ""),
            "url": aide.get("url", ""),
            "repere": aide.get("repere", ""),
            "renseignee": bool(key),
            "indice": mask(key) if key else "",
            "source": key_source(name),
            "active": provider_allowed(name),
            "autorise": enabled(name),
        })
    return {
        "fournisseurs": fournisseurs,
        "chat_pret": any(f["active"] for f in fournisseurs),
    }


@app.post("/cles/tester")
async def cles_tester(request: Request):
    body = await request.json()
    name = str(body.get("fournisseur", "")).strip().lower()
    key = str(body.get("cle", "")).strip()
    if name not in PROVIDERS:
        raise HTTPException(status_code=400, detail="Fournisseur inconnu")
    if not key:
        raise HTTPException(status_code=400, detail="Aucune cle fournie")
    result = await verify_key(name, key)
    env_name = PROVIDERS[name]["key_env"]
    if result["valide"]:
        store_key(env_name, key)
        log.info("cle enregistree pour %s (source interface)", name)
        if os.getenv(env_name, "").strip():
            # Sans cet avertissement, coller une cle ici serait sans effet visible :
            # la variable d'environnement garde la priorite et le message
            # « enregistree » laisserait croire au contraire.
            result["message"] += (
                " Attention : le fichier .env contient deja une cle pour ce service,"
                " et c'est elle qui continue d'etre utilisee. Pour que la cle saisie"
                " ici serve, videz la ligne %s du fichier .env." % env_name
            )
    return {
        "valide": result["valide"],
        "message": result["message"],
        "enregistree": result["valide"],
        "active": provider_allowed(name),
        "autorise": enabled(name),
    }


@app.post("/cles/oublier")
async def cles_oublier(request: Request):
    body = await request.json()
    name = str(body.get("fournisseur", "")).strip().lower()
    if name not in PROVIDERS:
        raise HTTPException(status_code=400, detail="Fournisseur inconnu")
    store_key(PROVIDERS[name]["key_env"], "")
    return {"oubliee": True, "encore_dans_env": key_source(name) == "env"}


CLES_HTML = """
<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Free AI Studio — vos cles</title>
<style>
:root{font-family:system-ui,sans-serif}
body{max-width:820px;margin:32px auto;padding:0 18px;line-height:1.5}
h1{margin-bottom:4px}
.sous{opacity:.75;margin-top:0}
.banniere{padding:16px 18px;border-radius:14px;margin:18px 0;border:1px solid #bbb}
.pret{background:#e8f6ec;border-color:#7fb98f}
.pasret{background:#fdf3e3;border-color:#d9ad63}
.carte{border:1px solid #bbb;border-radius:16px;padding:18px;margin-bottom:16px}
.entete{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.entete h2{margin:0;font-size:1.15rem}
.pastille{font-size:.8rem;border-radius:999px;padding:3px 10px;border:1px solid #999}
.verte{background:#e8f6ec;border-color:#7fb98f}
.grise{background:#f1f1f1}
.role{margin:8px 0 14px}
.etape{margin:10px 0}
.num{display:inline-block;width:22px;height:22px;line-height:22px;text-align:center;
 border-radius:999px;background:#333;color:#fff;font-size:.78rem;margin-right:7px}
a.bouton,button{font:inherit;padding:9px 14px;border-radius:10px;border:1px solid #666;
 background:#fff;cursor:pointer;text-decoration:none;color:inherit;display:inline-block}
button.primaire{background:#222;color:#fff;border-color:#222}
button[disabled]{opacity:.5;cursor:default}
input[type=password]{font:inherit;padding:9px 11px;border-radius:10px;border:1px solid #999;
 width:min(420px,100%);box-sizing:border-box}
.repere{font-size:.86rem;opacity:.75;margin:6px 0 0 29px}
.resultat{margin-top:10px;font-size:.92rem}
.ok{color:#1d6b32}.ko{color:#9b2116}
.pied{margin-top:26px;padding-top:16px;border-top:1px solid #ddd;font-size:.9rem;opacity:.8}
</style></head><body>
<h1>Vos cles</h1>
<p class="sous">Une cle est un mot de passe que le service vous donne pour que ce studio puisse
lui parler en votre nom. Elle reste sur cet ordinateur.</p>

<div id="banniere" class="banniere pasret">Verification en cours...</div>
<div id="cartes"></div>

<div class="pied">
Vous n'avez rien a payer : ces trois services ont une offre gratuite.
La cle collee ici est verifiee par un vrai appel avant d'etre gardee, et elle
prend effet tout de suite — rien d'autre a relancer.
</div>

<script>
function element(html){const d=document.createElement("div");d.innerHTML=html.trim();return d.firstChild;}

function pastille(f){
  if(f.active) return '<span class="pastille verte">marche</span>';
  if(f.renseignee && !f.autorise) return '<span class="pastille grise">cle enregistree, service desactive dans la configuration</span>';
  if(f.renseignee) return '<span class="pastille grise">cle enregistree</span>';
  return '<span class="pastille grise">pas encore de cle</span>';
}

function carte(f){
  const indice = f.renseignee ? ' <span class="repere">Cle actuelle : '+f.indice+' (venue de '+(f.source==="env"?"votre fichier .env":"cette page")+')</span>' : '';
  const c = element(
    '<div class="carte">'+
      '<div class="entete"><h2>'+f.titre+'</h2>'+pastille(f)+'</div>'+
      '<p class="role">'+f.role+'</p>'+
      '<div class="etape"><span class="num">1</span>'+
        '<a class="bouton" href="'+f.url+'" target="_blank" rel="noopener">Ouvrir la page officielle</a>'+
        '<div class="repere">'+f.repere+'</div>'+
      '</div>'+
      '<div class="etape"><span class="num">2</span>'+
        '<input type="password" placeholder="Collez la cle ici" autocomplete="off">'+
      '</div>'+
      '<div class="etape"><span class="num">3</span>'+
        '<button class="primaire verifier">Verifier et enregistrer</button>'+
        (f.source==="interface" ? '<button class="oublier" style="margin-left:10px">Oublier</button>' : '')+
        indice+
      '</div>'+
      '<div class="resultat"></div>'+
    '</div>');
  const champ = c.querySelector("input");
  const bouton = c.querySelector(".verifier");
  const sortie = c.querySelector(".resultat");
  const oublier = c.querySelector(".oublier");
  if(oublier){
    oublier.addEventListener("click", async () => {
      oublier.disabled = true;
      try{
        await fetch("/cles/oublier", {method:"POST", headers:{"Content-Type":"application/json"},
          body: JSON.stringify({fournisseur: f.nom})});
        charger();
      }finally{ oublier.disabled = false; }
    });
  }
  bouton.addEventListener("click", async () => {
    const cle = champ.value.trim();
    if(!cle){ sortie.className="resultat ko"; sortie.textContent="Collez d'abord une cle."; return; }
    bouton.disabled = true; sortie.className="resultat"; sortie.textContent="Verification aupres du fournisseur...";
    try{
      const r = await fetch("/cles/tester", {method:"POST", headers:{"Content-Type":"application/json"},
        body: JSON.stringify({fournisseur: f.nom, cle: cle})});
      const d = await r.json();
      sortie.className = "resultat " + (d.valide ? "ok" : "ko");
      sortie.textContent = d.message;
      if(d.valide){ champ.value=""; setTimeout(charger, 600); }
    }catch(e){
      sortie.className="resultat ko"; sortie.textContent="Le studio local n'a pas repondu : "+e;
    }finally{ bouton.disabled = false; }
  });
  champ.addEventListener("keydown", e => { if(e.key==="Enter") bouton.click(); });
  return c;
}

async function charger(){
  const r = await fetch("/cles/etat");
  const d = await r.json();
  const b = document.getElementById("banniere");
  if(d.chat_pret){
    b.className = "banniere pret";
    b.innerHTML = 'Le chat fonctionne. <a href="http://localhost:3000/" target="_blank" rel="noopener">Ouvrir le chat</a>';
  }else{
    b.className = "banniere pasret";
    b.textContent = "Le chat ne peut pas encore repondre : aucune cle valide. Remplissez au moins la premiere carte ci-dessous.";
  }
  const zone = document.getElementById("cartes");
  zone.innerHTML = "";
  d.fournisseurs.forEach(f => zone.appendChild(carte(f)));
}
charger();
</script>
</body></html>
"""


@app.get("/cles", response_class=HTMLResponse)
async def cles_page():
    return HTMLResponse(CLES_HTML)


# --- Mise a jour --------------------------------------------------------------
# Un conteneur ne peut pas se reconstruire lui-meme, et donner a une page web les
# pleins pouvoirs sur Docker serait une mauvaise affaire pour l'utilisateur. Le
# bouton depose donc une DEMANDE dans le repertoire partage ; un veilleur qui
# tourne sous le compte de l'utilisateur (lance par start.ps1) la ramasse et fait
# le travail avec ses propres identifiants git. Sans veilleur, la page renvoie
# vers le double-clic sur mettre-a-jour.cmd : le bouton dit toujours quoi faire.

DEPOT_GIT = Path(os.getenv("DEPOT_GIT_DIR", "/depot/.git"))
MAJ_DEMANDE = CONFIG_DIR / "maj-demandee.json"
MAJ_ETAT = CONFIG_DIR / "maj-etat.json"
MAJ_VEILLEUSE = CONFIG_DIR / "maj-veilleuse.json"
VEILLEUSE_FRAICHE_S = 30


def version_locale() -> Optional[str]:
    """Le commit installe, lu directement dans .git : aucun binaire git requis."""
    try:
        tete = (DEPOT_GIT / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not tete.startswith("ref:"):
        return tete or None
    ref = tete.split(":", 1)[1].strip()
    try:
        return (DEPOT_GIT / ref).read_text(encoding="utf-8").strip() or None
    except OSError:
        pass
    # Un depot fraichement clone range ses references dans un seul fichier.
    try:
        for ligne in (DEPOT_GIT / "packed-refs").read_text(encoding="utf-8").splitlines():
            if ligne.startswith("#") or " " not in ligne:
                continue
            sha, nom = ligne.split(" ", 1)
            if nom.strip() == ref:
                return sha.strip()
    except OSError:
        pass
    return None


def depot_github() -> Optional[str]:
    """« proprietaire/depot » deduit de l'adresse d'origine, ou None."""
    try:
        config = (DEPOT_GIT / "config").read_text(encoding="utf-8")
    except OSError:
        return None
    for motif in (r"github\.com[:/]([^/\s]+/[^/\s]+?)(?:\.git)?\s*$",):
        for ligne in config.splitlines():
            ligne = ligne.strip()
            if not ligne.startswith("url"):
                continue
            trouve = re.search(motif, ligne)
            if trouve:
                return trouve.group(1)
    return None


def lire_json_windows(chemin: Path) -> Optional[dict]:
    """Lit un fichier JSON ecrit par PowerShell.

    PowerShell 5.1 met une marque d'octets en tete de ses fichiers « utf8 » :
    trois octets invisibles que json.loads refuse. Les lire en utf-8-sig les
    enleve. Mesure du 09/09 : sans cela, le veilleur tournait et la page le
    croyait absent.
    """
    try:
        return json.loads(chemin.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def veilleuse_vivante() -> bool:
    """Le veilleur a-t-il donne signe de vie recemment ?

    On regarde la DATE DU FICHIER, pas l'heure ecrite dedans : le veilleur note
    son heure locale, ce conteneur vit en heure universelle, et comparer les deux
    donnerait deux heures d'ecart -- assez pour croire vivant un veilleur mort,
    ou l'inverse. La date du fichier, elle, est la meme des deux cotes.
    """
    try:
        age = time.time() - MAJ_VEILLEUSE.stat().st_mtime
    except OSError:
        return False
    return 0 <= age < VEILLEUSE_FRAICHE_S


# La page se rafraichit toutes les cinq secondes pour suivre une mise a jour en
# cours. Sans garde-fou, cela ferait 720 appels par heure a GitHub, qui en
# autorise 60 sans jeton : au bout de cinq minutes, l'API refuserait tout et la
# page annoncerait « depot prive » sur un depot parfaitement public. La reponse
# de GitHub est donc gardee quelques minutes -- ce qui vient de .git, lui, est
# relu a chaque fois, parce que c'est ce qui bouge pendant une mise a jour.
_GITHUB_CACHE: Dict[str, Any] = {"cle": None, "quand": 0.0, "valeur": None}
GITHUB_CACHE_S = max(60, int(os.getenv("MAJ_CACHE_SECONDS", "600")))
_CHAMPS_CACHES = ("comparaison", "a_jour", "retard", "version_distante", "quota_repris_a")


def _cle_cache(slug: str, locale: str) -> str:
    # La version installee entre dans la cle : sitot la mise a jour finie, la
    # reponse gardee ne vaut plus rien puisqu'elle comparait l'ANCIENNE version.
    return slug + "@" + locale


def _github_en_cache(slug: str, locale: str) -> Optional[Dict[str, Any]]:
    if _GITHUB_CACHE["cle"] != _cle_cache(slug, locale) or not _GITHUB_CACHE["valeur"]:
        return None
    if time.time() - _GITHUB_CACHE["quand"] > GITHUB_CACHE_S:
        return None
    valeur = dict(_GITHUB_CACHE["valeur"])
    valeur["age_secondes"] = round(time.time() - _GITHUB_CACHE["quand"])
    return valeur


def _github_mettre_en_cache(slug: str, locale: str, sortie: Dict[str, Any]) -> None:
    _GITHUB_CACHE.update({
        "cle": _cle_cache(slug, locale),
        "quand": time.time(),
        "valeur": {c: sortie[c] for c in _CHAMPS_CACHES if c in sortie},
    })


@app.get("/maj/etat")
async def maj_etat():
    locale = version_locale()
    slug = depot_github()
    sortie: Dict[str, Any] = {
        "version_locale": locale,
        "version_locale_courte": locale[:7] if locale else None,
        "depot": slug,
        "veilleuse": veilleuse_vivante(),
        "comparaison": "impossible",
        "a_jour": None,
        "retard": [],
    }
    sortie["travaux"] = lire_json_windows(MAJ_ETAT)

    if locale and slug:
        frais = _github_en_cache(slug, locale)
        if frais is not None:
            sortie.update(frais)
            return sortie
        # Sans jeton, l'API GitHub ne repond que pour un depot public. Un depot
        # prive rend 404 : ce n'est pas une panne, et le dire evite de faire
        # croire a une erreur.
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                r = await client.get(
                    f"https://api.github.com/repos/{slug}/commits",
                    params={"sha": os.getenv("DEPOT_BRANCHE", "main"), "per_page": "10"},
                    headers={"Accept": "application/vnd.github+json",
                             "User-Agent": "Free-AI-Studio/1.0"},
                )
            if r.status_code == 200:
                commits = r.json()
                distants = [c.get("sha", "") for c in commits]
                sortie["comparaison"] = "faite"
                sortie["version_distante"] = distants[0] if distants else None
                if locale in distants:
                    retard = distants[: distants.index(locale)]
                    sortie["a_jour"] = not retard
                    sortie["retard"] = [
                        {"sha": c.get("sha", "")[:7],
                         "titre": (c.get("commit", {}).get("message") or "").splitlines()[0][:120]}
                        for c in commits[: len(retard)]
                    ]
                else:
                    # Le commit installe n'est pas dans les dix derniers : soit tres
                    # en retard, soit une version locale modifiee.
                    sortie["a_jour"] = False
            elif r.status_code in (403, 429) and r.headers.get("x-ratelimit-remaining") == "0":
                # Quota epuise n'est PAS « depot prive » : confondre les deux
                # ferait dire a la page que le depot est ferme alors qu'il est
                # ouvert, et le proprietaire chercherait du cote des droits.
                sortie["comparaison"] = "quota_github"
                sortie["quota_repris_a"] = r.headers.get("x-ratelimit-reset")
            elif r.status_code in (401, 403, 404):
                sortie["comparaison"] = "depot_prive"
            else:
                sortie["comparaison"] = f"http_{r.status_code}"
            _github_mettre_en_cache(slug, locale, sortie)
        except httpx.HTTPError as exc:
            log.warning("comparaison de version impossible : %s", exc)
            sortie["comparaison"] = "reseau"
    return sortie


@app.post("/maj/lancer")
async def maj_lancer():
    if not veilleuse_vivante():
        raise HTTPException(
            503,
            "Le veilleur de mise a jour n'est pas la. Fermez cette page, ouvrez le "
            "dossier free-ai-studio et double-cliquez « mettre-a-jour.cmd ». "
            "Pour que ce bouton marche la prochaine fois, demarrez le Studio avec "
            "start.ps1 : il lance le veilleur.",
        )
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    MAJ_DEMANDE.write_text(
        json.dumps({"demande_le": time.strftime("%Y-%m-%d %H:%M:%S")}, ensure_ascii=False),
        encoding="utf-8",
    )
    return {"demande": True,
            "message": "Mise a jour demandee. La reconstruction prend quelques minutes ; "
                       "les services se coupent brievement."}


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
.etat{padding:14px 16px;border-radius:12px;border:1px solid #bbb;margin:12px 0}
.etat.pret{background:#e8f6ec;border-color:#7fb98f}
.etat.pasret{background:#fdf3e3;border-color:#d9ad63}
</style></head><body>
<div class="hero">
<h1>Free AI Studio</h1>
<p>Votre studio IA local. Une clé gratuite suffit : le chat, la lecture d’images, la fabrication d’images, la recherche Web et la voix marchent alors sans rien installer d’autre. La vidéo demande en plus un compte Modal, dont le crédit mensuel offert suffit.</p>
<div class="etat" id="etat">Vérification de l’état…</div>
<p class="status">🟢 Gratuit par défaut</p>
<span class="pill">Pas de dépense automatique</span>
<span class="pill">Fallback strictement contrôlé</span>
<span class="pill">Boost volontaire et plafonné</span>
</div>
<div class="grid">
<a class="card" href="/cles"><h2>🔑 Vos clés</h2><p>Première étape : brancher un service gratuit, en trois clics et sans toucher à un fichier.</p></a>
<a class="card" href="http://localhost:3000/" target="_blank"><h2>💬 Chat</h2><p>Questions, rédaction, raisonnement, vision et conversation.</p></a>
<a class="card" href="http://localhost:3000/" target="_blank"><h2>🎨 Image</h2><p>Dans le chat, ouvrez le rouage sous la zone de saisie, mettez <b>Image</b>, puis décrivez le dessin voulu. Utilise votre clé Google, comme le chat.</p></a>
<a class="card" href="http://localhost:3000/" target="_blank"><h2>🔎 Recherche Web</h2><p>Même rouage, interrupteur <b>Recherche Web</b> : la réponse cite ses sources. Aucun compte ni clé supplémentaire.</p></a>
<a class="card" href="http://localhost:3000/" target="_blank"><h2>🎤 Voix</h2><p>🔊 sous chaque réponse pour l’écouter, 🎙️ dans la barre de saisie pour dicter. Tout se passe sur votre ordinateur, sans clé.</p></a>
<a class="card" href="http://localhost:8020/video" target="_blank"><h2>🎬 Vidéo</h2><p>Décrivez une scène, ou donnez l’image de départ, celle d’arrivée, et une image de référence pour garder le même personnage. Le calcul tourne sur une machine louée à la minute : la page affiche ce qui reste du crédit offert.</p></a>
<a class="card" href="/notebooklm"><h2>📚 Étudier</h2><p>Documents, sources, citations, quiz, cartes mentales et résumés avec NotebookLM.</p></a>
<a class="card" href="http://localhost:3000/" target="_blank"><h2>💻 Code</h2><p>Demander de l'aide pour coder ; les résultats Sandbox peuvent devenir des ressources de travail de l'agent.</p></a>
<a class="card" href="http://localhost:8020/" target="_blank"><h2>🧪 Sandbox</h2><p>Local isolé, Kaggle automatisable et Colab direct. Les sorties sont conservées comme artefacts réutilisables.</p></a>
</div>
<div class="hero" style="margin-top:18px">
<h2>🔄 Mise à jour</h2>
<div class="etat" id="maj">Vérification de la version…</div>
<button id="majBouton" style="font:inherit;padding:10px 16px;border-radius:10px;border:1px solid #222;background:#222;color:#fff;cursor:pointer">Mettre à jour</button>
<span id="majMot" class="muted"></span>
<p class="muted" style="margin-top:10px">La mise à jour récupère la dernière version puis reconstruit les
services : ils se coupent une ou deux minutes. Rien n’est envoyé nulle part, et vos clés ne sont pas touchées.</p>
</div>

<div class="hero" style="margin-top:18px">
<h2>⚡ Besoin de plus de puissance ?</h2>
<p>Le Boost reste désactivé tant que vous ne le demandez pas. Free AI Studio peut expliquer le gain attendu avant toute dépense.</p>
<a href="/boost">Voir le Boost et mes limites →</a>
<p class="muted">Les noms techniques des fournisseurs sont volontairement masqués dans cette page débutant.</p>
</div>
<script>
fetch("/cles/etat").then(r => r.json()).then(d => {
  const e = document.getElementById("etat");
  if (d.chat_pret) {
    e.className = "etat pret";
    e.textContent = "Le chat fonctionne : au moins un service gratuit répond.";
  } else {
    e.className = "etat pasret";
    e.innerHTML = 'Le chat ne peut pas encore répondre : aucune clé valide. ' +
                  '<a href="/cles">Brancher un service gratuit →</a>';
  }
}).catch(() => {
  const e = document.getElementById("etat");
  e.className = "etat pasret";
  e.textContent = "État non vérifiable : le routeur local ne répond pas.";
});

// --- Mise à jour ---
const majCase = document.getElementById("maj");
const majBouton = document.getElementById("majBouton");
const majMot = document.getElementById("majMot");
let majEnCours = false;

function majAfficher(d){
  const version = d.version_locale_courte ? ("version installée " + d.version_locale_courte) : "version inconnue";
  if(d.travaux && !d.travaux.fini){
    majEnCours = true;
    majCase.className = "etat pasret";
    majCase.textContent = "⏳ " + d.travaux.message;
    majBouton.disabled = true;
    return;
  }
  if(d.travaux && d.travaux.fini && majEnCours){
    majEnCours = false;
    majCase.className = d.travaux.ok ? "etat pret" : "etat pasret";
    majCase.textContent = (d.travaux.ok ? "✔ " : "✖ ") + d.travaux.message;
    majBouton.disabled = false;
    return;
  }
  majBouton.disabled = false;
  if(d.a_jour === true){
    majCase.className = "etat pret";
    majCase.textContent = "À jour (" + version + ").";
  } else if(d.a_jour === false){
    majCase.className = "etat pasret";
    const liste = (d.retard || []).map(c => "• " + c.titre).join("\n");
    majCase.textContent = "Une version plus récente existe (" + version + ")."
      + (liste ? "\nCe qui vous manque :\n" + liste : "");
    majCase.style.whiteSpace = "pre-line";
  } else if(d.comparaison === "quota_github"){
    majCase.className = "etat";
    const reprise = d.quota_repris_a
      ? new Date(Number(d.quota_repris_a) * 1000).toLocaleTimeString("fr-FR", {hour:"2-digit", minute:"2-digit"})
      : null;
    majCase.textContent = "GitHub ne répond plus pour l’instant : trop de questions posées "
      + "depuis cette connexion (" + version + ")."
      + (reprise ? " Réessayez après " + reprise + "." : "")
      + " Le bouton met quand même à jour.";
  } else if(d.comparaison === "depot_prive"){
    majCase.className = "etat";
    majCase.textContent = "Dépôt privé : je ne peux pas comparer avec GitHub sans identifiants ("
      + version + "). Le bouton met quand même à jour.";
  } else {
    majCase.className = "etat";
    majCase.textContent = "Comparaison impossible pour l’instant (" + version + "). Le bouton met quand même à jour.";
  }
  majMot.textContent = d.veilleuse ? "" : " — le veilleur n’est pas lancé ; le bouton dira quoi faire.";
}

function majRafraichir(){
  return fetch("/maj/etat").then(r => r.json()).then(majAfficher).catch(() => {
    majCase.className = "etat pasret";
    majCase.textContent = "Version non vérifiable : le routeur local ne répond pas.";
  });
}

majBouton.addEventListener("click", () => {
  majBouton.disabled = true;
  majCase.className = "etat";
  majCase.textContent = "Demande envoyée…";
  fetch("/maj/lancer", {method:"POST"}).then(async r => {
    const d = await r.json().catch(() => ({}));
    if(!r.ok){ throw new Error(d.detail || ("HTTP " + r.status)); }
    majEnCours = true;
    majCase.className = "etat pasret";
    majCase.textContent = "⏳ " + d.message;
  }).catch(e => {
    majBouton.disabled = false;
    majCase.className = "etat pasret";
    majCase.style.whiteSpace = "pre-line";
    majCase.textContent = e.message;
  });
});

majRafraichir();
setInterval(majRafraichir, 5000);
</script>
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


# --- Fabriquer une image -----------------------------------------------------
# Open WebUI sait demander une image a n'importe quel service << compatible
# OpenAI >>. En le pointant ici plutot que directement sur Google, la cle reste
# au seul endroit que le debutant connait : la page << Vos cles >>, relue a
# chaque appel. S'il remplace sa cle, l'image continue de marcher sans qu'il
# ait rien a recopier ailleurs -- et il n'existe pas de deuxieme exemplaire de
# la cle qui vieillit en silence dans la base d'Open WebUI.
GEMINI_IMAGE_MODEL = os.getenv("GEMINI_IMAGE_MODEL", "gemini-3.1-flash-lite-image")
IMAGE_MODEL = "free-ai-image"
# Une image par appel chez Google. Le plafond evite qu'un client bavard vide le
# quota du jour d'un seul coup.
IMAGE_MAX_N = 4


def aspect_ratio(size: Any) -> Optional[str]:
    """Traduit un << 1024x1024 >> d'Open WebUI en proportion comprise par Google."""
    try:
        largeur, hauteur = (int(x) for x in str(size).lower().split("x"))
    except (ValueError, TypeError):
        return None
    if largeur == hauteur:
        return "1:1"
    return "16:9" if largeur > hauteur else "9:16"


@app.post("/v1/images/generations")
async def images_generations(request: Request, authorization: Optional[str] = Header(default=None)):
    if not auth_ok(authorization):
        raise HTTPException(status_code=401, detail="Unauthorized")

    payload = await request.json()
    prompt = str(payload.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="Aucune description d'image n'a ete envoyee.")

    key = provider_key("gemini")
    if not key or not enabled("gemini"):
        raise HTTPException(
            status_code=503,
            detail="La fabrication d'images passe par la cle Google (Gemini). "
                   "Ajoutez-la sur la page « Vos cles », puis reessayez.",
        )

    combien = 1
    try:
        combien = max(1, min(int(payload.get("n") or 1), IMAGE_MAX_N))
    except (TypeError, ValueError):
        pass

    corps: Dict[str, Any] = {"contents": [{"parts": [{"text": prompt}]}]}
    ratio = aspect_ratio(payload.get("size"))
    if ratio:
        corps["generationConfig"] = {"imageConfig": {"aspectRatio": ratio}}

    url = ("https://generativelanguage.googleapis.com/v1beta/models/"
           f"{GEMINI_IMAGE_MODEL}:generateContent")
    headers = {
        "x-goog-api-key": key,
        "Content-Type": "application/json",
        "User-Agent": "Free-AI-Studio/1.0",
    }

    images: List[Dict[str, str]] = []
    async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=15.0)) as client:
        for _ in range(combien):
            r = await client.post(url, headers=headers, json=corps)
            if r.status_code >= 400:
                # Le corps de la reponse peut contenir le detail du refus (quota,
                # securite). Il part dans le journal, pas vers le navigateur.
                log.warning("Gemini image HTTP %s : %s", r.status_code, r.text[:300])
                raise HTTPException(
                    status_code=502,
                    detail=f"Google a refuse la demande d'image (HTTP {r.status_code}).",
                )
            data = r.json()
            for candidat in data.get("candidates", []):
                for part in candidat.get("content", {}).get("parts", []):
                    inline = part.get("inlineData") or part.get("inline_data") or {}
                    b64 = inline.get("data")
                    if not b64:
                        continue
                    mime = inline.get("mimeType") or inline.get("mime_type") or "image/png"
                    # b64_json : du base64 nu, comme le veut l'API OpenAI.
                    # url : la meme image en data-URI, qui porte en plus le vrai
                    # type MIME -- Google rend souvent du JPEG, et sans cette
                    # indication le client l'enregistrerait sous une etiquette PNG.
                    images.append({"b64_json": b64, "url": f"data:{mime};base64,{b64}"})

    if not images:
        raise HTTPException(
            status_code=502,
            detail="Google n'a renvoye aucune image : la description a probablement ete refusee.",
        )

    return JSONResponse({"created": int(time.time()), "data": images})


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
    key = provider_key(name)
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
                        # aiter_bytes() defait la compression du fournisseur ; aiter_raw()
                        # rendait les octets gzip TELS QUELS, sous une etiquette
                        # text/event-stream et sans Content-Encoding. Le client recevait
                        # donc du binaire illisible : dans Open WebUI, la reponse
                        # s'affichait vide, alors que le titre et les questions de suivi
                        # (appels non streames) arrivaient normalement.
                        async for chunk in resp.aiter_bytes():
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
