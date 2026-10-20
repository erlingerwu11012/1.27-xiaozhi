"""Candidate production handlers with bounded software transports; no paid calls."""
import bootstrap,asyncio,json,time,types,unittest
from unittest.mock import AsyncMock,MagicMock,patch
from test_followup import BudgetResult
from core.utils.face_enrollment_operation import start_operation,monitor
from core.utils.tool_result import DeviceToolError
from core.utils.tool_harness.contracts import receipt
from plugins_func.register import Action,ActionResponse

class FaceLifecycle(unittest.IsolatedAsyncioTestCase):
 def setup_values(self,state='unconfirmed'):
  operation={'operation_id':'o','session_id':'s','state':state,'started_at':time.monotonic()}
  conn=types.SimpleNamespace(session_id='s',face_enrollment_operation=operation,logger=MagicMock(),config={})
  client=types.SimpleNamespace(closed=False,wait_ready=AsyncMock(return_value=True),resolve_tool_name=lambda x:x)
  return conn,client,operation
 async def test_unknown_active_does_not_start_twice(self):
  conn,client,_=self.setup_values();invoke=AsyncMock(return_value=json.dumps({'state':'capturing','accepted_count':0}))
  with self.assertRaises(DeviceToolError):await start_operation(conn,client,invoke,'camera.face.enroll.start','{}',3)
  self.assertEqual([x.args[2] for x in invoke.call_args_list],['camera.face.enroll.status'])
 async def test_unknown_status_failure_does_not_start(self):
  conn,client,_=self.setup_values();invoke=AsyncMock(side_effect=TimeoutError())
  with self.assertRaises(DeviceToolError):await start_operation(conn,client,invoke,'camera.face.enroll.start','{}',3)
  self.assertEqual(invoke.call_count,1)
 async def test_unknown_failed_then_new_request_can_start(self):
  conn,client,_=self.setup_values();client.resolve_tool_name=lambda x:None if x.endswith('status') else x
  invoke=AsyncMock(side_effect=[json.dumps({'state':'idle','terminal_state':'failed','last_error_code':'capture_failed','accepted_count':0}),json.dumps({'accepted':True,'state':'accepted','operation_id':'new'})])
  result=json.loads(await start_operation(conn,client,invoke,'camera.face.enroll.start','{}',3))
  self.assertTrue(result['accepted']);self.assertEqual(invoke.call_count,2);self.assertEqual(conn.face_enrollment_operation['device_operation_id'],'new')
 async def test_terminal_reason_retained_after_idle(self):
  conn,client,operation=self.setup_values('accepted');operation['device_operation_id']='d'
  invoke=AsyncMock(return_value=json.dumps({'state':'idle','terminal_state':'failed','operation_id':'d','accepted_count':0,'last_error_code':'capture_failed'}))
  with patch('core.utils.face_enrollment_operation.asyncio.sleep',AsyncMock()):await monitor(conn,client,invoke,operation)
  self.assertEqual(operation['state'],'failed');self.assertEqual(operation['errorCode'],'capture_failed')
 async def test_old_session_monitor_cannot_update_new_operation(self):
  conn,client,operation=self.setup_values('accepted');conn.session_id='new';invoke=AsyncMock()
  with patch('core.utils.face_enrollment_operation.asyncio.sleep',AsyncMock()):await monitor(conn,client,invoke,operation)
  self.assertEqual(operation['state'],'accepted');invoke.assert_not_called()
 def test_status_reply_explains_idle_failure(self):
  r=receipt('camera_face_enroll_status',{},ActionResponse(Action.REQLLM,result=json.dumps({'state':'idle','terminal_state':'failed','last_error_code':'capture_failed','accepted_count':0})),'r')
  self.assertEqual(r.state,'completed');self.assertIn('失败',r.reply);self.assertNotIn('尚未开始',r.reply);self.assertIn('获取图像',r.reply)
 def test_draft_is_not_committed(self):
  r=receipt('camera_face_enroll_status',{},ActionResponse(Action.REQLLM,result=json.dumps({'state':'draft_ready','accepted_count':3})),'r')
  self.assertIn('网页确认',r.reply);self.assertNotIn('入库完成',r.reply)

