# Free Tier Manager

Le **Free Tier Manager** est la passerelle transparente entre Open WebUI et les fournisseurs IA.

## Ce que voit le débutant

Dans Open WebUI, deux choix :

- **Free AI Auto** : l'usage courant. C'est le premier de la liste.
- **Free AI Max** : les questions difficiles (code, raisonnement long, documents lourds). Il n'apparaît que si une clé Gemini est branchée.

Il n'a pas besoin de choisir Gemini, Groq ou OpenRouter.

## Ordre par défaut

```text
Open WebUI
   ↓
Free AI Auto
   ↓
1. Gemini → gemini-3.5-flash-lite (Free Tier)
   ↓ si indisponible / quota atteint
2. OpenRouter → openrouter/free
   ↓ si indisponible / quota atteint
3. Groq → modèle du free plan
```

`gemini-3.5-flash-lite` est le modèle de Free AI Auto depuis le 11/09/2026 (avant : `gemini-3.8-flash`). C'est la variante Flash-Lite, prévue pour l'usage courant.

**Free AI Max** essaie d'abord le modèle haut de gamme, puis retombe sur la chaîne d'Auto :

```text
1. Gemini Max → gemini-3.8-flash (Free Tier, son propre quota)
   ↓ si indisponible / quota atteint
2. Gemini → gemini-3.5-flash-lite
   ↓
3. OpenRouter → openrouter/free
   ↓
4. Groq → modèle du free plan
```

Google compte le quota gratuit **par projet et par modèle** : Max a le sien. Auto n'y touche jamais, pour qu'il reste disponible quand on choisit Max. Réglages : `GEMINI_MAX_MODEL` (défaut `gemini-3.8-flash`) ; `ENABLE_GEMINI_MAX=false` retire Max du chat ; `ENABLE_GEMINI=false` coupe les deux modèles Gemini.

