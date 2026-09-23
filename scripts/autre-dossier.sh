#!/usr/bin/env bash
# Un autre dossier du Studio tourne-t-il deja sur cet ordinateur ?
# Jumeau de scripts/autre-dossier.ps1, pour install.sh et start.sh.
#
# Ecrit sur sa sortie le chemin de cet autre dossier, ou rien. Ne change rien :
# il lit seulement les etiquettes des conteneurs. Docker absent ou arrete : rien
# non plus, le lanceur le dira lui-meme a sa facon.
#
# Avec --arreter (ce que font install.sh et start.sh) : s'il y a un autre
# dossier, ecrit le message << ARRET : >> avec les deux choix et rend 1 ; sinon
# rend 0 sans rien ecrire.
#
# Pourquoi (essai a blanc du 23/09/2026) : deux dossiers du Studio font deux
# projets Docker, mais les noms de conteneurs sont fixes (free-ai-studio-*) ; le
# second demarrage echoue sur << Conflict. The container name ... is already in
# use >>. Docker range dans chaque conteneur le dossier qui l'a lance
# (com.docker.compose.project.working_dir) : on nomme l'autre dossier AVANT de
# construire quoi que ce soit. Et on ne supprime RIEN a la place de la personne :
# la cle Gemini est dans le dossier (config/), l'historique du chat dans un
# volume au nom de l'ancien dossier -- ni l'un ni l'autre ne suit.
#
#   ./scripts/autre-dossier.sh [--arreter] [DOSSIER]    # DOSSIER : racine du Studio

set -u
ARRETER=0
if [ "${1:-}" = "--arreter" ]; then ARRETER=1; shift; fi
ICI="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
ICI="${ICI%/}"

# Sous Git Bash, Docker range C:\Users\... quand le Studio a ete lance par
# demarrer.cmd, et ce shell voit /c/Users/... : on ramene les deux a C:/Users/...,
# sans casse, comme Windows.
if command -v cygpath >/dev/null 2>&1; then
  canon() { cygpath -m "$1" 2>/dev/null | tr '[:upper:]' '[:lower:]'; }
else
  canon() { printf '%s\n' "$1"; }
fi
ICI_CANON="$(canon "$ICI")"

trouver() {
  local noms dossier
  noms="$(docker ps -a --filter 'name=^free-ai-studio-' --format '{{.Names}}' 2>/dev/null)" || return 0
  [ -n "$noms" ] || return 0
  # shellcheck disable=SC2086  # un nom par mot, voulu
  docker inspect --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}' $noms 2>/dev/null |
  while IFS= read -r dossier; do
    dossier="${dossier%$'\r'}"
    dossier="${dossier%/}"
    [ -n "$dossier" ] || continue
    [ "$dossier" = "$ICI" ] && continue
    [ "$(canon "$dossier")" = "$ICI_CANON" ] && continue
    # Meme dossier par un autre chemin (lien symbolique, casse sous macOS) : -ef
    # compare les fichiers eux-memes, quand les deux chemins existent ici.
    [ -e "$dossier" ] && [ "$dossier" -ef "$ICI" ] && continue
    printf '%s\n' "$dossier"
    break
  done
}

autre="$(trouver)"
if [ "$ARRETER" -eq 0 ]; then
  [ -n "$autre" ] && printf '%s\n' "$autre"
  exit 0
fi
[ -z "$autre" ] && exit 0

cat <<MESSAGE
ARRET : le Studio est deja installe depuis un autre dossier.
  Il tourne depuis : $autre
  Ce dossier-ci     : $ICI
  Deux dossiers ne peuvent pas tourner en meme temps. Deux choix :

  A. Garder l'ancien : lancez ./start.sh dans le dossier ci-dessus.

  B. Passer a ce dossier-ci (par exemple pour le bouton << Mettre a jour >>) :
     1. cd "$autre" && docker compose down
        (retire ses conteneurs ; ses volumes et son dossier restent sur le disque)
     2. Revenez ici et relancez ./install.sh puis ./start.sh.
     La cle Gemini sera a recoller sur la page Cles, et les conversations
     du chat de l'ancien dossier ne suivront pas.
MESSAGE
exit 1
