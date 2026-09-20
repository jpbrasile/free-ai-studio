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

# --- dates -----------------------------------------------------------------
# « Renouvelé le » = la date où la chose est arrivée SUR CETTE MACHINE, pas
# celle où son auteur l'a publiée. C'est elle qui répond à la question du
# client : depuis quand est-ce que ça dort là. Vider puis réutiliser la remet à
# aujourd'hui -- c'est exactement ce que « renouvelé » veut dire ici.
jour() {                      # secondes depuis 1970 -> 19/09/2026
  case "${1:-}" in
    ''|*[!0-9]*) printf -- "-"; return ;;
  esac
  date -d "@$1" +%d/%m/%Y 2>/dev/null || printf -- "-"
}
jour_iso() {                  # 2026-09-19T21:10:33Z -> 19/09/2026
  case "${1:-}" in
    [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]*) echo "${1:8:2}/${1:5:2}/${1:0:4}" ;;
    *) printf -- "-" ;;
  esac
}
# Le fichier le plus récemment écrit, et non la date du dossier : un
# téléchargement repris ajoute des fichiers sans toucher au dossier du dessus.
date_dossier() {
  [ -d "$1" ] || { printf -- "-"; return; }
  local e
  e="$(find "$1" -type f -printf '%T@\n' 2>/dev/null | sort -n | tail -1 | cut -d. -f1)"
  [ -n "$e" ] || e="$(stat -c %Y "$1" 2>/dev/null)"
  jour "$e"
}
# `LastTagTime` est la date où l'image a atterri ici (construite ou tirée).
# `.Created` est celle de son auteur : c'est le repli, et il est moins bon.
# Rend AAAA-MM-JJ et rien d'autre : `LastTagTime` sort avec des espaces
# (« 2026-09-20 08:19:56.278 +0000 UTC »), et un mot coupé sur un espace fait
# comparer « UTC » à une date -- c'est ce qui affichait un tiret sur la ligne
# du Studio, mesuré le 20/09.
iso_image() {
  local t
  t="$(docker image inspect "$1" --format '{{.Metadata.LastTagTime}}' 2>/dev/null)"
  case "$t" in ''|0001-01-01*) t="$(docker image inspect "$1" --format '{{.Created}}' 2>/dev/null)" ;; esac
  # Le retour à la ligne compte : sans lui les trois dates du Studio se
  # collaient en un seul mot et la ligne affichait la date de la PREMIÈRE
  # image, pas la plus récente. Vu le 20/09 -- une date plausible et fausse.
  printf '%s\n' "${t:0:10}"
}
iso_max() {                   # la plus récente : l'ISO se compare comme du texte
  local m="" t
  for t in "$@"; do [ "$t" \> "$m" ] && m="$t"; done
  echo "$m"
}
date_image()  { jour_iso "$(iso_image "$1")"; }
date_volume() { jour_iso "$(docker volume inspect "$1" --format '{{.CreatedAt}}' 2>/dev/null)"; }

# --- où sont les choses ----------------------------------------------------
cache="${GPU_MODELES_DIR:-$HOME/.cache/huggingface}"
POIDS_VIDEO="$cache/hub/models--Wan-AI--Wan2.2-TI2V-5B-Diffusers"
# Le préfixe des volumes est celui du dossier du projet, comme docker compose
# le fabrique. On ne devine pas : on demande à docker.
PROJET="$(basename "$PWD" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9_-')"

IDS_CHAT="$(docker images --format '{{.Repository}}:{{.Tag}} {{.ID}}' | awk '/open-webui/{print $2}' | sort -u)"
LOT_STUDIO="free-ai-studio-free-tier-manager free-ai-studio-sandbox-manager free-ai-studio-sandbox-worker"

o_poids=$(taille_dossier "$POIDS_VIDEO")
o_img_gpu=$(taille_image free-ai-studio-sandbox-worker-gpu)
o_img_chat=$(for id in $IDS_CHAT; do taille_image "$id"; done | awk '{s+=$1} END{print s+0}')
o_img_studio=0
for i in $LOT_STUDIO; do
  o_img_studio=$(( o_img_studio + $(taille_image "$i") ))
