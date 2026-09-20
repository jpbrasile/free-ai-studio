#!/usr/bin/env bash
set +e
cd "$(dirname "$0")/.."

echo "FREE AI STUDIO — CAPACITÉS DE L'ENVIRONNEMENT"
echo

printf "%-28s " "Lecture fichiers"
[ -r "README.md" ] && echo "✓" || echo "✗"

tmp=".assistant_write_test_$$"
printf "%-28s " "Écriture fichiers"
echo "test" > "$tmp" 2>/dev/null
if [ $? -eq 0 ]; then
  rm -f "$tmp"
  echo "✓"
else
  echo "✗"
fi

printf "%-28s " "Terminal / shell"
[ -n "${SHELL:-}" ] || [ -x "/bin/sh" ]
[ $? -eq 0 ] && echo "✓" || echo "?"

printf "%-28s " "Docker"
command -v docker >/dev/null 2>&1 && echo "✓" || echo "ℹ non détecté"

echo
echo "Accès Web : impossible à garantir depuis un script local."
echo "L'assistant doit vérifier lui-même si son extension dispose d'une"
echo "fonction de recherche Web / documentation et demander l'autorisation"
echo "à l'utilisateur si nécessaire."
