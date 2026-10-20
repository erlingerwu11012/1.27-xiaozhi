"""Authorized release; frozen gates, new listeners before nginx switch, reversible deployment."""
from pathlib import Path
import argparse,asyncio,hashlib,importlib.util,json,os,re,runpy,shutil,socket,sqlite3,subprocess,sys,time,tarfile,xml.etree.ElementTree as ET
S=Path('/root/prjs/tmp/hardware-repair-20261009');REL=Path('/root/prjs/releases/hardware-repair-20261009');B=REL/'deploy-backup';STATE=REL/'deployment-state.json'
ROOT=Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server');JAVA=ROOT.parent/'manager-api';RUNTIME=REL/'runtime';PY='/root/miniconda3/envs/xiaozhi-esp32-server/bin/python'
NGINX=Path('/etc/nginx/sites-enabled/www.realecho.cn').resolve();INTERNAL=Path('/etc/nginx/conf.d/tool-harness-internal.conf');COMPAT=Path('/etc/nginx/conf.d/experience-manager-compat.conf')
spec=importlib.util.spec_from_file_location('previous_release','/root/prjs/releases/experience-repair-20261009/release.py');old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
read=old.read;sha=old.sha;atomic=old.atomic;command=old.command;apps=old.apps;app=old.app;env_of=old.env_of;db=old.db
PORTS=dict(ws=8060,http=8063,internal=8066,manager=18005)
def save(s):atomic(STATE,json.dumps(s,ensure_ascii=False,indent=2).encode())
def redis_client():
 import yaml
 env=env_of(next(x for x in apps() if x['name']=='manager-api' and x['pm2_env']['status']=='online'))
 values={}
 for p in [JAVA/'src/main/resources/application.yml',JAVA/'src/main/resources/application-dev.yml']:
  if p.exists():values.update(((yaml.safe_load(p.read_text()) or {}).get('spring',{}).get('data',{}).get('redis',{})))
 def v(k,default):
  x=env.get('SPRING_DATA_REDIS_'+k.upper(),values.get(k,default))
  if isinstance(x,str) and x.startswith('${'):
   a,_,b=x[2:-1].partition(':');return env.get(a,b or default)
  return x
 class Redis:
  def execute(self,*args):
   with socket.create_connection((v('host','127.0.0.1'),int(v('port',6379))),timeout=4) as sock:
    stream=sock.makefile('rb')
    def call(*parts):
     values=[str(x).encode() for x in parts];sock.sendall(b'*'+str(len(values)).encode()+b'\r\n'+b''.join(b'$'+str(len(x)).encode()+b'\r\n'+x+b'\r\n' for x in values));line=stream.readline();kind=line[:1];body=line[1:-2]
     if kind==b'-':raise RuntimeError('redis_command_failed')
     if kind==b'$':
      size=int(body)
      if size<0:return None
      value=stream.read(size);assert stream.read(2)==b'\r\n';return value
     if kind==b':':return int(body)
     return body
    password=v('password',None)
    if password:
     username=v('username',None);call('AUTH',username,password) if username else call('AUTH',password)
    database=int(v('database',0))
    if database:call('SELECT',database)
    return call(*args)
  def ping(self):return self.execute('PING')==b'PONG'
  def hget(self,*a):return self.execute('HGET',*a)
  def hdel(self,*a):return self.execute('HDEL',*a)
  def delete(self,*a):return self.execute('DEL',*a)
 return Redis()
def evict_threshold():
 r=redis_client();r.hdel('sys:params','server.voiceprint_similarity_threshold');r.delete('server:config')
