from pathlib import Path
import json
S=Path(__file__).parent
for line in (S/'resume-final-results.jsonl').read_text().splitlines():
 r=json.loads(line)
 if r['case']['id'] in {'reg-180','reg-164'}:print(json.dumps({k:r.get(k) for k in ['case','speech','outcome','decisions']},ensure_ascii=False))
