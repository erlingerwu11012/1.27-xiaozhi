from pathlib import Path
import json
S=Path(__file__).parent
r=[json.loads(x) for x in (S/'final-results.jsonl').read_text().splitlines()]
for x in r:
 if x['case']['tool'] is None and ('这次请求没有执行完' in x.get('speech','') or x['errors']):print(json.dumps({k:x.get(k) for k in ['case','outcome','decisions','speech','errors']},ensure_ascii=False))
from budget import Budget
print('budget',Budget(S/'budget.sqlite3').report())
