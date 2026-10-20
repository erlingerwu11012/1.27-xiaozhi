import argparse,os
cli=argparse.ArgumentParser();cli.add_argument('--name',required=True);cli.add_argument('--mode',choices=['development','baseline','final'],default='development');cli.add_argument('--groups',default='');opt=cli.parse_args()
os.environ['TEST_PHASE']='final' if opt.mode=='final' else 'development'
if opt.mode=='baseline':os.environ['CANDIDATE_WORK']='/root/prjs/releases/mcp-prune-20261010/runtime'
import bootstrap,asyncio,json,time,re,copy,dataclasses,hashlib,traceback,uuid
from bootstrap import stage,budget,production_provider
from wire_conversation import WireConversation
from core.utils.tool_harness.contracts import contract,unpack
from core.utils.person_identity import activate,deactivate
from plugins_func.register import Action,ActionResponse
import pymysql
PACK=json.loads((stage/'cases.json').read_text());REPORT=stage/(opt.name+'-results.jsonl')
assert not REPORT.exists(),'never overwrite failed or previous evidence'
assert hashlib.sha256((stage/'cases.json').read_bytes()).hexdigest()==(stage/'cases.sha256').read_text()
e=json.loads((stage/'private-test-env.json').read_text());assert e['PERSON_MEMORY_TEST_DATABASE'].startswith('bailian_memory_test_')
def clean_memory():
 with pymysql.connect(host='127.0.0.1',user='root',password=e['PERSON_MEMORY_TEST_PASSWORD'],database=e['PERSON_MEMORY_TEST_DATABASE'],autocommit=True) as d:
  with d.cursor() as c:
   for table in ['ai_agent_chat_history','ai_memory_override','ai_person_material']:c.execute('DELETE FROM '+table+' WHERE account_id=99003')

async def readback(w,row):
 mapping={'memory_add':'memory_search','memory_correct':'memory_search','memory_forget':'memory_search','self_audio_speaker_set_volume':'self_get_device_status','self_screen_set_brightness':'self_get_device_status','alarm_set':'alarm_list','alarm_delete':'alarm_list','add_reminder':'note_list','note_add':'note_list','note_delete':'note_list','habit_learn':'habit_list','habit_delete':'habit_list','reminder_close_current':'reminder_get_current','reminder_action':'reminder_get_current'}
 name=mapping.get(row.get('tool'))
 if not name or row.get('identity_block'):return None
 args={'query':row['query']} if name=='memory_search' else {}
 token=activate(w.c,w.c.person_turn)
 try:return {'tool':name,'payload':unpack(await w.c.func_handler.tool_manager._execute_tool(name,args))}
 finally:deactivate(token)

