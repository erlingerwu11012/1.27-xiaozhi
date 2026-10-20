from pathlib import Path
import json
S=Path('/root/prjs/tmp/quiet-maintenance-20261018')
d=json.loads((S/'deployment-private/person-data-before.json').read_text())
print(json.dumps([{'kind':r['kind'],'text':r['content']} for r in d['ai_person_material'] if r['kind'] in ['dialogue','explicit_fact'] and any(w in r['content'] for w in ['秦','老婆'])],ensure_ascii=False))
