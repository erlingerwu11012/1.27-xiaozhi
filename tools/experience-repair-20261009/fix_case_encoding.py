from pathlib import Path
import json
p=Path('tools/experience-repair-20261009/final-cases.json');rows=json.loads(p.read_text(encoding='utf-8'))
for row in rows:
 if row.get('session')=='multi4' and row.get('multi_step')==2:row['tool']=None;row['required']=['书','杯']
p.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
