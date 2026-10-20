import dataclasses
import json
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import test_harness_repair_20261017 as support
from core.utils.tool_harness.models import Decision
from core.utils.tool_harness.prompt_policy import decision_guidance
from core.utils.tool_harness.relative_plan import complete_relative_plan
from core.utils.person_identity import PersonTurn, activate, deactivate


def actor(person='p', at=1000):
    return PersonTurn('a', person, 0, 1, 'personal', 'matched', 'turn', 'd', 'agent', 1, captured_at=at)


class PromptAndPlanTests(unittest.TestCase):
    def test_assistant_suggestion_does_not_prove_user_ordered(self):
        from core.utils.tool_harness.runtime import grounded_chat
        messages=[{'role':'user','content':'家里没有现成的吃的'},{'role':'assistant','content':'可以点个外卖'}]
        self.assertNotIn('等外卖',grounded_chat('饿得难受还得等外卖。',messages,'我不想动'))
        messages.append({'role':'user','content':'我已经下单外卖了'})
        self.assertIn('等外卖',grounded_chat('还得等外卖。',messages,'还没送到'))
    def test_model_selected_target_needs_explicit_relative_command(self):
        from core.providers.tools.base import ToolDefinition,ToolType
        tool='self_screen_set_brightness'
        definition=ToolDefinition(tool,{'type':'function','function':{'name':tool,'description':'亮度1-5档','parameters':{'type':'object','properties':{'brightness':{'type':'integer','minimum':1,'maximum':100}}}}},ToolType.DEVICE_MCP)
        raw={'mode':'operate','intent':'action','intent_evidence':'调小一点','authorized_writes':[tool],
             'steps':[{'id':'read','tool':'self_get_device_status'}],'finished':False}
        result=complete_relative_plan(Decision(**raw),{},{tool:definition},'还是太刺眼，再调小一点。')
        self.assertEqual(result.steps[-1].relative,-1)
        self.assertTrue(result.finished)
        for query in ['有点太刺眼了','不要再调小一点','如果调小一点会怎么样','调小一点再调大一点','调到3档']:
            self.assertEqual(len(complete_relative_plan(Decision(**raw),{},{tool:definition},query).steps),1,query)
        volume='self_audio_speaker_set_volume'
        guessed=Decision(**(raw|{'authorized_writes':[volume],'steps':[{'id':'set','tool':volume,'arguments':{'volume':15}}]}))
        fixed=complete_relative_plan(guessed,{},{volume:definition},'不是你，别失去不失去的，你再调小声一点，太吵了。')
        self.assertEqual(fixed.steps[0].arguments,{})
        self.assertEqual(fixed.steps[0].relative,-10)

    def test_chat_has_retrieval_and_permissions_but_no_unrelated_domains(self):
        from core.utils.tool_harness.runtime import GUIDANCE
        small=decision_guidance(GUIDANCE, [])
        self.assertLess(len(small),len(GUIDANCE)*.5)
        self.assertIn('retrieve',small)
        self.assertIn('不能先说成功再执行',small)
        setting=decision_guidance(GUIDANCE,['self_screen_set_brightness'])
        self.assertIn('相对音量/亮度',setting)
        self.assertNotIn('明确开始人脸采集',setting)

    def test_only_explicit_single_authorized_relative_goal_is_completed(self):
        raw={'mode':'operate','intent':'action','intent_evidence':'调小一点','authorized_writes':['self_audio_speaker_set_volume'],
             'steps':[{'id':'read','tool':'self_get_device_status'}],'finished':False}
        tools={'self_audio_speaker_set_volume':object()}
        decision=complete_relative_plan(Decision(**raw),{'self_audio_speaker_set_volume':-10},tools)
        self.assertEqual(len(decision.steps),2)
        self.assertEqual(decision.steps[1].depends_on,['read'])
        self.assertEqual(decision.steps[1].relative,-10)
        for override in [{'intent':'query'},{'authorized_writes':[]},{'authorized_writes':['self_audio_speaker_set_volume','memory_add']}]:
            self.assertEqual(len(complete_relative_plan(Decision(**(raw|override)),{'self_audio_speaker_set_volume':-10},tools).steps),1)


class MemoryReadTests(unittest.IsolatedAsyncioTestCase):
    async def test_unavailable_is_not_empty_and_does_not_fall_through_cloud(self):
        from core.utils.recent_memory import search
        cloud=SimpleNamespace(personal=True,search=AsyncMock())
        conn=SimpleNamespace(config={},memory=cloud)
        token=activate(conn,actor())
        try:
            with patch('config.manage_api_client.ManageApiClient') as client:
                client.return_value.request=AsyncMock(side_effect=TimeoutError())
                result=await search(conn,'我爱喝什么')
            self.assertEqual(result['status'],'temporarily_unavailable')
            cloud.search.assert_not_awaited()
        finally:deactivate(token)

    async def test_prioritizes_explicit_facts_and_bounds_related_recall(self):
        from core.utils.recent_memory import search
        conn=SimpleNamespace(config={})
        rows=[{'text':'临时聊天'+str(i),'source':'user_archive_statement'} for i in range(6)]
        rows.append({'text':'我喜欢咖啡','source':'explicit_fact','record_id':'material:1'})
        token=activate(conn,actor())
        try:
            with patch('config.manage_api_client.ManageApiClient') as client:
                client.return_value.request=AsyncMock(return_value={'status':'ok','reliable':True,'text':'原文','items':rows})
                result=await search(conn,'我爱喝什么')
            self.assertEqual(result['items'][0]['record_id'],'material:1')
            self.assertEqual(len(result['items']),4)
        finally:deactivate(token)

    def test_failure_receipt_does_not_claim_missing_records(self):
        from core.utils.tool_harness.contracts import receipt
        from plugins_func.register import ActionResponse,Action
        r=receipt('memory_search',{},ActionResponse(Action.REQLLM,result={'status':'temporarily_unavailable','text':''}),'x')
        self.assertEqual(r.state,'unknown')
        self.assertNotIn('没有记录',r.reply)

    def test_empty_lookup_does_not_support_guessed_missing_reason(self):
        from core.utils.tool_harness.contracts import receipt
        from core.utils.tool_harness.reply_composer import unsafe
        from plugins_func.register import ActionResponse,Action
        result=receipt('memory_search',{},ActionResponse(Action.REQLLM,result={'status':'not_found','items':[],'text':''}),'x')
        self.assertTrue(unsafe('没查到，可能你之前没存过。',[result]))
        self.assertFalse(unsafe('这次没有查到相关记录。',[result]))


