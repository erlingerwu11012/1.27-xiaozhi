import json
from pathlib import Path
S=Path(__file__).parent
for r in map(json.loads,(S/'postfix-focused-results.jsonl').read_text().splitlines()):
 if r['errors']:print(json.dumps({'id':r['case']['id'],'outcome':r.get('outcome'),'decisions':r.get('decisions'),'errors':r['errors']},ensure_ascii=False))
from budget import Budget
print(Budget(S/'budget.sqlite3').report())
