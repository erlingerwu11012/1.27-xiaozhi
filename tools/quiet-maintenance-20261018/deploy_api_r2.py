from pathlib import Path
import hashlib,json,shutil,subprocess,time,requests,yaml
S=Path('/root/prjs/tmp/quiet-maintenance-20261018');R=Path('/root/prjs/releases/quiet-maintenance-20261018-r2')
def apps():return json.loads(subprocess.check_output(['pm2','jlist']))
def cmd(args,env=None):subprocess.run(args,env=env,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
v=json.loads((S/'api-retest-result.json').read_text());assert v['tests']>=68 and not any(v[k] for k in ['errors','failures','skipped'])
old=next(x for x in apps() if x['pm_id']==20);assert old['pm2_env']['status']=='online'
env={k.decode():v.decode() for item in (Path('/proc')/str(old['pid'])/'environ').read_bytes().split(b'\0') if b'=' in item for k,v in [item.split(b'=',1)]}
R.mkdir();shutil.copy2(S/'manager-api/target/xiaozhi-esp32-api.jar',R/'xiaozhi-esp32-api.jar')
entry=Path(old['pm2_env']['pm_exec_path'])
(R/'start-manager-api.sh').write_text(entry.read_text().replace(str(entry.parent/'xiaozhi-esp32-api.jar'),str(R/'xiaozhi-esp32-api.jar')));(R/'start-manager-api.sh').chmod(0o755)
secret=yaml.safe_load(Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server/data/.config.yaml').read_text())['manager-api']['secret']
def ready():
 try:
  r=requests.post('http://127.0.0.1:18005/xiaozhi/config/server-base',headers={'Authorization':'Bearer '+secret},json={},timeout=2)
  return r.status_code==200 and r.json().get('data',{}).get('wakeup_words')==['你好小念']
 except Exception:return False
state={'phase':'prepared','old_api':20,'new_api':None,'python':21}
try:
 cmd(['pm2','stop','20']);cmd(['pm2','start',str(R/'start-manager-api.sh'),'--name','manager-api','--cwd',old['pm2_env']['pm_cwd']],env)
 state['new_api']=next(x['pm_id'] for x in apps() if x['pm2_env']['pm_exec_path']==str(R/'start-manager-api.sh'))
 deadline=time.monotonic()+90
 while not ready():
  if time.monotonic()>deadline:raise RuntimeError('api_not_ready')
  time.sleep(1)
 r=requests.post('https://api.realecho.cn/xiaozhi/config/server-base',headers={'Authorization':'Bearer '+secret},json={},timeout=15);assert r.status_code==200 and r.json().get('code')==0
 assert next(x for x in apps() if x['pm_id']==21)['pm2_env']['status']=='online'
 cmd(['pm2','save']);state.update(phase='complete',completed_at=time.time(),sha256=hashlib.sha256((R/'xiaozhi-esp32-api.jar').read_bytes()).hexdigest())
except BaseException:
 if state['new_api'] is not None:cmd(['pm2','stop',str(state['new_api'])])
 cmd(['pm2','restart','20']);state['phase']='rolled_back';raise
finally:(S/'deployment-api-r2.json').write_text(json.dumps(state,indent=2));print(json.dumps(state),flush=True)