class HarnessLifecycle(unittest.IsolatedAsyncioTestCase):
 async def setup_wire(self):
  from bootstrap import production_provider
  from wire_conversation import WireConversation
  self.provider,cfg=production_provider();self.w=await WireConversation().setup(self.provider,cfg)
  return self.w
 async def asyncTearDown(self):
  if hasattr(self,'w'):await self.w.close();self.provider.client.close()
 def plans(self,*plans):
  import collections
  plans=collections.deque(plans);h=self.w.c._full_tool_harness
  h.stream_decide=None;h.decide=lambda _:plans.popleft() if len(plans)>1 else plans[0]
 async def test_relative_context_read_then_write(self):
  from core.utils.tool_harness.models import OperationOutcome,StepResult
  w=await self.setup_wire();h=w.c._full_tool_harness;w.device.state['volume']=60;w.device.save()
  h.relevant_operation=(h.scope(),time.monotonic(),OperationOutcome(mode='operate',reply='',results=[StepResult(state='completed',tool='self_audio_speaker_set_volume',call_id='p',arguments={'volume':60},reply='已调到60')]),'把音量调到60')
  self.plans({'mode':'operate','intent':'action','intent_evidence':'再大一点','authorized_writes':[],'steps':[{'id':'a','tool':'self_get_device_status'}]},
   {'mode':'operate','intent':'action','intent_evidence':'再大一点','authorized_writes':['self_audio_speaker_set_volume'],'steps':[{'id':'b','tool':'self_audio_speaker_set_volume','relative':10}]},
   {'mode':'chat','steps':[],'authorized_writes':[],'reply':'音量已调到70。'})
  result=await w.turn('再大一点。')
  self.assertEqual(result['state']['volume'],70);self.assertEqual(len([r for r in result['outcome']['results'] if r['tool']=='self_audio_speaker_set_volume' and r['state']=='completed']),1)
 async def test_cancel_reminder_reads_then_deletes_once(self):
  from core.utils.tool_harness.models import OperationOutcome,StepResult
  w=await self.setup_wire();h=w.c._full_tool_harness
  w.device.state['notes']=[{'text':'吃饭','remind_at':1900000000,'recipient_person_id':'all'}];w.device.save()
  h.relevant_operation=(h.scope(),time.monotonic(),OperationOutcome(mode='operate',reply='',results=[StepResult(state='completed',tool='reminder_list_pending',call_id='p',arguments={},reply='吃饭')]),'有哪些待提醒事项')
  self.plans({'mode':'operate','intent':'action','intent_evidence':'取消刚才吃饭提醒','authorized_writes':['note_delete'],'finished':False,'steps':[{'id':'a','tool':'note_list','arguments':{}}]},
   {'mode':'operate','intent':'action','intent_evidence':'取消刚才吃饭提醒','authorized_writes':['note_delete'],'steps':[{'id':'b','tool':'note_delete','arguments':{'index':1}}]},
   {'mode':'chat','intent':'chat','intent_evidence':'','steps':[],'authorized_writes':[],'reply':'吃饭提醒已经取消。'})
  result=await w.turn('取消刚才吃饭提醒。')
  self.assertEqual(result['state']['notes'],[]);self.assertEqual(len([r for r in result['calls'] if r['tool']=='note_delete']),1)
 def test_read_list_cannot_claim_cancelled(self):
  from core.utils.tool_harness.models import StepResult
  from core.utils.tool_harness.reply_composer import status_conflict
  read=StepResult(state='completed',tool='note_list',call_id='r',arguments={},reply='[1] 吃饭')
  self.assertTrue(status_conflict('吃饭提醒已经取消。',[read],{}))
 async def test_public_reminder_embedded_content(self):
  w=await self.setup_wire()
  self.plans({'mode':'operate','intent':'action','intent_evidence':'现在给我设公共喝水提醒，三分钟后','authorized_writes':['add_reminder'],'steps':[{'id':'a','tool':'add_reminder','arguments':{'text':'现在给我设公共喝水提醒，三分钟后。','content':'喝水','remind_time_str':'三分钟后'}}]},
   {'mode':'chat','steps':[],'authorized_writes':[],'reply':'三分钟后提醒所有人喝水。'})
  result=await w.turn('现在给我设公共喝水提醒，三分钟后。')
  self.assertEqual(result['state']['notes'][0]['recipient_person_id'],'all');self.assertFalse(any(r['state']!='completed' for r in result['outcome']['results']))
 async def test_negated_public_reminder_stays_personal(self):
  w=await self.setup_wire()
  self.plans({'mode':'operate','intent':'action','intent_evidence':'给我设喝水提醒','authorized_writes':['add_reminder'],'steps':[{'id':'a','tool':'add_reminder','arguments':{'text':'不要公共提醒，给我设喝水提醒，三分钟后。','content':'喝水','remind_time_str':'三分钟后'}}]},
   {'mode':'chat','steps':[],'authorized_writes':[],'reply':'三分钟后提醒你喝水。'})
  result=await w.turn('不要公共提醒，给我设喝水提醒，三分钟后。')
  self.assertNotEqual(result['state']['notes'][0]['recipient_person_id'],'all')
 def test_correction_feedback_drops_mocking(self):
  from core.utils.tool_harness.runtime import respect_chat_preferences,reply_preferences
  prefs=reply_preferences(['你把我说的话理解错了，我说的是假设。'])
  self.assertNotIn('表演',respect_chat_preferences('哦，原来是假设啊。请开始你的表演。',prefs))
 async def test_note_card_cannot_dismiss_alarm(self):
  w=await self.setup_wire();self.plans({'mode':'operate','intent':'action','intent_evidence':'停止闹钟','authorized_writes':['alarm_dismiss'],'steps':[{'id':'a','tool':'alarm_dismiss'}]})
  result=await w.turn('停止闹钟。')
  self.assertTrue(result['state']['alarm_ringing']);self.assertFalse(any(x['tool']=='alarm_dismiss' for x in result['calls']))
 def test_read_only_result_cannot_claim_adjustment(self):
  from core.utils.tool_harness.models import StepResult
  from core.utils.tool_harness.reply_composer import status_conflict
  read=StepResult(state='completed',tool='self_get_device_status',call_id='r',arguments={},reply='',payload={'audio_speaker':{'volume':60}})
  self.assertTrue(status_conflict('音量调到70。',[read],{}));self.assertTrue(status_conflict('当前音量是70。',[read],{}))
  self.assertFalse(status_conflict('当前音量是60。',[read],{}))
 def test_verified_memory_ack_does_not_require_verbatim_fact(self):
  from core.utils.tool_harness.models import StepResult
  from core.utils.tool_harness.reply_composer import unsafe
  saved=StepResult(state='completed',tool='memory_add',call_id='s',arguments={'fact':'我妻子叫测试甲'},reply='已保存',payload={'readback_confirmed':True})
  self.assertFalse(unsafe('我已经记好了。',[saved]));self.assertFalse(unsafe('记下了，你的妻子叫测试甲。',[saved]))
  self.assertTrue(unsafe('记下了，你的妻子叫测试乙。',[saved]))

if __name__=='__main__':
 import sys
 sys.path.insert(0,str(bootstrap.stage/'work/test'))
 from test_qwen_audio_tts_plus import TtsStreamTests,TtsAbortRecoverTests
 suite=unittest.defaultTestLoader.loadTestsFromTestCase(FaceLifecycle)
 suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(HarnessLifecycle))
 for name in ['test_wait_for_task_started_then_stream_pcm','test_official_caption_does_not_emit_legacy_full_turn_again','test_abort_stops_old_session']:suite.addTest(TtsStreamTests(name))
 for name in ['test_stale_first_does_not_clear_abort_or_start','test_delayed_old_cancel_does_not_close_new_session','test_late_old_events_do_not_affect_new_session','test_finish_abort_repeat_close_and_disconnect','test_start_timeout_is_not_silent_success','test_two_devices_abort_isolated']:suite.addTest(TtsAbortRecoverTests(name))
 result=unittest.TextTestRunner(verbosity=2,resultclass=BudgetResult).run(suite);raise SystemExit(not result.wasSuccessful())
