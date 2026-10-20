from pathlib import Path
import json
S=Path(__file__).parent
for line in (S/'resume-final-results.jsonl').read_text().splitlines():
 x=json.loads(line)
 if x['case']['id'] in {'reg-53','reg-54','reg-102'}:print(json.dumps({'id':x['case']['id'],'speech':x['speech'],'results':x['outcome']['results']},ensure_ascii=False))
