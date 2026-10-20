import os
os.environ['TEST_PHASE']='final'
import bootstrap,asyncio,json,copy,time,re,traceback
from bootstrap import stage,budget,production_provider
from wire_conversation import WireConversation
from core.utils.reminder_interaction import close_interaction,open_interaction
out=stage/'supplement01-results.jsonl';assert not out.exists()
async def run(w,label,query,expect=None,state=None):
 charge=budget.reserve('case','supplement01:'+label)
 try:
  r=await w.turn(query);assert r['speech'] and not r['outcome']['error']
  results=r['outcome']['results']
  if expect:
   assert any(x['tool']==expect and x['state'] in {'completed','accepted'} for x in results),(expect,results)
  else:
   from core.utils.tool_harness.contracts import contract
   assert not any(contract(x['tool']).write for x in results),'query_or_hypothesis_wrote'
  if state:assert state(r),'incorrect_persisted_state_or_reply'
  r.update(label=label,passed=True)
 except Exception as exc:
  r=locals().get('r',{});r.update(label=label,query=query,passed=False,error=repr(exc),trace=traceback.format_exc()[-2000:])
 budget.finish(charge,{'passed':r['passed']})
 with out.open('a') as f:f.write(json.dumps(r,ensure_ascii=False,default=str)+'\n')
 print(json.dumps({k:r.get(k) for k in ['label','query','speech','passed','error']},ensure_ascii=False),flush=True)
 if not r['passed']:raise RuntimeError('supplement_failure_preserved')
 return r
async def main():
 p,cfg=production_provider();w=await WireConversation().setup(p,cfg);close_interaction(w.c);w.device.state['card']['active']=False;w.device.save()
 try:
  await run(w,'hypothesis','假如我妻子说她不爱喝咖啡，那只是举例，不是我的偏好，也不要保存。',state=lambda r:not re.search('你不爱喝|你不喜欢咖啡',r['speech']))
  await run(w,'correction','你理解错了，我说的是我妻子的假设，不是我。直接回应，别逗我，也别反问。',state=lambda r:not re.search('嘿嘿|哈哈|坏笑|笨蛋|[？?]',r['speech']))
 finally:await w.close();p.client.close()
 p,cfg=production_provider();w=await WireConversation().setup(p,cfg);close_interaction(w.c);w.device.state['card']['active']=False;w.device.state['enrollment']={'state':'idle','accepted_count':0,'required_frames':3};w.device.save()
 try:
  await run(w,'face_start','现在开始人脸录入。','camera_face_enroll_start',lambda r:r['state']['enrollment']['state']=='capturing' and not re.search('已.{0,3}(?:录入完成|入库|采集完成)',r['speech']))
  w.device.state['enrollment'].update(state='idle',terminal_state='failed',last_error_code='capture_failed');w.device.save()
  await asyncio.sleep(2.3)
  await run(w,'face_retry','刚才没拍到，重新开始录入人脸。','camera_face_enroll_start',lambda r:r['state']['enrollment']['state']=='capturing')
 finally:
  task=getattr(w.c,'_face_enrollment_monitor',None)
  if task:task.cancel()
  await w.close();p.client.close()
 p,cfg=production_provider();w=await WireConversation().setup(p,cfg)
 w.device.state['card'].update(source_type='alarm',instance_id='sim-alarm',revision=2,title='起床',status='ringing',primary_action='停止');w.device.save()
 open_interaction(w.c,instance_id='sim-alarm',revision=2,expires_at=int(time.time())+90)
 try:
  await run(w,'alarm_stop','把正在响的闹钟关了吧。','alarm_dismiss',lambda r:not r['state']['alarm_ringing'])
  await run(w,'chat_after_alarm','好了，接着正常聊天。用一句话说说雨后的空气，不用再提闹钟。',state=lambda r:not re.search('闹钟|没声音|先说到这里',r['speech']))
 finally:await w.close();p.client.close()
 print(budget.report(),flush=True)
asyncio.run(main())
