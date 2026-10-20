import bootstrap,asyncio,json,time,hashlib,re,copy,dataclasses,traceback,uuid,pymysql,requests
from pathlib import Path
from bootstrap import stage,budget,production_provider
from wire_conversation import WireConversation
from stateful_device import StatefulDevice
from core.utils.person_identity import activate,deactivate
from core.utils.tool_harness.contracts import contract,unpack
from test_support import PACK
from plugins_func.register import Action,ActionResponse
CASES=json.loads((stage/'final-cases.json').read_text());REPORT=stage/'final-results.jsonl'
e=json.loads((stage/'private-test-env.json').read_text());assert e['PERSON_MEMORY_TEST_DATABASE']=='bailian_memory_test_experience_20261009'
def db():return pymysql.connect(host='127.0.0.1',user='root',password=e['PERSON_MEMORY_TEST_PASSWORD'],database=e['PERSON_MEMORY_TEST_DATABASE'],autocommit=True)
def seed_memory(w):
 a=w.c.person_turn
 with db() as d:
  with d.cursor() as c:
   for table in ['ai_agent_chat_history','ai_memory_override','ai_person_material']:c.execute('DELETE FROM '+table+' WHERE account_id=99003')
   for text in ['我喜欢咖啡','我的台灯叫银杏灯']:
    c.execute("INSERT INTO ai_agent_chat_history(mac_address,agent_id,session_id,chat_type,content,account_id,person_id,identity_status,turn_id,event_id,directory_version,default_generation,recall_allowed,created_at) VALUES('SOFTWARE-DEVICE-ONLY','agent_http','seed',1,%s,99003,%s,'default',%s,%s,%s,%s,TRUE,NOW())",(text,a.person_id,uuid.uuid4().hex,uuid.uuid4().hex,a.directory_version,a.generation))
def prepare(w,row,first):
 n=row.get('setup') or row.get('tool');s=w.device.state
 if not first:return
 if n and n.startswith('memory'):seed_memory(w)
 if n in {'alarm_delete','alarm_list'}:s['alarms']=[{'hour':22,'minute':0,'label':'闹钟','repeat_days':0}]
 if n in {'note_delete','note_list','note_snooze'}:s['notes']=[{'text':'买牛奶','remind_at':0}]
 if n in {'habit_delete','habit_list','habit_confirm','habit_reject'}:s['habits']=[{'intent':'drink_water','description':'喝水','hour':8,'minute':0,'advance_minutes':2,'source':'auto','repeat_days':127}]
 if n=='reminder_next':s['broadcast']=True
 if row.get('session','').startswith('chat'):
  from core.utils.reminder_interaction import close_interaction
  close_interaction(w.c);s['card']['active']=False
 w.device.save()
async def read_back(w,row,r):
 n=row['tool'];mapping={'self_audio_speaker_set_volume':'self_get_device_status','self_screen_set_brightness':'self_get_device_status','alarm_set':'alarm_list','alarm_delete':'alarm_list','note_add':'note_list','note_delete':'note_list','note_snooze':'note_list','add_reminder':'note_list','habit_learn':'habit_list','habit_delete':'habit_list','habit_confirm':'habit_list','habit_reject':'habit_list','reminder_action':'reminder_get_current','self_screen_set_render_mode':'self_screen_get_render_status','self_screen_set_render_options':'self_screen_get_render_status','camera_face_enroll_start':'camera_face_enroll_status','camera_face_enroll_cancel':'camera_face_enroll_status','memory_correct':'memory_search','memory_forget':'memory_search'}
 if n not in mapping:return
 name=mapping[n];args={'query':'咖啡' if n=='memory_correct' else ('台灯' if row.get('memory_kind')=='forget' else '咖啡')} if name=='memory_search' else {}
 token=activate(w.c,w.c.person_turn)
 try:x=await w.c.func_handler.tool_manager._execute_tool(name,args)
 finally:deactivate(token)
 r['readback']={'tool':name,'payload':unpack(x)}

