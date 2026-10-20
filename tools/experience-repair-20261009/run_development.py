import bootstrap,asyncio,json,sys
from bootstrap import stage,budget,production_provider
from wire_conversation import WireConversation
async def main():
 provider,cfg=production_provider();w=await WireConversation().setup(provider,cfg)
 cases=['嘿，你好呀','亮度弄到百分之九十','声音调到最大','声音小十个点','给我设一个晚上十点的闹钟','刚才那个提醒是什么来着','好，我已经拿完了','先别开玩笑，今天有点累，别给我安排事情']
 try:
  with (stage/'development-model.jsonl').open('a') as f:
   for query in cases:
    budget.reserve('case','development-real:'+query);r=await w.turn(query,noise=True);f.write(json.dumps(r,ensure_ascii=False,default=str)+'\n');f.flush();print(json.dumps({'query':query,'speech':r['speech'],'states':[(s['tool'],s['state'],s['error']) for s in r['outcome']['results']]},ensure_ascii=False),flush=True)
 finally:await w.close()
 print(budget.report())
asyncio.run(main())
