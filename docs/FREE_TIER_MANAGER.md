# Free Tier Manager

Le **Free Tier Manager** est la passerelle transparente entre Open WebUI et les fournisseurs IA.

## Ce que voit le débutant

Dans Open WebUI, le modèle principal est :

**Free AI Auto**

Il n'a pas besoin de choisir Gemini, Groq ou OpenRouter.

## Ordre par défaut

```text
Open WebUI
   ↓
Free AI Auto
   ↓
1. Gemini → gemini-3.8-flash (Free Tier)
   ↓ si indisponible / quota atteint
2. OpenRouter → openrouter/free
   ↓ si indisponible / quota atteint
3. Groq → modèle du free plan
```

L'ordre est configurable dans `.env` :

```env
FREE_PROVIDER_ORDER=gemini,openrouter,groq
```

## Protection contre les modèles payants

En mode normal :

```env
FREE_ONLY=true
ALLOW_PAID_MODELS=false
MAX_DAILY_COST=0
```

Le manager refuse la sélection directe d'un modèle arbitraire. Open WebUI ne publie que `free-ai-auto`.

Pour OpenRouter, le manager force :

```env
OPENROUTER_FREE_MODEL=openrouter/free
```

Il ne transmet pas au fournisseur les paramètres de routage ou de prix fournis par un client.

## Deux niveaux de sécurité

### Mode débutant — recommandé

```env
ALLOW_FREE_TIER_ACCOUNTS=true
```

Gemini Free Tier est prioritaire. OpenRouter `openrouter/free` sert de fallback strictement gratuit, puis Groq peut servir de troisième recours si sa clé a accès à un free tier.

### Mode ultra-strict

```env
ALLOW_FREE_TIER_ACCOUNTS=false
```

Le manager n'utilise que les fournisseurs marqués `strict-zero`. Cela limite alors le routage à `openrouter/free`; Gemini et Groq sont ignorés.

## Limite importante

Un logiciel local ne peut pas garantir le statut de facturation d'un compte externe si le fournisseur ne l'expose pas à l'API.

Le manager bloque donc les routes payantes qu'il contrôle, mais l'utilisateur doit conserver ses comptes Gemini/Groq dans leur niveau gratuit s'il active ces fallbacks.

## Voir l'état

Linux/macOS :

```bash
./scripts/free-tier-status.sh
```

Ou :

```bash
docker compose ps
```

Le manager expose aussi localement :

- `http://127.0.0.1:8010/health`
- `/status` avec authentification locale

Aucune clé fournisseur n'est retournée dans les réponses de statut.


## OpenRouter renforcé

OpenRouter documente actuellement deux plafonds pour les modèles gratuits :

```text
Compte sans >= $10 de crédits achetés : 50 requêtes/jour
Compte avec >= $10 de crédits achetés : 1 000 requêtes/jour
Cadence dans les deux cas : 20 requêtes/minute
```

Le dépôt **ne dépense pas automatiquement ces crédits** : `openrouter/free` reste forcé et les modèles payants restent bloqués.

### Détection automatique optionnelle

OpenRouter fournit l'endpoint officiel :

```text
GET https://openrouter.ai/api/v1/credits
```

Cet endpoint nécessite une **Management Key**.

Si vous souhaitez que le tableau d'état détecte automatiquement votre niveau :

```env
OPENROUTER_MANAGEMENT_KEY=
```

Cette clé sert uniquement à lire les informations de crédits. Elle n'est jamais exposée à Open WebUI.

Sans Management Key, Free AI Studio fonctionne normalement ; le niveau de quota est simplement affiché comme inconnu.

### Protection contre les 429

Lorsqu'un fournisseur renvoie `429 Too Many Requests`, le Free Tier Manager le place temporairement en pause et essaie immédiatement le fournisseur gratuit suivant. Cela évite de répéter inutilement des requêtes sur un fournisseur déjà limité.
