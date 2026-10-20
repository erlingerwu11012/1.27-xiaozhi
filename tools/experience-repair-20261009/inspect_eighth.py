from pathlib import Path
import json
S=Path(__file__).parent
for r in map(json.loads,(S/'final-results.jsonl').read_text().splitlines()):
 if r['errors']:print(json.dumps({k:r.get(k) for k in ['case','outcome','calls','decisions']},ensure_ascii=False))
