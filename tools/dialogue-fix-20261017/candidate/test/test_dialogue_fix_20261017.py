import asyncio,json,unittest
from types import SimpleNamespace
from unittest.mock import MagicMock,AsyncMock,patch
import test_harness_repair_20261017 as support
from core.utils.tool_harness.runtime import memory_read_request
from core.utils.tool_harness.request_authority import validate_memory_write


class PersonalQueryTests(unittest.TestCase):
    def test_asr_salutation_and_silence_feedback_do_not_become_reproach_or_diagnosis(self):
        from core.utils.tool_harness.runtime import grounded_chat
        self.assertEqual(grounded_chat('我在呢。这称呼挺别致。',[],'你好，小贱'),'我在呢。')
        self.assertEqual(grounded_chat('我在呢。这名字挺有个性。',[],'你好，小贱'),'我在呢。')
        self.assertNotIn('网络',grounded_chat('我在呢，刚才可能网络波动。',[],'哎，怎么不说话了？'))
        self.assertNotIn('信号',grounded_chat('我在呢，刚才可能信号卡了一下。',[],'哎，怎么不说话了？'))
        prior=[{'role':'assistant','content':'确实挺搞心态的。'}]
        self.assertNotIn('搞心态',grounded_chat('这事确实挺搞心态的。可以先放一放。',prior,'我也不清楚'))
    def test_colloquial_family_name_queries_require_real_lookup(self):
        for q in ['我老婆叫啥名儿啊','那我老婆叫啥呀','我的同事姓什么','我爸爸的名字是什么']:
            self.assertTrue(memory_read_request(q),q)
        for q in ['我老婆应该叫什么名字好','假设我老婆叫啥','你记一下，我老婆叫秦蕊','不要查我老婆的名字']:
            self.assertIsNone(memory_read_request(q),q)

    def test_character_explanation_does_not_allow_wrong_homophone(self):
        q='你改一下，我老婆现在不叫秦蕊了，叫秦章，弓长张'
        with self.assertRaisesRegex(ValueError,'explicit_character'):
            validate_memory_write('memory_correct',{'match':'我老婆叫秦蕊','replacement':'我老婆叫秦章'},q)
        with self.assertRaisesRegex(ValueError,'explicit_character'):
            validate_memory_write('memory_correct',{'match':'我老婆叫秦蕊','replacement':'我老婆叫秦章，弓长张'},q)
        validate_memory_write('memory_correct',{'match':'我老婆叫秦蕊','replacement':'我老婆叫秦张'},q)
        from core.utils.tool_harness.request_authority import normalize_character_spelling
        actual=normalize_character_spelling('memory_correct',{'replacement':'我老婆叫秦章，弓长张'},q)
        self.assertEqual(actual['replacement'],'我老婆叫秦张')
        self.assertEqual(normalize_character_spelling('memory_correct',{'replacement':'我老婆叫秦章'},'我老婆现在叫秦章')['replacement'],'我老婆叫秦章')


