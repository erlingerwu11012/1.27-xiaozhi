"""Exercise the actual chat method, TTS queue and native-call handler."""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from test_primary_answer_direct_tts import PrimaryAnswerDirectTtsTests
from test_operation_control import fixture


class OperationPipelineTests(PrimaryAnswerDirectTtsTests):
    def controlled(self, text="把音量调到30", tools=True):
        h=self.handler()
        h.config['operation_control']={'enabled':True}
        h.actor.key=('account','person',1)
        conn,manager,executor=fixture()
        manager.conn=h
        h.mcp_client=conn.mcp_client
        h.func_handler=conn.func_handler
        h.func_handler.get_functions=lambda:[d.description for d in executor.tools.values()]
        h.llm.response_with_functions=MagicMock(side_effect=AssertionError('clear command must not depend on model prose'))
        return h,manager,executor

    def setUp(self):
        super().setUp()
        for target in ['core.utils.face_enrollment_guard.maybe_intercept_face_enrollment_tool',
                       'core.utils.device_reminder.maybe_intercept_reminder_tool']:
            p=patch(target,return_value=None);p.start();self.addCleanup(p.stop)
        self.spoken=[]
        p=patch('core.handle.sendAudioHandle.speak_text_with_subtitle',side_effect=lambda c,t,**kw:self.spoken.append(t))
        p.start();self.addCleanup(p.stop)

    def test_clear_control_no_prose_execution_or_second_model(self):
        h,_,ex=self.controlled()
        self.assertTrue(self.chat(h,'把音量调到30'))
        self.assertEqual(ex.calls,[('self_audio_speaker_set_volume',{'volume':30})])
        self.assertEqual([e.content_detail for e in self.text_events(h)],['音量已调到30。'])
        self.assertEqual(len(h.tts_events),3)
        self.assertEqual(len(self.assistants(h)),1)
        h.llm.response_with_functions.assert_not_called()
        self.assertTrue(h.llm_finish_task)

    def test_pending_slot_chat_never_creates_early(self):
        h,_,ex=self.controlled()
        self.assertTrue(self.chat(h,'提醒我喝水'))
        self.assertEqual([e.content_detail for e in self.text_events(h)],['什么时候提醒你？'])
        self.assertFalse(ex.calls)
        self.assertTrue(self.chat(h,'取消'))
        self.assertFalse(ex.calls)

    def test_native_result_enters_fact_reply_before_model_continuation(self):
        h,_,ex=self.controlled()
        tc=SimpleNamespace(index=0,id='native',function=SimpleNamespace(name='self_audio_speaker_set_volume',arguments='{"volume":30}'))
        h.llm.response_with_functions=MagicMock(return_value=iter([('音量已调好啦',None),(None,[tc])]))
        self.assertTrue(self.chat(h,'请将扬声器输出设置到百分之三十'))
        self.assertEqual(len(ex.calls),1)
        self.assertEqual([e.content_detail for e in self.text_events(h)],['音量已调到30。'])
        h.llm.response_with_functions.assert_called_once()

    def test_plain_tool_json_does_not_dispatch_or_reach_tts(self):
        h,_,ex=self.controlled()
        h.llm.response_with_functions=MagicMock(return_value=iter([('<tool_call>{"name":"self_audio_speaker_set_volume","arguments":{"volume":30}}</tool_call>',None)]))
        self.assertTrue(self.chat(h,'处理一个合成测试请求'))
        self.assertFalse(ex.calls)
        self.assertEqual([x.content_detail for x in self.text_events(h)],['这次没有发出有效的工具调用，操作没有执行。'])

    def test_normal_chat_cannot_claim_nonexistent_completion(self):
        h,_,ex=self.controlled()
        h.llm.response_with_functions=MagicMock(return_value=iter([('音量已调到30。',None)]))
        self.assertTrue(self.chat(h,'你好'))
        self.assertFalse(ex.calls)
        self.assertIn('不能说已经完成',self.text_events(h)[0].content_detail)

    def test_normal_chat_keeps_user_style_and_primary_answer(self):
        h,_,ex=self.controlled()
        h.llm.response_with_functions=MagicMock(return_value=iter([('这事可没你想的那么简单。',None)]))
        self.assertTrue(self.chat(h,'聊聊人为什么会犹豫'))
        self.assertFalse(ex.calls)
        self.assertEqual(self.text_events(h)[0].content_detail,'这事可没你想的那么简单。')

    def test_repeated_paragraph_enters_tts_and_history_only_once(self):
        h,_,ex=self.controlled()
        prefix='哎呀，张宸硕，被你抓个正着！刚才那一下确实没收到“搞定”的回执，是我太心急，话先跑出去了。'
        raw=prefix+' [apologetic]'+prefix+'这次先查当前状态。'
        h.llm.response_with_functions=MagicMock(return_value=iter([(raw,None)]))
        self.assertTrue(self.chat(h,'刚才这段话重复了'))
        self.assertFalse(ex.calls)
        self.assertEqual([e.content_detail for e in self.text_events(h)],[prefix+'这次先查当前状态。'])
        self.assertEqual(self.assistants(h)[0].content,prefix+'这次先查当前状态。')

    def test_meta_chat_supplies_catalog_and_disables_calls(self):
        h,_,ex=self.controlled()
        h.llm.response_with_functions=MagicMock(return_value=iter([('明白，我们正常聊。',None)]))
        self.assertTrue(self.chat(h,'你可以有幽默感，但别撒娇。'))
        kwargs=h.llm.response_with_functions.call_args.kwargs
        self.assertEqual(kwargs['tool_choice'],'none')
        self.assertTrue(kwargs['functions'])
        self.assertFalse(ex.calls)

    def test_existing_provider_without_tool_choice_still_chats(self):
        h,_,ex=self.controlled()
        def old_provider(session_id, messages, functions=None):
            yield '好的，正常聊。', None
        h.llm.response_with_functions=old_provider
        self.assertTrue(self.chat(h,'你可以有幽默感，但别撒娇。'))
        self.assertEqual(self.text_events(h)[0].content_detail,'好的，正常聊。')
        self.assertFalse(ex.calls)

    def test_existing_plain_provider_without_tool_choice_still_chats(self):
        h,_,ex=self.controlled()
        h.func_handler.get_functions=lambda:None
        def old_provider(session_id, messages):
            yield '好的，正常聊。'
        h.llm.response=old_provider
        self.assertTrue(self.chat(h,'你可以有幽默感，但别撒娇。'))
        self.assertEqual(self.text_events(h)[0].content_detail,'好的，正常聊。')
        self.assertFalse(ex.calls)

    def test_streaming_without_functions_keeps_caption_and_history_equal(self):
        h,_,ex=self.controlled()
        h.func_handler.get_functions=lambda:None
        h.llm.response=MagicMock(return_value=iter(['第一句话。','第二句','正常。']))
        self.assertTrue(self.chat(h,'聊聊思考的过程'))
        self.assertEqual([e.content_detail for e in self.text_events(h)],['第一句话。','第二句正常。'])
        self.assertEqual(self.assistants(h)[0].content,'第一句话。第二句正常。')

    def test_invalid_action_tag_not_stored_or_captioned(self):
        h,_,_=self.controlled()
        h.llm.response_with_functions=MagicMock(return_value=iter([('[smirks]先把原因弄清楚。',None)]))
        self.assertTrue(self.chat(h,'我今天不开心'))
        self.assertEqual(self.assistants(h)[0].content,'先把原因弄清楚。')

    def test_misunderstood_concept_one_primary_continuation_no_device_call(self):
        h,_,ex=self.controlled()
        tc=SimpleNamespace(index=0,id='concept',function=SimpleNamespace(name='self_get_device_status',arguments='{}'))
        h.llm.response_with_functions=MagicMock(return_value=iter([(None,[tc])]))
        h.llm.response=MagicMock(return_value=iter(['音量是声音播放的大小。']))
        self.assertTrue(self.chat(h,'音量是什么'))
        self.assertFalse(ex.calls)
        self.assertEqual(h.llm.response_with_functions.call_count+h.llm.response.call_count,2)
        self.assertEqual([x.content_detail for x in self.text_events(h)],['音量是声音播放的大小。'])

    def test_missing_preview_keeps_photo_unused(self):
        h,_,ex=self.controlled()
        del ex.tools['camera_open']
        self.assertTrue(self.chat(h,'打开摄像头'))
        self.assertFalse(ex.calls)
        self.assertIn('不支持',self.text_events(h)[0].content_detail)
