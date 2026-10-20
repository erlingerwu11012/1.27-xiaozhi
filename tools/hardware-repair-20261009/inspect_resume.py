import json,os,signal
from pathlib import Path
S=Path(__file__).parent
pid=json.loads((S/'resume-authorization.json').read_text())['pid']
try:os.kill(pid,signal.SIGTERM)
except ProcessLookupError:pass
for line in (S/'resume-focus-results.jsonl').read_text().splitlines():
 r=json.loads(line)
 if r['errors'] or r['case']['id']=='new-3':print(json.dumps({k:r.get(k) for k in ['case','outcome','speech','errors','decisions']},ensure_ascii=False))
