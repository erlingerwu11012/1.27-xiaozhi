from pathlib import Path
import json
S=Path(__file__).parent
r=[json.loads(x) for x in (S/'resume-final-results.jsonl').read_text().splitlines()]
for x in r:print(x['case']['id']+' | '+x['case']['query']+' | '+x.get('speech',''))
