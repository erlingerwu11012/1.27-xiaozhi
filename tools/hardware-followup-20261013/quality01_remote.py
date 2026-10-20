from pathlib import Path
import sys,subprocess,tarfile,json
s=Path('/root/prjs/tmp/hardware-followup-20261013');sys.path.insert(0,str(s))
with tarfile.open(s/'source-delta.tgz') as a:
 assert all((s/m.name).resolve().is_relative_to(s) and 'budget.sqlite3' not in m.name for m in a.getmembers());a.extractall(s,filter='data')
from budget import Budget
b=Budget()
with (s/'quality-unit-01.log').open('x') as log:r=subprocess.run([sys.executable,str(s/'test_quality_followup.py')],cwd=s,stdout=log,stderr=subprocess.STDOUT)
print('quality unit',r.returncode);print((s/'quality-unit-01.log').read_text());print('budget',b.report())
rows=[json.loads(x) for x in (s/'final09-results.jsonl').read_text().splitlines()]
for row in rows:
 if (row['group'] in ['combo01','combo10','combo14','combo09'] and ((row['group']=='combo01' and row['turn'] in [0,1]) or (row['group'] in ['combo10','combo14'] and row['turn']==0) or (row['group']=='combo09' and row['turn'] in [3,4]))) or (row.get('holdout') and row['turn']==1):
  print(json.dumps({k:row.get(k) for k in ['group','turn','query','speech','dialogue_history','outcome']},ensure_ascii=False))
print('summary', (s/'final09-summary.json').read_text())
