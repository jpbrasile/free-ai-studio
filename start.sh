#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f .env ]; then
  echo "ERREUR: .env absent. Lancez ./install.sh"
  exit 1
fi

# Sous quel système le Studio est lancé. Le service qui décide tourne dans un
# conteneur Linux quelle que soit la machine : il ne PEUT pas le deviner. Sans
# cette ligne, le message « il manque les 34 Go » nommerait un script
# PowerShell à quelqu'un qui n'a pas PowerShell. `scripts/demarrer.ps1` pose
# "windows" de la même façon.
export STUDIO_LANCEUR=linux

# --- La carte de la maison, si elle existe ------------------------------------
# La surcouche docker-compose.gpu.yml n'est ajoutée QUE si une carte répond :
# une réservation `driver: nvidia` sur une machine sans carte fait ÉCHOUER
# `docker compose up`, et le débutant sans carte -- le cas le plus courant --
# ne doit jamais rencontrer ce message. C'est le pendant des lignes 357-401 de
# `scripts/demarrer.ps1` ; les deux lanceurs doivent rester copie conforme, et
# `tests/test_gpu_local.py` le vérifie.
#
# EXÉCUTÉ SOUS LINUX le 20/09/2026, dans un conteneur de cette machine
# (`Linux 6.18.33.2-microsoft-standard-WSL2`, `--gpus all`) : `nvidia-smi` y
# répond « NVIDIA GeForce RTX 4090 », la surcouche est ajoutée, les poids
# absents donnent les trois bonnes lignes, et une carte muette laisse le
# lanceur sur le seul `docker-compose.yml`. Reste à mesurer : un hôte Linux
# dont le shell et le moteur Docker partagent le disque -- de là seulement, le
# `compose up` réel et le clip fait à la maison (PLAN.md, étape 9, GPU-1).
#
# ATTENTION, mesuré le même jour : le runtime NVIDIA injecte `nvidia-smi` dans
# l'image, mais en musl (Alpine) le binaire ne s'exécute pas. D'où le test du
# CODE DE RETOUR ci-dessous, et jamais de la présence du fichier : tester la
# présence donnerait une machine qui se croit équipée et qui échoue au clip.
compose_args=(-f docker-compose.yml)
carte=""
if command -v nvidia-smi >/dev/null 2>&1; then
  carte="$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -n 1 | sed 's/^ *//; s/ *$//')" || carte=""
fi

if [ -n "$carte" ]; then
  compose_args+=(-f docker-compose.gpu.yml)
  echo "Carte graphique vue : $carte"

  # Les 34 Go de poids du modèle vidéo. S'ils sont DÉJÀ dans le cache Hugging
  # Face du compte -- c'est le cas de quiconque a déjà téléchargé un modèle à
  # la main -- on monte ce dossier au lieu d'en remplir un deuxième. Mesure du
  # 19/09 sous Windows : ce téléchargement a pris presque une heure et une
  # reprise après blocage ; le refaire pour rien serait de la peine pure.
  # La variable est posée dans l'environnement de CE processus : le `.env` de
  # l'utilisateur n'est jamais modifié.
  #
  # LA VARIABLE PASSE D'ABORD (20/09/2026). `docker-compose.gpu.yml` monte
  # `${GPU_MODELES_DIR:-<cache du profil>}` : la variable d'abord, le cache
  # ensuite. Ce lanceur faisait l'inverse -- il ÉCRASAIT une valeur déjà posée.
  # Quelqu'un qui garde ses 34 Go hors du profil, ce que le compose prévoit noir
  # sur blanc, voyait son choix remplacé sans un mot, et le clip partait sur une
  # machine louée en annonçant des poids absents qui étaient sur son disque.
  cache_hf="$HOME/.cache/huggingface"
  if [ -n "${GPU_MODELES_DIR:-}" ]; then
    modeles="$GPU_MODELES_DIR"
    echo "   Modèles pris là où vous les gardez : $modeles"
  elif [ -d "$cache_hf/hub" ]; then
    modeles="$cache_hf"
    export GPU_MODELES_DIR="$cache_hf"
    echo "   Modèles déjà téléchargés réutilisés : $cache_hf"
  else
    modeles="$cache_hf"
  fi

  # Le bac à sable qui fabrique les clips n'a pas internet -- par construction
  # -- donc il ne pourra pas chercher les poids tout seul. On le dit ici, une
  # fois, au lieu de laisser un clip échouer plus tard sur un message
  # incompréhensible. Cherchés LÀ OÙ ILS SERONT MONTÉS, et non dans le cache du
  # profil : sinon le message dit le contraire de ce qui va se passer.
  poids="$modeles/hub/models--Wan-AI--Wan2.2-TI2V-5B-Diffusers"
  if [ ! -d "$poids" ]; then
    echo "   Carte présente, mais le modèle vidéo (34 Go) n'est pas téléchargé."
    echo "   Les clips partiront sur une machine louée tant qu'il manque."
    echo "   Pour le descendre une fois : ./scripts/telecharger-modele-video.sh"
  fi
fi

# `--build` comme sous Windows : le code des services est COPIÉ dans les
# images, il n'est pas monté. Sans cette option, un dépôt mis à jour continue
# de tourner sur l'image d'avant -- y compris sur la détection de carte qui
# vient d'être ajoutée ici. Une reconstruction sans changement est servie par
# le cache de Docker et ne coûte que quelques secondes.
docker compose "${compose_args[@]}" up -d --build
echo
docker compose "${compose_args[@]}" ps
echo
echo "Free AI Studio / Open WebUI : http://localhost:3000"
echo "Sandbox : http://127.0.0.1:8020"
echo "Vérification : ./scripts/self-test.sh"

printf "\nFree AI Studio (débutant) : http://127.0.0.1:8010/studio\nChat : http://localhost:3000\n"
