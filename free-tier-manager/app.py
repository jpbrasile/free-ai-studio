import asyncio
import hashlib
import os
import re
import time
import json
import logging
from datetime import datetime, timedelta, timezone
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
# Deuxieme choix du chat, pour les questions difficiles : Gemini haut de gamme
# d'abord, puis la meme chaine qu'Auto. Auto ne touche jamais a ce quota-la.
MAX_MODEL = "free-ai-max"
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
        # Flash-Lite : la variante prevue pour l'usage courant (Free AI Auto).
        "model": os.getenv("GEMINI_FREE_MODEL", "gemini-3.5-flash-lite"),
        "strict_zero": False,
    },
    "gemini_max": {
        # Free AI Max : le modele haut de gamme, pour les questions difficiles.
        # Meme cle et meme projet que "gemini", mais Google compte le quota
        # gratuit PAR MODELE : chacun a donc sa propre pause.
        "key_env": "GEMINI_API_KEY",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": os.getenv("GEMINI_MAX_MODEL", "gemini-3.8-flash"),
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

# Les deux modeles Gemini partagent la cle et la remise a zero (minuit, heure du
# Pacifique) ; pas le quota.
GEMINI = ("gemini", "gemini_max")
# Titre d'un service sans carte de cle a lui : la cle de Max est celle de Gemini.
TITRES = {"gemini_max": "Gemini Max (Google)"}

provider_cooldown_until: Dict[str, float] = {p: 0.0 for p in PROVIDERS}
openrouter_credit_cache: Dict[str, Any] = {"checked_at": 0.0, "data": None, "error": None}

stats: Dict[str, Dict[str, Any]] = {
    p: {"attempts": 0, "successes": 0, "failures": 0, "last_status": None, "last_error": None}
    for p in PROVIDERS
}

# --- Quotas gratuits ----------------------------------------------------------
# Un quota epuise ne doit pas se voir seulement a une reponse differente : la
# personne doit savoir qu'elle a change de service, pourquoi, et quand le premier
# revient. Ce qui suit garde de quoi le dire.
#
# Limites publiees, relevees le 11/09/2026 sur les pages officielles. Google ne
# publie plus de chiffres : ils ne se lisent que dans AI Studio, pour le projet de
# la personne. La seule limite de Gemini que le Studio connaisse est donc celle
# que Google ecrit dans son refus (voir lire_quota).
LIMITES_RELEVEES_LE = "2026-09-11"
LIMITES_PUBLIEES: Dict[str, Dict[str, Any]] = {
    "gemini": {
        "par_jour": None,
        "texte": "non publiée ; visible dans AI Studio, comptée par projet et par modèle, "
                 "remise à zéro à minuit heure du Pacifique",
        "source": "https://ai.google.dev/gemini-api/docs/rate-limits",
    },
    "openrouter": {
        "par_jour": 50,
        "texte": "50 demandes par jour (1 000 après au moins 10 $ de crédits achetés), 20 par minute",
        "source": "https://openrouter.ai/docs/api-reference/limits",
    },
    "groq": {
        "par_jour": 1000,
        "texte": "1 000 demandes par jour et 30 par minute pour openai/gpt-oss-20b",
        "source": "https://console.groq.com/docs/rate-limits",
    },
}

LIMITES_PUBLIEES["gemini_max"] = LIMITES_PUBLIEES["gemini"]

quota_state: Dict[str, Dict[str, Any]] = {p: {} for p in PROVIDERS}
# Derniere limite ecrite par le fournisseur dans un refus du jour : gardee apres
# la fin de la pause, pour estimer ce qui reste le lendemain.
limites_annoncees: Dict[str, Dict[str, Any]] = {}
# Reponses servies depuis minuit, heure du Pacifique. En memoire : un redemarrage
# du routeur remet ce compte a zero, et la page le dit.
servies_du_jour: Dict[str, Dict[str, Any]] = {}
DEMARRE_A = time.time()
# Par service attendu (le premier d'un choix du chat) : vrai quand il vient
# d'etre mis en pause et que personne ne l'a encore dit dans le chat.
avis_bascule: Dict[str, bool] = {}
dernier_service: Dict[str, Any] = {}



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


def chaine_de(modele: str) -> List[str]:
    """Ordre d'essai pour le choix fait dans le chat."""
    auto = [n for n in provider_order() if n != "gemini_max"]
    if modele == MAX_MODEL:
        return ["gemini_max"] + auto
    return auto


def ordre_affiche() -> List[str]:
    """Tous les services, dans l'ordre ou les pages les montrent."""
    ordre = [n for n in provider_order() if n != "gemini_max"]
    ordre.insert(ordre.index("gemini") + 1 if "gemini" in ordre else 0, "gemini_max")
    return ordre


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
    if name == "gemini_max":
        # Couper Gemini coupe ses deux modeles. La cle de Max est celle de
        # Gemini : la coller dans /cles active Gemini, pas Max, que
        # ENABLE_GEMINI_MAX=false retire dans tous les cas.
        return enabled("gemini") and os.getenv("ENABLE_GEMINI_MAX", "true").lower() == "true"
    env_name = f"ENABLE_{name.upper()}"
    # Gemini Free Tier is the normal first choice; OpenRouter Free is the
    # strict-zero fallback. Groq remains an optional third fallback.
    default = "true" if name in ("gemini", "gemini_max", "openrouter") else "false"
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


def fuseau_pacifique():
    """Le quota du jour de Gemini repart a minuit, heure du Pacifique.

    L'image Docker porte la base des fuseaux horaires ; un Python sous Windows
    sans le paquet tzdata ne l'a pas. On retombe alors sur UTC-8, l'heure
    d'hiver : l'ete, la reprise annoncee a une heure de retard, jamais d'avance."""
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("America/Los_Angeles")
    except Exception:
        return timezone(timedelta(hours=-8))


def minuit_pacifique(maintenant: float) -> float:
    fuseau = fuseau_pacifique()
    demain = (datetime.fromtimestamp(maintenant, fuseau) + timedelta(days=1)).date()
    return datetime(demain.year, demain.month, demain.day, tzinfo=fuseau).timestamp()


def debut_du_jour_pacifique(maintenant: float) -> float:
    local = datetime.fromtimestamp(maintenant, fuseau_pacifique())
    return local.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def jour_pacifique(maintenant: float) -> str:
    return datetime.fromtimestamp(maintenant, fuseau_pacifique()).strftime("%Y-%m-%d")


_JOUR = re.compile(r"per.?day|daily", re.I)
_LIMITE = re.compile(r"limit:\s*(\d+)", re.I)
_ATTENTE = re.compile(r"retry in\s*([\d.]+)\s*s", re.I)
_MODELE = re.compile(r"model:\s*([\w.\-]+)", re.I)


def _nombre(texte: Any) -> Optional[float]:
    try:
        return float(str(texte).strip().rstrip("s"))
    except (TypeError, ValueError):
        return None


def lire_quota(corps: Any) -> Dict[str, Any]:
    """Lit un refus 429 : quota du jour ou de la minute, limite, attente, modele.

    Deux formes existent. La page officielle des erreurs de Gemini ne documente
    que {"error": {"code": "quota_exceeded" | "rate_limit_exceeded", "message"}}.
    Les refus reels portent en plus des details google.rpc (QuotaFailure avec
    quotaId et quotaValue, RetryInfo avec retryDelay), et arrivent parfois dans
    une LISTE. On cherche donc partout, sans supposer la forme. Ne leve jamais :
    un refus illisible rend un dictionnaire vide, et le routeur garde alors sa
    pause courte d'avant."""
    violations: List[Dict[str, Any]] = []
    delais: List[str] = []
    modeles: List[str] = []
    codes: List[str] = []
    messages: List[str] = []

    def parcourir(noeud: Any, profondeur: int = 0) -> None:
        if profondeur > 12:
            return
        if isinstance(noeud, list):
            for element in noeud:
                parcourir(element, profondeur + 1)
            return
        if not isinstance(noeud, dict):
            return
        if isinstance(noeud.get("quotaId"), str):
            violations.append(noeud)
        for cle, valeur in noeud.items():
            if isinstance(valeur, str):
                if cle == "retryDelay":
                    delais.append(valeur)
                elif cle == "model":
                    modeles.append(valeur)
                elif cle in ("code", "status"):
                    codes.append(valeur.lower())
                elif cle == "message":
                    messages.append(valeur)
            else:
                parcourir(valeur, profondeur + 1)

    parcourir(corps)
    if not (violations or delais or codes or messages):
        return {}
    texte = " ".join(messages)
    du_jour = [v for v in violations if "perday" in str(v.get("quotaId")).lower()]
    par_jour = bool(du_jour) or "quota_exceeded" in codes or bool(_JOUR.search(texte))

    limite = None
    for violation in (du_jour if par_jour and du_jour else violations):
        valeur = _nombre(violation.get("quotaValue"))
        if valeur is not None:
            limite = int(valeur)
            break
    if limite is None:
        trouve = _LIMITE.search(texte)
        if trouve:
            limite = int(trouve.group(1))

    attente = next((a for a in (_nombre(d) for d in delais) if a is not None), None)
    if attente is None:
        trouve = _ATTENTE.search(texte)
        if trouve:
            attente = _nombre(trouve.group(1))

    modele = modeles[0] if modeles else None
    if modele is None:
        trouve = _MODELE.search(texte)
        modele = trouve.group(1) if trouve else None

    sortie: Dict[str, Any] = {"par_jour": par_jour}
    if limite is not None:
        sortie["limite"] = limite
    if attente is not None:
        sortie["attente_s"] = attente
    if modele:
        sortie["modele"] = modele
    return sortie


def pause_indisponible(name: str, attente: Optional[float] = None) -> None:
    """Service qui ne repond pas (5xx, coupure reseau) : pause courte, puis
    nouvel essai. Sans elle, chaque message repaierait l'aller-retour rate."""
    maintenant = time.time()
    jusqu_a = maintenant + max(5.0, min(attente or 30.0, 60.0))
    provider_cooldown_until[name] = jusqu_a
    quota_state[name] = {"cause": "indisponible", "depuis": maintenant, "jusqu_a": jusqu_a, "limite": None}


def apply_rate_limit_cooldown(name: str, response: httpx.Response, corps: Any = None) -> bool:
    """Met le service en pause si le refus le demande ; rend vrai s'il l'a ete."""
    if response.status_code >= 500:
        # Google renvoie regulierement 503 << The model is overloaded >>.
        pause_indisponible(name, _nombre(response.headers.get("retry-after")))
        return True
    if response.status_code != 429:
        return False
    maintenant = time.time()
    quota = lire_quota(corps)
    if quota.get("par_jour") and name in GEMINI:
        # Reessayer toutes les 30 s jusqu'a minuit ne ferait que rallonger chaque
        # reponse d'un refus : la pause court jusqu'a la remise a zero documentee.
        jusqu_a = minuit_pacifique(maintenant)
    else:
        # Ailleurs, l'heure de remise a zero n'est pas documentee : on garde une
        # pause courte et on reessaie.
        attente = quota.get("attente_s")
        if attente is None:
            attente = _nombre(response.headers.get("retry-after")) or 30.0
        jusqu_a = maintenant + max(5.0, min(attente, 300.0))
    provider_cooldown_until[name] = jusqu_a
    quota_state[name] = {
        "cause": "quota_du_jour" if quota.get("par_jour") else "limite_par_minute",
        "depuis": maintenant,
        "jusqu_a": jusqu_a,
        "limite": quota.get("limite"),
    }
    if quota.get("par_jour") and quota.get("limite"):
        limites_annoncees[name] = {
            "limite": quota["limite"],
            "modele": quota.get("modele") or PROVIDERS[name]["model"],
            "le": maintenant,
        }
    return True


def titre_de(name: str) -> str:
    return TITRES.get(name) or PROVIDER_HELP.get(name, {}).get("titre", name)


def duree_lisible(secondes: float) -> str:
    s = max(0, int(round(secondes)))
    if s < 90:
        return "%d s" % s
    if s < 90 * 60:
        return "%d min" % round(s / 60)
    return "%d h" % round(s / 3600)


def noter_service(name: str, prefere: Optional[str]) -> bool:
    """Compte la reponse servie ; rend vrai si elle vient d'un secours."""
    maintenant = time.time()
    jour = jour_pacifique(maintenant)
    compte = servies_du_jour.get(name)
    if not compte or compte.get("jour") != jour:
        compte = servies_du_jour[name] = {"jour": jour, "n": 0}
    compte["n"] += 1
    if name == prefere:
        quota_state[name] = {}
        avis_bascule[name] = False
    bascule = prefere is not None and name != prefere
    dernier_service.update({
        "fournisseur": name,
        "titre": titre_de(name),
        "modele": PROVIDERS[name]["model"],
        "a": maintenant,
        "bascule": bascule,
    })
    return bascule


def texte_avis(prefere: str, servi: str) -> str:
    q = quota_state.get(prefere) or {}
    reste = duree_lisible(provider_cooldown_until.get(prefere, 0.0) - time.time())
    # Le modele est nomme : entre les deux Gemini, le titre seul ne dit pas lequel repond.
    par = "%s (%s)" % (titre_de(servi), PROVIDERS[servi]["model"])
    if q.get("cause") == "quota_du_jour":
        limite = " (%d demandes)" % q["limite"] if q.get("limite") else ""
        quand = ("Retour prévu dans environ %s, à minuit heure du Pacifique." % reste
                 if prefere in GEMINI else "Nouvel essai dans %s." % reste)
        return "_ℹ️ %s a atteint sa limite gratuite du jour%s : cette réponse est fournie par %s. %s_\n\n" % (
            titre_de(prefere), limite, par, quand)
    if q.get("cause") == "indisponible":
        return "_ℹ️ %s ne répond pas pour l’instant : cette réponse est fournie par %s. Nouvel essai dans %s._\n\n" % (
            titre_de(prefere), par, reste)
    return "_ℹ️ %s est saturé pour l’instant : cette réponse est fournie par %s. Nouvel essai dans %s._\n\n" % (
        titre_de(prefere), par, reste)


def morceau_avis(texte: str, modele: str = AUTO_MODEL) -> bytes:
    """Un morceau SSE au format OpenAI, place en tete du flux du secours."""
    morceau = {
        "id": "free-ai-avis",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": modele,
        "choices": [{"index": 0, "delta": {"role": "assistant", "content": texte}, "finish_reason": None}],
    }
    return ("data: " + json.dumps(morceau, ensure_ascii=False) + "\n\n").encode("utf-8")


def etat_quotas() -> Dict[str, Any]:
    """Ce que /studio et /diagnostic affichent. Aucune cle, aucun secret."""
    maintenant = time.time()
    jour = jour_pacifique(maintenant)
    fiches = []
    for name in ordre_affiche():
        q = quota_state.get(name) or {}
        jusqu_a = provider_cooldown_until.get(name, 0.0)
        en_pause = maintenant < jusqu_a
        du_jour = en_pause and q.get("cause") == "quota_du_jour"
        compte = servies_du_jour.get(name) or {}
        servies = compte.get("n", 0) if compte.get("jour") == jour else 0
        annonce = limites_annoncees.get(name) or {}
        limite = annonce.get("limite") if annonce.get("modele") == PROVIDERS[name]["model"] else None
        if du_jour:
            reste: Optional[int] = 0
        elif limite is not None:
            reste = max(0, limite - servies)
        else:
            reste = None
        s = stats[name]
        fiches.append({
            "nom": name,
            "titre": titre_de(name),
            "modele": PROVIDERS[name]["model"],
            "eligible": provider_allowed(name),
            "en_pause": en_pause,
            "reprise_a": jusqu_a if en_pause else None,
            # Faux quand on sait seulement quand on REESSAIERA, pas quand le
            # quota repart (fournisseur sans heure de remise a zero documentee).
            "reprise_connue": en_pause and (not du_jour or name in GEMINI),
            "quota_du_jour_atteint": du_jour,
            "indisponible": en_pause and q.get("cause") == "indisponible",
            "limite_annoncee": limite,
            "servies_aujourdhui": servies,
            "reste_estime": reste,
            "limite_publiee": LIMITES_PUBLIEES.get(name, {}),
            "demandes": {"essais": s["attempts"], "reussites": s["successes"], "echecs": s["failures"]},
        })
    par_nom = {f["nom"]: f for f in fiches}

    def secours(modele: str) -> bool:
        # Secours : le premier service de CE choix est en pause, un suivant repond.
        el = [par_nom[n] for n in chaine_de(modele) if n in par_nom and par_nom[n]["eligible"]]
        return bool(el) and el[0]["en_pause"] and any(not f["en_pause"] for f in el[1:])

    return {
        "maintenant": maintenant,
        "fournisseurs": fiches,
        "secours_en_cours": secours(AUTO_MODEL),
        "secours_max_en_cours": secours(MAX_MODEL),
        "dernier_service": dict(dernier_service) or None,
        "compte_depuis": max(DEMARRE_A, debut_du_jour_pacifique(maintenant)),
        "limites_relevees_le": LIMITES_RELEVEES_LE,
    }

def auth_ok(auth: Optional[str]) -> bool:
    # Refuse protected endpoints when no local key exists instead of falling
    # back to an implicit shared default. /health remains intentionally public.
    return bool(INTERNAL_KEY) and auth == f"Bearer {INTERNAL_KEY}"


async def safe_status() -> Dict[str, Any]:
    providers = []
    for name in ordre_affiche():
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
        "public_models": [AUTO_MODEL, MAX_MODEL],
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


ARENA_FAIT = CONFIG_DIR / "open-webui-arena.json"


async def masquer_arena(client: httpx.AsyncClient, entetes: Dict[str, str]) -> None:
    """Retire << Arena Model >> du choix du chat, une seule fois.

    Open WebUI l'ajoute d'office (ENABLE_EVALUATION_ARENA_MODELS vaut true par
    defaut). Son temoin est a part de celui des reglages de confort : une
    installation qui a deja ce temoin recoit quand meme ce reglage, une fois.
    Ensuite, si l'utilisateur le remet dans Admin > Evaluations, il reste."""
    if ARENA_FAIT.exists():
        return
    url = f"{WEBUI_URL}/api/v1/evaluations/config"
    try:
        r = await client.get(url, headers=entetes)
        r.raise_for_status()
        if r.json().get("ENABLE_EVALUATION_ARENA_MODELS"):
            r = await client.post(url, headers=entetes, json={"ENABLE_EVALUATION_ARENA_MODELS": False})
            r.raise_for_status()
            etat = "Arena Model retire du chat"
        else:
            etat = "Arena Model deja absent"
    except (httpx.HTTPError, ValueError) as exc:
        # Pas de temoin : nouvel essai au prochain demarrage.
        log.warning("Arena Model non retire : %s", exc)
        return
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        ARENA_FAIT.write_text(json.dumps({
            "pose_le": time.strftime("%Y-%m-%d %H:%M:%S"),
            "etat": etat,
            "note": "Tant que ce fichier existe, Free AI Studio ne touche plus a Arena. "
                    "Pour le remettre : Open WebUI, Admin, Settings, Evaluations.",
        }, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        log.warning("Temoin Arena non ecrit (%s) : %s", ARENA_FAIT, exc)
    log.info("%s", etat)


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
        # Avant le temoin, lui aussi : il a son propre temoin (voir masquer_arena).
        await masquer_arena(client, entetes)

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
    # Le motif du fournisseur est en anglais : il suit la phrase francaise, annonce.
    motif = (" Reponse du fournisseur, en anglais : " + detail) if detail.strip() else ""
    # Google refuse une cle inconnue par un 400 << API key not valid >>, pas un 401.
    cle_inconnue = response.status_code == 400 and "api key" in detail.lower().replace("_", " ")
    if response.status_code in (401, 403) or cle_inconnue:
        return {
            "valide": False,
            "message": "Cle refusee. Verifiez que vous l'avez copiee en entier, sans espace au debut ni a la fin." + motif,
        }
    return {
        "valide": False,
        "message": "Le fournisseur a refuse l'essai (HTTP %d)." % response.status_code + motif,
    }


@app.get("/quotas/etat")
async def quotas_etat():
    return etat_quotas()


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


# --- Diagnostic ---------------------------------------------------------------
# Sur un ordinateur sans terminal, une panne se raconte de memoire : << il n'y a
# pas de modele dans le chat >>. On ne peut rien en tirer, et on repart pour un
# tour de suppositions. Cette page fait les mesures a la place de la personne,
# les ecrit en phrases, et les met dans le presse-papier d'un clic.
#
# Aucune cle n'y figure. D'une cle on ne montre que sa longueur et une empreinte
# tronquee : cela suffit a dire si les deux cotes portent la MEME sans jamais
# reveler laquelle.

def empreinte(valeur: str) -> str:
    if not valeur:
        return "absente"
    return "%d signes, empreinte %s" % (
        len(valeur), hashlib.sha256(valeur.encode()).hexdigest()[:12])


async def etat_liaison() -> Dict[str, Any]:
    """La chaine chat -> routeur, maillon par maillon."""
    sortie: Dict[str, Any] = {
        "cle_du_routeur": empreinte(INTERNAL_KEY),
        "chat_joignable": False,
        "session_admin": False,
        "api_activee": None,
        "url_configuree": None,
        "cle_du_chat": None,
        "memes_cles": None,
        "modeles": None,
        "detail": None,
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=5.0)) as client:
        try:
            r = await client.get(f"{WEBUI_URL}/health")
            sortie["chat_joignable"] = r.status_code == 200
        except httpx.HTTPError as exc:
            sortie["detail"] = "Le chat ne repond pas : %s" % exc
            return sortie
        if not sortie["chat_joignable"]:
            sortie["detail"] = "Le chat repond, mais pas normalement."
            return sortie

        jeton = await webui_jeton(client)
        if not jeton:
            sortie["detail"] = ("Le chat demande un compte (WEBUI_AUTH=true) : le Studio ne "
                                "peut pas verifier la liaison a votre place.")
            return sortie
        sortie["session_admin"] = True
        entetes = {"Authorization": f"Bearer {jeton}"}

        interne = os.getenv("FREE_TIER_MANAGER_INTERNAL_URL",
                            "http://free-tier-manager:8000/v1")
        try:
            r = await client.get(f"{WEBUI_URL}/openai/config", headers=entetes)
            cfg = r.json()
            urls = list(cfg.get("OPENAI_API_BASE_URLS") or [])
            cles = list(cfg.get("OPENAI_API_KEYS") or [])
            sortie["api_activee"] = bool(cfg.get("ENABLE_OPENAI_API"))
            sortie["url_configuree"] = ", ".join(urls) if urls else None
            gardee = ""
            if interne in urls:
                rang = urls.index(interne)
                if rang < len(cles):
                    gardee = cles[rang]
            sortie["cle_du_chat"] = empreinte(gardee)
            sortie["memes_cles"] = bool(gardee) and gardee == INTERNAL_KEY
        except (httpx.HTTPError, ValueError) as exc:
            sortie["detail"] = "Reglages du chat illisibles : %s" % exc
            return sortie

        try:
            r = await client.get(f"{WEBUI_URL}/api/models", headers=entetes)
            sortie["modeles"] = [m.get("id") for m in (r.json().get("data") or [])]
        except (httpx.HTTPError, ValueError) as exc:
            sortie["detail"] = "Liste des modeles illisible : %s" % exc
    return sortie


@app.get("/diagnostic/etat")
async def diagnostic_etat():
    return {
        "version": version_locale(),
        # gemini_max porte la cle de gemini : la compter serait compter une cle deux fois.
        "fournisseurs_branches": [n for n in PROVIDERS if n != "gemini_max" and configured(n)],
        "quotas": etat_quotas(),
        "liaison": await etat_liaison(),
    }


@app.post("/diagnostic/reparer")
async def diagnostic_reparer():
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
        jeton = await webui_jeton(client)
        if not jeton:
            raise HTTPException(
                409, "Le chat demande un compte : reparation impossible depuis cette page.")
        await reparer_connexion_webui(client, {"Authorization": f"Bearer {jeton}"})
    return {"fait": True, "liaison": await etat_liaison()}


DIAGNOSTIC_HTML = """
<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Diagnostic - Free AI Studio</title>
<style>
:root{font-family:system-ui,sans-serif} body{max-width:820px;margin:32px auto;padding:0 18px;line-height:1.5}
.bloc{border:1px solid #bbb;border-radius:16px;padding:18px;margin-bottom:16px}
.ligne{display:flex;gap:10px;align-items:flex-start;padding:7px 0;border-bottom:1px solid #eee}
.ligne:last-child{border-bottom:0}
.quoi{flex:1}.det{opacity:.7;font-size:.92em}
button{font:inherit;padding:10px 16px;border-radius:10px;border:1px solid #222;background:#222;color:#fff;cursor:pointer}
button.pale{background:#fff;color:#222}
textarea{width:100%;height:190px;font-family:ui-monospace,Consolas,monospace;font-size:.86em;
 border:1px solid #bbb;border-radius:10px;padding:10px}
.verdict{padding:12px 14px;border-radius:12px;border:1px solid #bbb;margin:10px 0}
.bon{background:#e8f6ec;border-color:#7fb98f}.mauvais{background:#fdecec;border-color:#d98d8d}
</style></head><body>
<h1>Diagnostic</h1>
<p>Cette page mesure la chaine qui va du chat jusqu'aux services gratuits, et dit
ou elle casse. Aucune cle n'est affichee : d'une cle on ne montre que sa longueur
et une empreinte, de quoi verifier que deux endroits portent la meme.</p>

<div class="bloc">
  <div id="verdict" class="verdict">Mesure en cours...</div>
  <div id="lignes"></div>
</div>

<div class="bloc">
  <button id="reparer">Reparer la liaison</button>
  <button id="relancer" class="pale">Refaire la mesure</button>
  <span id="mot" class="det"></span>
</div>

<div class="bloc">
  <h2>A montrer si vous demandez de l'aide</h2>
  <button id="copier" class="pale">Copier ce diagnostic</button>
  <p class="det">Ce texte ne contient aucune cle.</p>
  <textarea id="texte" readonly></textarea>
</div>
<p><a href="/studio">&larr; Retour au Studio</a></p>

<script>
function ligne(ok, quoi, detail) {
  var d = document.createElement("div");
  d.className = "ligne";
  var marque = ok === null ? "\\u2753" : (ok ? "\\u2705" : "\\u274C");
  d.innerHTML = "<div>" + marque + "</div><div class='quoi'>" + quoi
              + "<div class='det'>" + (detail || "") + "</div></div>";
  return d;
}

function rendre(d) {
  var L = d.liaison, zone = document.getElementById("lignes");
  zone.innerHTML = "";
  var modeles = L.modeles || [];
  zone.appendChild(ligne(true, "Routeur en marche",
    "version " + (d.version || "inconnue") + ", mot de passe interne : " + L.cle_du_routeur));
  zone.appendChild(ligne(L.chat_joignable, "Le chat repond",
    L.chat_joignable ? "" : "le conteneur du chat ne repond pas"));
  zone.appendChild(ligne(L.session_admin, "Le Studio peut regler le chat",
    L.session_admin ? "" : (L.detail || "")));
  zone.appendChild(ligne(L.api_activee, "Connexion au routeur activee dans le chat",
    L.url_configuree || "aucune adresse enregistree"));
  zone.appendChild(ligne(L.memes_cles, "Les deux cotes portent le meme mot de passe",
    "cote chat : " + (L.cle_du_chat || "inconnue")));
  zone.appendChild(ligne(modeles.length > 0, "Un modele est proposable dans le chat",
    modeles.length ? modeles.join(", ") : "la liste est vide"));
  zone.appendChild(ligne(d.fournisseurs_branches.length > 0, "Au moins un service gratuit est branche",
    d.fournisseurs_branches.length ? d.fournisseurs_branches.join(", ") : "aucune cle enregistree"));

  // Quotas : quel service repond, lequel est en pause, jusqu'a quand.
  var actifs = ((d.quotas && d.quotas.fournisseurs) || []).filter(function (f) { return f.eligible; });
  actifs.forEach(function (f) {
    var officielle = "limite officielle : " + ((f.limite_publiee || {}).texte || "inconnue");
    var quoi = f.titre + " (" + f.modele + ") disponible";
    var det = officielle;
    if (f.en_pause) {
      quoi = f.titre + " (" + f.modele + ") : "
           + (f.quota_du_jour_atteint ? "limite gratuite du jour atteinte"
              : f.indisponible ? "ne repond pas pour l'instant" : "sature pour l'instant");
      det = (f.limite_annoncee ? "limite annoncee dans le refus : " + f.limite_annoncee + " demandes ; " : "")
          + (f.reprise_connue ? "reprise vers " : "nouvel essai vers ")
          + new Date(f.reprise_a * 1000).toLocaleTimeString("fr-FR") + " ; " + officielle;
    } else if (f.reste_estime !== null && f.reste_estime !== undefined) {
      det = "environ " + f.reste_estime + " demande(s) restante(s) aujourd'hui (estimation) ; " + officielle;
    }
    zone.appendChild(ligne(!f.en_pause, quoi, det));
  });
  var tousEnPause = actifs.length > 0 && actifs.every(function (f) { return f.en_pause; });

  var v = document.getElementById("verdict");
  if (modeles.length && d.fournisseurs_branches.length && tousEnPause) {
    v.className = "verdict mauvais";
    v.textContent = "Tous les services gratuits branches ont atteint leur limite. Le chat reprendra "
                  + "de lui-meme, aux heures indiquees ci-dessous. Rien n'est paye.";
  } else if (modeles.length && d.fournisseurs_branches.length) {
    v.className = "verdict bon";
    v.textContent = "Tout est en place. Le chat doit proposer un modele."
      + (d.quotas && d.quotas.secours_en_cours
         ? " Il repond en ce moment par un service de secours : le premier a atteint sa limite." : "");
  } else if (!modeles.length && L.session_admin && L.memes_cles === false) {
    v.className = "verdict mauvais";
    v.textContent = "Le chat garde un ancien mot de passe interne. Cliquez Reparer la liaison.";
  } else if (!modeles.length) {
    v.className = "verdict mauvais";
    v.textContent = "Le chat ne propose aucun modele. Le detail ci-dessous dit a quel maillon ca casse.";
  } else {
    v.className = "verdict mauvais";
    v.textContent = "Le chat a un modele, mais aucun service gratuit n'est branche : allez a la page Cles.";
  }
  document.getElementById("texte").value = JSON.stringify(d, null, 2);
}

function mesurer() {
  document.getElementById("mot").textContent = "";
  fetch("/diagnostic/etat").then(function (r) { return r.json(); }).then(rendre)
    .catch(function (e) {
      document.getElementById("verdict").className = "verdict mauvais";
      document.getElementById("verdict").textContent = "Le routeur ne repond pas : " + e;
    });
}

document.getElementById("relancer").onclick = mesurer;
document.getElementById("reparer").onclick = function () {
  document.getElementById("mot").textContent = "Reparation en cours...";
  fetch("/diagnostic/reparer", { method: "POST" }).then(function (r) { return r.json(); })
    .then(function (d) {
      document.getElementById("mot").textContent = "Repare. Rechargez l'onglet du chat.";
      if (d.liaison) { rendre({ version: null, fournisseurs_branches: [], liaison: d.liaison }); }
      mesurer();
    })
    .catch(function (e) { document.getElementById("mot").textContent = "Echec : " + e; });
};
document.getElementById("copier").onclick = function () {
  var t = document.getElementById("texte");
  t.select();
  try { navigator.clipboard.writeText(t.value); } catch (e) { document.execCommand("copy"); }
  document.getElementById("copier").textContent = "Copie";
};
mesurer();
</script>
</body></html>
"""


@app.get("/diagnostic", response_class=HTMLResponse)
async def diagnostic_page():
    return HTMLResponse(DIAGNOSTIC_HTML)


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
.exp{font-size:.7rem;font-weight:600;border:1px solid #c9a227;background:#fff8e1;border-radius:999px;
 padding:2px 8px;vertical-align:middle;margin-left:4px}
ul.quotas{margin:6px 0 8px;padding-left:20px} ul.quotas li{margin:5px 0}
</style></head><body>
<div class="hero">
<h1>Free AI Studio</h1>
<p>Votre studio IA local. Une clé gratuite suffit : le chat, la lecture d’images, la fabrication d’images, la recherche Web et la voix marchent alors sans rien installer d’autre. La vidéo demande en plus un compte Modal : carte bancaire exigée, 30 $ de calcul offerts par mois, et facturation au-delà tant que vous n’avez pas réglé de limite de dépense chez Modal.</p>
<div class="etat" id="etat">Vérification de l’état…</div>
<p class="status">🟢 Gratuit par défaut</p>
<span class="pill">Pas de dépense automatique</span>
<span class="pill">Fallback strictement contrôlé</span>
<span class="pill">Boost volontaire et plafonné</span>
</div>
<div class="etat" id="quotas" hidden></div>
<div class="grid">
<a class="card" href="/cles"><h2>🔑 Vos clés</h2><p>Première étape : brancher un service gratuit, en trois clics et sans toucher à un fichier.</p></a>
<a class="card" href="http://localhost:3000/" target="_blank"><h2>💬 Chat</h2><p>Questions, rédaction, raisonnement, vision et conversation. Deux choix en haut du chat : <b>Free AI Auto</b> pour le courant, <b>Free AI Max</b> pour les questions difficiles (modèle plus fort, avec son propre quota).</p></a>
<a class="card" href="http://localhost:3000/" target="_blank"><h2>🎨 Image</h2><p>Dans le chat, ouvrez le rouage sous la zone de saisie, mettez <b>Image</b>, puis décrivez le dessin voulu. Utilise votre clé Google, comme le chat.</p></a>
<a class="card" href="http://localhost:3000/" target="_blank"><h2>🔎 Recherche Web</h2><p>Même rouage, interrupteur <b>Recherche Web</b> : la réponse cite ses sources. Aucun compte ni clé supplémentaire.</p></a>
<a class="card" href="http://localhost:3000/" target="_blank"><h2>🎤 Voix <span class="exp">expérimental</span></h2><p>🔊 sous chaque réponse pour l’écouter, 🎙️ dans la barre de saisie pour dicter. Tout se passe sur votre ordinateur, sans clé.</p></a>
<a class="card" href="http://localhost:8020/video" target="_blank"><h2>🎬 Vidéo <span class="exp">expérimental</span></h2><p>Décrivez une scène, ou donnez l’image de départ, celle d’arrivée, et une image de référence pour garder le même personnage. Le calcul tourne sur une machine Modal louée à la minute (Modal exige une carte bancaire). La page affiche la dépense estimée par le Studio, pas votre facture Modal.</p></a>
<a class="card" href="/notebooklm"><h2>📚 Étudier <span class="exp">expérimental</span></h2><p>Documents, sources, citations, quiz, cartes mentales et résumés avec NotebookLM.</p></a>
<a class="card" href="http://localhost:3000/" target="_blank"><h2>💻 Code <span class="exp">expérimental</span></h2><p>Demander de l'aide pour coder ; les résultats Sandbox peuvent devenir des ressources de travail de l'agent.</p></a>
<a class="card" href="http://localhost:8020/" target="_blank"><h2>🧪 Sandbox <span class="exp">expérimental</span></h2><p>Local isolé, Kaggle automatisable et Colab direct. Les sorties sont conservées comme artefacts réutilisables.</p></a>
</div>
<p class="muted">Chat, Image et Recherche Web sont les fonctions stabilisées. Les cartes marquées « expérimental » peuvent changer ou casser d’une version à l’autre.</p>
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
<p style="margin-top:14px">Quelque chose ne marche pas ? <a href="/diagnostic"><b>🩺 Diagnostic</b></a> —
la page mesure la chaîne et dit où elle casse, sans terminal.</p>
<p class="muted">Le nom d’un service n’apparaît ici que pour dire lequel répond, et jusqu’à quand.</p>
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

// --- Quotas gratuits ---
function dureeLisible(s){
  s = Math.max(0, Math.round(s));
  if(s < 90) return s + " s";
  if(s < 5400) return Math.round(s / 60) + " min";
  return Math.round(s / 3600) + " h";
}
function heureLocale(t){
  return new Date(t * 1000).toLocaleTimeString("fr-FR", {hour:"2-digit", minute:"2-digit"});
}
function quotasAfficher(q){
  const z = document.getElementById("quotas");
  const actifs = q.fournisseurs.filter(f => f.eligible);
  if(!actifs.length){ z.hidden = true; return; }
  const lignes = actifs.map(f => {
    let t = "<b>" + f.titre + "</b> <span class='muted'>(" + f.modele + ")</span> : ";
    if(f.en_pause){
      t += f.quota_du_jour_atteint
        ? "limite gratuite du jour atteinte" + (f.limite_annoncee ? " (" + f.limite_annoncee + " demandes)" : "")
        : f.indisponible ? "ne répond pas pour l’instant" : "saturé pour l’instant";
      t += (f.reprise_connue ? ", reprise vers " : ", nouvel essai vers ") + heureLocale(f.reprise_a)
        + " (dans " + dureeLisible(f.reprise_a - q.maintenant) + ")";
    } else if(f.reste_estime !== null && f.reste_estime !== undefined){
      t += "disponible, environ " + f.reste_estime + " demande(s) restante(s) aujourd’hui (estimation)";
    } else {
      t += "disponible, " + f.servies_aujourdhui + " réponse(s) servie(s) aujourd’hui";
    }
    return "<li>" + t + ".<br><span class='muted'>Limite officielle : "
      + ((f.limite_publiee || {}).texte || "inconnue") + ".</span></li>";
  });
  z.className = q.secours_en_cours ? "etat pasret" : "etat";
  z.innerHTML = (q.secours_en_cours
      ? "<b>Le chat répond en ce moment avec un service de secours</b> : le premier a atteint sa limite. Rien n’est payé pour autant."
      : "<b>Services gratuits</b>")
    + "<ul class='quotas'>" + lignes.join("") + "</ul>"
    + "<span class='muted'>Limites relevées le " + q.limites_relevees_le + ". Réponses comptées depuis minuit "
    + "(heure du Pacifique) ou depuis le dernier démarrage du Studio. Une limite ne s’affiche qu’une fois "
    + "annoncée par le service lui-même dans un refus.</span>";
  z.hidden = false;
}
function quotasRafraichir(){
  return fetch("/quotas/etat").then(r => r.json()).then(quotasAfficher).catch(() => {});
}
quotasRafraichir();
setInterval(quotasRafraichir, 30000);

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
    // Barre oblique DOUBLEE dans le source : la page est une chaine Python, qui
    // ferait d'un retour a la ligne echappe une seule fois un vrai saut de ligne,
    // au milieu d'une chaine JavaScript. Tout ce script cesserait de marcher.
    const liste = (d.retard || []).map(c => "• " + c.titre).join("\\n");
    majCase.textContent = "Une version plus récente existe (" + version + ")."
      + (liste ? "\\nCe qui vous manque :\\n" + liste : "");
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
    data = [{"id": AUTO_MODEL, "object": "model", "created": 0,
             "owned_by": "free-ai-studio", "name": "Free AI Auto"}]
    # Max n'a de sens qu'avec une cle Gemini : sans elle, il repondrait
    # exactement comme Auto, sous un nom qui promet plus.
    if provider_allowed("gemini_max"):
        data.append({"id": MAX_MODEL, "object": "model", "created": 0,
                     "owned_by": "free-ai-studio", "name": "Free AI Max"})
    return {"object": "list", "data": data}


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


def refus_tout_en_pause(eligibles: List[str], modele_chat: str) -> HTTPException:
    """Tous les services du choix sont en pause : le dire au chat, en francais,
    avec l'heure du retour, plutot qu'une erreur technique."""
    attente = min(provider_cooldown_until.get(n, 0.0) for n in eligibles) - time.time()
    causes = {(quota_state.get(n) or {}).get("cause") for n in eligibles}
    if causes == {"indisponible"}:
        code = 503
        texte = ("Aucun service gratuit branché ne répond pour l’instant (connexion Internet coupée, "
                 "ou services indisponibles). Nouvel essai dans environ %s.")
    elif "indisponible" in causes:
        code = 429
        texte = ("Les services gratuits branchés sont tous en pause : limite atteinte pour les uns, "
                 "pas de réponse des autres. Le premier revient dans environ %s.")
    else:
        code = 429
        texte = "Tous les services gratuits branchés ont atteint leur limite. Le premier revient dans environ %s."
    texte = texte % duree_lisible(attente) + " Rien n’est payé : le Studio attend."
    if (modele_chat == AUTO_MODEL and provider_allowed("gemini_max")
            and not provider_on_cooldown("gemini_max")):
        # Quota compte par modele : quand Flash-Lite est a bout, Max repond encore.
        texte += " Free AI Max a son propre quota : choisissez-le en haut du chat pour continuer."
    return HTTPException(status_code=code, detail=texte,
                         headers={"Retry-After": str(max(1, int(attente)))})


@app.post("/v1/chat/completions")
async def chat_completions(request: Request, authorization: Optional[str] = Header(default=None)):
    if not auth_ok(authorization):
        raise HTTPException(status_code=401, detail="Unauthorized")

    payload = await request.json()
    if boost_active():
        # Exact budget accounting is prioritized over streaming during a paid Boost.
        payload["stream"] = False
    requested_model = payload.get("model", AUTO_MODEL)

    # Deux choix gratuits, et eux seuls : Auto (usage courant) et Max (questions
    # difficiles). Aucun modele ne se choisit directement.
    if requested_model not in (AUTO_MODEL, MAX_MODEL, "auto", "free"):
        if FREE_ONLY or not ALLOW_PAID:
            raise HTTPException(
                status_code=403,
                detail="Paid or direct model selection is blocked. Use 'free-ai-auto' or 'free-ai-max'."
            )
    modele_chat = MAX_MODEL if requested_model == MAX_MODEL else AUTO_MODEL

    # Le service que la personne attend : le premier de SON choix qui soit branche.
    # Toute reponse venue d'un autre est un secours, et se dit.
    eligibles = [name for name in chaine_de(modele_chat) if provider_allowed(name)]
    prefere = eligibles[0] if eligibles else None
    candidates = [name for name in eligibles if not provider_on_cooldown(name)]
    if boost_active() and "openrouter" in candidates:
        candidates = ["openrouter"] + [x for x in candidates if x != "openrouter"]

    if not candidates:
        if eligibles:
            # Tous en pause : le dire, avec l'heure du retour, plutot que
            # << aucune cle >> -- les cles sont la, c'est le quota qui manque.
            raise refus_tout_en_pause(eligibles, modele_chat)
        # Ce texte s'affiche tel quel dans le chat : il envoie a la page Cles,
        # le chemin du debutant, et non au fichier .env.
        raise HTTPException(
            status_code=503,
            detail="Aucun service d’IA gratuit n’est branché : il manque une clé. Ouvrez la page Clés "
                   "du Studio, http://localhost:8010/cles, collez-y une clé Gemini (gratuite), "
                   "puis reposez la question."
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
                # Le corps est lu EN ENTIER avant d'etre analyse : c'est lui, et
                # non l'en-tete retry-after, qui dit si le refus vaut pour la
                # minute ou pour la journee (voir lire_quota).
                brut = await response.aread()
                await response.aclose()
                try:
                    corps = json.loads(brut)
                except ValueError:
                    corps = None
                if apply_rate_limit_cooldown(name, response, corps):
                    # Toute mise en pause arme l'avis, meme pendant la demande
                    # d'un autre choix : Flash-Lite qui s'epuise pendant une
                    # demande Max doit etre annonce a la demande Auto suivante.
                    # L'avis ne s'affiche que si CE service etait l'attendu.
                    avis_bascule[name] = True
                body = brut[:800].decode("utf-8", errors="replace")
                stats[name]["failures"] += 1
                stats[name]["last_error"] = f"HTTP {response.status_code}: {body[:300]}"
                errors.append(f"{name}: HTTP {response.status_code}")
                log.warning("Provider %s failed with HTTP %s", name, response.status_code)
                continue

            stats[name]["successes"] += 1
            stats[name]["last_error"] = None
            bascule = noter_service(name, prefere)

            if stream:
                media_type = response.headers.get("content-type", "text/event-stream")
                # Premier message servi par un secours apres la mise en pause du
                # service attendu : une ligne en tete de la reponse le dit, une
                # seule fois. En flux SSE seulement : dans une reponse d'un bloc,
                # l'avis finirait dans un titre de conversation.
                debut = b""
                if bascule and avis_bascule.get(prefere) and "text/event-stream" in media_type:
                    debut = morceau_avis(texte_avis(prefere, name), modele_chat)
                    avis_bascule[prefere] = False

                async def iterator(resp=response, cli=client, debut=debut):
                    try:
                        if debut:
                            yield debut
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

                return StreamingResponse(iterator(), media_type=media_type,
                                         headers={"X-Free-AI-Provider": name})

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
                    "X-Free-AI-Secours": "oui" if bascule else "non",
                    "X-Free-AI-Mode": "boost" if boost_active() else "free",
                },
                media_type=media_type.split(";")[0],
            )

        except Exception as exc:
            stats[name]["failures"] += 1
            stats[name]["last_error"] = str(exc)[:300]
            errors.append(f"{name}: {type(exc).__name__}")
            log.exception("Provider %s raised an error", name)
            # Coupure reseau, delai depasse : traite comme un 5xx.
            pause_indisponible(name)
            avis_bascule[name] = True

    await client.aclose()
    if eligibles and all(provider_on_cooldown(n) for n in eligibles):
        # Le refus qui vient d'arriver a mis en pause le dernier service libre :
        # meme reponse que si la pause datait d'avant la demande.
        raise refus_tout_en_pause(eligibles, modele_chat)
    raise HTTPException(
        status_code=503,
        detail="Aucun service gratuit branché n’a pu répondre (%s). La page "
               "http://localhost:8010/diagnostic dit lequel bloque et pourquoi. Rien n’est payé."
               % ", ".join(errors)
    )
