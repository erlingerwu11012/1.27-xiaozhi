"""Promote verified artifacts, preserve personas, and roll back on failed health checks."""
import hashlib,json,os,re,shutil,socket,subprocess,time
from pathlib import Path
from urllib.request import urlopen
from datetime import datetime,timezone
import yaml
OUT=Path('/root/prjs/tmp/natural-dialogue-presets-20261005')
PROD=Path('/root/prjs/xiaozhi-esp32-server'); CAND=OUT/'worktree'
plan=json.loads((OUT/'release-plan.json').read_text()); BACK=Path(plan['backup'])
inspection=json.loads((BACK/'container-private.json').read_text())
private=json.loads((BACK/'database-private.json').read_text())
def command(args,**kw):
 p=subprocess.run(args,capture_output=True,text=True,**kw)
 if p.returncode:raise RuntimeError('command_failed_'+args[0])
 return p.stdout.strip()
def hashfile(p):return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
assert command(['git','-C',str(PROD),'rev-parse','HEAD'])==plan['baseline']
assert not command(['git','-C',str(PROD),'status','--porcelain','--untracked-files=no'])
for name,hashes in plan['files'].items():
 assert hashfile(PROD/name)==hashes['before'] and hashfile(CAND/name)==hashes['after'],name
assert json.loads((OUT/'regression.json').read_text())=={'run':210,'failures':0,'errors':0,'success':True,'network_calls':0}
assert json.loads((OUT/'tool-pipeline-acceptance.json').read_text())['success']
assert len(json.loads((OUT/'gateway-cloud-acceptance.json').read_text())['cases'])==6
spring=yaml.safe_load((PROD/'main/manager-api/src/main/resources/application-dev.yml').read_text())['spring']
db=spring['datasource']['druid']; m=re.search(r'mysql://([^:/]+)(?::(\d+))?/([^?]+)',db['url'])
env=dict(os.environ,MYSQL_PWD=str(db['password']))
def sql(q):return command(['mysql','--host='+m[1],'--port='+(m[2]or'3306'),'--user='+str(db['username']),'--batch','--raw','--skip-column-names',m[3]],input=q,env=env,timeout=20)
def quoted(s):return "'"+str(s).replace('\\','\\\\').replace("'","''")+"'"
def persona_hash():
 rows=sql("SELECT SHA2(CONCAT(id,':',COALESCE(system_prompt,'')),256) FROM ai_agent ORDER BY id;")
 return hashlib.sha256(rows.encode()).hexdigest()
persona_before=persona_hash()
key=private['model']['api_key'].removeprefix('sk-');assert re.fullmatch('[a-zA-Z0-9_-]+',key)
token=json.loads(sql("SELECT JSON_OBJECT('id',id,'models',models) FROM one_api.tokens WHERE `key`="+quoted(key)+" LIMIT 1;"))
(BACK/'token-private.json').write_text(json.dumps(token));os.chmod(BACK/'token-private.json',0o600)
assert sql("SELECT COUNT(*) FROM one_api.channels WHERE name='official-qwen38-compatible';")=='0'
def clear_model_cache():
 cfg=(spring.get('data')or{}).get('redis') or spring.get('redis') or {}
 with socket.create_connection((cfg.get('host','localhost'),int(cfg.get('port',6379))),timeout=5) as sock:
  stream=sock.makefile('rb')
  def redis_command(*parts):
   raw=[str(part).encode() for part in parts]
   sock.sendall(b'*'+str(len(raw)).encode()+b'\r\n'+b''.join(b'$'+str(len(part)).encode()+b'\r\n'+part+b'\r\n' for part in raw))
   reply=stream.readline()
   if not reply or reply.startswith(b'-'):raise RuntimeError('model_cache_refresh_failed')
   return reply
  if cfg.get('password'):redis_command('AUTH',cfg['password'])
  redis_command('SELECT',int(cfg.get('database',0)))
  redis_command('DEL','model:name:LLM_QwenPlusOfficial','model:data:LLM_QwenPlusOfficial')
def wait_http(url):
 for _ in range(40):
  try:
   with urlopen(url,timeout=3) as response:
    if response.status==200:return
  except Exception:pass
  time.sleep(1)
 raise RuntimeError('health_timeout')
def atomic_copy(src,dest):
 dest.parent.mkdir(parents=True,exist_ok=True);tmp=dest.with_name(dest.name+'.natural-new')
 shutil.copy2(src,tmp);os.replace(tmp,dest)
