from pathlib import Path
import json,shutil
S=Path(__file__).parent
for suffix in ['results.jsonl','freeze.json','console.log','summary.json']:
 p=S/('resume-final-'+suffix);p.rename(S/('resume-relative-failures-'+suffix))
p=S/'final-cases.json';rows=json.loads(p.read_text());shutil.copy2(p,S/'before-relative-cases.json')
for r in rows:
 if r['id']=='reg-166':r['required']=[x+'|(?:一半|50[%％])' for x in r['required']]
 if r['id']=='holdout-52':r['independent_holdout']=False;r['development_from_failed_holdout']=True
p.write_text(json.dumps(rows,ensure_ascii=False,indent=2))
(S/'relative-review.json').write_text(json.dumps({'actual_failures':['reg-91 explicit relative operation read only and invalid reference','holdout-52 correct explanation replaced by no operation because claim guard joined unrelated clauses'],'oracle_false_positives':['reg-99/reg-100/holdout-21 pre-operation intermediate read compared with final state','reg-166 half complete and no lost prior progress correctly stated'],'original_outputs_retained':True,'source_revalidation_required':True,'independent_holdout':sum(bool(r.get('independent_holdout')) for r in rows)},indent=2))
print('ready',len(rows))
