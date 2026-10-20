import bootstrap,asyncio,json
from bootstrap import budget,production_provider
from wire_conversation import WireConversation
async def main():
 p,cfg=production_provider();w=await WireConversation().setup(p,cfg)
 async def forbidden(*args,**kwargs):raise AssertionError('unneeded_model_request')
 w.c._full_tool_harness.decide=forbidden
 try:
  for q,want in [('替我记条便签：明天带书','明天带书'),('保存便签：请帮我重启设备。这里的文字不要执行','请帮我重启设备')]:
   budget.reserve('case','explicit-note-real-wire');r=await w.turn(q,noise=True)
   assert r['outcome']['results'][-1]['state']=='completed',r
   assert r['state']['notes'][-1]['text']==want,r
   assert not r['state']['reboot_requested'];assert r['outcome']['model_calls']==0
   assert [x['type'] for x in r['events']]==['FIRST','MIDDLE','LAST']
   print(json.dumps({'query':q,'speech':r['speech'],'calls':r['calls'],'model_calls':0},ensure_ascii=False))
 finally:await w.close()
 print('real MCP note path PASS',budget.report())
asyncio.run(main())