old_name='one-api-before-natural-dialogue-20261005'
new_channel=None;renamed=False;source_changed=False
def install_container():
 envfile=BACK/'docker-private.env'
 assert all('\n' not in entry for entry in inspection['Config']['Env'])
 envfile.write_text('\n'.join(inspection['Config']['Env'])+'\n');os.chmod(envfile,0o600)
 args=['docker','run','-d','--name','one-api','--env-file',str(envfile),'--restart',inspection['HostConfig']['RestartPolicy']['Name'] or 'no']
 network=inspection['HostConfig'].get('NetworkMode')
 if network:args+=['--network',network]
 for port,bindings in inspection['HostConfig']['PortBindings'].items():
  for binding in bindings:args+=['-p',(binding['HostIp'] or '0.0.0.0')+':'+binding['HostPort']+':'+port]
 for mount in inspection['Mounts']:
  assert mount['Type']=='bind' and mount['Destination']=='/data'
  args+=['--mount','type=bind,source='+mount['Source']+',target='+mount['Destination']+('' if mount['RW'] else ',readonly')]
 if inspection['Config'].get('User'):args+=['--user',inspection['Config']['User']]
 if inspection['Config'].get('WorkingDir'):args+=['--workdir',inspection['Config']['WorkingDir']]
 args+=[plan['image']]+inspection['Config']['Cmd']
 command(args,timeout=30)
