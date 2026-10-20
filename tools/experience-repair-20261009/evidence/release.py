"""Current experience release: fail-closed gates, private backup, blue/green and rollback."""
import argparse,asyncio,hashlib,importlib.util,json,os,re,runpy,shutil,socket,sqlite3,subprocess,sys,time,xml.etree.ElementTree as ET
from pathlib import Path
S=Path('/root/prjs/tmp/experience-repair-20261009');RELEASE=Path('/root/prjs/releases/experience-repair-20261009');B=RELEASE/'deploy-backup';ROOT=Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server');JAVA=ROOT.parent/'manager-api';RUNTIME=RELEASE/'runtime';PY='/root/miniconda3/envs/xiaozhi-esp32-server/bin/python';STATE=RELEASE/'deployment-state.json';NGINX=Path('/etc/nginx/sites-enabled/www.realecho.cn').resolve();INTERNAL=Path('/etc/nginx/conf.d/tool-harness-internal.conf');COMPAT=Path('/etc/nginx/conf.d/experience-manager-compat.conf')
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def atomic(p,data,mode=0o600):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_name(p.name+'.experience-tmp');tmp.write_bytes(data);os.chmod(tmp,mode);os.replace(tmp,p)
def save(d):atomic(STATE,json.dumps(d,ensure_ascii=False,indent=2).encode())
def command(args,env=None):
 r=subprocess.run(args,env=env,capture_output=True,text=True)
 if r.returncode:raise RuntimeError('command_failed:'+args[0]+':'+str(r.returncode))
 return r.stdout
def apps():return json.loads(command(['pm2','jlist']))
def app(i):return next(x for x in apps() if x['pm_id']==i)
def env_of(a):
 out=dict(os.environ)
 for row in Path('/proc',str(a['pid']),'environ').read_bytes().split(b'\0'):
  k,sep,v=row.partition(b'=')
  if sep:out[k.decode()]=v.decode()
 return out
