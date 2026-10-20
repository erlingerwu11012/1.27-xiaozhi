from pathlib import Path
import json,sys
s=Path('/root/prjs/tmp/hardware-followup-20261013');sys.path.insert(0,str(s))
from budget import Budget
rows=[json.loads(x) for x in (s/'final06-results.jsonl').read_text().splitlines()]
for row in rows:
 print(row['group'],row['turn'],row['query'] if 'query' in row else row['case']['query'],row.get('speech'),row['errors'])
 if row['errors']:print('decisions',[x.get('decision') for x in row.get('decisions',[])])
print('budget',Budget().report())


