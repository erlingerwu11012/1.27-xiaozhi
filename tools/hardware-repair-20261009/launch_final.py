from pathlib import Path
import subprocess
S=Path(__file__).parent
f=(S/'final-console.log').open('w')
p=subprocess.Popen(['/root/miniconda3/envs/xiaozhi-esp32-server/bin/python','-u',str(S/'run_model.py')],cwd=S,stdout=f,stderr=subprocess.STDOUT,start_new_session=True,stdin=subprocess.DEVNULL)
print('final_model_pid',p.pid)
