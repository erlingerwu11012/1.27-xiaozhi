import json
from pathlib import Path
S=Path(__file__).parent
for r in map(json.loads,(S/'final-results.jsonl').read_text().splitlines()):
 if r['case']['id']==99:print(json.dumps(r['decisions'],ensure_ascii=False))
