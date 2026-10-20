"""Regression of actual receipt -> spoken result, with no second model."""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from plugins_func.register import Action, ActionResponse
from core.utils.tool_fact_reply import verified_tool_reply
from core.utils.dialogue import Dialogue, Message
from core.utils.turn_context import render_turn_context
from test_primary_answer_direct_tts import PrimaryAnswerDirectTtsTests


class VerifiedToolFactsTests(PrimaryAnswerDirectTtsTests):
    def receipt(self, text='🌍 Europe/London 当前时间：\n2026年10月05日 11:49:53 (Monday)\n时区：UTC+1'):
        return ActionResponse(action=Action.REQLLM, result=text)

    def call(self, zone='Europe/London'):
        return {'name': 'get_world_time', 'id': 'time-test', 'arguments': json.dumps({'timezone': zone})}

    def test_london_receipt_is_spoken_exactly_without_model(self):
        h = self.handler()
        h.config['operation_control'] = {'enabled': True}
        h.chat = MagicMock(side_effect=AssertionError('facts must not be rewritten by model'))
        h._handle_function_result([(self.receipt(), self.call())], 0, _tts_turn=('tts', 1))
        self.assertEqual(self.text_events(h)[0].content_detail, '伦敦当地时间是2026年10月5日，11点49分。')
        h.chat.assert_not_called()
        self.assertEqual([m.role for m in h.dialogue.dialogue], ['system','assistant','tool','assistant'])
        self.assertEqual(h.dialogue.dialogue[1].tool_calls[0]['id'], h.dialogue.dialogue[2].tool_call_id)

    def test_mismatched_zone_and_malformed_receipt_do_not_invent_time(self):
        for raw in ['🌍 Asia/Tokyo 当前时间：\n2026年10月05日 11:49:53 (Monday)\n时区：UTC+9',
                    '执行失败', '', '11:49', '2026-10-05 11:49',
                    '🌍 Europe/London 当前时间：\n2026年10月05日 11:49:53 (Monday)\n时区：UTC+8']:
            with self.subTest(raw=raw):
                self.assertIn('不能确认', verified_tool_reply(self.receipt(raw), self.call()))

    def test_winter_and_half_hour_offsets_are_not_recomputed_as_shanghai(self):
        cases = [('Europe/London', '2026年12月07日 00:05:00 (Monday)', '+0', '00点05分'),
                 ('Asia/Kolkata', '2026年10月05日 23:59:00 (Monday)', '+5:30', '23点59分')]
        for zone, timestamp, offset, expected in cases:
            self.assertIn(expected, verified_tool_reply(self.receipt(f'🌍 {zone} 当前时间：\n{timestamp}\n时区：UTC{offset}'), self.call(zone)))

    def test_nested_device_status_and_partial_status(self):
        call={'name':'self_get_device_status','arguments':'{}'}
        body={'audio_speaker':{'output_volume':30},'screen':{'brightness':80}}
        result=ActionResponse(action=Action.REQLLM,result=json.dumps(body))
        self.assertEqual(verified_tool_reply(result,call),'当前音量是30，屏幕亮度是80。')
        result.result='{"volume":true,"brightness":101}'
        self.assertEqual(verified_tool_reply(result,call),'没有读到可信的音量或亮度数值。')
        result.result='{"volume":30,"ok":false}'
        self.assertEqual(verified_tool_reply(result,call),'没有读到可信的设备状态。')

    def test_open_ended_and_error_results_keep_existing_handler(self):
        self.assertIsNone(verified_tool_reply(self.receipt('杯子'),{'name':'self_camera_take_photo','arguments':'{}'}))
        result=ActionResponse(action=Action.ERROR,response='查询失败')
        self.assertIsNone(verified_tool_reply(result,self.call()))

    def test_write_receipt_requires_confirmed_actual_target(self):
        call={'name':'self_audio_speaker_set_volume','arguments':'{"volume":30}'}
        for body, expected in [({'ok':True,'volume':30},'音量已调到30。'),
                               ({'ok':True,'volume':50},'还不能确认'),
                               ({'accepted':True},'还不能确认完成')]:
            self.assertIn(expected,verified_tool_reply(ActionResponse(action=Action.REQLLM,result=json.dumps(body)),call))

    def test_memory_is_reference_not_summary_generation_instruction(self):
        d=Dialogue();d.put(Message(role='system',content='直接交谈'))
        d.compact_summary='用户希望聊天'
        d.put(Message(role='user',content='咖啡机还没发货'))
        messages=d.get_llm_dialogue_with_memory(static_system=True)
        self.assertIn('不要朗读、续写摘要',messages[1]['content'])
        self.assertEqual(messages[-1]['content'],'咖啡机还没发货')
        self.assertIn('背景数据',render_turn_context({'memory_text':'旧记忆'}))

    def test_server_mcp_error_envelope_never_announces_success(self):
        import asyncio
        from core.providers.tools.server_mcp.mcp_executor import ServerMCPExecutor
        async def run():
            executor=ServerMCPExecutor(SimpleNamespace())
            executor._initialized=True
            async def execute(*args):
                return {'isError':True,'content':[{'type':'text','text':'已将系统音量设置为30'}]}
            executor.mcp_manager=SimpleNamespace(execute_tool=execute)
            result=await executor.execute(SimpleNamespace(),'get_world_time',{})
            self.assertEqual(result.action,Action.ERROR)
            self.assertIn('工具返回错误',result.response)
        asyncio.run(run())
