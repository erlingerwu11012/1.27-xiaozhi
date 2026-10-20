import bootstrap,asyncio,json,copy
from bootstrap import stage,budget,production_provider
from wire_conversation import WireConversation
from stateful_device import StatefulDevice
from test_support import connection,decision,step
from core.utils.tool_harness.runtime import card_intent
from core.utils.tool_harness.contracts import receipt
from core.utils.tool_harness.presentation import safe_speech
from plugins_func.register import Action,ActionResponse
async def main():
 for q,action in [('现在这条不用提醒了，明天的别动','tertiary'),('这次跳过，别删除以后提醒','tertiary'),('再过十分钟提醒我当前这件事','secondary')]:
  budget.reserve('case','card-action-original-constraint');assert card_intent(q)['action']==action
  args={'instance_id':'sim-card','revision':2,'action':action,'minutes':10 if action=='secondary' else 0,'snooze_at':0}
  bad=decision(step('note_add',{'text':'喝水','remind_at':0}));good=decision(step('reminder_action',args));ds=iter([bad,good]);c,m,h=connection(StatefulDevice(),lambda _:next(ds))
  from core.utils.reminder_interaction import open_interaction
  import time
  open_interaction(c,instance_id='sim-card',revision=2,expires_at=int(time.time())+180)
  out=await h.run(q,[]);assert out.results[-1].state=='completed',(q,out);assert m.state['card']['last_action']==action;assert not m.state['notes']
 for raw in ["{'ok': False, 'errorCode': 'vision_not_ready', 'message': '视觉服务尚未就绪'}",{'ok':False,'error':{'raw':'secret'},'errorCode':'vision_not_ready'}]:
  budget.reserve('case','no-raw-error-speech');x=receipt('self_camera_take_photo',{},ActionResponse(Action.REQLLM,result=raw),'c');assert x.state=='failed';assert '尚未就绪' in x.reply;assert '{' not in x.reply
 budget.reserve('case','raw-python-repr-exit');assert '{' not in safe_speech("{'bad': 1}")
 print('card/errors injected PASS',budget.report())
asyncio.run(main())
