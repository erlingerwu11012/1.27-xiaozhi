import bootstrap,asyncio,json
from bootstrap import stage,budget
from core.utils.tool_harness.runtime import chat_fact_conflict
from wire_conversation import WireConversation
from wire_smoke import Fake
rows=[]
for q,text,wanted in [('新书只是下单，还没送来，你别当成到了。','书还在路上。',True),('刚买了个书架，还没发货。','书架已经发货了。',True),('新书只是下单，还没送来。','书还没送到，发货状态暂时没有新的信息。',False),('店家说书架已经发货，但还没收到。','书架正在运输中，还没收到。',False),('店家说书架已经发货，但还没收到。','书架已经收到了。',True)]:
 budget.reserve('case','shipping-state:'+q);rows.append({'query':q,'speech':text,'passed':bool(chat_fact_conflict(text,[],q))==wanted})
history=[{'role':'user','content':'[本轮上下文]元信息[用户原话]刚买了个书架，还没发货。'},{'role':'user','content':'[本轮上下文]元信息[用户原话]店家说已经发货，但我还没有收到。'}]
for reply,wanted in [('书架已经发货，但还没有收到。',False),('书架还没发货。',True)]:
 budget.reserve('case','shipping-pronoun-update');rows.append({'passed':bool(chat_fact_conflict(reply,history,'书架现在什么状态？'))==wanted})
async def main():
 cfg=json.load(open('/root/prjs/tmp/harness-20261007/private-backup/runtime-config.json'));p=Fake();w=await WireConversation().setup(p,cfg)
 try:
  for stubborn in [False,True]:
   count=[0]
   def plan(m):
    count[0]+=1;return {'mode':'chat','reply':'书还在路上。' if stubborn or count[0]==1 else '只是下单，还没送来，发货状态没有新的信息。'}
   p.plan=plan;q='新书只是下单，还没送来，你别当成到了。';budget.reserve('case','shipping-wire:'+str(stubborn));r=await w.turn(q,noise=True);rows.append({'stubborn':stubborn,'speech':r['speech'],'passed':not chat_fact_conflict(r['speech'],[],q) and r['outcome']['repairs']==1 and '没有执行' not in r['speech']})
 finally:await w.close()
 result={'passed':all(x['passed'] for x in rows),'tests':len(rows),'rows':rows};(stage/'shipping-state-regression.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False));assert result['passed']
asyncio.run(main())