done
o_whisper=$(taille_volume "${PROJET}_whisper-modeles")
o_travail=$(taille_volume "${PROJET}_sandbox-data")
o_convers=$(taille_volume "${PROJET}_open-webui-data")

# Plusieurs images sur une ligne : c'est la plus récente qui date la ligne.
d_poids=$(date_dossier "$POIDS_VIDEO")
d_img_gpu=$(date_image free-ai-studio-sandbox-worker-gpu)
d_img_chat=$(jour_iso "$(iso_max $(for id in $IDS_CHAT; do iso_image "$id"; done))")
d_img_studio=$(jour_iso "$(iso_max $(for i in $LOT_STUDIO; do iso_image "$i"; done))")
d_whisper=$(date_volume "${PROJET}_whisper-modeles")
d_travail=$(date_volume "${PROJET}_sandbox-data")
d_convers=$(date_volume "${PROJET}_open-webui-data")

total_telecharge=$(( o_poids + o_img_gpu + o_img_chat + o_img_studio + o_whisper ))
total_travail=$(( o_travail + o_convers ))

# --- affichage -------------------------------------------------------------
echo
echo "  Place occupée par le Studio sur cet ordinateur"
echo
ligne() { printf "  "; col "$1" 22; printf " "; col "$2" 42; printf "%10s    " "$3"; col "$4" 12; printf "%s\n" "$5"; }
ligne "APPLICATION" "CE QUI EST SUR LE DISQUE" "TAILLE" "RENOUVELÉ LE" ""
ligne "----------------------" "------------------------------------------" "----------" "------------" ""
ligne "Vidéo à la maison"  "les 34 Go du modèle vidéo"                 "$(lisible $o_poids)"     "$d_poids"     "   [video-poids]"
ligne "Vidéo à la maison"  "le bac à sable qui sait parler à la carte" "$(lisible $o_img_gpu)"   "$d_img_gpu"   "   [video-image]"
ligne "Chat (Open WebUI)"  "l'application de conversation"             "$(lisible $o_img_chat)"  "$d_img_chat"  "   [chat]"
ligne "Écoute des voix"    "les modèles qui transcrivent"              "$(lisible $o_whisper)"   "$d_whisper"   "   [whisper]"
ligne "Le Studio lui-même" "ses trois services"                        "$(lisible $o_img_studio)" "$d_img_studio" "   [studio]"
echo
ligne "VOTRE TRAVAIL" "jamais proposé à la suppression ici" "" "" ""
ligne "Vos fichiers" "l'espace de travail du bac à sable" "$(lisible $o_travail)" "$d_travail" ""
ligne "Vos conversations" "l'historique du chat" "$(lisible $o_convers)" "$d_convers" ""
echo
echo "  Téléchargé : $(lisible $total_telecharge)     Votre travail : $(lisible $total_travail)"
echo "  (les images Docker partagent des morceaux : le total téléchargé est une borne haute)"
echo "  « Renouvelé le » = arrivé sur cette machine à cette date. Pour un volume, c'est sa"
echo "  date de création : ce qu'il contient a pu être ajouté plus tard."
if command -v df >/dev/null 2>&1; then
  echo "  Disque : $(df -h . | awk 'NR==2{print $4" libres sur "$2}')"
fi
echo

