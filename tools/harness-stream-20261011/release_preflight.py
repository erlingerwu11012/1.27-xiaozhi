"""Read-only deployment inventory; do not print credentials or user records."""
from pathlib import Path
import subprocess,json,hashlib,tarfile,os
S=Path(__file__).parent
apps=json.loads(subprocess.check_output(['pm2','jlist']))
selected={n:next(x for x in apps if x['name']==n and x['pm2_env']['status']=='online') for n in ['xiaozhi-server','manager-api']}
for n,a in selected.items():
 e=a['pm2_env'];print(n,json.dumps({k:e.get(k) for k in ['pm_exec_path','pm_cwd','args','exec_interpreter']}))
baseline={}
with tarfile.open(S/'baseline/runtime.tgz') as t:
 for m in t.getmembers():
  if m.isfile() and m.name.endswith('.py'):
   baseline[m.name.removeprefix('./')]=hashlib.sha256(t.extractfile(m).read()).hexdigest()
changes={str(p.relative_to(S/'work')):hashlib.sha256(p.read_bytes()).hexdigest() for p in (S/'work').rglob('*.py') if '__pycache__' not in p.parts and baseline.get(str(p.relative_to(S/'work')))!=hashlib.sha256(p.read_bytes()).hexdigest()}
out={'changes':changes,'baseline_hashes':{n:baseline.get(n) for n in changes},'live_apps':{n:{k:a['pm2_env'].get(k) for k in ['pm_exec_path','pm_cwd','args','exec_interpreter']} for n,a in selected.items()}}
(S/'release-preflight.json').write_text(json.dumps(out,indent=2))
print('CHANGED_SOURCE',json.dumps(sorted(changes)))
for p in ['/etc/nginx/sites-enabled/www.realecho.cn','/etc/nginx/conf.d/tool-harness-internal.conf','/etc/nginx/conf.d/experience-manager-compat.conf']:
 text=Path(p).read_text()
 import re
 print(p,re.findall(r'127\.0\.0\.1:\d+',text))
meta=json.loads(subprocess.check_output(['docker','inspect','one-api']))[0]
print('ONEAPI',json.dumps({'image':meta['Config']['Image'],'ports':meta['HostConfig']['PortBindings'],'mounts':[{k:m[k] for k in ['Source','Destination','RW']} for m in meta['Mounts']]}))
