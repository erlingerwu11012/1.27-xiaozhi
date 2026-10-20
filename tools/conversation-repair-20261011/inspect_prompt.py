import bootstrap,asyncio,json,re
from bootstrap import stage,budget
from wire_conversation import WireConversation
class Fake:
 last_usage=None
 def decision(self,m):
  print('PROMPT',[(x['role'],len(str(x.get('content','')))) for x in m])
  for x in m:
   s=str(x.get('content',''))
   for term in ['behavior_log','tool_calls','唯一决策','task_action']:
    hits=[s[max(0,a.start()-65):a.end()+100] for a in re.finditer(re.escape(term),s)]
    if hits:print(term,json.dumps(hits,ensure_ascii=False))
  return {'mode':'clarify','reply':'想在什么时候提醒？'}
async def main():
 cfg=json.load(open('/root/prjs/tmp/harness-20261007/private-backup/runtime-config.json'));w=await WireConversation().setup(Fake(),cfg)
 budget.reserve('case','prompt-conflict-inspection')
 from core.utils.reminder_interaction import close_interaction
 close_interaction(w.c);w.device.state['card']['active']=False;w.device.save()
 print(await w.turn('给我设个公共提醒，内容是吃饭'))
 await w.close()
asyncio.run(main())
