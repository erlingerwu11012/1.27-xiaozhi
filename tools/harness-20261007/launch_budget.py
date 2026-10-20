import json,os,subprocess,sys,time
from pathlib import Path
p=Path(__file__).parent/'frozen-20261008-budget-final'
assert not (p/'budget-job.json').exists()
with (p/'budget-progress.log').open('ab') as log:
 c=subprocess.Popen([sys.executable,str(p/'run_budget_worker.py')],cwd=p,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
(p/'budget-job.json').write_text(json.dumps({'pid':c.pid,'started_at':time.time()}));print(json.dumps({'worker':c.pid}))
