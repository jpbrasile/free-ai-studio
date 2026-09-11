# Installation guidée — débutant

Ce guide suit le README ; en cas d'écart, le README fait foi.


## 0. Vérifier les permissions de l'assistant

Avant l'installation, demander à l'assistant de codage :

> Vérifie si tu as accès aux fichiers, au terminal et au Web. Si une permission manque, explique-moi comment l'autoriser sans contourner les réglages de sécurité.

Sous Linux/macOS, il peut également lancer :

```bash
./scripts/check-assistant-capabilities.sh
```

L'accès Web est particulièrement utile pour vérifier la documentation officielle avant d'ajouter de nouveaux fournisseurs ou modèles.


## A. Installer Docker

Docker est la méthode recommandée par Open WebUI.

### Windows

1. Installer Docker Desktop :
   https://www.docker.com/products/docker-desktop/
2. Activer WSL2 si Docker Desktop le demande.
3. Redémarrer le PC si nécessaire.

### macOS

Installer Docker Desktop :

https://www.docker.com/products/docker-desktop/

### Linux

Installer Docker Engine avec la documentation officielle :

https://docs.docker.com/engine/install/

Puis vérifier :

```bash
docker --version
docker compose version
```

## B. Récupérer Free AI Studio

Le README, section « Installation sur l'ordinateur de quelqu'un qui n'écrira jamais une
commande », donne les gestes : Git et VS Code puis `Git: Clone`, ou le ZIP de GitHub.

Rien à copier à la main : le premier lancement crée `.env` à partir de `.env.example` et
fabrique au hasard les mots de passe internes.

## C. Lancer

Windows : double-cliquer `demarrer.cmd`, à la racine du dossier.

Linux/macOS :

```bash
./install.sh
./start.sh
```

Windows, en PowerShell (chemin de l'assistant de code). Sur un Windows neuf, la politique
d'exécution des scripts bloque `.\install.ps1` lancé tel quel :

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

## D. Coller une clé

Ouvrir <http://127.0.0.1:8010/cles> (bouton **Clés** du portail) et coller une clé Google
Gemini gratuite, créée sur <https://aistudio.google.com/apikey>. Le Studio l'essaie aussitôt
chez Google et dit si elle marche. Elle suffit pour écrire, lire une image et fabriquer une
image. OpenRouter et Groq, facultatifs, servent de secours : liens dans `docs/API_KEYS.md`.

Les clés collées restent sur cet ordinateur, dans le dossier `config` du Studio. Ne partagez
jamais ce dossier ni le fichier `.env`.

## E. Premier démarrage du chat

Ouvrir <http://localhost:3000>. Aucun compte à créer : avec `WEBUI_AUTH=false` (le défaut),
le chat s'ouvre directement, et son port n'écoute que sur cet ordinateur. En haut du chat,
deux choix : **Free AI Auto** pour le courant, **Free AI Max** pour les questions difficiles.

## F. Vérifier

Sans terminal : <http://127.0.0.1:8010/diagnostic> teste la chaîne maillon par maillon et dit
où elle casse.

Avec un terminal : `./scripts/self-test.sh` (Linux/macOS) ou
`powershell -ExecutionPolicy Bypass -File .\scripts\self-test.ps1` (Windows ; Python requis).

## G. Étape suivante

La recherche Web et la fabrication d'image sont déjà réglées : rouage sous la zone de saisie
du chat. La vidéo (<http://127.0.0.1:8020/video>) loue une carte graphique chez Modal, carte
bancaire exigée : lire le README avant. Les GPU distants (Modal, Kaggle, Colab) :
`docs/GPU_CLOUD.md`.


## NotebookLM — optionnel

Aucune installation ni clé API n'est nécessaire.

Après démarrage de Free AI Studio, la page d'aide locale est disponible sur :

```text
http://127.0.0.1:8010/notebooklm
```

Elle permet d'ouvrir NotebookLM dans le navigateur. Free AI Studio reste entièrement fonctionnel sans ce service.


## Portail débutant

Une fois les conteneurs démarrés, ouvrir en priorité :

```text
http://127.0.0.1:8010/studio
```

Ce portail évite d'exposer les choix de fournisseurs au débutant. Le Chat ouvre ensuite Open WebUI sur le port 3000.
