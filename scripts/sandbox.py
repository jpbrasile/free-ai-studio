#!/usr/bin/env python3
"""Client local Free AI Studio Sandbox. Lit la clé depuis .env sans l'afficher."""
from __future__ import annotations
import argparse, json, mimetypes, os, sys, time, urllib.error, urllib.request, uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BASE=os.getenv('FREE_AI_SANDBOX_URL','http://127.0.0.1:8020').rstrip('/')

def env():
    d={}
    p=ROOT/'.env'
    if p.exists():
        for line in p.read_text(encoding='utf-8',errors='replace').splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                k,v=line.split('=',1); d[k.strip()]=v.strip()
    return d

def key():
    k=env().get('SANDBOX_MANAGER_KEY','')
    if not k: raise SystemExit('SANDBOX_MANAGER_KEY absente de .env')
    return k

def request(path, method='GET', data=None, content_type='application/json'):
    headers={'Authorization':'Bearer '+key()}
    body=None
    if data is not None:
        body=json.dumps(data).encode(); headers['Content-Type']=content_type
    req=urllib.request.Request(BASE+path,data=body,headers=headers,method=method)
    try:
        with urllib.request.urlopen(req,timeout=180) as r: return r.status,r.read()
    except urllib.error.HTTPError as e:
        raise SystemExit(f'HTTP {e.code}: {e.read().decode(errors="replace")[:1000]}')

def multipart_upload(path, file_path: Path):
    boundary='----FreeAIStudio'+uuid.uuid4().hex
    raw=file_path.read_bytes(); ctype=mimetypes.guess_type(file_path.name)[0] or 'application/octet-stream'
    body=(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{file_path.name}"\r\nContent-Type: {ctype}\r\n\r\n'.encode()+raw+f'\r\n--{boundary}--\r\n'.encode())
    req=urllib.request.Request(BASE+path,data=body,headers={'Authorization':'Bearer '+key(),'Content-Type':f'multipart/form-data; boundary={boundary}'},method='POST')
    try:
        with urllib.request.urlopen(req,timeout=180) as r: return r.status,r.read()
    except urllib.error.HTTPError as e: raise SystemExit(f'HTTP {e.code}: {e.read().decode(errors="replace")[:1000]}')

ap=argparse.ArgumentParser()
sub=ap.add_subparsers(dest='cmd',required=True)
p=sub.add_parser('submit'); p.add_argument('file'); p.add_argument('--provider',choices=['auto','modal','local','kaggle','colab'],default='auto'); p.add_argument('--title',default='Free AI Studio job'); p.add_argument('--gpu',action='store_true'); p.add_argument('--internet',action='store_true'); p.add_argument('--wait',action='store_true')
p=sub.add_parser('status'); p.add_argument('job_id')
p=sub.add_parser('import'); p.add_argument('job_id'); p.add_argument('file')
sub.add_parser('jobs'); sub.add_parser('artifacts'); sub.add_parser('providers')
a=ap.parse_args()
if a.cmd=='submit':
    code=Path(a.file).read_text(encoding='utf-8')
    _,b=request('/jobs','POST',{'provider':a.provider,'code':code,'title':a.title,'gpu':a.gpu,'internet':a.internet}); data=json.loads(b); print(json.dumps(data,ensure_ascii=False,indent=2)); jid=data['id']
    if a.wait and a.provider!='colab':
        while True:
            time.sleep(2); _,b=request('/jobs/'+jid); data=json.loads(b)
            if data.get('status') in ('succeeded','failed','needs_configuration','handoff_ready'):
                print(json.dumps(data,ensure_ascii=False,indent=2)); break
elif a.cmd=='status':
    _,b=request('/jobs/'+a.job_id); print(json.dumps(json.loads(b),ensure_ascii=False,indent=2))
elif a.cmd=='import':
    _,b=multipart_upload('/jobs/'+a.job_id+'/artifacts',Path(a.file)); print(json.dumps(json.loads(b),ensure_ascii=False,indent=2))
elif a.cmd in ('jobs','artifacts','providers'):
    _,b=request('/'+a.cmd); print(json.dumps(json.loads(b),ensure_ascii=False,indent=2))
