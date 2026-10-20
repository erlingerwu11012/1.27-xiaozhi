import json,collections,hashlib
from pathlib import Path
stage=Path('/root/prjs/tmp/harness-20261007')
names=['frozen-20261008-clause-final','frozen-20261008-clause-independent','frozen-20261008-clause-unseen']
rows=[]
for name in names:
 for suite in ['single','complex','holdout']:
  p=stage/name/(suite+'.jsonl')
  if p.exists():
   for line in p.read_text().splitlines():
    if line.strip():rows.append(dict(json.loads(line),_suite=suite,_source=name))
pack=json.loads((stage/'pack.json').read_text());hold=json.loads((stage/'holdout.json').read_text());reg=json.loads((stage/'blind-final-release.json').read_text());fresh=json.loads((stage/'unseen-clause-final.json').read_text())
keys={(r['_suite'],r['chain'],r['id'],r['repeat']) for r in rows};tasks=[]
def add(suite,row,repeat,chain):
 if (suite,chain,row['id'],repeat) not in keys:tasks.append({'suite':suite,'row':row,'repeat':repeat,'chain':chain})
for r in pack['cases']:
 add('single',r,0,'candidate')
 # Reuse the existing same-input baseline; do not buy duplicate baseline calls.
for r in pack['complex']:add('complex',r,0,'candidate')
for r in hold+reg:
 add('holdout',r,0,'candidate')
for r in fresh:
 for repeat in range(3):add('holdout',r,repeat,'candidate')
manifest=json.loads((stage/'candidate-manifest.json').read_text());code=hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest()
assert all(r['code_hash']==code for r in rows)
report={'prior_records':len(rows),'prior_candidate':sum(r['chain']=='candidate' for r in rows),'prior_model_events':sum(len(r.get('events',[])) for r in rows),'new_records':len(tasks),'projected_total_records':len(rows)+len(tasks)+6,'task_counts':dict(collections.Counter((r['suite']+'/'+r['chain']) for r in tasks)),'code_hash':code,'row_limit':2000,'new_model_request_limit':2000,'not_started':True}
(stage/'budget-continuation-tasks.json').write_text(json.dumps({'inventory':report,'tasks':tasks,'sources':names},ensure_ascii=False,indent=2));print(json.dumps(report))
