"""Regression cases from Oct 7; all tool/device transports are simulated."""
import asyncio
import json
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config.logger
config.logger.setup_logging = lambda: MagicMock()
from core.utils.recipient_resolver import extract_recipient_selector_from_text, ProfileDirectory, ProfileRecord
from core.utils.unified_recipient_resolver import resolve_unified_recipient_for_conn
from core.utils.operation_control import get_control, guard_reply
from core.utils.reminder_tool_contracts import describe_tool, reminder_action_completed
from core.utils.tool_result import DeviceToolError
from plugins_func.register import Action, ActionResponse
from core.providers.tts.qwen_audio_tts_plus import TTSProvider


class RecipientTests(unittest.IsolatedAsyncioTestCase):
    def test_content_is_not_a_person(self):
        for phrase in ['一分钟后提醒喝水哦。', '提醒喝水', '提醒一下吃药吧',
                       '两分钟后提醒交报告', '提醒出门带伞', '提醒睡觉', '提醒休息一下']:
            with self.subTest(phrase=phrase):
                self.assertIsNone(extract_recipient_selector_from_text(phrase))
        self.assertEqual(extract_recipient_selector_from_text('提醒张三喝水'), '张三')
        self.assertEqual(extract_recipient_selector_from_text('提醒张三交报告'), '张三')
        self.assertEqual(extract_recipient_selector_from_text('给小红设置提醒'), '小红')
        self.assertEqual(extract_recipient_selector_from_text('提醒我喝水'), '我')
        self.assertEqual(extract_recipient_selector_from_text('提醒来福喝水', ['来福']), '来福')

    async def test_speaker_default_and_explicit_other_are_preserved(self):
        directory = ProfileDirectory(account_id='a', profiles=[
            ProfileRecord('usr_a', '小明', 'active', 'a'),
            ProfileRecord('usr_b', '小红', 'active', 'a')])
        conn = SimpleNamespace(config={}, account_id='a', device_id='dev',
            current_speaker_user={'user_id': 'usr_a', 'display_name': '小明'})
        with patch('core.utils.unified_recipient_resolver._fetch_directory', AsyncMock(return_value=directory)):
            for text, expected in [('一分钟后提醒喝水哦。', 'usr_a'),
                                   ('一分钟后提醒我喝水', 'usr_a'),
                                   ('一分钟后提醒小红喝水', 'usr_b')]:
                result = await resolve_unified_recipient_for_conn(conn, user_text=text)
                self.assertEqual(result.recipient_person_id, expected)
            result = await resolve_unified_recipient_for_conn(conn, user_text='提醒张三喝水')
            self.assertFalse(result.ok_for_create)
            conn.current_speaker_user = None
            result = await resolve_unified_recipient_for_conn(conn, user_text='提醒喝水哦。')
            self.assertEqual(result.recipient_person_id, 'all')


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.conn = SimpleNamespace(config={'operation_control': {'enabled': True}})
        get_control(self.conn).begin('我喝过了，取消吧', 'actor')

    def test_actual_false_claims_are_blocked(self):
        for text in ['好嘞，卡片关掉，世界清静了。', '倒计时开始滴答了。',
                     '好的，那就不提醒了。', '提醒已完成。', '提醒已永久删除。',
                     '没看明白，但提醒已完成。']:
            self.assertIn('没有确认', guard_reply(self.conn, text))

    def test_read_or_log_receipt_does_not_authorize_action(self):
        control = get_control(self.conn)
        control.ledger[('behavior_log', '{}')] = ActionResponse(Action.REQLLM, result='记录成功')
        control.ledger[('reminder_get_current', '{}')] = ActionResponse(Action.REQLLM, result='{}')
        self.assertIn('没有确认', guard_reply(self.conn, '提醒已完成。'))

    def test_only_matching_success_authorizes_claim(self):
        control = get_control(self.conn)
        args = {'instance_id': 'n7', 'revision': 2, 'action': 'primary'}
        result = ActionResponse(Action.RESPONSE, response='提醒已完成', result='提醒已完成')
        result.operation_state = 'completed'
        control.ledger[('reminder_action', json.dumps(args))] = result
        self.assertEqual(guard_reply(self.conn, '提醒已完成。'), '提醒已完成。')
        self.assertIn('没有确认', guard_reply(self.conn, '提醒已永久删除。'))
        self.assertFalse(reminder_action_completed(args, '已接收'))
        self.assertFalse(reminder_action_completed(args, '提醒已永久删除'))
        self.assertTrue(reminder_action_completed(args, '提醒已完成'))
        self.assertFalse(reminder_action_completed(args, {'ok': True, 'status': 'completed', 'instance_id': 'other', 'action': 'primary'}))

    def test_negative_and_hypothetical_chat_is_unchanged(self):
        for text in ['没有确认回执，不能说提醒已完成。', '如果倒计时开始会怎样？',
                     '“提醒已完成”只是一个例子。', '我喜欢那种倒计时的声音。']:
            self.assertEqual(guard_reply(self.conn, text), text)

    def test_error_code_is_not_lost(self):
        err = DeviceToolError(None, 'identity_mismatch: 当前不是此提醒的接收人')
        self.assertEqual(err.code, 'identity_mismatch')
        self.assertIn('接收人', err.user_message)
        self.assertEqual(DeviceToolError(None, 'arbitrary: unknown').code, 'unclassified_tool_error')
        self.assertIn('没有保存', DeviceToolError('storage_full').user_message)

    def test_catalog_copy_is_not_modified(self):
        original = {'function': {'name': 'behavior_log', 'description': '自动调用', 'parameters': {'type': 'object'}}}
        edited = describe_tool(original)
        self.assertEqual(original['function']['description'], '自动调用')
        self.assertIn('不能创建提醒', edited['function']['description'])
        self.assertEqual(edited['function']['parameters'], original['function']['parameters'])

    def test_adjacent_repeated_paragraph_with_tag_is_removed(self):
        prefix = '哎呀，张宸硕，被你抓个正着！刚才那一下确实没收到“搞定”的回执，是我太心急，话先跑出去了。'
        text = prefix + ' [apologetic]' + prefix + '这次应先查当前状态。'
        self.assertEqual(guard_reply(self.conn, text), prefix + '这次应先查当前状态。')
        normal = '想想也挺好。这是你以前说过的事。想想也挺好。'
        self.assertEqual(guard_reply(self.conn, normal), normal)

    def test_missing_receipt_feedback_is_not_retry_authorization(self):
        control = get_control(self.conn)
        control.begin('那你刚才也没有去找到回执。', 'actor')
        self.assertIsNotNone(control.validate_intent('self_screen_set_brightness', {'brightness': 100}))
        self.assertIsNone(control.validate_intent('self_get_device_status', {}))