def check(row,r,before):
 errors=[];speech=r['speech'];o=r['outcome'];results=o['results'];s=r['state']
 if not speech:errors.append('silent_valid_request')
 if r['assistant_history']!=[speech]:errors.append('speech_history_mismatch')
 if [x['type'] for x in r['events']]!=['FIRST','MIDDLE','LAST']:errors.append('tts_sequence')
 if re.search(r'确认操作目标或参数|确定操作目标或参数|instance_id|record_id|tool_calls|catalog_version|\[smirks\]|\[apologetic\]|^[{[]',speech):errors.append('internal_or_generic_speech')
 parts=[x.strip() for x in re.split('[。！？!?]',speech) if len(x.strip())>7]
 if len(parts)!=len(set(parts)):errors.append('duplicate_sentence')
 for pattern in row.get('required',[]):
  semantic_empty=pattern in {'没有|空|零|0','没有|空|暂无|0|零'} and re.search(r'没了|一个都没|不剩|不剩下',speech)
  if not re.search(pattern,speech) and not semantic_empty:errors.append('missing_answer:'+pattern)
 for pattern in row.get('forbidden',[]):
  if re.search(pattern,speech):errors.append('forbidden_answer:'+pattern)
 writes=[x for x in results if contract(x['tool']).write]
 if row.get('identity_block'):
  if any(x['state']=='completed' for x in results if x['tool'].startswith('memory')) or not re.search('听出|身份|是谁|认出',speech):errors.append('identity_scope_misreported')
 elif row.get('tool'):
  for tool in [row['tool']]+row.get('also',[]):
   matches=[x for x in results if x['tool']==tool]
   if len(matches)!=1 or matches[0]['state']!='completed':errors.append('requested_operation_not_completed:'+tool)
 if row.get('clarify') and o['mode']!='clarify':errors.append('missing_specific_clarification')
 if not row.get('tool') and writes:errors.append('unrequested_write')
 if row.get('tool') and any(x['tool'] not in [row['tool']]+row.get('also',[]) for x in writes):errors.append('wrong_extra_write')
 if len({(x['tool'],json.dumps(x['arguments'],sort_keys=True)) for x in writes})!=len(writes):errors.append('duplicate_write')
 for key,attr in [('volume','volume'),('level','level')]:
  if key in row and s[attr]!=row[key]:errors.append('wrong_persisted_'+key)
 for key in ['alarms','notes','habits']:
  if key in row and len(s[key])!=row[key]:errors.append('wrong_persisted_'+key)
 if 'card' in row and s['card']['active']!=row['card']:errors.append('wrong_card_state')
 if row.get('card_action') and s['card'].get('last_action')!=row['card_action']:errors.append('wrong_card_action')
 if row.get('recipient'):
  recent=[x for x in r['calls'] if x['tool']=='note_add']
  if not recent or recent[-1]['arguments'].get('recipient_person_id')!=row['recipient']:errors.append('public_recipient_lost')
 if not row.get('tool') and not row.get('clarify') and re.search(r'这次请求没有执行完|尚未确认任何新的修改|需要确认.*参数|没有得到有效结果',speech):errors.append('chat_replaced_by_error')
 feedback='\n'.join(r['user_history'])
 if re.search(r'没听出|没认出|未确认身份',speech) and re.search(r'没有.{0,12}(?:你|宠物|个人).{0,10}(?:记录|记忆)',speech):errors.append('identity_scope_misreported')
 if re.search(r'这就忘了|装作没听见|别想赖账|苦中作乐|半夜自己改名|压根.{0,8}没存',speech):errors.append('persona_mocking_or_fabrication')
 if re.search(r'别逗|别开玩笑|别再.*逗',feedback) and re.search(r'嘿嘿|哈哈|坏笑|逗你|笨蛋|傻瓜',speech):errors.append('joking_after_feedback')
 if re.search(r'别反问|不要每句都问',feedback) and re.search(r'[？?]|(?:吗|呢)[。！! ]*$',speech) and not row.get('clarify'):errors.append('unwanted_question')
 from core.utils.tool_harness.reply_composer import unsafe,status_conflict
 from core.utils.tool_harness.models import StepResult
 visible=[StepResult.model_validate(x) for x in results if not x['intermediate'] or x['state']!='completed']
 if visible and (unsafe(speech,visible) or status_conflict(speech,visible,{})):errors.append('unverified_spoken_claim')
 if r.get('readback'):
  p=r['readback']['payload']
  if row['tool'].startswith('memory'):
   if row['tool']=='memory_add' and not any(x['tool']=='memory_add' and x.get('payload',{}).get('readback_confirmed') for x in results):errors.append('memory_add_not_readback_verified')
   if row['tool'] in {'memory_correct','memory_forget'} and not any(x['tool']==row['tool'] and x.get('payload',{}).get('readback_confirmed') for x in results):errors.append('memory_change_not_verified')
 return errors

