"""Remote candidate staging. Records production versions and forbids path escapes."""
from pathlib import Path
import tarfile,json,hashlib
prod=Path('/root/prjs/xiaozhi-esp32-server')
candidate=Path('/root/prjs/tmp/bailian-memory-product')
release=Path('/root/prjs/tmp/context-memory-release-20260929')
release.mkdir(exist_ok=True)
manifest=json.loads(Path('/tmp/context-memory-manifest.json').read_text())
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
base=release/'baseline.json'
baseline=json.loads(base.read_text()) if base.exists() else {}
for name in manifest:
    if name not in baseline:baseline[name]=digest(prod/name)
base.write_text(json.dumps(baseline,indent=2))
with tarfile.open('/tmp/context-memory-overlay.tar.gz') as archive:
    for item in archive.getmembers():
        assert item.name in manifest and item.isfile()
        assert (candidate/item.name).resolve().is_relative_to(candidate.resolve())
    archive.extractall(candidate,filter='data')
assert all(digest(candidate/n)==h for n,h in manifest.items())
(release/'manifest.json').write_text(json.dumps(manifest,indent=2))
print(json.dumps({'staged':True,'files':len(manifest),'release':str(release)}))
