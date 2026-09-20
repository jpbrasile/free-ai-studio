#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo ".env absent."
  exit 1
fi

key="$(grep '^FREE_TIER_MANAGER_KEY=' .env | head -n1 | cut -d= -f2-)"
if [ -z "$key" ]; then
  echo "FREE_TIER_MANAGER_KEY absente. Lancez ./install.sh"
  exit 1
fi

if command -v curl >/dev/null 2>&1; then
  curl -fsS -H "Authorization: Bearer $key" http://127.0.0.1:8010/status
  echo
else
  echo "curl absent. Ouvrez http://127.0.0.1:8010/health"
fi
