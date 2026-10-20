from pathlib import Path
import json
s=Path('/root/prjs/tmp/hardware-followup-20261013')
for line in (s/'final01-results.jsonl').read_text().splitlines():
 r=json.loads(line)
 if r['errors']:print(json.dumps({k:r.get(k) for k in ['case','state','outcome','calls','decisions']},ensure_ascii=False))
