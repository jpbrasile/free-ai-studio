# Free AI Studio

**Une IA personnelle multimodale, pensée pour les débutants, qui exploite automatiquement les offres gratuites avant toute dépense.**

> État : projet expérimental / alpha. Les quotas et conditions des fournisseurs externes peuvent changer.

## 🧪 Sandbox pour l’agent de codage

Le Studio inclut désormais une couche Sandbox **Modal-first** : Modal est le backend automatique principal lorsqu’il est configuré, Local sert de fallback isolé, Kaggle peut prendre le relais si configuré, et Colab reste disponible en handoff. **Les accès directs Colab/Kaggle restent toujours visibles pour l’utilisateur.** Les sorties récupérées deviennent des **artefacts** réutilisables par l’agent de codage.

Interface : `http://127.0.0.1:8020/`  
Documentation : `docs/SANDBOX.md`


## Ce que l'utilisateur voit

```text
💬 Chat   🎨 Image   🎬 Vidéo
🎤 Voix  👁 Vision  🔎 Recherche
📚 Étudier           💻 Code

🟢 Gratuit par défaut
```

Le débutant n'a pas besoin de choisir entre 25 modèles ou de comprendre Docker, les endpoints ou les GPU distants.

## Philosophie

Free AI Studio sépare deux interfaces :

- **l'assistant de codage** dans VS Code = installateur, administrateur, réparateur et assistant de mise à jour ;
- **Free AI Studio / Open WebUI** = interface quotidienne pour utiliser l'IA.

Le dépôt contient `AGENTS.md`, qui briefe directement les assistants de codage compatibles.

## Installation recommandée

### 1. Installer
- Git
- Docker Desktop
- VS Code
- un assistant de codage disposant, avec votre autorisation, d'un accès aux fichiers et au terminal.

### 2. Cloner le dépôt

```bash
git clone <URL_DU_DEPOT>
cd free-ai-studio
```

### 3. Ouvrir le dossier dans VS Code

Puis demander à l'assistant :

> Lis `AGENTS.md` et installe Free AI Studio sur cet ordinateur. Configure au maximum ce que tu peux sans aucune dépense et sans exposer mes clés.

### 4. Installation manuelle alternative

Linux/macOS :

```bash
./install.sh
./start.sh
```

Windows PowerShell :

```powershell
.\install.ps1
.\start.ps1
```

Open WebUI :
`http://localhost:3000`

Portail débutant :
`http://127.0.0.1:8010/studio`

## Gratuit uniquement par défaut

```env
FREE_ONLY=true
ALLOW_PAID_MODELS=false
ALLOW_PAID_GPU=false
MAX_DAILY_COST=0
```

Aucun service payant ne doit être activé automatiquement.

Un fournisseur externe peut modifier ses offres ou quotas : l'assistant de codage doit vérifier les sources officielles avant toute nouvelle intégration ou modification tarifaire.

## Chat : fallback automatique

Architecture minimale :

```text
Open WebUI
    ↓
Free Tier Manager
    ↓
OpenRouter gratuit → Groq free plan → Gemini free tier
```

Le débutant voit principalement **Free AI Auto**. Le manager tente les fournisseurs éligibles et applique les fallbacks.

Détails : `docs/FREE_TIER_MANAGER.md`.

## GPU pour Image / Vidéo

Stratégie cible :

```text
Modal configuré (automatique)
   ↓ si indisponible
Local isolé
   ↓ si indisponible
Kaggle configuré
   ↓ sinon
Colab handoff

Accès direct permanent : [ Ouvrir Colab ]  [ Ouvrir Kaggle ]
```

### Modal
Modal est maintenant le **moteur distant automatique principal** du Sandbox Manager lorsqu’il est configuré. Le provider `auto` tente Modal en premier, puis les fallbacks.

Formulation débutant :
> « Free AI Studio peut utiliser temporairement une machine puissante lorsque votre ordinateur ne suffit pas. »

### Colab / Kaggle
Ce sont des solutions de secours gratuites ponctuelles. Elles doivent être accessibles via des notebooks préparés et des liens cliquables, pas utilisées comme serveurs permanents.

