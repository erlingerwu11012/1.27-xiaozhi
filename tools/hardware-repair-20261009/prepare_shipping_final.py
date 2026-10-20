from pathlib import Path
import json,shutil
S=Path(__file__).parent
for suffix in ['results.jsonl','freeze.json','console.log','summary.json']:
 p=S/('resume-final-'+suffix)
 if p.exists():p.rename(S/('resume-before-shipping-review-'+suffix))
p=S/'final-cases.json';rows=json.loads(p.read_text());shutil.copy2(p,S/'before-shipping-cases.json')
for r in rows:
 if r['id']=='holdout-43':r['independent_holdout']=False;r['development_from_failed_holdout']=True
p.write_text(json.dumps(rows,ensure_ascii=False,indent=2))
(S/'shipping-review.json').write_text(json.dumps({'actual_manual_failure':'holdout-43 only ordered but reply claimed book in transit','automatic_checks_passed_but_manual_review_rejected':True,'original_outputs_retained':True,'independent_holdout':sum(bool(r.get('independent_holdout')) for r in rows)},indent=2))
print('ready',len(rows))
