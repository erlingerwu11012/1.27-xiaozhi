import copy
import unittest
from unittest.mock import MagicMock
from config.config_loader import apply_local_only_top_level


class ConversationValidationConfigTests(unittest.TestCase):
    def test_absent_switch_preserves_streaming_and_original_request(self):
        from test_primary_answer_direct_tts import PrimaryAnswerDirectTtsTests
        fixture=PrimaryAnswerDirectTtsTests();fixture.setUpClass();fixture.setUp()
        try:
            h=fixture.handler(functions=None)
            h.llm.response=MagicMock(return_value=iter(['正常','聊两句。']))
            self.assertTrue(fixture.chat(h,'我只是正常聊两句，别给建议。'))
            h.llm.response.assert_called_once()
            messages=h.llm.response.call_args.args[1]
            self.assertFalse(any('本轮回应检查' in str(m.get('content')) for m in messages))
            self.assertEqual([e.content_detail for e in fixture.text_events(h)],['正常','聊两句。'])
            self.assertIsNone(h._conversation_gate)
        finally:fixture.doCleanups();fixture.tearDownClass()

    def test_invalid_local_switch_does_not_enable_or_crash(self):
        from types import SimpleNamespace
        from core.utils.conversation_turn import conversation_validation_mode
        for settings in ('yes', ['qwen3.8-max'], {'enabled':'true'},
                         {'enabled':True,'model_names':'qwen3.8-max'}):
            conn=SimpleNamespace(config={'conversation_validation':settings},
                                 llm=SimpleNamespace(model_name='qwen3.8-max'))
            self.assertEqual(conversation_validation_mode(conn),(False,False))

    def test_local_activation_survives_api_merge_without_changing_providers(self):
        for enabled in (True,False):
            api={'ASR':{'chosen':'api'},'LLM':{'chosen':'api'},'TTS':{'chosen':'api'},
                 'conversation_validation':{'semantic_enabled':not enabled}}
            old=copy.deepcopy(api)
            local={'ASR':{'chosen':'local'},'conversation_validation':
                   {'semantic_enabled':enabled,'model_names':['qwen3.8-max']}}
            apply_local_only_top_level(local,api)
            self.assertEqual(api['conversation_validation'],local['conversation_validation'])
            for provider in ('ASR','LLM','TTS'):self.assertEqual(api[provider],old[provider])

    def test_unqualified_custom_model_does_not_receive_semantic_requests(self):
        from test_primary_answer_direct_tts import PrimaryAnswerDirectTtsTests
        fixture=PrimaryAnswerDirectTtsTests();fixture.setUpClass();fixture.setUp()
        try:
            h=fixture.handler();h.config['conversation_validation']={
               'semantic_enabled':True,'model_names':['qwen3.8-max']}
            fixture.primary_with_tools(h,['今天吃面条挺方便。'])
            h.llm.model_name='custom-untested-model'
            self.assertTrue(fixture.chat(h,'今天午饭是面条。'))
            h.llm.response.assert_not_called()
            h.llm.response_with_functions.assert_called_once()
            self.assertIsNone(h._conversation_gate)
        finally:fixture.doCleanups();fixture.tearDownClass()

    def test_selected_default_model_receives_one_check_not_a_polishing_model(self):
        from test_primary_answer_direct_tts import PrimaryAnswerDirectTtsTests
        fixture=PrimaryAnswerDirectTtsTests();fixture.setUpClass();fixture.setUp()
        try:
            h=fixture.handler();h.config['conversation_validation']={
               'semantic_enabled':True,'model_names':['qwen3.8-max']}
            fixture.primary_with_tools(h,['今天吃面条挺方便。']);h.llm.model_name='qwen3.8-max'
            h.llm.response=MagicMock(return_value=iter([
               '{"checks":[{"index":0,"kind":"general_opinion","allowed":true,"code":null,"basis":null}]}']))
            self.assertTrue(fixture.chat(h,'今天午饭是面条。'))
            h.llm.response.assert_called_once();h.llm.response_with_functions.assert_called_once()
            self.assertFalse(h._conversation_gate['fallback'])
        finally:fixture.doCleanups();fixture.tearDownClass()


if __name__=='__main__':unittest.main()
