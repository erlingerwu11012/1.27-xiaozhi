import bootstrap,json,asyncio
from bootstrap import stage,budget
from core.utils.tool_harness.runtime import Harness,live_read_request,chat_fact_conflict
from wire_conversation import WireConversation
from wire_smoke import Fake
rows=[]
for q,t in [('查一下屏幕卡片现在是不是已经关闭了','reminder_get_current'),('查一下卡片关没关','reminder_get_current'),('这会儿提醒卡片是不是还在显示','reminder_get_current'),('把卡片关掉',None),('查一下卡片，然后关闭',None)]:
 budget.reserve('case','card-query-scope:'+q);actual=live_read_request(q);writes=Harness.write_targets(q);rows.append({'query':q,'actual':actual,'passed':actual==t and (t is None or not writes)})
messages=[{'role':'user','content':'报告上周写好一半，昨天只改了标题。'}]
for text,wanted in [('已经完成了大半。',True),('报告完成了一半。',False),('报告还没写完，不过已经完成大半。',True),('不是大半，是一半。',False),('上周进度主要停留在标题修改上。',True),('上周完成了一半，昨天改了标题。',False)]:
 budget.reserve('case','chat-fraction:'+text);rows.append({'speech':text,'passed':bool(chat_fact_conflict(text,messages,messages[0]['content']))==wanted})
async def main():
 cfg=json.load(open('/root/prjs/tmp/harness-20261007/private-backup/runtime-config.json'));p=Fake();w=await WireConversation().setup(p,cfg)
 try:
  for stubborn in [False,True]:
   count=[0]
   def plan(m):
    count[0]+=1;return {'mode':'chat','reply':'报告已经完成了大半。' if stubborn or count[0]==1 else '上周写好了一半正文，昨天只改了标题。'}
   p.plan=plan;budget.reserve('case','chat-fraction-wire:'+str(stubborn));r=await w.turn(messages[0]['content'],noise=True);rows.append({'stubborn':stubborn,'speech':r['speech'],'repairs':r['outcome']['repairs'],'passed':not chat_fact_conflict(r['speech'],messages,messages[0]['content']) and r['outcome']['repairs']==1 and r['assistant_history']==[r['speech']]})
 finally:await w.close()
 summary={'tests':len(rows),'passed':all(x['passed'] for x in rows),'rows':rows};(stage/'card-progress-regression.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2));print(json.dumps(summary,ensure_ascii=False));assert summary['passed']
asyncio.run(main())
