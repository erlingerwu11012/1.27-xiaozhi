from pathlib import Path
import json,re
R=Path('tools/hardware-repair-20261009');rows=json.loads((R/'final-cases.json').read_text())
for r in rows:
 if r['group']!='chat' and re.search(r'[零〇一二两三四五六七八九十百\d]+[点时]',r['query']) and not re.search(r'早|晨|上午|中午|下午|晚上|夜|凌晨|傍晚',r['query']):print(r['id'],r['query'],r['tool'])
print('unique_queries',len(set(r['query'] for r in rows)),len(rows));print('tools',len(set(r['tool'] for r in rows if r['tool'])))
