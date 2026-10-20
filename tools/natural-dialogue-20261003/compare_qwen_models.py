"""Offline, bounded comparison. Uses existing Alibaba credential in memory only."""
import hashlib, json, os, re, subprocess, sys, time
from pathlib import Path
from urllib.parse import urlparse
from unittest.mock import MagicMock
import yaml
from openai import OpenAI

OUT=Path('/root/prjs/tmp/natural-dialogue-20261003')
ROOT=Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server')
# Synthetic public test only: no production prompt, device config or customer history.
persona='你腹黑、调皮、爱捉弄人。说话带一点坏心眼，喜欢调侃用户，但本质是善意的玩笑。'
system='''你叫小智，用中文与用户自然交谈。
用户选择的人格：你腹黑、调皮、爱捉弄人。说话带一点坏心眼，喜欢调侃用户，但本质是善意的玩笑。
聊天规则：
1. 按用户实际说的内容接话。计划、愿望、猜测不等于已经发生的事实；没有用户说明或工具结果，不声称事情已完成。
2. 用户当下明确说“别教育我”“别给方案”“随便聊聊”时，遵守该要求；个性通过措辞自然体现。
3. 日常闲聊通常简短，不默认提供建议、清单、追问或安排；用户主动问建议时才给建议。
4. 不写舞台动作、表情标签、拟声表演，不虚构自己的身体动作或替用户准备东西。
5. 执行实际操作必须通过API结构化tool_calls调用可用工具，正文不能假装执行。工具目录里没有的能力如实说明，不能用别的工具冒充。收到成功结果之前不能说操作已完成。
'''
db=yaml.safe_load((ROOT.parent/'manager-api/src/main/resources/application-dev.yml').read_text())['spring']['datasource']['druid']
match=re.search(r'mysql://([^:/]+)(?::(\d+))?/([^?]+)',db['url'])
env=dict(os.environ,MYSQL_PWD=str(db['password']))
def sql(query):
    p=subprocess.run(['mysql','--host='+match[1],'--port='+(match[2]or'3306'),'--user='+str(db['username']),'--batch','--raw','--skip-column-names',match[3]],input=query,env=env,capture_output=True,text=True,timeout=15)
    if p.returncode:raise RuntimeError('database_query_failed')
    return p.stdout.strip()
channel=json.loads(sql("SELECT JSON_OBJECT('key',`key`,'base_url',base_url) FROM one_api.channels WHERE id=8 AND status=1;"))
assert urlparse(channel['base_url']).hostname=='dashscope.aliyuncs.com'
assert '\n' not in channel['key'],'multi-key channel needs explicit selection'
client=OpenAI(api_key=channel['key'],base_url=channel['base_url'],max_retries=0,timeout=45)
scenes=[
 ('下班闲聊',['今天累了一天，啥也不想干。','别给我灌鸡汤，也别给方案，就随便聊两句。','我点了外卖，吃完洗澡，然后躺着。']),
 ('拖延与接话',['本来想今天把方案写完，结果刷手机刷到现在。','你这话听着像我领导，别教育我。','那你说，我今晚还做不做？']),
 ('轻松调侃',['我打算周末把家里彻底收拾一遍。','说实话，我每次都这么说，最后就收拾个桌面。'])]
report={'production_default_unchanged':True,'production_model':'qwen-plus',
 'credential_source':'existing active Alibaba upstream channel; secret not exported',
 'api_host':urlparse(channel['base_url']).hostname,'persona':persona,'persona_sha256':hashlib.sha256(persona.encode()).hexdigest(),
 'prompt_source':'synthetic public rules, not full production prompt','system_prompt':system,
 'system_characters':len(system),'system_sha256':hashlib.sha256(system.encode()).hexdigest(),
 'generation_parameters':{'temperature':0.7,'top_p':1.0,'max_tokens':600,'enable_thinking':False,'preserve_thinking':False},
 'text_only':True,'secondary_rewrite':False,'tools_executed':0,'call_limit':48,'calls':0,'models':[]}
def save():
 (OUT/'qwen-model-comparison.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
def call(model,messages,tools=None):
 assert report['calls']<report['call_limit'];report['calls']+=1
 started=time.perf_counter()
 try:
  kw={'model':model,'messages':messages,'temperature':0.7,'top_p':1.0,'max_tokens':600,'extra_body':{'enable_thinking':False,'preserve_thinking':False}}
  if tools:kw.update(tools=tools,tool_choice='auto')
  result=client.chat.completions.create(**kw)
  msg=result.choices[0].message
  return {'assistant':msg.content or '', 'tool_calls':[{'name':t.function.name,'arguments':t.function.arguments} for t in (msg.tool_calls or [])],
    'elapsed_ms':round((time.perf_counter()-started)*1000),'usage':result.usage.model_dump() if result.usage else None,
    'response_model':result.model,'finish_reason':result.choices[0].finish_reason}
 except Exception as e:
  body=getattr(e,'body',{}) or {}
  if isinstance(body,dict):body=body.get('error',body)
  code=body.get('code') if isinstance(body,dict) else None
  return {'error':type(e).__name__,'http_status':getattr(e,'status_code',None),'api_code':code,'elapsed_ms':round((time.perf_counter()-started)*1000)}
def user(text):return {'role':'user','content':text}
tools=[{'type':'function','function':{'name':'self_audio_speaker_set_volume','description':'设置设备扬声器音量。','parameters':{'type':'object','properties':{'volume':{'type':'integer','minimum':0,'maximum':100}},'required':['volume']}}},
 {'type':'function','function':{'name':'self_get_device_status','description':'查询设备当前状态，包括音量和亮度。','parameters':{'type':'object','properties':{}}}}]
for model in ['qwen-plus','qwen3.8-flash','qwen3.8-max','qwen3.7-plus']:
 entry={'requested_model':model,'scenes':[],'tool_selection_probes':[]};report['models'].append(entry)
 failed=False
 for title,inputs in scenes:
  messages=[{'role':'system','content':system}];rows=[];entry['scenes'].append({'title':title,'turns':rows})
  for text in inputs:
   messages.append(user(text));row={'user':text,**call(model,messages)};rows.append(row);save()
   print(json.dumps({'model':model,'scene':title,**row},ensure_ascii=False),flush=True)
   if 'error' in row:failed=True;break
   messages.append({'role':'assistant','content':row['assistant']})
  if failed:break
 if failed:continue
 for text,available,expected in [('声音小一点，调到30吧',tools,'self_audio_speaker_set_volume'),('先别调音量，我就问问现在是多少',tools,'self_get_device_status'),('打开摄像头让我看实时画面',tools,None)]:
  row={'user':text,'expected_tool':expected,**call(model,[{'role':'system','content':system},user(text)],available)}
  entry['tool_selection_probes'].append(row);save();print(json.dumps({'model':model,'probe':True,**row},ensure_ascii=False),flush=True)
save();print(json.dumps({'completed':True,'calls':report['calls']}),flush=True)
