#!/usr/bin/env bash
# Saisir une cle dans .env sans qu'elle s'affiche (jumeau de scripts/saisir-cle.ps1).
#
# Pour les cles que les pages Cles du Studio ne prennent pas (OPENROUTER_MANAGEMENT_KEY,
# HF_TOKEN, Cloudflare...). La valeur est lue par `read -s` : ni affichee, ni
# passee en argument (elle serait visible dans la liste des processus), seulement
# ecrite dans .env. Un assistant de codage dit a la personne de lancer ce script
# elle-meme, dans son propre terminal.
#
#   ./scripts/saisir-cle.sh [NOM]

set -euo pipefail
RACINE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$RACINE"

CONNUES=(
  "GEMINI_API_KEY|Gemini (Google AI Studio), la cle gratuite principale"
  "GROQ_API_KEY|Groq"
  "OPENROUTER_API_KEY|OpenRouter, cle d'inference"
  "OPENROUTER_MANAGEMENT_KEY|OpenRouter, Management Key (Boost protege, docs/BOOST.md)"
  "HF_TOKEN|Hugging Face"
  "CLOUDFLARE_ACCOUNT_ID|Cloudflare Workers AI, identifiant de compte"
  "CLOUDFLARE_API_TOKEN|Cloudflare Workers AI, jeton"
  "MODAL_TOKEN_ID|Modal, identifiant du jeton"
  "MODAL_TOKEN_SECRET|Modal, secret du jeton"
  "KAGGLE_USERNAME|Kaggle, nom d'utilisateur"
  "KAGGLE_API_TOKEN|Kaggle, jeton"
)

if [ ! -f .env ]; then
  [ -f .env.example ] || { echo "ARRET : ni .env ni .env.example dans $RACINE."; exit 1; }
  cp .env.example .env
  echo ".env cree a partir de .env.example"
fi

choisir_nom() {
  echo >&2
  echo "Quelle cle ?" >&2
  local i=1 entree nom etat
  for entree in "${CONNUES[@]}"; do
    nom="${entree%%|*}"
    etat=""
    grep -q "^${nom}=[^[:space:]]" .env && etat="  [deja renseignee]"
    printf '  %2d. %s -- %s%s\n' "$i" "$nom" "${entree#*|}" "$etat" >&2
    i=$((i + 1))
  done
  echo "  ou tapez le nom exact d'une autre variable de .env.example" >&2
  local reponse
  read -r -p "Numero ou nom (Entree seule : quitter) : " reponse
  reponse="${reponse//$'\r'/}"
  if [[ "$reponse" =~ ^[0-9]+$ ]]; then
    if [ "$reponse" -ge 1 ] && [ "$reponse" -le "${#CONNUES[@]}" ]; then
      reponse="${CONNUES[$((reponse - 1))]%%|*}"
    else
      echo "Pas de numero $reponse." >&2
      reponse="?"
    fi
  fi
  printf '%s' "$reponse" | tr '[:lower:]' '[:upper:]'
}

# La valeur passe par l'environnement du seul python3, jamais par un argument.
enregistrer() {
  NOM="$1" VALEUR="$2" python3 - <<'PY'
import os, re
from pathlib import Path
nom, valeur = os.environ["NOM"], os.environ["VALEUR"]
# Guillemets simples : docker compose lit alors la valeur telle quelle.
if re.search(r"[\s#$\"\\]", valeur):
    valeur = "'" + valeur + "'"
p = Path(".env")
lignes = p.read_text(encoding="utf-8").splitlines()
fait = False
for i, ligne in enumerate(lignes):
    if ligne.startswith(nom + "="):
        lignes[i] = nom + "=" + valeur
        fait = True
if not fait:
    lignes.append(nom + "=" + valeur)
p.write_text("\n".join(lignes) + "\n", encoding="utf-8")
PY
}

UNIQUE="${1:-}"
enregistrees=0
while true; do
  if [ -n "$UNIQUE" ]; then nom="$(printf '%s' "$UNIQUE" | tr '[:lower:]' '[:upper:]')"; else nom="$(choisir_nom)"; fi
  [ -z "$nom" ] && break
  [ "$nom" = "?" ] && continue
  if ! [[ "$nom" =~ ^[A-Z][A-Z0-9_]*$ ]] || ! grep -q "^${nom}=" .env.example; then
    # Sans repeter ce qui a ete tape : une cle collee ici par erreur s'afficherait.
    echo "Ce n'est ni un numero de la liste ni une variable de .env.example : rien n'est ecrit."
    [ -n "$UNIQUE" ] && exit 1
    continue
  fi

  echo
  echo "Collez la valeur de $nom, puis Entree. Rien ne s'affiche pendant la saisie, c'est normal."
  valeur=""
  read -r -s -p "$nom : " valeur
  echo
  valeur="$(printf '%s' "$valeur" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
  if [ -z "$valeur" ]; then
    echo "Rien de saisi : $nom n'est pas modifiee."
  elif [[ "$valeur" == *"'"* ]]; then
    echo "Cette valeur contient une apostrophe, aucune cle n'en a : $nom n'est pas modifiee."
  else
    enregistrer "$nom" "$valeur"
    enregistrees=$((enregistrees + 1))
    echo "OK : $nom enregistree dans .env (${#valeur} caracteres)."
  fi
  valeur=""

  [ -n "$UNIQUE" ] && break
  read -r -p "Une autre cle ? (o/N) " encore
  encore="${encore//$'\r'/}"
  [ "$encore" = "o" ] || [ "$encore" = "O" ] || break
done

[ "$enregistrees" -eq 0 ] && exit 0

echo
echo "Les services lisent .env a leur demarrage."
read -r -p "Les relancer maintenant pour prendre la ou les cles ? (O/n) " relancer
relancer="${relancer//$'\r'/}"
if [ "$relancer" = "n" ] || [ "$relancer" = "N" ]; then
  echo "Plus tard : ./start.sh"
  exit 0
fi
# up -d ne recree que les conteneurs dont la configuration a change.
docker compose up -d || { echo "ARRET : docker compose up -d a echoue. Docker est-il demarre ?"; exit 1; }
echo "Services relances."
