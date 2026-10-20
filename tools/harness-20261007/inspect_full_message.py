import json,sys
from pathlib import Path
p=Path('/root/prjs/tmp/harness-20261007')/sys.argv[1]
f=p/'full-message-evidence.json'
if f.exists():
 for r in json.loads(f.read_text()):
  o=r['outcome'];print(json.dumps({'user':r['user'],'reply':o['reply'],'error':o.get('error'),'results':o['results'],'model_calls':o.get('model_calls'),'wire':r['wire'],'events':r['events']},ensure_ascii=False))
print((p/'auxiliary-progress.log').read_text()[-7000:])
