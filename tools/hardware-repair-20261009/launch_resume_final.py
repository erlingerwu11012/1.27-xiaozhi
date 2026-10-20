from pathlib import Path
import subprocess,shutil,json,time
S=Path(__file__).parent
shutil.copy2(S/'regression-summary.json',S/'resume-regression-summary.json')
p=subprocess.Popen(['/root/miniconda3/envs/xiaozhi-esp32-server/bin/python','-u',str(S/'run_model.py'),'--run-name','resume-final'],cwd=S,stdout=(S/'resume-final-console.log').open('x'),stderr=subprocess.STDOUT,start_new_session=True,stdin=subprocess.DEVNULL)
(S/'resume-authorization.json').write_text(json.dumps({'time':time.time(),'authorization':'User lifted previous test/API budget limits and asked to continue to acceptance and deployment','pid':p.pid},indent=2));print('final_validation_pid',p.pid)
