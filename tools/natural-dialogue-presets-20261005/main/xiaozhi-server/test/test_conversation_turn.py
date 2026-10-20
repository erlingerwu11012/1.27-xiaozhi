import copy
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock
from core.utils.conversation_turn import attach_conversation_evidence, explicit_discussion, reply_violations, validated_primary_stream
from core.utils.dialogue import Message


class ConversationEvidenceTests(unittest.TestCase):
    def test_advice_variants_and_changed_user_request(self):
        dialogue=[Message(role='user',content='先别指导我，我只是聊聊琴弦。')]
        for answer in ['那就先留着这个念头。','就慢慢挑，不同材质不一样。','等想好了再动手也不迟。','急也没用。']:
            self.assertIn('unsolicited_advice',reply_violations(answer,dialogue))
        dialogue.append(Message(role='user',content='我不想等了，帮我制定计划。'))
        self.assertNotIn('unsolicited_advice',reply_violations('你可以先挑型号。',dialogue))

    def test_latest_fact_correction_overrides_previous_partial_progress(self):
        dialogue=[Message(role='user',content='报告已经写好一半。'),Message(role='user',content='纠正一下，那是提纲，正文从来没写过。')]
        self.assertNotIn('partial_progress_erased',reply_violations('报告正文没写过。',dialogue))

    def test_new_listen_epoch_during_generation_never_retries_or_speaks(self):
        conn=SimpleNamespace(client_abort=False,listen_epoch=1,tts_abort_epoch=1)
        def stream():
            yield ('你可以先想想。',None)
            conn.listen_epoch=2
            yield ('继续',None)
        retry=MagicMock()
        self.assertEqual(list(validated_primary_stream(stream(),retry,[],[Message(role='user',content='别给建议')],conn,True)),[])
        retry.assert_not_called()

    def test_unknown_assembly_and_layout_are_not_confirmed(self):
        dialogue=[Message(role='user',content='刚买了个书架，还没发货，我想把以前的书摆出来。')]
        self.assertIn('unsupported_assembly_claim',reply_violations('等它到了拆开组装就能摆书。',dialogue))
        self.assertIn('unsupported_user_plan',reply_violations('你早就在脑子里安排好位置了。',dialogue))
        self.assertNotIn('unsupported_assembly_claim',reply_violations('有些书架可能需要组装。',dialogue))

    def test_previous_reply_is_not_repeated_as_new_conversation(self):
        answer='书架还没有发货，但是等把那些旧书摆出来，感受应该会和买新书不太一样。'
        dialogue=[Message(role='user',content='书架还没发货。'),Message(role='assistant',content=answer),Message(role='user',content='说说你的看法。')]
        self.assertIn('repeated_previous_reply',reply_violations(answer,dialogue))
        dialogue[-1].content='请重复刚才的话。'
        self.assertNotIn('repeated_previous_reply',reply_violations(answer,dialogue))

    def test_explicit_feedback_and_advice_release(self):
        dialogue=[Message(role='user',content='别反问，也别给建议。'),Message(role='user',content='继续聊。')]
        self.assertIn('unwanted_question',reply_violations('你买哪种？',dialogue))
        self.assertIn('unsolicited_advice',reply_violations('你可以先把书整理好。',dialogue))
        dialogue.append(Message(role='user',content='现在给我建议，怎么整理？'))
        self.assertNotIn('unsolicited_advice',reply_violations('你可以先按作者整理。',dialogue))

    def test_clear_shipping_conflict_and_conditional_language(self):
        dialogue=[Message(role='user',content='刚买了个书架，还没发货。')]
        self.assertIn('pending_changed_to_delivered_or_transit',reply_violations('新书架还在路上。',dialogue))
        self.assertNotIn('pending_changed_to_delivered_or_transit',reply_violations('书架未发货，不能说在路上。',dialogue))
        dialogue.append(Message(role='user',content='更新，书架已经发货了。'))
        self.assertNotIn('pending_changed_to_delivered_or_transit',reply_violations('书架已经在路上。',dialogue))

    def test_bounded_regeneration_never_sends_failed_draft_to_model(self):
        conn=SimpleNamespace(client_abort=False)
        dialogue=[Message(role='user',content='别给方案，只是聊聊。')]
        retry=MagicMock(return_value=iter([('这事确实有点意思。',None)]))
        request=[{'role':'user','content':dialogue[0].content}]
        output=list(validated_primary_stream(iter([('你可以先把东西收起来。',None)]),retry,request,dialogue,conn,True))
        self.assertEqual(output,[('这事确实有点意思。',None)])
        self.assertNotIn('东西收起来',str(retry.call_args))
        self.assertEqual(conn._conversation_gate['attempts'],2)
        self.assertEqual(request[0]['content'],'别给方案，只是聊聊。')

    def test_native_calls_are_never_retried_or_executed_by_text_check(self):
        conn=SimpleNamespace(client_abort=False);retry=MagicMock()
        chunks=[('你可以', [SimpleNamespace(id='real-call')])]
        self.assertEqual(list(validated_primary_stream(iter(chunks),retry,[],[],conn,True)),chunks)
        retry.assert_not_called()

    def test_abort_never_regenerates_and_persistent_violation_is_visible_failure(self):
        retry=MagicMock(return_value=iter(['你可以先试试。']))
        dialogue=[Message(role='user',content='别给建议。')]
        conn=SimpleNamespace(client_abort=True)
        self.assertEqual(list(validated_primary_stream(iter(['坏回答']),retry,[],dialogue,conn,False)),[])
        retry.assert_not_called()
        conn.client_abort=False
        out=list(validated_primary_stream(iter(['你可以先试试。']),retry,[{'role':'user','content':'别给建议。'}],dialogue,conn,False))
        self.assertTrue(conn._conversation_gate['fallback'])
        self.assertEqual(len(out),1)
        retry.assert_called_once()

    def test_clear_discussion_and_mixed_operations_are_separate(self):
        self.assertTrue(explicit_discussion('有本书以前看不进去，现在反而喜欢了。你觉得这是为什么？'))
        self.assertTrue(explicit_discussion('别给方案，我就想吐槽两个会都白开了。'))
        for text in ['你觉得呢，顺便查询伦敦现在的时间', '别教育我，把音量调到30',
                     '我只是随便聊，但帮我记个便签，买书', '现在天气怎么样',
                     '帮我给家人发消息', '今天有点累']:
            self.assertFalse(explicit_discussion(text))

    def test_user_evidence_is_exact_and_assistant_fabrication_is_excluded(self):
        dialogue=[Message(role='user',content='已经买了，尚未发货。'),
                  Message(role='assistant',content='已经送到了，放在阳台。'),
                  Message(role='user',content='目前什么状态？')]
        messages=[{'role':m.role,'content':m.content} for m in dialogue]
        result=attach_conversation_evidence(messages,dialogue)
        self.assertIn('已经买了，尚未发货。',result[-1]['content'])
        self.assertNotIn('阳台',result[-1]['content'])
        self.assertTrue(result[-1]['content'].endswith('目前什么状态？'))
        self.assertEqual(messages[-1]['content'],'目前什么状态？')

    def test_system_memory_does_not_become_user_evidence(self):
        dialogue=[Message(role='system',content='过期记忆：订单到了，画画完成。'),
                  Message(role='user',content='纠正一下，画只画一半。'),
                  Message(role='user',content='现在什么状态？')]
        result=attach_conversation_evidence([{'role':'user','content':'现在什么状态？'}],dialogue)
        self.assertNotIn('订单到了',result[0]['content'])
        self.assertIn('画只画一半',result[0]['content'])

    def test_corrections_and_explicit_feedback_are_preserved_in_order(self):
        texts=['先别反问，也别给建议。','东西还没买。','更新，已经买了但还没发货。','继续聊。']
        result=attach_conversation_evidence([{'role':'user','content':texts[-1]}],
            [Message(role='user',content=t) for t in texts])[0]['content']
        self.assertLess(result.index('东西还没买'),result.index('更新，已经买了'))
        self.assertIn('先别反问，也别给建议',result)

    def test_multimodal_input_and_tool_pairing_are_not_changed(self):
        messages=[{'role':'assistant','content':None,'tool_calls':[{'id':'x'}]},
                  {'role':'tool','tool_call_id':'x','content':'真实回执'},
                  {'role':'user','content':[{'type':'text','text':'看看图片'},
                       {'type':'image_url','image_url':{'url':'data:image/png;base64,AA'}}]}]
        old=copy.deepcopy(messages)
        result=attach_conversation_evidence(messages,[Message(role='user',content=messages[-1]['content'])])
        self.assertEqual(result[:2],old[:2])
        self.assertEqual(result[-1]['content'][1:],old[-1]['content'])
        self.assertEqual(messages,old)

    def test_context_is_bounded_without_truncating_current_input(self):
        dialogue=[Message(role='user',content='已经'+str(i)+'文'*2000) for i in range(40)]
        dialogue.append(Message(role='user',content='当前'+'字'*5000))
        result=attach_conversation_evidence([{'role':'user','content':dialogue[-1].content}],dialogue)[0]['content']
        self.assertLess(len(result)-len(dialogue[-1].content),5000)
        self.assertTrue(result.endswith(dialogue[-1].content))

    def test_no_evidence_does_not_create_a_request_or_extra_call(self):
        messages=[{'role':'system','content':'人格原文'}]
        self.assertIs(attach_conversation_evidence(messages,[]),messages)

    def test_actual_handler_injects_context_once_without_a_second_model(self):
        from test_primary_answer_direct_tts import PrimaryAnswerDirectTtsTests
        fixture=PrimaryAnswerDirectTtsTests();fixture.setUpClass();fixture.setUp()
        try:
            h=fixture.handler();h.config['conversation_validation']={'enabled':True}
            h.dialogue.put(Message(role='user',content='已买，未发货。'))
            fixture.primary_with_tools(h,['东西还在等发货，这种期待也挺有意思。'])
            self.assertTrue(fixture.chat(h,'别给建议，我就聊聊。'))
            h.llm.response.assert_not_called()
            h.llm.response_with_functions.assert_called_once()
            request=h.llm.response_with_functions.call_args[0][1]
            last_user=next(m for m in reversed(request) if m['role']=='user')
            self.assertEqual(last_user['content'].count('[本轮回应检查'),1)
            self.assertIn('别给建议，我就聊聊',last_user['content'])
            self.assertNotIn('[本轮回应检查',h.dialogue.dialogue[-2].content)
        finally:
            fixture.doCleanups();fixture.tearDownClass()

if __name__=='__main__': unittest.main()
