"""Actual production persona assembly, main LLM, response path and read-only MCP.

Independent synthetic sessions; no customer chat history, memory or hardware writes.
The six preset texts are changed only in these isolated in-memory sessions.
"""
import asyncio,hashlib,json,os,re,subprocess,sys,time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock,patch
from urllib.request import Request,urlopen
from zoneinfo import ZoneInfo
import yaml
PROD=Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server')
OUT=Path('/root/prjs/tmp/natural-dialogue-presets-20261005')
os.chdir(PROD);sys.path[:0]=[str(PROD),str(PROD/'test')]
import config.logger
config.logger.setup_logging=lambda:MagicMock()
mgr=yaml.safe_load((PROD/'data/.config.yaml').read_text())['manager-api']
url=mgr['url'].rstrip('/')
if '/xiaozhi' not in url:url+='/xiaozhi'
headers={'Authorization':'Bearer '+mgr['secret'],'Content-Type':'application/json'}
payload={'macAddress':'ac:a7:04:fd:20:2c','clientId':'persona-isolated-acceptance','selectedModule':{'LLM':'LLM_QwenPlusOfficial'}}
def readcfg():
 with urlopen(Request(url+'/config/agent-models',data=json.dumps(payload).encode(),headers=headers),timeout=20) as r:return json.load(r)['data']
