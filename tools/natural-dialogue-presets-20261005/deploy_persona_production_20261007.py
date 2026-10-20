"""Promote exact tested persona source and frontend; rollback on health failure."""
import hashlib,json,os,re,shutil,socket,stat,subprocess,time
from pathlib import Path
from urllib.request import urlopen
from datetime import datetime,timezone
OUT=Path('/root/prjs/tmp/natural-dialogue-presets-20261005')
STAGE=Path('/root/prjs/tmp/persona-production-release-20261007')
PROD=Path('/root/prjs/xiaozhi-esp32-server')
PUBLIC=Path('/var/www/realecho-www')
plan=json.loads((STAGE/'plan.json').read_text());assert plan['prepared'] and plan['ui_passed']==14 and plan['backend_checks']
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def command(args,**kwargs):
 p=subprocess.run(args,capture_output=True,text=True,**kwargs)
 if p.returncode:raise RuntimeError('command_failed_'+args[0])
 return p.stdout.strip()
assert command(['git','-C',str(PROD),'rev-parse','HEAD'])==plan['baseline']
for n,v in plan['files'].items():assert digest(PROD/n)==v['before'] and digest(STAGE/n)==v['after'],'source_changed_during_build'
for n,v in plan['protected'].items():assert digest(PROD/n)==v,'protected_source_changed_during_build'
exec((OUT/'inspect_qwen37_release_20261007.py').read_text().split('cfg=json.loads')[0])
def db_hashes():
 return {'model':hashlib.sha256(sql("SELECT CONCAT(model_name,'|',config_json) FROM ai_model_config WHERE id='LLM_QwenPlusOfficial';").encode()).hexdigest(),'personas':hashlib.sha256(sql("SELECT SHA2(CONCAT_WS('|',id,COALESCE(system_prompt,'')),256) FROM ai_agent ORDER BY id;").encode()).hexdigest()}
assert db_hashes()=={'model':plan['model_config_sha256'],'personas':plan['user_personas_sha256']},'configuration_changed_during_build'
cfg=json.loads(sql("SELECT config_json FROM ai_model_config WHERE id='LLM_QwenPlusOfficial';"))
display=sql("SELECT model_name FROM ai_model_config WHERE id='LLM_QwenPlusOfficial';")
assert cfg['model_name']=='qwen3.7-plus' and cfg['temperature']==.4 and cfg['enable_thinking'] is False and cfg['preserve_thinking'] is False
assert cfg['base_url']=='http://127.0.0.1:3000/v1' and display=='回响现实官方服务'
BACK=STAGE/('backup-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S'));BACK.mkdir(mode=0o700)
for n in plan['files']:
 saved=BACK/'source'/n;saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(PROD/n,saved)
shutil.copytree(PUBLIC,BACK/'public')
dist=PROD/'main/manager-web/dist'
if dist.is_dir():shutil.copytree(dist,BACK/'dist')
def atomic_copy(src,dest,mode=None):
 parents=[];p=dest.parent
 while not p.exists():parents.append(p);p=p.parent
 for parent in reversed(parents):parent.mkdir(mode=0o755)
 tmp=dest.with_name(dest.name+'.persona-release-new');shutil.copy2(src,tmp)
 if mode is not None:os.chmod(tmp,mode)
 os.replace(tmp,dest)
def wait_http(url):
 for _ in range(35):
  try:
   with urlopen(url,timeout=3) as r:
    if r.status==200:return
  except Exception:pass
  time.sleep(1)
 raise RuntimeError('health_timeout')
def publish_tree(src,dest):
 assert dest in [PUBLIC,dist]
 files=[p for p in src.rglob('*') if p.is_file()]
 for p in files:
  if p.name=='index.html':continue
  target=dest/p.relative_to(src)
  assert target.resolve().is_relative_to(dest.resolve())
  atomic_copy(p,target,0o644)
 atomic_copy(src/'index.html',dest/'index.html',0o644)
