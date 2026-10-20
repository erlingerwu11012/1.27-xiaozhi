"""Actual candidate platform prompts, public personas and synthetic test conversations."""
import hashlib,json,os,re,subprocess,sys,time
from pathlib import Path
from unittest.mock import MagicMock
from urllib.request import Request,urlopen
import yaml
from openai import OpenAI
OUT=Path('/root/prjs/tmp/natural-dialogue-presets-20261005')
PROD=Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server')
ROOT=OUT/'worktree/main/xiaozhi-server'
os.chdir(ROOT);sys.path.insert(0,str(ROOT))
import config.logger
config.logger.setup_logging=lambda:MagicMock()
db=yaml.safe_load((PROD.parent/'manager-api/src/main/resources/application-dev.yml').read_text())['spring']['datasource']['druid']
match=re.search(r'mysql://([^:/]+)(?::(\d+))?/([^?]+)',db['url'])
env=dict(os.environ,MYSQL_PWD=str(db['password']))
def sql(query):
 p=subprocess.run(['mysql','--host='+match[1],'--port='+(match[2]or'3306'),'--user='+str(db['username']),'--batch','--raw','--skip-column-names',match[3]],input=query,env=env,capture_output=True,text=True,timeout=15)
 if p.returncode:raise RuntimeError('database_query_failed')
 return p.stdout.strip()
channel=json.loads(sql("SELECT JSON_OBJECT('key',`key`,'base_url',base_url) FROM one_api.channels WHERE id=8 AND status=1;"))
assert channel['base_url']=='https://dashscope.aliyuncs.com/compatible-mode/v1'
client=OpenAI(api_key=channel['key'],base_url=channel['base_url'],max_retries=0,timeout=45)
mgr=yaml.safe_load((PROD/'data/.config.yaml').read_text())['manager-api']
url=mgr['url'].rstrip('/')
if '/xiaozhi' not in url:url+='/xiaozhi'
request=Request(url+'/config/server-base',data=b'{}',method='POST',headers={'Authorization':'Bearer '+mgr['secret'],'Content-Type':'application/json'})
with urlopen(request,timeout=15) as response:base=json.load(response)['data']
public_config={'system_base_prompt':base.get('system_base_prompt',''),'language':'中文'}
from core.utils.prompt_manager import PromptManager
from core.utils.current_time import get_prompt_time_context
from core.utils.turn_context import render_turn_context
node_code="import {readFileSync} from 'node:fs';const mod=await import('data:text/javascript;base64,'+readFileSync(process.argv[1]).toString('base64'));console.log(JSON.stringify(mod.PERSONA_PRESETS));"
presets=json.loads(subprocess.run(['node','--input-type=module','-e',node_code,str(OUT/'worktree/main/manager-web/src/constants/personaPresets.js')],check=True,capture_output=True,text=True).stdout)
presets.append({'id':'existing-playful','name':'此前截图原文','prompt':'你腹黑、调皮、爱捉弄人。说话带一点坏心眼，喜欢调侃用户，但本质是善意的玩笑。'})
def build(persona):return PromptManager(public_config,logger=MagicMock()).build_enhanced_prompt_v2(persona,'synthetic-template-test',device_name='小智',user_nickname='小林',official_enhanced=True)
report={'candidate':'current three-layer assembly with revised platform rules and examples','production_changed':False,'customer_history_used':False,
 'secondary_rewrite':False,'native_tool_calls_executed':0,'max_calls':140,'calls':0,'temperature':0.7,'top_p':1.0,'max_tokens':500,
 'thinking':False,'training_scenarios':[],'heldout_scenarios':[],'model_comparison':[],'tool_probes':[]}
