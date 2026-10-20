import json
from pathlib import Path
S=Path(__file__).parent;rows=[json.loads(x) for x in (S/'final-results.jsonl').read_text().splitlines()]
for r in rows:
 if r['errors']:print(json.dumps({'id':r['case']['id'],'query':r['case']['query'],'speech':r.get('speech'),'errors':r['errors'],'decision':[d.get('decision') for d in r.get('decisions',[])]},ensure_ascii=False))
print('rows',len(rows))
