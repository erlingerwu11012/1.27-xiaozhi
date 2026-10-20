import bootstrap,asyncio,json
from bootstrap import budget,production_provider,stage
from core.utils.tool_harness.models import Step
from pydantic import ValidationError
from test_support import connection
from stateful_device import StatefulDevice
from wire_conversation import WireConversation
async def main():
 budget.reserve('case','strict-relative-reject-boolean')
 try:Step.model_validate({'id':'a','tool':'self_screen_set_brightness','relative':True});raise AssertionError('boolean_accepted')
 except ValidationError:pass
 budget.reserve('case','explicit-relative-replaces-malformed-model-value')
 c,m,h=connection(StatefulDevice(),lambda _:{'mode':'operate','steps':[{'id':'a','tool':'self_get_device_status','arguments':{}},{'id':'b','tool':'self_screen_set_brightness','arguments':{'brightness':-1},'relative':True,'depends_on':['a']}]})
 out=await h.run('屏幕太刺眼，帮我往下调一档',[]);assert m.state['level']==2,(out,m.calls);assert out.repairs==0
 p,cfg=production_provider();w=await WireConversation().setup(p,cfg);rows=[]
 try:
  for q,decision,forbid in [('随便聊聊，也别老反问',{'mode':'chat','reply':'那就聊两句。你现在在忙什么？'},True),('你可以问我了',{'mode':'chat','reply':'今天在读什么书？'},False),('给我设个闹钟',{'mode':'clarify','reply':'需要几点响？'},False)]:
   budget.reserve('case','explicit-chat-preference-and-necessary-clarification');w.c._full_tool_harness.decide=lambda _,d=decision:d;r=await w.turn(q,noise=True);assert ('？' not in r['speech']) if forbid else ('？' in r['speech']),r;rows.append(r)
 finally:await w.close()
 (stage/'relative-feedback-final-check.json').write_text(json.dumps({'passed':True,'cases':5,'rows':rows,'hardware':False},ensure_ascii=False));print('strict relative and feedback PASS',budget.report())
asyncio.run(main())
