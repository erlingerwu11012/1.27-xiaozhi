"""Authorized production cutover, fresh small backups, immediate verification.

Only config reads and a synthetic invalid-token handshake touch production.
No model/TTS/vision or physical-device/business operation is generated.
"""
from pathlib import Path
import asyncio,gzip,hashlib,json,os,re,shutil,socket,sqlite3,subprocess,sys,time
import pymysql,requests,yaml,websockets
S=Path('/root/prjs/tmp/hardware-followup-20261013');R=Path('/root/prjs/releases/harness-followup-20261013');OLD=Path('/root/prjs/releases/harness-stream-20261012');ROOT=Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server')
sys.path.insert(0,str(S));from budget import Budget
b=Budget();STATE=S/'deployment-followup.json';PRIVATE=S/'deployment-private';assert not STATE.exists()
def pm2():return json.loads(subprocess.check_output(['pm2','jlist']))
def command(args,env=None):return subprocess.run(args,env=env,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
def process_env(pid):return {k.decode():v.decode() for f in (Path('/proc')/str(pid)/'environ').read_bytes().split(b'\0') if b'=' in f for k,v in [f.split(b'=',1)]}
def save():STATE.write_text(json.dumps(state,ensure_ascii=False,indent=2))
def new_app(name,script):return next((a for a in pm2() if a['name']==name and a['pm2_env'].get('pm_exec_path')==str(script)),None)
def api_ready():
 try:
  response=requests.post('http://127.0.0.1:18005/xiaozhi/config/server-base',headers={'Authorization':'Bearer '+secret},json={},timeout=4);body=response.json()
  return response.status_code==200 and body.get('code')==0 and 'log' in (body.get('data') or {})
 except (requests.RequestException,ValueError):return False
def ports_ready():
 for port in [8270,8273,8276]:
  try:
   with socket.create_connection(('127.0.0.1',port),timeout=.5):pass
  except OSError:return False
 return True
def config_read():
 body=requests.post('http://127.0.0.1:18005/xiaozhi/config/agent-models',headers={'Authorization':'Bearer '+secret},json={'macAddress':'ac:a7:04:fd:20:2c','clientId':'followup-readonly-config','selectedModule':{}},timeout=12).json();assert body.get('code')==0
 return body['data']
def rollback(reason):
 state.update(phase='rolling_back',reason=reason);save()
 for path,backup in nginx_backups.items():Path(path).write_bytes(Path(backup).read_bytes())
 command(['nginx','-t']);command(['nginx','-s','reload'])
 for name,script in [('xiaozhi-server',R/'serve.py'),('manager-api',R/'start-manager-api.sh')]:
  a=new_app(name,script)
  if a:command(['pm2','stop',str(a['pm_id'])])
 for name in ['manager-api','xiaozhi-server']:command(['pm2','restart',str(old[name]['pm_id'])])
 command(['pm2','save']);state.update(phase='rolled_back',rollback_at=time.time(),operation_ledger_preserved=True);save();b.finish(charge,{'passed':False,'rolled_back':True,'reason':reason})

review=json.loads((S/'acceptance-final-review.json').read_text());assert review['business_passed']==181 and review['experience_pass_ratio']>=.95
assert review['latency']['tool_gate'] and review['latency']['audio_gate'] and json.loads((S/'followup02-candidate-evidence.json').read_text())['passed']
manifest=json.loads((S/'final-source-freeze.json').read_text())
for rel,digest in manifest['candidate_work_hashes'].items():assert hashlib.sha256((R/'runtime'/rel).read_bytes()).hexdigest()==digest
assert hashlib.sha256((R/'xiaozhi-esp32-api.jar').read_bytes()).hexdigest()==manifest['api_sha256']
assert hashlib.sha256((OLD/'xiaozhi-esp32-api.jar').read_bytes()).hexdigest()==manifest['rollback_api_sha256']
assert shutil.disk_usage('/').free>150*1024**2
old={n:next(a for a in pm2() if a['pm_id']==i and a['name']==n and a['pm2_env']['status']=='online') for n,i in [('manager-api',9),('xiaozhi-server',10)]}
assert old['manager-api']['pm2_env']['pm_exec_path']==str(OLD/'start-manager-api.sh') and old['xiaozhi-server']['pm2_env']['pm_exec_path']==str(OLD/'serve.py')
for port in [8270,8273,8276]:
 with socket.socket() as sock:assert sock.connect_ex(('127.0.0.1',port))!=0,'candidate process still owns release port'
environments={n:process_env(a['pid']) for n,a in old.items()};secret=yaml.safe_load((ROOT/'data/.config.yaml').read_text())['manager-api']['secret'];assert api_ready()
baseline=config_read();cfg_hash=hashlib.sha256((ROOT/'data/.config.yaml').read_bytes()).hexdigest()
for path,replacements in [('/etc/nginx/sites-enabled/www.realecho.cn',['127.0.0.1:8170','127.0.0.1:8173']),('/etc/nginx/conf.d/tool-harness-internal.conf',['127.0.0.1:8176'])]:
 for before in replacements:assert Path(path).read_text().count(before)==1,'unexpected current nginx routing'
PRIVATE.mkdir(mode=0o700);(PRIVATE/'processes.json').write_text(json.dumps({'apps':pm2(),'environments':environments}));(PRIVATE/'processes.json').chmod(0o600)
nginx_backups={}
for path in ['/etc/nginx/sites-enabled/www.realecho.cn','/etc/nginx/conf.d/tool-harness-internal.conf']:
 backup=PRIVATE/(Path(path).name+'.before');backup.write_bytes(Path(path).read_bytes());backup.chmod(0o600);nginx_backups[path]=str(backup)
for path in [ROOT/'data/.config.yaml',ROOT/'config.yaml']:
 if path.exists():target=PRIVATE/(path.parent.name+'-'+path.name);target.write_bytes(path.read_bytes());target.chmod(0o600)
charge=b.reserve('case','production-followup-cutover-and-immediate-public-acceptance')
state={'phase':'backing_up','charge':charge,'started_at':time.time(),'release':str(R),'rollback_release':str(OLD),'old_pm2_ids':{n:a['pm_id'] for n,a in old.items()},'model_calls':0,'tts_calls':0,'vision_calls':0,'hardware_operations':0,'production_business_writes':0,'nginx_backups':nginx_backups};save()
switched=False
try:
 pw=json.loads((S/'private-test-env.json').read_text())['PERSON_MEMORY_TEST_PASSWORD'];cnf=PRIVATE/'mysql.cnf';cnf.write_text('[client]\nhost=127.0.0.1\nuser=root\npassword="'+pw.replace('\\','\\\\').replace('"','\\"')+'"\n');cnf.chmod(0o600)
 with (PRIVATE/'dump-errors.log').open('wb') as err:
  dump=subprocess.Popen(['mysqldump','--defaults-extra-file='+str(cnf),'--set-gtid-purged=OFF','--single-transaction','--hex-blob','--no-tablespaces','--routines','--triggers','xiaozhi_esp32_server'],stdout=subprocess.PIPE,stderr=err)
  with gzip.open(PRIVATE/'database.sql.gz','wb') as out:
   while chunk:=dump.stdout.read(1024*1024):out.write(chunk)
  assert dump.wait()==0,'fresh database backup failed'
 (PRIVATE/'database.sql.gz').chmod(0o600);sqlite_files=[]
 for source in (ROOT/'data').rglob('*.sqlite3'):
  target=PRIVATE/('sqlite-'+str(source.relative_to(ROOT/'data')).replace('/','-'))
  with sqlite3.connect(source) as src,sqlite3.connect(target) as dest:src.backup(dest)
  with sqlite3.connect(target) as conn:assert conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
  target.chmod(0o600);sqlite_files.append(target.name)
 db=pymysql.connect(host='127.0.0.1',user='root',password=pw,database='xiaozhi_esp32_server')
 with db.cursor() as cursor:cursor.execute('SHOW COLUMNS FROM ai_memory_override');columns={r[0] for r in cursor.fetchall()}
 db.close();assert {'material_cutoff_id','archive_cutoff_id'}<=columns
 state['backup']={'fresh_database_sha256':hashlib.sha256((PRIVATE/'database.sql.gz').read_bytes()).hexdigest(),'sqlite_snapshots':sqlite_files,'source_config_restore_rehearsal':'predeploy-backup02/manifest.json','immutable_old_release_retained':True};state['migration']={'required':False,'business_rows_changed':0};save()
 assert shutil.disk_usage('/').free>120*1024**2
 state['phase']='starting_api';save();switched=True;command(['pm2','stop','9'])
 command(['pm2','start',str(R/'start-manager-api.sh'),'--name','manager-api','--interpreter','/usr/bin/bash','--cwd',old['manager-api']['pm2_env']['pm_cwd']],env=environments['manager-api'])
 for _ in range(90):
  if api_ready():break
  time.sleep(1)
 else:raise RuntimeError('new API readiness timeout')
 api=new_app('manager-api',R/'start-manager-api.sh');assert api and api['pm2_env']['status']=='online';state['new_api_pm2_id']=api['pm_id'];save();print('new management API ready',flush=True)
 env=dict(environments['xiaozhi-server']);env.pop('XIAOZHI_RELEASE_CANDIDATE',None);env.update(XIAOZHI_RELEASE_ALTERNATE_PORTS='1',FULL_TOOL_HARNESS='1',HARNESS_LEDGER_PATH=str(ROOT/'data/harness/operations.sqlite3'),PERSON_MATERIAL_OUTBOX=str(ROOT/'data/person-material-outbox.sqlite3'))
 state['phase']='starting_server';save();command(['pm2','start',str(R/'serve.py'),'--name','xiaozhi-server','--interpreter',sys.executable,'--cwd',old['xiaozhi-server']['pm2_env']['pm_cwd']],env=env)
 for _ in range(75):
  if ports_ready():break
  time.sleep(1)
 else:raise RuntimeError('new server readiness timeout')
 server=new_app('xiaozhi-server',R/'serve.py');assert server and server['pm2_env']['status']=='online';state['new_server_pm2_id']=server['pm_id'];save()
 for path in nginx_backups:
  text=Path(path).read_text();replacements={'127.0.0.1:8170':'127.0.0.1:8270','127.0.0.1:8173':'127.0.0.1:8273'} if path.endswith('www.realecho.cn') else {'127.0.0.1:8176':'127.0.0.1:8276'}
  for before,after in replacements.items():assert text.count(before)==1;(text:=text.replace(before,after))
  Path(path).write_text(text)
 command(['nginx','-t']);command(['nginx','-s','reload']);state.update(phase='checking_public_entry',cutover_at=time.time());save();print('formal nginx entry switched',flush=True)
 assert requests.get('https://www.realecho.cn/',timeout=15).status_code==200
 async def auth_rejection():
  async with websockets.connect('wss://www.realecho.cn/xiaozhi/v1/',additional_headers={'device-id':'aa:00:00:00:13:ff','client-id':'followup-unbound-software','Authorization':'Bearer invalid'},open_timeout=12) as ws:
   try:
    while True:await asyncio.wait_for(ws.recv(),12)
   except websockets.exceptions.ConnectionClosed:assert ws.close_code==1008
 asyncio.run(auth_rejection());current=config_read()
 assert current.get('prompt')==baseline.get('prompt') and current.get('selected_module')==baseline.get('selected_module')
 key=current['selected_module']['LLM'];llm=current['LLM'][key];previous=baseline['LLM'][baseline['selected_module']['LLM']]
 assert llm['model_name']=='qwen3.7-plus' and float(llm['temperature'])==.4
 for key in ['model_name','temperature','hardware_billing','hardware_account_id']:assert llm.get(key)==previous.get(key),key
 for key in ['official_tts_enhanced','official_tts_enhanced_mode','official_tts']:assert current.get(key)==baseline.get(key),key
 assert hashlib.sha256((ROOT/'data/.config.yaml').read_bytes()).hexdigest()==cfg_hash
 env_live=process_env(server['pid']);assert env_live.get('HARNESS_LEDGER_PATH')==str(ROOT/'data/harness/operations.sqlite3')
 assert env_live.get('FULL_TOOL_HARNESS')=='1' and env_live.get('XIAOZHI_RELEASE_CANDIDATE')!='1'
 for key in ['HW_BILLING_SERVICE_KEY','HW_BILLING_GATEWAY_ORIGIN','HW_BILLING_AUDIO_GATEWAY_ORIGIN']:assert env_live.get(key)==environments['xiaozhi-server'].get(key),key
 assert env_live.get('PERSON_MATERIAL_OUTBOX')!=str(S/'candidate-material-outbox.sqlite3')
 active={a['pm_id']:a for a in pm2() if a['pm_id'] in [api['pm_id'],server['pm_id']]};assert len(active)==2 and all(a['pm2_env']['status']=='online' for a in active.values())
 assert api_ready() and ports_ready()
 command(['pm2','stop','10']);command(['pm2','save'])
 state.update(phase='complete',completed_at=time.time(),checks=['fresh_database_and_ledger_backup','restore_rehearsal_reused','final_source_and_jar_hashes','candidate_authenticated_hello_mcp','api_ready','three_server_listeners','nginx_valid','public_https_200','public_invalid_token_1008','unchanged_model_persona_billing_official_display','unchanged_root_config','same_production_ledger','old_exact_pm2_ids_retained'],model_config={'model':llm['model_name'],'temperature':llm['temperature'],'hardware_billing':llm.get('hardware_billing'),'account_bound':bool(llm.get('hardware_account_id')),'persona_sha256':hashlib.sha256(str(current.get('prompt','')).encode()).hexdigest(),'thinking':'unchanged; non-thinking adapter verified in isolated real model requests'},extended_observation_waived=True,hardware_accepted=False,firmware_flashed=False,public_valid_handshake_evidence='same release real candidate entry with isolated API; production only negative token to avoid business writes',free_bytes=shutil.disk_usage('/').free,budget=b.report());save()
 b.finish(charge,{'passed':True,'deployed':True,'rollback_used':False,'immediate_checks':True});print(json.dumps({'deployed':True,'new_pm2_ids':[api['pm_id'],server['pm_id']],'budget':b.report(),'free_bytes':state['free_bytes']},ensure_ascii=False),flush=True)
except BaseException as exc:
 if switched:rollback(type(exc).__name__+':'+str(exc)[:180])
 else:state.update(phase='backup_failed_original_service_preserved',reason=repr(exc));save();b.finish(charge,{'passed':False,'production_unchanged':True,'reason':repr(exc)})
 raise
