"""多设备并发隔离与串指令专项测试。

覆盖用户审计要求的并发场景：
- 设备 A、B 同时在线：A 的 update_spine 只能发给 A（send_json_to_device 按 device_id 路由）。
- A 重连：旧 A 连接清理不影响新 A 连接，更不影响 B；旧连接永不回退为 current。
- A、B 同时上报 spine_ota_status：各自只更新自己的 task（设备身份取自连接，不信任 payload）。
- TTS/配置消息不能跨 device_id/session_id（send_tts_to_device 必须指定 device_id；prompt 缓存 key 绑定 device_id）。
- pending update_spine 投递只发送到本连接的 websocket（不跨设备）；stale 竞态释放领取。
- /api/v1/broadcast 已移除：路由不可用，绝不发送 TTS。
不依赖完整 app；仅用轻量 FakeWS/FakeHandler + mock。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.websocket_server import WebSocketServer


class FakeWS:
    def __init__(self):
        self.sent = []
        self.closed = False

    async def send(self, data):
        self.sent.append(data)

    async def close(self):
        self.closed = True


class FakeTTS:
    def __init__(self):
        self.tts_text_queue = FakeQueue()


class FakeQueue:
    def __init__(self):
        self.items = []

    def put(self, item):
        self.items.append(item)

    def qsize(self):
        return len(self.items)

    def get_nowait(self):
        if not self.items:
            raise Exception("empty")
        return self.items.pop(0)


def _make_handler(device_id, session_id):
    h = MagicMock()
    h.device_id = device_id
    h.session_id = session_id
    h.correlation_id = "corr-" + session_id
    h.websocket = FakeWS()
    h.tts = FakeTTS()
    h.tts.tts_audio_queue = FakeQueue()
    h.superseded = False
    h.client_abort = False
    h.tts_abort_epoch = 0
    h.tts_sentence_epochs = {}
    h.server = None
    h.stop_event = None  # 禁止 MagicMock 伪造 is_set()
    h._outbound_tasks = set()
    h._reminder_voice_tasks = set()
    return h


def _make_server():
    server = WebSocketServer.__new__(WebSocketServer)
    server.logger = MagicMock()
    server._connections = {}
    server._current_sessions = {}
    server._device_send_locks = {}
    server._reminder_control_manager = None
    return server


def _seed(server, device_id, session_id):
    """通过注册路径登记连接，使 _current_sessions 与 _connections 保持一致。"""
    h = _make_handler(device_id, session_id)
    h.server = server
    server._register_connection(device_id, h)
    return h


def _update_spine(task_id="task-a-1", pack_id="pack-a"):
    return {
        "type": "system",
        "command": "update_spine",
        "task_id": task_id,
        "pack_id": pack_id,
    }


class TestSupersededSessionOutboundBlocked(unittest.IsolatedAsyncioTestCase):
    """A2 成为 current 后，A1 任何下行路径 0 send / 0 新入队；B 隔离；MCP 独立断言。"""

    async def test_a1_tts_audio_mcp_reminder_hello_ping_blocked_after_a2(self):
        from core.utils.device_outbound import guarded_ws_send, enqueue_tts, is_outbound_allowed, begin_tts_turn
        from core.providers.tts.dto.dto import TTSMessageDTO, SentenceType, ContentType
        from core.handle.helloHandle import handleHelloMessage
        from core.handle.textHandler.pingMessageHandler import PingTextMessageHandler
        from core.providers.tools.device_mcp.mcp_handler import send_mcp_message

        server = _make_server()
        a1 = _seed(server, "dev-a", "sess-a1")
        b = _seed(server, "dev-b", "sess-b")

        # A1 注册后开始各类下行准备
        self.assertTrue(is_outbound_allowed(a1))
        a1.features = {"mcp": True}
        a1.welcome_msg = {"type": "hello", "session_id": a1.session_id}
        a1.hello_received = False
        a1._set_protocol_version = MagicMock(return_value=True)
        a1.logger = MagicMock()
        a1.logger.bind.return_value = a1.logger

        await guarded_ws_send(a1, '{"type":"pre"}', command="pre", msg_type="pre")
        self.assertEqual(len(a1.websocket.sent), 1)
        begin_tts_turn(a1, "s1")
        enqueue_tts(
            a1,
            TTSMessageDTO(
                sentence_id="s1",
                sentence_type=SentenceType.MIDDLE,
                content_type=ContentType.TEXT,
                content_detail="hello-a1",
            ),
        )
        self.assertEqual(a1.tts.tts_text_queue.qsize(), 1)

        # A2 注册并成为 current（会 invalidate A1，清空其 TTS 队列）
        a2 = _seed(server, "dev-a", "sess-a2")
        self.assertTrue(a1.superseded)
        self.assertFalse(is_outbound_allowed(a1))
        self.assertTrue(is_outbound_allowed(a2))
        self.assertEqual(a1.tts.tts_text_queue.qsize(), 0)

        a1_sent_before = len(a1.websocket.sent)
        a2_sent_before = len(a2.websocket.sent)
        b_sent_before = len(b.websocket.sent)

        # A1 后续：TTS/音频/MCP/Reminder/hello/ping — 均不得再 send / 入队
        ok_tts = await guarded_ws_send(
            a1, '{"type":"tts","state":"start"}', command="tts", msg_type="tts"
        )
        ok_audio = await guarded_ws_send(a1, b"\x00\x01audio", command="audio", msg_type="binary")
        ok_mcp = await guarded_ws_send(
            a1, '{"type":"mcp","payload":{}}', command="mcp", msg_type="mcp"
        )
        ok_reminder = await guarded_ws_send(
            a1,
            '{"type":"reminder_voice_asset"}',
            command="reminder_voice_asset",
            msg_type="reminder_voice_asset",
        )
        self.assertFalse(ok_tts)
        self.assertFalse(ok_audio)
        self.assertFalse(ok_mcp)
        self.assertFalse(ok_reminder)

        enq = enqueue_tts(
            a1,
            TTSMessageDTO(
                sentence_id="s2",
                sentence_type=SentenceType.MIDDLE,
                content_type=ContentType.TEXT,
                content_detail="should-not-enqueue",
            ),
        )
        self.assertFalse(enq)
        self.assertEqual(a1.tts.tts_text_queue.qsize(), 0)

        await PingTextMessageHandler().handle(a1, {"type": "ping"})
        # hello：A1 已非 current，不得回复 welcome
        await handleHelloMessage(
            a1, {"type": "hello", "version": 1, "audio_params": {"format": "opus"}}
        )

        from core.utils.tool_result import DeviceToolError

        with self.assertRaises(DeviceToolError) as cm:
            await send_mcp_message(a1, {"jsonrpc": "2.0", "method": "tools/list", "id": 1})
        self.assertEqual(cm.exception.code, "connection_closed")
        self.assertEqual(len(a1.websocket.sent), a1_sent_before)

        # A2 不受影响
        ok_a2 = await guarded_ws_send(
            a2, '{"type":"tts","state":"start"}', command="tts", msg_type="tts"
        )
        self.assertTrue(ok_a2)
        self.assertEqual(len(a2.websocket.sent), a2_sent_before + 1)

        a2.features = {"mcp": True}
        a2.logger = MagicMock()
        a2.logger.bind.return_value = a2.logger
        await send_mcp_message(a2, {"jsonrpc": "2.0", "method": "tools/list", "id": 2})
        self.assertGreater(len(a2.websocket.sent), a2_sent_before + 1)
        a2_mcp = "".join(str(x) for x in a2.websocket.sent)
        self.assertIn('"type":"mcp"', a2_mcp.replace(" ", ""))
        self.assertEqual(len(a1.websocket.sent), a1_sent_before)

        begin_tts_turn(a2, "s3")
        enq_a2 = enqueue_tts(
            a2,
            TTSMessageDTO(
                sentence_id="s3",
                sentence_type=SentenceType.MIDDLE,
                content_type=ContentType.TEXT,
                content_detail="a2-ok",
            ),
        )
        self.assertTrue(enq_a2)

        # B 不收到 A 的任何内容
        self.assertEqual(len(b.websocket.sent), b_sent_before)
        for raw in a2.websocket.sent:
            self.assertNotIn(b.session_id, str(raw))

    async def test_mcp_a_sends_b_never_receives(self):
        """MCP 独立断言：A 发 MCP，B 的 websocket.sent 保持 0 增量。"""
        from core.providers.tools.device_mcp.mcp_handler import send_mcp_message

        server = _make_server()
        a = _seed(server, "dev-a", "sess-a")
        b = _seed(server, "dev-b", "sess-b")
        a.features = {"mcp": True}
        b.features = {"mcp": True}
        a.logger = MagicMock()
        a.logger.bind.return_value = a.logger

        b_before = len(b.websocket.sent)
        await send_mcp_message(a, {"jsonrpc": "2.0", "method": "initialize", "id": 1})
        self.assertEqual(len(a.websocket.sent), 1)
        raw = a.websocket.sent[0]
        self.assertIn('"type":"mcp"', raw.replace(" ", ""))
        self.assertEqual(len(b.websocket.sent), b_before)


class TestConnectionRoutingIsolation(unittest.IsolatedAsyncioTestCase):
    async def test_update_spine_only_to_target_device(self):
        """A、B 同时在线：A 的 update_spine 只能发给 A，绝不发给 B。"""
        server = _make_server()
        a = _seed(server, "dev-a", "sess-a")
        b = _seed(server, "dev-b", "sess-b")

        ok = await server.send_json_to_device("dev-a", _update_spine("task-a-1"))

        self.assertTrue(ok)
        self.assertEqual(len(a.websocket.sent), 1)
        self.assertEqual(len(b.websocket.sent), 0)
        sent = json.loads(a.websocket.sent[0])
        self.assertEqual(sent["command"], "update_spine")
        self.assertEqual(sent["task_id"], "task-a-1")

    async def test_update_spine_to_b_not_a(self):
        """反向校验：向 B 发送时 A 不受影响。"""
        server = _make_server()
        a = _seed(server, "dev-a", "sess-a")
        b = _seed(server, "dev-b", "sess-b")

        ok = await server.send_json_to_device("dev-b", _update_spine("task-b-1"))

        self.assertTrue(ok)
        self.assertEqual(len(b.websocket.sent), 1)
        self.assertEqual(len(a.websocket.sent), 0)

    async def test_unknown_device_returns_false_and_sends_nothing(self):
        server = _make_server()
        a = _seed(server, "dev-a", "sess-a")
        ok = await server.send_json_to_device("dev-c", _update_spine("task-c"))
        self.assertFalse(ok)
        self.assertEqual(len(a.websocket.sent), 0)

    async def test_send_tts_targets_only_requested_device(self):
        """TTS 指定 device_id 时不得跨设备投递。"""
        server = _make_server()
        a = _seed(server, "dev-a", "sess-a")
        b = _seed(server, "dev-b", "sess-b")

        ok = await server.send_tts_to_device("hello", "dev-a")

        self.assertTrue(ok)
        self.assertGreater(len(a.tts.tts_text_queue.items), 0)
        self.assertEqual(len(b.tts.tts_text_queue.items), 0)
        for item in a.tts.tts_text_queue.items:
            self.assertEqual(item.abort_epoch, 0)
            self.assertIsNotNone(item.sentence_id)
            self.assertEqual(a.sentence_id, item.sentence_id)

    async def test_send_tts_requires_device_id(self):
        """缺少 device_id 必须 fail closed，绝不遍历全部连接。"""
        server = _make_server()
        a = _seed(server, "dev-a", "sess-a")
        b = _seed(server, "dev-b", "sess-b")

        with self.assertRaises(ValueError):
            await server.send_tts_to_device("hello", None)
        with self.assertRaises(ValueError):
            await server.send_tts_to_device("hello", "")

        self.assertEqual(len(a.tts.tts_text_queue.items), 0)
        self.assertEqual(len(b.tts.tts_text_queue.items), 0)

    async def test_send_json_requires_device_id(self):
        server = _make_server()
        a = _seed(server, "dev-a", "sess-a")
        ok = await server.send_json_to_device(None, _update_spine("task-x"))
        self.assertFalse(ok)
        self.assertEqual(len(a.websocket.sent), 0)


class TestCurrentSessionRouting(unittest.IsolatedAsyncioTestCase):
    """同一 device_id 的旧、新连接共存时，普通设备消息只发当前有效连接。"""

    def _old_new(self):
        server = _make_server()
        old = _seed(server, "dev-a", "sess-old")
        new = _seed(server, "dev-a", "sess-new")
        b = _seed(server, "dev-b", "sess-b")
        return server, old, new, b

    async def test_send_json_to_device_only_current_session(self):
        server, old, new, b = self._old_new()

        ok = await server.send_json_to_device("dev-a", _update_spine("task-a-1"))

        self.assertTrue(ok)
        self.assertEqual(len(new.websocket.sent), 1)
        self.assertEqual(len(old.websocket.sent), 0)
        self.assertEqual(len(b.websocket.sent), 0)

    async def test_send_tts_only_current_session(self):
        server, old, new, b = self._old_new()

        ok = await server.send_tts_to_device("hello", "dev-a")

        self.assertTrue(ok)
        self.assertEqual(len(new.tts.tts_text_queue.items), 3)
        self.assertEqual(len(old.tts.tts_text_queue.items), 0)
        self.assertEqual(len(b.tts.tts_text_queue.items), 0)
        for item in new.tts.tts_text_queue.items:
            self.assertEqual(item.abort_epoch, 0)

    async def test_precise_stale_session_fails(self):
        """精确指定旧代际路由：已非当前连接时必须失败，不得退化群发。"""
        server, old, new, b = self._old_new()

        ok = await server.send_json_to_device(
            "dev-a", _update_spine("task-a-1"), session_id="sess-old"
        )

        self.assertFalse(ok)
        self.assertEqual(len(new.websocket.sent), 0)
        self.assertEqual(len(old.websocket.sent), 0)

    async def test_precise_current_session_succeeds(self):
        server, old, new, b = self._old_new()

        ok = await server.send_json_to_device(
            "dev-a", _update_spine("task-a-1"), session_id="sess-new"
        )

        self.assertTrue(ok)
        self.assertEqual(len(new.websocket.sent), 1)
        self.assertEqual(len(old.websocket.sent), 0)


class TestReconnectGenerationIsolation(unittest.IsolatedAsyncioTestCase):
    async def test_register_multiple_generations_same_device(self):
        """同一 device_id 的多个连接代际可共存，不互相覆盖；current 指向最新。"""
        server = _make_server()
        old = _make_handler("dev-a", "sess-old")
        new = _make_handler("dev-a", "sess-new")
        b = _make_handler("dev-b", "sess-b")
        server._register_connection("dev-a", old)
        server._register_connection("dev-a", new)
        server._register_connection("dev-b", b)

        self.assertEqual(set(server._connections["dev-a"].keys()), {"sess-old", "sess-new"})
        self.assertEqual(set(server._connections["dev-b"].keys()), {"sess-b"})
        self.assertEqual(server._current_sessions["dev-a"], "sess-new")
        self.assertEqual(server._current_sessions["dev-b"], "sess-b")
        self.assertTrue(getattr(old, "superseded", False))
        self.assertFalse(getattr(new, "superseded", True))

    async def test_unregister_old_keeps_new_and_other_device(self):
        """A 重连后旧连接清理：不得误删新 A，也不得影响 B，且不清除新 A 的 current 标记。"""
        server = _make_server()
        old = _make_handler("dev-a", "sess-old")
        new = _make_handler("dev-a", "sess-new")
        b = _make_handler("dev-b", "sess-b")
        server._register_connection("dev-a", old)
        server._register_connection("dev-a", new)
        server._register_connection("dev-b", b)

        server._unregister_connection("dev-a", old)

        self.assertEqual(set(server._connections["dev-a"].keys()), {"sess-new"})
        self.assertIn("dev-b", server._connections)
        self.assertEqual(set(server._connections["dev-b"].keys()), {"sess-b"})
        self.assertEqual(server._current_sessions["dev-a"], "sess-new")
        self.assertEqual(server._current_sessions["dev-b"], "sess-b")

    async def test_unregister_last_connection_removes_device_key(self):
        server = _make_server()
        a = _make_handler("dev-a", "sess-a")
        server._register_connection("dev-a", a)
        server._unregister_connection("dev-a", a)
        self.assertNotIn("dev-a", server._connections)
        self.assertNotIn("dev-a", server._current_sessions)

    async def test_unregister_current_does_not_promote_old(self):
        """A2 断开后不得将 A1 提升为 current；向 A 发送必须失败直到 A3 注册。"""
        server = _make_server()
        a1 = _make_handler("dev-a", "sess-a1")
        a2 = _make_handler("dev-a", "sess-a2")
        server._register_connection("dev-a", a1)
        server._register_connection("dev-a", a2)
        self.assertEqual(server._current_sessions["dev-a"], "sess-a2")

        server._unregister_connection("dev-a", a2)

        self.assertNotIn("dev-a", server._current_sessions)
        self.assertIn("sess-a1", server._connections["dev-a"])
        self.assertFalse(server.is_current_connection("dev-a", a1))

        ok = await server.send_json_to_device("dev-a", _update_spine("task-a-1"))
        self.assertFalse(ok)
        self.assertEqual(len(a1.websocket.sent), 0)

        a3 = _make_handler("dev-a", "sess-a3")
        server._register_connection("dev-a", a3)
        self.assertEqual(server._current_sessions["dev-a"], "sess-a3")
        ok2 = await server.send_json_to_device("dev-a", _update_spine("task-a-2"))
        self.assertTrue(ok2)
        self.assertEqual(len(a3.websocket.sent), 1)
        self.assertEqual(len(a1.websocket.sent), 0)

    async def test_register_marks_old_superseded(self):
        server = _make_server()
        a1 = _make_handler("dev-a", "sess-a1")
        a2 = _make_handler("dev-a", "sess-a2")
        server._register_connection("dev-a", a1)
        server._register_connection("dev-a", a2)
        self.assertTrue(a1.superseded)
        self.assertFalse(a2.superseded)
        self.assertTrue(server.is_current_connection("dev-a", a2))
        self.assertFalse(server.is_current_connection("dev-a", a1))


class TestSpineOtaStatusIdentity(unittest.IsolatedAsyncioTestCase):
    async def test_ack_uses_connection_device_id_not_payload(self):
        """A、B 同时上报 spine_ota_status：身份取自连接，不信任 payload.device_id。"""
        from core.handle.textHandler.spineOtaStatusMessageHandler import (
            SpineOtaStatusMessageHandler,
        )
        from config import manage_api_client

        conn = MagicMock()
        conn.device_id = "dev-a"
        conn.logger = MagicMock()
        conn.server = None
        conn.websocket = FakeWS()

        msg = {
            "type": "spine_ota_status",
            "task_id": "task-a-1",
            "pack_id": "pack-a",
            "phase": "downloading",
            "device_id": "dev-b",
        }
        client = MagicMock()
        client.request = AsyncMock(return_value={"ok": True})

        with patch.object(manage_api_client.ManageApiClient, "_instance", client):
            await SpineOtaStatusMessageHandler().handle(conn, msg)

        client.request.assert_awaited_once()
        args = client.request.await_args
        self.assertEqual(args.kwargs["headers"]["X-Device-Id"], "dev-a")
        body = args.kwargs["json"]
        self.assertEqual(body["taskId"], "task-a-1")
        self.assertEqual(body["packId"], "pack-a")


class TestSpineOtaStoreDeviceOwnership(unittest.TestCase):
    """本地投递闸门必须按 task_id + device_id 精确隔离：B 不得推进/取消 A 的任务状态。"""

    def setUp(self):
        from core.utils import spine_ota_store as store

        self.store = store
        self._tmp = tempfile.TemporaryDirectory()
        store.set_db_path(os.path.join(self._tmp.name, "spine_ota.db"))
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(lambda: store.set_db_path(None))

    def _payload(self, task_id):
        return {
            "type": "system",
            "command": "update_spine",
            "task_id": task_id,
            "pack_id": "pack-a",
        }

    def test_other_device_cannot_mark_status(self):
        store = self.store
        action, d = store.prepare_delivery(
            "task-a-1", "dev-a", "pack-a", self._payload("task-a-1"), now=1000.0
        )
        self.assertEqual("deliver", action)

        with self.assertRaises(store.DeviceMismatchError):
            store.mark_status("task-a-1", "dev-b", "pack-a", "downloading")

        d2 = store.get_delivery("task-a-1")
        self.assertEqual("sent", d2["state"])
        self.assertEqual("dev-a", d2["device_id"])

    def test_other_device_cannot_complete_task(self):
        store = self.store
        store.prepare_delivery(
            "task-a-1", "dev-a", "pack-a", self._payload("task-a-1"), now=1000.0
        )
        with self.assertRaises(store.DeviceMismatchError):
            store.mark_completed("task-a-1", "dev-b", "pack-a")
        self.assertEqual("sent", store.get_delivery("task-a-1")["state"])

    def test_other_device_cannot_redeliver_task(self):
        store = self.store
        store.prepare_delivery(
            "task-a-1", "dev-a", "pack-a", self._payload("task-a-1"), now=1000.0
        )
        with self.assertRaises(store.DeviceMismatchError):
            store.prepare_delivery(
                "task-a-1", "dev-b", "pack-a", self._payload("task-a-1"), now=1000.0
            )
        self.assertEqual(1, store.get_delivery("task-a-1")["attempt_count"])

    def test_abnormal_disconnect_ignored_for_mismatch(self):
        store = self.store
        store.prepare_delivery(
            "task-a-1", "dev-a", "pack-a", self._payload("task-a-1"), now=1000.0
        )
        store.record_abnormal_disconnect("task-a-1", "dev-b")
        d = store.get_delivery("task-a-1")
        self.assertEqual("sent", d["state"])
        self.assertIsNone(d["last_error"])


class TestPendingSpineDeliveryScoped(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from core.utils import spine_ota_store as store

        self._tmp = tempfile.TemporaryDirectory()
        store.set_db_path(os.path.join(self._tmp.name, "spine_ota.db"))
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(lambda: store.set_db_path(None))

    def _handler(self, device_id, session_id, server=None):
        from core.connection import ConnectionHandler

        h = ConnectionHandler.__new__(ConnectionHandler)
        h.device_id = device_id
        h.session_id = session_id
        h.correlation_id = "corr-" + session_id
        h.logger = MagicMock()
        h.websocket = FakeWS()
        h.config = {}
        h.spine_update_sent_task_id = None
        h.spine_update_sent_at_ms = None
        h._monotonic_ms = lambda: 1
        h.server = server
        return h

    async def test_deliver_pending_only_to_own_websocket(self):
        """pending update_spine 只发送到本连接的 websocket，不触碰其他设备连接。"""
        server = _make_server()
        handler_a = self._handler("dev-a", "sess-a", server=server)
        server._register_connection("dev-a", handler_a)

        other = FakeWS()
        payload = {
            "type": "system",
            "command": "update_spine",
            "task_id": "task-a-1",
            "pack_id": "pack-a",
        }
        client = MagicMock()
        client.request = AsyncMock(
            return_value={
                "hasPending": True,
                "payload": payload,
                "taskId": "task-a-1",
                "attemptCount": 1,
            }
        )

        with patch("asyncio.sleep", new=AsyncMock()), patch(
            "config.manage_api_client.ManageApiClient"
        ) as mac:
            mac._instance = client
            await handler_a._deliver_pending_spine_role()

        self.assertEqual(len(handler_a.websocket.sent), 1)
        self.assertEqual(len(other.sent), 0)
        self.assertEqual(client.request.await_args.kwargs["params"]["deviceId"], "dev-a")

    async def test_stale_before_claim_skips_pending(self):
        """领取前已非 current：不得查询/领取 pending。"""
        server = _make_server()
        new = _make_handler("dev-a", "sess-new")
        server._connections = {"dev-a": {"sess-new": new}}
        server._current_sessions = {"dev-a": "sess-new"}

        old = self._handler("dev-a", "sess-old", server=server)
        client = MagicMock()
        client.request = AsyncMock()

        with patch("asyncio.sleep", new=AsyncMock()), patch(
            "config.manage_api_client.ManageApiClient"
        ) as mac:
            mac._instance = client
            await old._deliver_pending_spine_role()

        self.assertEqual(len(old.websocket.sent), 0)
        client.request.assert_not_awaited()

    async def test_stale_after_claim_releases_and_new_can_redeliver(self):
        """A1 通过第一轮 current 检查并领取；A2 在 A1 send 前成为 current；
        A1 不得 send，必须按 lease 释放；A2 能重新领取并只 send 一次；B 不受影响。
        重放 A1 的旧 lease release 不得影响 A2。
        """
        server = _make_server()
        a1 = self._handler("dev-a", "sess-a1", server=server)
        b = self._handler("dev-b", "sess-b", server=server)
        server._register_connection("dev-a", a1)
        server._register_connection("dev-b", b)

        payload = {
            "type": "system",
            "command": "update_spine",
            "task_id": "task-a-1",
            "pack_id": "pack-a",
        }
        state = {"a2": None, "leases": [], "releases": []}

        async def fake_request(method, endpoint, **kwargs):
            if endpoint == "role-packs/device/pending":
                device_id = kwargs.get("params", {}).get("deviceId")
                if device_id == "dev-a" and state["a2"] is None:
                    a2 = self._handler("dev-a", "sess-a2", server=server)
                    await server.register_connection("dev-a", a2)
                    state["a2"] = a2
                    lease = "lease-L1"
                    state["leases"].append(lease)
                    return {
                        "hasPending": True,
                        "payload": dict(payload),
                        "taskId": "task-a-1",
                        "attemptCount": 1,
                        "deliveryLeaseId": lease,
                        "deliveryVersion": 1,
                        "claimedSessionId": "sess-a1",
                    }
                lease = "lease-L2"
                state["leases"].append(lease)
                return {
                    "hasPending": True,
                    "payload": dict(payload),
                    "taskId": "task-a-1",
                    "attemptCount": 1,
                    "deliveryLeaseId": lease,
                    "deliveryVersion": 2,
                    "claimedSessionId": "sess-a2",
                }
            if endpoint == "role-packs/device/release-pending":
                state["releases"].append(dict(kwargs.get("params") or {}))
                return {"released": True}
            return {"hasPending": False}

        client = MagicMock()
        client.request = AsyncMock(side_effect=fake_request)

        with patch("asyncio.sleep", new=AsyncMock()), patch(
            "config.manage_api_client.ManageApiClient"
        ) as mac:
            mac._instance = client
            await a1._deliver_pending_spine_role()

            self.assertEqual(len(a1.websocket.sent), 0)
            self.assertEqual(1, len(state["releases"]))
            self.assertEqual(state["releases"][0]["deliveryLeaseId"], "lease-L1")

            a2 = state["a2"]
            self.assertIsNotNone(a2)
            await a2._deliver_pending_spine_role()

            # 重放 A1 旧 lease release：调用方再次 release，服务端应 0 行（此处仅验证参数仍是 L1）
            await a1._release_claimed_delivery("task-a-1", "lease-L1", "sess-a1")
            self.assertEqual(2, len(state["releases"]))
            self.assertEqual(state["releases"][1]["deliveryLeaseId"], "lease-L1")

        self.assertEqual(len(a2.websocket.sent), 1)
        self.assertEqual(len(a1.websocket.sent), 0)
        self.assertEqual(len(b.websocket.sent), 0)
        sent = json.loads(a2.websocket.sent[0])
        self.assertEqual(sent["task_id"], "task-a-1")
        self.assertEqual(state["leases"], ["lease-L1", "lease-L2"])


class TestSendTocttouSerialization(unittest.IsolatedAsyncioTestCase):
    """current 检查与 send 必须与 register 串行，消除 TOCTTOU。"""

    async def test_send_completes_before_register_or_fails_after(self):
        """A1 已进入 send_to_current 持锁窗口时，A2 注册必须等待；
        释放后 A2 成为唯一 current，后续消息只到 A2。
        """
        server = _make_server()
        a1 = _seed(server, "dev-a", "sess-a1")
        events = []
        gate = asyncio.Event()

        async def pause_after_check():
            events.append("a1_checked")
            gate.set()
            await asyncio.sleep(0.05)
            events.append("a1_sending")

        send_task = asyncio.create_task(
            server.send_to_current(
                "dev-a",
                json.dumps({"type": "system", "command": "ping"}),
                handler=a1,
                command="ping",
                msg_type="system",
                _pre_send=pause_after_check,
            )
        )
        await gate.wait()
        self.assertIn("a1_checked", events)

        a2 = _make_handler("dev-a", "sess-a2")
        reg_task = asyncio.create_task(server.register_connection("dev-a", a2))
        # 给 register 一点时间：若未串行会立刻完成；串行则仍 pending
        await asyncio.sleep(0.01)
        self.assertFalse(reg_task.done())

        sent_ok = await send_task
        self.assertTrue(sent_ok)
        await reg_task
        self.assertEqual(server._current_sessions["dev-a"], "sess-a2")
        self.assertEqual(len(a1.websocket.sent), 1)
        self.assertEqual(len(a2.websocket.sent), 0)

        # A2 成为 current 后，再向 A 发送只到 A2
        ok = await server.send_json_to_device("dev-a", _update_spine("task-after"))
        self.assertTrue(ok)
        self.assertEqual(len(a2.websocket.sent), 1)
        self.assertEqual(len(a1.websocket.sent), 1)  # 仍只有此前那一条

    async def test_a1_cannot_send_after_a2_current(self):
        server = _make_server()
        a1 = _seed(server, "dev-a", "sess-a1")
        a2 = _make_handler("dev-a", "sess-a2")
        await server.register_connection("dev-a", a2)

        ok = await server.send_to_current(
            "dev-a",
            json.dumps({"type": "system", "command": "ping"}),
            handler=a1,
            command="ping",
        )
        self.assertFalse(ok)
        self.assertEqual(len(a1.websocket.sent), 0)
        ok2 = await server.send_json_to_device("dev-a", _update_spine("t2"))
        self.assertTrue(ok2)
        self.assertEqual(len(a2.websocket.sent), 1)

class TestMemoryIsolation(unittest.TestCase):
    """Memory 每个连接独立实例，绝不跨设备共享 role_id / short_memory。"""

    def _handler(self, device_id):
        from core.connection import ConnectionHandler

        h = ConnectionHandler.__new__(ConnectionHandler)
        h.device_id = device_id
        h.session_id = "sess-" + device_id
        h.correlation_id = "corr-" + device_id
        h.logger = MagicMock()
        h.llm = None
        h.read_config_from_api = False
        h.memory = None
        h.config = {
            "selected_module": {"Memory": "mem_local_short"},
            "Memory": {"mem_local_short": {"type": "mem_local_short", "llm": None}},
            "LLM": {},
        }
        return h

    def _no_memory_file(self):
        real_exists = os.path.exists

        def fake_exists(path):
            if ".memory.yaml" in str(path):
                return False
            return real_exists(path)

        return patch("os.path.exists", side_effect=fake_exists)

    def test_instances_distinct_and_role_isolated(self):
        with self._no_memory_file():
            h_a = self._handler("dev-a")
            h_b = self._handler("dev-b")
            h_a._initialize_memory()
            h_b._initialize_memory()

        self.assertIsNotNone(h_a.memory)
        self.assertIsNotNone(h_b.memory)
        self.assertFalse(getattr(h_a, "memory_init_error", None))
        self.assertIsNot(h_a.memory, h_b.memory)
        self.assertEqual(h_a.memory.role_id, "dev-a")
        self.assertEqual(h_b.memory.role_id, "dev-b")
        h_a.memory.short_memory = "A 的短期记忆"
        self.assertNotEqual(h_b.memory.short_memory, "A 的短期记忆")

    def test_private_config_missing_memory_section_still_isolated(self):
        with self._no_memory_file():
            h_a = self._handler("dev-a")
            h_b = self._handler("dev-b")
            h_a.config = {"selected_module": {}, "LLM": {}}
            h_b.config = {"selected_module": {}, "LLM": {}}
            h_a.memory = None
            h_b.memory = None
            h_a._initialize_memory()
            h_b._initialize_memory()

        self.assertIsNotNone(h_a.memory)
        self.assertIsNotNone(h_b.memory)
        self.assertIsNot(h_a.memory, h_b.memory)
        self.assertEqual(h_a.memory.role_id, "dev-a")
        self.assertEqual(h_b.memory.role_id, "dev-b")
        self.assertEqual(h_a.memory.__class__.__module__, "core.providers.memory.nomem.nomem")
        h_a.memory.short_memory = "A 的短期记忆"
        self.assertNotEqual(h_b.memory.short_memory, "A 的短期记忆")


class TestBroadcastDisabled(unittest.IsolatedAsyncioTestCase):
    """/api/v1/broadcast 已彻底移除：不得再作为可调用的全局 TTS 入口。"""

    async def test_api_broadcast_symbol_removed(self):
        import app

        self.assertFalse(hasattr(app, "api_broadcast"))

    async def test_broadcast_route_not_registered(self):
        from app import broadcast_app

        paths = {getattr(r, "path", None) for r in broadcast_app.routes}
        self.assertNotIn("/api/v1/broadcast", paths)
        self.assertIn("/api/v1/device/send", paths)


class TestConfigIsolation(unittest.TestCase):
    def test_image_session_key_binds_device_id(self):
        """视觉追问图片缓存 key 必须绑定 device_id，避免同 session_id 跨设备串图。"""
        from core.api.vision_handler import VisionHandler

        self.assertEqual(
            VisionHandler._image_session_key("dev-a", "sess-1"),
            "dev-a:sess-1",
        )
        self.assertNotEqual(
            VisionHandler._image_session_key("dev-a", "sess-1"),
            VisionHandler._image_session_key("dev-b", "sess-1"),
        )

    def test_device_prompt_cache_key_includes_device_id(self):
        """差异化 prompt 缓存 key 必须包含 device_id（读 DEVICE_PROMPT 命名空间）。"""
        from core.utils.prompt_manager import PromptManager

        pm = PromptManager.__new__(PromptManager)
        pm.config = {"prompt_template": None}
        pm.logger = MagicMock()
        cache = MagicMock()
        cache.get = MagicMock(return_value=None)
        pm.cache_manager = cache
        from core.utils.cache.config import CacheType
        pm.CacheType = CacheType

        pm.get_quick_prompt("prompt-text", "dev-a")

        set_args = cache.set.call_args
        self.assertEqual(set_args.args[0], CacheType.DEVICE_PROMPT)
        self.assertIn("dev-a", set_args.args[1])



class BlockingFakeWS:
    """可阻塞的 FakeWebSocket：进入 send 后暂停，直至放行才记入 sent。"""

    def __init__(self):
        self.sent = []
        self.closed = False
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def send(self, data):
        self.entered.set()
        await self.release.wait()
        self.sent.append(data)

    async def close(self):
        self.closed = True


class TestA1A2BlockingSendRace(unittest.IsolatedAsyncioTestCase):
    """真实并发：A1 已进入 websocket.send 但未标记 sent 时，A2 register 必须等待。"""

    async def test_register_waits_until_a1_send_completes(self):
        server = _make_server()
        a1 = _make_handler("dev-a", "sess-a1")
        a1.websocket = BlockingFakeWS()
        a1.server = server
        server._register_connection("dev-a", a1)

        b = _seed(server, "dev-b", "sess-b")
        b_before = len(b.websocket.sent)

        send_task = asyncio.create_task(
            server.send_to_current(
                "dev-a",
                json.dumps({"type": "mcp", "payload": {"method": "ping"}}),
                handler=a1,
                command="mcp",
                msg_type="mcp",
            )
        )
        await asyncio.wait_for(a1.websocket.entered.wait(), timeout=1.0)
        # A1 已进入 send，但尚未写入 sent
        self.assertEqual(a1.websocket.sent, [])

        a2 = _make_handler("dev-a", "sess-a2")
        a2.websocket = FakeWS()
        a2.server = server
        reg_task = asyncio.create_task(server.register_connection("dev-a", a2))
        await asyncio.sleep(0.02)
        self.assertFalse(
            reg_task.done(),
            "A2 register 不得在 A1 send 完成前完成（必须同锁串行）",
        )
        self.assertEqual(server._current_sessions.get("dev-a"), "sess-a1")

        a1.websocket.release.set()
        ok = await send_task
        self.assertTrue(ok)
        await reg_task

        self.assertEqual(len(a1.websocket.sent), 1)
        self.assertEqual(server._current_sessions.get("dev-a"), "sess-a2")
        self.assertTrue(a1.superseded)

        # A2 current 后，A1 的 MCP/TTS/JSON/主动问候均为 0 新增 send
        a1_before = len(a1.websocket.sent)
        a2_before = len(a2.websocket.sent)
        from core.utils.device_outbound import guarded_ws_send

        self.assertFalse(
            await guarded_ws_send(a1, '{"type":"mcp"}', command="mcp", msg_type="mcp")
        )
        self.assertFalse(
            await server.send_json_to_device(
                "dev-a",
                {"type": "system", "command": "ping"},
                session_id="sess-a1",
            )
        )
        ok_a2 = await guarded_ws_send(
            a2, '{"type":"tts","state":"start"}', command="tts", msg_type="tts"
        )
        self.assertTrue(ok_a2)
        self.assertEqual(len(a1.websocket.sent), a1_before)
        self.assertEqual(len(a2.websocket.sent), a2_before + 1)
        self.assertEqual(len(b.websocket.sent), b_before)

    async def test_a1_unregister_does_not_clear_a2(self):
        server = _make_server()
        a1 = _seed(server, "dev-a", "sess-a1")
        a2 = _make_handler("dev-a", "sess-a2")
        a2.server = server
        await server.register_connection("dev-a", a2)
        self.assertEqual(server._current_sessions["dev-a"], "sess-a2")
        await server.unregister_connection("dev-a", a1)
        self.assertEqual(server._current_sessions.get("dev-a"), "sess-a2")
        self.assertIn("sess-a2", server._connections["dev-a"])
        # A2 注销后不得回升 A1
        await server.unregister_connection("dev-a", a2)
        self.assertIsNone(server._current_sessions.get("dev-a"))
        ok = await server.send_json_to_device("dev-a", {"type": "system", "command": "x"})
        self.assertFalse(ok)
        self.assertEqual(a1.websocket.sent, [])



if __name__ == "__main__":
    unittest.main()