def check(row,r,before):
 errors=[];n=row['tool'];out=r['outcome'];speech=r['speech'];state=r['state'];a=row['arguments'];results=out['results'];writes=[x['tool'] for x in r['calls'] if contract(x['tool']).write]
 if not speech:errors.append('silent_valid_request')
 if speech and r['assistant_history']!=[speech]:errors.append('speech_history_mismatch')
 if [x['type'] for x in r['events']]!=['FIRST','MIDDLE','LAST']:errors.append('tts_message_order')
 if speech.startswith(('{','[')) or re.search(r'instance_id|record_id|tool_calls|\[smirks\]|\[apologetic\]|self_[a-z_]+',speech):errors.append('raw_internal_speech')
 if n is None:
  feedback='\n'.join(r.get('user_history',[]))
  if re.search(r'别.{0,6}(?:反问|每一句.*问|每句话.*问)|不要反问',feedback) and re.search(r'[？?]|(?:吗|呢)[。！!\s]*$',speech):errors.append('feedback_unwanted_question')
  if re.search(r'别开玩笑|别逗|不要开玩笑',feedback) and re.search(r'哈哈|嘿嘿|狗头|坏笑|逗你|笨蛋|傻瓜|\[smirks\]',speech):errors.append('feedback_unwanted_teasing')
  if re.search(r'别教育|不用安慰|别安排|别替我安排',feedback) and re.search(r'你应该|你得|建议你|不妨|试着|要不要.{0,10}(?:提醒|记录|安排|计划)|需要我.{0,10}(?:提醒|记录|安排|计划)',speech):errors.append('feedback_unwanted_advice')
  if row.get('session')=='chat0' and row.get('required') and re.search(r'没发货|未发货|尚未发货',speech):errors.append('latest_shipping_state_reversed')
  if row.get('session')=='chat1' and row.get('required') and re.search(r'正文(?:完全)?空白|正文(?:从来|一直)?没写|从来没写过',speech) and not re.search(r'不能|不是|不对',speech):errors.append('existing_report_progress_reversed')
  for pattern in row.get('forbidden',[]):
   if re.search(pattern,speech):errors.append('chat_state_reversed:'+pattern)
  if writes:errors.append('non_request_write')
  for pattern in row.get('required',[]):
   if not re.search(pattern,speech):errors.append('chat_fact_missing:'+pattern)
  return errors
 matches=[x for x in results if x['tool']==n]
 wanted='accepted' if n in {'self_reboot','camera_face_enroll_start'} else 'completed'
 if len(matches)!=1 or matches[0]['state']!=wanted:errors.append('requested_operation_not_verified:'+n)
 allowed={n,'note_add'} if n=='add_reminder' else {n}
 if any(x not in allowed for x in writes):errors.append('unrequested_write:'+str(writes))
 if any(writes.count(x)>1 for x in set(writes)):errors.append('duplicate_write')
 if matches:
  from test_support import effective_arguments
  actual=effective_arguments(n,matches[0]['arguments'])
  for k,v in a.items():
   if k in {'query','question','label','say_goodbye','match','replacement','raw','outcome','remind_time_str','delay','relative'}:continue
   if n=='reminder_action' and k in {'instance_id','revision'}:continue
   observed=actual.get(k)
   if k=='brightness' and type(observed) is int and type(v) is int:
    def level(x):return x if x<=5 else 1 if x<65 else 2 if x<75 else 3 if x<85 else 4 if x<95 else 5
    observed,v=level(observed),level(v)
   if observed!=v:errors.append('wrong_argument:'+k)
 if n in {'self_audio_speaker_set_volume','self_screen_set_brightness'}:
  key='volume' if n.endswith('volume') else 'level';v=a.get('volume' if key=='volume' else 'brightness')
  if 'relative' in a:v=max(0 if key=='volume' else 1,min(100 if key=='volume' else 5,before[key]+a['relative']))
  if key=='level' and v and v>5:v=1 if v<65 else 2 if v<75 else 3 if v<85 else 4 if v<95 else 5
  if v is not None and state[key]!=v:errors.append('wrong_persisted_setting')
 if n=='alarm_set':
  if len(state['alarms'])!=len(before['alarms'])+1:errors.append('alarm_state_not_created')
  if state['alarms'] and any(state['alarms'][-1].get(k)!=v for k,v in a.items() if k in {'hour','minute','repeat_days'}):errors.append('alarm_state_wrong_time')
 if n in {'alarm_delete','note_delete','habit_delete'}:
  key={'alarm_delete':'alarms','note_delete':'notes','habit_delete':'habits'}[n]
  if len(state[key])!=len(before[key])-1:errors.append('delete_state_unchanged')
 if n in {'note_add','add_reminder'}:
  if len(state['notes'])!=len(before['notes'])+1:errors.append('note_or_reminder_not_saved')
  elif a.get('content') and a['content'] not in state['notes'][-1]['text']:errors.append('reminder_content_wrong')
  if n=='add_reminder' and state['notes'] and state['notes'][-1].get('remind_at',0)<=0:errors.append('reminder_time_missing')
 if n=='reminder_action' and matches:
  action=matches[0]['arguments'].get('action')
  if action in {'primary','tertiary','cancel'} and state['card']['active']:errors.append('card_not_closed')
  if state['card'].get('last_action')!=action:errors.append('card_action_not_applied')
 if n=='habit_learn' and len(state['habits'])!=len(before['habits'])+1:errors.append('habit_not_saved')
 if n=='self_reboot' and (not state['reboot_requested'] or '尚未' not in speech):errors.append('reboot_phase_not_honest')
 if n=='camera_face_enroll_start' and ('尚未' not in speech or state['enrollment']['state']!='capturing'):errors.append('enrollment_phase_not_honest')
 if n=='camera_face_enroll_cancel' and state['enrollment']['state']!='cancelled':errors.append('enrollment_not_cancelled')
 if n=='behavior_log' and len(state['behavior'])!=len(before['behavior'])+1:errors.append('behavior_not_persisted')
 rb=r.get('readback',{}).get('payload');rbtext=json.dumps(rb,ensure_ascii=False)
 if n=='memory_correct' and ('绿茶' not in rbtext if row.get('group')=='tool' else '不喝咖啡' not in rbtext):errors.append('corrected_memory_not_queryable')
 if n=='memory_forget' and (('银杏灯' if row.get('memory_kind')=='forget' else '我喜欢咖啡') in rbtext):errors.append('forgotten_memory_still_queryable')
 if row['group']=='memory' and row['memory_step']==2:
  if row['memory_kind']=='correct' and '不喝咖啡' not in speech:errors.append('memory_latest_fact_lost')
  if row['memory_kind']=='forget' and '银杏灯' in speech:errors.append('forgotten_fact_spoken')
 return errors
