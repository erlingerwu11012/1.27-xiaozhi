"""Audited catalog workflows through real Harness, isolated API and loopback MCP."""
import argparse,os
cli=argparse.ArgumentParser();cli.add_argument('--name',required=True);cli.add_argument('--phase',default='development');cli.add_argument('--tools',default='');cli.add_argument('--faults',action='store_true');cli.add_argument('--replay',action='store_true');opt=cli.parse_args()
os.environ['TEST_PHASE']=opt.phase
import bootstrap,asyncio,json,copy,time
from bootstrap import stage,budget,production_provider
from wire_conversation import WireConversation
from test_support import PACK
from core.utils.tool_harness.registry import manifest
from core.utils.tool_harness.contracts import contract,receipt
from core.utils.person_identity import activate,deactivate
from core.utils.reminder_interaction import close_interaction
from plugins_func.register import Action,ActionResponse

REPORT=stage/(opt.name+'-tools.jsonl');assert not REPORT.exists()
EXTRA={'memory_add':{'query':'记一下，我喜欢咖啡','arguments':{'fact':'喜欢咖啡'}},'reminder_close_current':{'query':'只关闭当前提醒卡片，事项保留','arguments':{'instance_id':'sim-card','revision':2}},'get_weather':{'query':'查询杭州现在的天气','arguments':{'location':'杭州','lang':'zh_CN'}},'get_news_from_newsnow':{'query':'查询澎湃新闻最新消息','arguments':{'source':'澎湃新闻','lang':'zh_CN'}}}

def workflow_provider(name):
 provider,cfg=production_provider()
 if not opt.replay:return provider,cfg
 from collections import deque
 from core.utils.tool_harness.stream_decision import ReplyStream
 from core.utils.tool_harness.models import Decision
 records=[];clarifications=[]
 for source in ('tools-final16',):
  for line in (stage/(source+'-tools.jsonl')).read_text().splitlines():
   row=json.loads(line)
   if row.get('tool')!=name or row.get('errors'):continue
   if row.get('mode')=='clarification':clarifications.extend(row.get('decisions',[]))
   if row.get('mode')=='real_model_workflow':records=clarifications+row.get('decisions',[])
 plans=deque(copy.deepcopy(r['decision']) for r in records if r.get('decision'))
 assert plans,('missing_recorded_plan',name)
 class Replay:
  last_usage=None
  def __getattr__(self,key):return getattr(provider,key)
  def decision_stream(self,messages,on_reply=None,admit_reply=None):
   if not plans:raise RuntimeError('recorded_decisions_exhausted_no_paid_fallback')
   value=plans.popleft();value={k:v for k,v in value.items() if k!='reply'}|{'reply':value.get('reply','')}
   def admit(meta):
    try:d=Decision.model_validate(dict(meta,reply='待确认'))
    except Exception:return False
    return d.mode in {'chat','clarify'} and not d.steps and not d.authorized_writes and (admit_reply is None or admit_reply(d))
   parser=ReplyStream(on_reply,admit);raw=json.dumps(value,ensure_ascii=False)
   for i in range(0,len(raw),7):parser.feed(raw[i:i+7])
   return parser.finish()
  def decision(self,messages):return self.decision_stream(messages)
 return Replay(),cfg
def write(row):
 with REPORT.open('a') as f:f.write(json.dumps(row,ensure_ascii=False,default=str)+'\n')
 print(json.dumps({k:v for k,v in row.items() if k in {'tool','mode','errors','speech','availability'}},ensure_ascii=False),flush=True)

