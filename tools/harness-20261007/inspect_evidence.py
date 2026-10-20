"""Small, credential-free diagnostic summaries of synthetic evidence."""
import argparse,collections,json
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('path');p.add_argument('--failures',type=int,default=8);a=p.parse_args()
root=Path(__file__).parent;target=(root/a.path).resolve()
assert target.is_relative_to(root.resolve())
files=[target] if target.is_file() else [target/(n+'.jsonl') for n in ('single','complex','holdout')]
for f in files:
    if not f.exists():continue
    rows=[json.loads(x) for x in f.read_text().splitlines() if x.strip()]
    groups=collections.defaultdict(list)
    for r in rows:groups[(r['chain'],r['group'])].append(r)
    print(json.dumps({'file':str(f),'rows':len(rows),'groups':[{'chain':k[0],'group':k[1],'n':len(v),'passed':sum(x['passed'] for x in v)} for k,v in groups.items()]}))
    if len(rows)<=12:
        for r in rows:print(json.dumps({'id':r['id'],'chain':r['chain'],'passed':r['passed'],'elapsed_ms':r['elapsed_ms'],'fixture_setup_ms':r.get('fixture_setup_ms'),'test_wall_ms':r.get('test_wall_ms'),'model_ms':sum(e.get('elapsed_ms',0) for e in r.get('events',[])),'model_calls':r.get('outcome',{}).get('model_calls')},ensure_ascii=False))
    for r in [x for x in rows if x['chain']=='candidate' and not x['passed']][:a.failures]:
        print(json.dumps({'failure':r},ensure_ascii=False))
