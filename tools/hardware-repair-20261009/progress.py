from pathlib import Path
import json
S=Path(__file__).parent
rows=[json.loads(x) for x in (S/'final-results.jsonl').read_text().splitlines()]
print(json.dumps({'finished':len(rows),'failed':[{'id':r['case']['id'],'query':r['case']['query'],'speech':r.get('speech'),'errors':r['errors']} for r in rows if r['errors']]},ensure_ascii=False))
