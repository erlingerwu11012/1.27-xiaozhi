from pathlib import Path
import json
S=Path(__file__).parent;files=[]
for p in S.glob('*results.jsonl'):
 count=errors=0
 try:
  for line in p.read_text().splitlines():
   r=json.loads(line)
   if 'case' not in r or 'errors' not in r:continue
   count+=1;errors+=bool(r['errors'])
 except (ValueError,UnicodeError):continue
 if errors:files.append({'file':p.name,'cases':count,'failed_rows':errors})
(S/'retained-failures-index.json').write_text(json.dumps(files,indent=2));print(json.dumps(files))
