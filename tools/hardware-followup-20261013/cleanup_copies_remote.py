from pathlib import Path
import hashlib,subprocess,json,os
s=Path('/root/prjs/tmp/hardware-followup-20261013');base=s/'baseline-work';formal=Path('/root/prjs/releases/harness-stream-20261012/runtime')
commands=[]
for p in Path('/proc').iterdir():
 if p.name.isdigit():
  try:commands.append((p/'cmdline').read_bytes())
  except OSError:pass
removed=[]
for p in (base/'models').rglob('*'):
 if not p.is_file() or p.stat().st_size<8*1024*1024:continue
 assert p.resolve().is_relative_to((base/'models').resolve()) and not p.is_symlink()
 original=formal/p.relative_to(base);assert original.is_file() and original.stat().st_size==p.stat().st_size
 digest=hashlib.sha256(p.read_bytes()).hexdigest();assert digest==hashlib.sha256(original.read_bytes()).hexdigest()
 assert not any(str(p).encode() in cmd for cmd in commands)
 removed.append({'path':str(p),'restore_source':str(original),'bytes':p.stat().st_size,'sha256':digest});p.unlink()
p=s/'manager-api/xiaozhi-esp32-api.jar'
assert p.resolve().parent==s/'manager-api' and not any(str(p).encode() in cmd for cmd in commands)
original=Path('/root/prjs/releases/harness-stream-20261012/xiaozhi-esp32-api.jar');digest=hashlib.sha256(p.read_bytes()).hexdigest();assert digest==hashlib.sha256(original.read_bytes()).hexdigest()
removed.append({'path':str(p),'restore_source':str(original),'bytes':p.stat().st_size,'sha256':digest});p.unlink()
(s/'rebuildable-cleanup-03.json').write_text(json.dumps(removed,indent=2));v=os.statvfs('/root/prjs');print('removed_bytes',sum(x['bytes'] for x in removed),'available_bytes',v.f_bavail*v.f_frsize)
