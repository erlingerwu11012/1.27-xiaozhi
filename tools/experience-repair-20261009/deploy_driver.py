from pathlib import Path
import subprocess,json,time
S=Path(__file__).parent;P='/root/miniconda3/envs/xiaozhi-esp32-server/bin/python'
with (S/'deployment-console.log').open('w') as f:
 r=subprocess.run([P,str(S/'release.py'),'apply'],stdout=f,stderr=subprocess.STDOUT,cwd=S)
if r.returncode:raise SystemExit(r.returncode)
with (S/'observation-console.log').open('w') as f:
 p=subprocess.Popen([P,'/root/prjs/releases/experience-repair-20261009/release.py','observe'],stdout=f,stderr=subprocess.STDOUT,start_new_session=True)
(S/'observation-pid.json').write_text(json.dumps({'pid':p.pid,'started_at':time.time()}))
