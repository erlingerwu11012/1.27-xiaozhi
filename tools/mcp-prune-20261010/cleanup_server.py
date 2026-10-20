from pathlib import Path
import os,json,hashlib,shutil,subprocess,time,gzip
stage=Path('/root/prjs/tmp/mcp-prune-20261010');base=Path('/root/prjs/tmp').resolve();before=shutil.disk_usage('/').free
roots=[base/n for n in ['hardware-repair-20261009/manager-api','experience-repair-20261009/manager-api','nvs-habit-renewal-20261007/work/manager-api']]
# Keep every deployment/recovery copy. Only disposable build jars are removed.
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
backups={}
for p in Path('/root/prjs/releases').rglob('*.jar'):
 if p.is_file():backups.setdefault((p.stat().st_size,sha(p)),p)
openfiles=set();commands=[]
for proc in Path('/proc').iterdir():
 if not proc.name.isdigit():continue
 try:
  commands.append((proc/'cmdline').read_bytes().replace(b'\0',b' ').decode(errors='replace'))
  for fd in (proc/'fd').iterdir():
   try:openfiles.add(str(fd.resolve()))
   except OSError:pass
 except (OSError,PermissionError):pass
actions=[]
for root in roots:
 assert root.resolve().is_relative_to(base) and (root/'pom.xml').exists()
 for rel in ['target/xiaozhi-esp32-api.jar','xiaozhi-esp32-api.jar']:
  p=root/rel
  if not p.is_file() or p.is_symlink():continue
  assert p.resolve().is_relative_to(base)
  if str(p) in openfiles or any(str(p) in c for c in commands):continue
  key=(p.stat().st_size,sha(p));keep=backups.get(key)
  if keep is None:continue
  p.unlink();actions.append({'path':str(p),'bytes':key[0],'sha256':key[1],'matching_backup_retained':str(keep),'kind':'duplicate_build_jar'})
 # Preserve old isolated test logs in gzip, skip anything open by a process.
 logs=root/'logs'
 for p in logs.rglob('*.log') if logs.exists() else []:
  if p.is_symlink() or str(p.resolve()) in openfiles or p.stat().st_size<1024*1024:continue
  assert p.resolve().is_relative_to(base)
  dest=p.with_name(p.name+'.gz')
  if dest.exists():continue
  size=p.stat().st_size;digest=sha(p)
  with p.open('rb') as src,gzip.open(dest,'wb',compresslevel=6) as out:shutil.copyfileobj(src,out)
  h=hashlib.sha256()
  with gzip.open(dest,'rb') as f:
   for b in iter(lambda:f.read(1048576),b''):h.update(b)
  assert h.hexdigest()==digest
  p.unlink();actions.append({'path':str(p),'archive':str(dest),'bytes_reclaimed':size-dest.stat().st_size,'kind':'compress_closed_test_log'})
subprocess.run(['apt-get','clean'],check=True,capture_output=True)
after=shutil.disk_usage('/').free
result={'before_free':before,'after_free':after,'reclaimed_bytes':after-before,'actions':actions,'production_and_backups_retained':True,'at':time.time()}
(stage/'cleanup.json').write_text(json.dumps(result,indent=2));print(json.dumps({'reclaimed_gib':round((after-before)/1024**3,3),'free_gib':round(after/1024**3,3),'actions':len(actions)}))