# --- ce qui se remet à zéro tout seul --------------------------------------
# Les lignes du dessus dorment sur le disque : elles ne bougent que si on les
# vide. Celles-ci sont des DROITS D'USAGE, et elles repartent à une date. Ne
# pas la connaître, c'est soit attendre pour rien alors que le crédit est
# revenu, soit lancer un calcul qui sera refusé.
#
# Le compteur Modal se lit dans `config/`, qui est monté depuis ce dépôt : ni
# clé, ni docker, ni service à démarrer.
json_nombre() { [ -f "$1" ] && sed -n 's/.*"'"$2"'"[[:space:]]*:[[:space:]]*\([0-9.]*\).*/\1/p' "$1" | head -1 || true; }
json_texte()  { [ -f "$1" ] && sed -n 's/.*"'"$2"'"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$1" | head -1 || true; }
premier_du_mois_suivant() {   # 2026-09 -> 01/10/2026
  local a="${1%%-*}" m="${1##*-}"
  m=$((10#$m + 1))
  if [ "$m" -gt 12 ]; then m=1; a=$((a + 1)); fi
  printf '01/%02d/%d' "$m" "$a"
}

MOIS="$(date +%Y-%m)"
BUDGET_MODAL="config/modal-budget.json"
credit="${MODAL_CREDIT_MENSUEL_USD:-30}"
estime="$(json_nombre "$BUDGET_MODAL" usd)"
# Depuis le 20/09/2026 le compteur range aussi le chiffre RELEVÉ chez Modal.
# Cette page lisait `usd` seul, donc elle affichait encore l'estimation quand
# les pages du Studio, elles, montraient la vraie facture : 1,39 $ ici contre
# 3,80 $ là, le même jour, pour le même mois.
reel="$(json_nombre "$BUDGET_MODAL" usd_reel)"
reel_le="$(json_texte "$BUDGET_MODAL" usd_reel_le)"
# Un compteur d'un mois clos ne dit rien du mois en cours : il est déjà reparti
# de zéro, et l'afficher serait un chiffre faux présenté comme à jour.
[ "$(json_texte "$BUDGET_MODAL" mois)" = "$MOIS" ] || { estime=""; reel=""; }
[ -n "$estime" ] || estime=0
# Le plus grand des deux, comme le garde lui-même : les deux nombres sont des
# MINORANTS. Le nôtre sous-évalue mémoire et processeur ; celui de Modal ignore
# encore le calcul qui vient de finir (« within minutes »).
depense="$estime"
vient_de_modal=0
if [ -n "$reel" ] && awk -v r="$reel" -v e="$estime" 'BEGIN{exit !(r >= e)}'; then
  depense="$reel"
  vient_de_modal=1
fi

# CE QUI EST SOURCÉ ET CE QUI NE L'EST PAS. Vérifié le 20/09/2026, après que le
# propriétaire a demandé « les jours exacts », puis « mesure Modal pour moi » :
#   - Modal, pages PUBLIQUES : « $30 / month free compute » (modal.com/pricing)
#     et « All Workspaces are billed monthly » (docs/guide/billing). Le JOUR
#     n'y est écrit NULLE PART. Le « 1er du mois » qu'on avait affiché venait
#     d'un résumé de moteur de recherche, pas de Modal : il a été retiré.
#   - Modal, TABLEAU DE BORD de l'espace de travail : lui l'écrit. Relevé le
#     20/09/2026 sur `jp-brasile`, page « Usage & billing » : plan Starter,
#     « $30.00 included compute credits per month », « Billing Cycle:
#     Sep 1 - Oct 1, 2026 ». Le cycle EST donc le mois civil ici -- mesuré, pas
#     supposé -- et il s'affiche par espace de travail : celui d'un autre
#     client peut tomber ailleurs dans le mois.
#   - Gemini : « Requests per day (RPD) quotas reset at midnight Pacific time »
#     (ai.google.dev/gemini-api/docs/rate-limits). Seule date écrite par un
#     fournisseur dans sa documentation publique.
#   - OpenRouter : la page des limites donne les comptes par jour, pas l'heure.
#   - Groq : pas d'heure fixe publiée ; l'API rend un COMPTE À REBOURS dans
#     l'en-tête `x-ratelimit-reset-requests`.
#
# L'ÉCART MESURÉ LE 20/09/2026, ET CE QUI EN RESTE. Ce compteur disait 1,39 $
# quand Modal en facturait 3,80 $ sur la même période. La cause a été trouvée le
# même jour, et ce n'était pas un « ordre de grandeur » : Modal publie DEUX
# grilles de prix (`modal billing rates`), et les bacs à sable — tout ce que le
# Studio lance — paient le processeur et la mémoire TROIS FOIS le tarif normal.
# Nous comptions avec l'autre grille. Les prix sont corrigés depuis.
#
# Ce qui reste, et qui est écrit tel quel : Modal facture le plus grand de ce
# qu'on RÉSERVE et de ce qu'on UTILISE. Le Studio réserve 1 cœur ; les six jours
# facturés de septembre en montrent de 1,0 à 3,2. L'estimation peut donc encore
# être un peu basse, de l'ordre de 8 % sur ce mélange de travaux — plus jamais
# du triple. Sur la seule journée entièrement couverte, le 20/09, elle retombe à
# 0,145 $ contre 0,158 $ facturés.
echo "  Ce qui se remet à zéro tout seul"
echo
printf "  %s\n" "Modal (machines louées)   $(awk -v d="$depense" -v c="$credit" 'BEGIN{printf "%.2f $ dépensés sur %.0f $ ce mois-ci, reste %.2f $", d, c, (c-d<0?0:c-d)}')"
printf "  %s\n" "                          NOTRE compteur repart le $(premier_du_mois_suivant "$MOIS"), et tous les 1ers."
echo "                            Le crédit Modal aussi : « Billing Cycle: Sep 1 - Oct 1 »,"
echo "                            lu le 20/09/2026 sur VOTRE tableau de bord. Leur page"
echo "                            publique, elle, ne publie PAS le jour ; le tableau de"
echo "                            bord si, et c'est VOTRE cycle qui fait foi (modal.com)."
if [ "$vient_de_modal" -eq 1 ]; then
  echo "                            Ce montant est RELEVÉ CHEZ MODAL (le $reel_le) :"
  echo "                            c'est leur compte, pas le nôtre. Notre estimation"
  printf "  %s\n" "                          locale, elle, dit $(awk -v e="$estime" 'BEGIN{printf "%.2f", e}') \$ — elle sous-compte"
  echo "                            un peu (le processeur réellement utilisé au-delà du"
  echo "                            cœur réservé). Le détail est sur leur page"
  echo "                            « Usage & billing »."
else
  echo "                            ATTENTION, Modal n'a pas répondu : ce chiffre est"
  echo "                            NOTRE estimation. Elle compte MOINS que la vraie"
  echo "                            facture, d'environ 8 % sur les travaux mesurés en"
  echo "                            septembre 2026 — le processeur réellement utilisé"
  echo "                            dépasse le cœur réservé, et cela ne se sait qu'après."
  echo "                            Le reste exact est sur leur page « Usage & billing »."
fi
echo "  Gemini                    quota du JOUR, remis à zéro à minuit heure du"
echo "                            Pacifique, soit 9 h chez nous — écrit par Google"
echo "  OpenRouter                quota du JOUR ; l'heure n'est pas publiée"
echo "  Groq                      pas d'heure fixe : l'API rend un compte à rebours"
echo "  Le compte du jour est sur la page Clés du Studio."
echo "  (vérifié le 20/09/2026 sur les pages officielles)"
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
  chat)        for id in $IDS_CHAT; do vider_image "$id" || code=1; done ;;
  whisper)     vider_volume "${PROJET}_whisper-modeles" || code=1 ;;
  studio)      for i in $LOT_STUDIO; do vider_image "$i" || code=1; done ;;
  tout)
    vider_poids || code=1
    vider_image free-ai-studio-sandbox-worker-gpu || code=1
    for id in $IDS_CHAT; do vider_image "$id" || code=1; done
    vider_volume "${PROJET}_whisper-modeles" || code=1
    for i in $LOT_STUDIO; do vider_image "$i" || code=1; done
    ;;
esac

echo
if [ "$code" -eq 0 ]; then
  echo "  Fait. Relancez ./scripts/ressources.sh pour voir la place rendue."
else
  echo "  Une partie n'a pas pu être rendue (voir au-dessus). Votre travail n'a pas été touché."
fi
exit "$code"
