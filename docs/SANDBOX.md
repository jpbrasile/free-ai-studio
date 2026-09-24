# Sandbox — Modal-first, Local, Kaggle et Colab

Free AI Studio sépare **l'accès direct de l'utilisateur** et **l'orchestration de l'agent**.

## Routage automatique

Le provider `auto` est le mode recommandé :

```text
Sans carte ni Internet     Avec carte, sans Internet      Avec Internet
Agent → Local              Agent → carte d'ici (libre ?)  Agent → Modal
  ↓ worker indisponible      ↓ occupée ou absente           ↓ indisponible/configuration absente
Modal (si configuré)       Modal (si configuré)           Local
  ↓ sinon                    ↓ sinon                        ↓ worker indisponible
Colab handoff              Local, Kaggle, Colab           Kaggle (si configuré), puis Colab
```

Votre ordinateur passe **d'abord** quand il suffit (décision du 23/09/2026) : le bac à sable local tourne sur processeur, sans Internet, et un code qui ne demande ni l'un ni l'autre n'a aucune raison de partir sur une machine louée. Un code qui demande une **carte** passe sur celle d'ici quand elle est libre ; le bac à sable de la carte ne lit le cache des modèles qu'en **lecture seule**. Modal reste le **premier choix pour ce qui demande Internet**, et le secours d'une carte occupée, lorsqu'il est configuré. Une installation fraîche ne lance jamais Modal tant que `MODAL_ENABLED=true` et les tokens n'ont pas été fournis.

Important : le fallback concerne les **pannes/configurations d'infrastructure**. Si le code est bien exécuté sur Modal ou Local mais termine avec une erreur, le Studio retourne cette erreur à l'agent au lieu de réexécuter automatiquement le même code ailleurs.

## Accès direct utilisateur conservé

| Moteur | Accès utilisateur direct | Lancement par l'agent | Retour des résultats |
|---|---|---|---|
| Modal | Dashboard Modal | oui, premier choix pour Internet ; secours sinon | automatique |
| Local | via Studio/API | oui, premier choix sans carte ni Internet | automatique |
| Kaggle | **oui, kaggle.com/code** | oui si activé/configuré ; en `auto`, jobs `gpu=true` seulement | automatique via outputs kernel |
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

Même sur votre machine, le mode `auto` n'envoie sur Kaggle que les jobs `gpu=true` : la politique d'usage de Kaggle exclut ce qui n'est pas de la science des données. Un job sans GPU passe au handoff Colab, avec `cpu_job_not_sent` dans `fallback_attempts` ; `GET /providers` le dit (`kaggle.automatic_only_for: "gpu_jobs"`).

## Colab : le carnet ouvert, piloté par le Studio

Colab n'a pas d'API d'exécution ouverte à tous, et sa FAQ interdit, sur l'offre gratuite, de contourner l'interface du carnet. Le Studio passe donc **par** le carnet, avec le protocole de `googlecolab/colab-mcp` (Apache-2.0, Google), réimplémenté dans `sandbox-manager/colab_pont.py` :

1. `GET /colab/etat` donne une adresse `https://colab.research.google.com/notebooks/empty.ipynb#mcpProxyToken=…&mcpProxyPort=8020`. La page vidéo l'affiche dans le bouton « Ouvrir Colab ».
2. La personne l'ouvre dans **son** navigateur, avec **son** compte Google, et accepte la boîte « Connect to a local Colab MCP server ». L'onglet se branche sur `ws://localhost:8020`.
3. Le Studio ajoute ses cellules dans le carnet, sous les yeux de la personne. Le script tourne en arrière-plan dans la machine Colab. Une petite cellule le suit toutes les 10 s, puis les fichiers de `FREE_AI_OUTPUT_DIR` reviennent par morceaux de 256 Kio, avec contrôle de l'empreinte SHA-256. À la fin, les cellules du Studio sont retirées.

Les gardes du branchement :
- **Origin :** Colab seulement.
- **Jeton :** tiré au hasard, renouvelé à chaque débranchement.
- **Un seul carnet à la fois.**
- **Studio partagé :** le branchement est coupé, comme Kaggle automatique.

Rien ne s'exécute sur cet ordinateur : il envoie du texte de cellule et relit des sorties.

Où ça sert :
- **Vidéo :** « Si on loue » › « Colab ». Pour une vidéo, la carte du carnet doit être réglée sur GPU T4 (menu « Exécution » › « Modifier le type d'exécution ») ; sans carte, le travail ne part pas et la page le dit.
- **`POST /jobs` avec `provider=colab` :** le travail va au carnet s'il est branché.
- **Mode `auto` :** le carnet branché passe avant le fichier `.ipynb` à importer.
- **Arrêt d'urgence :** il tue vraiment le calcul dans le carnet, dans les 10 s.

Sans carnet branché, le comportement d'avant reste : `auto` prépare un `.ipynb` que l'utilisateur peut ouvrir dans Colab, et les résultats déposés dans `FREE_AI_OUTPUT_DIR` peuvent être réimportés dans le registre de ressources.

**Vérifié :**
- sur un faux carnet qui parle le même protocole et exécute les cellules (`tests/test_colab_pont.py`) ;
- sur de vraies websockets (uvicorn, 24/09/2026) : 403 pour une mauvaise origine ou un mauvais jeton, et un travail avec fichier de 700 Ko rapatrié intact.

**Non vérifié sur le vrai Colab** : voir `PLAN.md`, point 17.4.

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
# Automatique : ici d'abord (processeur, ou carte si libre), Modal pour Internet
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