class TtsOwnershipTests(unittest.IsolatedAsyncioTestCase):
    async def test_superseded_reply_has_own_start_before_its_audio_and_stop(self):
        from core.handle.sendAudioHandle import sendAudioMessage,send_tts_message
        from core.providers.tts.dto.dto import SentenceType
        c=SimpleNamespace(session_id='session',sentence_id='old',tts_abort_epoch=0,
            tts=SimpleNamespace(tts_audio_first_sentence=True),logger=MagicMock(),config={},
            _cid=lambda:'test',clearSpeakStatus=MagicMock(),close_after_chat=False)
        frames=[]
        async def send(conn,data,**kw):frames.append(json.loads(data));return True,0.1
        with patch('core.handle.sendAudioHandle.is_outbound_allowed',return_value=True),patch('core.handle.sendAudioHandle._device_send',side_effect=send),patch('core.handle.sendAudioHandle.sendAudio',new=AsyncMock()),patch('core.handle.sendAudioHandle._note_tts_sentence_started'),patch('core.handle.sendAudioHandle._finalize_tts_sentence'):
            await sendAudioMessage(c,SentenceType.FIRST,[],'旧回复')
            c.sentence_id='new'  # old stream never reached LAST; flag stays true
            c.tts.tts_audio_first_sentence=False
            await sendAudioMessage(c,SentenceType.FIRST,[],'新回复')
            await send_tts_message(c,'stop',stream_token=('session','old',0))
            await sendAudioMessage(c,SentenceType.LAST,[],None)
        self.assertEqual([(x['request_id'],x['state']) for x in frames],[('old','start'),('old','sentence_start'),('new','start'),('new','sentence_start'),('new','stop')])

    async def test_new_owner_still_starts_if_first_queue_marker_was_dropped(self):
        from core.handle.sendAudioHandle import sendAudioMessage
        from core.providers.tts.dto.dto import SentenceType
        c=SimpleNamespace(session_id='s',sentence_id='fresh',tts_abort_epoch=2,tts=SimpleNamespace(tts_audio_first_sentence=False),logger=MagicMock(),config={},_cid=lambda:'test',clearSpeakStatus=MagicMock(),close_after_chat=False)
        frames=[]
        async def send(conn,data,**kw):frames.append(json.loads(data));return True,0
        with patch('core.handle.sendAudioHandle.is_outbound_allowed',return_value=True),patch('core.handle.sendAudioHandle._device_send',side_effect=send),patch('core.handle.sendAudioHandle.sendAudio',new=AsyncMock()),patch('core.handle.sendAudioHandle._finalize_tts_sentence'):
            await sendAudioMessage(c,SentenceType.MIDDLE,[],None)
            await sendAudioMessage(c,SentenceType.LAST,[],None)
        self.assertEqual([x['state'] for x in frames],['start','stop'])


class RecallTests(unittest.TestCase):
    def test_delete_followup_recalls_real_note_schemas(self):
        from core.utils.tool_harness.retrieval import recall
        from core.utils.tool_harness.models import OperationOutcome,StepResult
        from core.utils.tool_harness.runtime import selection_policy
        from core.providers.tools.base import ToolDefinition,ToolType
        def tool(n):return ToolDefinition(n,{'type':'function','function':{'name':n,'description':n,'parameters':{'type':'object','properties':{}}}},ToolType.DEVICE_MCP)
        tools={n:tool(n) for n in ['note_list','note_delete','note_add']}
        previous=OperationOutcome(mode='operate',reply='一个吃饭提醒',results=[StepResult(state='completed',tool='reminder_list_pending',call_id='r',arguments={},reply='一个吃饭提醒')])
        selected=recall('我不吃了，你把这饼删了吧',tools,selection_policy(),previous=previous)
        self.assertIn('note_list',selected);self.assertIn('note_delete',selected)


class MissingSchemaFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_guessed_name_is_recalled_and_replanned_before_any_dispatch(self):
        from core.utils.tool_harness.runtime import Harness
        from core.utils.tool_harness.ledger import Ledger
        from core.providers.tools.base import ToolDefinition,ToolType
        from plugins_func.register import ActionResponse,Action
        conn=support.connection();conn.config['tool_harness_personalized_replies']=False
        manager,executor=support.CatalogTests().manager(conn)
        name='self_get_device_status'
        executor.get_tools.return_value={name:ToolDefinition(name,{'type':'function','function':{'name':name,'description':'读取设备状态','parameters':{'type':'object','properties':{},'additionalProperties':False}}},ToolType.DEVICE_MCP)}
        executor.execute=AsyncMock(return_value=ActionResponse(Action.REQLLM,result={'audio_speaker':{'volume':40}}))
        conn.func_handler=SimpleNamespace(tool_manager=manager)
        decisions=MagicMock(side_effect=[{'mode':'operate','intent':'query','steps':[{'id':'a','tool':'get_device_status'}]}, {'mode':'operate','intent':'query','steps':[{'id':'a','tool':name}]}])
        recalls=0
        def select(*a,**k):
            nonlocal recalls
            recalls+=1
            return [] if recalls==1 else [name]
        ledger=Ledger(':memory:')
        try:
            with patch('core.utils.tool_harness.retrieval.recall',side_effect=select),patch.object(Harness,'fast_decision',return_value=None):
                result=await Harness(conn,ledger=ledger,decide=decisions).run('查看设备状态',[])
            self.assertEqual(result.error,'',result)
            self.assertEqual(decisions.call_count,2)
            self.assertEqual(executor.execute.await_count,1)
            self.assertEqual(executor.execute.call_args.args[1],name)
        finally:ledger.close()
