#!/usr/bin/env python3
"""Free AI Studio post-install self-test. No AI provider calls are made."""
from __future__ import annotations
import json, os, subprocess, sys, time, urllib.error, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / '.env'

def env_values():
    out = {}
    if ENV.exists():
        for raw in ENV.read_text(encoding='utf-8', errors='replace').splitlines():
            line = raw.strip()
            if not line or line.startswith('#') or '=' not in line: continue
            k,v=line.split('=',1); out[k.strip()] = v.strip()
    return out

def run(cmd):
    return subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)

def check(label, ok, detail=''):
    mark='OK' if ok else 'ECHEC'
    print(f'[{mark}] {label}' + (f' — {detail}' if detail else ''))
    return ok

def get(url, headers=None, timeout=6):
    req=urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(200000)
    except urllib.error.HTTPError as e:
        return e.code, e.read(200000)

print('== Free AI Studio : auto-test ==')
all_ok=True
all_ok &= check('.env présent', ENV.exists())

r=run(['docker','compose','config','-q'])
all_ok &= check('docker compose config', r.returncode==0, r.stderr.strip()[:300])
if r.returncode != 0: sys.exit(1)

r=run(['docker','compose','ps','--format','json'])
all_ok &= check('docker compose ps', r.returncode==0, r.stderr.strip()[:300])
if r.returncode==0:
    text=r.stdout.strip()
    try:
        rows=[]
        if text.startswith('['): rows=json.loads(text)
        else:
            rows=[json.loads(x) for x in text.splitlines() if x.strip().startswith('{')]
        services={x.get('Service') or x.get('Name'): x for x in rows}
        for svc in ('sandbox-worker','sandbox-manager','free-tier-manager','open-webui'):
            row=services.get(svc)
            state=(row or {}).get('State','').lower()
            all_ok &= check(f'conteneur {svc}', bool(row) and state=='running', state or 'absent')
    except Exception as exc:
        check('lecture état conteneurs', False, str(exc)); all_ok=False

# Give a just-started healthcheck a short grace period.
manager_ok=False
for _ in range(8):
    try:
        status, body=get('http://127.0.0.1:8010/health', timeout=3)
        manager_ok=status==200 and json.loads(body).get('ok') is True
        if manager_ok: break
    except Exception: pass
    time.sleep(1)
all_ok &= check('manager /health', manager_ok, 'http://127.0.0.1:8010/health')

vals=env_values(); key=vals.get('FREE_TIER_MANAGER_KEY','')
if key:
    try:
        status, body=get('http://127.0.0.1:8010/status', {'Authorization':f'Bearer {key}'})
        all_ok &= check('manager authentifié /status', status==200, f'HTTP {status}')
        if status==200:
            data=json.loads(body)
            eligible=[p['name'] for p in data.get('providers',[]) if p.get('eligible')]
            print('[INFO] fournisseurs éligibles : ' + (', '.join(eligible) if eligible else 'aucun'))
            if not eligible:
                print('[INFO] Ajoutez OPENROUTER_API_KEY dans .env pour le chat gratuit strict.')
    except Exception as exc:
        all_ok &= check('manager authentifié /status', False, str(exc))
else:
    all_ok &= check('FREE_TIER_MANAGER_KEY configurée', False)

# Sandbox manager: health is public, data API is protected.
sandbox_ok=False
try:
    status, body=get('http://127.0.0.1:8020/health', timeout=5)
    sandbox_ok=status==200 and json.loads(body).get('ok') is True
except Exception:
    pass
all_ok &= check('Sandbox Manager /health', sandbox_ok, 'http://127.0.0.1:8020/health')

sandbox_key=vals.get('SANDBOX_MANAGER_KEY','')
if sandbox_key:
    try:
        status, body=get('http://127.0.0.1:8020/providers', {'Authorization':f'Bearer {sandbox_key}'})
        all_ok &= check('Sandbox API authentifiée', status==200, f'HTTP {status}')
        if status==200:
            providers=json.loads(body)
            print('[INFO] sandbox : modal=' + ('principal/configuré' if providers.get('modal',{}).get('configured') else 'non configuré -> fallback') +
                  ', local=' + ('ok' if providers.get('local',{}).get('available') else 'non') +
                  ', kaggle=' + ('configuré' if providers.get('kaggle',{}).get('configured') else 'direct seulement') +
                  ', colab=direct/handoff')
            order=providers.get('automatic_order',[])
            all_ok &= check('ordre Sandbox Modal-first', order[:4]==['modal','local','kaggle','colab'], str(order))
    except Exception as exc:
        all_ok &= check('Sandbox API authentifiée', False, str(exc))
else:
    all_ok &= check('SANDBOX_MANAGER_KEY configurée', False)

try:
    status, _=get('http://127.0.0.1:3000/', timeout=5)
    all_ok &= check('Open WebUI accessible', 200 <= status < 500, f'HTTP {status}')
except Exception as exc:
    all_ok &= check('Open WebUI accessible', False, str(exc))

print('\nRésultat : ' + ('TOUT EST OPÉRATIONNEL' if all_ok else 'DES CORRECTIONS SONT NÉCESSAIRES'))
sys.exit(0 if all_ok else 1)
