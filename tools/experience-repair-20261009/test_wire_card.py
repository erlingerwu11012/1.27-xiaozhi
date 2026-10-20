import bootstrap,asyncio,json
from bootstrap import stage,budget
from wire_conversation import WireConversation
from test_support import decision,step
class Fake:
 last_usage={}
 def decision(self,msgs):
  context=json.loads(msgs[-1]['content'].split('[本轮可信目录与执行状态]\n')[-1]);print('active_card',context.get('active_card'))
  return decision(step('reminder_get_current'))
async def main():
 cfg=json.load(open('/root/prjs/tmp/harness-20261007/private-backup/runtime-config.json'));w=await WireConversation().setup(Fake(),cfg)
 try:
  budget.reserve('case','wire-current-card-real-executor');r=await w.turn('当前提醒是什么');print(json.dumps(r,ensure_ascii=False,default=str))
 finally:await w.close()
asyncio.run(main())
