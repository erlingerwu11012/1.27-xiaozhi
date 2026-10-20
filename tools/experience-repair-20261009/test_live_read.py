import bootstrap,asyncio,json
from bootstrap import budget,production_provider,stage
from wire_conversation import WireConversation
from core.utils.tool_harness.runtime import live_read_request
async def main():
 p,cfg=production_provider();w=await WireConversation().setup(p,cfg);rows=[]
 w.c._full_tool_harness.decide=lambda _:(_ for _ in ()).throw(AssertionError('unneeded_paid_request'))
 try:
  for q,t in [('这会儿显示的卡片是什么','reminder_get_current'),('只看现在的亮度，不改设置','self_get_device_status'),('这次别调，我只是确认目前声音多大','self_get_device_status'),('别调音量，帮我看下现在是多少','self_get_device_status'),('眼前这条提醒的内容是啥','reminder_get_current'),('存一条便签：带充电线，不要定时','note_add'),('存一条便签：“不要定时”','note_add')]:
   budget.reserve('case','live-query-note-final-wire');r=await w.turn(q,noise=True);assert r['outcome']['model_calls']==0,r
   matches=[x for x in r['outcome']['results'] if x['tool']==t];assert len(matches)==1 and matches[0]['state']=='completed',r
   assert sum(x['tool']==t for x in r['calls'])==1,r
   assert [e['type'] for e in r['events']]==['FIRST','MIDDLE','LAST'];assert r['assistant_history']==[r['speech']]
   if t=='note_add':assert r['state']['notes'][-1]['text']==('不要定时' if '“' in q else '带充电线')
   rows.append(r)
  for q in ['不要查音量，随便聊','假设我问音量多少，会怎样？','“音量多少”是什么意思','音量多少，然后再调大一点','亮度是多少，再加一档','保存便签：现在音量多少']:
   budget.reserve('case','live-query-no-write-or-quotation');assert live_read_request(q) is None,q
 finally:await w.close()
 (stage/'live-query-note-results.json').write_text(json.dumps({'passed':True,'cases':13,'rows':rows,'hardware':False},ensure_ascii=False));print('live query and note PASS',budget.report())
asyncio.run(main())
