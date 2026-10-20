import json,re
from pathlib import Path
p=Path(__file__).parent;secrets=set()
def visit(x):
 if isinstance(x,dict):
  for k,v in x.items():
   if re.search('api.?key|secret|password|token',k,re.I) and isinstance(v,str) and len(v)>8:secrets.add(v)
   visit(v)
 elif isinstance(x,list):
  for v in x:visit(v)
for n in ['runtime-config.json','device-config.json']:visit(json.loads((p/'private-backup'/n).read_text()))
files=[f for f in (p/'delivery').iterdir() if f.is_file()];violations=[]
for f in files:
 text=f.read_text()
 if any(v in text for v in secrets):violations.append(f.name)
assert not violations,'private_export_detected'
print(json.dumps({'export_files':len(files),'secret_value_matches':0}))
