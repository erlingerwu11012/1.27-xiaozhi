from pathlib import Path
import subprocess,json,time
S=Path(__file__).parent
assert not (S/'deployment-driver-pid.json').exists(),'deploy already dispatched'
f=(S/'deployment-driver.log').open('w');p=subprocess.Popen(['/root/miniconda3/envs/xiaozhi-esp32-server/bin/python','-u',str(S/'deploy_driver.py')],stdout=f,stderr=subprocess.STDOUT,start_new_session=True,cwd=S)
(S/'deployment-driver-pid.json').write_text(json.dumps({'pid':p.pid,'started_at':time.time()}));print(json.dumps({'deployment_driver_pid':p.pid}))
