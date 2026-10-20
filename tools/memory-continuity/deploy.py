"""Publish only the independently tested additive increment; no firmware/portrait/config changes."""
from pathlib import Path
import json,hashlib,os,shutil,subprocess,tarfile,time,urllib.request,fcntl
os.umask(0o077)
prod=Path('/root/prjs/xiaozhi-esp32-server');cand=Path('/root/prjs/tmp/bailian-memory-product');release=Path('/root/prjs/tmp/memory-continuity-release-20260930')
lock=(release/'publish.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
manifest=json.loads((release/'manifest.json').read_text())
assert json.loads((release/'tests.json').read_text())['passed']
real=json.loads((release/'real-tests.json').read_text());assert all(real.get(k) for k in ('models_passed','cloud_passed','test_facts_cleaned'))
assert float(real['charged_cny'])<20
assert json.loads(Path('/tmp/bailian-memory-boot-smoke-result.json').read_text())['liquibase_new_changeset']=='202609301900-memory-continuity'
assert not (release/'published.json').exists()
assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=prod,text=True).strip()=='496899c4654656707c1e0e9e8dc57b1c42f14bd9'
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
base={}
for name,value in manifest.items():
 assert digest(cand/name)==value,'candidate_changed:'+name
 old=subprocess.run(['git','show','HEAD:'+name],cwd=prod,capture_output=True)
 base[name]=hashlib.sha256(old.stdout).hexdigest() if old.returncode==0 else None
 assert digest(prod/name)==base[name],'production_changed:'+name
(release/'baseline.json').write_text(json.dumps(base,indent=2))
with tarfile.open(release/'source-before.tar.gz','w:gz') as bundle:
 for name in manifest:
  if (prod/name).exists():bundle.add(prod/name,arcname=name)
jar=prod/'main/manager-api/target/xiaozhi-esp32-api.jar';shutil.copy2(jar,release/'manager-api-before.jar')
cfg_hash=digest(prod/'main/xiaozhi-server/config.yaml')
def install(a,b):
 b.parent.mkdir(parents=True,exist_ok=True);tmp=b.with_name(b.name+'.continuity-next');shutil.copy2(a,tmp);os.replace(tmp,b)
def run(args,label):
 with (release/(label+'.log')).open('w') as output:r=subprocess.run(args,stdout=output,stderr=subprocess.STDOUT)
 if r.returncode:raise RuntimeError(label)
def wait(url,check):
 deadline=time.monotonic()+90
 while time.monotonic()<deadline:
  try:
   with urllib.request.urlopen(url,timeout=3) as response:
    if response.status==200 and check(json.loads(response.read())):return
  except Exception:pass
  time.sleep(.5)
 raise RuntimeError('health_timeout')
mysql=['docker','exec','-i','xiaozhi-esp32-server-db','sh','-c','exec env MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --user=root --batch --raw --skip-column-names']
def sql(q):return subprocess.run(mysql,input=q,text=True,capture_output=True,check=True).stdout.strip()
def aggregates():return json.loads(sql("SELECT JSON_OBJECT('audio_rows',(SELECT COUNT(*) FROM xiaozhi_esp32_server.ai_agent_chat_audio),'audio_bytes',(SELECT COALESCE(SUM(OCTET_LENGTH(audio)),0) FROM xiaozhi_esp32_server.ai_agent_chat_audio),'archive_rows',(SELECT COUNT(*) FROM xiaozhi_esp32_server.ai_agent_chat_history),'pending_material',(SELECT COUNT(*) FROM xiaozhi_esp32_server.ai_person_material));"))
# Count columns without reading any stored user content; audio bytes are recorded by postcheck.
before={'audio_rows':int(sql('SELECT COUNT(*) FROM xiaozhi_esp32_server.ai_agent_chat_audio;')),'archive_rows':int(sql('SELECT COUNT(*) FROM xiaozhi_esp32_server.ai_agent_chat_history;')),'pending_material':int(sql('SELECT COUNT(*) FROM xiaozhi_esp32_server.ai_person_material;'))}
(release/'before-aggregates.json').write_text(json.dumps(before))
try:
 run(['pm2','stop','xiaozhi-server','manager-api'],'stop')
 for name in manifest:install(cand/name,prod/name)
 install(cand/'main/manager-api/target/xiaozhi-esp32-api.jar',jar)
 run(['pm2','restart','manager-api'],'java-start')
 wait('http://127.0.0.1:8002/xiaozhi/user/pub-config',lambda x:x.get('code')==0)
 assert sql("SELECT COUNT(*) FROM xiaozhi_esp32_server.DATABASECHANGELOG WHERE ID='202609301900-memory-continuity';")=='1'
 run(['pm2','restart','xiaozhi-server'],'voice-start')
 wait('http://127.0.0.1:8006/openapi.json',lambda x:'/api/v1/device/send' in x.get('paths',{}))
 wait('https://api.realecho.cn/xiaozhi/user/pub-config',lambda x:x.get('code')==0)
 for url in ('https://www.realecho.cn','https://realecho.cn'):
  with urllib.request.urlopen(url,timeout=10) as response:assert response.status==200
 assert digest(prod/'main/xiaozhi-server/config.yaml')==cfg_hash
 run(['pm2','save'],'pm2-save')
 result={'published':True,'at':time.strftime('%Y-%m-%d %H:%M:%S %z'),'jar_sha256':digest(jar),'source_files':len(manifest),'min_user_tokens':10000,'audio_max_hours':72,'archive_max_turns':50,'portraits_enabled':False,'firmware_ota':False,'frontend_changed':False,'gateway_changed':False,'automation_recreated':False,'domains':['api.realecho.cn','www.realecho.cn','realecho.cn']}
 (release/'published.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)
except Exception:
 with tarfile.open(release/'source-before.tar.gz') as bundle:
  for entry in bundle.getmembers():
   assert entry.isfile() and not entry.name.startswith('/') and '..' not in Path(entry.name).parts
   target=prod/entry.name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(bundle.extractfile(entry).read())
 for name,value in base.items():
  if value is None and (prod/name).exists():(prod/name).unlink()
 install(release/'manager-api-before.jar',jar)
 subprocess.run(['pm2','restart','manager-api','xiaozhi-server'],capture_output=True)
 (release/'publish-failed.json').write_text(json.dumps({'executables_rolled_back':True,'deletion_and_ledger_retained':True}))
 raise
