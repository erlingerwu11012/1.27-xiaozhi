"""Fresh held-out dialogue and native-call/MCP execution acceptance, no device writes."""
from pathlib import Path
bootstrap=Path(__file__).with_name('live_prompt_acceptance.py').read_text().split('training=')[0]
bootstrap=bootstrap.replace("OUT/'live-prompt-acceptance.json'", "OUT/'final-acceptance.json'")
exec(compile(bootstrap, '<candidate-bootstrap>', 'exec'))
report['round']=2
report['validation_policy']='New dialogue phrasing; preserve exploratory round one; no post-hoc exclusion.'
scenes=[
 ('缺少截止时间',['这篇稿子还没写，我今天一直在摸鱼。','不要劝我努力，我就是抱怨一句。','你说今晚写还是明天写？']),
 ('尚未发生',['新买的书周三才送来，我打算放在窗边。','不是已经送到了，你别替我脑补。']),
 ('反馈收住',['我想周末把阳台那些东西理一理。','先别安排，也别跟我开玩笑，正常说话就行。']),
 ('成年人故事',['给我讲个短故事，听众是成年人，不用哄小孩。']),
 ('简洁事实',['17乘23是多少？直接告诉我结果。']),
]
for preset in presets:
 for title,inputs in scenes:scene('qwen3.8-flash',preset,title,inputs,'heldout_scenarios')

import asyncio
from core.providers.tools.server_mcp.mcp_client import ServerMCPClient
async def mcp_acceptance():
 configs=json.loads((PROD/'data/.mcp_server_settings.json').read_text())['mcpServers']
 mcp=ServerMCPClient(next(c for c in configs.values() if not c.get('disabled',False)))
 try:
  await asyncio.wait_for(mcp.initialize(),20)
  available=mcp.get_available_tools()
  selected=[t for t in available if t['function']['name']=='get_world_time']
  assert len(selected)==1,'live_time_tool_missing'
  for preset in (presets[0],presets[4],presets[-1]):
   messages=[{'role':'system','content':build(preset['prompt'])},user('帮我查一下东京现在几点，用工具查。')]
   kwargs=dict(model='qwen3.8-flash',messages=messages,tools=selected,tool_choice='auto',temperature=0.7,max_tokens=220,extra_body={'enable_thinking':False,'preserve_thinking':False})
   report['calls']+=1
   response=client.chat.completions.create(**kwargs)
   message=response.choices[0].message
   assert len(message.tool_calls or [])==1,'time_native_call_missing'
   tc=message.tool_calls[0]
   assert tc.function.name=='get_world_time'
   args=json.loads(tc.function.arguments)
   result=await asyncio.wait_for(mcp.call_tool(tc.function.name,args),20)
   assert not getattr(result,'isError',False),'mcp_execution_failed'
   public_result=result.model_dump(mode='json')
   messages.append(message.model_dump(exclude_none=True))
   messages.append({'role':'tool','tool_call_id':tc.id,'content':json.dumps(public_result,ensure_ascii=False)})
   final=call('qwen3.8-flash',messages,selected)
   assert not final.get('error') and not final['tool_calls'] and final['assistant'],'time_final_reply_missing'
   report['tool_probes'].append({'preset':preset['id'],'actual_mcp_execution':True,'name':tc.function.name,'arguments':args,'result':public_result,**final})
   report['native_tool_calls_executed']+=1;save()
 finally:await mcp.cleanup()
asyncio.run(mcp_acceptance())
print(json.dumps({'completed':True,'calls':report['calls'],'actual_mcp_executions':report['native_tool_calls_executed']},ensure_ascii=False))
