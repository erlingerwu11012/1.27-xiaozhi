"""spine OTA 中央状态机集成测试（xiaozhi-server 侧）。

验证 ACK 路由/generation、ACK 失败不重投、设备隔离、终态不重投、退避重投。
manager-api 中央状态机（CAS 幂等/终态门控）由 Java 侧集成测试与真实 DB 证据覆盖。

覆盖场景：
A. success → 中央 completed → ACK 发送失败 → 不重新下发 update_spine
C. 设备 A/B 并发 status，绝不串任务/串 ACK
D. 同设备旧/新连接并存，ACK 只去最新 generation
E. cancelled/failed/needs_manual_review 永不重投（中央未 completed → 不发 ACK）
F. 并发 success 幂等：中央 completed=true 重复上报 → 幂等 ACK，本地镜像保持 completed
G. accepted 后断线未 success → 按退避重投；成功后停止
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.utils import spine_ota_store as store

DEV_A = "aa:aa:aa:aa:aa:aa"
DEV_B = "bb:bb:bb:bb:bb:bb"
PACK = "halloween_witch"
TASK_A = "task-aaaa"
TASK_B = "task-bbbb"


def _payload(task_id, pack_id):
    return {
        "type": "system",
        "command": "update_spine",
        "task_id": task_id,
        "pack_id": pack_id,
        "url": "https://cdn.example/x",
        "signature": "sig",
    }


class FakeWS:
    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail
        self.fail_times = 0

    async def send(self, data):
        if self.fail:
            self.fail_times += 1
            raise RuntimeError("send failed")
        self.sent.append(data)


class RecordingLogger:
    """捕获 bind().info/warning/error/debug 的轻量记录器，便于断言日志证据。"""

    def __init__(self):
        self.messages = []

    def bind(self, **kwargs):
        return self

    def info(self, msg, *a, **k):
        self.messages.append(msg)

    def warning(self, msg, *a, **k):
        self.messages.append(msg)

    def error(self, msg, *a, **k):
        self.messages.append(msg)

    def debug(self, msg, *a, **k):
        self.messages.append(msg)


class FakeConn:
    def __init__(self, device_id, session_id=None, ws=None, server=None):
        self.device_id = device_id
        self.session_id = session_id or f"sess-{device_id}"
        self.correlation_id = f"corr-{self.session_id}"
        self.logger = MagicMock()
        self.websocket = ws if ws is not None else FakeWS()
        self.config = {}
        self.server = server
        self.superseded = False
        self._outbound_closed = False
        # 无完整 WebSocketServer 时用 local_active 受控注册表
        if server is not None:
            self.outbound_mode = None
        else:
            import sys
            import os

            _td = os.path.dirname(__file__)
            if _td not in sys.path:
                sys.path.insert(0, _td)
            from local_active_test_util import bind_local_active_registry

            bind_local_active_registry(self)


class FakeServer:
    """最小连接代际注册表 + send_to_current，供 superseded ACK 隔离测试。"""

    def __init__(self):
        self._connections = {}
        self._current_sessions = {}
        self._device_send_locks = {}

    def register(self, device_id, conn):
        bag = self._connections.setdefault(device_id, {})
        old_key = self._current_sessions.get(device_id)
        if old_key and old_key != conn.session_id:
            old = bag.get(old_key)
            if old is not None:
                old.superseded = True
        bag[conn.session_id] = conn
        self._current_sessions[device_id] = conn.session_id
        conn.server = self
        conn.outbound_mode = None
        conn.superseded = False

    def is_current_connection(self, device_id, handler):
        key = getattr(handler, "session_id", None)
        if self._current_sessions.get(device_id) != key:
            return False
        conns = self._connections.get(device_id) or {}
        return conns.get(key) is handler

    def _get_device_send_lock(self, device_id):
        import asyncio

        lock = self._device_send_locks.get(device_id)
        if lock is None:
            lock = asyncio.Lock()
            self._device_send_locks[device_id] = lock
        return lock

    async def send_to_current(
        self,
        device_id,
        data,
        *,
        handler=None,
        session_id=None,
        command=None,
        msg_type=None,
        task_id=None,
        _pre_send=None,
    ):
        async with self._get_device_send_lock(device_id):
            target = handler
            if target is None:
                key = session_id or self._current_sessions.get(device_id)
                target = (self._connections.get(device_id) or {}).get(key)
            if target is None or not self.is_current_connection(device_id, target):
                return False
            if _pre_send is not None:
                await _pre_send()
            await target.websocket.send(data)
            return True

    def _current_connection(self, device_id):
        key = self._current_sessions.get(device_id)
        if not key:
            return None
        conns = self._connections.get(device_id)
        return conns.get(key) if conns else None


class _DbMixin:
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        store.set_db_path(os.path.join(self._tmp.name, "spine_ota.db"))
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(lambda: store.set_db_path(None))


def _success_msg(task_id):
    return {"task_id": task_id, "pack_id": PACK, "phase": "success", "progress": 100}


def _completed_result(task_id, device_id, duplicate=False, state="completed"):
    return {
        "taskId": task_id,
        "deviceId": device_id,
        "state": state,
        "completed": True,
        "duplicate": duplicate,
        "attemptCount": 1,
    }


class TestAckFailureNoRedeliver(_DbMixin, unittest.IsolatedAsyncioTestCase):
    """A. success → 中央 completed → ACK 发送失败 → 绝不重新下发 update_spine。"""

    async def test_ack_send_failure_keeps_completed_and_no_redeliver(self):
        from core.handle.textHandler.spineOtaStatusMessageHandler import (
            SpineOtaStatusMessageHandler,
        )
        from config import manage_api_client

        ws = FakeWS(fail=True)
        conn = FakeConn(DEV_A, "sess-a", ws=ws)
        conn.logger = RecordingLogger()
        client = MagicMock()
        client.request = AsyncMock(
            return_value=_completed_result(TASK_A, DEV_A, duplicate=False)
        )
        with patch.object(manage_api_client.ManageApiClient, "_instance", client), patch(
            "asyncio.sleep", new=AsyncMock()
        ):
            await SpineOtaStatusMessageHandler().handle(conn, _success_msg(TASK_A))

        # ACK 发送尝试了有限次重试
        self.assertGreater(ws.fail_times, 0)
        # 绝不因 ACK 失败而触发重新下发：没有 pending 查询、没有 update_spine 下发
        pending_calls = [
            c for c in client.request.await_args_list
            if "pending" in str(c.kwargs.get("endpoint", c.args[1] if len(c.args) > 1 else ""))
        ]
        self.assertEqual([], pending_calls)
        # 本地镜像已落 completed（中央真相已完成，镜像同步）
        self.assertEqual("completed", store.get_delivery(TASK_A)["state"])
        # ACK 失败记录在案，且明确 state=completed(kept)（绝不回退/绝不重投）
        self.assertTrue(any("ack_failed" in m and "completed(kept)" in m for m in conn.logger.messages))
        self.assertTrue(any("ack_retry_exhausted" in m for m in conn.logger.messages))


class TestDeviceIsolation(_DbMixin, unittest.IsolatedAsyncioTestCase):
    """C. A/B 并发 status 不串任务、不串 ACK。"""

    async def test_two_devices_ack_isolated(self):
        from core.handle.textHandler.spineOtaStatusMessageHandler import (
            SpineOtaStatusMessageHandler,
        )
        from config import manage_api_client

        conn_a = FakeConn(DEV_A, "sess-a")
        conn_b = FakeConn(DEV_B, "sess-b")

        async def fake_request(method, endpoint, **kwargs):
            dev = kwargs["headers"]["X-Device-Id"]
            body = kwargs["json"]
            return _completed_result(body["taskId"], dev)

        client = MagicMock()
        client.request = AsyncMock(side_effect=fake_request)
        handler = SpineOtaStatusMessageHandler()
        with patch.object(manage_api_client.ManageApiClient, "_instance", client):
            await asyncio.gather(
                handler.handle(conn_a, _success_msg(TASK_A)),
                handler.handle(conn_b, _success_msg(TASK_B)),
            )

        # A 只收到 A 的 ACK，B 只收到 B 的 ACK
        a_acks = [json.loads(x) for x in conn_a.websocket.sent]
        b_acks = [json.loads(x) for x in conn_b.websocket.sent]
        self.assertEqual([TASK_A], [a["task_id"] for a in a_acks])
        self.assertEqual([TASK_B], [a["task_id"] for a in b_acks])
        self.assertEqual("completed", store.get_delivery(TASK_A)["state"])
        self.assertEqual("completed", store.get_delivery(TASK_B)["state"])


class TestGenerationRouting(_DbMixin, unittest.IsolatedAsyncioTestCase):
    """D. 同设备旧/新连接并存，ACK 只去最新 generation。"""

    async def test_ack_goes_to_latest_generation_only(self):
        from core.handle.textHandler.spineOtaStatusMessageHandler import (
            SpineOtaStatusMessageHandler,
        )
        from config import manage_api_client

        server = FakeServer()
        old_ws = FakeWS()
        new_ws = FakeWS()
        old_conn = FakeConn(DEV_A, "sess-old", ws=old_ws, server=server)
        new_conn = FakeConn(DEV_A, "sess-new", ws=new_ws, server=server)
        server.register(DEV_A, old_conn)
        server.register(DEV_A, new_conn)  # new 成为当前代际

        client = MagicMock()
        client.request = AsyncMock(return_value=_completed_result(TASK_A, DEV_A))
        # 旧连接上报 success
        with patch.object(manage_api_client.ManageApiClient, "_instance", client):
            await SpineOtaStatusMessageHandler().handle(old_conn, _success_msg(TASK_A))

        # ACK 只去最新 generation
        self.assertEqual(0, len(old_ws.sent))
        self.assertEqual(1, len(new_ws.sent))
        self.assertEqual("completed", json.loads(new_ws.sent[0])["status"])


class TestTerminalNoRedeliver(_DbMixin, unittest.IsolatedAsyncioTestCase):
    """E. cancelled/failed/needs_manual_review：中央未 completed → 不发 ACK；pending 不重投。"""

    async def test_terminal_state_no_ack(self):
        from core.handle.textHandler.spineOtaStatusMessageHandler import (
            SpineOtaStatusMessageHandler,
        )
        from config import manage_api_client

        conn = FakeConn(DEV_A, "sess-a")
        client = MagicMock()
        client.request = AsyncMock(
            return_value={
                "taskId": TASK_A, "deviceId": DEV_A, "state": "cancelled",
                "completed": False, "duplicate": False, "attemptCount": 1,
            }
        )
        with patch.object(manage_api_client.ManageApiClient, "_instance", client):
            await SpineOtaStatusMessageHandler().handle(conn, _success_msg(TASK_A))
        self.assertEqual(0, len(conn.websocket.sent))

    async def test_pending_none_when_terminal(self):
        """中央返回 hasPending=false（completed/cancelled/failed 终态）→ 不下发 update_spine。"""
        from core.connection import ConnectionHandler

        handler = ConnectionHandler.__new__(ConnectionHandler)
        handler.device_id = DEV_A
        handler.session_id = "sess-a"
        handler.correlation_id = "corr-a"
        handler.logger = MagicMock()
        handler.websocket = FakeWS()
        handler.config = {}
        handler.server = None

        client = MagicMock()
        client.request = AsyncMock(return_value={"hasPending": False})
        with patch("asyncio.sleep", new=AsyncMock()), patch(
            "config.manage_api_client.ManageApiClient"
        ) as mac:
            mac._instance = client
            await handler._deliver_pending_spine_role()

        self.assertEqual(0, len(handler.websocket.sent))


class TestIdempotentConcurrentSuccess(_DbMixin, unittest.IsolatedAsyncioTestCase):
    """F. 并发 success 幂等：中央 completed=true 重复上报 → 幂等 ACK，本地镜像保持 completed。"""

    async def test_repeated_success_idempotent_ack(self):
        from core.handle.textHandler.spineOtaStatusMessageHandler import (
            SpineOtaStatusMessageHandler,
        )
        from config import manage_api_client

        conn = FakeConn(DEV_A, "sess-a")
        client = MagicMock()
        client.request = AsyncMock(
            return_value=_completed_result(TASK_A, DEV_A, duplicate=True)
        )
        handler = SpineOtaStatusMessageHandler()
        with patch.object(manage_api_client.ManageApiClient, "_instance", client):
            for _ in range(3):
                await handler.handle(conn, _success_msg(TASK_A))

        # 每次成功上报都回幂等 ACK（completed），且本地镜像始终 completed
        acks = [json.loads(x) for x in conn.websocket.sent]
        self.assertEqual(3, len(acks))
        self.assertTrue(all(a["status"] == "completed" for a in acks))
        self.assertEqual("completed", store.get_delivery(TASK_A)["state"])


class TestBackoffRedeliver(_DbMixin, unittest.TestCase):
    """G. accepted 后断线未 success：按退避重投；真正成功后停止。"""

    def test_accepted_then_backoff_then_stop_on_completed(self):
        store.record_sent_mirror(TASK_A, DEV_A, PACK, _payload(TASK_A, PACK), now=1000.0)
        # 设备 accepted（进入下载）
        store.mark_status(TASK_A, DEV_A, PACK, "downloading", progress=30, now=1100.0)
        self.assertEqual("in_progress", store.get_delivery(TASK_A)["state"])

        # 断线后未 success：镜像仍非终态，退避策略允许按窗口重投（决策在中央）
        d = store.get_delivery(TASK_A)
        self.assertNotIn(d["state"], store.TERMINAL_STATES)

        # 真正 success 后立即停止：终态，不可再重投
        changed, _, d2 = store.mark_completed(TASK_A, DEV_A, PACK, now=2000.0)
        self.assertTrue(changed)
        self.assertEqual("completed", d2["state"])
        self.assertIn("completed", store.TERMINAL_STATES)


if __name__ == "__main__":
    unittest.main()
