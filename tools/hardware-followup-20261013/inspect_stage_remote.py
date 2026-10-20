from pathlib import Path
import json,sys
s=Path('/root/prjs/tmp/hardware-followup-20261013');sys.path.insert(0,str(s));from budget import Budget
print('api_evidence',json.loads((s/'api-package-evidence-05.json').read_text()))
print('budget',Budget().report());rows=[json.loads(x) for x in (s/'final09-results.jsonl').read_text().splitlines()];print('rows',len(rows),'failures',[{'group':r['group'],'turn':r['turn'],'errors':r['errors']} for r in rows if r['errors']])
