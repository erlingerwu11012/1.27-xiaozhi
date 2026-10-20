"""wallpaper OTA handler 与跨资源视觉 OTA 串行调度测试。"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.utils import wallpaper_ota_store as store

DEV_A = "aa:aa:aa:aa:aa:aa"
DEV_B = "bb:bb:bb:bb:bb:bb"
PACK = "wallpaper_pack_1"
TASK_A = "wall-task-aaaa"
TASK_B = "wall-task-bbbb"
SPINE_TASK = "spine-task-aaaa"
WALL_TASK = "wall-task-bbbb"


def _payload(task_id, pack_id):
    return {
        "type": "system",
        "command": "update_wallpaper",
        "task_id": task_id,
        "pack_id": pack_id,
        "url": "https://cdn.example/w",
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


def _registered_conn(device_id, session_id=None, ws=None):
    server = FakeServer()
    conn = FakeConn(device_id, session_id, ws=ws, server=server)
    server.register(device_id, conn)
    return conn, server


class FakeServer:
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
        conn.superseded = False

    def is_current_connection(self, device_id, handler):
        key = getattr(handler, "session_id", None)
        if self._current_sessions.get(device_id) != key:
            return False
        conns = self._connections.get(device_id) or {}
        return conns.get(key) is handler

    def _get_device_send_lock(self, device_id):
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
        store.set_db_path(os.path.join(self._tmp.name, "wallpaper_ota.db"))
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(lambda: store.set_db_path(None))


def _success_msg(task_id, device_id=None):
    msg = {"task_id": task_id, "pack_id": PACK, "phase": "success", "progress": 100}
    if device_id:
        msg["device_id"] = device_id
    return msg


def _failed_msg(task_id, error="E_NETWORK"):
    return {"task_id": task_id, "pack_id": PACK, "phase": "failed", "error": error}


def _completed_result(task_id, device_id, duplicate=False, state="completed"):
    return {
        "taskId": task_id,
        "deviceId": device_id,
        "state": state,
        "completed": True,
        "duplicate": duplicate,
        "attemptCount": 1,
    }


class TestHandlerRegistration(unittest.TestCase):
    def test_wallpaper_ota_status_registered(self):
        from core.handle.textMessageType import TextMessageType
        from core.handle.textHandler.wallpaperOtaStatusMessageHandler import (
            WallpaperOtaStatusMessageHandler,
        )

        handler = WallpaperOtaStatusMessageHandler()
        self.assertEqual(TextMessageType.WALLPAPER_OTA_STATUS, handler.message_type)

        registry_path = os.path.join(
            os.path.dirname(__file__), "..", "core", "handle", "textMessageHandlerRegistry.py"
        )
        with open(registry_path, encoding="utf-8") as f:
            src = f.read()
        self.assertIn("WallpaperOtaStatusMessageHandler", src)
        self.assertIn("wallpaperOtaStatusMessageHandler", src)


class TestWallpaperOtaHandler(_DbMixin, unittest.IsolatedAsyncioTestCase):
    async def test_success_sends_completed_ack(self):
        from core.handle.textHandler.wallpaperOtaStatusMessageHandler import (
            WallpaperOtaStatusMessageHandler,
        )
        from config import manage_api_client

        conn, _ = _registered_conn(DEV_A, "sess-a")
        client = MagicMock()
        client.request = AsyncMock(return_value=_completed_result(TASK_A, DEV_A))
        with patch.object(manage_api_client.ManageApiClient, "_instance", client):
            await WallpaperOtaStatusMessageHandler().handle(conn, _success_msg(TASK_A))

        self.assertEqual(1, len(conn.websocket.sent))
        ack = json.loads(conn.websocket.sent[0])
        self.assertEqual("wallpaper_ota_ack", ack["type"])
        self.assertEqual(TASK_A, ack["task_id"])
        self.assertEqual("completed", ack["status"])

    async def test_device_id_from_connection_not_payload(self):
        from core.handle.textHandler.wallpaperOtaStatusMessageHandler import (
            WallpaperOtaStatusMessageHandler,
        )
        from config import manage_api_client

        conn, _ = _registered_conn(DEV_A, "sess-a")
        client = MagicMock()
        client.request = AsyncMock(return_value=_completed_result(TASK_A, DEV_A))
        msg = _success_msg(TASK_A, device_id=DEV_B)
        with patch.object(manage_api_client.ManageApiClient, "_instance", client):
            await WallpaperOtaStatusMessageHandler().handle(conn, msg)

        headers = client.request.await_args.kwargs["headers"]
        self.assertEqual(DEV_A, headers["X-Device-Id"])

    async def test_failed_no_completed_ack(self):
        from core.handle.textHandler.wallpaperOtaStatusMessageHandler import (
            WallpaperOtaStatusMessageHandler,
        )
        from config import manage_api_client

        conn, _ = _registered_conn(DEV_A, "sess-a")
        client = MagicMock()
        client.request = AsyncMock(
            return_value={
                "taskId": TASK_A,
                "deviceId": DEV_A,
                "state": "failed",
                "completed": False,
                "duplicate": False,
                "attemptCount": 1,
            }
        )
        with patch.object(manage_api_client.ManageApiClient, "_instance", client):
            await WallpaperOtaStatusMessageHandler().handle(conn, _failed_msg(TASK_A))

        self.assertEqual(0, len(conn.websocket.sent))

    async def test_e_busy_no_completed_ack(self):
        from core.handle.textHandler.wallpaperOtaStatusMessageHandler import (
            WallpaperOtaStatusMessageHandler,
        )
        from config import manage_api_client

        conn, _ = _registered_conn(DEV_A, "sess-a")
        client = MagicMock()
        client.request = AsyncMock(
            return_value={
                "taskId": TASK_A,
                "deviceId": DEV_A,
                "state": "retrying",
                "completed": False,
                "duplicate": False,
                "attemptCount": 1,
            }
        )
        with patch.object(manage_api_client.ManageApiClient, "_instance", client):
            await WallpaperOtaStatusMessageHandler().handle(
                conn, _failed_msg(TASK_A, error="E_BUSY")
            )

        self.assertEqual(0, len(conn.websocket.sent))

    async def test_central_error_no_ack(self):
        from core.handle.textHandler.wallpaperOtaStatusMessageHandler import (
            WallpaperOtaStatusMessageHandler,
        )
        from config import manage_api_client

        conn, _ = _registered_conn(DEV_A, "sess-a")
        client = MagicMock()
        client.request = AsyncMock(side_effect=RuntimeError("central rejected"))
        with patch.object(manage_api_client.ManageApiClient, "_instance", client):
            await WallpaperOtaStatusMessageHandler().handle(conn, _success_msg(TASK_A))

        self.assertEqual(0, len(conn.websocket.sent))

    async def test_ack_only_to_current_generation(self):
        from core.handle.textHandler.wallpaperOtaStatusMessageHandler import (
            WallpaperOtaStatusMessageHandler,
        )
        from config import manage_api_client

        server = FakeServer()
        old_ws = FakeWS()
        new_ws = FakeWS()
        old_conn = FakeConn(DEV_A, "sess-old", ws=old_ws, server=server)
        new_conn = FakeConn(DEV_A, "sess-new", ws=new_ws, server=server)
        server.register(DEV_A, old_conn)
        server.register(DEV_A, new_conn)

        client = MagicMock()
        client.request = AsyncMock(return_value=_completed_result(TASK_A, DEV_A))
        with patch.object(manage_api_client.ManageApiClient, "_instance", client):
            await WallpaperOtaStatusMessageHandler().handle(old_conn, _success_msg(TASK_A))

        self.assertEqual(0, len(old_ws.sent))
        self.assertEqual(1, len(new_ws.sent))

    async def test_duplicate_success_idempotent(self):
        from core.handle.textHandler.wallpaperOtaStatusMessageHandler import (
            WallpaperOtaStatusMessageHandler,
        )
        from config import manage_api_client

        conn, _ = _registered_conn(DEV_A, "sess-a")
        client = MagicMock()
        client.request = AsyncMock(
            return_value=_completed_result(TASK_A, DEV_A, duplicate=True)
        )
        handler = WallpaperOtaStatusMessageHandler()
        with patch.object(manage_api_client.ManageApiClient, "_instance", client):
            await handler.handle(conn, _success_msg(TASK_A))
            await handler.handle(conn, _success_msg(TASK_A))

        self.assertEqual(2, len(conn.websocket.sent))
        self.assertEqual("completed", store.get_delivery(TASK_A)["state"])


class TestVisualOtaSerialDelivery(_DbMixin, unittest.IsolatedAsyncioTestCase):
    def _make_conn(self, device_id, session_id):
        conn = MagicMock()
        conn.device_id = device_id
        conn.session_id = session_id
        conn.logger = MagicMock()
        conn._is_stale_connection = MagicMock(return_value=False)
        conn._deliver_pending_spine_role = AsyncMock(return_value=False)
        conn._deliver_pending_wallpaper = AsyncMock(return_value=False)
        return conn

    async def test_both_pending_only_spine_delivered_first(self):
        from core.utils.visual_ota_delivery import deliver_pending_visual_ota

        conn = self._make_conn(DEV_A, "sess-a")
        conn._deliver_pending_spine_role = AsyncMock(return_value=True)
        with patch("asyncio.sleep", new=AsyncMock()):
            await deliver_pending_visual_ota(conn)

        conn._deliver_pending_spine_role.assert_awaited_once_with(_skip_initial_sleep=True)
        conn._deliver_pending_wallpaper.assert_not_awaited()

    async def test_spine_none_then_wallpaper_delivered(self):
        from core.utils.visual_ota_delivery import deliver_pending_visual_ota

        conn = self._make_conn(DEV_A, "sess-a")
        with patch("asyncio.sleep", new=AsyncMock()):
            await deliver_pending_visual_ota(conn)

        conn._deliver_pending_spine_role.assert_awaited_once_with(_skip_initial_sleep=True)
        conn._deliver_pending_wallpaper.assert_awaited_once_with(_skip_initial_sleep=True)

    async def test_different_devices_parallel(self):
        from core.utils.visual_ota_delivery import deliver_pending_visual_ota

        conn_a = self._make_conn(DEV_A, "sess-a")
        conn_b = self._make_conn(DEV_B, "sess-b")
        conn_a._deliver_pending_spine_role = AsyncMock(return_value=True)
        conn_b._deliver_pending_wallpaper = AsyncMock(return_value=True)
        conn_b._deliver_pending_spine_role = AsyncMock(return_value=False)

        with patch("asyncio.sleep", new=AsyncMock()):
            await asyncio.gather(
                deliver_pending_visual_ota(conn_a),
                deliver_pending_visual_ota(conn_b),
            )

        conn_a._deliver_pending_wallpaper.assert_not_awaited()
        conn_b._deliver_pending_spine_role.assert_awaited_once()
        conn_b._deliver_pending_wallpaper.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
