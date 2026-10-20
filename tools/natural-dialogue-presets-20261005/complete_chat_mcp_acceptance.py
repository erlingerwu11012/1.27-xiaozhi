"""Actual candidate handler + native calls + live read-only MCP receipts."""
import os,json,asyncio,time
import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
os.environ['CANDIDATE_RUNTIME']='1'
s=Path(__file__).with_name('runtime_production_acceptance.py').read_text().split('async def runtime_mcp():')[0]
exec(compile(s,'<bootstrap>','exec'));provider.client.close()
from test_primary_answer_direct_tts import PrimaryAnswerDirectTtsTests
from core.providers.tts.dto.dto import ContentType
from core.utils.tool_fact_reply import world_time_reply
from plugins_func.register import Action,ActionResponse

async def run():
 settings=json.loads((PROD/'data/.mcp_server_settings.json').read_text())['mcpServers']
 client=ServerMCPClient(next(c for c in settings.values() if not c.get('disabled',False)))
 fixture=PrimaryAnswerDirectTtsTests();fixture.setUpClass();fixture.setUp()
 h=fixture.handler();h.config['operation_control']={'enabled':True};h.actor.key=('synthetic','mcp-release',1)
 h.config['conversation_validation']={'semantic_enabled':True,'model_names':['qwen3.8-max']}
 h.dialogue.update_system_message(prompt);h.llm=LLMProvider(dict(llm,model_name='qwen3.8-max',temperature=0.3,timeout=45,max_tokens=250))
 report={'hardware_writes':0,'physical_test':False,'cases':[],'success':False}
 report['runtime_source_sha256']={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest()
    for p in ['core/connection.py','core/utils/conversation_turn.py','core/utils/conversation_guidance.py']}
 report_path=OUT/(os.environ.get('CHAT_REPORT','complete-chat-mcp-scoped')+'.json')
 events=[];calls=[]
 original=h.llm.client.chat.completions.create
 def capture(**params):
  calls.append({'model':params['model'],'stream':params.get('stream')});return original(**params)
 h.llm.client.chat.completions.create=capture
 try:
  await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(client.initialize(),h.loop))
  definitions=client.get_available_tools()
  executor=ServerMCPExecutor(h);executor._initialized=True
  executor.mcp_manager=SimpleNamespace(get_all_tools=lambda:definitions,execute_tool=client.call_tool)
  manager=ToolManager(h);manager.register_executor(ToolType.SERVER_MCP,executor)
  async def handler(conn,call):
   if call['name'] not in {'get_world_time','mcp_get_world_time'}:
    events.append({'name':call['name'],'blocked':True});return ActionResponse(action=Action.ERROR,response='验收只允许时间查询，未执行其他操作。')
   args=json.loads(call['arguments']);result=await manager.execute_tool(call['name'],args)
   events.append({'name':call['name'],'arguments':args,'receipt':result.result,'action':result.action.name})
   return result
  h.func_handler=SimpleNamespace(get_functions=lambda:definitions,handle_llm_function_call=handler,tool_manager=manager)
  samples=['查询伦敦现在的时间','查询东京现在的时间','查询上海现在的时间',
           '伦敦那边现在几点了？','东京的时间你能帮我看看吗？','帮我看一下现在伦敦和东京分别几点。']
  for text in samples:
   h.tts_events.clear();events.clear();calls.clear()
   start=time.perf_counter();ok=await asyncio.to_thread(lambda:h.chat(text,_identity=h.actor))
   spoken=''.join(str(e.content_detail) for e in h.tts_events if e.content_type==ContentType.TEXT)
   expected=''.join(world_time_reply(e['arguments'],e['receipt']) for e in events if not e.get('blocked'))
   success=bool(ok and events and all(not e.get('blocked') for e in events) and spoken==expected)
   row={'user':text,'spoken':spoken,'tool_events':list(events),'primary_requests':list(calls),'elapsed_ms':round((time.perf_counter()-start)*1000),'success':success}
   report['cases'].append(row)
   report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(row,ensure_ascii=False),flush=True)
  report['success']=all(r['success'] for r in report['cases'])
  report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2))
 finally:
  await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(client.cleanup(),h.loop))
  h.llm.client.close();fixture.doCleanups();fixture.tearDownClass()
 print(json.dumps({'success':report['success']}))
 if not report['success']:raise SystemExit(1)
asyncio.run(run())
