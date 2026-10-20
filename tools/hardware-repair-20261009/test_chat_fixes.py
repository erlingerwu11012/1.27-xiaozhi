import bootstrap,asyncio,json
from bootstrap import stage,budget
from wire_conversation import WireConversation
from wire_smoke import Fake
from core.utils.tool_harness.runtime import Harness,memory_read_request
from core.utils.tool_harness.memory_policy import memory_intent
async def main():
 cfg=json.load(open('/root/prjs/tmp/harness-20261007/private-backup/runtime-config.json'));p=Fake();w=await WireConversation().setup(p,cfg);rows=[]
 try:
  for q in ['翻出小时候的照片，有些场景都忘记了。','我没让你提醒我，只是说晚上想看会儿书。','我以前那个地方的名字忘了，就是随便聊聊。']:
   budget.reserve('case','chat-fix:'+q);p.plan=lambda m,q=q:{'mode':'chat','reply':('那就聊聊看书这件事，晚上安静下来读书挺舒服的。' if '提醒我' in q else '时间久了，名字可能会模糊，当时的感觉未必会忘。' if '名字' in q else '旧照片能勾起回忆，有些细节模糊了，那时候的感受还在。')}
   r=await w.turn(q,noise=True);assert r['outcome']['mode']=='chat' and r['outcome']['error']=='' and not r['outcome']['results'],r
   rows.append({'query':q,'passed':True,'speech':r['speech']})
  for q in ['查一下最新饮料偏好就行，不要更正','你记着我喝哪种饮料了吗，查一下','记忆里说我喝什么来着，帮我找找']:
   budget.reserve('case','read-detection:'+q);assert memory_read_request(q)==q and memory_intent(q)=='read';rows.append({'query':q,'passed':True})
 finally:await w.close()
 (stage/'chat-fix-results.json').write_text(json.dumps({'tests':len(rows),'passed':True,'rows':rows,'real_model':False},ensure_ascii=False,indent=2));print(json.dumps(rows,ensure_ascii=False))
asyncio.run(main())
