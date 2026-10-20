import json,time,hashlib,os,sqlite3
from pathlib import Path
from rollout import RELEASE,STATE,pmid,observe_metadata
s=json.loads(STATE.read_text());o=RELEASE/'observation.json';d=json.loads(o.read_text()) if o.exists() else {'records':[]};last=d['records'][-1] if d['records'] else {}
p=pmid(s['new_pm2_id']);meta=observe_metadata(s)
report={'phase':s['phase'],'deployed_at':s['deployed_at'],'elapsed_seconds':round(time.time()-s['deployed_at']),'code_hash':s['gate']['code_hash'],'checks_completed':len(d['records']),'all_checks_pass':all(r['passed'] for r in d['records']),'last_check_at':last.get('at'),'process':{'id':p['pm_id'],'status':p['pm2_env']['status'],'restarts':p['pm2_env'].get('restart_time',0)},'metadata':meta}
print(json.dumps(report,ensure_ascii=False))
