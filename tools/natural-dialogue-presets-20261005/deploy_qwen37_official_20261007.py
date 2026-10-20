"""Promote verified Qwen37 candidates. Snapshot only configuration, never rewind billing."""
import ast,hashlib,json,os,shutil,socket,subprocess,time
from pathlib import Path
from urllib.request import Request,urlopen
from datetime import datetime,timezone
OUT=Path('/root/prjs/tmp/natural-dialogue-presets-20261005')
ROOT=Path('/root/prjs/tmp/qwen37-official-release-20261007')
PROD=Path('/root/prjs/xiaozhi-esp32-server')
GATE=Path('/root/prjs/one-api-bailian')
exec((OUT/'inspect_qwen37_release_20261007.py').read_text().split('cfg=json.loads')[0])
prepared=json.loads((ROOT/'prepared.json').read_text());assert prepared['prepared']
assert json.loads((ROOT/'static-container-smoke.json').read_text())['passed']
assert json.loads((ROOT/'python-preflight.json').read_text())['passed']
assert len(prepared['gateway_cloud']['cases'])==6
manifest=prepared['source_files']
def command(args,**kwargs):
 p=subprocess.run(args,capture_output=True,text=True,**kwargs)
 if p.returncode:raise RuntimeError('command_failed_'+args[0])
 return p.stdout.strip()
def quoted(s):return "'"+str(s).replace('\\','\\\\').replace("'","''")+"'"
def routes(kind):return (PROD/'main/xiaozhi-server',ROOT/'xiaozhi-server') if kind=='python' else (PROD/'main/manager-api',ROOT/'manager-api') if kind=='manager' else (GATE,ROOT/'gateway')
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
for key,hashes in manifest.items():
 kind,name=key.split(':',1);dest,src=routes(kind)
 assert digest(dest/name)==hashes['before'] and digest(src/name)==hashes['after'],'candidate_source_drift'
BACK=ROOT/('backup-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S'));BACK.mkdir(mode=0o700)
inspection=json.loads(command(['docker','inspect','one-api']))[0]
(BACK/'container-private.json').write_text(json.dumps(inspection));os.chmod(BACK/'container-private.json',0o600)
cfg=json.loads(sql("SELECT config_json FROM ai_model_config WHERE id='LLM_QwenPlusOfficial';"))
assert cfg['model_name']=='qwen3.8-flash' and cfg['base_url']=='http://127.0.0.1:3000/v1'
display=sql("SELECT model_name FROM ai_model_config WHERE id='LLM_QwenPlusOfficial';")
assert display=='回响现实官方服务', 'official_display_changed'
channels=[json.loads(line) for line in sql("SELECT JSON_OBJECT('id',id,'models',models) FROM one_api.channels WHERE id IN(8,11) ORDER BY id;").splitlines()]
assert len(channels)==2
token=json.loads(sql('SELECT JSON_OBJECT(\'id\',id,\'models\',models) FROM one_api.tokens WHERE id=10;'))
assert sql("SELECT COUNT(*) FROM one_api.abilities WHERE model='qwen3.7-plus' AND channel_id IN(8,11);")=='0'
private={'model':cfg,'channels':channels,'token':token}
(BACK/'database-private.json').write_text(json.dumps(private));os.chmod(BACK/'database-private.json',0o600)
def unchanged_hash():
 rows=sql("SELECT SHA2(CONCAT_WS('|',id,COALESCE(system_prompt,''),COALESCE(summary_memory,''),COALESCE(mem_model_id,''),COALESCE(intent_model_id,'')),256) FROM ai_agent ORDER BY id;")
 return hashlib.sha256(rows.encode()).hexdigest()
personas_before=unchanged_hash()
preserve_names=['core/utils/conversation_turn.py','core/connection.py','core/providers/tools/server_mcp/server_mcp_client.py']
preserved={n:digest(PROD/'main/xiaozhi-server'/n) for n in preserve_names if (PROD/'main/xiaozhi-server'/n).exists()}
for key in manifest:
 kind,name=key.split(':',1);dest,_=routes(kind);saved=BACK/'source'/kind/name
 saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(dest/name,saved)
