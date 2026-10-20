import bootstrap,unittest,time
from test_followup import BudgetResult
from core.utils.tool_harness.runtime import save_confirmation_request,grounded_chat
class Confirmation(unittest.TestCase):
 def test_confirmation_not_new_save(self):
  self.assertTrue(save_confirmation_request('存到记忆库了吗？'));self.assertTrue(save_confirmation_request('刚才存好了吗？'));self.assertFalse(save_confirmation_request('记一下，我喜欢咖啡。'))
 def test_no_invented_sleep_or_wake(self):
  self.assertEqual(grounded_chat('你好。今天起得挺准时嘛。',[], '你好。'),'你好。')
  self.assertNotIn('睡着',grounded_chat('我在。怕你睡着了。',[], '我没让你停止对话。'))
 def test_explicit_wake_preserved(self):
  self.assertIn('起床',grounded_chat('刚起床啊。',[], '我刚起床。'))
if __name__=='__main__':
 result=unittest.TextTestRunner(verbosity=2,resultclass=BudgetResult).run(unittest.defaultTestLoader.loadTestsFromTestCase(Confirmation));raise SystemExit(not result.wasSuccessful())