def save(): (OUT/'live-prompt-acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
def call(model,messages,tools=None):
 assert report['calls']<report['max_calls'];report['calls']+=1;start=time.perf_counter()
 try:
  kwargs=dict(model=model,messages=messages,temperature=0.7,top_p=1.0,max_tokens=500,extra_body={'enable_thinking':False,'preserve_thinking':False})
  if tools:kwargs.update(tools=tools,tool_choice='auto')
  result=client.chat.completions.create(**kwargs);msg=result.choices[0].message
  return {'assistant':msg.content or '', 'tool_calls':[{'name':t.function.name,'arguments':t.function.arguments} for t in(msg.tool_calls or [])],
   'response_model':result.model,'finish_reason':result.choices[0].finish_reason,'elapsed_ms':round((time.perf_counter()-start)*1000),'usage':result.usage.model_dump() if result.usage else None}
 except Exception as e:return {'error':type(e).__name__,'http_status':getattr(e,'status_code',None)}
def user(text):return {'role':'user','content':render_turn_context(get_prompt_time_context())+'\n[用户原话]\n'+text}
def scene(model,preset,title,inputs,group):
 system=build(preset['prompt']);entry={'model':model,'preset':preset['id'],'scene':title,'system_characters':len(system),
  'persona_sha256':hashlib.sha256(preset['prompt'].encode()).hexdigest(),'turns':[]};report[group].append(entry)
 messages=[{'role':'system','content':system}]
 for text in inputs:
  messages.append(user(text));row={'user':text,**call(model,messages)};entry['turns'].append(row);save()
  print(json.dumps({'model':model,'preset':preset['id'],'scene':title,**row},ensure_ascii=False),flush=True)
  if 'error' in row:raise RuntimeError('candidate_model_request_failed')
  messages.append({'role':'assistant','content':row['assistant']})
training=[('下班闲聊',['今天累了一天，啥也不想干。','别给我灌鸡汤，也别给方案，就随便聊两句。','我点了外卖，吃完洗澡，然后躺着。']),
 ('拖延与反馈',['本来想今天把方案写完，结果刷手机刷到现在。','你这话听着像我领导，别教育我。','那你说，我今晚还做不做？']),
 ('收拾房间',['我打算周末把家里彻底收拾一遍。','说实话，我每次都这么说，最后就收拾个桌面。'])]
for preset in presets:
 for title,inputs in training:scene('qwen3.8-flash',preset,title,inputs,'training_scenarios')
 # New phrasing not present in platform examples. State deliberately has not happened.
 scene('qwen3.8-flash',preset,'新措辞与事实', ['洗碗机后天才到，我现在只是想想厨房怎么放。','别忙着替我规划，我就是随口一说，今天也别逗我。'],'heldout_scenarios')
for model in ('qwen-plus','qwen3.8-max'):
 for preset in (presets[0],presets[-1]):scene(model,preset,'相同提示词模型对照',training[1][1],'model_comparison')
tools=[{'type':'function','function':{'name':'self_audio_speaker_set_volume','description':'设置设备音量。','parameters':{'type':'object','properties':{'volume':{'type':'integer','minimum':0,'maximum':100}},'required':['volume']}}},
 {'type':'function','function':{'name':'self_get_device_status','description':'查询设备音量和亮度。','parameters':{'type':'object','properties':{}}}},
 {'type':'function','function':{'name':'self_camera_take_photo','description':'拍一张静态照片并识别，不支持实时预览。','parameters':{'type':'object','properties':{'question':{'type':'string'}},'required':['question']}}}]
for preset in (presets[0],presets[4],presets[-1]):
 for text,expected in [('声音小一点，调到30吧','self_audio_speaker_set_volume'),('先别调音量，我就问问现在是多少','self_get_device_status'),('打开摄像头让我看实时画面',None),('他跟我说“把音量调到30”，这句话是什么意思？',None),('拍张照片，看看桌上是什么','self_camera_take_photo')]:
  row={'preset':preset['id'],'user':text,'expected_tool':expected,**call('qwen3.8-flash',[{'role':'system','content':build(preset['prompt'])},user(text)],tools)}
  report['tool_probes'].append(row);save();print(json.dumps({'tool_probe':True,**row},ensure_ascii=False),flush=True)
print(json.dumps({'completed':True,'calls':report['calls'],'presets':len(presets)}),flush=True)
