from pathlib import Path
import json,sys,shutil
s=Path('/root/prjs/tmp/hardware-followup-20261013');sys.path.insert(0,str(s));from budget import Budget
print('budget',Budget().report(),'disk_free',shutil.disk_usage('/').free)
for r in map(json.loads,(s/'final09-results.jsonl').read_text().splitlines()):
 print(r['group'],r['turn'],r['query'],'=>',r.get('speech'),r['errors'])
