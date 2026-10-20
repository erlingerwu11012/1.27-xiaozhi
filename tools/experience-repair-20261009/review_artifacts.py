import json,hashlib
from pathlib import Path
S=Path('tools/experience-repair-20261009');E=S/'evidence'; f=json.loads((E/'final-freeze.json').read_text(encoding='utf-8')); rows=[json.loads(x) for x in (E/'final-results.jsonl').read_text(encoding='utf-8').splitlines()]
for p in (E/'java').glob('*.java'):
 assert hashlib.sha256(p.read_bytes()).hexdigest()==f['java_source'][p.name],p
print('Java final frozen sources verified:',len(list((E/'java').glob('*.java'))))
for r in rows:
 if r['case']['id'] in [700,701,702,703,704,705,709,710,711,751,752,753,757,758,759]:
  print(json.dumps({'id':r['case']['id'],'user':r['query'],'assistant':r['speech'],'errors':r['errors']},ensure_ascii=False))
print('schema keys', list(rows[0].keys()))

