import json,hashlib,shutil
from pathlib import Path
root=Path('/root/prjs/xiaozhi-esp32-server');candidate=Path('/root/prjs/tmp/bailian-memory-product');out=Path('/root/prjs/tmp/memory-continuity-release-20260930')
assert json.loads((out/'tests.json').read_text())['passed']
old=json.loads((out/'manifest.json').read_text());new=json.loads(Path('/tmp/manifest.json').read_text());changed=[n for n in new if new[n]!=old[n]]
assert changed and all('/src/test/' in n for n in changed)
for n in changed:
 assert hashlib.sha256((root/n).read_bytes()).hexdigest()==old[n]
 assert hashlib.sha256((candidate/n).read_bytes()).hexdigest()==new[n]
 shutil.copy2(candidate/n,root/n)
(out/'manifest.json').write_text(json.dumps(new,indent=2))
print(json.dumps({'saved_test_sources':len(changed),'runtime_changed':False}))
