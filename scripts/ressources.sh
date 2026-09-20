#!/usr/bin/env bash
# Ce que le Studio occupe sur cet ordinateur, application par application --
# et comment en rendre une partie.
#
# Jumeau exact de `scripts/ressources.ps1` ; `tests/test_ressources.py` garde
# les deux alignés.
#
# POURQUOI CE N'EST PAS UN BOUTON DANS LA PAGE, et ce n'est pas un détail.
# Vider une image ou un volume Docker demande la prise `/var/run/docker.sock`.
# La donner au service qui sert les pages, c'est donner les pleins pouvoirs sur
# la machine à n'importe quelle page -- et au code que le bac à sable exécute,
# dont c'est tout le métier d'être quelconque. Le Studio ne la monte nulle part,
# et ce script est la réponse : la personne lance elle-même la commande, avec
# ses propres droits, le temps de la commande.
#
# NE SUPPRIME RIEN SANS ARGUMENT. Sans `--vider`, il mesure et il affiche.
#
#   ./scripts/ressources.sh                  voir ce qui est occupé
#   ./scripts/ressources.sh --vider <clé>    en rendre une ligne
#   ./scripts/ressources.sh --vider tout     toutes les lignes téléchargées
#   ... --oui                                sans poser la question (scripts)
set -uo pipefail
cd "$(dirname "$0")/.."

cle=""
oui=0
while [ $# -gt 0 ]; do
  case "$1" in
    --vider) cle="${2:-}"; shift 2 ;;
    --oui) oui=1; shift ;;
    -h|--help) sed -n '1,23p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Argument inconnu : $1"; exit 2 ;;
  esac
done

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker n'est pas installé sur cette machine : rien à mesurer."
  exit 2
fi

# --- tailles ---------------------------------------------------------------
# Docker rend ses tailles de volume en texte (« 2.144GB », « 819.1MB », « 40B »).
# On les ramène en octets pour pouvoir additionner.
en_octets() {
  echo "$1" | awk '
    /GB$/ { printf "%.0f", substr($0,1,length($0)-2) * 1000000000; exit }
    /MB$/ { printf "%.0f", substr($0,1,length($0)-2) * 1000000; exit }
    /kB$/ { printf "%.0f", substr($0,1,length($0)-2) * 1000; exit }
    /B$/  { printf "%.0f", substr($0,1,length($0)-1); exit }
    { print 0 }'
}
# `printf "%-22s"` compte des octets : avec un accent, la colonne se decale d'un
# cran et le tableau se lit de travers. `${#t}` compte des caracteres.
col() {
  local t="$1" n="$2" i
  printf '%s' "$t"
  i=${#t}
  while [ "$i" -lt "$n" ]; do printf ' '; i=$((i + 1)); done
}
lisible() {
  awk -v o="$1" 'BEGIN{
    if (o >= 1073741824) printf "%.2f Go", o/1073741824;
    else if (o >= 1048576) printf "%.1f Mo", o/1048576;
    else if (o > 0) printf "%.0f ko", o/1024;
    else printf "-";
  }'
}
taille_image()  { docker image inspect "$1" --format '{{.Size}}' 2>/dev/null || echo 0; }
taille_dossier() { [ -d "$1" ] && du -sb "$1" 2>/dev/null | cut -f1 || echo 0; }

# Un seul appel a `docker system df -v` : il est lent, et on en tire tous les
# volumes d'un coup.
TABLE_VOLUMES="$(docker system df -v 2>/dev/null | awk '/VOLUME NAME/{f=1;next} f && NF>=3 {print $1" "$NF}')"
taille_volume() {
  local t
  t="$(echo "$TABLE_VOLUMES" | awk -v n="$1" '$1==n {print $2; exit}')"
  [ -n "$t" ] && en_octets "$t" || echo 0
}

# --- où sont les choses ----------------------------------------------------
cache="${GPU_MODELES_DIR:-$HOME/.cache/huggingface}"
POIDS_VIDEO="$cache/hub/models--Wan-AI--Wan2.2-TI2V-5B-Diffusers"
# Le préfixe des volumes est celui du dossier du projet, comme docker compose
# le fabrique. On ne devine pas : on demande à docker.
PROJET="$(basename "$PWD" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9_-')"

