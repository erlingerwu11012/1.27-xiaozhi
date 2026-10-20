from pathlib import Path
import json,sys
s=Path('/root/prjs/tmp/hardware-followup-20261013');sys.path.insert(0,str(s));from budget import Budget
rows=[json.loads(x) for x in (s/'final09-results.jsonl').read_text().splitlines()]
print('budget',Budget().report());print('rows',len(rows),'failures',[{k:r[k] for k in ['group','turn','errors','speech']} for r in rows if r['errors']]);print('recent',[(r['group'],r['turn'],r.get('speech')) for r in rows[-6:]])