async def main():
 provider,cfg=production_provider();w=await WireConversation().setup(provider,cfg)
 catalog=manifest(w.c.func_handler.tool_manager)
 (stage/(opt.name+'-manifest.json')).write_text(json.dumps(catalog,ensure_ascii=False,indent=2))
 names=[r['name'] for r in catalog if r['availability']=='available']
 await w.close();provider.client.close()
 wanted=set(opt.tools.split(',')) if opt.tools else set(names)
 for row in catalog:
  if row['availability']!='available':write({'tool':row['name'],'availability':row['availability'],'errors':[]})
 for name in names:
  if name not in wanted:continue
  charge=budget.reserve('case',opt.name+':'+name);provider,cfg=workflow_provider(name);w=await WireConversation().setup(provider,cfg)
  try:
   fixture=copy.deepcopy(EXTRA.get(name) or PACK['fixtures'][name]);args=fixture['arguments']
   w.device.state['notes']=[{'text':'测试便签','remind_at':0}]
   w.device.state['alarms']=[{'hour':22,'minute':0,'repeat_days':0,'label':'闹钟'}]
   w.device.state['habits']=[{'description':'喝水','hour':18,'minute':0}]
   if not name.startswith('reminder_'):close_interaction(w.c);w.device.state['card']['active']=False
   w.device.save()
   if name in {'memory_correct','memory_forget','memory_search','memory_add'}:
    from core.utils.recent_memory import add,search,override
    token=activate(w.c,w.c.person_turn)
    try:
     cleanup=budget.reserve('case',opt.name+':memory-isolated-cleanup:'+name)
     cleared=await override(w.c,'forget','*');budget.finish(cleanup,{'status':cleared.get('status'),'local_applied':cleared.get('local_applied')})
     if name!='memory_add':
      setup=budget.reserve('case',opt.name+':memory-setup:'+name)
      r=await add(w.c,'喜欢咖啡');budget.finish(setup,{'local_applied':r.get('local_applied')});assert r.get('local_applied')
    finally:deactivate(token)
   before=copy.deepcopy(w.device.state);r=await w.turn(fixture['query'])
   if name=='habit_learn' and r['outcome']['mode']=='clarify':
    write(dict(r,tool=name,mode='clarification',errors=[]));budget.finish(charge,{'clarified':True})
    charge=budget.reserve('case',opt.name+':habit-am-pm-supplement');r=await w.turn('早上八点，其他按刚才说的。')
   matches=[x for x in r['outcome']['results'] if x['tool']==name]
   expected='accepted' if name=='camera_face_enroll_start' else 'completed'
   errors=[]
   if len(matches)!=1 or matches[0]['state']!=expected:errors.append('requested_workflow_not_verified:'+expected)
   if r['outcome']['error']:errors.append(r['outcome']['error'])
   from core.utils.tool_harness.reply_composer import unsafe,status_conflict
   from core.utils.tool_harness.models import StepResult
   visible=[StepResult.model_validate(x) for x in r['outcome']['results'] if not x['intermediate'] or x['state']!='completed']
   if visible and (unsafe(r['speech'],visible) or status_conflict(r['speech'],visible,w.c._full_tool_harness.catalog())):errors.append('unverified_spoken_claim')
   if any(tool in r['speech'] for tool in names):errors.append('internal_tool_name_spoken')
   if matches:
    actual=matches[0]['arguments']
    for key in ('hour','minute','minutes','advance_minutes','repeat_days','index','delay_minutes','volume','timezone','date','mode','intent','raw','outcome','fact','replacement','remind_at'):
     expected_value=fixture['query'] if key=='raw' and name=='behavior_log' else args.get(key)
     if key=='intent' and name=='habit_learn' and actual.get(key) in {'drink_water','drink','喝水','drinking_water','water_drinking'}:continue
     # Explicit first-person fact and its subject-omitted local form express
     # the same owner-bound fact; retain both raw forms in the evidence.
     if key in {'fact','replacement'} and isinstance(actual.get(key),str) and actual[key].removeprefix('我')==str(expected_value).removeprefix('我'):continue
     if key in args and actual.get(key)!=expected_value:errors.append('incorrect_requested_argument:'+key)
   if not r['speech'] or r['assistant_history']!=[r['speech']]:errors.append('speech_history_mismatch')
   if name.startswith('memory') and contract(name).write and (not matches or not matches[0]['payload'].get('readback_confirmed')):errors.append('memory_readback_missing')
   r.update(tool=name,mode='recorded_decision_program_regression' if opt.replay else 'real_model_workflow',errors=errors,before=before,paid_model=not opt.replay)
   write(r);budget.finish(charge,{'errors':errors})
   if errors:raise RuntimeError('paid_tool_workflow_failed_stop_batch')
   if opt.faults and contract(name).write:
    # Failure is injected before mutation. Unknown receipt deliberately follows
    # one actual dispatch, with no automatic resend; the state remains inspectable.
    for fault in ('failure','unknown'):
     q=budget.reserve('case',opt.name+':'+name+':'+fault)
     manager=w.c.func_handler.tool_manager;original=manager._execute_tool;state=copy.deepcopy(w.device.state);calls=len(w.device.calls);dispatches=[]
     response=ActionResponse(Action.ERROR,result={'ok':False,'errorCode':'storage_no_space','message':'隔离存储拒绝'}) if fault=='failure' else ActionResponse(Action.REQLLM,result={'unconfirmed':True})
     async def injected(tool,arguments):dispatches.append((tool,arguments));return response
     manager._execute_tool=injected
     from core.utils.tool_harness.ledger import Ledger
     from core.utils.tool_harness.runtime import Harness
     h=Harness(w.c,ledger=Ledger(':memory:'));effective=copy.deepcopy(matches[0]['arguments']);token=activate(w.c,w.c.person_turn)
     try:
      checked=await h.dispatch(name,effective,h.scope(),'fault-'+name,h.epoch(),h.catalog(),time.monotonic()+10)
      again=await h.dispatch(name,effective,h.scope(),'fault-'+name,h.epoch(),h.catalog(),time.monotonic()+10)
      assert again.state==checked.state and len(dispatches)==1,'duplicate_fault_dispatch'
     finally:deactivate(token);manager._execute_tool=original;h.ledger.close()
     assert checked.state==('failed' if fault=='failure' else 'unknown'),checked.model_dump()
     assert w.device.state==state and len(w.device.calls)==calls
     spoken=checked.reply
     if opt.phase=='final':
      from core.utils.tool_harness.reply_composer import compose,unsafe
      from core.utils.tool_harness.models import OperationOutcome
      from bootstrap import system_prompt
      final=await compose(h,fixture['query'],[{'role':'system','content':system_prompt(w.c.config)},{'role':'user','content':fixture['query']}],OperationOutcome(mode='operate',results=[checked],reply=checked.reply),time.monotonic()+25)
      spoken=final.reply;assert spoken and not unsafe(spoken,[checked]),'unverified_failure_reply'
     assert not any(tool in spoken for tool in names),'internal_tool_name_spoken'
     write({'tool':name,'mode':fault,'state':checked.model_dump(),'speech':spoken,'errors':[],'evidence':'real_Harness_dispatch_isolated_fault_executor','dispatches':dispatches,'unchanged_state':True})
     budget.finish(q,{'state':checked.state})
  finally:await w.close();provider.client.close()
 print('BUDGET',json.dumps(budget.report()),flush=True)
asyncio.run(main())
