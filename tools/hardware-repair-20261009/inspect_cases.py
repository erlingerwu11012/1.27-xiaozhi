from pathlib import Path
import json,collections
S=Path('tools/experience-repair-20261009');a=json.loads((S/'final-cases.json').read_text(encoding='utf-8-sig'));print('cases',len(a));print(collections.Counter(x.get('tool') for x in a));print('first',a[:2]);print('memory',[x for x in a if str(x.get('tool','')).startswith('memory')][:6])
