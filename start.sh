#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f .env ]; then
  echo "ERREUR: .env absent. Lancez ./install.sh"
  exit 1
fi

docker compose up -d
echo
docker compose ps
echo
echo "Free AI Studio / Open WebUI : http://localhost:3000"
echo "Sandbox : http://127.0.0.1:8020"
echo "Vérification : ./scripts/self-test.sh"

printf "\nFree AI Studio (débutant) : http://127.0.0.1:8010/studio\nChat : http://localhost:3000\n"
