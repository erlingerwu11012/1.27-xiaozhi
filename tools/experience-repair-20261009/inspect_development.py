import json
from pathlib import Path
S=Path(__file__).parent
for r in map(json.loads,(S/'development-model.jsonl').read_text().splitlines()):
 if '刚才那个' in r['query'] or '闹钟' in r['query']:
  print(json.dumps({'query':r['query'],'decisions':r['decisions'],'wire':r['wire'],'calls':r['calls'],'outcome':r['outcome']},ensure_ascii=False))
