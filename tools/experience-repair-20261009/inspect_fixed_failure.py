import json
from pathlib import Path
S=Path(__file__).parent
for r in map(json.loads,(S/'fixed-failures-real.jsonl').read_text().splitlines()):
 if r['errors']:print(json.dumps({k:r.get(k) for k in ['case','outcome','decisions','calls']},ensure_ascii=False,default=str))
