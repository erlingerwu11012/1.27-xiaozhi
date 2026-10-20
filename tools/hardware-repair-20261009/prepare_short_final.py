from pathlib import Path
import json,shutil,time
S=Path(__file__).parent
for suffix in ['results.jsonl','freeze.json','console.log','summary.json']:
 p=S/('resume-final-'+suffix)
 if p.exists():p.rename(S/('resume-short-memory-failures-'+suffix))
p=S/'final-cases.json';rows=json.loads(p.read_text());shutil.copy2(p,S/'before-short-memory-cases.json')
for r in rows:
 if r['id']=='holdout-50':r['independent_holdout']=False;r['development_from_failed_holdout']=True
p.write_text(json.dumps(rows,ensure_ascii=False,indent=2))
(S/'short-memory-review.json').write_text(json.dumps({'actual_failures':['holdout-6 short authoritative replacement 喝绿茶 excluded by minimum 4 codepoint filter','holdout-7 lost latest fact after failed correction readback'],'additional_speech_fix':'Never claim stored memory without a completed write; correct once rather than replacing ordinary explanation','original_outputs_retained':True,'independent_holdout':sum(bool(r.get('independent_holdout')) for r in rows),'at':time.time()},ensure_ascii=False,indent=2))
print('ready',len(rows))
