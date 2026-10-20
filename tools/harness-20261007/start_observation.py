import os,subprocess,json
from pathlib import Path
p=Path('/root/prjs/releases/tool-harness-20261008');log=p/'observation-worker.log'
with log.open('ab') as f:
 os.chmod(log,0o600)
 child=subprocess.Popen(['/root/miniconda3/envs/xiaozhi-esp32-server/bin/python',str(p/'rollout.py'),'observe'],stdin=subprocess.DEVNULL,stdout=f,stderr=subprocess.STDOUT,start_new_session=True)
(p/'observation-worker.json').write_text(json.dumps({'pid':child.pid}));os.chmod(p/'observation-worker.json',0o600)
print(json.dumps({'observer_pid':child.pid,'duration_seconds':1800,'model_requests':0}))
