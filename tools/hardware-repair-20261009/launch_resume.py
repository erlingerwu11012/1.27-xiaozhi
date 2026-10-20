from pathlib import Path
import subprocess,json,time
S=Path(__file__).parent
p=subprocess.Popen(['/root/miniconda3/envs/xiaozhi-esp32-server/bin/python','-u',str(S/'run_model.py'),'--run-name','resume-focus','--focus'],cwd=S,stdout=(S/'resume-focus-console.log').open('x'),stderr=subprocess.STDOUT,start_new_session=True,stdin=subprocess.DEVNULL)
(S/'resume-authorization.json').write_text(json.dumps({'time':time.time(),'authorization':'User lifted previous test/API budget limits and asked to continue to acceptance and deployment','pid':p.pid},indent=2));print('focused_validation_pid',p.pid)
