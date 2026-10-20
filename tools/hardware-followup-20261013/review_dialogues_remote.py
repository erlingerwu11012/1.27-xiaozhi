from pathlib import Path
import json,sys
s=Path('/root/prjs/tmp/hardware-followup-20261013');sys.path.insert(0,str(s));from budget import Budget
rows=[json.loads(x) for x in (s/'final09-results.jsonl').read_text().splitlines()]
print('budget',Budget().report(),'rows',len(rows))
for r in rows:
 if r['group'] in {'combo-01','combo-07','combo-08','combo-09','combo-10','combo-11','combo-12','combo-13','combo-14','combo-15','combo-24','combo-25','combo-26','combo-27','combo-28','combo-29'}:print(r['group'],r['turn'],r['case']['query'],'=>',r.get('speech'),r['errors'])
