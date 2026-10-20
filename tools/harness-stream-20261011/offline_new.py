"""Deterministic protocol evidence, never counted as model experience evidence."""
import bootstrap,json,unittest,types,time
from bootstrap import budget
from core.utils.tool_harness.stream_decision import ReplyStream
from core.utils.tool_harness.speech_output import SpeechOutput
from core.utils.tool_harness.models import Decision,TaskUpdate
from core.utils.tool_harness.task_context import TaskContext

class Protocol(unittest.TestCase):
 def setUp(self):self.charge=budget.reserve('case',self.id())
 def tearDown(self):budget.finish(self.charge,{'kind':'deterministic_protocol'})
 def test_fragment_every_boundary(self):
  value={'mode':'chat','goal':'','steps':[],'finished':True,'task_action':'none','authorized_writes':[],'retrieval_query':'','task_update':None,'reply':'你好。引号"反斜线\\和换行\n😀可以分包。'}
  text=json.dumps(value,ensure_ascii=True)
  for width in range(1,33):
   updates=[];p=ReplyStream(updates.append)
   for i in range(0,len(text),width):p.feed(text[i:i+width])
   self.assertEqual(p.finish(),value);self.assertEqual(updates[-1],value['reply'])
   self.assertTrue(all(value['reply'].startswith(part) for part in updates))
 def test_operations_not_spoken(self):
  for mode in ['operate','continue','retrieve']:
   updates=[];p=ReplyStream(updates.append);p.feed(json.dumps({'mode':mode,'steps':[],'reply':'设好了。'}));p.finish();self.assertFalse(updates)
 def test_protocol_rejects(self):
  for text in ['{"mode":"chat","mode":"operate","reply":"x"}', '{"mode":"chat","reply":"x","steps":[]}', '{"mode":"chat","reply":"unterminated', '{"mode":"chat","reply":"x"}[]', '{"mode":"chat","reply":"bad\\q"}']:
   with self.assertRaises((ValueError,json.JSONDecodeError)):
    p=ReplyStream();p.feed(text);p.finish()
 def test_speech_once_and_abort(self):
  emitted=[];valid=[True];p=SpeechOutput(lambda:valid[0],lambda:emitted.append('BEGIN'),emitted.append,lambda:emitted.append('END'))
  for text in ['你好','你好。接','你好。接着说。','你好。接着说。']:p.feed(text,lambda x:True)
  self.assertEqual(p.finish('你好。接着说。'), '你好。接着说。')
  self.assertEqual(emitted,['BEGIN','你好。','接着说。','END']);p.finish('你好。接着说。');self.assertEqual(len(emitted),4)
  q=SpeechOutput(lambda:valid[0],lambda:None,emitted.append,lambda:None);valid[0]=False;q.feed('旧请求。',lambda x:True);q.finish('旧请求。');self.assertEqual(len(emitted),4)
 def test_cumulative_guard(self):
  emitted=[];p=SpeechOutput(lambda:True,lambda:None,emitted.append,lambda:None)
  p.feed('已受理。',lambda x:True);p.feed('已受理。已经完成。',lambda x:'完成' not in x)
  self.assertEqual(emitted,['已受理。','后面的内容还不能确认，先说到这里。']);self.assertEqual(p.finish('结果尚未确认。'),''.join(emitted))
 def test_task_scope_expiry_patch(self):
  actor=types.SimpleNamespace(eligible=True,key=('99003','person-a'),account_id='99003');conn=types.SimpleNamespace(account_id='99003',device_id='device-a',session_id='session-a')
  task=TaskContext('99003','device-a','session-a',actor.key,'公共提醒吃饭','什么时候？')
  definition=types.SimpleNamespace(description={'function':{'parameters':{'type':'object','properties':{'recipient_person_id':{'type':'string'},'text':{'type':'string'},'remind_at':{'type':'integer'}}}}})
  task.update(TaskUpdate(target_tool='note_add',parameters={'recipient_person_id':'all','text':'吃饭'},missing_fields=['remind_at']),{'note_add':definition},'1','公共提醒吃饭')
  created=task.created;task.update(TaskUpdate(target_tool='note_add',parameters={'remind_at':1234}),{'note_add':definition},'2','两分钟后')
  self.assertEqual(task.parameters,{'recipient_person_id':'all','text':'吃饭','remind_at':1234});self.assertEqual(task.created,created)
  self.assertTrue(task.visible(conn,actor));self.assertFalse(task.visible(conn,actor,created+90))
  self.assertFalse(task.visible(conn,types.SimpleNamespace(eligible=True,key=('99003','person-b'))))
  with self.assertRaises(ValueError):task.update(TaskUpdate(target_tool='note_add',parameters={'unknown':1}),{'note_add':definition},'3','x')
 def test_retrieval_decision(self):
  Decision(mode='retrieve',retrieval_query='查询设备剩余电量')
  for values in [{'mode':'retrieve'},{'mode':'retrieve','retrieval_query':'电量','authorized_writes':['note_add']},{'mode':'chat','steps':[{'id':'a','tool':'note_add'}]}]:
   with self.assertRaises(ValueError):Decision.model_validate(values)
 def test_time_supplement_variants(self):
  from core.utils.remind_time import extract_time_expression,parse_remind_time
  for text in ['五分钟以后','五分钟之后','五分钟后']:
   self.assertEqual(extract_time_expression('接着刚才的事项，'+text),'五分钟后')
   self.assertIsNotNone(parse_remind_time(text))
 def test_unrelated_chat_does_not_chase_task(self):
  from core.utils.tool_harness.runtime import without_task_chaser
  task=object();reply='路上安静挺难得的。不过包裹什么时候取？没定时间我可记不住。'
  self.assertEqual(without_task_chaser(reply,task,'今天路上挺安静'),'路上安静挺难得的。')
  self.assertEqual(without_task_chaser(reply,task,'刚才的任务缺什么'),reply)
 def test_historical_card_receipt_does_not_authorize_new_claim(self):
  from core.utils.tool_harness.runtime import Harness
  h=object.__new__(Harness);h.scope=lambda:'owner';h.last=('owner',time.monotonic(),{'outcome':[{'tool':'reminder_action','state':'completed','arguments':{'action':'secondary'}}]})
  self.assertFalse(h.unverified_action_claim('刚才只是把屏幕上的卡片关掉了。'))
  self.assertTrue(h.unverified_action_claim('已经把卡片关掉了。'))
  self.assertTrue(h.unverified_action_claim('刚才把卡片关掉了，也已经删除记忆了。'))
  h.last=('other',time.monotonic(),h.last[2]);self.assertTrue(h.unverified_action_claim('刚才把卡片关掉了。'))
 def test_chat_does_not_invent_causes_or_personal_state(self):
  from core.utils.tool_harness.runtime import grounded_chat
  self.assertEqual(grounded_chat('还没发货，看来这书架挺抢手。',[],'新书架还没发货'),'还没发货。')
  self.assertEqual(grounded_chat('随口说说也挺好，看来今晚心情不错。',[],'今天天色不错，随口说说'),'随口说说也挺好。')
  self.assertEqual(grounded_chat('正文还是一半。看来是想靠颜值撑场面。',[],'昨天只改了标题'),'正文还是一半。')
 def test_photo_delivers_verified_description_without_replay_or_story(self):
  from core.utils.tool_harness.reply_composer import focused_result_reply,unsafe
  from core.utils.tool_harness.models import StepResult
  result=StepResult(call_id='photo',arguments={},tool='self_camera_take_photo',state='completed',reply='画面里是一只蓝色杯子，放在桌面上。',payload={'description':'画面里是一只蓝色杯子，放在桌面上。'})
  sent=[];output=SpeechOutput(lambda:True,lambda:None,sent.append,lambda:None)
  for raw in ['拍好','拍好了。','拍好了。桌上孤零零地躺着一只蓝色杯子，看来它很享受极简风格。']:
   output.feed(focused_result_reply(raw,[result]),lambda value:not unsafe(value,[result]))
  final=output.finish(focused_result_reply(raw,[result]))
  self.assertEqual(final,'拍好了。'+result.reply)
  self.assertEqual(''.join(sent),final);self.assertEqual(final.count('拍好了'),1)
  self.assertNotIn('极简',final);self.assertNotIn('孤零零',final)
 def test_grounded_stream_keeps_valid_sentence_without_generic_truncation(self):
  from core.utils.tool_harness.runtime import grounded_chat,respect_chat_preferences
  query='现在家里还没有新书架，我只是期待把旧书摆出来'
  value='期待把旧书摆出来很有意思。旧书堆在那儿，心里已经预演了好几遍。'
  sent=[];output=SpeechOutput(lambda:True,lambda:None,sent.append,lambda:None)
  for width in range(1,len(value)+1):
   text=value[:width];ends=[m.end() for m in __import__('re').finditer('[。！？]',text)]
   filtered=grounded_chat(text[:max(ends,default=0)],[],query)
   output.feed(filtered,lambda value:True)
  final=output.finish(grounded_chat(value,[],query))
  self.assertEqual(final,'期待把旧书摆出来很有意思。');self.assertEqual(sent,[final])
  self.assertEqual(respect_chat_preferences('想不想继续？',{'no_optional_questions':True},fallback=False),'')
 def test_past_setting_claim_requires_scoped_verified_values(self):
  from core.utils.tool_harness.runtime import Harness
  from core.utils.tool_harness.models import StepResult,OperationOutcome
  h=object.__new__(Harness);h.scope=lambda:'owner';h.last=None;h._user_request='我刚才说的，你听到了吧';h.write_targets=lambda q:set()
  result=StepResult(call_id='set',arguments={'brightness':4},tool='self_screen_set_brightness',state='completed',reply='亮度已调到4档。',payload={'brightness':4,'brightness_level':4})
  h.relevant_operation=('owner',time.monotonic(),OperationOutcome(mode='operate',reply=result.reply,results=[result]),'屏幕提亮一点')
  self.assertFalse(h.unverified_action_claim('听到了，亮度已经调好了。'))
  self.assertTrue(h.unverified_action_claim('亮度已经调到5档了。'))
  self.assertTrue(h.unverified_action_claim('亮度已经调好了，也已经删除记忆了。'))
  h.relevant_operation=('other',time.monotonic(),h.relevant_operation[2],'x');self.assertTrue(h.unverified_action_claim('亮度已经调好了。'))
 def test_contextual_memory_read_and_scoped_delete_language(self):
  from core.utils.tool_harness.runtime import memory_read_request
  from core.utils.tool_harness.memory_policy import memory_intent
  query='重新检索最常用的杯子'
  self.assertIsNone(memory_read_request(query));self.assertEqual(memory_read_request(query,True),query)
  self.assertEqual(memory_intent('把刚才杯子那条资料删除，不要删其他的'),'forget')
  for query in ['不要删除那条资料','你刚才删除资料了吗','这句话：删除那条资料']:
   self.assertEqual(memory_intent(query),'read')
 def test_card_reassurance_uses_completed_action_not_requested_action(self):
  from core.utils.tool_harness.reply_composer import focused_result_reply
  from core.utils.tool_harness.models import StepResult
  result=StepResult(call_id='old',arguments={'action':'secondary'},tool='reminder_action',state='completed',reply='已延后。')
  h=types.SimpleNamespace(scope=lambda:'owner',_verified_card_action=('owner',time.monotonic(),result))
  value=focused_result_reply('刚才跳过了。',[],h,'没叫你删掉以后每天的规则啊')
  self.assertIn('延后',value);self.assertNotIn('跳过',value)

if __name__=='__main__':unittest.main(verbosity=2)
