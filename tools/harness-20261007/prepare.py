import hashlib,json,os,shutil,tarfile
from pathlib import Path
stage=Path('/root/prjs/tmp/harness-20261007');root=Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server')
stage.mkdir(exist_ok=True,parents=True);os.chmod(stage,0o700)
if (stage/'baseline.json').exists():raise RuntimeError('existing baseline must not be overwritten')
files=[]
for folder in ['core','config','plugins_func','test']:
 for p in (root/folder).rglob('*'):
  if p.is_file() and p.suffix in {'.py','.yaml'} and '__pycache__' not in p.parts and 'assets' not in p.parts:
   files.append(p)
for rel in ['app.py','requirements.txt','requirements-llm.txt']:
 if (root/rel).exists():files.append(root/rel)
baseline={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
with tarfile.open(stage/'source.tgz','w:gz') as archive:
 for p in files:archive.add(p,arcname=str(p.relative_to(root)))
(stage/'baseline.json').write_text(json.dumps(baseline,indent=2))
private=stage/'private-backup';private.mkdir();os.chmod(private,0o700)
for rel in ['data/.config.yaml','data/.mcp_server_settings.json']:
 p=root/rel
 if p.exists():shutil.copy2(p,private/p.name);os.chmod(private/p.name,0o600)
print(json.dumps({'backup':str(stage),'source_files':len(files)}))
