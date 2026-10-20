import bootstrap,asyncio,json
from bootstrap import budget,stage,production_provider
from wire_conversation import WireConversation
async def main():
 provider,cfg=production_provider();w=await WireConversation().setup(provider,cfg);captures=[]
 def decide(messages):
  content=messages[-1]['content'];context=json.loads(content.split('[本轮可信目录与执行状态]\n',1)[1]);captures.append(context['recent_user_statements']['ordered_oldest_to_newest']);return {'mode':'chat','reply':'收到。'}
 w.c._full_tool_harness.decide=decide
 try:
  from core.utils.reminder_interaction import close_interaction
  close_interaction(w.c);w.device.state['card']['active']=False;w.device.save()
  for q in ['外卖还没到，我还没吃晚饭。','刚收到通知，外卖已经到楼下了，我还没拿。','先不用你提醒我，我知道了。','我现在吃上了吗？']:
   budget.reserve('case','raw-user-context-preserved');await w.turn(q,noise=True)
  assert len(captures[-1])==4,captures;assert '我还没拿' in captures[-1][1];assert all('收到。' not in text for text in captures[-1])
  budget.reserve('case','card-query-converges-on-one-receipt');r=await w.turn('现在还显示什么提醒',noise=True);assert len(r['outcome']['results'])==1;assert r['outcome']['model_calls']==0;assert r['speech']=='当前没有提醒卡片。'
  (stage/'context-preservation-results.json').write_text(json.dumps({'passed':True,'captured_user_statements':captures[-1],'query_result':r,'hardware':False},ensure_ascii=False));print('context and query convergence PASS',budget.report())
 finally:await w.close()
asyncio.run(main())
