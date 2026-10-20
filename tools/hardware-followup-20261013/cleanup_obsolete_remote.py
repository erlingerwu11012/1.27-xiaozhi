from pathlib import Path
import shutil,json,hashlib,time
s=Path('/root/prjs/tmp/hardware-followup-20261013')
print('disk_before',shutil.disk_usage('/root/prjs')._asdict())
commands=[]
for p in Path('/proc').iterdir():
 if p.name.isdigit():
  try:commands.append((p/'cmdline').read_bytes())
  except OSError:pass
removed=[]
for name in ['candidate-api.jar','candidate-api-02.jar','candidate-update.tgz']:
 p=(s/name).resolve();assert p.parent==s and p.is_file()
 assert not any(str(p).encode() in cmd for cmd in commands)
 digest=hashlib.sha256(p.read_bytes()).hexdigest();size=p.stat().st_size
 p.unlink();removed.append({'path':str(p),'bytes':size,'sha256':digest,'reason':'superseded isolated rebuildable artifact; source and package evidence preserved'})
(s/'rebuildable-cleanup-02.json').write_text(json.dumps(removed,indent=2));print('removed_bytes',sum(x['bytes'] for x in removed));print('disk_after',shutil.disk_usage('/root/prjs')._asdict())
