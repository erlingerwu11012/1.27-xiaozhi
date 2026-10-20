from pathlib import Path
import subprocess,sys
S=Path(__file__).parent;name=sys.argv[1];args=sys.argv[2:]
p=subprocess.Popen(['/root/miniconda3/envs/xiaozhi-esp32-server/bin/python','-u',str(S/'run_model.py'),'--run-name',name]+args,cwd=S,stdout=(S/(name+'-console.log')).open('x'),stderr=subprocess.STDOUT,start_new_session=True,stdin=subprocess.DEVNULL);print('validation_pid',p.pid,'run',name)