def gate():
 f=read(S/'resume-final-freeze.json');rows=[json.loads(x) for x in (S/'resume-final-results.jsonl').read_text().splitlines()];cases=read(S/'final-cases.json');summary=read(S/'resume-final-summary.json')
 requirements={'complete':len(rows)==len(cases) and len({x['case']['id'] for x in rows})==len(cases),'no_failed_rows':all(not x['errors'] for x in rows),'real_model_turns':sum(any(d.get('usage') for d in x.get('decisions',[])) for x in rows)>=240,'independent_holdout':sum(bool(x['case'].get('independent_holdout')) for x in rows)>=60,'frozen_corpus':sha(S/'final-cases.json')==f['cases_sha256'],'frozen_python':all(sha(S/'work'/n)==h for n,h in f['source'].items()),'frozen_java':all(sha(S/'manager-api/src/main/java/xiaozhi/modules/personmemory'/n)==h for n,h in f['java_source'].items()),'frozen_jar':sha(S/'manager-api/target/xiaozhi-esp32-api.jar')==f['jar_sha256'],'frozen_fixtures':all(sha(S/n)==h for n,h in f['fixture_hashes'].items()),'summary':not summary['failed_ids'] and summary['cases']==len(cases)}
 audit=read(S/'resume-holdout-audit.json');requirements['audited_independent_holdout']=audit['passed'] and audit['audited_independent_count']>=60 and audit['results_sha256']==sha(S/'resume-final-results.jsonl')
 x=read(S/'resume-regression-summary.json');requirements['python_regression']=x['tests']>=199 and not x['failures'] and not x['errors']
 for name in ['resume-memory-regression.json','http-api-results.json','firmware-host-results.json','photo-worker-host-results.json','supplement-results.json','chat-fix-results.json','resume-speech-regression.json','card-progress-regression.json','card-view-regression.json','relative-claims-regression.json','shipping-state-regression.json','java-drift-preflight.json','python-drift-preflight.json']:
  requirements[name]=read(S/name)['passed'] is True
 suites=[ET.parse(p).getroot().attrib for p in (S/'manager-api/target/surefire-reports').glob('TEST-*.xml')];requirements['java_tests']=sum(int(x['tests']) for x in suites)>=31 and all(int(x['errors'])==int(x['failures'])==0 for x in suites)
 voice=read(S/'voice-backend-threshold.json');requirements['voice_backend']=voice['allows_client_threshold_0_3'] and voice['process_online']
 requirements['persona_equivalence']=read(S/'resume-persona-equivalence.json')['matched'] is True
 review=read(S/'resume-final-review.json');requirements['speech_review']=review['passed'] and review['reviewed_cases']==len(cases)
 audio=read(S/'real-tts-results.json');requirements['tts']=len(audio)>=3 and all(x['frames']>0 and sha(S/x['path'])==x['sha256'] for x in audio)
 vision=read(S/'vision-http-results.json');requirements['vision']=len(vision)>=5 and vision[0]['status']==401 and vision[1]['status']==403 and any(x.get('heartbeat_ticks_during_request',0)>=5 for x in vision)
 requirements['memory_restore_test']=read(S/'memory-cleanup-restore-test.json')['passed']
 out={'passed':all(requirements.values()),'requirements':requirements,'cases':len(rows),'real_model_turns':sum(any(d.get('usage') for d in x.get('decisions',[])) for x in rows),'audited_independent_holdout':audit['audited_independent_count'],'source':f['source'],'jar_sha256':f['jar_sha256'],'at':time.time(),'hardware':False}
 atomic(S/'resume-release-gate.json',json.dumps(out,indent=2).encode());assert out['passed'],'unmet gates:'+','.join(k for k,v in requirements.items() if not v);return out

def ready(public=False):return old.ready(**PORTS,public=public)
def reload():command(['nginx','-t']);command(['systemctl','reload','nginx'])
def serve():
 os.chdir(ROOT);sys.path.insert(0,str(RUNTIME));os.environ['FULL_TOOL_HARNESS']='1';os.environ['HARNESS_LEDGER_PATH']=str(ROOT/'data/harness/operations.sqlite3')
 import config.config_loader as loader
 original=loader.get_config_from_api
 def configure(c):
  r=original(c);r['server']=dict(r.get('server') or {},ip='127.0.0.1',port=8060,http_port=8063,broadcast_http_port=8066);r['harness']=dict(r.get('harness') or {},enabled=True);return r
 loader.get_config_from_api=configure;runpy.run_path(str(RUNTIME/'app.py'),run_name='__main__')
