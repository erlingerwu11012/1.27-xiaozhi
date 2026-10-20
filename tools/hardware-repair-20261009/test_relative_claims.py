import bootstrap,asyncio,json
from bootstrap import stage,budget
from core.utils.tool_harness.runtime import Harness,relative_requirements
from wire_conversation import WireConversation
from wire_smoke import Fake
rows=[]
for q,wanted in [('声音比现在低十个点就行',-10),('音量比当前高五个点',5),('声音比原来的小二十个点',-20),('把声音往下调十个点',-10)]:
 budget.reserve('case','relative-constraints:'+q);rows.append({'query':q,'passed':relative_requirements(q).get('self_audio_speaker_set_volume')==wanted})
for text,wanted in [('看旧照片会激活当时的情境记忆，让人感慨时光早已无法重来。',False),('记忆中的环境早已改变，看到旧照片会怀念。',False),('闹钟设好啦。',True),('亮度已经调到四档了。',True),('卡片已经关闭了。',True),('我先不标记完成，等你收到货。',False),('我已经帮你设好了。',True),('还没收到完成回执，不能说闹钟已经设好。',False)]:
 budget.reserve('case','claim-scope:'+text);rows.append({'speech':text,'passed':Harness.claims_action(text)==wanted})
budget.reserve('case','relative-one-level');rows.append({'passed':relative_requirements('屏幕再亮一档吧').get('self_screen_set_brightness')==1})
async def main():
 cfg=json.load(open('/root/prjs/tmp/harness-20261007/private-backup/runtime-config.json'));p=Fake();w=await WireConversation().setup(p,cfg)
 try:
  count=[0]
  def plan(m):
   count[0]+=1
   if count[0]==1:return {'mode':'operate','finished':False,'steps':[{'id':'a','tool':'self_get_device_status','arguments':{}}]}
   return {'mode':'operate','steps':[{'id':'a','tool':'self_get_device_status','arguments':{}},{'id':'b','tool':'self_audio_speaker_set_volume','arguments':{'volume':{'$ref':{'step':'a','path':'volume'}}},'depends_on':['a']}]}
  p.plan=plan;budget.reserve('case','relative-wire-bad-model-ref');r=await w.turn('声音比现在低十个点就行',noise=True);rows.append({'speech':r['speech'],'passed':r['state']['volume']==40 and sum(x['tool']=='self_audio_speaker_set_volume' for x in r['calls'])==1})
  p.plan=lambda m:{'mode':'chat','reply':'看旧照片会激活当时的情境记忆，让人感慨时光早已无法重来。'}
  budget.reserve('case','chat-wire-old-photo');r=await w.turn('别逗了，认真回答为什么看旧照片会感慨。',noise=True);rows.append({'speech':r['speech'],'passed':'旧照片' in r['speech'] and '没有执行操作' not in r['speech'] and r['assistant_history']==[r['speech']]})
 finally:await w.close()
 summary={'tests':len(rows),'passed':all(x['passed'] for x in rows),'rows':rows};(stage/'relative-claims-regression.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2));print(json.dumps(summary,ensure_ascii=False));assert summary['passed']
asyncio.run(main())
