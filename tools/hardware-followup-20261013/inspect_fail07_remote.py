from pathlib import Path
import json
s=Path('/root/prjs/tmp/hardware-followup-20261013')
rows=[json.loads(x) for x in (s/'final07-results.jsonl').read_text().splitlines()]
for r in rows:
 if r['errors']:
  print('case',r['case']);print('decisions',json.dumps(r['decisions'],ensure_ascii=False));print('task',r['task_before'],r['task_after']);print('outcome',r['outcome'])
print('log','\n'.join((s/'final07.log').read_text().splitlines()[-12:]))
