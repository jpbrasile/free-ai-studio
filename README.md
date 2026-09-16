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

Cinq gestes. Aucun terminal, aucun assistant de code.

1. **Docker Desktop** — <https://www.docker.com/products/docker-desktop/>. Installer,
   redémarrer si on le demande, puis **ouvrir Docker Desktop** et attendre que la baleine
   en bas à gauche soit verte. C'est le seul vrai prérequis : sans lui, rien ne tourne.
   Il demande Windows 10 22H2 ou Windows 11 23H2 (ou plus récent), en 64 bits : sinon,
   **Windows Update** d'abord. `demarrer.cmd` le vérifie.
   S'il affiche **« Virtualization support not detected »**, ce n'est pas votre
   installation qui est en cause et ce n'est pas une impasse :
   [docs/DEPANNAGE.md](docs/DEPANNAGE.md) donne les trois causes possibles, dans l'ordre,
   avec le chemin à cliquer pour chacune.
2. **Git pour Windows** — <https://git-scm.com/download/win>. Suivant jusqu'au bout.
   Sert uniquement à ce que le bouton « Mettre à jour » sache quelle version vous avez.
   Si VS Code était déjà ouvert, le fermer et le rouvrir : il ne cherche Git qu'à son
   démarrage.
3. **VS Code** — <https://code.visualstudio.com/>. Installer avec les choix proposés. Il
   sert au geste suivant, et plus tard à ouvrir un assistant de code si vous le souhaitez.
