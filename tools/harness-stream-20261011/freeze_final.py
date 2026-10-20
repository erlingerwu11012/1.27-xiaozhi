from pathlib import Path
import json,hashlib,time,sys
S=Path(__file__).parent;name=sys.argv[1];out=S/(name+'-frozen.json');assert not out.exists()
files={}
for folder in ('work','java'):
 for p in (S/folder).rglob('*'):
  if p.is_file() and p.suffix in {'.py','.java','.txt'} and '__pycache__' not in p.relative_to(S).parts and not any(x in p.relative_to(S).parts for x in ('data','logs','tmp')):files[str(p.relative_to(S))]=hashlib.sha256(p.read_bytes()).hexdigest()
for p in S.glob('*.py'):files[p.name]=hashlib.sha256(p.read_bytes()).hexdigest()
for name in ('cases-v2.json','cases-v2.sha256','fixture-corrections.json','manager-api/target/xiaozhi-esp32-api.jar'):
 files[name]=hashlib.sha256((S/name).read_bytes()).hexdigest()
out.write_text(json.dumps({'created':time.time(),'files':files,'production_modified':False},indent=2))
print(out.name,len(files),flush=True)
