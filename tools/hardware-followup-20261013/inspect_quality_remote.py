from pathlib import Path
import json
s=Path('/root/prjs/tmp/hardware-followup-20261013')
for r in map(json.loads,(s/'final09-results.jsonl').read_text().splitlines()):
 if r['group'] in {'combo-01','combo-09','combo-10','combo-14'}:
  print(json.dumps({k:r.get(k) for k in ['group','turn','query','speech','task_before','task_after','outcome']},ensure_ascii=False))
