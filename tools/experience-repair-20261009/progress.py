import json
from pathlib import Path
S=Path(__file__).parent
p=S/'final-results.jsonl';r=[json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []
print(json.dumps({'done':len(r),'failed':[{'id':x['case']['id'],'q':x['case']['query'],'errors':x['errors'],'reply':x.get('speech'),'detail':x.get('outcome',{}).get('error')} for x in r if x['errors']],'model_turns':sum(bool(x.get('outcome',{}).get('model_calls')) for x in r)},ensure_ascii=False))
