from pathlib import Path
import os,signal,json
pid=159360
p=Path('/proc')/str(pid)/'cmdline'
if p.exists():
 assert b'/root/prjs/tmp/hardware-repair-20261009/run_model.py' in p.read_bytes();os.kill(pid,signal.SIGTERM)
S=Path(__file__).parent
rows=[json.loads(x) for x in (S/'final-results.jsonl').read_text().splitlines()]
for r in rows:
 if r['errors']:
  print(json.dumps({k:r.get(k) for k in ['case','outcome','decisions','calls','speech','errors']},ensure_ascii=False))
from budget import Budget
print('BUDGET',Budget(S/'budget.sqlite3').report())
