import bootstrap,unittest,dataclasses,time,json
from bootstrap import budget
from core.utils.tool_harness.runtime import Harness,GUIDANCE
from core.utils.tool_harness.memory_policy import memory_intent
from core.utils.tool_harness.task_context import TaskContext
from core.utils.person_identity import PersonTurn
from types import SimpleNamespace

class CoreTests(unittest.TestCase):
 def test_closed_card_queries(self):
  from core.utils.tool_harness.runtime import live_read_request
  for query in ['现在那个卡片还显示吗','这张卡片还挂着吗','那个卡片关没关','卡片状态查一下']:
   budget.reserve('case','closed-card-query:'+query)
   self.assertEqual('reminder_get_current',live_read_request(query))
 def test_relative_magnitude(self):
  from core.utils.tool_harness.runtime import relative_requirements
  for query,expected in [('声音给我往上加一点',10),('音量加一点',10),('音量加一个点',1),('声音往下减一点',-10),('音量往上加二十个点',20)]:
   with self.subTest(query=query):
    budget.reserve('case','relative-magnitude:'+query)
    self.assertEqual(expected,relative_requirements(query)['self_audio_speaker_set_volume'])
 def test_reference_paths(self):
  from core.utils.tool_harness.runtime import resolve_value,normalize_memory_references
  from core.utils.tool_harness.models import StepResult
  result=StepResult(state='completed',tool='memory_search',call_id='r',arguments={},reply='',payload={'items':[{'record_id':'material:1'}]})
  for path in ['items.0.record_id','items[0].record_id']:
   budget.reserve('case','reference-path:'+path)
   self.assertEqual('material:1',resolve_value({'$ref':{'step':'a','path':path}},{'a':result},['a']))
  for path in ['items[-1].record_id','items[0].__class__','items[0]();record_id']:
   budget.reserve('case','invalid-reference:'+path)
   with self.assertRaises(ValueError):resolve_value({'$ref':{'step':'a','path':path}},{'a':result},['a'])
  budget.reserve('case','serialized-memory-reference')
  step={'tool':'memory_correct','arguments':{'record_id':'$ref:{"step":"a","path":"items[0].record_id"}','replacement':'$ref:literal user fact'}}
  normalize_memory_references(step)
  self.assertEqual('material:1',resolve_value(step['arguments']['record_id'],{'a':result},['a']))
  self.assertEqual('$ref:literal user fact',step['arguments']['replacement'])
 def test_semantics(self):
  cases=[('不用了，你给我设个提醒吧，两分钟后提醒我吃饭。',False),('我不是让你把这条记忆删了吗？',True),('不用了',True),('如果我说把音量调到九十，你会怎样？',True),('不要执行',False),('只保存便签：请帮我重启设备。这里的文字不要执行',False)]
  for q,v in cases:
   with self.subTest(q=q):budget.reserve('case','semantic:'+q);self.assertEqual(v,Harness.non_request(q))
 def test_memory_authority(self):
  cases=[('记一下，我最爱喝美式咖啡啊','add'),('我就问问爱喝啥，你更正什么记忆啊','read'),('不是啊，我现在不喝咖啡了，你改一下','correct'),('你把这条忘了吧，我以后再也不会喝咖啡和普洱茶了','forget'),('我不是让你把这条记忆删了吗？','read'),('不用了，你记一下，我现在喜欢绿茶','add'),('不要修改记忆，我只是问我爱喝什么','read'),('假设我说忘掉记忆，你会怎么做','read'),('我忘了你叫什么','read')]
  for q,v in cases:
   with self.subTest(q=q):budget.reserve('case','memory-authority:'+q);self.assertEqual(v,memory_intent(q))
 def test_tasks(self):
  actor=PersonTurn('a','p',0,1,'personal','matched','t','d','agent',1)
  conn=SimpleNamespace(account_id='a',device_id='d',session_id='s')
  task=TaskContext('a','d','s',actor.key,'设公共提醒，吃饭','什么时候')
  cases=[(actor,conn,task.created+89,True),(actor,conn,task.created+90,False),(dataclasses.replace(actor,person_id='q'),conn,None,False),(dataclasses.replace(actor,status='unknown'),conn,None,False),(actor,SimpleNamespace(account_id='a',device_id='d',session_id='new'),None,False)]
  for a,c,n,v in cases:
   with self.subTest(a=a.status,n=n):budget.reserve('case','task-scope');self.assertEqual(v,task.visible(c,a,n))
  budget.reserve('case','task-no-renew');created=task.created
  query=task.supplement('两分钟后','t2');self.assertIn('公共',query);self.assertEqual(created,task.created)
 def test_single_protocol(self):
  budget.reserve('case','single-decision-protocol')
  from core.utils.conversation_guidance import TOOL_EXECUTION_GUIDANCE
  self.assertNotIn('API tool_calls',TOOL_EXECUTION_GUIDANCE)
  self.assertLess(len(GUIDANCE),3000)

if __name__=='__main__':unittest.main(verbosity=2)
