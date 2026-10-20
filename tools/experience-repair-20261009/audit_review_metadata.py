from pathlib import Path
import json,re
p=Path('/root/prjs/releases/experience-repair-20261009/backup/memory-review-private.json');d=json.loads(p.read_text())
print(json.dumps({'records':len(d['records']),'metadata':[{'table':r['table'],'id':r['id'],'reason':r['reason'],'bytes':len((r.get('content') or '').encode()),'starts_with_wrapper':bool(re.match(r'^\s*\[(?:本轮可信|来源[:：])',r.get('content') or '')),'scope_bound':bool(r.get('account_id') and r.get('person_id') and r.get('agent_id')),'approved':r.get('approved')} for r in d['records']]},ensure_ascii=False))
