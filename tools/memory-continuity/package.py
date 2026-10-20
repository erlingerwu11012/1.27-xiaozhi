import hashlib,json,tarfile,shutil
from pathlib import Path
here=Path(__file__).resolve().parent;root=here.parents[1]/'tmp/bailian-memory-product/server'
names=json.loads((here/'changed.json').read_text())
delivery=here/'delivery';delivery.mkdir(exist_ok=True)
manifest={}
with tarfile.open(here/'overlay.tar.gz','w:gz') as archive:
 for name in names:
  source=root/name;target=delivery/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
  manifest[name]=hashlib.sha256(source.read_bytes()).hexdigest();archive.add(source,arcname=name)
(here/'manifest.json').write_text(json.dumps(manifest,indent=2))
print(json.dumps({'source_files':len(names)}))