data=readcfg()
with urlopen(Request(url+'/config/server-base',data=b'{}',headers=headers),timeout=20) as r:base=json.load(r)['data']
cfg=next(v for v in data['LLM'].values() if isinstance(v,dict) and v.get('model_name'))
assert cfg['model_name']=='qwen3.7-plus' and cfg['base_url']=='http://127.0.0.1:3000/v1' and cfg['hardware_billing']
assert cfg['temperature']==.4 and cfg['max_tokens']==600
assert cfg['enable_thinking'] is False and cfg['preserve_thinking'] is False
inspection=json.loads(subprocess.check_output(['docker','inspect','one-api'],text=True))[0]
private_env=dict(entry.split('=',1) for entry in inspection['Config']['Env'] if '=' in entry)
os.environ['HW_BILLING_SERVICE_KEY']=private_env['HW_BILLING_SERVICE_KEY']
os.environ['HW_BILLING_GATEWAY_ORIGIN']='http://127.0.0.1:3000'
from core.utils.prompt_manager import PromptManager
from core.providers.llm.openai.openai import LLMProvider
from core.providers.tools.server_mcp.mcp_client import ServerMCPClient
from core.providers.tools.server_mcp.mcp_executor import ServerMCPExecutor
from core.providers.tools.unified_tool_manager import ToolManager
from core.providers.tools.base import ToolType
from core.providers.tts.dto.dto import ContentType
from plugins_func.register import Action,ActionResponse
from test_primary_answer_direct_tts import PrimaryAnswerDirectTtsTests
inventory=json.loads((OUT/'persona-inventory-20261007.json').read_text())
assert data['prompt']==inventory['current_persona']
personas=[{'id':'current','name':'当前自定义人格','prompt':data['prompt']}]+inventory['presets']
scenes=[
 {'id':'light','name':'轻松聊天与收住玩笑','turns':[
  '今天买了一个小花盆，还没种东西。我就是闲聊，不用帮我安排。',
  '我把跑步鞋摆到门口，结果一整天都没穿，鞋倒先占上位置了。',
  '这事可以打趣两句，但别叫我宝宝，也别表演动作。',
  '今天先别逗我，也别说慢慢来。直接说说把旧书重新摆出来这件事，你怎么看？']},
 {'id':'serious','name':'认真交流与事实状态','turns':[
  '今天会上我的意见被打断了几次，我有点烦。我只是说说，别替我安排。',
  '别分析我，也别替对方找理由，你就说这件事。',
  '上周报告正文写好一半，昨天只改了标题，剩下的正文还没碰。',
  '只根据我说的，报告正文目前完成了多少？昨天没进展能说从来没写过吗？']},
 {'id':'help','name':'建议请求和切回闲聊','turns':[
  '我有三个任务：明天交报告，下周交照片，读一本没有期限的书。你觉得我该先做哪个？说说理由。',
  '我现在不想要方案了，只想聊聊。你觉得买书和读书是同一种快乐吗？别反问。',
  '这次只给一个具体看法和理由，别夸我，也别把小事说成人生道理。']},
 {'id':'tools','name':'人格不干扰查询及否定请求','turns':[
  '伦敦那边现在几点了？帮我查一下，直接说结果，别顺便逗我。',
  '别查时间。我只是想知道时差是什么意思，正常解释一下。']}
]
def sha(value):return hashlib.sha256(value.encode()).hexdigest()
report={'date_beijing':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),'model':'qwen3.7-plus','temperature':.4,'max_tokens':600,'enable_thinking':False,'preserve_thinking':False,'production_gateway':True,'owned_account_signed_billing':True,'secondary_rewrite':False,'semantic_sentence_checker':False,'repeats':2,'personas':personas,'scenarios':scenes,'expected_turns':182,'hardware_writes':0,'customer_memory_writes':0,'physical_voice_test':False,'scope':'真实线上代码及文本输出；独立合成会话，不带个人历史或长期记忆，不合成音频','sessions':[],'finished':False}
path=OUT/'persona-runtime-results-20261007.json'
def save():path.write_text(json.dumps(report,ensure_ascii=False,indent=2))
def state_hash(d):return sha(json.dumps({k:d.get(k) for k in ['agent_id','prompt','device_name','user_nickname','summaryMemory','selected_module']},sort_keys=True,ensure_ascii=False))
state_before=state_hash(data)
native_budget=0
async def run():
 global native_budget
 settings=json.loads((PROD/'data/.mcp_server_settings.json').read_text())['mcpServers']
 client=ServerMCPClient(next(v for v in settings.values() if not v.get('disabled',False)))
 PrimaryAnswerDirectTtsTests.setUpClass()
 try:
  await asyncio.wait_for(client.initialize(),20);definitions=client.get_available_tools()
  report['tool_catalog_sha256']=sha(json.dumps(definitions,sort_keys=True,ensure_ascii=False));report['tools_count']=len(definitions)
  for repeat in [1,2]:
   for persona in personas:
    system=PromptManager(dict(base,**data),logger=MagicMock()).build_enhanced_prompt_v2(persona['prompt'],'persona-isolated-test',device_name=data.get('device_name','小智'),user_nickname=data.get('user_nickname','用户'),official_enhanced=True)
    assert '<personality>\n'+persona['prompt']+'\n</personality>' in system
    if persona['id']=='current':assert sha(system)==inventory['effective_system_sha256']
    for scene in scenes:
     fixture=PrimaryAnswerDirectTtsTests();fixture.setUp()
     clock=patch('core.utils.turn_context.build_turn_context',return_value={'current_datetime':datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M:%S'),'timezone':'Asia/Shanghai'})
     clock.start();fixture.addCleanup(clock.stop)
     h=fixture.handler(functions=definitions);h.config=dict(base,**data,operation_control={'enabled':True})
     h.actor.key=('synthetic-persona',persona['id'],repeat);h.dialogue.update_system_message(system)
     h.llm=LLMProvider(cfg);h.llm.client=h.llm.client.with_options(max_retries=0)
     executor=ServerMCPExecutor(h);executor._initialized=True;executor.mcp_manager=SimpleNamespace(get_all_tools=lambda:definitions,execute_tool=client.call_tool)
     manager=ToolManager(h);manager.register_executor(ToolType.SERVER_MCP,executor)
     events=[];api_requests=[];billing_ids=[]
     async def tool_handler(conn,call):
      args=json.loads(call['arguments'])
      if call['name'] not in {'get_world_time','mcp_get_world_time'}:
       events.append({'name':call['name'],'arguments':args,'blocked_by_test_harness':True})
       return ActionResponse(action=Action.ERROR,response='测试只允许时间查询，未执行其他操作。')
      result=await manager.execute_tool(call['name'],args)
      events.append({'name':call['name'],'arguments':args,'receipt':result.result,'action':result.action.name})
      return result
     h.func_handler=SimpleNamespace(get_functions=lambda:definitions,handle_llm_function_call=tool_handler,tool_manager=manager)
     h.llm.client._client.event_hooks.setdefault('request',[]).append(lambda req:billing_ids.append(req.headers.get('X-HW-Request-ID','')))
     original=h.llm._create_with_retry
     def capture(**params):
      global native_budget
      native_budget+=1;assert native_budget<=240,'model_call_budget_exceeded'
      assert params['model']=='qwen3.7-plus' and params['temperature']==.4 and params['max_tokens']==600
      assert params['extra_body']=={'enable_thinking':False,'preserve_thinking':False}
      record={'model':params['model'],'raw_text':'','tool_calls':{},'reasoning_chars':0,'usage':None}
      api_requests.append(record)
      for chunk in original(**params):
       if chunk.usage:record['usage']=chunk.usage.model_dump()
       for choice in chunk.choices or []:
        record['raw_text']+=choice.delta.content or ''
        record['reasoning_chars']+=len(getattr(choice.delta,'reasoning_content',None) or '')
        for c in choice.delta.tool_calls or []:
         item=record['tool_calls'].setdefault(c.index,{'id':'','name':'','arguments':''})
         if c.id:item['id']=c.id
         if c.function.name:item['name']+=c.function.name
         if c.function.arguments:item['arguments']+=c.function.arguments
       yield chunk
     h.llm._create_with_retry=capture
     session={'persona_id':persona['id'],'persona_name':persona['name'],'scenario':scene['id'],'repeat':repeat,'system_sha256':sha(system),'turns':[]}
     report['sessions'].append(session)
     try:
      for index,text in enumerate(scene['turns'],1):
       h.tts_events.clear();events.clear();api_requests.clear();billing_ids.clear();start=time.perf_counter()
       error=None
       try:ok=await asyncio.to_thread(lambda:h.chat(text,_identity=h.actor))
       except Exception as exc:ok=False;error={'type':type(exc).__name__}
       spoken=''.join(str(e.content_detail) for e in h.tts_events if e.content_type==ContentType.TEXT)
       row={'turn':index,'user':text,'assistant':spoken,'runtime_ok':bool(ok),'tool_events':list(events),'model_requests':json.loads(json.dumps(api_requests,ensure_ascii=False)),'billing_ids':list(billing_ids),'elapsed_ms':round((time.perf_counter()-start)*1000),'error':error}
       session['turns'].append(row);save()
      print(json.dumps({'completed':sum(len(s['turns']) for s in report['sessions']),'persona':persona['name'],'scenario':scene['id'],'repeat':repeat}),flush=True)
     finally:h.llm.client.close();fixture.doCleanups()
 finally:
  await client.cleanup();PrimaryAnswerDirectTtsTests.tearDownClass()
 assert state_hash(readcfg())==state_before,'customer_configuration_changed'
 report.update(finished=True,model_requests=native_budget,customer_configuration_unchanged=True)
 save();print(json.dumps({'finished':True,'turns':sum(len(s['turns']) for s in report['sessions']),'model_requests':native_budget}),flush=True)
asyncio.run(run())
