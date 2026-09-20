#!/usr/bin/env bash
# Télécharge une seule fois les poids du modèle vidéo de la maison (34 Go).
#
# Jumeau exact de `scripts/telecharger-modele-video.ps1`, pour Linux et macOS.
# Les deux doivent viser le MÊME dossier que `docker-compose.gpu.yml`, sinon
# les 34 Go atterrissent là où personne ne les lit -- une heure de ligne pour
# rien, et le Studio continue de dire que les poids manquent.
# `tests/test_gpu_local.py` garde les trois fichiers alignés.
#
# Pourquoi il faut un script pour ça : le bac à sable qui fabrique les clips
# est sur un réseau SANS internet -- c'est ce qui rend sûr d'y exécuter du code
# quelconque. Il ne peut donc pas télécharger les poids lui-même. Ce script
# lance un conteneur qui a le droit d'aller sur le réseau, et qui écrit dans le
# même dossier que le bac à sable lira ensuite.
#
# EXÉCUTÉ SOUS LINUX le 20/09/2026, dans un conteneur de cette machine : le
# chemin « image absente » rend son message et sort 2 sans rien télécharger, et
# la commande assemblée porte des chemins Linux natifs et le compte de la
# personne (`--user <uid>:<gid>`). Ce qui reste à mesurer : le `docker run` réel
# depuis un hôte Linux -- depuis un conteneur, le moteur ne sait pas résoudre
# les dossiers à monter, qui sont ceux du conteneur et non les siens. Le
# téléchargement lui-même, lui, a bien eu lieu, sous Windows : 34,20 Go, 62
# fichiers, 21 min 51 s dans un dossier vide (20/09).
#
# À lancer depuis le dossier du Studio :
#   ./scripts/telecharger-modele-video.sh
set -euo pipefail
cd "$(dirname "$0")/.."
racine="$PWD"

echo
echo "  Modèle vidéo de la maison -- téléchargement unique"
echo "  Environ 34 Go. Comptez une demi-heure à une heure selon la ligne."
echo

# EXACTEMENT le dossier que monte docker-compose.gpu.yml : GPU_MODELES_DIR s'il
# est posé, sinon le cache Hugging Face du compte. Le dernier recours était le
# volume Docker `modeles-gpu` et il ne l'est plus : depuis que le compose prend
# le cache du compte par défaut, télécharger dans le volume ferait descendre
# 34 Go dans un dossier que PLUS PERSONNE ne lit.
cache_hf="$HOME/.cache/huggingface"
if [ -n "${GPU_MODELES_DIR:-}" ]; then
  cible="$GPU_MODELES_DIR"
else
  cible="$cache_hf"
  mkdir -p "$cible"
fi
echo "  Destination : $cible"

# L'image du bac à sable GPU porte déjà huggingface_hub : rien à installer.
image="free-ai-studio-sandbox-worker-gpu"
if ! docker image inspect "$image" >/dev/null 2>&1; then
  echo
  echo "  L'image du bac à sable GPU n'existe pas encore."
  echo "  Lancez d'abord le Studio (./start.sh) sur une machine qui a une carte."
  exit 2
fi

# Différence assumée avec le `.ps1` : là-bas le conteneur tourne en root parce
# que le cache appartient à l'utilisateur Windows et que le compte non
# privilégié de l'image ne peut pas toujours y écrire. Ici, root écrirait des
# fichiers root DANS le dossier personnel, que l'utilisateur ne pourrait plus
# effacer sans sudo. On tourne donc sous son propre compte, et HOME est posé
# sur le cache parce que cet identifiant n'existe pas dans l'image.
# `|| code=$?` et pas `code=$?` sur la ligne suivante : avec `set -e`, un
# téléchargement qui échoue arrêterait le script AVANT qu'on ait lu son code,
# et la personne n'aurait aucun message. C'est le genre de détail qui ne se
# voit que le jour où ça rate.
code=0
docker run --rm \
  -v "${cible}:/cache/huggingface" \
  -v "${racine}/scripts:/scripts:ro" \
  -e HF_HOME=/cache/huggingface \
  -e HOME=/cache/huggingface \
  -e HF_HUB_DISABLE_XET=1 \
  -e PYTHONUNBUFFERED=1 \
  --user "$(id -u):$(id -g)" \
  "$image" python /scripts/telecharger_modele_video.py || code=$?

if [ "$code" -eq 0 ]; then
  echo
  echo "  Fait. Le prochain clip partira sur la carte de cet ordinateur, gratuitement."
else
  echo
  echo "  Le téléchargement a échoué (code $code). Relancez : il reprend où il s'est arrêté."
fi
exit "$code"
