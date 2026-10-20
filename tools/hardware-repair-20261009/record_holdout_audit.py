from pathlib import Path
import json,hashlib,time
S=Path(__file__).parent
rows=[json.loads(x) for x in (S/'resume-final-results.jsonl').read_text().splitlines()]
excluded={'holdout-6':'Used to repair three-character authoritative memory readback','holdout-21':'Used to repair final-outcome oracle excluding intermediate pre-write reads'}
ids=[x['case']['id'] for x in rows if x['case'].get('independent_holdout') and x['case']['id'] not in excluded]
r={'passed':len(ids)>=60,'original_marked_count':sum(bool(x['case'].get('independent_holdout')) for x in rows),'audited_independent_count':len(ids),'excluded_debug_samples':excluded,'independent_ids':ids,'results_sha256':hashlib.sha256((S/'resume-final-results.jsonl').read_bytes()).hexdigest(),'at':time.time(),'raw_frozen_records_unchanged':True}
assert r['passed']
(S/'resume-holdout-audit.json').write_text(json.dumps(r,ensure_ascii=False,indent=2))
for n in ['resume-release-gate.json','resume-acceptance-summary.json']:
 p=S/n;b=S/('before-holdout-audit-'+n)
 if not b.exists():b.write_bytes(p.read_bytes())
p=S/'resume-acceptance-summary.json';a=json.loads(p.read_text());a['independent_holdout']=len(ids);a['holdout_marking_audit']='resume-holdout-audit.json';p.write_text(json.dumps(a,ensure_ascii=False,indent=2))
print(json.dumps({'audited_independent_count':len(ids),'passed':True,'raw_records_changed':False}))