o_poids=$(taille_dossier "$POIDS_VIDEO")
o_img_gpu=$(taille_image free-ai-studio-sandbox-worker-gpu)
o_img_chat=$(docker images --format '{{.Repository}}:{{.Tag}} {{.ID}}' | awk '/open-webui/{print $2}' | sort -u \
             | while read -r id; do docker image inspect "$id" --format '{{.Size}}' 2>/dev/null; done \
             | awk '{s+=$1} END{print s+0}')
o_img_studio=0
for i in free-ai-studio-free-tier-manager free-ai-studio-sandbox-manager free-ai-studio-sandbox-worker; do
  o_img_studio=$(( o_img_studio + $(taille_image "$i") ))
done
o_whisper=$(taille_volume "${PROJET}_whisper-modeles")
o_travail=$(taille_volume "${PROJET}_sandbox-data")
o_convers=$(taille_volume "${PROJET}_open-webui-data")

total_telecharge=$(( o_poids + o_img_gpu + o_img_chat + o_img_studio + o_whisper ))
total_travail=$(( o_travail + o_convers ))

# --- affichage -------------------------------------------------------------
echo
echo "  Place occupée par le Studio sur cet ordinateur"
echo
ligne() { printf "  "; col "$1" 22; printf " "; col "$2" 42; printf "%10s%s\n" "$3" "$4"; }
ligne "APPLICATION" "CE QUI EST SUR LE DISQUE" "TAILLE" ""
ligne "----------------------" "------------------------------------------" "----------" ""
ligne "Vidéo à la maison"  "les 34 Go du modèle vidéo"                 "$(lisible $o_poids)"     "   [video-poids]"
ligne "Vidéo à la maison"  "le bac à sable qui sait parler à la carte" "$(lisible $o_img_gpu)"   "   [video-image]"
ligne "Chat (Open WebUI)"  "l'application de conversation"             "$(lisible $o_img_chat)"  "   [chat]"
ligne "Écoute des voix"    "les modèles qui transcrivent"              "$(lisible $o_whisper)"   "   [whisper]"
ligne "Le Studio lui-même" "ses trois services"                        "$(lisible $o_img_studio)" "   [studio]"
echo
ligne "VOTRE TRAVAIL" "jamais proposé à la suppression ici" "" ""
ligne "Vos fichiers" "l'espace de travail du bac à sable" "$(lisible $o_travail)" ""
ligne "Vos conversations" "l'historique du chat" "$(lisible $o_convers)" ""
echo
echo "  Téléchargé : $(lisible $total_telecharge)     Votre travail : $(lisible $total_travail)"
echo "  (les images Docker partagent des morceaux : le total téléchargé est une borne haute)"
if command -v df >/dev/null 2>&1; then
  echo "  Disque : $(df -h . | awk 'NR==2{print $4" libres sur "$2}')"
fi
echo

if [ -z "$cle" ]; then
  echo "  Pour en rendre une ligne :  ./scripts/ressources.sh --vider <clé entre crochets>"
  echo "  Pour tout le téléchargé  :  ./scripts/ressources.sh --vider tout"
  echo
  exit 0
fi

