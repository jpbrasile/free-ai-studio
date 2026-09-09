#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo ".env absent."
  exit 1
fi

# Charge uniquement les noms de variables utiles sans afficher les valeurs.
set -a
# shellcheck disable=SC1091
source .env
set +a

check_var () {
  name="$1"
  value="${!name:-}"
  if [ -n "$value" ]; then
    printf "%-28s configuré ✓\n" "$name"
  else
    printf "%-28s absent ℹ\n" "$name"
  fi
}

echo "FREE AI STUDIO — FOURNISSEURS"
echo
check_var GEMINI_API_KEY
check_var GROQ_API_KEY
check_var OPENROUTER_API_KEY
check_var OPENROUTER_MANAGEMENT_KEY
check_var HF_TOKEN
check_var CLOUDFLARE_ACCOUNT_ID
check_var CLOUDFLARE_API_TOKEN
check_var MODAL_TOKEN_ID
check_var MODAL_TOKEN_SECRET
