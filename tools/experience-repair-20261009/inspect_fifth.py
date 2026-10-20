import json
from pathlib import Path
S=Path(__file__).parent
for r in map(json.loads,(S/'final-results.jsonl').read_text().splitlines()):
 if r.get('errors'):
  print(json.dumps({k:r.get(k) for k in ['case','speech','calls','outcome','decisions']},ensure_ascii=False))
p=S/'work/core/utils/tool_harness/runtime.py';lines=p.read_text().splitlines()
for a,b in [(65,145),(325,487)]:
 for i in range(a,b):print(str(i+1)+': '+lines[i])
