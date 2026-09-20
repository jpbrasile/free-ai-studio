#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "== Free AI Studio : installation =="

if ! command -v docker >/dev/null 2>&1; then
  echo "ERREUR: Docker n'est pas installé."
  echo "Voir docs/INSTALLATION.md"
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "ERREUR: Docker Compose v2 n'est pas disponible."
  exit 1
fi

if [ ! -f .env ]; then
  cp .env.example .env
  echo ".env créé depuis .env.example"
fi

if ! grep -q '^WEBUI_SECRET_KEY=.\+' .env 2>/dev/null; then
  if command -v openssl >/dev/null 2>&1; then
    secret="$(openssl rand -hex 32)"
  else
    secret="$(python3 - <<'PY'
import secrets
print(secrets.token_hex(32))
PY
)"
  fi
  python3 - "$secret" <<'PY'
from pathlib import Path
import sys
p = Path(".env")
secret = sys.argv[1]
lines = p.read_text().splitlines()
out = []
done = False
for line in lines:
    if line.startswith("WEBUI_SECRET_KEY="):
        out.append("WEBUI_SECRET_KEY=" + secret)
        done = True
    else:
        out.append(line)
if not done:
    out.append("WEBUI_SECRET_KEY=" + secret)
p.write_text("\n".join(out) + "\n")
PY
  echo "WEBUI_SECRET_KEY générée."
fi

if ! grep -q '^FREE_TIER_MANAGER_KEY=.\+' .env 2>/dev/null; then
  if command -v openssl >/dev/null 2>&1; then
    manager_key="$(openssl rand -hex 32)"
  else
    manager_key="$(python3 - <<'PY'
import secrets
print(secrets.token_hex(32))
PY
)"
  fi
  python3 - "$manager_key" <<'PY'
from pathlib import Path
import sys
p = Path(".env")
key = sys.argv[1]
lines = p.read_text().splitlines()
out = []
done = False
for line in lines:
    if line.startswith("FREE_TIER_MANAGER_KEY="):
        out.append("FREE_TIER_MANAGER_KEY=" + key)
        done = True
    else:
        out.append(line)
if not done:
    out.append("FREE_TIER_MANAGER_KEY=" + key)
p.write_text("\n".join(out) + "\n")
PY
  echo "FREE_TIER_MANAGER_KEY générée."
fi


for key_name in SANDBOX_MANAGER_KEY SANDBOX_WORKER_KEY; do
  if ! grep -q "^${key_name}=.\+" .env 2>/dev/null; then
    if command -v openssl >/dev/null 2>&1; then
      generated="$(openssl rand -hex 32)"
    else
      generated="$(python3 - <<'PY2'
import secrets
print(secrets.token_hex(32))
PY2
)"
    fi
    python3 - "$key_name" "$generated" <<'PY2'
from pathlib import Path
import sys
p=Path('.env'); name=sys.argv[1]; value=sys.argv[2]
lines=p.read_text().splitlines(); out=[]; done=False
for line in lines:
    if line.startswith(name+'='):
        out.append(name+'='+value); done=True
    else: out.append(line)
if not done: out.append(name+'='+value)
p.write_text('\n'.join(out)+'\n')
PY2
    echo "$key_name générée."
  fi
done

echo "Téléchargement de l'image Open WebUI..."
docker compose pull

echo
echo "Installation prête."
echo "Lancez ./start.sh"
echo "Puis vérifiez avec ./scripts/self-test.sh"
echo "Sandbox : http://127.0.0.1:8020 (Modal-first si configuré; boutons Colab/Kaggle conservés)"

printf "\nFree AI Studio (débutant) : http://127.0.0.1:8010/studio\nChat : http://localhost:3000\n"
