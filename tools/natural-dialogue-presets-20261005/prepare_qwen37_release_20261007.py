"""Build/test isolated production candidates; preserve frozen prompt and billing policy."""
import ast,hashlib,json,os,shutil,subprocess,zipfile
from pathlib import Path
from inspect_qwen37_release_20261007 import sql,PROD,OUT
ROOT=Path('/root/prjs/tmp/qwen37-official-release-20261007')
ROOT.mkdir(mode=0o700,exist_ok=True)
MAN=ROOT/'manager-api';GATE=ROOT/'gateway';PY=ROOT/'xiaozhi-server'
for src,dst in [(PROD/'main/manager-api',MAN),(Path('/root/prjs/one-api-bailian'),GATE)]:
 if not dst.exists():shutil.copytree(src,dst,ignore=shutil.ignore_patterns('.git','target','node_modules','one-api-candidate','one-api-bailian','*.log'))
PY.mkdir(exist_ok=True)
manifest={}
def edit(root,name,mutate,kind):
 src=root/name
 target=(MAN if kind=='manager' else GATE if kind=='gateway' else PY)/name
 target.parent.mkdir(parents=True,exist_ok=True)
 before=src.read_text(encoding='utf-8-sig');after=mutate(before)
 assert before!=after,name
 target.write_text(after)
 manifest[kind+':'+name]={'before':hashlib.sha256(src.read_bytes()).hexdigest(),'after':hashlib.sha256(target.read_bytes()).hexdigest()}
def replace(s,old,new,count=1):
 assert s.count(old)==count,old
 return s.replace(old,new)
pack=json.loads((OUT/'qwen-paired-tool-pack-20261006.json').read_text())
tree=ast.parse(Path('/root/prjs/tmp/complete-chat-review-20261006/main/xiaozhi-server/core/utils/conversation_guidance.py').read_text(encoding='utf-8-sig'))
natural=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='NATURAL_CONVERSATION_GUIDANCE' for t in n.targets))
assert '\n\n'+natural.strip()+'\n\n'+pack['tool_guidance'] in pack['cases'][0]['initial_messages'][0]['content']
edit(PROD/'main/xiaozhi-server','core/utils/conversation_guidance.py',lambda _: '"""Shared natural speech and verified native tool rules; user persona stays separate."""\nNATURAL_CONVERSATION_GUIDANCE = '+repr(natural)+'\n\nTOOL_EXECUTION_GUIDANCE = '+repr(pack['tool_guidance'])+'\n','python')
edit(PROD/'main/xiaozhi-server','core/utils/prompt_manager.py',lambda s:replace(replace(s,'from core.utils.conversation_guidance import NATURAL_CONVERSATION_GUIDANCE','from core.utils.conversation_guidance import NATURAL_CONVERSATION_GUIDANCE, TOOL_EXECUTION_GUIDANCE'),"            enhanced_prompt += '\\n\\n' + NATURAL_CONVERSATION_GUIDANCE.strip()", "            enhanced_prompt += '\\n\\n' + NATURAL_CONVERSATION_GUIDANCE.strip()\n            enhanced_prompt += '\\n\\n' + TOOL_EXECUTION_GUIDANCE"),'python')
edit(PROD/'main/xiaozhi-server','core/providers/llm/openai/openai.py',lambda s:replace(s,'{"qwen3.8-flash", "qwen3.8-max"}','{"qwen3.7-plus", "qwen3.8-flash", "qwen3.8-max"}',3),'python')
for name in ['core/utils/operation_control.py','core/providers/tools/unified_tool_manager.py']:
 edit(PROD/'main/xiaozhi-server',name,lambda _,n=name:(OUT/'qwen-paired-guard'/n).read_text(),'python')
