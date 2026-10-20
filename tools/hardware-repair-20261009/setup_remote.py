
import sys,os,json,shutil,subprocess,importlib.util,hashlib,time,gzip
from pathlib import Path
stage=Path('/root/prjs/tmp/hardware-repair-20261009');stage.mkdir(exist_ok=True,mode=0o700)
backup=stage/'baseline';backup.mkdir(exist_ok=True,mode=0o700)
release=Path('/root/prjs/releases/experience-repair-20261009');runtime=release/'runtime'
if not (backup/'runtime.tgz').exists():subprocess.run(['tar','-czf',str(backup/'runtime.tgz'),'-C',str(runtime),'.'],check=True)
repo=Path('/root/prjs/xiaozhi-esp32-server')
if not (backup/'tracked.diff').exists():(backup/'tracked.diff').write_bytes(subprocess.check_output(['git','-C',str(repo),'diff','--binary']))
if not (backup/'status.txt').exists():(backup/'status.txt').write_bytes(subprocess.check_output(['git','-C',str(repo),'status','--short']))
spec=importlib.util.spec_from_file_location('previous_release',release/'release.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
if not (backup/'database-backup-metadata.json').exists():
 m.B=backup;m.backup_database()
 for name in ['schema.sql','memory-private.sql']:
  p=backup/name
  with p.open('rb') as src,gzip.open(str(p)+'.gz','wb') as dst:shutil.copyfileobj(src,dst)
  p.unlink()
if not (stage/'work').exists():
 shutil.copytree(runtime,stage/'work',ignore=shutil.ignore_patterns('data','models','logs','tmp','__pycache__','.git','*.pyc'))
 for name in ['data','models','logs']:
  if (runtime/name).exists():(stage/'work'/name).symlink_to(runtime/name,target_is_directory=True)
old=Path('/root/prjs/tmp/experience-repair-20261009')
for name in ['bootstrap.py','budget.py','wire_conversation.py','stateful_device.py','experience_protocol.py','pack.json','private-test-env.json','api-test-secret']:
 if not (stage/name).exists():shutil.copy2(old/name,stage/name)
p=stage/'budget.py';s=p.read_text();s=s.replace("'case':4300,'model':2200","'case':2000,'model':600");p.write_text(s)
if not (stage/'manager-api').exists():shutil.copytree(old/'manager-api',stage/'manager-api',ignore=shutil.ignore_patterns('target','.git','node_modules'))
manifest={'created':time.time(),'runtime':str(runtime),'backup':str(backup),'disk_free':shutil.disk_usage(stage).free,'config_retained_server_only':True}
(stage/'baseline.json').write_text(json.dumps(manifest,indent=2))
print(json.dumps(manifest))