def prepare():
 evidence=gate();assert not STATE.exists() and not B.exists(),'release collision'
 assert shutil.disk_usage(S).free>650*1024**2,'insufficient disk'
 live={n:next(x for x in apps() if x['name']==n and x['pm2_env']['status']=='online') for n in ['manager-api','xiaozhi-server']}
 assert live['xiaozhi-server']['pm2_env']['pm_exec_path']=='/root/prjs/releases/experience-repair-20261009/release.py'
 assert live['manager-api']['pm2_env']['args']==['/root/prjs/releases/experience-repair-20261009/start-manager-api.sh']
 for port in PORTS.values():
  with socket.socket() as x:assert x.connect_ex(('127.0.0.1',port))!=0,'port collision'
 base=Path('/root/prjs/releases/experience-repair-20261009/runtime')
 with tarfile.open(S/'baseline/runtime.tgz') as t:
  for n in evidence['source']:
   member=next((x for x in t.getmembers() if x.name=='./'+n),None)
   if member is None:assert not (base/n).exists() and not (ROOT/n).exists(),'new source collision:'+n
   else:
    original=t.extractfile(member).read();assert (base/n).read_bytes()==original and (ROOT/n).read_bytes()==original,'live source drift:'+n
 B.mkdir(parents=True,mode=0o700);old.B=B;old.backup_database()
 ledger=ROOT/'data/harness/operations.sqlite3'
 if ledger.exists():
  with sqlite3.connect(ledger) as a,sqlite3.connect(B/'operations.sqlite3') as b:a.backup(b)
  os.chmod(B/'operations.sqlite3',0o600)
 baseline={n:sha(ROOT/n) if (ROOT/n).exists() else None for n in evidence['source']}
 for n in evidence['source']:
  if (ROOT/n).exists():atomic(B/'python'/n,(ROOT/n).read_bytes())
 java=['src/main/java/xiaozhi/modules/personmemory/'+n for n in ['RecentArchiveService.java','PersonMemoryService.java','PersonMemoryController.java']]+[str(next((S/'manager-api/src/main/java').rglob('ConfigServiceImpl.java')).relative_to(S/'manager-api'))]
 for n in java:atomic(B/'java'/n,(JAVA/n).read_bytes())
 atomic(B/'old-api.jar',(JAVA/'target/xiaozhi-esp32-api.jar').read_bytes())
 for n,p in [('www',NGINX),('internal',INTERNAL),('compat',COMPAT)]:atomic(B/(n+'.conf'),p.read_bytes())
 envs={n:env_of(a) for n,a in live.items()}
 for n,a in live.items():atomic(B/(n+'-rollback.json'),json.dumps({'apps':[{'name':n,'script':a['pm2_env']['pm_exec_path'],'args':a['pm2_env'].get('args',[]),'cwd':a['pm2_env']['pm_cwd'],'interpreter':a['pm2_env'].get('exec_interpreter','none'),'env':envs[n]}]}).encode())
 with db() as d:
  with d.cursor() as c:c.execute("SELECT param_value FROM sys_params WHERE param_code='server.voiceprint_similarity_threshold'");threshold=c.fetchone()[0]
 s={'phase':'prepared','started_at':time.time(),'gate':evidence,'source':evidence['source'],'old':{n:a['pm_id'] for n,a in live.items()},'new':{},'java_rel':java,'old_threshold':threshold,'baseline':baseline,'billing_hashes':{n:hashlib.sha256(envs['xiaozhi-server'].get(n,'').encode()).hexdigest() for n in ['HW_BILLING_SERVICE_KEY','HW_BILLING_GATEWAY_ORIGIN','HW_BILLING_AUDIO_GATEWAY_ORIGIN']},'hardware':False}
 save(s)
 shared={'data','models','logs','tmp'};shutil.copytree(base,RUNTIME,ignore=shutil.ignore_patterns(*shared,'__pycache__','.pytest_cache','.git'))
 for n in shared:
  if (ROOT/n).exists():(RUNTIME/n).symlink_to(ROOT/n,target_is_directory=True)
 for n in evidence['source']:atomic(RUNTIME/n,(S/'work'/n).read_bytes(),0o644)
 atomic(REL/'xiaozhi-esp32-api.jar',(S/'manager-api/target/xiaozhi-esp32-api.jar').read_bytes())
 wrapper=Path('/root/prjs/releases/experience-repair-20261009/start-manager-api.sh').read_text();wrapper,count=re.subn(r'exec java -jar .* --server.port=18003',f'exec java -jar {REL}/xiaozhi-esp32-api.jar --server.port=18005',wrapper);assert count==1
 atomic(REL/'start-manager-api.sh',wrapper.encode(),0o700);atomic(REL/'release.py',Path(__file__).read_bytes(),0o700)
 return s,envs

