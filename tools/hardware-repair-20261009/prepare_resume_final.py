from pathlib import Path
import json,shutil,time
S=Path(__file__).parent
p=S/'final-cases.json';rows=json.loads(p.read_text());backup=S/'before-resume-final-cases.json';assert not backup.exists();shutil.copy2(p,backup)
tuned={'holdout-2','holdout-4','holdout-5','holdout-7','holdout-38','holdout-49'}
for r in rows:
 if r['id'] in tuned:r['independent_holdout']=False;r['development_from_failed_holdout']=True
p.write_text(json.dumps(rows,ensure_ascii=False,indent=2));(S/'resume-corpus-review.json').write_text(json.dumps({'time':time.time(),'queries_removed':0,'expectations_weakened':False,'retained_failed_ids':sorted(tuned),'independent_holdout_count':sum(bool(r.get('independent_holdout')) for r in rows),'reason':'These six former holdout failures informed fixes; retained as regressions rather than counted as independent holdout.'},indent=2))
shutil.copy2(S/'regression-summary.json',S/'resume-regression-summary.json')
print('cases',len(rows),'independent',sum(bool(r.get('independent_holdout')) for r in rows))
