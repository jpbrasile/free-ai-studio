#!/usr/bin/env bash
set -euo pipefail

echo "Free AI Studio — vérification Modal"
echo

if ! command -v modal >/dev/null 2>&1; then
  echo "Modal CLI non installé."
  echo "L'assistant peut l'installer avec: pip install modal"
  exit 2
fi

echo "✓ Modal CLI détecté"

echo
echo "Applications visibles :"
if ! modal app list; then
  echo
  echo "Impossible d'interroger Modal. L'authentification est peut-être absente."
  echo "Utiliser 'modal setup' avec l'accord de l'utilisateur."
  exit 3
fi

echo
echo "Endpoints LLM visibles :"
modal endpoint list || true

echo
echo "Aucun déploiement n'a été lancé par ce script."
echo "Vérifier le crédit gratuit et docs/MODAL_CATALOG.md avant tout déploiement GPU."