def apply():
 s,envs=prepare()
 try:
  before={x['pm_id'] for x in apps()};command(['pm2','start','/usr/bin/bash','--name','manager-api','--cwd',str(JAVA),'--force','--',str(REL/'start-manager-api.sh')],envs['manager-api']);new=[x for x in apps() if x['pm_id'] not in before and x['pm2_env'].get('args')==[str(REL/'start-manager-api.sh')]];assert len(new)==1;s['new']['manager-api']=new[0]['pm_id'];save(s)
  import requests
  end=time.time()+120
  while time.time()<end:
   try:
    if requests.get('http://127.0.0.1:18005/xiaozhi/user-identities/internal/state/0',timeout=.3).status_code==401:break
   except requests.RequestException:pass
   time.sleep(.1)
  else:raise RuntimeError('manager not ready')
  accepted=time.time();conf=NGINX.read_text();conf,n=re.subn(r'(upstream\s+manager_api_http\s*\{\s*server\s+127\.0\.0\.1:)18003(?=;)',r'\g<1>18005',conf);assert n==1
  atomic(NGINX,conf.encode(),0o644);atomic(COMPAT,COMPAT.read_text().replace('127.0.0.1:18003','127.0.0.1:18005').encode(),0o644);reload();command(['pm2','stop',str(s['old']['manager-api'])]);s['api_overlap_seconds']=time.time()-accepted;assert s['api_overlap_seconds']<8;save(s)
  with db() as d:
   with d.cursor() as c:
    c.execute("UPDATE sys_params SET param_value='0.3' WHERE param_code='server.voiceprint_similarity_threshold'");assert c.rowcount==1 or s['old_threshold']=='0.3'
  evict_threshold();s['threshold_updated']=True;save(s)
  before={x['pm_id'] for x in apps()};command(['pm2','start',str(REL/'release.py'),'--interpreter',PY,'--name','xiaozhi-server','--cwd',str(ROOT),'--force','--','serve'],envs['xiaozhi-server']);new=[x for x in apps() if x['pm_id'] not in before and x['pm2_env']['pm_exec_path']==str(REL/'release.py')];assert len(new)==1;s['new']['xiaozhi-server']=new[0]['pm_id'];save(s);s['candidate_health']=ready()
  conf=NGINX.read_text()
  for label,a,b in [('xiaozhi_ws',8040,8060),('xiaozhi_http',8043,8063)]:
   conf,n=re.subn(r'(upstream\s+'+label+r'\s*\{\s*server\s+127\.0\.0\.1:)'+str(a)+r'(?=;)',r'\g<1>'+str(b),conf);assert n==1
  internal=INTERNAL.read_text();assert internal.count('127.0.0.1:8046')==1;atomic(NGINX,conf.encode(),0o644);atomic(INTERNAL,internal.replace('127.0.0.1:8046','127.0.0.1:8066').encode(),0o644);reload()
  s['public_health']=ready(public=True);command(['pm2','stop',str(s['old']['xiaozhi-server'])])
  for n in s['source']:atomic(ROOT/n,(S/'work'/n).read_bytes(),0o644)
  for n in s['java_rel']:atomic(JAVA/n,(S/'manager-api'/n).read_bytes(),0o644)
  atomic(JAVA/'target/xiaozhi-esp32-api.jar',(REL/'xiaozhi-esp32-api.jar').read_bytes(),0o644)
  s['java_hashes']={n:sha(JAVA/n) for n in s['java_rel']};s['config_hashes']={str(p):sha(p) for p in [NGINX,INTERNAL,COMPAT]};s['phase']='observing';s['deployed_at']=time.time();s['log_offsets']={p:Path(p).stat().st_size if Path(p).exists() else 0 for a in [app(i) for i in s['new'].values()] for p in [a['pm2_env'].get('pm_out_log_path'),a['pm2_env'].get('pm_err_log_path')] if p};save(s);command(['pm2','save']);print(json.dumps({'phase':s['phase'],'new':s['new'],'api_overlap_seconds':s['api_overlap_seconds'],'deployed_at':s['deployed_at']}),flush=True)
 except Exception:
  rollback('deployment_exception');raise

def rollback(reason):
 s=read(STATE)
 for n in ['manager-api','xiaozhi-server']:
  a=next((x for x in apps() if x['pm_id']==s['old'][n]),None)
  if a is None:command(['pm2','start',str(B/(n+'-rollback.json')),'--force'])
  elif a['pm2_env']['status']!='online':command(['pm2','restart',str(a['pm_id'])])
 old.ready(ws=8040,http=8043,internal=8046,manager=18003)
 for name,p in [('www',NGINX),('internal',INTERNAL),('compat',COMPAT)]:atomic(p,(B/(name+'.conf')).read_bytes(),0o644)
 reload()
 for i in s['new'].values():command(['pm2','stop',str(i)])
 for n,h in s['baseline'].items():
  if h is None:
   if (ROOT/n).exists():
    assert sha(ROOT/n)==s['source'][n],'rollback source drift:'+n;(ROOT/n).unlink()
  else:atomic(ROOT/n,(B/'python'/n).read_bytes(),0o644)
 for n in s['java_rel']:atomic(JAVA/n,(B/'java'/n).read_bytes(),0o644)
 atomic(JAVA/'target/xiaozhi-esp32-api.jar',(B/'old-api.jar').read_bytes(),0o644)
 with db() as d:
  with d.cursor() as c:c.execute("UPDATE sys_params SET param_value=%s WHERE param_code='server.voiceprint_similarity_threshold'",(s['old_threshold'],))
 evict_threshold();s.update(phase='rolled_back',reason=reason,rolled_back_at=time.time());save(s);command(['pm2','save']);print(json.dumps({'phase':s['phase'],'reason':reason,'ledger_retained':True}))