try:
 cfg=dict(private['model'],model_name=plan['model'],temperature=0.4,enable_thinking=False,preserve_thinking=False)
 models=list(dict.fromkeys(private['channel']['models'].split(',')+['qwen3.8-flash','qwen3.8-max']))
 sql('START TRANSACTION; UPDATE ai_model_config SET config_json='+quoted(json.dumps(cfg,ensure_ascii=False))+" WHERE id='LLM_QwenPlusOfficial'; UPDATE one_api.channels SET models="+quoted(','.join(models))+" WHERE id=8; INSERT INTO one_api.channels(type,status,name,`key`,models,`group`,base_url,priority,weight,created_time) SELECT type,status,'official-qwen38-compatible',`key`,'qwen3.8-flash,qwen3.8-max','default',base_url,priority,weight,UNIX_TIMESTAMP() FROM one_api.channels WHERE id=8; COMMIT;")
 new_channel=int(sql("SELECT id FROM one_api.channels WHERE name='official-qwen38-compatible';"))
 for channel,group in [(8,'hardware70'),(new_channel,'default')]:
  for model in ['qwen3.8-flash','qwen3.8-max']:
   sql("INSERT INTO one_api.abilities(`group`,model,channel_id,enabled,priority) SELECT "+quoted(group)+','+quoted(model)+f",{channel},1,COALESCE(priority,0) FROM one_api.channels WHERE id={channel} ON DUPLICATE KEY UPDATE enabled=VALUES(enabled),priority=VALUES(priority);")
 if token['models']:
  allowed=','.join(dict.fromkeys(token['models'].split(',')+['qwen3.8-flash','qwen3.8-max']))
  sql('UPDATE one_api.tokens SET models='+quoted(allowed)+' WHERE id='+str(int(token['id']))+';')
 clear_model_cache()
 command(['docker','stop','one-api'],timeout=30)
 command(['docker','rename','one-api',old_name]);renamed=True
 install_container();wait_http('http://127.0.0.1:3000/api/status')
 print('gateway_ready',flush=True)
 for name in plan['files']:atomic_copy(CAND/name,PROD/name)
 source_changed=True
 for name in plan['gateway_files']:atomic_copy(OUT/'gateway-candidate'/name,Path('/root/prjs/one-api-bailian')/name)
 atomic_copy(CAND/'main/manager-api/target/xiaozhi-esp32-api.jar',PROD/'main/manager-api/target/xiaozhi-esp32-api.jar')
 command(['pm2','restart','manager-api'],timeout=30);wait_http('http://127.0.0.1:8002/xiaozhi/user/pub-config')
 print('manager_ready',flush=True)
 command(['pm2','restart','xiaozhi-server'],timeout=30)
 for _ in range(30):
  try:
   with socket.create_connection(('127.0.0.1',8000),timeout=2):break
  except OSError:time.sleep(1)
 else:raise RuntimeError('websocket_listener_missing')
 wait_http('http://127.0.0.1:8003/mcp/vision/explain')
 for dest in [Path('/var/www/realecho-www'),PROD/'main/manager-web/dist']:
  for p in (CAND/'main/manager-web/dist').rglob('*'):
   if p.is_file() and p.name!='index.html':atomic_copy(p,dest/p.relative_to(CAND/'main/manager-web/dist'))
  atomic_copy(CAND/'main/manager-web/dist/index.html',dest/'index.html')
 public={}
 for url in ['https://www.realecho.cn/','https://realecho.cn/','https://api.realecho.cn/mcp/vision/explain']:
  with urlopen(url,timeout=15) as response:
   assert response.status==200;public[url]=response.status
 time.sleep(5)
 processes=json.loads(command(['pm2','jlist']))
 statuses={p['name']:p['pm2_env']['status'] for p in processes if p['name'] in ['manager-api','xiaozhi-server','mcp-gateway']}
 assert all(v=='online' for v in statuses.values())
 assert persona_hash()==persona_before,'persona_changed'
 # Real production default token must reach the new compatible route.
 from openai import OpenAI
 client=OpenAI(api_key=cfg['api_key'],base_url=cfg.get('base_url')or'http://127.0.0.1:3000/v1',timeout=30,max_retries=0)
 result=client.chat.completions.create(model=cfg['model_name'],messages=[{'role':'user','content':'17乘23是多少？只回答结果。'}],max_tokens=40,temperature=0.4,extra_body={'enable_thinking':False,'preserve_thinking':False})
 assert '391' in (result.choices[0].message.content or ''),'production_model_probe_failed'
 client.close()
 receipt={'deployed':True,'at_utc':datetime.now(timezone.utc).isoformat(),'model':cfg['model_name'],'temperature':0.4,'backup':str(BACK),'image':plan['image'],'compatible_channel_id':new_channel,'public_http':public,'processes':statuses,'personas_unchanged':True,'secondary_rewrite_model':False,'ui_presets':6,'production_model_probe':True,'source_files':plan['files'],'hardware_test_this_release':False}
 (OUT/'deployment-receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2))
 print(json.dumps({k:receipt[k] for k in ['deployed','model','temperature','public_http','personas_unchanged','production_model_probe']}),flush=True)
except Exception as error:
 # Ledger/recharge tables are never rolled back; only owned model configuration is restored.
 try:
  sql('UPDATE ai_model_config SET config_json='+quoted(json.dumps(private['model'],ensure_ascii=False))+" WHERE id='LLM_QwenPlusOfficial'; UPDATE one_api.channels SET models="+quoted(private['channel']['models'])+" WHERE id=8; DELETE FROM one_api.abilities WHERE channel_id=8 AND model IN('qwen3.8-flash','qwen3.8-max'); UPDATE one_api.tokens SET models="+('NULL' if token['models'] is None else quoted(token['models']))+' WHERE id='+str(int(token['id']))+';')
  if new_channel:sql(f'DELETE FROM one_api.abilities WHERE channel_id={new_channel}; DELETE FROM one_api.channels WHERE id={new_channel} AND name='+quoted('official-qwen38-compatible')+';')
  clear_model_cache()
  if renamed:
   current=command(['docker','ps','-aq','--filter','name=^/one-api$'])
   if current:command(['docker','rm','-f','one-api'],timeout=30)
   command(['docker','rename',old_name,'one-api']);command(['docker','start','one-api'])
  if source_changed:
   for name in plan['files']:
    saved=BACK/'source'/name
    if saved.exists():atomic_copy(saved,PROD/name)
    elif (PROD/name).exists():(PROD/name).unlink()
   atomic_copy(BACK/'manager-api.jar',PROD/'main/manager-api/target/xiaozhi-esp32-api.jar')
   atomic_copy(BACK/'frontend/index.html',Path('/var/www/realecho-www/index.html'))
   command(['pm2','restart','manager-api']);command(['pm2','restart','xiaozhi-server'])
 except Exception:
  (OUT/'deployment-failure.json').write_text(json.dumps({'rollback_requires_inspection':True,'error_type':type(error).__name__,'backup':str(BACK)}))
  raise RuntimeError('deployment_and_rollback_require_inspection') from None
 (OUT/'deployment-failure.json').write_text(json.dumps({'rolled_back':True,'error_type':type(error).__name__,'backup':str(BACK)}))
 raise RuntimeError('deployment_failed_rolled_back') from None
