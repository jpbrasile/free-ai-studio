#!/usr/bin/env python3
"""Free AI Studio post-install self-test. No AI provider calls are made."""
from __future__ import annotations
import json, subprocess, sys, time, urllib.error, urllib.request
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

# La route « fabriquer une image » existe-t-elle ? On la sonde SANS clé : une
# route presente repond 401, une route absente repond 404. Rien n'est demande
# a Google, donc aucun quota consomme.
try:
    req=urllib.request.Request('http://127.0.0.1:8010/v1/images/generations',
                               data=b'{}', headers={'Content-Type':'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=6) as r: code=r.status
    except urllib.error.HTTPError as e: code=e.code
    all_ok &= check('route « fabriquer une image »', code==401, f'HTTP {code} (401 attendu : la route existe et exige la clé locale)')
except Exception as exc:
    all_ok &= check('route « fabriquer une image »', False, str(exc))

# Reglages d'Open WebUI reellement poses. Une variable presente dans le conteneur
# ne prouve rien : Open WebUI ne lit ses variables qu'au tout premier demarrage,
# ensuite c'est sa base qui decide. On lit donc la base, par son API.
def webui_reglages():
    corps=json.dumps({'email':'admin@localhost','password':'admin'}).encode()
    req=urllib.request.Request('http://127.0.0.1:3000/api/v1/auths/signin', data=corps,
                               headers={'Content-Type':'application/json'}, method='POST')
    with urllib.request.urlopen(req, timeout=10) as r:
        jeton=json.loads(r.read())['token']
    h={'Authorization':'Bearer '+jeton}
    lu={}
    for nom, chemin in (('recherche','/api/v1/retrieval/config'),
                        ('image','/api/v1/images/config'),
                        ('modeles','/api/v1/configs/models'),
                        ('proposes','/api/models')):
        req=urllib.request.Request('http://127.0.0.1:3000'+chemin, headers=h)
        with urllib.request.urlopen(req, timeout=10) as r:
            lu[nom]=json.loads(r.read())
    return lu

try:
    lu=webui_reglages()
    web=lu['recherche'].get('web', {})
    all_ok &= check('Open WebUI : recherche Web active',
                    bool(web.get('ENABLE_WEB_SEARCH')) and bool(web.get('WEB_SEARCH_ENGINE')),
                    'moteur = ' + (web.get('WEB_SEARCH_ENGINE') or 'aucun'))
    img=lu['image']
    all_ok &= check('Open WebUI : fabrication d’images active',
                    bool(img.get('ENABLE_IMAGE_GENERATION')) and 'free-tier-manager' in (img.get('IMAGES_OPENAI_API_BASE_URL') or ''),
                    'passe par ' + (img.get('IMAGES_OPENAI_API_BASE_URL') or 'aucun service'))
    params=lu['modeles'].get('DEFAULT_MODEL_PARAMS') or {}
    all_ok &= check('Open WebUI : interrupteurs d’intégrations effectifs',
                    params.get('function_calling')=='legacy',
                    'function_calling = ' + str(params.get('function_calling')))
    # Le contrôle qui manquait : ce que l'utilisateur voit dans le menu déroulant.
    # Tout le reste peut être vert et cette liste être VIDE — c'est arrivé le 09/09.
    # Open WebUI garde la clé du routeur dans sa base dès le premier démarrage ;
    # si la clé interne change ensuite, il présente l'ancienne, le routeur refuse,
    # et le chat n'affiche aucun modèle sans un mot d'explication.
    proposes=[m.get('id') for m in (lu['proposes'].get('data') or [])]
    all_ok &= check('Open WebUI : le chat propose au moins un modèle',
                    'free-ai-auto' in proposes,
                    ('liste VIDE — la clé gardée par le chat ne correspond plus à celle du routeur'
                     if not proposes else 'modèles : ' + ', '.join(proposes)))
except urllib.error.HTTPError as exc:
    print(f'[INFO] réglages Open WebUI non lisibles (HTTP {exc.code}) : normal si vous avez mis WEBUI_AUTH=true. '
          'Vérifiez à la main dans ses paramètres d’administration.')
except Exception as exc:
    all_ok &= check('réglages Open WebUI lisibles', False, str(exc))

# Vidéo. Rien n'est fabriqué ici : on vérifie que la page existe, que le compteur
# de dépense répond, et que le modèle annoncé est bien sous licence libre.
try:
    status, body = get('http://127.0.0.1:8020/video', timeout=5)
    all_ok &= check('page « fabriquer une vidéo »', status == 200, f'HTTP {status}')
except Exception as exc:
    all_ok &= check('page « fabriquer une vidéo »', False, str(exc))

if sandbox_key:
    try:
        status, body = get('http://127.0.0.1:8020/video/budget', {'Authorization': f'Bearer {sandbox_key}'})
        if status == 200:
            data = json.loads(body)
            b, m = data['budget'], data['modeles']['rapide']
            all_ok &= check('compteur de dépense vidéo', True,
                            f"{b['usd']:.2f} $ dépensés ce mois-ci sur un plafond de {b['plafond_usd']:.2f} $")
            all_ok &= check('modèle vidéo sous licence libre', m['licence'] == 'Apache 2.0',
                            f"{m['hf']} ({m['licence']})")
            print('[INFO] La vidéo est la seule fonction qui loue une carte graphique. '
                  'Le plafond refuse AVANT de lancer, il ne constate pas après coup.')
        else:
            all_ok &= check('compteur de dépense vidéo', False, f'HTTP {status}')
    except Exception as exc:
        all_ok &= check('compteur de dépense vidéo', False, str(exc))

    # Une adresse de vidéo se recopie, s'enregistre dans l'historique du
    # navigateur, se colle dans un message. Elle ne doit donc jamais contenir la
    # clé du Sandbox, qui donnerait à son lecteur le droit de lancer n'importe
    # quel calcul sur le compte de l'utilisateur. On vérifie ici que le
    # laissez-passer mis dans l'adresse n'est PAS cette clé.
    try:
        status, body = get('http://127.0.0.1:8020/jobs',
                           {'Authorization': f'Bearer {sandbox_key}'}, timeout=10)
        jobs = json.loads(body) if status == 200 else []
        jids = [j.get('id') for j in jobs if j.get('video') and j.get('status') == 'succeeded']
        url = ''
        for jid in jids[:5]:
            s, b = get(f'http://127.0.0.1:8020/video/jobs/{jid}',
                       {'Authorization': f'Bearer {sandbox_key}'}, timeout=10)
            if s == 200:
                url = json.loads(b).get('video_url') or ''
                if url:
                    break
        if url:
            all_ok &= check("l'adresse d'une vidéo ne porte pas la clé du Sandbox",
                            sandbox_key not in url,
                            'laissez-passer limité à ce seul fichier'
                            if sandbox_key not in url else 'FUITE : la clé est dans l’adresse')
        else:
            print('[INFO] adresse de vidéo non vérifiée : aucun clip fabriqué sur cette machine.')
    except Exception as exc:
        all_ok &= check("l'adresse d'une vidéo ne porte pas la clé du Sandbox", False, str(exc))

# Mise à jour : le numéro de version installé doit être lisible, sinon le bouton
# « Mettre à jour » ne peut rien dire d'utile.
try:
    status, body = get('http://127.0.0.1:8010/maj/etat', timeout=12)
    data = json.loads(body) if status == 200 else {}
    all_ok &= check('version installée lisible', status == 200 and bool(data.get('version_locale_courte')),
                    f"version {data.get('version_locale_courte') or '?'}, comparaison : {data.get('comparaison')}")
    if not data.get('veilleuse'):
        print('[INFO] Le veilleur de mise à jour n’est pas lancé : le bouton « Mettre à jour » '
              'renverra vers le double-clic sur mettre-a-jour.cmd. Démarrez avec start.ps1 '
              'pour qu’il agisse directement.')
except Exception as exc:
    all_ok &= check('version installée lisible', False, str(exc))

print('\nRésultat : ' + ('TOUT CE QUI EST TESTÉ ICI RÉPOND' if all_ok else 'DES CORRECTIONS SONT NÉCESSAIRES'))
print('[INFO] Non testé ici : la qualité des réponses et le quota restant chez les fournisseurs. '
      'Cet auto-test n’appelle aucun service payant ni gratuit, pour ne rien consommer. '
      'Posez une question dans le chat pour la preuve de bout en bout.')
sys.exit(0 if all_ok else 1)
