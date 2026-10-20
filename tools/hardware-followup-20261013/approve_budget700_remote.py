from pathlib import Path
import json,hashlib,time
s=Path('/root/prjs/tmp/hardware-followup-20261013');p=s/'budget.py';text=p.read_text();assert "'model':600" in text
old=hashlib.sha256(p.read_bytes()).hexdigest();p.write_text(text.replace("'model':600","'model':700"))
(s/'budget-approval-700.json').write_text(json.dumps({'human_authorization':'允许主模型上限提高到700次，继续剩余验收','previous_model_cap':600,'model_cap':700,'case_cap':800,'tts_cap':12,'vision_cap':0,'ledger_reset':False,'at':time.time(),'prior_budget_source_sha256':old},ensure_ascii=False,indent=2))
import sys;sys.path.insert(0,str(s));from budget import Budget
print(Budget().report())
