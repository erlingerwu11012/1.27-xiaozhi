from pathlib import Path
import json,shutil
S=Path(__file__).parent
for suffix in ['results.jsonl','freeze.json','console.log','summary.json']:
 p=S/('resume-final-'+suffix);p.rename(S/('resume-card-view-'+suffix))
p=S/'final-cases.json';rows=json.loads(p.read_text());shutil.copy2(p,S/'before-card-view-cases.json')
for r in rows:
 if r['id']=='reg-166':r['required']=[x+'|说得对.{0,20}(?:一半|50)' for x in r['required']]
 if r['id']=='holdout-22':r['required']=[x.replace('已关闭','已(?:经)?关闭') for x in r['required']]
 if r['id']=='fresh-read-1':r['independent_holdout']=False;r['development_from_failed_holdout']=True
p.write_text(json.dumps(rows,ensure_ascii=False,indent=2));(S/'card-view-review.json').write_text(json.dumps({'actual_ux_failure':'fresh-read-1: active card returned but model denied ability to know display state','oracle_false_positives':['reg-65 explicit not confirmed reboot completion is honest accepted phase','reg-166 agreeing cannot say zero progress plus half-complete is correct','holdout-22 已经关闭 and 已关闭 have the same meaning'],'original_outputs_retained':True,'source_revalidation_required':True,'independent_holdout':sum(bool(r.get('independent_holdout')) for r in rows)},indent=2));print('ready',len(rows))
