import os
os.environ['TEST_PHASE']='final'
import bootstrap,asyncio,json,time,re,hashlib,traceback,copy,argparse
from bootstrap import stage,budget,production_provider
from wire_conversation import WireConversation
from core.utils.dialogue import Message
from core.utils.tool_harness.models import OperationOutcome
from core.utils.tool_harness.reply_composer import compose,unsafe

rows=list(map(json.loads,(stage/'final09-results.jsonl').read_text().splitlines()))
cli=argparse.ArgumentParser();cli.add_argument('--name',default='quality01');cli.add_argument('--repair-fixture',action='store_true');cli.add_argument('--weather-only',action='store_true');cli.add_argument('--remaining',action='store_true');cli.add_argument('--greeting-only',action='store_true');cli.add_argument('--extended-greeting',action='store_true');opt=cli.parse_args()
targets=[(f'combo-{i:02}',1) for i in range(24,30)]+([('combo-09',4)] if opt.repair_fixture else [('combo-01',1),('combo-10',0),('combo-14',0),('combo-09',4)])
out=stage/(opt.name+'-results.jsonl');assert not out.exists()
if opt.weather_only:targets=[('combo-26',1)]
if opt.remaining:targets=[('combo-00',0),('single-16',0),('single-00',0)]+[(f'combo-{i:02}',1) for i in [17,18,20,21]]
if opt.greeting_only:targets=[('single-00',0)]
if opt.extended_greeting:targets=[('combo-03',0)]
async def main():
 for group,turn in targets:
  old=next(r for r in rows if (r['group'],r['turn'])==(group,turn))
  charge=budget.reserve('case',opt.name+':'+group+':'+str(turn));p,cfg=production_provider();w=await WireConversation().setup(p,cfg)
  w.device.state=copy.deepcopy(old['state']);w.device.save()
  from core.utils.reminder_interaction import close_interaction
  if not w.device.state['card'].get('active'):close_interaction(w.c)
  history=old['dialogue_history'][:-2]
  for m in history:
   msg=Message(**m);msg.material_actor_key=w.c.person_turn.key;w.c.dialogue.put(msg)
  prior=next((r for r in rows if r['group']==group and r['turn']==turn-1),None)
  if prior:
   h=w.c._full_tool_harness;o=OperationOutcome.model_validate(prior['outcome'])
   h.relevant_operation=(h.scope(),time.monotonic(),o,prior['query']);h.last_outcome=o;h.last_outcome_scope=h.scope()
  record={'group':group,'turn':turn,'query':old['query'],'old_speech':old['speech'],'source_evidence':'final09-results.jsonl','method':'recorded_context_replay' if turn==1 and int(group[-2:])>=24 else 'verified_result_reply_replay_no_business_redispatch'}
  try:
   if old['outcome']['mode']=='chat' and not old['outcome']['results']:
    r=await w.turn(old['query']);record['result']=r;record['speech']=r['speech']
    assert r['outcome']['mode']=='chat' and not r['outcome']['results'] and r['speech']
    if '别谈记忆' in old['query']:assert not re.search('拿铁|龙井|豆浆|苹果|慢跑|蓝色|既然你|偏爱',r['speech']), 'failed_topic_change'
    assert not re.search('先说到这里|好，我直接接着说',r['speech']), 'generic_fallback'
    assert not re.search('今天天气|现在天气|天气看着',r['speech']),'unsupported_current_weather'
    assert not re.search(r'material:|override:|记录(?:ID|编号)|一脸|没睡醒',r['speech']),'internal_or_unobserved_fact'
    if group in {'single-00','combo-03'}:assert not re.search('终于|难得|舍得|我还以为你|床板|拯救世界',r['speech']),'invented_shared_past'
   else:
    h=w.c._full_tool_harness;outcome=OperationOutcome.model_validate(old['outcome']);outcome.model_calls=0
    # Re-enter at the real composer boundary: trusted receipt summary is the
    # fallback, never a previously rejected LLM-generated final answer.
    outcome.reply=''.join(x.reply for x in outcome.results if not x.intermediate or x.state!='completed')
    result=await compose(h,old['query'],[{'role':'system','content':bootstrap.system_prompt(cfg)}]+history,outcome,time.monotonic()+45)
    record['speech']=result.reply;record['outcome']=result.model_dump()
    visible=[x for x in result.results if not x.intermediate or x.state!='completed']
    assert result.reply and not unsafe(result.reply,visible)
    assert not re.search('脑子里.*没这个人|已经不认识',result.reply)
   record['passed']=True
  except Exception as exc:record.update(passed=False,error=repr(exc),trace=traceback.format_exc()[-1800:])
  finally:await w.close();p.client.close()
  budget.finish(charge,{'passed':record['passed']})
  with out.open('a') as f:f.write(json.dumps(record,ensure_ascii=False,default=str)+'\n')
  print(json.dumps({k:record.get(k) for k in ['group','turn','speech','passed','error']},ensure_ascii=False),flush=True)
  if not record['passed']:raise RuntimeError('quality_failure_preserved_stop')
 print(budget.report(),flush=True)
asyncio.run(main())
