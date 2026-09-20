#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if ! command -v python3 >/dev/null 2>&1; then
  echo "ERREUR: python3 est requis pour l'auto-test."; exit 1
fi
exec python3 scripts/self-test.py
