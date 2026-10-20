import hashlib,json,tarfile
from pathlib import Path
stage=Path(__file__).parent
base=json.loads((stage/'baseline.json').read_text())
changes=[]
for p in (stage/'candidate').rglob('*'):
 if p.is_file():
    rel=p.relative_to(stage/'candidate').as_posix();digest=hashlib.sha256(p.read_bytes()).hexdigest()
    if base.get(rel)!=digest:changes.append({'path':rel,'baseline_sha256':base.get(rel),'candidate_sha256':digest})
(stage/'manifest.json').write_text(json.dumps(changes,indent=2))
with tarfile.open(stage/'changes.tgz','w:gz') as tar:
 for r in changes:tar.add(stage/'candidate'/r['path'],arcname=r['path'])
print(json.dumps({'modified':len(changes),'files':[r['path'] for r in changes]},indent=2))
