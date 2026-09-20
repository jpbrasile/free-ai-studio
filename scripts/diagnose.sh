#!/usr/bin/env bash
set +e
cd "$(dirname "$0")/.."

echo "FREE AI STUDIO — DIAGNOSTIC"
echo

check () {
  label="$1"
  shift
  if "$@" >/dev/null 2>&1; then
    printf "%-22s ✓\n" "$label"
  else
    printf "%-22s ✗\n" "$label"
  fi
}

check "Docker" docker --version
check "Docker Compose" docker compose version
check ".env" test -f .env

if [ -f .env ]; then
  grep -q '^FREE_ONLY=true' .env
  [ $? -eq 0 ] && printf "%-22s ✓\n" "FREE_ONLY=true" || printf "%-22s ⚠\n" "FREE_ONLY=true"

  grep -q '^ALLOW_PAID_MODELS=false' .env
  [ $? -eq 0 ] && printf "%-22s ✓\n" "Paid models bloqués" || printf "%-22s ⚠\n" "Paid models bloqués"
fi

docker compose ps --status running 2>/dev/null | grep -q free-ai-studio-open-webui
[ $? -eq 0 ] && printf "%-22s ✓\n" "Open WebUI actif" || printf "%-22s ✗\n" "Open WebUI actif"

if command -v nvidia-smi >/dev/null 2>&1; then
  printf "%-22s ✓\n" "GPU NVIDIA détecté"
else
  printf "%-22s ℹ\n" "GPU NVIDIA"
fi


docker compose ps --status running 2>/dev/null | grep -q free-ai-studio-manager
[ $? -eq 0 ] && printf "%-22s ✓\n" "Free Tier Manager" || printf "%-22s ✗\n" "Free Tier Manager"
