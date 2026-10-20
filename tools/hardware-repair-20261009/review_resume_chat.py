from pathlib import Path
import json
S=Path(__file__).parent
rows=[json.loads(x) for x in (S/'resume-final-results.jsonl').read_text().splitlines()]
for x in rows:
 if x['case']['tool'] is None or x['case']['id'] in {'reg-53','reg-54','reg-102','reg-164','reg-180'}:print(x['case']['id']+' | '+x['case']['query']+' | '+x.get('speech','')+' | '+str(x['errors']))