async def run_group(rows):
 provider,cfg=production_provider();w=await WireConversation().setup(provider,cfg)
 try:
  for i,row in enumerate(rows):
   budget.reserve('case','final:'+str(row['id']));prepare(w,row,i==0);before=copy.deepcopy(w.device.state)
   if row.get('setup')=='photo_retry':
    if row.get('multi_step')==0:w.device.faults['self_camera_take_photo']=ActionResponse(Action.REQLLM,result={'ok':False,'errorCode':'vision_not_ready','message':'视觉服务尚未就绪'})
    else:w.device.faults.clear()
   start=time.monotonic()
   try:
    r=await w.turn(row['query'],noise=True);r['case']=row;r['duration_ms']=round((time.monotonic()-start)*1000,2)
    # An injected failed capture is a correct failure, followed by a fresh retry.
    await read_back(w,row,r);r['errors']=check(row,r,before)
    if row.get('setup')=='photo_retry' and row.get('multi_step')==0:
     r['errors']=[x for x in r['errors'] if not x.startswith('requested_operation_not_verified:')]
     if '尚未就绪' not in r['speech']:r['errors'].append('vision_failure_reason_lost')
    if json.loads(w.device.path.read_text())!=r['state']:r['errors'].append('persisted_device_state_mismatch')
   except Exception as exc:r={'case':row,'errors':['test_exception:'+type(exc).__name__],'trace':traceback.format_exc()[-3000:]}
   with REPORT.open('a') as f:f.write(json.dumps(r,ensure_ascii=False,default=str)+'\n')
   print(json.dumps({'id':row['id'],'query':row['query'],'speech':r.get('speech'),'errors':r['errors'],'model_calls':r.get('outcome',{}).get('model_calls')},ensure_ascii=False),flush=True)
 finally:await w.close()
async def main():
 assert not REPORT.exists(),'existing final results must never be overwritten'
 files=json.loads((stage/'changed-files.json').read_text(encoding='utf-8-sig'));hashes={n:hashlib.sha256((stage/'work'/n).read_bytes()).hexdigest() for n in files}
 (stage/'final-freeze.json').write_text(json.dumps({'source':hashes,'java_source':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (stage/'manager-api/src/main/java/xiaozhi/modules/personmemory').glob('*.java')},'jar_sha256':hashlib.sha256((stage/'manager-api/target/xiaozhi-esp32-api.jar').read_bytes()).hexdigest(),'cases_sha256':hashlib.sha256((stage/'final-cases.json').read_bytes()).hexdigest(),'fixture_hashes':{n:hashlib.sha256((stage/n).read_bytes()).hexdigest() for n in ['wire_conversation.py','stateful_device.py','bootstrap.py','run_final.py','experience_protocol.py']},'time':time.time(),'budget':budget.report()},indent=2))
 groups={}
 for row in CASES:groups.setdefault(row.get('session') or 'single'+str(row['id']),[]).append(row)
 memory=[];others=[]
 for rows in groups.values():
  (memory if any((x.get('tool') or '').startswith('memory') for x in rows) else others).append(rows)
 sem=asyncio.Semaphore(4)
 async def limited(rows):
  async with sem:await run_group(rows)
 await asyncio.gather(*(limited(rows) for rows in others))
 for rows in memory:await run_group(rows)
 results=[json.loads(x) for x in REPORT.read_text().splitlines()];failed=[r for r in results if r['errors']]
 summary={'cases':len(results),'passed':len(results)-len(failed),'failed_ids':[r['case']['id'] for r in failed],'real_model_turns':sum(bool(r.get('outcome',{}).get('model_calls')) for r in results),'model_requests':sum(r.get('outcome',{}).get('model_calls',0) for r in results),'holdout':sum(bool(r['case'].get('holdout')) for r in results),'independent_holdout':sum(bool(r['case'].get('independent_holdout')) for r in results),'budget':budget.report(),'production_modified':False}
 (stage/'final-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2));print(json.dumps(summary,ensure_ascii=False),flush=True)
asyncio.run(main())
