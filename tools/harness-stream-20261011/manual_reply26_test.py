"""One grounding regression plus one separately charged memory speech regression."""
import bootstrap,unittest
from bootstrap import budget

class Replies(unittest.TestCase):
 def setUp(self):self.charge=budget.reserve('case',self.id())
 def tearDown(self):budget.finish(self.charge,{'kind':'deterministic_reply_regression'})
 def test_no_invented_personal_state(self):
  from core.utils.tool_harness.runtime import grounded_chat,reply_preferences,respect_chat_preferences,chat_fallback
  q='今天天色不错，我只是随口说说'
  self.assertEqual(grounded_chat('随口说说也挺好，难得有个好心情。',[],q),'随口说说也挺好。')
  self.assertEqual(grounded_chat('随口说说也挺好，心情不错嘛。',[],q),'随口说说也挺好。')
  self.assertEqual(grounded_chat('心情不错。',[],'我今天心情不错'),'心情不错。')
  self.assertEqual(grounded_chat('好的。这么晚了还不睡，是在忙什么？',[],'正常聊聊'),'好的。')
  self.assertEqual(grounded_chat('忙了一整天，确实够呛。',[],'今天事情多，只是吐槽'),'')
  q='不是要你现在做，刚才只是举例'
  self.assertEqual(respect_chat_preferences('懂了，就是举例。你打算什么时候真做？',reply_preferences([q])),'懂了，就是举例。')
  q='店家刚通知发货了，不过我还没收到'
  self.assertEqual(chat_fallback(q),'店家已经通知发货，你还没收到。')
  self.assertEqual(grounded_chat('刚才确认了音量。',[],'别调了，我只是问问'),'明白，这次不调整。')
 def test_memory_answer_does_not_stream_untrusted_padding(self):
  from core.utils.tool_harness.reply_composer import focused_result_reply,unsafe
  from core.utils.tool_harness.models import StepResult
  from core.utils.tool_harness.speech_output import SpeechOutput
  result=StepResult(call_id='memory',arguments={},tool='memory_search',state='completed',reply='查到一条记忆：台灯叫测试2灯。',payload={'items':[{'text':'台灯叫测试2灯。'}]})
  spoken=[];output=SpeechOutput(lambda:True,lambda:None,spoken.append,lambda:None)
  for raw in ['叫测试2灯。','叫测试2灯。看来这名字很有个性。']:
   output.feed(focused_result_reply(raw,[result]),lambda value:not unsafe(value,[result]))
  final=output.finish(focused_result_reply(raw,[result]))
  self.assertIn('测试2灯',final)
  self.assertNotIn('后面的内容',final)
  self.assertNotIn('看来',final)
  self.assertEqual(''.join(spoken),final)

if __name__=='__main__':unittest.main()
