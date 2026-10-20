import bootstrap,asyncio,json
from bootstrap import stage,budget,production_provider
from wire_conversation import WireConversation
async def main():
 p,cfg=production_provider()
 original=p.decision
 def spy(messages):
  ctx=json.loads(messages[-1]['content'].split('[本轮可信目录与执行状态]\n')[-1]);print('CARD',json.dumps(ctx.get('active_card'),ensure_ascii=False),flush=True)
  return original(messages)
 p.decision=spy
 for q in ['当前提醒是什么','好，我已经拿完了']:
  w=await WireConversation().setup(p,cfg)
  try:
   budget.reserve('case','card-focus:'+q);r=await w.turn(q);print(json.dumps(r,ensure_ascii=False,default=str),flush=True)
  finally:await w.close()
 print(budget.report())
asyncio.run(main())
