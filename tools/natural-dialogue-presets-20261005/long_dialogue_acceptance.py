"""Two continuous twelve-turn conversations via production primary model; keep all outputs."""
import json,re,asyncio,subprocess
from pathlib import Path
source=Path(__file__).with_name('runtime_production_acceptance.py').read_text().split('async def runtime_mcp():')[0]
exec(compile(source,'<production-bootstrap>','exec'))
from core.utils.current_time import get_prompt_time_context
from core.utils.turn_context import render_turn_context
node="import {readFileSync} from 'node:fs';let m=await import('data:text/javascript;base64,'+readFileSync(process.argv[1]).toString('base64'));console.log(JSON.stringify(m.PERSONA_PRESETS));"
presets=json.loads(subprocess.run(['node','--input-type=module','-e',node,str(PROD.parent/'manager-web/src/constants/personaPresets.js')],capture_output=True,text=True,check=True).stdout)
profiles=[{'id':'natural','name':'自然朋友完整预设','prompt':presets[0]['prompt']},{'id':'existing-playful','name':'用户截图中的原人格','prompt':PERSONA}]
questions=['今天下午开了两个会，脑子有点木，就想随便聊聊。',
 '你别急着让我休息，也别列清单，我不是来找解决方案的。',
 '刚下单一个咖啡机，周四才发货，现在还没到。',
 '不是已经到了，连快递都还没发。',
 '我昨天只改了报告的标题，正文还差一大半。',
 '别说已经写完了。我只是打开文档改了个标题。',
 '你刚才这句听着太像领导了，正常说话，别教育我。',
 '今天也先别拿我开玩笑，我现在有点烦。',
 '还是换个话题吧。你觉得成年人的朋友为什么越来越难约？',
 '别每句话都反问我。你直接说你的看法就行。',
 '其实我想要的是像朋友那样自然聊，不是被安慰或者被带着安排。',
 '查一下伦敦现在几点。']
result={'source':'production default provider and actual platform prompt assembly','model':llm['model_name'],'temperature':llm['temperature'],'secondary_rewrite':False,'physical_voice_test':False,'nickname':'主人','profiles':[],'primary_calls':0,'actual_mcp_calls':0,'max_primary_calls':30,'all_outputs_preserved':True}
def save(): (OUT/'long-dialogue-acceptance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
async def run():
 settings=json.loads((PROD/'data/.mcp_server_settings.json').read_text())['mcpServers']
 client=ServerMCPClient(next(c for c in settings.values() if not c.get('disabled',False)))
 try:
  await asyncio.wait_for(client.initialize(),20)
  definitions=client.get_available_tools()
  for profile in profiles:
   entry={**profile,'turns':[]};result['profiles'].append(entry)
   prompt=PromptManager({'system_base_prompt':base.get('system_base_prompt',''),'language':'中文'},logger=MagicMock()).build_enhanced_prompt_v2(profile['prompt'],'synthetic-long-dialogue',device_name='小智',user_nickname='主人',official_enhanced=True)
   messages=[{'role':'system','content':prompt}]
   conn=SimpleNamespace(config={'operation_control':{'enabled':True}},session_id='synthetic-long-dialogue',mcp_client=SimpleNamespace(ready=True,closed=False))
   executor=ServerMCPExecutor(conn);executor._initialized=True
   executor.mcp_manager=SimpleNamespace(get_all_tools=lambda:definitions,execute_tool=client.call_tool)
   manager=ToolManager(conn);manager.register_executor(ToolType.SERVER_MCP,executor)
   async def handler(c,call):return await manager.execute_tool(call['name'],json.loads(call['arguments']))
   conn.func_handler=SimpleNamespace(tool_manager=manager,handle_llm_function_call=handler)
   for index,question in enumerate(questions,1):
    check_budget();assert result['primary_calls']<result['max_primary_calls']
    messages.append({'role':'user','content':render_turn_context(get_prompt_time_context())+'\n[用户原话]\n'+question})
    plan=get_control(conn).begin(question,('synthetic','actor'),has_recent_topic=index>1)
    row={'turn':index,'user':question,'tool_events':[]}
    if plan.requests:
     replies,tools=await execute_plan(conn,plan)
     assert not replies and len(tools)==1
     for receipt,call in tools:
      assert call['name']=='get_world_time'
      row['tool_events'].append({'name':call['name'],'arguments':json.loads(call['arguments']),'actual_result':receipt.result,'executed':True})
      messages.append({'role':'assistant','content':None,'tool_calls':[{'id':call['id'],'type':'function','function':{'name':call['name'],'arguments':call['arguments']}}]})
      messages.append({'role':'tool','tool_call_id':call['id'],'content':receipt.result})
      result['actual_mcp_calls']+=1
     result['primary_calls']+=1
     text=''.join(provider.response('synthetic-long-dialogue',messages,max_tokens=260))
    else:
     result['primary_calls']+=1
     completion=provider.client.chat.completions.create(model=llm['model_name'],messages=messages,tools=definitions,tool_choice='auto',max_tokens=260,temperature=0.4,extra_body={'enable_thinking':False,'preserve_thinking':False})
     msg=completion.choices[0].message;text=msg.content or ''
     if msg.tool_calls:
      messages.append(msg.model_dump(exclude_none=True))
      for tc in msg.tool_calls:
       row['tool_events'].append({'name':tc.function.name,'arguments':tc.function.arguments,'executed':False,'reason':'No explicit operation authorized in this synthetic chat turn; no write tool executed.'})
       messages.append({'role':'tool','tool_call_id':tc.id,'content':'本轮是在聊天，没有明确授权这个操作，工具没有执行。请直接接话。'})
      result['primary_calls']+=1;assert result['primary_calls']<=result['max_primary_calls']
      text=''.join(provider.response('synthetic-long-dialogue',messages,max_tokens=260))
    row.update(raw_assistant=text,display_assistant=guard_reply(conn,text))
    row['invalid_style_flag']=bool(re.search(r'\[(?:smirk|wink|grin|emotion)|喵|小主人|乖乖|小尾巴|\*[^*]+\*',text,re.I))
    entry['turns'].append(row);messages.append({'role':'assistant','content':text});save()
    print(json.dumps({'profile':profile['id'],**row},ensure_ascii=False),flush=True)
 finally:await client.cleanup();provider.client.close()
asyncio.run(run())
result['completed']=all(len(p['turns'])==12 for p in result['profiles']);save()
print(json.dumps({'completed':result['completed'],'primary_calls':result['primary_calls'],'actual_mcp_calls':result['actual_mcp_calls']}))
