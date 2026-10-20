import json,subprocess,sys,time
from pathlib import Path
p=Path(__file__).parent
commands=['test_budget_guard.py','test_unit.py','test_protocol.py','test_server_protocol.py','run_regressions.py','run_budget_tests.py','test_full_message_path.py'];results=[]
for script in commands:
 began=time.time();r=subprocess.run([sys.executable,str(p/script)],cwd=p)
 results.append({'script':script,'exit_code':r.returncode,'seconds':round(time.time()-began,3)})
 (p/'budget-jobs-results.json').write_text(json.dumps(results,indent=2))
 if r.returncode:break
