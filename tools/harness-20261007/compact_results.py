import collections,json,sys
from pathlib import Path
for file in sys.argv[1:]:
    rows=[json.loads(s) for s in Path(file).read_text(encoding='utf8').splitlines() if s.strip()]
    for chain in ['baseline','candidate']:
        data=[r for r in rows if r['chain']==chain]
        if not data:continue
        positive=[r for r in data if r['group']!='negative'];negative=[r for r in data if r['group']=='negative']
        fails=[r for r in positive if not r['passed']]
        print(json.dumps({'file':file,'chain':chain,'positive':len(positive),'positive_failed':len(fails),'negative':len(negative),'negative_failed':sum(not r['passed'] for r in negative),'failure_tools':collections.Counter(r.get('expected_tool') for r in fails)},ensure_ascii=False))
        for r in fails[:12]:
            print(json.dumps({'id':r['id'],'repeat':r['repeat'],'turns':[{'user':t['user'],'passed':t['passed'],'reply':t['outcome']['reply'],'error':t['outcome']['error'],'calls':t['calls'],'model_errors':[(e.get('error_type'),e.get('error_kind')) for e in t['events'] if e.get('error_type')]} for t in r.get('turns',[]) if not t['passed']]},ensure_ascii=False))
