# Sandbox — Modal-first, Local, Kaggle et Colab

Free AI Studio sépare **l'accès direct de l'utilisateur** et **l'orchestration de l'agent**.

## Routage automatique

Le provider `auto` est le mode recommandé :

```text
Agent → Modal → artefacts → Agent
          ↓ indisponible/configuration absente
        Local
          ↓ worker indisponible
        Kaggle (si configuré)
          ↓ sinon
        Colab handoff
```

Modal est donc le **backend principal lorsqu'il est configuré**. Une installation fraîche ne lance jamais Modal tant que `MODAL_ENABLED=true` et les tokens n'ont pas été fournis.

Important : le fallback concerne les **pannes/configurations d'infrastructure**. Si le code est bien exécuté sur Modal ou Local mais termine avec une erreur, le Studio retourne cette erreur à l'agent au lieu de réexécuter automatiquement le même code ailleurs.

## Accès direct utilisateur conservé

| Moteur | Accès utilisateur direct | Lancement par l'agent | Retour des résultats |
|---|---|---|---|
| Modal | Dashboard Modal | oui, principal si configuré | automatique |
| Local | via Studio/API | oui, fallback | automatique |
| Kaggle | **oui, kaggle.com/code** | oui si activé/configuré | automatique via outputs kernel |
| Colab | **oui, colab.research.google.com** | handoff notebook | import vers le registre d'artefacts |

Les boutons **Ouvrir Kaggle** et **Ouvrir Colab** restent toujours visibles dans `http://127.0.0.1:8020/`, indépendamment de Modal.

## Modal principal

Dans `.env` :

```dotenv
MODAL_ENABLED=true
MODAL_TOKEN_ID=...
MODAL_TOKEN_SECRET=...
MODAL_JOB_TIMEOUT_SECONDS=300
MODAL_IDLE_TIMEOUT_SECONDS=60
MODAL_CLEANUP_GRACE_SECONDS=60
MODAL_CPU=1.0
MODAL_MEMORY_MB=2048
MODAL_GPU_DEFAULT=T4
```

Le Sandbox Manager utilise le SDK Modal et `modal.Sandbox`. Pour chaque job il :

1. crée un Sandbox temporaire ;
2. copie le code dans le filesystem du Sandbox ;
3. exécute Python avec `FREE_AI_OUTPUT_DIR=/tmp/free_ai_output` ;
4. récupère stdout/stderr ;
5. copie les fichiers de sortie dans le registre d'artefacts du Studio ;
6. termine explicitement le Sandbox avec attente de terminaison, afin de libérer immédiatement les ressources cloud/GPU.

Trois protections évitent qu'un GPU reste réservé inutilement :

- `terminate(wait=True)` est appelé dès que stdout/stderr et les artefacts sont récupérés ;
- `MODAL_IDLE_TIMEOUT_SECONDS` (60 s par défaut) fait terminer par Modal une Sandbox devenue inactive ;
- le `timeout` absolu de la Sandbox vaut `MODAL_JOB_TIMEOUT_SECONDS + MODAL_CLEANUP_GRACE_SECONDS` (360 s par défaut), tandis que l'exécution du code reste limitée à `MODAL_JOB_TIMEOUT_SECONDS` (300 s).

Le réseau Modal est bloqué par défaut et n'est ouvert que si le job demande explicitement `internet=true`. Le GPU n'est demandé que lorsque `gpu=true`.

Modal est un service externe à quota/facturation propre. Free AI Studio ne peut pas garantir qu'un compte possède encore du crédit gratuit : laissez `MODAL_ENABLED=false` tant que vous ne souhaitez pas utiliser votre compte Modal.

## Isolation locale

Le fallback local s'exécute dans `sandbox-worker`, un conteneur distinct : pas de clés API du Studio, réseau Docker interne uniquement, root filesystem en lecture seule, capacités Linux supprimées, `no-new-privileges`, limites CPU/RAM/PID/durée. Seuls les fichiers écrits dans `FREE_AI_OUTPUT_DIR` deviennent des artefacts.

Cette isolation réduit fortement les risques, mais n'est pas une frontière équivalente à une VM dédiée face à un attaquant déterminé.

## Kaggle automatique + accès direct

Dans `.env` :

```dotenv
KAGGLE_ENABLED=true
KAGGLE_USERNAME=votre_nom
KAGGLE_API_TOKEN=votre_token
```

Le manager crée un kernel privé, suit son état et récupère ses outputs. Le bouton direct Kaggle reste utilisable même lorsque l'orchestration automatique n'est pas configurée.

Ce pilotage suppose **vos** identifiants, sur **votre** machine. Si le Studio semble servir d'autres personnes (`STUDIO_HEBERGE=true`, `WEBUI_AUTH=true`, page ouverte par l'adresse réseau de la machine, ou requête relayée par un proxy), le Sandbox coupe Kaggle automatique. `POST /jobs` avec `provider=kaggle` répond alors 403, le mode `auto` passe directement au handoff Colab, et `GET /etat` indique `kaggle.automatique_permis: false` avec la raison. Détail : `docs/GPU_CLOUD.md`.

## Colab direct / handoff

Colab reste accessible directement. Si tous les moteurs d'exécution automatique sont indisponibles, le provider `auto` prépare un `.ipynb` que l'utilisateur peut ouvrir dans Colab. Les résultats déposés dans `FREE_AI_OUTPUT_DIR` peuvent ensuite être réimportés dans le registre de ressources.

L'API Colab officielle reste en bêta/allowlist ; le Studio ne prétend pas disposer d'une exécution arbitraire universelle via cette API.

## API pour l'agent

Le Sandbox Manager écoute sur `http://127.0.0.1:8020` et protège les routes de données avec `SANDBOX_MANAGER_KEY`.

Endpoints principaux :

```text
GET  /providers
POST /jobs
GET  /jobs
GET  /jobs/{id}
GET  /jobs/{id}/colab-notebook
POST /jobs/{id}/artifacts
GET  /artifacts
GET  /artifacts/{id}
```

Exemple recommandé :

```json
{
  "provider": "auto",
  "title": "Analyse CSV",
  "code": "from pathlib import Path\nimport os\nPath(os.environ['FREE_AI_OUTPUT_DIR'],'result.txt').write_text('ok')",
  "gpu": false,
  "internet": false
}
```

Chaque élément de `artifacts` est une ressource réutilisable par l'agent de codage.

## Client pratique

```bash
# Modal-first avec fallback automatique
python scripts/sandbox.py submit mon_script.py --wait

# Forcer Modal
python scripts/sandbox.py submit mon_script.py --provider modal --wait

# Forcer le local
python scripts/sandbox.py submit mon_script.py --provider local --wait

# Forcer Kaggle
python scripts/sandbox.py submit entrainement.py --provider kaggle --gpu --wait

# Préparer explicitement Colab
python scripts/sandbox.py submit notebook_job.py --provider colab

# Réimporter un résultat Colab
python scripts/sandbox.py import <JOB_ID> free-ai-studio-results.zip

# Voir les ressources
python scripts/sandbox.py artifacts
```
