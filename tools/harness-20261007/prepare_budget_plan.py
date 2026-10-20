import json,collections
from pathlib import Path
p=Path(__file__).parent;pack=json.loads((p/'pack.json').read_text());hold=json.loads((p/'holdout.json').read_text());fresh=json.loads((p/'unseen-clause-final.json').read_text());reg=json.loads((p/'blind-final-release.json').read_text());reg=[x for x in reg if x['id']=='blind3:7'];assert len(reg)==1
holdout=hold+fresh+reg;tasks=[];baseline=set()
def add(s,row,chain='candidate',repeat=0):tasks.append(dict(suite=s,row=row,chain=chain,repeat=repeat))
for r in pack['cases']:
 add('single',r)
 if r['group']!='negative' and r['tool'] not in baseline:add('single',r,'baseline');baseline.add(r['tool'])
for r in pack['complex']:add('complex',r)
for r in holdout:add('holdout',r)
for repeat in [1,2]:add('holdout',reg[0],repeat=repeat)
plan={'tasks':tasks,'prior_records':904,'prior_recorded_model_events':1165,'total_records_including_wire':904+len(tasks)+7,'record_limit':2000,'additional_model_requests_limit':1000,'sampling':'Every enabled tool:8 positives and4 negatives, common tools20 positives;60 complex and56 holdout cases. First positive per tool has matched current baseline. Known stop regression repeats3. Counts reduced following user API-cost cap; correctness and safety rates unchanged.'}
assert plan['total_records_including_wire']<=2000
(p/'budget-plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2));(p/'budget-holdout.json').write_text(json.dumps(holdout,ensure_ascii=False,indent=2))
print(json.dumps({k:v for k,v in plan.items() if k!='tasks'},ensure_ascii=False))
