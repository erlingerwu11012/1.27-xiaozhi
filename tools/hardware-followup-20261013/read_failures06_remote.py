from pathlib import Path
import json
s=Path('/root/prjs/tmp/hardware-followup-20261013')
for line in (s/'development06-results.jsonl').read_text().splitlines():
 row=json.loads(line)
 if row['errors']:
  print('failure',row['query']);print('decisions',[(x.get('decision'),x.get('error')) for x in row.get('decisions',[])])