edit(PROD/'main/manager-api','src/main/java/xiaozhi/modules/model/OfficialServiceDefaults.java',lambda s:replace(s,'LLM_MODEL_NAME = "qwen3.8-flash"','LLM_MODEL_NAME = "qwen3.7-plus"'),'manager')
price='''\tif model == "qwen3.7-plus" && (operation == "llm" || operation == "summary" || operation == "habit") {
\t\tmode := "non_thinking"
\t\tmaximum := int64(991808)
\t\tif thinking { mode = "thinking"; maximum = 983616 }
\t\treturn Price{Version: "aliyun-beijing-20261007-qwen37", Region: "cn-beijing", Model: model, Operation: operation, Mode: mode, SourceURL: "https://help.aliyun.com/zh/model-studio/qwen3-7-plus", Unit: "tokens", Tiers: []Tier{{256000, "2", "8", "0.4"}, {maximum, "6", "24", "1.2"}}}, nil
\t}
'''
edit(Path('/root/prjs/one-api-bailian'),'hardwarebilling/pricing.go',lambda s:replace(s,'func BeijingPrice(model, operation string, thinking bool) (Price, error) {','func BeijingPrice(model, operation string, thinking bool) (Price, error) {\n'+price),'gateway')
edit(Path('/root/prjs/one-api-bailian'),'relay/controller/hardware_billing.go',lambda s:replace(s,'request.Model == "qwen-plus" ||','request.Model == "qwen3.7-plus" || request.Model == "qwen-plus" ||'),'gateway')
edit(Path('/root/prjs/one-api-bailian'),'relay/billing/ratio/model.go',lambda s:replace(replace(s,'var ModelRatio = map[string]float64{','var ModelRatio = map[string]float64{\n\t"qwen3.7-plus": 2.0 / 1000 * RMB,'),'"qwen3.8-flash": 2.7 / 0.8,','"qwen3.7-plus": 8.0 / 2.0,\n\t"qwen3.8-flash": 2.7 / 0.8,'),'gateway')
cloud=(GATE/'relay/controller/qwen38_cloud_test.go').read_text().replace('cloud_qwen38','cloud_qwen37').replace('TestQwen38RealAliRelayAndPaidLedger','TestQwen37RealAliRelayAndPaidLedger').replace('qwen3.8-flash','qwen3.7-plus')
(GATE/'relay/controller/qwen37_cloud_test.go').write_text(cloud)
(GATE/'hardwarebilling/qwen37_price_test.go').write_text('''package hardwarebilling
import "testing"
func TestQwen37PriceCacheTierAndExistingSalesRule(t *testing.T) {
 for _, op := range []string{"llm","summary","habit"} {
  p,e:=BeijingPrice("qwen3.7-plus",op,false);if e!=nil{t.Fatal(e)}
  cost,e:=p.Cost(measured(10000,1000,8000));if e!=nil{t.Fatal(e)};equal(t,cost,"0.0152")
  sale,e:=SaleCNY(cost);if e!=nil{t.Fatal(e)};equal(t,sale,"19/375")
  cost,e=p.Cost(measured(256000,1000,0));if e!=nil{t.Fatal(e)};equal(t,cost,"0.52")
  cost,e=p.Cost(measured(256001,1000,0));if e!=nil{t.Fatal(e)};equal(t,cost,"1.560006")
  if _,e=p.Cost(measured(991809,0,0));e==nil{t.Fatal("unsupported input accepted")}
  if _,e=BeijingPrice("qwen3.7-plus-unverified",op,false);e==nil{t.Fatal("unknown alias accepted")}
 }
 if _,e:=BeijingPrice("qwen3.7-plus","vision",false);e==nil{t.Fatal("text operation cannot replace vision route")}
}
''')
def run(args,cwd,log,env=None,timeout=240):
 with (ROOT/log).open('w') as output:
  result=subprocess.run(args,cwd=cwd,env=env,stdout=output,stderr=subprocess.STDOUT,timeout=timeout)
 print(json.dumps({'step':log,'exit':result.returncode}),flush=True)
 assert result.returncode==0,log
run(['/usr/local/go/bin/gofmt','-w','hardwarebilling/pricing.go','hardwarebilling/qwen37_price_test.go','relay/controller/hardware_billing.go','relay/controller/qwen37_cloud_test.go','relay/billing/ratio/model.go'],GATE,'gofmt.log')
for key,record in manifest.items():
 kind,name=key.split(':',1);record['after']=hashlib.sha256(((MAN if kind=='manager' else GATE if kind=='gateway' else PY)/name).read_bytes()).hexdigest()
(ROOT/'source-manifest.json').write_text(json.dumps(manifest,indent=2))
run(['/usr/local/go/bin/go','test','./hardwarebilling','./relay/controller','./relay/billing/ratio','./relay/model'],GATE,'gateway-unit.log')
key=sql('SELECT `key` FROM one_api.channels WHERE id=11 AND status=1;').strip();assert key
run(['/usr/local/go/bin/go','test','-tags','cloud_qwen37','./relay/controller','-run','TestQwen37RealAliRelayAndPaidLedger','-count=1','-v'],GATE,'gateway-cloud.log',dict(os.environ,CLOUD_HW_TEST_KEY=key,CLOUD_HW_AUTHORIZED='1',CLOUD_HW_RESULT_FILE=str(ROOT/'gateway-cloud-acceptance.json')),180)
run(['/usr/local/go/bin/go','build','-o',str(ROOT/'one-api-qwen37'),'.'],GATE,'gateway-build.log')
run(['mvn','-q','-Dtest=HardwareBillingPolicyTest,OfficialServiceDefaultsTest','test'],MAN,'manager-tests.log')
run(['mvn','-q','-DskipTests','package'],MAN,'manager-build.log')
with zipfile.ZipFile(MAN/'target/xiaozhi-esp32-api.jar') as archive:
 for path in (PROD/'main/manager-api/src/main/resources').rglob('*'):
  if path.is_file() and not any(p.startswith('.') for p in path.relative_to(PROD/'main/manager-api/src/main/resources').parts):
   entry='BOOT-INF/classes/'+path.relative_to(PROD/'main/manager-api/src/main/resources').as_posix()
   assert archive.read(entry)==path.read_bytes(),'runtime_resource_changed'
image=ROOT/'image';image.mkdir(exist_ok=True)
shutil.copy2(ROOT/'one-api-qwen37',image/'one-api-qwen37')
(image/'Dockerfile').write_text('FROM one-api:natural-dialogue-20261005\nCOPY one-api-qwen37 /one-api-bailian-core-image\n')
run(['docker','build','-t','one-api:qwen37-official-20261007',str(image)],ROOT,'docker-build.log',timeout=180)
(ROOT/'prepared.json').write_text(json.dumps({'prepared':True,'pack_sha256':pack['content_sha256'],'source_files':manifest,'gateway_cloud':json.loads((ROOT/'gateway-cloud-acceptance.json').read_text()),'production_mutated':False},ensure_ascii=False,indent=2))
print('qwen37_release_candidates_prepared',flush=True)