os.link(PROD/'main/manager-api/target/xiaozhi-esp32-api.jar',BACK/'manager-api.jar')
# Reuse previously verified cache, HTTP, atomic-copy and container preservation helpers.
legacy=ast.parse((OUT/'deploy_release.py').read_text())
for node in legacy.body:
 if isinstance(node,ast.FunctionDef) and node.name in {'clear_model_cache','wait_http','atomic_copy','install_container'}:
  exec(compile(ast.Module(body=[node],type_ignores=[]),'<release-helper>','exec'))
plan={'image':'one-api:qwen37-official-20261007'}
old_name='one-api-before-qwen37-'+BACK.name;renamed=False;source_changed=False;db_changed=False
def shared_probe(newcfg):
 from openai import OpenAI
 with OpenAI(api_key=newcfg['api_key'],base_url=newcfg['base_url'],timeout=45,max_retries=0) as client:
  r=client.chat.completions.create(model='qwen3.7-plus',messages=[{'role':'user','content':'17乘23是多少？只回答结果。'}],max_tokens=40,temperature=.4,extra_body={'enable_thinking':False,'preserve_thinking':False})
  assert '391' in (r.choices[0].message.content or ''),'production_model_probe_failed'
 return True
try:
 newcfg=dict(cfg,model_name='qwen3.7-plus',temperature=.4,max_tokens=600,timeout=45,enable_thinking=False,preserve_thinking=False)
 updates=["UPDATE ai_model_config SET config_json="+quoted(json.dumps(newcfg,ensure_ascii=False))+" WHERE id='LLM_QwenPlusOfficial'"]
 for c in channels:
  models=','.join(dict.fromkeys(c['models'].split(',')+['qwen3.7-plus']))
  updates.append('UPDATE one_api.channels SET models='+quoted(models)+' WHERE id='+str(c['id']))
 for cid,group in [(8,'hardware70'),(11,'default')]:
  updates.append("INSERT INTO one_api.abilities(`group`,model,channel_id,enabled,priority) SELECT "+quoted(group)+",'qwen3.7-plus',"+str(cid)+",1,COALESCE(priority,0) FROM one_api.channels WHERE id="+str(cid))
 if token['models']:
  updates.append('UPDATE one_api.tokens SET models='+quoted(','.join(dict.fromkeys(token['models'].split(',')+['qwen3.7-plus'])))+' WHERE id=10')
 sql('START TRANSACTION;'+';'.join(updates)+';COMMIT;');db_changed=True
 clear_model_cache()
 # Previous rollback containers had restart=always and stole port 3000 at reboot.
 # Keep their data and images, but prevent stopped backups from restarting.
 old_backups=['one-api-before-natural-dialogue-20261005','one-api-before-hardware70-20261001','one-api-before-bailian-20260915']
 (BACK/'disabled-backup-containers.json').write_text(json.dumps(old_backups))
 for name in old_backups:
  command(['docker','update','--restart=no',name]);command(['docker','stop',name],timeout=30)
 command(['docker','stop','one-api'],timeout=30)
 command(['docker','rename','one-api',old_name]);renamed=True
 command(['docker','update','--restart=no',old_name])
 install_container();wait_http('http://127.0.0.1:3000/api/status');print('gateway_ready',flush=True)
 source_changed=True
 for key in manifest:
  kind,name=key.split(':',1);dest,src=routes(kind);atomic_copy(src/name,dest/name)
 for name in ['hardwarebilling/qwen37_price_test.go','relay/controller/qwen37_cloud_test.go']:
  atomic_copy(ROOT/'gateway'/name,GATE/name)
 atomic_copy(ROOT/'manager-api/target/xiaozhi-esp32-api.jar',PROD/'main/manager-api/target/xiaozhi-esp32-api.jar')
 command(['pm2','restart','manager-api'],timeout=30);wait_http('http://127.0.0.1:8002/xiaozhi/user/pub-config');print('manager_ready',flush=True)
 command(['pm2','restart','xiaozhi-server'],timeout=30)
 for _ in range(40):
  try:
   with socket.create_connection(('127.0.0.1',8000),timeout=2):break
  except OSError:time.sleep(1)
 else:raise RuntimeError('websocket_listener_missing')
 wait_http('http://127.0.0.1:8003/mcp/vision/explain')
 public={}
 for url in ['https://www.realecho.cn/','https://realecho.cn/','https://api.realecho.cn/mcp/vision/explain']:
  with urlopen(url,timeout=15) as response:assert response.status==200;public[url]=200
 assert unchanged_hash()==personas_before,'agent_persona_or_memory_changed'
 assert all(digest(PROD/'main/xiaozhi-server'/n)==h for n,h in preserved.items()),'tool_or_retrieval_changed'
 shared_probe(newcfg)
 # Run the actual owned-device provider and require a settled production bill.
 scope={'__name__':'__qwen37_acceptance__'}
 original=(OUT/'device_config_acceptance.py').read_text()
 original=original.replace("=='qwen3.8-flash'","=='qwen3.7-plus'")
 original=original.replace("inspection=json.loads((Path(json.loads((OUT/'deployment-receipt.json').read_text())['backup'])/'container-private.json').read_text())","inspection=json.loads(Path("+repr(str(BACK/'container-private.json'))+").read_text())")
 original=original.replace("'device-config-acceptance.json'","'qwen37-device-config-acceptance.json'")
 exec(compile(original,'<production-device-config-and-meter>','exec'),scope)
 bill=scope['bill'];usage=scope['report']['usage']
 price=json.loads(bill['price']) if isinstance(bill['price'],str) else bill['price']
 assert 'qwen3.7-plus' in json.dumps(price) and '20261007-qwen37' in json.dumps(price),'wrong_production_price'
 statuses={p['name']:p['pm2_env']['status'] for p in json.loads(command(['pm2','jlist'])) if p['name'] in {'manager-api','xiaozhi-server','mcp-gateway'}}
 assert len(statuses)==3 and all(s=='online' for s in statuses.values())
 receipt={'deployed':True,'at_utc':datetime.now(timezone.utc).isoformat(),'display_name':display,'model':'qwen3.7-plus','temperature':.4,'max_tokens':600,'thinking':False,'gateway_base_url':newcfg['base_url'],'public_http':public,'processes':statuses,'personas_memory_unchanged':True,'tool_retrieval_sources_unchanged':True,'production_owned_bill_settled':True,'usage':usage,'price':price,'backup':str(BACK),'image':plan['image'],'source_files':manifest,'physical_hardware_test':False}
 (OUT/'qwen37-official-deployment-20261007.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2))
 print(json.dumps({k:receipt[k] for k in ['deployed','display_name','model','gateway_base_url','production_owned_bill_settled','public_http']}),flush=True)
except Exception as error:
 try:
  if db_changed:
   rollback=["UPDATE ai_model_config SET config_json="+quoted(json.dumps(cfg,ensure_ascii=False))+" WHERE id='LLM_QwenPlusOfficial'","DELETE FROM one_api.abilities WHERE model='qwen3.7-plus' AND channel_id IN(8,11)",'UPDATE one_api.tokens SET models='+('NULL' if token['models'] is None else quoted(token['models']))+' WHERE id=10']
   rollback+=['UPDATE one_api.channels SET models='+quoted(c['models'])+' WHERE id='+str(c['id']) for c in channels]
   sql('START TRANSACTION;'+';'.join(rollback)+';COMMIT;');clear_model_cache()
  if renamed:
   if command(['docker','ps','-aq','--filter','name=^/one-api$']):command(['docker','rm','-f','one-api'],timeout=30)
   plan['image']=inspection['Config']['Image'];install_container();wait_http('http://127.0.0.1:3000/api/status')
  if source_changed:
   for key in manifest:
    kind,name=key.split(':',1);dest,_=routes(kind);atomic_copy(BACK/'source'/kind/name,dest/name)
   atomic_copy(BACK/'manager-api.jar',PROD/'main/manager-api/target/xiaozhi-esp32-api.jar')
   command(['pm2','restart','manager-api']);command(['pm2','restart','xiaozhi-server'])
  rolled_back=True
 except Exception:rolled_back=False
 (OUT/'qwen37-official-deployment-failure-20261007.json').write_text(json.dumps({'rolled_back':rolled_back,'error_type':type(error).__name__,'reason':str(error)[:160],'backup':str(BACK)}))
 raise RuntimeError('deployment_failed_'+('rolled_back' if rolled_back else 'rollback_requires_inspection')) from None
