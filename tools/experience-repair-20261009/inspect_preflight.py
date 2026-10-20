import json
from pathlib import Path
S=Path(__file__).parent
for r in json.loads((S/'preflight-state-results.json').read_text()):
 if r['errors']:print(json.dumps({k:r.get(k) for k in ['query','errors','outcome','readback']},ensure_ascii=False,default=str))
