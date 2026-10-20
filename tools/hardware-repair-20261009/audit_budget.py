from pathlib import Path
import sqlite3,json,collections
S=Path(__file__).parent
with sqlite3.connect(S/'budget.sqlite3') as d:r=d.execute("SELECT kind,metadata FROM charges").fetchall()
counts=collections.Counter();tokens=collections.Counter()
for kind,meta in r:
 if not meta:counts[(kind,'no_response')]+=1;continue
 x=json.loads(meta);counts[(kind,str(x.get('status',x.get('success'))))]+=1
 for k,v in (x.get('usage') or {}).items():
  if isinstance(v,int):tokens[k]+=v
print(json.dumps({'requests':{str(k):v for k,v in counts.items()},'tokens':dict(tokens)},ensure_ascii=False))
rows=[json.loads(x) for x in (S/'final-results.jsonl').read_text().splitlines()]
for x in rows:
 if x['case']['id'] in ['reg-10','reg-11','reg-12','new-2','holdout-2']:print(json.dumps({k:x.get(k) for k in ['case','outcome','speech','errors','decisions']},ensure_ascii=False))
