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

## Installation sur l'ordinateur de quelqu'un qui n'écrira jamais une commande

Quatre gestes. Aucun terminal, aucun assistant de code.

1. **Docker Desktop** — <https://www.docker.com/products/docker-desktop/>. Installer,
   redémarrer si on le demande, puis **ouvrir Docker Desktop** et attendre que la baleine
   en bas à gauche soit verte. C'est le seul vrai prérequis : sans lui, rien ne tourne.
   S'il affiche **« Virtualization support not detected »**, ce n'est pas votre
   installation qui est en cause et ce n'est pas une impasse :
   [docs/DEPANNAGE.md](docs/DEPANNAGE.md) donne les trois causes possibles, dans l'ordre,
   avec le chemin à cliquer pour chacune.
2. **Git pour Windows** — <https://git-scm.com/download/win>. Suivant jusqu'au bout.
   Sert uniquement à ce que le bouton « Mettre à jour » sache quelle version vous avez.
   Si VS Code était déjà ouvert, le fermer et le rouvrir : il ne cherche Git qu'à son
   démarrage.
3. **Récupérer le dossier.** Dans VS Code : menu **Affichage** → **Palette de commandes**,
   taper `Git: Clone`, coller `https://github.com/jpbrasile/free-ai-studio.git`, et
   **désigner le dossier parent** — `Documents`, pas un dossier `free-ai-studio` déjà
   créé : git fabrique lui-même le sous-dossier à son nom. Deux dossiers du même nom
   partagent le même projet Docker, ce qui casse le chat plus tard.
   *(Sans Git : bouton vert « Code » sur GitHub → « Download ZIP » → extraire. Tout
   marchera sauf le bouton de mise à jour, et l'installateur vous le dira.)*
4. **Double-cliquer `demarrer.cmd`**, à la racine du dossier.

`demarrer.cmd` vérifie l'ordinateur avant d'agir : version de Windows, Docker installé,
Docker **démarré** (ce n'est pas la même chose, et c'est ce qui manque neuf fois sur dix),
ports 3000/8010/8020 libres, dossier complet. Quand quelque chose manque, il dit quoi faire
et ouvre la page de téléchargement — il ne montre jamais une erreur technique. Quand Docker
ne démarre pas, il ne se contente pas de dire « ouvrez-le » : il lit l'état réel de la
virtualisation et nomme la cause — micrologiciel éteint, composants Windows non cochés,
WSL en panne, ou Docker simplement pas lancé. Puis il crée
les réglages, fabrique les mots de passe internes au hasard, construit les services, lance
le veilleur de mise à jour, attend que la page réponde vraiment, et l'ouvre.

Le rappeler plus tard ne casse rien : il redémarre, conserve `.env`, et ne relance pas un
deuxième veilleur.

Il reste alors **une seule chose** à faire : sur la page, cliquer **Clés** et coller une clé
Google Gemini gratuite. Elle suffit pour écrire, lire une image et fabriquer une image.

**Si quelque chose ne marche pas**, le Studio se diagnostique lui-même :
<http://127.0.0.1:8010/diagnostic> teste la chaîne maillon par maillon, dit où elle casse,
propose un bouton **Réparer la liaison** et un bouton **Copier ce diagnostic** — de quoi
montrer l'état exact à quelqu'un sans avoir à le décrire. Aucune clé n'y figure. Les pannes
déjà rencontrées et ce qui les a réglées : [docs/DEPANNAGE.md](docs/DEPANNAGE.md).

## Installation avec un assistant de codage

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
Gemini (palier gratuit) → OpenRouter `openrouter/free` → Groq (si activé)
```

Le débutant voit principalement **Free AI Auto**. Le manager tente les fournisseurs éligibles dans cet ordre (`FREE_PROVIDER_ORDER`). Quand le premier a épuisé son quota, **le basculement n’est pas silencieux** : la réponse suivante du chat commence par une ligne qui le dit, et les pages `/studio` et `/diagnostic` affichent le service en pause, la limite annoncée par le fournisseur et l’heure de reprise.

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

Les validations GitHub (`.github/workflows/validate.yml`) vérifient :
- la compilation de **tous** les fichiers Python suivis par git (découverts, pas listés à la main) ;
- `ruff check` : erreurs de syntaxe, noms non définis, imports morts (règles `E9` et `F`, `ruff.toml`) ;
- le chargement réel des trois services FastAPI (`scripts/verifier-imports.py`) ;
- la syntaxe du JavaScript embarqué dans leurs pages (`scripts/verifier-js.py`, par `node --check`) ;
- les tests `tests/` : bascule annoncée quand un quota gratuit est atteint, garde Kaggle ;
- syntaxe Bash, interdits du mode gratuit, structure Docker Compose.

Les mêmes commandes tournent en local : `ruff check .`, `python scripts/verifier-imports.py`, `python -m pytest -q tests`.

## Limites actuelles

Le dépôt est encore en développement :
- fonctions stabilisées : **Chat, Image, Recherche Web**. Voix, Vidéo, Étudier, Code et Sandbox portent la mention « expérimental » sur `/studio` : elles peuvent changer ou casser d'une version à l'autre ;
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

Le routage LLM livré est **Gemini Free Tier d’abord**, puis `openrouter/free`, puis Groq si activé. Gemini utilise `gemini-3.5-flash-lite` par défaut ; le modèle haut de gamme `gemini-3.8-flash` reste accessible sur choix explicite (`GEMINI_FREE_MODEL`), avec son propre quota. Le Studio ne peut pas déterminer automatiquement si une clé Google/Groq est rattachée à un niveau gratuit ou payant : pour une garantie ultra-stricte, passez `ALLOW_FREE_TIER_ACCOUNTS=false`, ce qui conserve uniquement les routes explicitement zéro coût comme `openrouter/free`.

### Fonctions média

Mesuré le 09/09/2026, chaque ligne par un appel réel :

| Fonction | Ce qui la fait tourner | Coût |
|---|---|---|
| Chat, lecture d’image | votre clé Google (Gemini) | gratuit |
| Fabrication d’image | la même clé, route `/v1/images/generations` du routeur | gratuit |
| Recherche Web | DuckDuckGo | gratuit, sans compte |
| Lire à haute voix, dictée | voix du navigateur, Whisper local du conteneur | gratuit, sans clé |
| **Fabrication de vidéo** | modèle ouvert **Wan 2.1 VACE 1,3 B** (Apache 2.0) sur une machine Modal louée à la minute | **crédit Modal de 30 $/mois, carte bancaire exigée** ; au-delà du crédit, Modal facture jusqu’à votre limite de dépense |

**Pourquoi la vidéo est à part.** Aucun service de fabrication de vidéo n’est gratuit et
hébergé en septembre 2026. Le Studio fait donc tourner un modèle ouvert sur une carte
graphique louée. Un seul modèle couvre les trois demandes : décrire une scène, partir d’une
image, finir sur une autre, et garder un personnage ressemblant grâce à une image de
référence. La page `/video` du Sandbox affiche en permanence ce qui a été dépensé dans le
mois, et **refuse de lancer un clip avant** qu’il fasse dépasser le plafond
(`VIDEO_BUDGET_USD_PAR_MOIS`, 20 $ par défaut).

**Carte bancaire et facturation — relevé du 11/09/2026.** Modal affiche « 30 $ de crédit
gratuit par mois » pour son offre Starter ([pricing](https://modal.com/pricing)), mais
**exige un moyen de paiement** pour utiliser la plateforme
([billing](https://modal.com/docs/guide/billing)). Au-delà du crédit, Modal **facture**,
jusqu’à la limite de dépense du compte ; par défaut, cette limite vaut la limite d’usage
moins le crédit ([budgets](https://modal.com/docs/guide/budgets)). Réglez-la au plus bas dans
<https://modal.com/settings/usage>. Aucune source officielle ne mentionne de palier « sans
carte » : l’audit du 11/09/2026 citait 5 $ sans carte, ce relevé ne le retrouve pas.

Le Studio **ne lit pas** votre compte Modal. Son plafond de 20 $ ne compte que ses propres
clips vidéo, pas le reste du Sandbox ni d’autres usages de Modal, et le crédit de 30 $ que
la page affiche est celui que vous déclarez (`MODAL_CREDIT_MENSUEL_USD`) : la page le dit.

**Ce que coûte un clip, mesuré le 09/09/2026.** Réglage le moins cher (3 s, « Rapide »,
carte L4) : 832×480, 49 images, **7 minutes d’attente**, **0,096 $**. À ce prix, les 30 $ de
crédit paieraient 312 clips. Le plafond du Studio en laisse passer **203** : 20 $ divisés par
0,096 $ en feraient 208, mais un clip n’est lancé que si son pire cas (40 minutes de L4
sans résultat, 0,53 $) tient encore sous le plafond. Calcul refait le 11/09/2026 avec la
règle du code (`budget_verifier` dans `sandbox-manager/video.py`). Le premier lancement d’un modèle prend 1 à
2 minutes de plus, le temps de le télécharger ; ensuite il reste sur un disque persistant.
Le petit modèle fait des plans presque fixes : la scène est juste, le mouvement est discret.

Attention si vous cherchez « mieux » : les licences de **MiniMax H3** et de **HunyuanVideo**
excluent l’Union européenne, le Royaume-Uni et la Corée du déploiement local. Wan est sous
Apache 2.0, sans restriction de territoire. La page `/video` affiche la licence et le
territoire du modèle **à côté du choix de qualité**, là où l’on décide.

### Ce qui est ouvert, ce qui ne l’est pas

Free AI Studio **assemble des paliers gratuits** ; il n’est pas un studio open source. Pour
chaque fonction, qui fait le travail, et pourriez-vous le faire tourner vous-même ?
Licences relevées le 11/09/2026 sur les fiches officielles des modèles.

| Fonction | Fournisseur, modèle | Nature | Licence |
|---|---|---|---|
| Chat (1er choix) | Google, `gemini-3.5-flash-lite` | API propriétaire, palier gratuit | poids non publiés ; conditions de l’API Gemini |
| Chat (1er secours) | OpenRouter, `openrouter/free` | API tierce, palier gratuit ; le modèle servi change d’une requête à l’autre, ouvert ou non | celle du modèle routé, variable |
| Chat (2e secours, si activé) | Groq, `openai/gpt-oss-20b` | modèle ouvert exécuté à distance, par un service propriétaire | Apache 2.0 ([fiche](https://huggingface.co/openai/gpt-oss-20b)) |
| Lecture d’image | Google, modèle du chat | API propriétaire, palier gratuit | poids non publiés |
| Fabrication d’image | Google, `gemini-3.1-flash-lite-image` | API propriétaire, palier gratuit | poids non publiés |
| Recherche Web | DuckDuckGo | service tiers, sans compte | conditions de DuckDuckGo |
| Lire à haute voix | voix du navigateur | exécuté localement, par le navigateur | celle du navigateur |
| Dictée | Whisper, dans le conteneur | modèle ouvert exécuté localement | MIT ([licence](https://github.com/openai/whisper/blob/main/LICENSE)) |
| Vidéo | Wan 2.1 VACE 1,3 B ou 14 B, sur Modal (ou Kaggle) | modèle ouvert exécuté à distance, sur une machine louée | Apache 2.0, aucune restriction de territoire ([fiche](https://huggingface.co/Wan-AI/Wan2.1-VACE-1.3B)) |

Seules la dictée et la voix ne dépendent d’aucun tiers. La vidéo et le 2e secours du chat
reposent sur des modèles ouverts que vous pourriez faire tourner vous-même, avec la carte
graphique qu’il faut. Tout le reste dépend d’un fournisseur qui peut changer son offre.

### Mettre à jour

Bouton **« Mettre à jour »** sur `http://127.0.0.1:8010/studio`. Il compare votre version à
celle du dépôt, puis récupère la dernière et reconstruit les services.

Un conteneur ne peut pas se reconstruire lui-même, et donner à une page web les pleins
pouvoirs sur Docker serait une mauvaise affaire. Le bouton dépose donc une demande, et un
petit veilleur qui tourne sous votre compte (lancé par `start.ps1`) fait le travail avec vos
propres identifiants git. Si le veilleur n’est pas là, le bouton vous dit exactement quoi
faire : **double-cliquer `mettre-a-jour.cmd`**, à la racine du dossier.
