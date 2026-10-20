import hashlib,json
from pathlib import Path
stage=Path(__file__).parent
old=json.loads((stage/'production-backup/deployment.json').read_text())['protected']
changes=[]
for name,expected in old.items():
 p=Path(name);current=hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
 if current!=expected:changes.append({'path':name,'before':expected,'after':current,'modified_at':p.stat().st_mtime if p.exists() else None})
print(json.dumps({'changed':changes},indent=2))
if changes:
 from datetime import datetime
 for row in changes:
    print(row['path'],datetime.fromtimestamp(row['modified_at']).isoformat())
