import hashlib,json,subprocess,sys
from pathlib import Path
S=Path('/root/prjs/tmp/experience-repair-20261009');sys.path.insert(0,str(S))
from budget import Budget
R=Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server')
baseline=json.loads((S/'baseline.json').read_text());names=json.loads((S/'changed-files.json').read_text(encoding='utf-8-sig'))
drift=[]
for n in names:
    p=R/n;actual=hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
    if actual!=baseline.get(n):drift.append(n)
apps=json.loads(subprocess.check_output(['pm2','jlist']))
print(json.dumps({'budget':Budget(S/'budget.sqlite3').report(),'production_drift':drift,'services':[{'name':p['name'],'id':p['pm_id'],'status':p['pm2_env']['status'],'restarts':p['pm2_env']['restart_time']} for p in apps if p['name'] in {'xiaozhi-server','manager-api'}]},ensure_ascii=False))
