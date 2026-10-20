"""Actual bounded request -> ToolManager -> ServerMCPExecutor -> live MCP -> primary model."""
from pathlib import Path
import os
source=Path('/root/prjs/tmp/natural-dialogue-20261003/live_chain_acceptance.py').read_text().split('async def mcp_test():')[0]
source=source.replace("ROOT=Path('/root/prjs/tmp/natural-dialogue-20261003/main/xiaozhi-server')", "ROOT=Path('/root/prjs/tmp/natural-dialogue-presets-20261005/worktree/main/xiaozhi-server')" if os.environ.get('CANDIDATE_RUNTIME')=='1' else 'ROOT=PROD')
source=source.replace('OUT=ROOT.parents[1]', "OUT=Path('/root/prjs/tmp/natural-dialogue-presets-20261005')")
exec(compile(source,'<runtime-production-bootstrap>','exec'))
from core.providers.llm.openai.openai import LLMProvider
from core.providers.tools.server_mcp.mcp_client import ServerMCPClient
from core.providers.tools.server_mcp.mcp_executor import ServerMCPExecutor
from core.providers.tools.unified_tool_manager import ToolManager
from core.providers.tools.base import ToolType
from core.utils.operation_control import get_control,execute_plan,guard_reply
assert llm['model_name']=='qwen3.8-flash' and float(llm['temperature'])==0.4
provider=LLMProvider(dict(llm,timeout=35,max_tokens=200));provider.client=provider.client.with_options(max_retries=0)
report.update(production_gateway=True,candidate_runtime=os.environ.get('CANDIDATE_RUNTIME')=='1',hardware_writes=0,secondary_rewrite=False,dialogues=[])
async def runtime_mcp():
 settings=json.loads((PROD/'data/.mcp_server_settings.json').read_text())['mcpServers']
 client=ServerMCPClient(next(c for c in settings.values() if not c.get('disabled',False)))
 try:
  await asyncio.wait_for(client.initialize(),20)
  definitions=client.get_available_tools()
  conn=SimpleNamespace(config={'operation_control':{'enabled':True}},session_id='synthetic-runtime',mcp_client=SimpleNamespace(ready=True,closed=False))
  executor=ServerMCPExecutor(conn);executor._initialized=True
  executor.mcp_manager=SimpleNamespace(get_all_tools=lambda:definitions,execute_tool=client.call_tool)
  manager=ToolManager(conn);manager.register_executor(ToolType.SERVER_MCP,executor)
  async def handler(c,call):return await manager.execute_tool(call['name'],json.loads(call['arguments']))
  conn.func_handler=SimpleNamespace(tool_manager=manager,handle_llm_function_call=handler)
  for question in ['请查询东京现在的时间','请查询伦敦现在的时间','请查询上海现在的时间']:
   check_budget()
   plan=get_control(conn).begin(question,('synthetic','actor'))
   assert len(plan.requests)==1 and plan.requests[0].kind=='world_time'
   replies,results=await execute_plan(conn,plan)
   assert not replies and len(results)==1
   result,call=results[0]
   assert call['name']=='get_world_time' and result.result,'actual_time_receipt_missing'
   messages=[{'role':'system','content':prompt},{'role':'user','content':question},
    {'role':'assistant','content':None,'tool_calls':[{'id':call['id'],'type':'function','function':{'name':call['name'],'arguments':call['arguments']}}]},
    {'role':'tool','tool_call_id':call['id'],'content':result.result}]
   report['model_calls']+=1
   answer=await asyncio.to_thread(lambda:''.join(provider.response('synthetic-runtime',messages,max_tokens=200)))
   guarded=guard_reply(conn,answer)
   assert guarded and not re.search(r'\[(?:smirk|wink|grin|emotion)|喵|小主人|小尾巴',guarded,re.I)
   report['native_mcp'].append({'question':question,'route':'actual operation_control + unified ToolManager + ServerMCPExecutor','tool_call':call,'actual_tool_result':result.result,'raw_primary_reply':answer,'reply':guarded,'success':True})
 finally:await client.cleanup()
asyncio.run(runtime_mcp())
for persona_id,persona in [('natural','你随和、坦诚，有自己的看法。用熟人之间自然的方式交谈。'),('existing-playful',PERSONA)]:
 system=PromptManager({'system_base_prompt':base.get('system_base_prompt',''),'language':'中文'},logger=MagicMock()).build_enhanced_prompt_v2(persona,'synthetic-production',device_name='小智',user_nickname='小林',official_enhanced=True)
 messages=[{'role':'system','content':system}]
 for question in ['今天累了一天，别讲道理，也别替我安排事情，陪我正常聊两句。','我点了晚饭，还没送到，准备吃完再去洗澡。','明天再弄那份方案吧，我就是这么打算，还没写完。']:
  check_budget();messages.append({'role':'user','content':question});report['model_calls']+=1
  answer=''.join(provider.response('synthetic-production',messages,max_tokens=160))
  flags=bool(re.search(r'\[(?:smirk|wink|grin|emotion)|喵|小主人|乖乖|小尾巴|\*[^*]+\*',answer,re.I))
  report['dialogues'].append({'persona':persona_id,'user':question,'assistant':answer,'invalid_style_flag':flags})
  messages.append({'role':'assistant','content':answer})
  assert answer and not flags,'production_dialogue_style_failed'
provider.client.close()
report.update(model=llm['model_name'],temperature=llm['temperature'],actual_mcp_executions=len(report['native_mcp']),model_calls=9,secondary_rewrite=False,hardware_writes=0)
path=OUT/('candidate-runtime-acceptance.json' if report['candidate_runtime'] else 'production-acceptance.json')
path.write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps({'actual_mcp_executions':report['actual_mcp_executions'],'model_calls':report['model_calls'],'dialogues':report['dialogues']},ensure_ascii=False))