changed=False
try:
 changed=True
 for n in plan['files']:atomic_copy(STAGE/n,PROD/n,stat.S_IMODE((BACK/'source'/n).stat().st_mode))
 # New hashed bundles first, entry pages last. Retain older bundles for existing tabs.
 for dest in [PUBLIC,dist]:publish_tree(STAGE/'main/manager-web/dist',dest)
 command(['pm2','restart','xiaozhi-server'],timeout=30)
 for _ in range(40):
  try:
   with socket.create_connection(('127.0.0.1',8000),timeout=1):break
  except OSError:time.sleep(1)
 else:raise RuntimeError('websocket_not_listening')
 wait_http('http://127.0.0.1:8003/mcp/vision/explain')
 wait_http('http://127.0.0.1:8002/xiaozhi/user/pub-config')
 new_index=(PUBLIC/'index.html').read_bytes()
 public={}
 for url in ['https://www.realecho.cn/','https://realecho.cn/']:
  with urlopen(url+'?persona_release=20261007',timeout=15) as r:
   assert r.status==200 and r.read()==new_index,'public_frontend_not_updated';public[url]=200
 with urlopen('https://api.realecho.cn/mcp/vision/explain',timeout=15) as r:assert r.status==200;public['https://api.realecho.cn/mcp/vision/explain']=200
 public_bundles=re.findall(r'(?:src|href)="(/(?:js|css)/[^" ]+)"',new_index.decode())
 assert public_bundles
 for relative in public_bundles:
  with urlopen('https://www.realecho.cn'+relative,timeout=15) as r:assert r.status==200 and r.read()==(PUBLIC/relative.lstrip('/')).read_bytes(),'published_asset_mismatch'
 for n,v in plan['protected'].items():assert digest(PROD/n)==v
 assert db_hashes()=={'model':plan['model_config_sha256'],'personas':plan['user_personas_sha256']},'user_or_model_config_changed'
 print('public_frontend_and_backend_ready',flush=True)
 # Real requests use the installed production module, not an in-memory candidate.
 with (STAGE/'production-probe.log').open('w') as log:
  p=subprocess.run(['/root/miniconda3/envs/xiaozhi-esp32-server/bin/python',str(OUT/'persona_production_probe_20261007.py')],stdout=log,stderr=subprocess.STDOUT,timeout=180)
  assert p.returncode==0,'production_probe_failed'
 probe=json.loads((OUT/'persona-production-probe-results-20261007.json').read_text())
 rows=[r for s in probe['sessions'] for r in s['turns']]
 assert probe['finished'] and probe['customer_configuration_unchanged'] and len(rows)==21
 assert all(r['runtime_ok'] and r['assistant'] and not r['error'] and all(m['persona_in_actual_request'] and m['reasoning_chars']==0 for m in r['model_requests']) for r in rows)
 for s in probe['sessions']:
  if s['scenario']=='tools':
   one,two=s['turns']
   assert len(one['tool_events'])==1 and one['tool_events'][0]['arguments']['timezone']=='Europe/London' and not one['tool_events'][0].get('blocked_by_test_harness')
   assert not two['tool_events'] and all(not m['tool_calls'] for m in two['model_requests'])
 previous=json.loads((OUT/'persona-refined-runtime-results-20261007.json').read_text())
 assert probe['tool_catalog_sha256']==previous['tool_catalog_sha256']
 processes=json.loads(command(['pm2','jlist']))
 statuses={p['name']:p['pm2_env']['status'] for p in processes if p['name'] in ['manager-api','xiaozhi-server','mcp-gateway','manager-web']}
 assert len(statuses)==4 and all(v=='online' for v in statuses.values())
 receipt={'deployed':True,'at_utc':datetime.now(timezone.utc).isoformat(),'public_http':public,'processes':statuses,'source_files':plan['files'],'backup':str(BACK),'model':'qwen3.7-plus','thinking':False,'temperature':.4,'official_display':display,'gateway':'http://127.0.0.1:3000/v1','model_config_unchanged':True,'user_personas_unchanged':True,'presets':6,'production_probe_turns':21,'native_mcp_time_queries':7,'no_query_controls':7,'tool_catalog_unchanged':True,'physical_voice_test':False,'known_limitations':['人格边界仍存在偶发偏离','上一轮测试出现中途事实偏差，不能承诺全部回复正确'],'billing_policy_unchanged':True}
 (OUT/'persona-production-deployment-20261007.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2))
 print(json.dumps(receipt,ensure_ascii=False),flush=True)
except Exception as exc:
 if changed:
  for n in plan['files']:atomic_copy(BACK/'source'/n,PROD/n,stat.S_IMODE((BACK/'source'/n).stat().st_mode))
  publish_tree(BACK/'public',PUBLIC)
  if (BACK/'dist').is_dir():publish_tree(BACK/'dist',dist)
  command(['pm2','restart','xiaozhi-server'],timeout=30)
  wait_http('http://127.0.0.1:8003/mcp/vision/explain')
 (OUT/'persona-production-deployment-failure-20261007.json').write_text(json.dumps({'rolled_back':changed,'error_type':type(exc).__name__,'backup':str(BACK)}))
 raise
