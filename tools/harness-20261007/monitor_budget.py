import json,sys,collections,sqlite3
from pathlib import Path
p=Path('/root/prjs/tmp/harness-20261007')/(sys.argv[1] if len(sys.argv)>1 else 'frozen-20261008-budget-final');f=p/'budget-results.jsonl';rows=[json.loads(x) for x in f.read_text().splitlines() if x.strip()] if f.exists() else []
print(json.dumps({'records':len(rows),'expected':len(json.loads((p/'budget-plan.json').read_text())['tasks']),'chains':dict(collections.Counter(x['chain'] for x in rows)),'candidate_failures':[{'id':x['id'],'suite':x['suite']} for x in rows if x['chain']=='candidate' and not x['passed']]}))
for r in rows:
 if r['chain']=='candidate' and not r['passed']:
  print(json.dumps({'id':r['id'],'expected':r.get('expected_arguments'),'turns':[{'user':t['user'],'expected':t.get('expected'),'reply':t['outcome']['reply'],'error':t['outcome'].get('error'),'calls':t['calls'],'decisions':[e.get('decision') for e in t['events'] if e.get('decision')]} for t in r['turns']]},ensure_ascii=False))
with sqlite3.connect('/root/prjs/tmp/harness-20261007/budget-resume-20261008.sqlite3') as db:print(json.dumps({'budget':dict((k,{'used':u,'limit':c}) for k,u,c in db.execute('SELECT kind,used,cap FROM counters'))}))
