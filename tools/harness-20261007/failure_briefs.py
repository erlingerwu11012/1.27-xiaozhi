import collections,json,sys
from pathlib import Path
root=Path(__file__).parent/sys.argv[1]
for f in [root/n for n in ('single.jsonl','complex.jsonl','holdout.jsonl') if (root/n).exists()]:
    rows=[json.loads(x) for x in f.read_text().splitlines() if x.strip()]
    failures=[r for r in rows if r['chain']=='candidate' and not r['passed']]
    for r in failures:
        print(json.dumps({'suite':f.stem,'id':r['id'],'repeat':r['repeat'],'turns':[{'user':t['user'],'passed':t['passed'],'reply':t['outcome']['reply'],'error':t['outcome']['error'],'calls':t['calls'],'expected':t.get('expected'),'decisions':[e.get('decision') for e in t['events']]} for t in r.get('turns',[])]},ensure_ascii=False))
    print(json.dumps({'suite':f.stem,'candidate_n':sum(r['chain']=='candidate' for r in rows),'candidate_failed':len(failures),'failed_ids':dict(collections.Counter(r['id'] for r in failures))}))
