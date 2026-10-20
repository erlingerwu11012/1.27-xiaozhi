import json,hashlib,shutil,os,subprocess
from pathlib import Path
root=Path('/root/prjs/xiaozhi-esp32-server');candidate=Path('/root/prjs/tmp/bailian-memory-product');out=Path('/root/prjs/tmp/memory-continuity-release-20260930')
assert json.loads((out/'tests.json').read_text())['passed']
old=json.loads((out/'manifest.json').read_text());new=json.loads(Path('/tmp/manifest.json').read_text())
changed=[name for name in new if new[name]!=old[name]]
assert changed and all(name.startswith('main/xiaozhi-server/') for name in changed)
for name in changed:
 assert hashlib.sha256((root/name).read_bytes()).hexdigest()==old[name]
 assert hashlib.sha256((candidate/name).read_bytes()).hexdigest()==new[name]
subprocess.run(['pm2','stop','xiaozhi-server'],capture_output=True,check=True)
for name in changed:
 target=root/name;temporary=target.with_name(target.name+'.harden-next');shutil.copy2(candidate/name,temporary);os.replace(temporary,target)
subprocess.run(['pm2','restart','xiaozhi-server'],capture_output=True,check=True)
(out/'manifest.json').write_text(json.dumps(new,indent=2))
published=json.loads((out/'published.json').read_text());published['post_release_hardening']=changed;(out/'published.json').write_text(json.dumps(published,indent=2))
print(json.dumps({'voice_hardening_published':True,'changed_files':len(changed)}))