async def run_group(group):
 provider,cfg=production_provider();w=await WireConversation().setup(provider,cfg);actor=w.c.person_turn
 from core.utils.reminder_interaction import close_interaction
 if not group.get('card'):close_interaction(w.c);w.device.state['card']['active']=False;w.device.save()
 if any((x.get('tool') or '').startswith('memory') for x in group['turns']):clean_memory()
 try:
  for i,row in enumerate(group['turns']):
   charge=budget.reserve('case',opt.mode+':'+group['id']+':'+str(i));before=copy.deepcopy(w.device.state)
   if row.get('identity')=='unknown':w.c.person_turn=dataclasses.replace(actor,status='unknown',person_id='',mode='personal')
   if row.get('identity')=='restore':w.c.person_turn=actor
   start=time.monotonic()
   try:
    r=await w.turn(row['query'],noise=row.get('noise',False));r['readback']=await readback(w,row);r['errors']=check(row,r,before)
   except Exception as exc:r={'errors':['test_exception:'+type(exc).__name__],'trace':traceback.format_exc()[-2500:]}
   r.update({'case':row,'group':group['id'],'turn':i,'holdout':group.get('holdout',False),'duration_ms':round((time.monotonic()-start)*1000,2)})
   budget.finish(charge,{'errors':r['errors'],'duration_ms':r['duration_ms']})
   with REPORT.open('a') as f:f.write(json.dumps(r,ensure_ascii=False,default=str)+'\n')
   print(json.dumps({'group':r['group'],'turn':i,'query':row['query'],'speech':r.get('speech'),'errors':r['errors'],'calls':r.get('outcome',{}).get('model_calls')},ensure_ascii=False),flush=True)
   if r.get('trace'):raise RuntimeError('test_infrastructure_exception_recorded')
   if opt.mode=='final' and r['errors']:raise RuntimeError('final_gate_failure_preserved_stop_paid_run')
 finally:await w.close();provider.client.close()

async def main():
 groups=PACK['groups']+PACK['singles']
 if opt.groups:
  wanted=set(opt.groups.split(','));groups=[g for g in groups if g['id'] in wanted]
 elif opt.mode=='development':groups=[g for g in groups if g['id'] in {f'combo-{i:02d}' for i in range(8)}]
 elif opt.mode=='baseline':groups=[g for g in PACK['singles'] if g['kind'] in {1,2,3,5,6,7}][:30]
 if opt.mode=='final':assert len(groups)==120 and sum(len(g['turns']) for g in groups)==360
 files={str(p.relative_to(stage/'work')):hashlib.sha256(p.read_bytes()).hexdigest() for p in (stage/'work').rglob('*.py')}
 (stage/(opt.name+'-freeze.json')).write_text(json.dumps({'source':files,'cases_hash':hashlib.sha256((stage/'cases.json').read_bytes()).hexdigest(),'fixtures':{n:hashlib.sha256((stage/n).read_bytes()).hexdigest() for n in ['run_dialogues.py','wire_conversation.py','stateful_device.py','bootstrap.py']},'budget_start':budget.report(),'time':time.time()},indent=2))
 # Memory uses one test account, so keep its transactions/conversations serial.
 serial=[g for g in groups if any((t.get('tool') or '').startswith('memory') for t in g['turns'])]
 rest=[g for g in groups if g not in serial]
 sem=asyncio.Semaphore(3)
 async def limited(g):
  async with sem:await run_group(g)
 await asyncio.gather(*(limited(g) for g in sorted(rest,key=lambda g:not g.get('holdout',False))))
 for g in sorted(serial,key=lambda g:not g.get('holdout',False)):await run_group(g)
 rows=[json.loads(x) for x in REPORT.read_text().splitlines()]
 summary={'cases':len(rows),'passed':sum(not r['errors'] for r in rows),'failed':[{k:r[k] for k in ['group','turn','errors']} for r in rows if r['errors']],'real_model_turns':sum(any(d.get('usage') for d in r.get('decisions',[])) for r in rows),'model_calls':sum(r.get('outcome',{}).get('model_calls',0) for r in rows),'budget':budget.report(),'production_modified':False}
 (stage/(opt.name+'-summary.json')).write_text(json.dumps(summary,ensure_ascii=False,indent=2));print('SUMMARY',json.dumps(summary,ensure_ascii=False),flush=True)
asyncio.run(main())
