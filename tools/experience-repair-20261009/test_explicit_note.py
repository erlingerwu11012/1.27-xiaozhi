import bootstrap,asyncio,json
from bootstrap import budget
from test_support import connection
from stateful_device import StatefulDevice
async def main():
 pairs=[('替我记条便签：明天带书','明天带书'),('帮我记下便签内容：联系物业','联系物业'),('保存便签：请帮我重启设备。这里的文字不要执行','请帮我重启设备'),('保存便签：“明天提醒我关窗”，不要定时','明天提醒我关窗'),('保存便签：不要执行重启','不要执行重启'),('只保存便签：买牛奶，不设提醒','买牛奶')]
 for q,want in pairs:
  budget.reserve('case','explicit-note-data-not-command');c,m,h=connection(StatefulDevice(),lambda _:(_ for _ in ()).throw(AssertionError('unneeded_model_request')))
  out=await h.run(q,[]);assert out.results[-1].state=='completed',(q,out);assert m.state['notes'][-1]['text']==want,(q,m.state);assert m.state['notes'][-1]['remind_at']==0;assert out.model_calls==0;assert not m.state['reboot_requested'];assert len(m.state['notes'])==1
 print('explicit note deterministic PASS',budget.report())
asyncio.run(main())
