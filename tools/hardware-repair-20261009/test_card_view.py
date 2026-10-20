import bootstrap,asyncio,json
from bootstrap import stage,budget
from core.utils.tool_harness.reply_composer import status_conflict
from core.utils.tool_harness.models import StepResult
from wire_conversation import WireConversation
from wire_smoke import Fake
rows=[]
for active,text,wanted in [(True,'我这边只能查到提醒事项，没看到关于卡片开关的状态信息。',True),(True,'卡片已经关闭了。',True),(True,'卡片还在显示，提醒你拿快递。',False),(False,'卡片还在显示。',True),(False,'已经没有卡片了。',False)]:
 budget.reserve('case','card-display-facts');r=StepResult(tool='reminder_get_current',state='completed',arguments={},call_id='t',reply='事实',payload={'active':active,'title':'拿快递'});rows.append({'active':active,'text':text,'passed':status_conflict(text,[r],{})==wanted})
async def main():
 cfg=json.load(open('/root/prjs/tmp/harness-20261007/private-backup/runtime-config.json'));p=Fake();w=await WireConversation().setup(p,cfg)
 try:
  for active in [True,False]:
   w.device.state['card']['active']=active;w.device.save();p.plan=lambda m,active=active:{'mode':'chat','reply':'无法确认卡片展示状态。' if active else '卡片还在显示。'};budget.reserve('case','card-display-wire');r=await w.turn('查一下卡片关没关',noise=True);rows.append({'active':active,'speech':r['speech'],'passed':bool(r['speech']) and not status_conflict(r['speech'],[StepResult.model_validate(x) for x in r['outcome']['results']],{}) and ('显示' in r['speech'] if active else '没有' in r['speech']) and r['assistant_history']==[r['speech']]})
 finally:await w.close()
 summary={'tests':len(rows),'passed':all(x['passed'] for x in rows),'rows':rows};(stage/'card-view-regression.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2));print(json.dumps(summary,ensure_ascii=False));assert summary['passed']
asyncio.run(main())
