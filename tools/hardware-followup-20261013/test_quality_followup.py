import bootstrap,unittest
from test_followup import BudgetResult
from core.utils.tool_harness.models import StepResult
from core.utils.tool_harness.reply_composer import unsafe
from core.utils.tool_harness.runtime import grounded_chat
class Quality(unittest.TestCase):
 def test_relations_can_ack_without_quoting_name(self):
  result=StepResult(state='completed',tool='memory_add',call_id='r',arguments={'fact':'我妻子叫林岚'},reply='已保存',payload={'readback_confirmed':True})
  self.assertTrue(unsafe('好的，林岚。',[result]));self.assertFalse(unsafe('记好了。',[result]));self.assertFalse(unsafe('记下了，你太太叫林岚。',[result]))
 def test_topic_switch_and_dangling_question(self):
  text=grounded_chat('行，那就不提那些记录。既然你偏爱龙井？',[], '现在先别谈记忆，我们随便聊一句。')
  self.assertEqual(text,'');self.assertEqual(grounded_chat('既然你偏爱龙井？',[], '我们聊聊吧。'),'')
 def test_unqueried_current_weather_is_not_fact(self):
  self.assertEqual(grounded_chat('行。今天天气看着还行，适合发呆。',[],'随便聊一句。'),'行。')
  self.assertIn('下雨',grounded_chat('下雨的日子适合听音乐。',[],'我这里现在下雨了。'))
 def test_chat_hides_record_ids_and_unobserved_appearance(self):
  self.assertEqual(grounded_chat('真的保存了。系统回执记录编号 material:692，内容是我喜欢龙井。',[],'存了吗？'),'真的保存了。内容是我喜欢龙井。')
  self.assertEqual(grounded_chat('早啊。看你这一脸没睡醒的样子，昨晚去哪了？',[],'你好。'),'早啊。')
 def test_greeting_does_not_invent_shared_past(self):
  self.assertEqual(grounded_chat('哟，终于舍得出现了？我还以为你打算跟床板过一辈子呢。',[],'你好。'),'')
  self.assertEqual(grounded_chat('你好，想聊点什么？',[],'你好。'),'你好，想聊点什么？')
  self.assertEqual(grounded_chat('好啊，难得你主动找我闲聊。说吧。',[],'你好，今天想跟你随便聊聊。'),'说吧。')
  self.assertEqual(grounded_chat('好啊，难得你这么主动找我聊天。说吧。',[],'你好，今天想跟你随便聊聊。'),'说吧。')
if __name__=='__main__':
 import sys
 suite=unittest.defaultTestLoader.loadTestsFromNames(sys.argv[1:],sys.modules[__name__]) if len(sys.argv)>1 else unittest.defaultTestLoader.loadTestsFromTestCase(Quality)
 result=unittest.TextTestRunner(verbosity=2,resultclass=BudgetResult).run(suite);raise SystemExit(not result.wasSuccessful())
