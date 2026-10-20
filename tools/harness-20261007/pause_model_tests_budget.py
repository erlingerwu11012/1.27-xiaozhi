import json,os,signal,time
from pathlib import Path
stage=Path('/root/prjs/tmp/harness-20261007');stopped=[];rows={}
for name in ['frozen-20261008-clause-final','frozen-20261008-clause-independent','frozen-20261008-clause-unseen']:
 p=stage/name
 for fn,key in [('jobs.json','jobs'),('blind-job.json',None)]:
  f=p/fn
  if not f.exists():continue
  d=json.loads(f.read_text());jobs=d[key] if key else [d]
  for j in jobs:
   pid=j['pid'];proc=Path('/proc')/str(pid)
   if not proc.exists():continue
   argv=proc.joinpath('cmdline').read_bytes().split(b'\0')
   if name.encode() in argv and any(x in argv for x in [str(stage/'launch_tests.py').encode(),str(stage/'launch_blind.py').encode()]) and os.getpgid(pid)==pid:
    os.killpg(pid,signal.SIGTERM);stopped.append(pid)
 p.joinpath('budget-paused.json').write_text(json.dumps({'timestamp':time.time(),'reason':'User requested lower API spending and 2000-row cap for future tests. No new model calls until evidence inventory.'},indent=2))
 rows[name]={s:sum(1 for x in (p/(s+'.jsonl')).read_text().splitlines() if x.strip()) if (p/(s+'.jsonl')).exists() else 0 for s in ['single','complex','holdout']}
print(json.dumps({'test_workers_stopped':stopped,'records':rows,'production_untouched':True}))