def db():
 spec=importlib.util.spec_from_file_location('private_release_db','/root/prjs/xiaozhi_mcp_gateway/core/db_config.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
 import pymysql
 return pymysql.connect(host=m.DB_HOST,port=m.DB_PORT,user=m.DB_USER,password=m.DB_PASSWORD,database=m.DB_NAME,autocommit=True)
def backup_database():
 spec=importlib.util.spec_from_file_location('private_backup_db','/root/prjs/xiaozhi_mcp_gateway/core/db_config.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
 env=dict(os.environ,MYSQL_PWD=m.DB_PASSWORD);args=['mysqldump','--single-transaction','--skip-lock-tables','--no-tablespaces','-h',m.DB_HOST,'-P',str(m.DB_PORT),'-u',m.DB_USER,m.DB_NAME]
 with db() as d:
  with d.cursor() as c:
   c.execute('SHOW TABLES');tables=[r[0] for r in c.fetchall() if r[0].startswith('ai_person_') or r[0] in {'ai_agent_chat_history','ai_memory_override'}]
 for name,extra in [('schema.sql',['--no-data']),('memory-private.sql',tables)]:
  with (B/name).open('wb') as f:
   r=subprocess.run(args+extra,env=env,stdout=f,stderr=subprocess.PIPE)
   if r.returncode:raise RuntimeError('database_backup_failed')
  os.chmod(B/name,0o600)
 atomic(B/'database-backup-metadata.json',json.dumps({'created_at':time.time(),'tables':tables,'schema_sha256':sha(B/'schema.sql'),'memory_sha256':sha(B/'memory-private.sql')}).encode())
def gate():
 assert read(S/'persona-config-equivalence.json')['matches'] is True
 live=read(S/'live-config-readonly.json');assert live['model_name']=='qwen3.7-plus' and float(live['temperature'])==.4 and live['enable_thinking'] is False and live['hardware_billing'] is True
 f=read(S/'final-freeze.json');r=[json.loads(x) for x in (S/'final-results.jsonl').read_text().splitlines()];cases=read(S/'final-cases.json');summary=read(S/'final-summary.json')
 requirements={'complete':len(r)==len(cases)==322 and len({x['case']['id'] for x in r})==322,'no_failed_rows':all(not x['errors'] for x in r),'real_final_model_turns':sum(bool(x.get('outcome',{}).get('model_calls')) for x in r)>=240,'new_independent_holdout':sum(bool(x['case'].get('independent_holdout')) for x in r)==60,'cases_frozen':sha(S/'final-cases.json')==f['cases_sha256'],'python_frozen':all(sha(S/'work'/n)==h for n,h in f['source'].items()),'fixtures_frozen':all(sha(S/n)==h for n,h in f['fixture_hashes'].items()),'java_frozen':all(sha(S/'manager-api/src/main/java/xiaozhi/modules/personmemory'/n)==h for n,h in f['java_source'].items()),'jar_frozen':sha(S/'manager-api/target/xiaozhi-esp32-api.jar')==f['jar_sha256'],'summary_complete':summary['cases']==322 and not summary['failed_ids']}
 for n in ['latest-regression-summary.json','focused-regression-summary.json','lifecycle-summary.json']:
  x=read(S/n);requirements[n]=not x.get('failures') and not x.get('errors') and x.get('tests',x.get('run',0))>0
 for n in ['http-api-results.json','live-query-note-results.json','query-lifecycle-replay-summary.json','relative-feedback-replay-summary.json','relative-feedback-final-check.json','read-repair-final-check.json']:requirements[n]=read(S/n).get('passed') is True
 xml=list((S/'manager-api/target/surefire-reports').glob('TEST-*.xml'));suite=[ET.parse(p).getroot().attrib for p in xml];requirements['java_database_tests']=sum(int(x['tests']) for x in suite)>=28 and all(not int(x['failures']) and not int(x['errors']) and not int(x['skipped']) for x in suite)
 audio=read(S/'real-tts-results.json');requirements['real_audio']=len(audio)==3 and all(x['frames']>0 and sha(S/x['path'])==x['sha256'] for x in audio)
 vision=read(S/'vision-http-results.json');requirements['vision_http']=len(vision)>=5 and vision[0]['status']==401 and vision[1]['status']==403 and any(x.get('heartbeat_ticks_during_request',0)>=5 for x in vision)
 sys.path.insert(0,str(S));from budget import Budget,LIMITS
 usage=Budget(S/'budget.sqlite3').report();requirements['budget']=all(x['used']<=x['limit'] for x in usage.values())
 common={'self_audio_speaker_set_volume','self_screen_set_brightness','alarm_set','add_reminder','note_add','reminder_action','reminder_get_current'}
 positive=[x for x in r if x['case']['tool'] and not(x['case'].get('setup')=='photo_retry' and x['case'].get('multi_step')==0)];normal=[x['duration_ms'] for x in r if 'duration_ms' in x];normal.sort()
 out={'requirements':requirements,'passed':all(requirements.values()),'cases':len(r),'verified_operations':len(positive),'common_cases':sum(x['case']['tool'] in common for x in r),'real_model_turns':sum(bool(x.get('outcome',{}).get('model_calls')) for x in r),'model_requests':sum(x.get('outcome',{}).get('model_calls',0) for x in r),'p50_ms':normal[len(normal)//2],'p95_ms':normal[int(len(normal)*.95)],'budget':usage,'at':time.time(),'hardware':False,'source':f['source'],'jar_sha256':f['jar_sha256']}
 atomic(S/'release-gate.json',json.dumps(out,ensure_ascii=False,indent=2).encode())
 if not out['passed']:raise RuntimeError('unmet_gates:'+','.join(k for k,v in requirements.items() if not v))
 return out
async def health(ws=8040,http=8043,internal=8046,manager=18003,public=False):
 import aiohttp
 checks=[]
 async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=7)) as c:
  targets=[('http',f'http://127.0.0.1:{http}/','GET',404),('internal_auth',f'http://127.0.0.1:{internal}/api/v1/device/send','POST',401),('habit_auth',f'http://127.0.0.1:{internal}/api/v1/habit/sync','POST',401),('manager_auth',f'http://127.0.0.1:{manager}/xiaozhi/user-identities/internal/state/0','GET',401)]
  if public:targets += [('www','https://www.realecho.cn/','GET',200),('api','https://api.realecho.cn/','GET',200)]
  for name,url,method,status in targets:
   try:
    async with c.request(method,url,json={} if method=='POST' else None) as res:
     await res.read();checks.append({'name':name,'status':res.status,'passed':res.status==status})
   except Exception as e:checks.append({'name':name,'passed':False,'error':type(e).__name__})
  urls=[('ws',f'http://127.0.0.1:{ws}/xiaozhi/v1/')]
  if public:urls += [('public_ws','https://www.realecho.cn/xiaozhi/v1/'),('api_ws','https://api.realecho.cn/xiaozhi/v1/')]
  for name,url in urls:
   try:
    async with c.ws_connect(url,headers={'Device-Id':'00:00:00:00:00:00','Client-Id':'experience-unauthenticated-health'}) as w:
     msg=await w.receive(timeout=4);body=json.loads(msg.data) if msg.type==aiohttp.WSMsgType.TEXT else {};checks.append({'name':name,'passed':bool(body.get('type')=='error' or body.get('error')),'code':body.get('code')})
   except aiohttp.WSServerHandshakeError as e:checks.append({'name':name,'passed':e.status in {401,403},'status':e.status})
   except Exception as e:checks.append({'name':name,'passed':False,'error':type(e).__name__})
 return checks
def ready(**kw):
 end=time.time()+90
 while True:
  checks=asyncio.run(health(**kw))
  if all(x['passed'] for x in checks):return checks
  if time.time()>end:raise RuntimeError('not_ready:'+json.dumps(checks))
  time.sleep(1)
def reload_nginx():command(['nginx','-t']);command(['systemctl','reload','nginx'])
def copy_runtime():
 if RUNTIME.exists():raise RuntimeError('runtime_already_exists')
 shared={'data','models','logs','tmp'}
 shutil.copytree(ROOT,RUNTIME,ignore=shutil.ignore_patterns(*shared,'__pycache__','.git','.pytest_cache'))
 for n in shared:
  if (ROOT/n).exists():(RUNTIME/n).symlink_to(ROOT/n,target_is_directory=True)
 for n in read(S/'changed-files.json'):atomic(RUNTIME/n,(S/'work'/n).read_bytes(),0o644)
def serve():
 os.chdir(ROOT);sys.path.insert(0,str(RUNTIME));os.environ['FULL_TOOL_HARNESS']='1';os.environ['HARNESS_LEDGER_PATH']=str(ROOT/'data/harness/operations.sqlite3')
 import config.config_loader as loader
 original=loader.get_config_from_api
 def configured(config):
  result=original(config);result['server']=dict(result.get('server') or {},ip='127.0.0.1',port=8040,http_port=8043,broadcast_http_port=8046);result['harness']=dict(result.get('harness') or {},enabled=True);return result
 loader.get_config_from_api=configured;runpy.run_path(str(RUNTIME/'app.py'),run_name='__main__')
def prepare():
 evidence=gate()
 if STATE.exists() or B.exists() or COMPAT.exists():raise RuntimeError('release_collision')
 if shutil.disk_usage(RELEASE).free<700*1024*1024:raise RuntimeError('insufficient_free_disk')
 old={n:next(a for a in apps() if a['name']==n and a['pm2_env']['status']=='online') for n in ['xiaozhi-server','manager-api']}
 assert old['xiaozhi-server']['pm2_env']['pm_exec_path']=='/root/prjs/releases/tool-harness-20261008/rollout.py';assert old['manager-api']['pm2_env']['args']==['/root/prjs/xiaozhi-esp32-server/secrets/start-manager-api.sh']
 baseline=read(S/'baseline.json');names=read(S/'changed-files.json');drift=[n for n in names if (sha(ROOT/n) if (ROOT/n).exists() else None)!=baseline.get(n)]
 if drift:raise RuntimeError('production_source_drift:'+','.join(drift))
 unrelated=[n for n,h in baseline.items() if n.endswith('.py') and n not in names and not n.startswith('test/') and (not (ROOT/n).is_file() or sha(ROOT/n)!=h)]
 if unrelated:raise RuntimeError('unrelated_source_drift:'+','.join(unrelated))
 java_names=['MemoryDailyWorker.java','PersonMemoryController.java','PersonMemoryService.java','MemoryMaterialPolicy.java','RecentArchiveService.java'];java_rel=['src/main/java/xiaozhi/modules/personmemory/'+n for n in java_names]
 import tarfile
 with tarfile.open(RELEASE/'backup/sources-private.tgz') as t:
  for n in java_rel:
   if t.extractfile('manager-api/'+n).read()!=(JAVA/n).read_bytes():raise RuntimeError('java_source_drift:'+n)
 for port in [8040,8043,8046,18003]:
  with socket.socket() as x:
   if x.connect_ex(('127.0.0.1',port))==0:raise RuntimeError('port_collision:'+str(port))
 B.mkdir(mode=0o700);backup_database();private=[]
 for n in names:
  p=ROOT/n
  if p.exists():atomic(B/'python'/n,p.read_bytes())
 for n in java_rel:atomic(B/'java'/n,(JAVA/n).read_bytes())
 shutil.copy2(JAVA/'target/xiaozhi-esp32-api.jar',B/'old-api.jar');os.chmod(B/'old-api.jar',0o600)
 atomic(B/'nginx-www.conf',NGINX.read_bytes());atomic(B/'nginx-internal.conf',INTERNAL.read_bytes())
 ledger=ROOT/'data/harness/operations.sqlite3'
 if ledger.exists():
  with sqlite3.connect(ledger) as a,sqlite3.connect(B/'operations.sqlite3') as b:a.backup(b)
 envs={n:env_of(a) for n,a in old.items()}
 for n,a in old.items():atomic(B/(n+'-rollback.json'),json.dumps({'apps':[{'name':n,'script':a['pm2_env']['pm_exec_path'],'args':a['pm2_env'].get('args',[]),'cwd':a['pm2_env']['pm_cwd'],'interpreter':a['pm2_env'].get('exec_interpreter','none'),'env':envs[n]}]}).encode())
 billing_names=['HW_BILLING_SERVICE_KEY','HW_BILLING_GATEWAY_ORIGIN','HW_BILLING_AUDIO_GATEWAY_ORIGIN']
 billing_hashes={n:hashlib.sha256(envs['xiaozhi-server'].get(n,'').encode()).hexdigest() for n in billing_names}
 state={'billing_env_hashes':billing_hashes,'phase':'prepared','started_at':time.time(),'gate':evidence,'old':{n:a['pm_id'] for n,a in old.items()},'new':{},'baseline':{n:baseline.get(n) for n in names},'source':evidence['source'],'java_rel':java_rel,'nginx':str(NGINX),'old_nginx_sha':sha(NGINX),'old_internal_sha':sha(INTERNAL),'hardware':False,'ledger_retained':True}
 save(state);copy_runtime();shutil.copy2(S/'manager-api/target/xiaozhi-esp32-api.jar',RELEASE/'xiaozhi-esp32-api.jar');os.chmod(RELEASE/'xiaozhi-esp32-api.jar',0o600)
 wrapper=Path('/root/prjs/xiaozhi-esp32-server/secrets/start-manager-api.sh').read_text();wrapper,count=re.subn(r'exec java -jar target/xiaozhi-esp32-api\.jar',f'exec java -jar {RELEASE}/xiaozhi-esp32-api.jar --server.port=18003',wrapper);assert count==1,'manager_start_shape';atomic(RELEASE/'start-manager-api.sh',wrapper.encode(),0o700)
 atomic(RELEASE/'release.py',Path(__file__).read_bytes(),0o700)
 return state,envs

def apply():
 state,envs=prepare()
 try:
  with db() as d:
   with d.cursor() as c:
    c.execute("SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='ai_person_material' AND COLUMN_NAME='recall_allowed'")
    if not c.fetchone()[0]:c.execute('ALTER TABLE ai_person_material ADD COLUMN recall_allowed BOOLEAN NOT NULL DEFAULT TRUE')
  state['phase']='database_compatible';save(state)
  before={x['pm_id'] for x in apps()};command(['pm2','start','/usr/bin/bash','--name','manager-api','--cwd',str(JAVA),'--force','--',str(RELEASE/'start-manager-api.sh')],envs['manager-api'])
  new=[x for x in apps() if x['pm_id'] not in before and x['pm2_env'].get('args')==[str(RELEASE/'start-manager-api.sh')]];assert len(new)==1;state['new']['manager-api']=new[0]['pm_id'];save(state)
  # The periodic memory worker has an initial delay of 10s. Keep cutover below it.
  import requests
  deadline=time.time()+100;accepted=None
  while time.time()<deadline:
   try:
    res=requests.get('http://127.0.0.1:18003/xiaozhi/user-identities/internal/state/0',timeout=.3)
    if res.status_code==401:accepted=time.time();break
   except requests.RequestException:pass
   if app(state['new']['manager-api'])['pm2_env']['status']!='online':raise RuntimeError('manager_exited')
   time.sleep(.1)
  if accepted is None:raise RuntimeError('manager_not_ready')
  conf=NGINX.read_text();conf,n=re.subn(r'(upstream\s+manager_api_http\s*\{\s*server\s+127\.0\.0\.1:)8002(?=;)',r'\g<1>18003',conf);assert n==1;atomic(NGINX,conf.encode(),0o644);state['new_nginx_sha']=sha(NGINX);save(state);reload_nginx()
  command(['pm2','stop',str(state['old']['manager-api'])]);state['api_overlap_seconds']=time.time()-accepted
  if state['api_overlap_seconds']>=8:raise RuntimeError('manager_scheduler_overlap_budget')
  atomic(COMPAT,b'server { listen 127.0.0.1:8002; server_name localhost; location / { proxy_pass http://127.0.0.1:18003; proxy_http_version 1.1; proxy_set_header Host $host; proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for; proxy_read_timeout 65s; } }\n',0o644);state['compat_sha']=sha(COMPAT);save(state);reload_nginx();state['phase']='manager_switched';save(state)
  before={x['pm_id'] for x in apps()};command(['pm2','start',str(RELEASE/'release.py'),'--interpreter',PY,'--name','xiaozhi-server','--cwd',str(ROOT),'--force','--','serve'],envs['xiaozhi-server'])
  new=[x for x in apps() if x['pm_id'] not in before and x['pm2_env'].get('pm_exec_path')==str(RELEASE/'release.py')];assert len(new)==1;state['new']['xiaozhi-server']=new[0]['pm_id'];save(state);state['candidate_readiness']=ready();save(state)
  conf=NGINX.read_text()
  for label,old,new in [('xiaozhi_ws',8020,8040),('xiaozhi_http',8023,8043)]:
   conf,n=re.subn(r'(upstream\s+'+label+r'\s*\{\s*server\s+127\.0\.0\.1:)'+str(old)+r'(?=;)',r'\g<1>'+str(new),conf);assert n==1
  internal=INTERNAL.read_text();assert internal.count('127.0.0.1:8026')==1
  atomic(NGINX,conf.encode(),0o644);atomic(INTERNAL,internal.replace('127.0.0.1:8026','127.0.0.1:8046').encode(),0o644);state['new_nginx_sha']=sha(NGINX);state['new_internal_sha']=sha(INTERNAL);save(state);reload_nginx();state['phase']='public_switched';save(state)
  state['formal_readiness']=ready(internal=8006,public=True)
  command(['pm2','stop',str(state['old']['xiaozhi-server'])])
  for n in read(S/'changed-files.json'):atomic(ROOT/n,(S/'work'/n).read_bytes(),0o644)
  for n in state['java_rel']:atomic(JAVA/n,(S/'manager-api'/n).read_bytes(),0o644)
  atomic(JAVA/'target/xiaozhi-esp32-api.jar',(RELEASE/'xiaozhi-esp32-api.jar').read_bytes(),0o644)
  state['installed_java']={n:sha(JAVA/n) for n in state['java_rel']};state['phase']='observing';state['deployed_at']=time.time();save(state);command(['pm2','save']);print(json.dumps({'phase':state['phase'],'ids':state['new'],'api_overlap_seconds':state['api_overlap_seconds'],'deployed_at':state['deployed_at'],'checks':state['formal_readiness']},ensure_ascii=False),flush=True)
 except Exception as exc:
  try:rollback('deployment_exception:'+type(exc).__name__)
  except Exception as e:print('rollback_failed:'+type(e).__name__,flush=True)
  raise

def rollback(reason):
 s=read(STATE)
 for n,h in s['baseline'].items():
  p=ROOT/n;actual=sha(p) if p.exists() else None
  if actual not in {h,s['source'][n]}:raise RuntimeError('rollback_source_drift:'+n)
  if h is None:
   if p.exists():p.unlink()
  else:atomic(p,(B/'python'/n).read_bytes(),0o644)
 for n in s['java_rel']:atomic(JAVA/n,(B/'java'/n).read_bytes(),0o644)
 atomic(JAVA/'target/xiaozhi-esp32-api.jar',(B/'old-api.jar').read_bytes(),0o644)
 # Restore the old API port; formal traffic remains on the new API until old is ready.
 if COMPAT.exists():
  if sha(COMPAT)!=s.get('compat_sha'):raise RuntimeError('compat_drift')
  COMPAT.unlink();reload_nginx()
 for name in ['manager-api','xiaozhi-server']:
  old=next((x for x in apps() if x['pm_id']==s['old'][name]),None)
  if old and old['pm2_env']['status']=='stopped':command(['pm2','restart',str(old['pm_id'])])
  elif old is None:command(['pm2','start',str(B/(name+'-rollback.json')),'--force'])
 # Prevent dual memory workers before the old initial delay expires.
 import requests
 end=time.time()+100
 while time.time()<end:
  try:
   if requests.get('http://127.0.0.1:8002/xiaozhi/user-identities/internal/state/0',timeout=.3).status_code==401:break
  except requests.RequestException:pass
  time.sleep(.1)
 else:raise RuntimeError('old_manager_not_ready')
 conf=NGINX.read_text();conf=re.sub(r'(upstream\s+manager_api_http\s*\{\s*server\s+127\.0\.0\.1:)18003(?=;)',r'\g<1>8002',conf);atomic(NGINX,conf.encode(),0o644);reload_nginx()
 if 'manager-api' in s['new']:command(['pm2','stop',str(s['new']['manager-api'])])
 ready(ws=8020,http=8023,internal=8026,manager=8002)
 if sha(NGINX) not in {s.get('new_nginx_sha'),s['old_nginx_sha'],sha(B/'nginx-www.conf')}:
  # Only the manager upstream has just been changed by this rollback.
  current=NGINX.read_text();known=(B/'nginx-www.conf').read_text().replace('127.0.0.1:8020','127.0.0.1:8040').replace('127.0.0.1:8023','127.0.0.1:8043')
  if current!=known:raise RuntimeError('rollback_nginx_drift')
 atomic(NGINX,(B/'nginx-www.conf').read_bytes(),0o644);atomic(INTERNAL,(B/'nginx-internal.conf').read_bytes(),0o644);reload_nginx()
 if 'xiaozhi-server' in s['new']:command(['pm2','stop',str(s['new']['xiaozhi-server'])])
 command(['pm2','save']);s['phase']='rolled_back';s['reason']=reason;s['rolled_back_at']=time.time();save(s);print(json.dumps({'phase':s['phase'],'reason':reason,'ledger_retained':True}),flush=True)

def metadata(s):
 out={'source_matches':all(sha(ROOT/n)==h and sha(RUNTIME/n)==h for n,h in s['source'].items()),'jar_matches':sha(RELEASE/'xiaozhi-esp32-api.jar')==s['gate']['jar_sha256'],'java_matches':all(sha(JAVA/n)==h for n,h in s['installed_java'].items()),'config_matches':sha(NGINX)==s['new_nginx_sha'] and sha(INTERNAL)==s['new_internal_sha'] and sha(COMPAT)==s['compat_sha']}
 proc=[app(i) for i in s['new'].values()];out['processes_healthy']=all(a['pm2_env']['status']=='online' and a['pm2_env'].get('restart_time',0)==0 for a in proc)
 env=env_of(app(s['new']['xiaozhi-server']));out['billing_env_matches']=all(hashlib.sha256(env.get(n,'').encode()).hexdigest()==h for n,h in s['billing_env_hashes'].items())
 p=ROOT/'data/harness/operations.sqlite3'
 if p.exists():
  with sqlite3.connect('file:'+str(p)+'?mode=ro',uri=True) as d:
   out['states']=dict(d.execute('SELECT state,count(*) FROM dispatch GROUP BY state'));out['duplicate_groups']=d.execute('SELECT COUNT(*) FROM (SELECT 1 FROM dispatch GROUP BY scope,turn,fingerprint HAVING COUNT(*)>1)').fetchone()[0]
  out['ledger_private']=p.stat().st_mode&0o777==0o600 and p.parent.stat().st_mode&0o777==0o700
 else:out['ledger_private']=False
 return out

def observe():
 s=read(STATE);assert s['phase']=='observing';sys.path.insert(0,str(S));from budget import Budget
 budget=Budget(S/'budget.sqlite3');rows=[];end=s['deployed_at']+1800
 while True:
  budget.reserve('case','production-observation-snapshot');checks=asyncio.run(health(internal=8006,public=True));m=metadata(s);ok=all(x['passed'] for x in checks) and all(m[k] for k in ['source_matches','jar_matches','java_matches','config_matches','processes_healthy','ledger_private','billing_env_matches']) and m.get('duplicate_groups',0)==0
  rows.append({'at':time.time(),'passed':ok,'checks':checks,'metadata':m});atomic(RELEASE/'observation.json',json.dumps({'records':rows,'hardware':False},indent=2).encode());print(json.dumps({'snapshot':len(rows),'elapsed_seconds':round(time.time()-s['deployed_at']),'passed':ok}),flush=True)
  if not ok:rollback('observation_health_failed');return
  if time.time()>=end:break
  time.sleep(min(60,max(0,end-time.time())))
 for name,i in s['old'].items():
  old=app(i);assert old['pm2_env']['status']=='stopped';command(['pm2','delete',str(i)])
 command(['pm2','save']);s['phase']='deployed_verified';s['finished_at']=time.time();s['observation_count']=len(rows);s['hardware']=False;save(s);print(json.dumps({'phase':s['phase'],'observed_seconds':round(s['finished_at']-s['deployed_at']),'snapshots':len(rows),'budget':budget.report()}),flush=True)
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('action',choices=['gate','apply','serve','observe','rollback']);arg=a.parse_args()
 if arg.action=='gate':print(json.dumps(gate(),ensure_ascii=False))
 elif arg.action=='apply':apply()
 elif arg.action=='serve':serve()
 elif arg.action=='observe':observe()
 else:rollback('operator_requested')
