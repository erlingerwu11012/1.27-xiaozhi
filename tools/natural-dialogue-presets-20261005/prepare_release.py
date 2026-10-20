"""Prepare final tests/image and a private rollback snapshot; no production mutation."""
import hashlib,json,os,re,shutil,subprocess,zipfile
from pathlib import Path
from datetime import datetime,timezone
import yaml
OUT=Path('/root/prjs/tmp/natural-dialogue-presets-20261005')
PROD=Path('/root/prjs/xiaozhi-esp32-server')
CAND=OUT/'worktree'
BASE='5419da5b9c8db490bf42efac9e21449d2d533f9b'
def run(args,**kwargs):
 p=subprocess.run(args,capture_output=True,**kwargs)
 if p.returncode:raise RuntimeError('command_failed_'+args[0])
 return p.stdout
assert run(['git','-C',str(PROD),'rev-parse','HEAD']).decode().strip()==BASE
assert not run(['git','-C',str(PROD),'status','--porcelain','--untracked-files=no']).strip()
assert shutil.disk_usage('/root').free>600_000_000
test=CAND/'main/manager-api/src/test/java/xiaozhi/modules/pay/service/HardwareBillingPolicyTest.java'
text=test.read_text()
anchor='   else assertEquals("http://127.0.0.1:3000/v1",copy.get("base_url"));'
assert anchor in text
if 'LLM_TEMPERATURE' not in text:
 text=text.replace(anchor,anchor+'\n   if("LLM".equals(category)){assertEquals(xiaozhi.modules.model.OfficialServiceDefaults.LLM_MODEL_NAME,copy.get("model_name"));assertEquals(xiaozhi.modules.model.OfficialServiceDefaults.LLM_TEMPERATURE,copy.get("temperature"));assertEquals(false,copy.get("preserve_thinking"));}')
 test.write_text(text)
runner=OUT/'run_regression.py'
text=runner.read_text().replace("names=['test_conversation_contract'", "names=['test_natural_tool_failure_regression','test_conversation_contract'")
runner.write_text(text)
jar=CAND/'main/manager-api/target/xiaozhi-esp32-api.jar'
with zipfile.ZipFile(jar) as archive:
 for p in (PROD/'main/manager-api/src/main/resources').rglob('*'):
  if p.is_file() and not any(s.startswith('.') for s in p.relative_to(PROD/'main/manager-api/src/main/resources').parts):
   entry='BOOT-INF/classes/'+p.relative_to(PROD/'main/manager-api/src/main/resources').as_posix()
   assert archive.read(entry)==p.read_bytes(),'runtime_resource_changed_'+p.name
index=(CAND/'main/manager-web/dist/index.html').read_text()
bundle=re.search(r'src="(/js/app[^" ]+\.js)"',index).group(1)
assert 'https://api.realecho.cn/xiaozhi' in (CAND/'main/manager-web/dist'/bundle.lstrip('/')).read_text()
assert json.loads((OUT/'ui-component-tests.json').read_text())['passed']==14
release=json.loads((OUT/'release-acceptance.json').read_text())
assert release['calls']==85 and all(not t.get('error') for s in release['heldout_scenarios'] for t in s['turns'])
assert json.loads((OUT/'final-acceptance.json').read_text())['native_tool_calls_executed']==3
assert len(json.loads((OUT/'gateway-cloud-acceptance.json').read_text())['cases'])==4
image=OUT/'docker-image';image.mkdir(exist_ok=True)
shutil.copy2(OUT/'one-api-candidate',image/'one-api-candidate')
(image/'Dockerfile').write_text('FROM one-api:hardware70-20261001\nCOPY one-api-candidate /one-api-bailian-core-image\n')
run(['docker','build','-t','one-api:natural-dialogue-20261005',str(image)],timeout=120)
back=OUT/('production-backup-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S'))
back.mkdir(mode=0o700)
inspection=json.loads(run(['docker','inspect','one-api']))[0]
(back/'container-private.json').write_text(json.dumps(inspection))
os.chmod(back/'container-private.json',0o600)
db=yaml.safe_load((PROD/'main/manager-api/src/main/resources/application-dev.yml').read_text())['spring']['datasource']['druid']
m=re.search(r'mysql://([^:/]+)(?::(\d+))?/([^?]+)',db['url'])
env=dict(os.environ,MYSQL_PWD=str(db['password']))
def sql(q):return run(['mysql','--host='+m[1],'--port='+(m[2]or'3306'),'--user='+str(db['username']),'--batch','--raw','--skip-column-names',m[3]],input=q.encode(),env=env,timeout=15).decode().strip()
private={'model':json.loads(sql("SELECT config_json FROM ai_model_config WHERE id='LLM_QwenPlusOfficial';")),
 'channel':json.loads(sql("SELECT JSON_OBJECT('models',models) FROM one_api.channels WHERE id=8;")),
 'abilities':json.loads(sql("SELECT COALESCE(JSON_ARRAYAGG(JSON_OBJECT('group',`group`,'model',model,'channel_id',channel_id,'enabled',enabled,'priority',priority)),JSON_ARRAY()) FROM one_api.abilities WHERE channel_id=8;"))}
(back/'database-private.json').write_text(json.dumps(private));os.chmod(back/'database-private.json',0o600)
shutil.copy2(PROD/'main/manager-api/target/xiaozhi-esp32-api.jar',back/'manager-api.jar')
shutil.copytree('/var/www/realecho-www',back/'frontend')
changed=run(['git','-C',str(CAND),'diff','--name-only']).decode().splitlines()
changed+=['main/xiaozhi-server/core/utils/conversation_guidance.py','main/manager-web/src/constants/personaPresets.js','main/manager-web/src/components/PersonaPresetPicker.vue','main/xiaozhi-server/test/test_conversation_contract.py','main/xiaozhi-server/test/test_natural_tool_failure_regression.py']
changed=list(dict.fromkeys(changed));manifest={}
for name in changed:
 assert name.startswith('main/') and '..' not in Path(name).parts
 p=PROD/name
 old=run(['git','-C',str(PROD),'show',BASE+':'+name]) if p.exists() else None
 assert old is None or old==p.read_bytes(),'production_source_changed_'+name
 if p.exists():
  target=back/'source'/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target)
 manifest[name]={'before':hashlib.sha256(old).hexdigest() if old else None,'after':hashlib.sha256((CAND/name).read_bytes()).hexdigest()}
gate_names=['hardwarebilling/pricing.go','hardwarebilling/qwen38_price_test.go','relay/controller/hardware_billing.go','relay/controller/qwen38_cloud_test.go','relay/billing/ratio/model.go','relay/model/general.go','relay/model/qwen38_request_test.go']
for name in gate_names:
 p=Path('/root/prjs/one-api-bailian')/name
 if p.exists():
  target=back/'gateway'/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target)
plan={'baseline':BASE,'backup':str(back),'files':manifest,'gateway_files':gate_names,'image':'one-api:natural-dialogue-20261005','model':'qwen3.8-flash','temperature':0.4}
(OUT/'release-plan.json').write_text(json.dumps(plan,indent=2))
print(json.dumps({'prepared':True,'production_changed':False,'source_files':len(manifest),'backup':str(back),'image_built':True}))