4. **Récupérer le dossier.** Dans VS Code : menu **Affichage** → **Palette de commandes**,
   taper `Git: Clone`, coller `https://github.com/jpbrasile/free-ai-studio.git`, et
   **désigner le dossier parent** — `Documents`, pas un dossier `free-ai-studio` déjà
   créé : git fabrique lui-même le sous-dossier à son nom. Deux dossiers du même nom
   partagent le même projet Docker, ce qui casse le chat plus tard.
   *(Sans Git ni VS Code : bouton vert « Code » sur GitHub → « Download ZIP » → extraire.
   Tout marchera sauf le bouton de mise à jour, et l'installateur vous le dira.)*
5. **Double-cliquer `demarrer.cmd`**, à la racine du dossier.

`demarrer.cmd` vérifie l'ordinateur avant d'agir : version de Windows, Docker installé,
Docker **démarré** (ce n'est pas la même chose, et c'est ce qui manque neuf fois sur dix),
ports 3000/8010/8020 libres, dossier complet. Quand quelque chose manque, il dit quoi faire
et ouvre la page de téléchargement — il ne montre jamais une erreur technique. Quand Docker
ne démarre pas, il ne se contente pas de dire « ouvrez-le » : il lit l'état réel de la
virtualisation et nomme la cause — micrologiciel éteint, composants Windows non cochés,
WSL en panne, ou Docker simplement pas lancé. Puis il crée
les réglages, fabrique les mots de passe internes au hasard, construit les services, lance
le veilleur de mise à jour, attend que la page **et le chat** répondent vraiment, et ouvre
la page. Si le chat tourne sans répondre sur le port 3000, il le redémarre.

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

Windows PowerShell. Sur un Windows neuf, la politique d'exécution des scripts (*Restricted*
par défaut) bloque `.\install.ps1` lancé tel quel ; d'où la forme ci-dessous. Pour un
débutant, le chemin Windows reste le double-clic sur `demarrer.cmd`.

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
powershell -ExecutionPolicy Bypass -File .\start.ps1
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
Free AI Auto : Gemini Flash-Lite (palier gratuit) → OpenRouter `openrouter/free` → Groq (si activé)
Free AI Max  : Gemini 3.8 Flash (palier gratuit) → puis la même chaîne qu'Auto
```

Le chat propose deux choix : **Free AI Auto** pour l'usage courant, **Free AI Max** pour les questions difficiles. Max essaie d'abord Gemini 3.8 Flash, qui a son propre quota gratuit (Google le compte par modèle) ; Auto n'y touche jamais. Le manager tente les fournisseurs éligibles dans cet ordre (`FREE_PROVIDER_ORDER`). Quand le premier a épuisé son quota, **le basculement n’est pas silencieux** : la réponse suivante du chat commence par une ligne qui le dit, et les pages `/studio` et `/diagnostic` affichent le service en pause, la limite annoncée par le fournisseur et l’heure de reprise.

**Dessins SVG.** Demandez par exemple « fais-moi un cube en SVG ». Sous la réponse, le dessin s'affiche, suivi d'un lien « Télécharger » qui enregistre le fichier `.svg`. Les 200 derniers dessins sont gardés dans `config/dessins/`.

**Interpréteur de code : coupé par le Studio.** Avec cet interrupteur, Open WebUI demande au modèle d'écrire du Python qu'il exécute dans le navigateur. Les modèles gratuits le pilotent mal : le 14/09/2026, un dessin demandé a fini en bulle vide. Le Studio le coupe une fois, au démarrage. Le bouton « Exécuter » d'un bloc de code reste. Pour le remettre : Panneau d'administration, puis « Exécution de code ».

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

Sans terminal : ouvrir <http://127.0.0.1:8010/diagnostic>. La page teste la chaîne maillon
par maillon et dit où elle casse.

Avec un terminal, ou pour l'assistant de code, le test intégré :

- Linux/macOS : `./scripts/self-test.sh`
- Windows : `powershell -ExecutionPolicy Bypass -File .\scripts\self-test.ps1` (il demande
  Python, qu'un Windows neuf n'a pas : sans Python, la page `/diagnostic` suffit)

Le test ne consomme aucun crédit IA : il valide Docker Compose, l’état des conteneurs, `/health`, l’authentification du manager, l’accès local à Open WebUI et les choix proposés dans le chat.

### Mode gratuit strict

Le routage LLM livré est **Gemini Free Tier d’abord**, puis `openrouter/free`, puis Groq si activé. **Free AI Auto** utilise `gemini-3.5-flash-lite`. Le second choix du chat, **Free AI Max**, essaie d'abord `gemini-3.8-flash` (`GEMINI_MAX_MODEL`), avec la même clé mais son propre quota, puis la chaîne d'Auto ; `ENABLE_GEMINI_MAX=false` le retire du chat. Le Studio ne peut pas déterminer automatiquement si une clé Google/Groq est rattachée à un niveau gratuit ou payant : pour une garantie ultra-stricte, passez `ALLOW_FREE_TIER_ACCOUNTS=false`, ce qui conserve uniquement les routes explicitement zéro coût comme `openrouter/free`.

### Fonctions média

Mesuré le 09/09/2026, chaque ligne par un appel réel :

| Fonction | Ce qui la fait tourner | Coût |
|---|---|---|
| Chat, lecture d’image | votre clé Google (Gemini) | gratuit |
| Fabrication d’image | la même clé, route `/v1/images/generations` du routeur | gratuit |
| Recherche Web | DuckDuckGo | gratuit, sans compte |
| Lire à haute voix (16/09/2026) | deux voix Piper dans le routeur du Studio, sur le processeur : « siwis » en français, « norman » en anglais, choisies phrase par phrase ; le texte ne quitte pas le PC | gratuit, sans clé |
| Dictée (15/09/2026) | au choix, sur la page d’accueil du Studio : « Groq si possible » (`whisper-large-v3`, avec une clé Groq ; sans clé, ou si Groq refuse, l’ordinateur prend le relais) ou « Sur cet ordinateur » (Whisper `small` sur le processeur, la voix ne quitte pas le PC). La langue parlée est reconnue toute seule ; sur l’ordinateur, parmi le français et l’anglais (`DICTEE_LANGUES`) | gratuit |
| **Fabrication de vidéo** | modèle ouvert **Wan 2.1 VACE 1,3 B** (Apache 2.0) sur une machine Modal louée à la minute | **crédit Modal de 30 $/mois, carte bancaire exigée** ; au-delà du crédit, Modal facture jusqu’à votre limite de dépense |
| **Chanson** (15/09/2026 ; essayée en réel sur Kaggle et Modal, pas Colab) | modèle ouvert **YuE2-3B** (**CC BY-NC 4.0, non commercial**) : sur Modal (carte L4 louée), ou sur la carte T4 gratuite de Kaggle ou de Colab | Modal : **estimé** 1,04 $ de l’heure (carte, processeur et 24 Gio de mémoire, prix relevés le 15/09/2026), 0,52 $ au pire par chanson, 0,08 $ compté pour l’essai du 15/09, plafond à part de 5 $/mois ; Kaggle et Colab : gratuit |

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
carte L4) : 832×480, 49 images, **7 minutes d’attente**. Le premier chiffre publié,
0,096 $, est le prix de la carte seule pendant 432 s. Modal facture aussi le processeur et la
mémoire ; le compteur les ajoute depuis le 15/09/2026, et la même durée compte alors
**0,117 $**. À ce prix, les 30 $ de crédit paieraient 256 clips. Le plafond du Studio en
laisse passer **166** : un clip n’est lancé que si son pire cas (40 minutes de L4 sans
résultat, 0,65 $) tient encore sous le plafond. Calcul refait le 15/09/2026 avec la
règle du code (`budget_verifier` dans `sandbox-manager/video.py`). Le premier lancement d’un modèle prend 1 à
2 minutes de plus, le temps de le télécharger ; ensuite il reste sur un disque persistant.
Le petit modèle fait des plans presque fixes : la scène est juste, le mouvement est discret.

Attention si vous cherchez « mieux » : les licences de **MiniMax H3** et de **HunyuanVideo**
excluent l’Union européenne, le Royaume-Uni et la Corée du déploiement local. Wan est sous
Apache 2.0, sans restriction de territoire. La page `/video` affiche la licence et le
territoire du modèle **à côté du choix de qualité**, là où l’on décide.

**La chanson** (page `/chanson` du Sandbox, carte « Chanson » de `/studio`). Des paroles et
un style : YuE2-3B compose une partition, puis la chante, voix et instruments, jusqu’à
3 minutes en 48 kHz stéréo. Sa fiche annonce l’anglais et le chinois, pas le français.
Trois endroits où le lancer :
- **Modal**, carte L4 : le pipeline officiel, tel quel. Le compteur ajoute cette fois le
  processeur et la mémoire, que Modal facture en plus de la carte. Une chanson n’est lancée
  que si son pire cas (30 minutes) tient sous le plafond `CHANSON_BUDGET_USD_PAR_MOIS`
  (5 $ par défaut, à part des 20 $ de la vidéo) : au pire 9 chansons par mois. Essayé le
  15/09/2026, premier lancement : 43 secondes de chanson en moins de 5 minutes, image et
  téléchargement du modèle compris, comptées 0,08 $ par le Studio. La facture de Modal
  elle-même n’a pas été relevée.
- **Kaggle** : une ou deux cartes T4, gratuites. Le pipeline officiel refuse cette carte, faute
  de bfloat16. Le script applique alors les correctifs du carnet Kaggle public « YuE2-3B -
  Frontier Full-Song Music Generation » (AIQUEST Academy, Apache 2.0) : float16, attention
  SDPA, intégration en float32, décodage par tuiles. Ce chemin n’est pas celui des auteurs du
  modèle. Essayé le 15/09/2026 : deux cartes T4, une minute de chanson en 6 minutes. Kaggle
  arrête lui-même le notebook au bout de 90 minutes (`CHANSON_KAGGLE_TIMEOUT_SECONDS`). Coupé
  quand le Studio est partagé, comme la vidéo.
- **Colab** : le Studio fabrique un carnet avec les paroles ; vous l’importez dans Colab et le
  lancez sur votre compte Google, carte T4 gratuite, avec les mêmes correctifs.

La licence CC BY-NC 4.0 des poids est affichée **à côté du choix de l’endroit**. Ce qu’elle
permet de faire des chansons produites n’est pas tranché par le Studio : pour un usage
commercial, lisez la [fiche du modèle](https://huggingface.co/m-a-p/YuE2-3B).

### Ce qui est ouvert, ce qui ne l’est pas

Free AI Studio **assemble des paliers gratuits** ; il n’est pas un studio open source. Pour
chaque fonction, qui fait le travail, et pourriez-vous le faire tourner vous-même ?
Licences relevées le 11/09/2026 sur les fiches officielles des modèles.

| Fonction | Fournisseur, modèle | Nature | Licence |
|---|---|---|---|
| Chat, Free AI Auto | Google, `gemini-3.5-flash-lite` | API propriétaire, palier gratuit | poids non publiés ; conditions de l’API Gemini |
| Chat, Free AI Max | Google, `gemini-3.8-flash`, puis la chaîne d’Auto | API propriétaire, palier gratuit, quota à part | poids non publiés ; conditions de l’API Gemini |
| Chat (1er secours) | OpenRouter, `openrouter/free` | API tierce, palier gratuit ; le modèle servi change d’une requête à l’autre, ouvert ou non | celle du modèle routé, variable |
| Chat (2e secours, si activé) | Groq, `openai/gpt-oss-20b` | modèle ouvert exécuté à distance, par un service propriétaire | Apache 2.0 ([fiche](https://huggingface.co/openai/gpt-oss-20b)) |
| Lecture d’image | Google, modèle du chat | API propriétaire, palier gratuit | poids non publiés |
| Fabrication d’image | Google, `gemini-3.1-flash-lite-image` | API propriétaire, palier gratuit | poids non publiés |
| Recherche Web | DuckDuckGo | service tiers, sans compte | conditions de DuckDuckGo |
| Lire à haute voix (16/09/2026) | Piper 1.8.0 et deux voix, `fr_FR-siwis-medium` et `en_US-norman-medium`, dans le routeur du Studio, sur le processeur | modèles ouverts exécutés localement | Piper : GPL-3.0-or-later ([code](https://github.com/OHF-Voice/piper1-gpl)). Voix française : entraînée sur « The SIWIS French Speech Synthesis Database » (J. Yamagishi, P.-E. Honnet, P. Garner, A. Lazaridis, université d’Édimbourg, 2017, [doi:10.7488/ds/1705](https://doi.org/10.7488/ds/1705)), **CC BY 4.0** : usage commercial permis, en citant la source ([fiche de la voix](https://huggingface.co/rhasspy/piper-voices/blob/main/fr/fr_FR/siwis/medium/MODEL_CARD)). Voix anglaise : entraînée de zéro sur environ 15,5 h d’enregistrements [LibriVox](https://librivox.org), **domaine public** ([fiche de la voix](https://huggingface.co/rhasspy/piper-voices/blob/main/en/en_US/norman/medium/MODEL_CARD)) |
| Dictée « sur cet ordinateur », et repli quand Groq refuse | Whisper `small`, dans le routeur du Studio, sur le processeur | modèle ouvert exécuté localement | MIT ([fiche](https://huggingface.co/Systran/faster-whisper-small), [licence](https://github.com/openai/whisper/blob/main/LICENSE)) |
| Dictée « Groq si possible », avec une clé Groq | Groq, `whisper-large-v3` | modèle ouvert exécuté à distance, par un service propriétaire ; votre voix part chez Groq | Apache 2.0 ([fiche](https://huggingface.co/openai/whisper-large-v3)) |
| Vidéo | Wan 2.1 VACE 1,3 B ou 14 B, sur Modal (ou Kaggle) | modèle ouvert exécuté à distance, sur une machine louée | Apache 2.0, aucune restriction de territoire ([fiche](https://huggingface.co/Wan-AI/Wan2.1-VACE-1.3B)) |
| Chanson (15/09/2026) | m-a-p, YuE2-3B et son décodeur YuE2-Vae, sur Modal, Kaggle ou Colab | modèle ouvert exécuté à distance, sur une machine louée ou prêtée | poids : **CC BY-NC 4.0, usage non commercial**, aucune restriction de territoire ; code `yue2_infer` : Apache 2.0 ([fiche](https://huggingface.co/m-a-p/YuE2-3B)). Correctifs T4 repris du carnet Kaggle d’AIQUEST Academy, Apache 2.0 |

Seules la voix, et la dictée « sur cet ordinateur », ne dépendent d’aucun tiers. La vidéo, la chanson et le 2e secours du chat
reposent sur des modèles ouverts que vous pourriez faire tourner vous-même, avec la carte
graphique qu’il faut. Tout le reste dépend d’un fournisseur qui peut changer son offre.

### Mettre à jour

Bouton **« Mettre à jour »** sur `http://127.0.0.1:8010/studio`. Il compare votre version à
celle du dépôt, puis récupère la dernière et reconstruit les services.

Un conteneur ne peut pas se reconstruire lui-même, et donner à une page web les pleins
pouvoirs sur Docker serait une mauvaise affaire. Le bouton dépose donc une demande, et un
petit veilleur qui tourne sous votre compte fait le travail avec vos propres identifiants
git. `demarrer.cmd` le lance, sans fenêtre ; il pose alors un raccourci dans le dossier
Démarrage de Windows et repart seul à chaque ouverture de session. Vous n’avez rien à
lancer : cliquer suffit. Il ne tourne jamais en double.

Si le veilleur n’est pas là, le bouton vous dit quoi faire : **double-cliquer une fois
`demarrer.cmd`**, qui le relance, puis recliquer. `mettre-a-jour.cmd`, à la racine du
dossier, fait la même mise à jour à la main.

Pour qu’il ne reparte plus avec Windows : touches Windows+R, taper `shell:startup`, et
supprimer le raccourci « Free AI Studio - mises a jour ».
