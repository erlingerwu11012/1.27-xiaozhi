import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock
from core.utils.dialogue import Message
from core.utils.conversation_turn import (
    semantic_check_messages, parse_semantic_check, validated_primary_stream, safe_leading_prefix)

GOOD='{"checks":[{"index":0,"kind":"general_opinion","allowed":true,"code":null,"basis":null}]}'


class SemanticConversationGuardTests(unittest.TestCase):
    def setUp(self):
        self.dialogue = [Message(role='user', content='琴弦刚买了，店家还没发货。别给建议。')]
        self.messages = [{'role': 'user', 'content': self.dialogue[0].content}]
        self.conn = SimpleNamespace(client_abort=False, listen_epoch=1, tts_abort_epoch=1)

    def verdict(self, code, span):
        return json.dumps({'checks': [{'index':0,'kind':'personal_fact','allowed':False,
            'code':code,'basis':self.dialogue[0].content}]}, ensure_ascii=False)

    def test_semantic_checker_catches_alias_without_keyword_match(self):
        raw = self.verdict('contradicted_fact', '新弦还在路上')
        checker = MagicMock(side_effect=[raw, GOOD])
        retry = MagicMock(return_value=iter(['新弦已经买了，还在等店家发货。']))
        out = list(validated_primary_stream(iter(['新弦还在路上。']), retry,
            self.messages, self.dialogue, self.conn, False, checker))
        self.assertEqual(out, ['新弦已经买了，还在等店家发货。'])
        self.assertEqual(checker.call_count, 2)
        self.assertNotIn('新弦还在路上', str(retry.call_args))
        self.assertFalse(self.conn._conversation_gate['fallback'])

    def test_native_tools_never_enter_checker_or_retry(self):
        checker = MagicMock(); retry = MagicMock()
        calls = [SimpleNamespace(id='native-call')]
        stream = [('正文', None), ('', calls)]
        self.assertEqual(list(validated_primary_stream(iter(stream), retry,
            self.messages, self.dialogue, self.conn, True, checker)), stream)
        checker.assert_not_called(); retry.assert_not_called()

    def test_verdict_must_quote_real_user_and_real_candidate(self):
        for raw in ['{"checks":[{"index":2,"kind":"personal_fact","allowed":false,"code":"unsupported_fact","basis":"别给建议。"}]}',
                    '{"checks":[{"index":0,"kind":"personal_fact","allowed":false,"code":"unsupported_fact","basis":"用户没有说这句"}]}',
                    '{"violations":[{"code":"unsupported_fact","span":"新弦","basis":"用户没有说这句"}]}',
                    '{"violations":[{"code":"rewrite","span":"新弦","basis":"琴弦刚买了，店家还没发货。别给建议。"}]}',
                    '{"violations":[],"reply":"润色正文"}', 'not json', '[]',
                    '```json\n{"violations":[]}\n```']:
            self.assertEqual(parse_semantic_check(raw, '新弦还在路上。', self.dialogue),
                             ['validation_unavailable'])
        self.assertEqual(parse_semantic_check(GOOD, '原文', self.dialogue), [])
        self.assertEqual(parse_semantic_check(
            '{"checks":[{"index":0,"kind":"personal_fact","allowed":false,"code":"contradicted_fact","basis":"店家还没发货"}]}',
            '新弦还在路上。', self.dialogue), ['contradicted_fact'])

    def test_unavailable_check_does_not_regenerate_or_emit_unchecked_text(self):
        checker = MagicMock(return_value='invalid'); retry = MagicMock()
        out = list(validated_primary_stream(iter(['新弦还在路上。']), retry,
            self.messages, self.dialogue, self.conn, False, checker))
        self.assertNotIn('新弦还在路上。', out)
        self.assertTrue(self.conn._conversation_gate['fallback'])
        self.assertEqual(self.conn._conversation_gate['attempts'], 1)
        retry.assert_not_called()

    def test_checker_exception_is_visible_failure(self):
        checker = MagicMock(side_effect=TimeoutError); retry = MagicMock()
        out = list(validated_primary_stream(iter(['新弦还在路上。']), retry,
            self.messages, self.dialogue, self.conn, False, checker))
        self.assertEqual(len(out), 1)
        self.assertTrue(self.conn._conversation_gate['fallback']); retry.assert_not_called()

    def test_cancellation_during_semantic_check_cannot_speak_or_retry(self):
        def checker(_):
            self.conn.listen_epoch += 1
            return GOOD
        retry = MagicMock()
        self.assertEqual(list(validated_primary_stream(iter(['新弦还在路上。']), retry,
            self.messages, self.dialogue, self.conn, False, checker)), [])
        retry.assert_not_called()

    def test_second_failure_is_counted_as_failure_not_quality_success(self):
        checker = MagicMock(return_value=self.verdict('contradicted_fact', '新弦还在路上'))
        retry = MagicMock(return_value=iter(['新弦还在路上。']))
        list(validated_primary_stream(iter(['新弦还在路上。']), retry,
            self.messages, self.dialogue, self.conn, False, checker))
        self.assertEqual(checker.call_count, 2); retry.assert_called_once()
        self.assertTrue(self.conn._conversation_gate['fallback'])

    def test_assistant_and_background_never_become_user_evidence(self):
        self.dialogue.insert(0, Message(role='system', content='过期记忆：已经发货。'))
        self.dialogue.insert(1, Message(role='assistant', content='琴弦在路上。'))
        messages = semantic_check_messages('还没发货。', self.dialogue)
        data = json.loads(messages[1]['content'])
        self.assertEqual(data['prior_user_quotes'], [])
        self.assertEqual(data['current_user'], self.dialogue[-1].content)
        self.assertNotIn('过期记忆', str(data)); self.assertNotIn('琴弦在路上', str(data))

    def test_deterministic_violation_skips_extra_semantic_call(self):
        checker = MagicMock(return_value=GOOD)
        retry = MagicMock(return_value=iter(['琴弦还在等发货。']))
        list(validated_primary_stream(iter(['[smirks]先整理琴。']), retry,
            self.messages, self.dialogue, self.conn, False, checker))
        checker.assert_called_once(); retry.assert_called_once()

    def test_real_handler_checks_ordinary_share_with_same_primary_provider(self):
        from test_primary_answer_direct_tts import PrimaryAnswerDirectTtsTests
        fixture=PrimaryAnswerDirectTtsTests();fixture.setUpClass();fixture.setUp()
        try:
            h=fixture.handler();h.config['conversation_validation']={'semantic_enabled':True}
            fixture.primary_with_tools(h,['面条做午饭挺常见，吃起来也方便。'])
            h.llm.response=MagicMock(return_value=iter([GOOD]))
            self.assertTrue(fixture.chat(h,'今天午饭是面条。'))
            h.llm.response_with_functions.assert_called_once()
            h.llm.response.assert_called_once()
            self.assertEqual(h.llm.response.call_args[0][1][0]['role'], 'system')
            self.assertNotIn('tools', h.llm.response.call_args.kwargs)
            self.assertEqual(h.llm.response.call_args.kwargs['temperature'], 0.0)
            self.assertFalse(h._conversation_gate['fallback'])
        finally:
            fixture.doCleanups();fixture.tearDownClass()

    def test_policy_keywords_do_not_override_new_semantic_permission(self):
        self.dialogue.append(Message(role='user',content='换个话题，问我一句吧。'))
        checker=MagicMock(return_value=GOOD); retry=MagicMock()
        out=list(validated_primary_stream(iter(['你喜欢哪种音乐？']),retry,
            self.messages,self.dialogue,self.conn,False,checker))
        self.assertEqual(out,['你喜欢哪种音乐？']); retry.assert_not_called()

    def test_verdict_must_cover_all_sentences_once(self):
        self.assertEqual(parse_semantic_check(GOOD,'第一句。第二句。',self.dialogue),['validation_unavailable'])
        duplicate=json.loads(GOOD); duplicate['checks']*=2
        self.assertEqual(parse_semantic_check(json.dumps(duplicate),'第一句。第二句。',self.dialogue),['validation_unavailable'])

    def test_only_verified_leading_text_is_kept_without_rewriting(self):
        raw=json.dumps({'checks':[
          {'index':0,'kind':'personal_fact','allowed':True,'code':None,'basis':None},
          {'index':1,'kind':'personal_fact','allowed':False,'code':'unsupported_fact','basis':'店家还没发货'}]})
        answer='琴弦已经买了，还没发货。你心里已经预演过好几次换好之后的声音了。'
        checker=MagicMock(return_value=raw);retry=MagicMock()
        out=list(validated_primary_stream(iter([answer]),retry,self.messages,self.dialogue,self.conn,False,checker))
        self.assertEqual(out,['琴弦已经买了，还没发货。'])
        retry.assert_not_called();self.assertTrue(self.conn._conversation_gate['trimmed_prefix'])
        self.assertFalse(self.conn._conversation_gate['fallback'])
        self.dialogue.append(Message(role='user',content='现在什么状态，琴弦换好了吗？'))
        self.assertIsNone(safe_leading_prefix(raw,answer,self.dialogue))

    def test_unsafe_first_sentence_is_never_skipped_to_keep_later_text(self):
        raw=json.dumps({'checks':[
          {'index':0,'kind':'personal_fact','allowed':False,'code':'contradicted_fact','basis':'店家还没发货'},
          {'index':1,'kind':'general_opinion','allowed':True,'code':None,'basis':None}]})
        self.assertIsNone(safe_leading_prefix(raw,'琴弦已经收到了。新东西有时候很让人期待。',self.dialogue))

    def test_user_requested_fiction_is_a_valid_verdict_category(self):
        raw=GOOD.replace('general_opinion','fiction')
        self.assertEqual(parse_semantic_check(raw,'虚构故事。',self.dialogue),[])

    def test_already_aborted_turn_does_not_start_lazy_primary_request(self):
        started=[]
        def primary():
            started.append(True)
            yield '不应生成的文本'
        self.conn.client_abort=True
        self.assertEqual(list(validated_primary_stream(primary(),MagicMock(),
            self.messages,self.dialogue,self.conn,False,MagicMock())),[])
        self.assertEqual(started,[])


if __name__ == '__main__': unittest.main()
