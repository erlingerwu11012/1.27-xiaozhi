import json
from pathlib import Path
S=Path(__file__).parent
for x in map(json.loads,(S/'final-results.jsonl').read_text().splitlines()):
 if x['errors']:print(json.dumps({k:x.get(k) for k in ['case','outcome','decisions','calls','errors']},ensure_ascii=False,default=str))
from budget import Budget
print(Budget(S/'budget.sqlite3').report())