class AssetTests(unittest.IsolatedAsyncioTestCase):
    def provider(self, outcome='ok'):
        class Socket:
            def __init__(self):
                self.sent = []; self.closed = False; self.step = 0; self.task_id = None
            async def send(self, raw):
                row = json.loads(raw); self.sent.append(row)
                self.task_id = row['header']['task_id']
            async def recv(self):
                self.step += 1
                if self.step == 1:
                    return json.dumps({'header': {'task_id': self.task_id, 'event': 'task-started'}})
                if self.step == 2:
                    if outcome == 'cancel':
                        raise asyncio.CancelledError()
                    if outcome == 'fail':
                        return json.dumps({'header': {'task_id': self.task_id, 'event': 'task-failed', 'error_message': 'private upstream message'}})
                    if outcome == 'wrong_id':
                        return json.dumps({'header': {'task_id': 'other', 'event': 'task-finished'}})
                    if outcome == 'empty':
                        return json.dumps({'header': {'task_id': self.task_id, 'event': 'task-finished'}})
                    return b'\x01\x00' * 1600
                return json.dumps({'header': {'task_id': self.task_id, 'event': 'task-finished'}})
            async def close(self):
                self.closed = True
        ws = Socket()
        tts = TTSProvider.__new__(TTSProvider)
        tts._config_snapshot = {'voice': 'longanlingxi', 'sample_rate': 16000, 'rate': 1.1}
        tts.sample_rate = 16000; tts.ws_url = 'ws://gateway.test/native'
        tts._auth_header = MagicMock(return_value={'Authorization': 'Bearer test-customer'})
        tts._connect = AsyncMock(return_value=ws)
        live = object(); tts._current = live; tts.ws = live
        tts.tts_audio_queue = MagicMock()
        return tts, ws, live

    async def test_isolated_wav_uses_customer_gateway_and_does_not_touch_live_session(self):
        tts, ws, live = self.provider()
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / 'speech.wav')
            await tts.synthesize_wav_isolated('该喝水了', path)
            with wave.open(path, 'rb') as wav:
                self.assertEqual((wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getnframes()), (1, 2, 16000, 1600))
        self.assertTrue(ws.closed)
        self.assertIs(tts._current, live); self.assertIs(tts.ws, live)
        tts.tts_audio_queue.put.assert_not_called()
        tts._connect.assert_awaited_once_with(tts.ws_url, {'Authorization': 'Bearer test-customer'})
        self.assertEqual([r['header']['action'] for r in ws.sent], ['run-task', 'continue-task', 'finish-task'])
        self.assertEqual(ws.sent[0]['payload']['parameters']['voice'], 'longanlingxi')

    async def test_failure_and_cancellation_write_no_asset_and_keep_live_session(self):
        for outcome, exception in [('fail', RuntimeError), ('empty', RuntimeError),
                                   ('wrong_id', RuntimeError), ('cancel', asyncio.CancelledError)]:
            tts, ws, live = self.provider(outcome)
            with tempfile.TemporaryDirectory() as tmp:
                path = str(Path(tmp) / 'speech.wav')
                with self.assertRaises(exception):
                    await tts.synthesize_wav_isolated('测试', path)
                self.assertFalse(Path(path).exists())
            self.assertTrue(ws.closed)
            self.assertIs(tts._current, live)


class ToolDispatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_action_receipts_are_checked_in_actual_tool_manager(self):
        from test_operation_control import fixture
        from core.providers.tools.base import ToolType, ToolDefinition
        args = {'instance_id': 'n7', 'revision': 2, 'action': 'primary'}
        for receipt, completed in [('提醒已完成', True), ('已接收', False),
                                   ('提醒已永久删除', False)]:
            conn, manager, executor = fixture()
            executor.tools['reminder_action'] = ToolDefinition('reminder_action',
                {'type': 'function', 'function': {'name': 'reminder_action',
                    'parameters': {'type': 'object', 'properties': {}}}}, ToolType.DEVICE_MCP)
            executor.result = ActionResponse(Action.REQLLM, result=receipt)
            get_control(conn).begin('我已经喝水了', 'actor')
            with patch('core.utils.device_reminder.maybe_intercept_reminder_tool', AsyncMock(return_value=None)):
                result = await manager.execute_tool('reminder_action', args)
                # Repeat transport request in the same turn is not dispatched twice.
                repeated = await manager.execute_tool('reminder_action', args)
            self.assertEqual(executor.calls, [('reminder_action', args)])
            self.assertIs(result, repeated)
            self.assertEqual(getattr(result, 'operation_state', None) == 'completed', completed)
            self.assertEqual(result.action, Action.RESPONSE)
            if not completed:
                self.assertIn('没有确认', result.response)

    async def test_final_catalog_keeps_relative_time_and_receipt_rules(self):
        from core.utils.device_reminder import rewrite_reminder_tool_descriptions
        conn = SimpleNamespace(mcp_client=SimpleNamespace(has_tool=lambda name: name in {'note_add', 'note.add'}))
        catalog = [{'type': 'function', 'function': {'name': 'note_add', 'description': '旧', 'parameters': {}}}]
        output = rewrite_reminder_tool_descriptions([describe_tool(t) for t in catalog], conn)
        description = output[0]['function']['description']
        self.assertIn('add_reminder', description)
        self.assertIn('remind_at=0', description)
        self.assertIn('保存失败不能说设置成功', description)
        self.assertEqual(catalog[0]['function']['description'], '旧')


if __name__ == '__main__':
    unittest.main()