Pourquoi deux choix : sur les fiches techniques de Google, 3.8 Flash obtient 89,4 % à Terminal-bench 2.1 contre 54,0 % pour 3.5 Flash-Lite, et 1545 contre 1140 Elo à GDPVal-AA v2 ([Flash-Lite](https://deepmind.google/models/model-cards/gemini-3-5-flash-lite/), [3.8 Flash](https://deepmind.google/models/model-cards/gemini-3-8-flash/), relevé du 11/09/2026). Son quota gratuit n'est pas publié.

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

Le manager refuse la sélection directe d'un modèle arbitraire. Il ne publie que `free-ai-auto` et `free-ai-max`, tous deux limités aux routes gratuites.

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

## Limites gratuites de chaque fournisseur

Relevé du **11/09/2026** sur les pages officielles. Ces chiffres changent sans préavis : relisez la source avant de vous y fier.

| Fournisseur | Modèle utilisé | Demandes par jour | Par minute | Remise à zéro | Source |
|---|---|---|---|---|---|
| Gemini (Google) | `gemini-3.5-flash-lite` | **non publié** : Google renvoie à AI Studio, où chaque projet voit ses propres limites | non publié | minuit, heure du Pacifique | [rate-limits](https://ai.google.dev/gemini-api/docs/rate-limits) |
| OpenRouter | `openrouter/free` | 50 ; 1 000 après au moins 10 $ de crédits achetés | 20 | non documentée | [limits](https://openrouter.ai/docs/api-reference/limits) |
| Groq | `openai/gpt-oss-20b` | 1 000 | 30 | non documentée | [rate-limits](https://console.groq.com/docs/rate-limits) |

Pour Gemini, la page officielle dit seulement que les limites sont comptées **par projet** (pas par clé) et **par modèle**, que le quota journalier repart à minuit heure du Pacifique, et que les valeurs réelles s'affichent dans AI Studio. Le chiffre « 20 par jour pour Flash » de l'audit du 11/09/2026 n'est donc pas vérifiable sur une page publique ; le « 500 par jour » qu'il cite pour Flash-Lite correspond, sur la page des prix, à la ligne « ancrage Google Search », pas aux demandes de chat. Le Studio ne suppose aucun chiffre : il lit celui que Google écrit dans son refus.

**Mesuré le 11/09/2026**, sur un projet Google au palier gratuit : 65 demandes à `gemini-3.5-flash-lite` dans la même journée, dont 40 en rafale (une toutes les 0,8 s environ), **sans aucun refus**. Ce n'est pas la limite, seulement un plancher observé. Elle reste inconnue tant que Google n'a pas refusé.

Si votre `.env` date d'avant le 11/09/2026, il contient peut-être `GEMINI_FREE_MODEL=gemini-3.8-flash` ; cette ligne prime sur le nouveau défaut. Supprimez-la, ou mettez `gemini-3.5-flash-lite`, puis redémarrez.

`gemini-3.5-flash-lite` et `gemini-3.8-flash` sont tous deux gratuits sur le palier gratuit ([pricing](https://ai.google.dev/gemini-api/docs/pricing)) et exposés tels quels par l'API de Google ([models](https://ai.google.dev/gemini-api/docs/models)). Chacun a son propre quota : passer de l'un à l'autre ne rend pas de quota à l'autre.

## Quand une limite est atteinte

Lorsqu'un fournisseur renvoie `429 Too Many Requests`, le Free Tier Manager lit le corps du refus :

- **quota du jour** (Gemini : `quotaId` contenant `PerDay`, ou code `quota_exceeded`) : Gemini est mis en pause **jusqu'à minuit heure du Pacifique**, au lieu d'être réessayé toutes les 30 secondes ;
- **limite par minute** (`rate_limit_exceeded`, ou tout autre refus) : pause courte, de 5 s à 5 min, d'après le délai indiqué par le fournisseur. Pour OpenRouter et Groq, l'heure de remise à zéro du quota du jour n'est pas documentée : même un refus « du jour » y reçoit une pause courte, puis un nouvel essai.

Un service **qui ne répond pas** (statut `5xx`, par exemple `503 The model is overloaded` chez Google, coupure réseau, délai dépassé) reçoit lui aussi une pause courte : de 5 à 60 s, 30 s si le fournisseur n'indique rien. Sans elle, chaque message repaierait l'aller-retour raté.

Il essaie aussitôt le fournisseur gratuit suivant. Le basculement n'est **pas silencieux** :

- la première réponse servie par le secours commence par une ligne en italique : « ℹ️ Gemini (Google) a atteint sa limite gratuite du jour (N demandes) : cette réponse est fournie par OpenRouter. Retour prévu dans environ X h, à minuit heure du Pacifique. » ; elle n'est écrite qu'une fois par pause, et seulement dans une réponse en flux (celles du chat). Pour un service qui ne répond pas, elle dit : « ℹ️ Gemini (Google) ne répond pas pour l'instant : cette réponse est fournie par … Nouvel essai dans 30 s. » Toute mise en pause arme l'avis, même survenue pendant une demande de l'autre choix du chat : si Flash-Lite atteint sa limite pendant une demande Free AI Max, la demande Free AI Auto suivante le dit ;
- `/studio` affiche un bandeau « Le chat répond en ce moment avec un service de secours » et, pour chaque service : disponible ou en pause, heure de reprise, demandes restantes estimées ;
- `/diagnostic` ajoute une ligne par service, avec la même information ;
- `GET /quotas/etat` (sans clé, sans secret) rend l'état brut : `en_pause`, `reprise_a`, `quota_du_jour_atteint`, `indisponible`, `limite_annoncee`, `servies_aujourdhui`, `reste_estime`, `secours_en_cours`, `dernier_service` ;
- les réponses non-flux portent l'en-tête `X-Free-AI-Secours: oui|non`.

Si **tous** les services branchés du choix sont en pause, le chat répond `429`, en français, avec l'heure du premier retour. C'est vrai dès la demande dont le refus met en pause le dernier service libre : avec la seule clé Gemini, le premier refus du jour donne ce message, pas une erreur technique. Si la pause vient de services qui ne répondent pas, la réponse est `503`, avec le même délai. Quand Free AI Auto est à bout et que Free AI Max répond encore, le message propose de le choisir. Sans aucune clé, le chat répond `503` et envoie à la page Clés (`http://localhost:8010/cles`). Rien de payant n'est essayé.

Ce que le Studio **ne sait pas** : le quota restant côté Google avant le premier refus. Il compte les réponses servies depuis minuit (ou depuis son dernier démarrage) ; l'estimation « reste N » n'apparaît qu'une fois que Google a écrit sa limite dans un refus, et seulement pour le même modèle.
