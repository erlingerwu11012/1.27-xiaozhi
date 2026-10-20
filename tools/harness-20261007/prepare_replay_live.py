import json
from pathlib import Path
p=Path(__file__).parent;d=p/'frozen-20261008-budget-delta'
rows=[json.loads(x) for x in (d/'offline-replay.jsonl').read_text().splitlines() if x.strip()]
tasks=[{'suite':r['suite'],'row':r['original_row'],'chain':'candidate','repeat':r['repeat']} for r in rows if r['needs_live']]
assert len(tasks)==2
plan={'tasks':tasks,'prior_records':1839,'total_records_including_wire':1841,'record_limit':2000,'additional_model_requests_limit':1000,'reason':'These recorded scenarios lack a reusable complete model decision; verify with actual model instead of manufacturing a replay.'}
(p/'budget-plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2));(p/'budget-replay-live-holdout.json').write_text(json.dumps([t['row'] for t in tasks],ensure_ascii=False,indent=2))
print(json.dumps({'live_followups':len(tasks),'users':[t['row'] for t in tasks]},ensure_ascii=False))
