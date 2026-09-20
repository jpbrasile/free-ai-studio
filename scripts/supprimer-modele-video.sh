#!/usr/bin/env bash
# Rend les 34 Go du modèle vidéo, quand on ne veut plus fabriquer de clips ici.
#
# Jumeau exact de `scripts/supprimer-modele-video.ps1` ;
# `tests/test_gpu_local.py` garde les deux alignés.
#
# POURQUOI CE N'EST PAS AUTOMATIQUE, et ne le sera pas :
#   1. le dossier visé n'appartient pas au Studio. C'est le cache Hugging Face
#      du COMPTE -- celui que lisent aussi ComfyUI, un carnet Jupyter, ou tout
#      autre outil d'IA de la personne. Y passer un balai tout seul, c'est
#      effacer le travail de quelqu'un d'autre sur sa propre machine ;
#   2. revenir en arrière coûte 22 minutes de ligne, mesurées le 20/09
#      (34,20 Go, 24,9 Mio/s). Un geste de trois secondes qui en coûte
#      vingt-deux se DEMANDE ;
#   3. aucun disque n'est en danger : 34 Go sur un disque de 1 862 Go.
#
# Ne supprime que sur un « oui » tapé à la main, et ne supprime QUE le dossier
# du modèle vidéo -- jamais le cache entier, qui contient les modèles des
# autres outils.
#
#   ./scripts/supprimer-modele-video.sh
#   ./scripts/supprimer-modele-video.sh --oui   (pour un script appelant)
set -euo pipefail
cd "$(dirname "$0")/.."

oui=0
[ "${1:-}" = "--oui" ] && oui=1

# Même règle que `scripts/telecharger-modele-video.sh` et que le compose.
cible="${GPU_MODELES_DIR:-$HOME/.cache/huggingface}"
modele="$cible/hub/models--Wan-AI--Wan2.2-TI2V-5B-Diffusers"

echo
echo "  Modèle vidéo de la maison -- suppression"

if [ ! -d "$modele" ]; then
  echo "  Rien à supprimer : $modele n'existe pas."
  echo "  Les clips partent déjà sur une machine louée."
  exit 0
fi

taille="$(du -sh "$modele" 2>/dev/null | cut -f1)"
echo
echo "  À supprimer : $modele"
echo "  $taille"
echo
echo "  Ce qui change après : les clips repartiront sur une machine louée,"
echo "  payante, au lieu de la carte de cet ordinateur."
echo "  Pour revenir en arrière : ./scripts/telecharger-modele-video.sh,"
echo "  environ 22 minutes de ligne (mesure du 20/09)."
echo

if [ "$oui" -eq 0 ]; then
  # `read` et non une touche : on veut le mot écrit, pas un geste réflexe.
  # Sans terminal (script appelant qui a oublié --oui), on n'efface pas.
  if [ ! -t 0 ]; then
    echo "  Pas de terminal pour poser la question. Rien n'a été touché."
    echo "  Relancez avec --oui si c'est bien ce que vous voulez."
    exit 1
  fi
  printf "  Tapez oui pour supprimer, n'importe quoi d'autre pour annuler : "
  read -r reponse
  case "$(echo "$reponse" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')" in
    oui|o|yes|y) ;;
    *) echo "  Annulé. Rien n'a été touché."; exit 0 ;;
  esac
fi

rm -rf "$modele"
echo
echo "  Supprimé, $taille rendus."
echo "  Le reste de votre cache Hugging Face n'a pas été touché."
