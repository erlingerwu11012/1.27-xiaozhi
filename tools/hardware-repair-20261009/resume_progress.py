from pathlib import Path
import json,sqlite3,collections,sys
S=Path(__file__).parent;name=sys.argv[1] if len(sys.argv)>1 else 'resume-final';rows=[json.loads(x) for x in (S/(name+'-results.jsonl')).read_text().splitlines()]
failed=[{'id':x['case']['id'],'query':x['case']['query'],'speech':x.get('speech'),'errors':x['errors']} for x in rows if x['errors']]
print(json.dumps({'tested':len(rows),'planned':len(json.loads((S/'final-cases.json').read_text())),'failed':failed,'model_response_turns':sum(any(d.get('usage') for d in r.get('decisions',[])) for r in rows)},ensure_ascii=False))
