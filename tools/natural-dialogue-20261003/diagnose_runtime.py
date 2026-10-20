"""Redacted runtime comparison; no secrets, identities, or customer histories."""
import json, subprocess, os, sys, asyncio
from urllib.parse import urlparse
from pathlib import Path
from unittest.mock import MagicMock
OUT=Path('/root/prjs/tmp/natural-dialogue-20261003')
ROOT=OUT/'main/xiaozhi-server'
procs=json.loads(subprocess.run(['pm2','jlist'],capture_output=True,text=True,check=True).stdout)
for name in ['xiaozhi-server','natural-dialogue-canary']:
    row=next(p for p in procs if p['name']==name)
    env=row['pm2_env']
    proxies={k:urlparse(str(v)).hostname for k,v in env.items() if 'proxy' in k.lower()}
    raw=Path('/proc/'+str(row['pid'])+'/environ').read_bytes()
    running={p.split(b'=',1)[0].decode():p.split(b'=',1)[1].decode(errors='replace') for p in raw.split(b'\0') if b'=' in p}
    billing={k:{'present':bool(v),'length':len(v) if 'KEY' in k else None,
                'origin':urlparse(v).netloc if 'ORIGIN' in k else None} for k,v in running.items() if k.startswith('HW_BILLING_')}
    print(json.dumps({'process':name,'proxies':proxies,'no_proxy_present':bool(env.get('NO_PROXY') or env.get('no_proxy')),'billing_runtime':billing}))
    if name=='natural-dialogue-canary':
        for k,v in env.items():
            if k.isupper() and isinstance(v,str):os.environ[k]=v
os.chdir(ROOT);sys.path.insert(0,str(ROOT))
import config.logger
config.logger.setup_logging=lambda:MagicMock()
import httpx
for trust in [True,False]:
    try:
        r=httpx.Client(timeout=3,trust_env=trust).get('http://127.0.0.1:3000/')
        print(json.dumps({'trust_env':trust,'http_status':r.status_code}))
    except Exception as exc:print(json.dumps({'trust_env':trust,'error':type(exc).__name__,'cause':str(exc)[:180]}))
