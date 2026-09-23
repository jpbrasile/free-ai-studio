#!/usr/bin/env bash
# Sonde de la carte, cote hote. Jumeau de scripts/sonde-carte.ps1 ;
# tests/test_gpu_local.py garde les deux alignes.
#
# Le conteneur ne voit pas les processus de l'hote (autre espace de noms), et
# `nvidia-smi` ne voit pas un processus qui a pris la carte sans encore y
# ecrire. Cette sonde ecrit toutes les ~10 s, dans config/etat-carte-hote.json,
# les processus surveilles. Absent, illisible ou vieux de plus de 30 s : le
# Studio compte la carte PRISE. Elle n'arrete aucun processus.
#
#   ./scripts/sonde-carte.sh            en boucle (lancee par start.sh)
#   ./scripts/sonde-carte.sh --une-fois un seul releve
#
# Noms surveilles : SONDE_CARTE_NOMS (defaut : julia), separes par des espaces.
set -u

racine="$(cd "$(dirname "$0")/.." && pwd)"
cible="$racine/config/etat-carte-hote.json"
provisoire="$cible.tmp"
intervalle="${SONDE_CARTE_INTERVALLE:-10}"
noms="${SONDE_CARTE_NOMS:-julia}"
mkdir -p "$racine/config"

ecrire_releve() {
  local locataires="" surveilles="" n pid
  for n in $noms; do
    surveilles="$surveilles${surveilles:+,}\"$n\""
    for pid in $(pgrep -x "$n" 2>/dev/null); do
      locataires="$locataires${locataires:+,}{\"nom\":\"$n\",\"pid\":$pid}"
    done
  done
  # Ecrit a cote puis deplace : le Studio ne lit jamais un fichier a moitie ecrit.
  printf '{"ecrit_le_epoch":%s,"surveilles":[%s],"locataires":[%s]}\n' \
    "$(date +%s)" "$surveilles" "$locataires" > "$provisoire" &&
    mv -f "$provisoire" "$cible"
}

if [ "${1:-}" = "--une-fois" ]; then
  ecrire_releve && cat "$cible"
  exit $?
fi

# Une seule sonde par dossier.
exec 9>"$racine/config/.sonde-carte.verrou"
if command -v flock >/dev/null 2>&1 && ! flock -n 9; then
  echo "Une sonde de la carte tourne deja pour ce dossier : rien a faire."
  exit 0
fi

while true; do
  ecrire_releve || echo "Releve non ecrit." >&2
  sleep "$intervalle"
done
