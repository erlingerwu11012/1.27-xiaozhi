import bootstrap,asyncio,json
from bootstrap import budget,production_provider,stage
from wire_conversation import WireConversation
async def main():
 p,cfg=production_provider();w=await WireConversation().setup(p,cfg);rows=[]
 try:
  budget.reserve('case','pure-list-default-authority')
  w.c._full_tool_harness.decide=lambda _:{'mode':'operate','steps':[{'id':'a','tool':'note_list','arguments':{}}],'finished':False}
  r=await w.turn('之前设的喝水提醒还在吧，查一下便签',noise=True);assert r['outcome']['results'][-1]['state']=='completed' and r['outcome']['model_calls']==1,r;assert not any(x['tool']=='note_add' for x in r['calls']);rows.append(r)
  budget.reserve('case','repair-may-reread-but-only-one-write')
  def plan(path):return {'mode':'operate','steps':[{'id':'1','tool':'reminder_get_current','arguments':{}},{'id':'2','tool':'reminder_action','arguments':{'instance_id':{'$ref':{'step':'1','path':path+'instance_id'}},'revision':{'$ref':{'step':'1','path':path+'revision'}},'action':'primary'},'depends_on':['1']}]}
  seq=iter([plan('result.'),plan('')]);w.c._full_tool_harness.decide=lambda _:next(seq)
  r=await w.turn('这件事做完了，标记当前提醒完成',noise=True);assert not r['state']['card']['active'],r;assert r['outcome']['repairs']==1,r;assert sum(x['tool']=='reminder_action' for x in r['calls'])==1,r;assert r['speech']=='本次提醒已确认完成。',r;rows.append(r)
 finally:await w.close()
 (stage/'read-repair-final-check.json').write_text(json.dumps({'passed':True,'cases':2,'rows':rows,'hardware':False},ensure_ascii=False));print('read normalization and repair PASS',budget.report())
asyncio.run(main())
