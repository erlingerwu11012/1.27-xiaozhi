import collections,json,sys
from pathlib import Path
rows=[json.loads(x) for x in Path(sys.argv[1]).read_text().splitlines() if x.strip()]
groups=collections.defaultdict(list)
for r in rows:groups[r['chain']].append(r)
for chain,data in groups.items():
    positive=[r for r in data if r['group']!='negative'];negative=[r for r in data if r['group']=='negative']
    failures=[r for r in positive if not r['passed']]
    print(json.dumps({'chain':chain,'positive_total':len(positive),'positive_failed':len(failures),'negative_total':len(negative),'negative_failed':sum(not r['passed'] for r in negative),'failures':[{'id':r['id'],'repeat':r['repeat'],'user':r.get('user'),'reply':r.get('outcome',{}).get('reply'),'error':r.get('outcome',{}).get('error'),'calls':r['calls'],'events':r['events']} for r in failures[:20]]},ensure_ascii=False))
