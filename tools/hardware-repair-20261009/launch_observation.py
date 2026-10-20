from pathlib import Path
import subprocess,json,time
S=Path(__file__).parent;R=Path('/root/prjs/releases/hardware-repair-20261009')
assert json.loads((R/'deployment-state.json').read_text())['phase']=='observing'
p=subprocess.Popen(['/root/miniconda3/envs/xiaozhi-esp32-server/bin/python','-u',str(R/'release.py'),'observe'],cwd=S,stdout=(S/'release-observation-console.log').open('x'),stderr=subprocess.STDOUT,start_new_session=True,stdin=subprocess.DEVNULL)
print(json.dumps({'observer_pid':p.pid,'started_at':time.time(),'minimum_seconds':1800}))