class RecentContextTests(unittest.TestCase):
    def setUp(self):
        from core.utils.person_material_outbox import MaterialOutbox
        self.tmp=tempfile.TemporaryDirectory()
        self.outbox=MaterialOutbox(self.tmp.name+'/memory.sqlite3')
        self.patcher=patch('core.utils.person_short_memory.material_outbox',self.outbox)
        self.patcher.start();self.addCleanup(self.patcher.stop);self.addCleanup(self.tmp.cleanup)

    def dialogue(self,a):
        m=SimpleNamespace(role='user',content='我今天累了，还有工作没做完',material_actor_key=a.key,caption_text=None)
        return SimpleNamespace(compact_summary='',source_revision=0,dialogue=[m])

    def test_short_session_context_is_scoped_and_expires(self):
        from core.utils.person_short_memory import persist_compact,load
        a=actor();persist_compact(a,self.dialogue(a))
        self.assertIn('我今天累了',load(a))
        self.assertIn('不是长期事实',load(a))
        self.assertEqual(load(actor('other')),'')
        self.assertEqual(load(dataclasses.replace(a,agent_id='other-agent')),'')
        with patch('core.utils.person_short_memory.time.time',return_value=time.time()+901):
            self.assertEqual(load(a),'')

    def test_stale_save_cannot_restore_invalidated_context(self):
        from core.utils.person_short_memory import persist_compact,load,invalidate
        a=actor();d=self.dialogue(a);persist_compact(a,d);invalidate(a);persist_compact(a,d)
        self.assertEqual(load(a),'')

    def test_old_snapshot_cannot_replace_newer(self):
        from core.utils.person_short_memory import persist_compact,load
        newer=actor(at=2000);persist_compact(newer,self.dialogue(newer))
        older=actor(at=1000);d=self.dialogue(older);d.dialogue[0].content='旧内容'
        persist_compact(older,d)
        self.assertNotIn('旧内容',load(newer))

    def test_other_actor_quotes_are_not_persisted(self):
        from core.utils.person_short_memory import persist_compact,load
        a=actor();d=self.dialogue(actor('other'));persist_compact(a,d)
        self.assertEqual(load(a),'')


class RelativeFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_read_only_plan_finishes_adjustment_in_one_model_request(self):
        from core.providers.tools.base import ToolDefinition,ToolType
        from core.utils.tool_harness.runtime import Harness
        from core.utils.tool_harness.ledger import Ledger
        from plugins_func.register import ActionResponse,Action
        conn=support.connection();conn.person_turn=actor();manager,ex=support.CatalogTests().manager(conn)
        def definition(name,properties,required):
            return ToolDefinition(name,{'type':'function','function':{'name':name,'description':name,'parameters':{'type':'object','properties':properties,'required':required,'additionalProperties':False}}},ToolType.DEVICE_MCP)
        ex.get_tools.return_value.update({
            'self_get_device_status':definition('self_get_device_status',{},[]),
            'self_audio_speaker_set_volume':definition('self_audio_speaker_set_volume',{'volume':{'type':'integer','minimum':0,'maximum':100}},['volume'])})
        async def execute(c,name,args):
            return ActionResponse(Action.REQLLM,result=json.dumps({'audio_speaker':{'volume':40}} if name=='self_get_device_status' else {'ok':True,'volume':args['volume']}))
        ex.execute=AsyncMock(side_effect=execute)
        conn.func_handler=SimpleNamespace(tool_manager=manager)
        decide=MagicMock(return_value={'mode':'operate','intent':'action','intent_evidence':'音量调小一点',
                'authorized_writes':['self_audio_speaker_set_volume'],'steps':[{'id':'read','tool':'self_get_device_status'}],'finished':False})
        ledger=Ledger(':memory:');token=activate(conn,conn.person_turn)
        try:
            with patch.object(Harness,'fast_decision',return_value=None):
                result=await Harness(conn,ledger=ledger,decide=decide).run('音量调小一点',[])
            self.assertEqual(result.error,'',result)
            self.assertEqual(result.model_calls,1,result)
            self.assertEqual(ex.execute.await_count,2)
            self.assertTrue(any(r.state=='completed' and r.arguments.get('volume')==30 for r in result.results),result)
        finally:deactivate(token);ledger.close()
