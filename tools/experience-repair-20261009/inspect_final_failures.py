import json
from pathlib import Path
S=Path(__file__).parent
rows=[json.loads(x) for x in (S/'final-results.jsonl').read_text().splitlines()]
for r in rows:
 if r['errors'] and r['case']['id'] in [31,32,34,1,3]:print(json.dumps({k:r.get(k) for k in ['case','outcome','calls','wire','readback','decisions']},ensure_ascii=False,default=str))