def metadata(s):
 p=app(s['new']['xiaozhi-server']);env=env_of(p)
 out={'sources':all(sha(ROOT/n)==h and sha(RUNTIME/n)==h for n,h in s['source'].items()),'jar':sha(REL/'xiaozhi-esp32-api.jar')==s['gate']['jar_sha256'],'java':all(sha(JAVA/n)==h for n,h in s['java_hashes'].items()),'nginx':all(sha(p)==h for p,h in s['config_hashes'].items()),'billing':all(hashlib.sha256(env.get(n,'').encode()).hexdigest()==h for n,h in s['billing_hashes'].items()),'processes':all(app(i)['pm2_env']['status']=='online' and app(i)['pm2_env'].get('restart_time',0)==0 for i in s['new'].values())}
 with db() as d:
  with d.cursor() as c:c.execute("SELECT param_value FROM sys_params WHERE param_code='server.voiceprint_similarity_threshold'");out['threshold']=float(c.fetchone()[0])==.3
 ledger=ROOT/'data/harness/operations.sqlite3'
 with sqlite3.connect('file:'+str(ledger)+'?mode=ro',uri=True) as d:
  out['duplicate_writes']=d.execute('SELECT COUNT(*) FROM (SELECT 1 FROM dispatch GROUP BY scope,turn,fingerprint HAVING COUNT(*)>1)').fetchone()[0]==0
 out['ledger_private']=ledger.stat().st_mode&0o777==0o600
 return out

def inspect_new_logs(s):
 counts={'tracebacks':0,'severe_failures':0,'reply_fallbacks':0,'identity_blocked':0,'harness_receipts':0};critical=[]
 for name,offset in s.get('log_offsets',{}).items():
  p=Path(name)
  if not p.exists():continue
  with p.open('rb') as f:
   if p.stat().st_size<offset:offset=0
   f.seek(offset);chunk=f.read(2*1024*1024);s['log_offsets'][name]=f.tell()
  text=chunk.decode(errors='replace');counts['tracebacks']+=text.count('Traceback (most recent call last)');counts['reply_fallbacks']+=text.count('harness.reply_fallback');counts['identity_blocked']+=text.count('identity_unconfirmed');counts['harness_receipts']+=text.count('harness.receipt')
  for pattern in ['MemoryError','Fatal Python error','Address already in use','OutOfMemoryError','memory_query_unrequested_write_executed','harness.false_success','harness.unauthorized_write','harness.duplicate_dispatch']:
   if pattern in text:critical.append(pattern);counts['severe_failures']+=text.count(pattern)
 return {'counts':counts,'critical':sorted(set(critical))}

def observe():
 s=read(STATE);assert s['phase']=='observing';records=[]
 while True:
  checks=asyncio.run(old.health(**PORTS,public=True));meta=metadata(s);logs=inspect_new_logs(s);ok=not logs['critical'] and all(x['passed'] for x in checks) and all(meta.values());records.append({'at':time.time(),'passed':ok,'checks':checks,'metadata':meta,'logs':logs});atomic(REL/'observation.json',json.dumps({'records':records,'hardware':False},indent=2).encode());print(json.dumps({'snapshot':len(records),'elapsed_seconds':round(time.time()-s['deployed_at']),'passed':ok}),flush=True)
  if not ok:rollback('observation_failure');return
  save(s)
  if time.time()>=s['deployed_at']+1800:break
  time.sleep(min(60,s['deployed_at']+1800-time.time()))
 s.update(phase='deployed_verified',finished_at=time.time(),observation_count=len(records));save(s);command(['pm2','save']);print(json.dumps({'phase':s['phase'],'observed_seconds':round(s['finished_at']-s['deployed_at'])}),flush=True)
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('action',choices=['gate','apply','serve','observe','rollback']);v=a.parse_args().action
 if v=='gate':print(json.dumps(gate()))
 elif v=='apply':apply()
 elif v=='serve':serve()
 elif v=='observe':observe()
 else:rollback('operator_requested')
