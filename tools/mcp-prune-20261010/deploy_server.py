from pathlib import Path
import importlib.util,json,os,shutil,socket,subprocess,sys,time,hashlib
stage=Path('/root/prjs/tmp/mcp-prune-20261010');rel=Path('/root/prjs/releases/mcp-prune-20261010');prior=Path('/root/prjs/releases/hardware-repair-20261009')
assert not (stage/'deployment.json').exists(), 'already deployed; use recorded rollback instead'
spec=importlib.util.spec_from_file_location('prior_release',prior/'release.py');old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
assert json.loads((stage/'test-results.json').read_text())['passed']
private=rel/'process-private.json';prior_proc=json.loads(private.read_text())['apps'][0]
env={k:v for k,v in prior_proc['env'].items() if k==k.upper() and not k.startswith(('PM2_','NODE_'))}
active={'pm_id':8,'pid':30103}
old.command(['pm2','stop','8'])
new=next((a for a in old.apps() if a['name']=='xiaozhi-server' and a['pm2_env']['pm_exec_path']==str(rel/'serve.py') and a['pm2_env']['status']=='online'),None)
if new is None:
 p=subprocess.run(['pm2','start',str(rel/'serve.py'),'--name','xiaozhi-server','--interpreter',old.PY,'--cwd',str(old.ROOT),'--force'],env=env,capture_output=True,text=True)
 assert p.returncode==0,'candidate start failed'
 new=next(a for a in old.apps() if a['name']=='xiaozhi-server' and a['pm2_env']['pm_exec_path']==str(rel/'serve.py'))
nginx=Path('/etc/nginx/sites-enabled/www.realecho.cn').resolve();internal=Path('/etc/nginx/conf.d/tool-harness-internal.conf')
state={'old_pm_id':active['pm_id'],'old_listener_pid':active['pid'],'new_pm_id':new['pm_id'],'source_commit':json.loads((stage/'server-commit.json').read_text())['commit'],'ports':[8070,8073,8076],'backup':str(rel/'backup'),'started_at':time.time(),'firmware_compiled':False}
(rel/'backup').mkdir(mode=0o700,exist_ok=True)
for p in [nginx,internal]:shutil.copy2(p,rel/'backup'/p.name)
try:
 old.old.ready(ws=8070,http=8073,internal=8076,manager=18005,public=False)
 for p in [nginx,internal]:
  s=p.read_text();s=s.replace('127.0.0.1:8060','127.0.0.1:8070').replace('127.0.0.1:8063','127.0.0.1:8073').replace('127.0.0.1:8066','127.0.0.1:8076');old.atomic(p,s.encode(),0o644)
 old.command(['nginx','-t']);old.command(['systemctl','reload','nginx'])
 state['health']=old.old.ready(ws=8070,http=8073,internal=8076,manager=18005,public=True)
 state['phase']='switched';state['switched_at']=time.time()
except Exception:
 for p in [nginx,internal]:shutil.copy2(rel/'backup'/p.name,p)
 old.command(['nginx','-t']);old.command(['systemctl','reload','nginx']);old.command(['pm2','stop',str(new['pm_id'])]);raise
(rel/'deployment.json').write_text(json.dumps(state,indent=2));(stage/'deployment.json').write_text(json.dumps(state,indent=2));print(json.dumps({'phase':state['phase'],'new_pm_id':new['pm_id'],'health_passed':all(x['passed'] for x in state['health'])}))
