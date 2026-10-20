from pathlib import Path
import hashlib,json,os,shutil,socket,sqlite3,subprocess,time
import pymysql,requests,yaml
S=Path('/root/prjs/tmp/quiet-maintenance-20261018');R=Path('/root/prjs/releases/quiet-maintenance-20261018')
ROOT=Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server');OLD=Path('/root/prjs/releases/dialogue-fix-20261017')
PY='/root/miniconda3/envs/xiaozhi-esp32-server/bin/python'
def apps():return json.loads(subprocess.check_output(['pm2','jlist']))
def cmd(args,env=None):subprocess.run(args,env=env,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(): (S/'deployment.json').write_text(json.dumps(state,indent=2))
def environ(app):return {k.decode():v.decode() for item in (Path('/proc')/str(app['pid'])/'environ').read_bytes().split(b'\0') if b'=' in item for k,v in [item.split(b'=',1)]}
def ready_api():
 try:
  v=requests.post('http://127.0.0.1:18005/xiaozhi/config/server-base',headers=headers,json={},timeout=2)
  return v.status_code==200 and v.json().get('data',{}).get('wakeup_words')==['你好小念']
 except Exception:return False
def ready_py():
 try:
  for port in [8270,8273,8276]:
   with socket.create_connection(('127.0.0.1',port),timeout=.5):pass
  return True
 except OSError:return False
def wait(fn):
 deadline=time.monotonic()+90
 while time.monotonic()<deadline:
  if fn():return
  time.sleep(1)
 raise RuntimeError('readiness_timeout')
assert not R.exists()
for file,minimum in [('verification.json',126),('api-test-result.json',67)]:
 v=json.loads((S/file).read_text());assert v['tests']>=minimum and not any(v[k] for k in ['errors','failures','skipped'])
before=apps();old=next(x for x in before if x['pm_id']==19);api=next(x for x in before if x['pm_id']==16)
old_env=environ(old);api_env=environ(api)
assert all(x['pm2_env']['status']=='online' for x in [old,api])
assert old['pm2_env']['pm_exec_path']==str(OLD/'serve.py')
api_entry=Path(api['pm2_env']['pm_exec_path']);oldjar=api_entry.parent/'xiaozhi-esp32-api.jar'
secret=yaml.safe_load((ROOT/'data/.config.yaml').read_text())['manager-api']['secret'];headers={'Authorization':'Bearer '+secret}
password=json.loads(Path('/root/prjs/tmp/hardware-followup-20261013/private-test-env.json').read_text())['PERSON_MEMORY_TEST_PASSWORD']
assert ready_api() and ready_py() and shutil.disk_usage('/').free>700*1024**2
private=S/'deployment-private';private.mkdir(mode=0o700)
for source in (ROOT/'data').rglob('*.sqlite3'):
 dest=private/('sqlite-'+str(source.relative_to(ROOT/'data')).replace('/','-'))
 with sqlite3.connect(source) as a,sqlite3.connect(dest) as b:a.backup(b)
 dest.chmod(0o600)
with pymysql.connect(host='127.0.0.1',user='root',password=password,database='xiaozhi_esp32_server',cursorclass=pymysql.cursors.DictCursor) as db:
 with db.cursor() as c:
  backup={}
  for table in ['ai_person_material','ai_person_memory_entity','ai_memory_task','ai_memory_override','ai_person_behavior_event','ai_person_behavior_analysis','ai_person_behavior_watermark']:
   c.execute('SELECT * FROM '+table+' WHERE account_id=%s',('2022326478036516866',));backup[table]=c.fetchall()
  c.execute('SELECT id,user_id,agent_id FROM ai_device WHERE mac_address=%s',('ac:a7:04:fd:20:5c',));binding=c.fetchall()
 dest=private/'person-data-before.json';dest.write_text(json.dumps(backup,default=str,ensure_ascii=False));dest.chmod(0o600)
R.mkdir();shutil.copytree(OLD/'runtime',R/'runtime',ignore=shutil.ignore_patterns('models','__pycache__','*.pyc'))
(R/'runtime/models').symlink_to(OLD/'runtime/models',target_is_directory=True)
for p in (S/'server').rglob('*.py'):
 relative=p.relative_to(S/'server');shutil.copy2(p,R/'runtime'/relative)
(R/'serve.py').write_text((OLD/'serve.py').read_text().replace(str(OLD/'runtime'),str(R/'runtime')))
shutil.copy2(S/'manager-api/target/xiaozhi-esp32-api.jar',R/'xiaozhi-esp32-api.jar')
(R/'start-manager-api.sh').write_text(api_entry.read_text().replace(str(oldjar),str(R/'xiaozhi-esp32-api.jar')))
(R/'start-manager-api.sh').chmod(0o755)
state={'phase':'prepared','old_python':19,'old_api':16,'new_python':None,'new_api':None,'config_sha':sha(ROOT/'data/.config.yaml'),'binding_before':binding,'firmware_flashed':False,'started_at':time.time()};save()
try:
 state['phase']='switching';save()
 cmd(['pm2','stop','19']);cmd(['pm2','stop','16'])
 cmd(['pm2','start',str(R/'start-manager-api.sh'),'--name','manager-api','--cwd',api['pm2_env']['pm_cwd']],api_env)
 newapi=next(x for x in apps() if x['pm2_env']['pm_exec_path']==str(R/'start-manager-api.sh'));state['new_api']=newapi['pm_id'];save();wait(ready_api)
 cmd(['pm2','start',str(R/'serve.py'),'--name','xiaozhi-server','--interpreter',PY,'--cwd',old['pm2_env']['pm_cwd']],old_env)
 newpy=next(x for x in apps() if x['pm2_env']['pm_exec_path']==str(R/'serve.py'));state['new_python']=newpy['pm_id'];save();wait(ready_py)
 assert requests.get('https://www.realecho.cn/',timeout=15).status_code==200
 r=requests.post('https://api.realecho.cn/xiaozhi/config/server-base',headers=headers,json={},timeout=15)
 assert r.status_code==200 and r.json().get('data',{}).get('wakeup_words')==['你好小念']
 denied=requests.post('https://api.realecho.cn/xiaozhi/person-memory/internal/maintenance/rerun-memory',json={},timeout=10)
 assert denied.status_code in [401,403] or denied.json().get('code') in [401,403]
 assert sha(ROOT/'data/.config.yaml')==state['config_sha']
 current={x['pm_id']:x for x in apps()}
 assert all(current[x['pm_id']]['pm2_env']['status']==x['pm2_env']['status'] for x in before if x['pm_id'] not in [16,19])
 cmd(['pm2','save']);state.update(phase='complete',completed_at=time.time(),checks=['formal_https','formal_api','private_endpoint_requires_service_auth','ports','other_processes_unchanged','configuration_unchanged']);save();print(json.dumps(state),flush=True)
except BaseException as error:
 state.update(phase='rolling_back',error_type=type(error).__name__);save()
 for app in apps():
  if app['pm2_env']['pm_exec_path'] in [str(R/'serve.py'),str(R/'start-manager-api.sh')]:cmd(['pm2','stop',str(app['pm_id'])])
 cmd(['pm2','restart','16']);wait(ready_api);cmd(['pm2','restart','19']);wait(ready_py);cmd(['pm2','save'])
 state['phase']='rolled_back';save();raise
