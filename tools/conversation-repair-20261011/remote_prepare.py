"""Capture the active release without modifying production or exposing secrets."""
import hashlib,json,os,shutil,sqlite3,subprocess,tarfile,time
from pathlib import Path

S=Path('/root/prjs/tmp/conversation-repair-20261011')
R=Path('/root/prjs/xiaozhi-esp32-server')
A=Path('/root/prjs/releases/mcp-prune-20261010/runtime')
S.mkdir(mode=0o700,exist_ok=True)
B=S/'baseline';B.mkdir(mode=0o700,exist_ok=True)
apps=json.loads(subprocess.check_output(['pm2','jlist']))
selected=[a for a in apps if a['name'] in ('xiaozhi-server','manager-api') and a['pm2_env']['status']=='online']
assert len(selected)==2
private=B/'process-private.json'
if not private.exists():private.write_text(json.dumps(selected));private.chmod(0o600)
for name,args in [('status.txt',['status','--short']),('tracked.diff',['diff','--binary'])]:
 p=B/name
 if not p.exists():p.write_bytes(subprocess.check_output(['git','-C',str(R),*args]))
if not (S/'work').exists():
 shutil.copytree(A,S/'work',ignore=shutil.ignore_patterns('data','models','logs','tmp','__pycache__','.git','*.pyc','node_modules'))
 for name in ('data','logs'):(S/'work'/name).mkdir(mode=0o700)
 if (A/'models').exists():(S/'work/models').symlink_to(A/'models',target_is_directory=True)
if not (B/'runtime.tgz').exists():
 with tarfile.open(B/'runtime.tgz','w:gz') as t:
  for p in sorted((S/'work').rglob('*')):
   if p.is_file() and not p.is_symlink():t.add(p,arcname=str(p.relative_to(S/'work')),recursive=False)
for p in [R/'main/xiaozhi-server/data/.config.yaml',R/'main/xiaozhi-server/config.yaml']:
 if p.exists():
  dest=B/('private-'+p.name.lstrip('.'))
  if not dest.exists():shutil.copy2(p,dest);dest.chmod(0o600)
ledger=R/'main/xiaozhi-server/data/harness/operations.sqlite3'
if ledger.exists() and not (B/'operations.sqlite3').exists():
 with sqlite3.connect('file:'+str(ledger)+'?mode=ro',uri=True) as a,sqlite3.connect(B/'operations.sqlite3') as b:a.backup(b)
 (B/'operations.sqlite3').chmod(0o600)
hashes={str(p.relative_to(S/'work')):hashlib.sha256(p.read_bytes()).hexdigest() for p in (S/'work').rglob('*.py') if p.is_file() and not p.is_symlink()}
meta={'created':time.time(),'active_runtime':str(A),'source_hashes':hashes,'services':[{'name':a['name'],'pid':a['pid'],'script':a['pm2_env']['pm_exec_path'],'cwd':a['pm2_env']['pm_cwd']} for a in selected],'disk_free':shutil.disk_usage(S).free}
(B/'manifest.json').write_text(json.dumps(meta,indent=2))
print(json.dumps({k:v for k,v in meta.items() if k!='source_hashes'}))
for p in [R/'AGENTS.md',R/'main/AGENTS.md',R/'main/xiaozhi-server/AGENTS.md']:
 if p.exists():print('REPOSITORY_INSTRUCTIONS',p,p.read_text())