Voir `notebooks/README.md`, `docs/GPU_CLOUD.md` et `docs/MODAL_CATALOG.md`.

## Configuration des services

Commencez simplement avec :
- Gemini ;
- Groq ;
- OpenRouter.

Ajoutez les autres seulement selon vos besoins :
- Modal : puissance GPU automatique distante ;
- Colab / Kaggle : GPU ponctuel gratuit ;
- E2B / Daytona : ordinateur temporaire séparé pour tester du code ;
- Hugging Face / Cloudflare : fournisseurs de secours ou modèles supplémentaires.

Voir `docs/SERVICES_DEBUTANT.md` et `docs/API_KEYS.md`.

## Étudier avec NotebookLM

La section **Étudier** peut ouvrir le service officiel NotebookLM comme complément externe.

Free AI Studio :
- n'envoie aucun document automatiquement ;
- n'utilise pas d'API non officielle ;
- ne présente pas le niveau gratuit comme illimité.

Voir `docs/NOTEBOOKLM.md`.

## Boost payant facultatif

Le Boost est séparé du fonctionnement gratuit et désactivé par défaut.

Avant activation, l'interface doit montrer :
- bénéfice attendu ;
- plafond ;
- budget restant ;
- réserve protégée.

Voir `docs/BOOST.md`.

## Architecture cible

```text
Utilisateur
   │
   ├── Assistant de codage
   │      ├── installation
   │      ├── configuration
   │      ├── maintenance
   │      └── Modal / modèles / diagnostic
   │
   └── Free AI Studio
          ├── Open WebUI
          ├── Free Tier Manager
          ├── Chat / Vision / Search
          ├── Image / Vidéo / Voix
          │      ├── GPU local
          │      ├── Modal automatique
          │      └── Colab / Kaggle secours
          └── Étudier / Code
```

## Sécurité

Ne committez jamais `.env`.

Le `.gitignore` protège les fichiers d'environnement locaux. Utilisez uniquement `.env.example` pour documenter les noms de variables.

Avant un commit :

```bash
git status
git diff
```

Et vérifiez qu'aucun secret n'apparaît.

## Développement

Les contributions sont bienvenues. Voir `CONTRIBUTING.md`.

Les validations GitHub vérifient notamment :
- syntaxe Python ;
- syntaxe Bash ;
- structure Docker Compose quand Docker Compose est disponible dans le runner.

## Limites actuelles

Le dépôt est encore en développement :
- les workflows Image / Vidéo / Voix ne sont pas tous aussi intégrés que le Chat ;
- Colab reste un handoff utilisateur pour l’exécution générique ;
- l'installation doit encore être testée de bout en bout sur plusieurs machines propres ;
- les quotas externes ne peuvent pas être garantis par le projet.

## Licence

Voir `LICENSE`.


## Vérification après installation

Après `./start.sh` (Linux/macOS) ou `.\start.ps1` (Windows), lancez le test intégré :

- Linux/macOS : `./scripts/self-test.sh`
- Windows : `.\scripts\self-test.ps1`

Le test ne consomme aucun crédit IA : il valide Docker Compose, l’état des conteneurs, `/health`, l’authentification du manager et l’accès local à Open WebUI.

### Mode gratuit strict

Le routage LLM livré est **Gemini Free Tier d’abord**, puis `openrouter/free`, puis Groq si activé. Gemini utilise `gemini-3.8-flash` par défaut. Le Studio ne peut pas déterminer automatiquement si une clé Google/Groq est rattachée à un niveau gratuit ou payant : pour une garantie ultra-stricte, passez `ALLOW_FREE_TIER_ACCOUNTS=false`, ce qui conserve uniquement les routes explicitement zéro coût comme `openrouter/free`.

### Fonctions média

Le chat est inclus. Image, vidéo et voix sont affichés comme **optionnels** : ils nécessitent un backend compatible configuré séparément dans Open WebUI. Le paquet n’annonce plus ces fonctions comme installées lorsqu’elles ne le sont pas.