# --- vidage ----------------------------------------------------------------
# Ce qu'on perd, et ce qu'il en coûte de revenir : dit AVANT la question, pour
# chaque ligne. Un vidage qui ne dit pas son prix n'est pas un choix.
case "$cle" in
  video-poids) quoi="les 34 Go du modèle vidéo"; perte="les clips partiront sur une machine louée tant qu'ils ne sont pas revenus"; retour="tout seul : au prochain clip demandé à la maison, le Studio les retélécharge (≈22 minutes) et vous propose d'attendre ou de louer" ;;
  video-image) quoi="le bac à sable qui parle à la carte"; perte="plus de vidéo à la maison tant qu'il n'est pas refait"; retour="quelques minutes au prochain ./start.sh" ;;
  chat)        quoi="l'application de conversation"; perte="le chat ne démarre plus tant qu'il n'est pas retéléchargé"; retour="quelques minutes au prochain ./start.sh" ;;
  whisper)     quoi="les modèles qui transcrivent"; perte="la première transcription sera plus lente"; retour="automatique, au premier besoin" ;;
  studio)      quoi="les trois services du Studio"; perte="le Studio est arrêté le temps de se refaire"; retour="quelques minutes au prochain ./start.sh" ;;
  tout)        quoi="TOUT ce qui a été téléchargé ci-dessus"; perte="le Studio repart de zéro, et les clips sont loués en attendant"; retour="22 minutes pour la vidéo, quelques minutes pour le reste" ;;
  sandbox-data|open-webui-data|travail|conversations)
    echo "  Ce n'est pas une ressource téléchargée : c'est VOTRE travail."
    echo "  Ce script ne le supprime pas. Si c'est vraiment ce que vous voulez :"
    echo "    docker volume rm ${PROJET}_sandbox-data      (vos fichiers)"
    echo "    docker volume rm ${PROJET}_open-webui-data   (vos conversations)"
    exit 1 ;;
  *) echo "  Clé inconnue : $cle"; echo "  Les clés sont entre crochets dans le tableau ci-dessus."; exit 2 ;;
esac

echo "  À vider : $quoi"
echo "  Ce que vous perdez : $perte"
echo "  Pour revenir : $retour"
echo
if [ "$oui" -eq 0 ]; then
  if [ ! -t 0 ]; then
    echo "  Pas de terminal pour poser la question. Rien n'a été touché."
    echo "  Relancez avec --oui si c'est bien ce que vous voulez."
    exit 1
  fi
  printf "  Tapez oui pour vider, n'importe quoi d'autre pour annuler : "
  read -r reponse
  case "$(echo "$reponse" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')" in
    oui|o|yes|y) ;;
    *) echo "  Annulé. Rien n'a été touché."; exit 0 ;;
  esac
fi

# Une image ou un volume encore utilisé fait refuser docker. On ne force pas et
# on n'arrête pas le Studio à la place de la personne : on dit quoi faire.
refus() {
  echo "  Docker a refusé : $1"
  echo "  C'est qu'il est encore en service. Arrêtez le Studio puis relancez :"
  echo "    docker compose down"
  echo "    ./scripts/ressources.sh --vider $cle"
}

vider_poids() {
  # Une seule route pour effacer les 34 Go : le script dédié, avec ses gardes.
  ./scripts/supprimer-modele-video.sh --oui
}
vider_image() {
  sortie="$(docker image rm "$1" 2>&1)" || { refus "$sortie"; return 1; }
  echo "  Rendu : $1"
}
vider_volume() {
  sortie="$(docker volume rm "$1" 2>&1)" || { refus "$sortie"; return 1; }
  echo "  Rendu : $1"
}

code=0
case "$cle" in
  video-poids) vider_poids || code=1 ;;
  video-image) vider_image free-ai-studio-sandbox-worker-gpu || code=1 ;;
  chat)        for id in $(docker images --format '{{.Repository}}:{{.Tag}} {{.ID}}' | awk '/open-webui/{print $2}' | sort -u); do vider_image "$id" || code=1; done ;;
  whisper)     vider_volume "${PROJET}_whisper-modeles" || code=1 ;;
  studio)      for i in free-ai-studio-free-tier-manager free-ai-studio-sandbox-manager free-ai-studio-sandbox-worker; do vider_image "$i" || code=1; done ;;
  tout)
    vider_poids || code=1
    vider_image free-ai-studio-sandbox-worker-gpu || code=1
    for id in $(docker images --format '{{.Repository}}:{{.Tag}} {{.ID}}' | awk '/open-webui/{print $2}' | sort -u); do vider_image "$id" || code=1; done
    vider_volume "${PROJET}_whisper-modeles" || code=1
    for i in free-ai-studio-free-tier-manager free-ai-studio-sandbox-manager free-ai-studio-sandbox-worker; do vider_image "$i" || code=1; done
    ;;
esac

echo
if [ "$code" -eq 0 ]; then
  echo "  Fait. Relancez ./scripts/ressources.sh pour voir la place rendue."
else
  echo "  Une partie n'a pas pu être rendue (voir au-dessus). Votre travail n'a pas été touché."
fi
exit "$code"
