# Installation guidée — débutant


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

## B. Préparer Free AI Studio

Copier `.env.example` vers `.env`.

Linux/macOS :

```bash
cp .env.example .env
```

Windows PowerShell :

```powershell
Copy-Item .env.example .env
```

## C. Ajouter les clés API

Ouvrir `.env` dans VS Code.

Commencer idéalement par :

- `GEMINI_API_KEY`
- `GROQ_API_KEY`
- `OPENROUTER_API_KEY`

Les liens officiels sont dans `API_KEYS.md`.

Ne partagez jamais le fichier `.env`.

## D. Lancer Open WebUI

Linux/macOS :

```bash
./install.sh
./start.sh
```

Windows :

```powershell
.\install.ps1
.\start.ps1
```

Puis ouvrir :

http://localhost:3000

## E. Premier démarrage

Open WebUI peut demander de créer un compte administrateur local au premier lancement.

Les clés API présentes dans `.env` ne sont volontairement pas toutes injectées directement dans le navigateur. Les futures intégrations/pipe doivent les consommer côté serveur.

## F. Vérifier

Linux/macOS :

```bash
./scripts/diagnose.sh
```

Vous devez voir Open WebUI en fonctionnement.

## G. Étape suivante

Une fois le chat minimal validé :

1. connecter les fournisseurs compatibles,
2. ajouter le routeur gratuit,
3. installer ComfyUI si génération image/vidéo nécessaire,
4. ajouter éventuellement un backend GPU distant.


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
