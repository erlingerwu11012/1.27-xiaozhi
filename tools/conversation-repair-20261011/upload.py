"""Package only candidate source and test scripts; no private runtime configs."""
from pathlib import Path
import tarfile,subprocess
S=Path(__file__).resolve().parent
with tarfile.open(S/'changes.tgz','w:gz') as t:
 for root in ['work','java']:
  for p in (S/root).rglob('*'):
   if p.is_file() and '__pycache__' not in p.parts:t.add(p,arcname=p.relative_to(S),recursive=False)
 for p in S.glob('*.py'):
  if p.name not in {'upload.py','edit_candidate.py','edit_memory_backend.py','edit_lifecycle.py'}:t.add(p,arcname=p.name)
 for name in ['cases.json','cases.sha256']:
  if (S/name).exists():t.add(S/name,arcname=name)
print('archive_bytes',(S/'changes.tgz').stat().st_size)
