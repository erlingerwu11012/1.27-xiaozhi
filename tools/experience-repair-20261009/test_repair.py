import bootstrap
import asyncio,json,unittest,types,dataclasses
from pathlib import Path
from unittest.mock import MagicMock
from test_support import connection,decision,step
from stateful_device import StatefulDevice
from core.utils.tool_harness.contracts import receipt
from core.utils.tool_harness.presentation import reminder_reply,memory_items,safe_speech
from core.utils.tool_result import DeviceToolError
from plugins_func.register import Action,ActionResponse
from core.utils.person_identity import PersonTurn,activate,deactivate
class RepairTests(unittest.IsolatedAsyncioTestCase):
    def make(self,decide=None):return connection(StatefulDevice(),decide)
    async def test_listen_noise_does_not_cancel(self):
        c,m,h=self.make();scope,epoch=h.scope(),h.epoch();c.listen_epoch+=1;c.utterance_id=9;c.tts_abort_epoch=4;c.client_abort=True
        self.assertTrue(h.valid(scope,epoch))
    async def test_explicit_cancel_invalidates(self):
        c,m,h=self.make();scope,epoch=h.scope(),h.epoch();c._harness_explicit_abort_generation=1;self.assertFalse(h.valid(scope,epoch))
    async def test_new_accepted_request_invalidates(self):
        c,m,h=self.make();scope,epoch=h.scope(),h.epoch();c._harness_request_generation=1;self.assertFalse(h.valid(scope,epoch))
    async def test_connection_replacement_invalidates(self):
        c,m,h=self.make();scope,epoch=h.scope(),h.epoch();c.session_id='new';self.assertFalse(h.valid(scope,epoch))
    async def test_late_model_with_ingress_noise_still_replies(self):
        import time
        c,m,h=self.make(lambda _:(time.sleep(.12) or {'mode':'chat','reply':'你好，我在。'}))
        task=asyncio.create_task(h.run('你好',[]));await asyncio.sleep(.03);c.listen_epoch+=1;c.utterance_id=22;c.tts_abort_epoch=1
        out=await task;self.assertEqual(out.reply,'你好，我在。');self.assertFalse(out.interrupted)
    async def test_percentage_maps_actual_level_and_persists(self):
        c,m,h=self.make();out=await h.run('亮度调到百分之九十',[])
        self.assertEqual(m.state['level'],4);self.assertEqual(out.results[-1].state,'completed');self.assertIn('4档',out.reply)
        restored=StatefulDevice(m.path);self.assertEqual(restored.state['level'],4)
    async def test_invalid_brightness_gap_never_sent(self):
        c,m,h=self.make(lambda _:decision(step('self_screen_set_brightness',{'brightness':40})))
        out=await h.run('亮度调到40',[]);self.assertFalse(m.calls);self.assertNotIn('已调到',out.reply)
    async def test_relative_brightness(self):
        c,m,h=self.make();out=await h.run('亮一点',[]);self.assertEqual(m.state['level'],4);self.assertIn('4档',out.reply);self.assertNotIn('当前亮度',out.reply)
    async def test_relative_volume(self):
        c,m,h=self.make();out=await h.run('大声一点',[]);self.assertEqual(m.state['volume'],60);self.assertNotIn('当前音量',out.reply)
    async def test_reminder_query_human_result(self):
        c,m,h=self.make(lambda _:decision(step('reminder_list_pending')))
        out=await h.run('还有啥没办完',[]);self.assertIn('拿快递',out.reply);self.assertNotIn('instance_id',out.reply);self.assertNotIn('{',out.reply)
    async def test_card_action_changes_state_and_confirms(self):
        c,m,h=self.make(lambda _:decision(step('reminder_get_current',id='r'),step('reminder_action',{'instance_id':{'$ref':{'step':'r','path':'instance_id'}},'revision':{'$ref':{'step':'r','path':'revision'}},'action':'primary','minutes':0,'snooze_at':0},id='w',depends_on=['r'])))
        out=await h.run('我拿完了，标记当前提醒完成',[])
        self.assertFalse(m.state['card']['active']);self.assertIn('已确认完成',out.reply);self.assertNotIn('{',out.reply)
    async def test_memory_archive_is_not_a_fact(self):
        self.assertEqual(memory_items({'text':'[来源:3 时间:今天 用户]喜欢咖啡\n[来源:4 助手]好'}),[])
    async def test_memory_fact_has_stable_id(self):
        x=memory_items({'items':[{'record_id':'archive:123','text':'我喜欢咖啡'}]});self.assertEqual(x[0]['record_id'],'archive:123')
    async def test_no_raw_json_speech(self):self.assertNotIn('{',safe_speech('{"items":[]}'))
    async def test_no_punctuation_only_speech(self):self.assertEqual(safe_speech('。！…'),'')
    async def test_no_emotion_tag_speech(self):self.assertEqual(safe_speech('[smirks]你好'),'你好')
    async def test_specific_vision_failure(self):self.assertIn('视觉服务尚未就绪',DeviceToolError('vision_not_ready').user_message)
    async def test_legacy_vision_prefix(self):self.assertEqual(DeviceToolError('', 'vision_not_ready: missing').code,'vision_not_ready')
    async def test_failure_not_repeated(self):
        c,m,h=self.make(lambda _:decision(step('self_camera_take_photo',{'question':'桌上有什么'})))
        m.faults['self_camera_take_photo']=ActionResponse(Action.REQLLM,result={'ok':False,'errorCode':'vision_not_ready','message':'视觉服务尚未就绪'})
        out=await h.run('拍个照看看',[]);self.assertNotIn('self_camera',out.reply);self.assertNotIn('不会自动重复',out.reply)
    async def test_explicit_retry_new_request_is_not_deduplicated(self):
        c,m,h=self.make(lambda _:decision(step('self_camera_take_photo',{'question':'桌上有什么'})))
        m.faults['self_camera_take_photo']=ActionResponse(Action.REQLLM,result={'ok':False,'errorCode':'vision_not_ready','message':'视觉服务尚未就绪'})
        await h.run('拍个照看看',[]);m.faults.clear();c._harness_request_generation=2
        # Ledger write idempotency does not apply to this safe read-like request.
        out=await h.run('再拍一次',[]);self.assertEqual(len(m.calls),2);self.assertEqual(out.results[-1].state,'completed')
if __name__=='__main__':
    from bootstrap import budget,stage
    class Result(unittest.TextTestResult):
        def startTest(self,test):budget.reserve('case',test.id());super().startTest(test)
    r=unittest.TextTestRunner(verbosity=2,resultclass=Result).run(unittest.defaultTestLoader.loadTestsFromTestCase(RepairTests))
    (stage/'repair-tests-summary.json').write_text(json.dumps({'run':r.testsRun,'failures':[(str(t),s) for t,s in r.failures],'errors':[(str(t),s) for t,s in r.errors],'budget':budget.report()},ensure_ascii=False,indent=2));raise SystemExit(not r.wasSuccessful())
