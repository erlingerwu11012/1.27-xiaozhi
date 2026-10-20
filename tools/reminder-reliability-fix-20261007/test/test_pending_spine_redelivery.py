"""update_spine 中央权威 + 本地审计镜像测试。

架构说明：
- 投递决策完全由 manager-api 中央状态机负责（pending 查询 + 退避 + 次数上限 + 原子递增）。
- 本地 SQLite（core.utils.spine_ota_store）仅为审计镜像，不参与投递决策，可安全丢失/重建。
- spine_ota_status 先上报中央 ACK，仅当中央返回 completed=true 时才向设备回 spine_ota_ack。

覆盖：
- 本地镜像：record_sent_mirror 递增次数、mark_completed/mark_failed/mark_status 幂等推进、cancel 镜像。
- 设备隔离：task_id 与 device_id 不匹配时拒绝推进（DeviceMismatchError）。
- handler：中央 completed=true 才回 ACK；completed=false / 中央异常 不回 ACK；重复 success 幂等仍回 completed。
- 纯策略：退避/最大次数（本地保留的策略纯函数，用于 next_attempt_at 计算）。
"""

from __future__ import annotations

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


class _DbMixin:
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        store.set_db_path(os.path.join(self._tmp.name, "spine_ota.db"))
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(lambda: store.set_db_path(None))


class StoreMirrorTests(_DbMixin, unittest.TestCase):
    def test_record_sent_mirror_increments_attempt(self):
        store.record_sent_mirror(TASK_A, DEV_A, PACK, _payload(TASK_A, PACK), now=1000.0)
        d = store.get_delivery(TASK_A)
        self.assertEqual("sent", d["state"])
        self.assertEqual(1, d["attempt_count"])
        self.assertEqual(DEV_A, d["device_id"])

        store.record_sent_mirror(TASK_A, DEV_A, PACK, _payload(TASK_A, PACK), now=2000.0)
        d2 = store.get_delivery(TASK_A)
        self.assertEqual(2, d2["attempt_count"])

    def test_mark_completed_and_idempotent(self):
        store.record_sent_mirror(TASK_A, DEV_A, PACK, _payload(TASK_A, PACK), now=1000.0)
        changed, _, d = store.mark_completed(TASK_A, DEV_A, PACK, now=1100.0)
        self.assertTrue(changed)
        self.assertEqual("completed", d["state"])
        self.assertIsNotNone(d["completed_at"])

        changed2, prev2, d2 = store.mark_completed(TASK_A, DEV_A, PACK, now=1200.0)
        self.assertFalse(changed2)
        self.assertEqual("completed", prev2)
        self.assertEqual("completed", d2["state"])

    def test_cancel_device_mirror(self):
        store.record_sent_mirror(TASK_A, DEV_A, PACK, _payload(TASK_A, PACK), now=1000.0)
        cancelled = store.cancel_device(DEV_A, reason="reboot_loop")
        self.assertEqual([TASK_A], [c["task_id"] for c in cancelled])
        d = store.get_delivery(TASK_A)
        self.assertEqual("cancelled", d["state"])
        self.assertEqual("reboot_loop", d["cancel_reason"])
        self.assertIsNotNone(d["cancelled_at"])

    def test_device_isolation_on_mirror(self):
        store.record_sent_mirror(TASK_A, DEV_A, PACK, _payload(TASK_A, PACK), now=1000.0)
        with self.assertRaises(store.DeviceMismatchError):
            store.record_sent_mirror(TASK_A, DEV_B, PACK, _payload(TASK_A, PACK), now=1000.0)
        with self.assertRaises(store.DeviceMismatchError):
            store.mark_status(TASK_A, DEV_B, PACK, "downloading")
        # A 状态未被 B 篡改
        self.assertEqual("sent", store.get_delivery(TASK_A)["state"])
        self.assertEqual(DEV_A, store.get_delivery(TASK_A)["device_id"])

    def test_other_device_unaffected_by_cancel(self):
        store.record_sent_mirror(TASK_A, DEV_A, PACK, _payload(TASK_A, PACK), now=1000.0)
        store.record_sent_mirror(TASK_B, DEV_B, PACK, _payload(TASK_B, PACK), now=1000.0)
        store.cancel_device(DEV_A, reason="only_a")
        self.assertEqual("cancelled", store.get_delivery(TASK_A)["state"])
        self.assertEqual("sent", store.get_delivery(TASK_B)["state"])


class StorePolicyTests(_DbMixin, unittest.TestCase):
    def test_exponential_backoff(self):
        self.assertAlmostEqual(30.0, store.backoff_after(1, 30.0), delta=0.001)
        self.assertAlmostEqual(60.0, store.backoff_after(2, 30.0), delta=0.001)
        self.assertAlmostEqual(120.0, store.backoff_after(3, 30.0), delta=0.001)

    def test_decide_delivery(self):
        self.assertEqual("deliver", store.decide_delivery(0, None, 1000.0, 3))
        self.assertEqual("stop", store.decide_delivery(3, None, 1000.0, 3))
        self.assertEqual("skip_backoff", store.decide_delivery(1, 2000.0, 1000.0, 3))
        self.assertEqual("deliver", store.decide_delivery(1, 999.0, 1000.0, 3))


class FakeWS:
    def __init__(self):
        self.sent = []

    async def send(self, data):
        self.sent.append(data)


class _FakeConn:
    def __init__(self, device_id):
        self.device_id = device_id
        self.session_id = f"sess-{device_id}"
        self.logger = MagicMock()
        self.websocket = FakeWS()
        self.config = {}
        self.server = None
        sys.path.insert(0, os.path.dirname(__file__))
        from local_active_test_util import bind_local_active_registry

        bind_local_active_registry(self)


class SpineOtaStatusHandlerTests(_DbMixin, unittest.IsolatedAsyncioTestCase):
    async def _handle(self, conn, msg, ack_result):
        from core.handle.textHandler.spineOtaStatusMessageHandler import (
            SpineOtaStatusMessageHandler,
        )
        from config import manage_api_client

        client = MagicMock()
        client.request = AsyncMock(return_value=ack_result)
        with patch.object(manage_api_client.ManageApiClient, "_instance", client):
            await SpineOtaStatusMessageHandler().handle(conn, msg)
        return client

    def _success_msg(self):
        return {"task_id": TASK_A, "pack_id": PACK, "phase": "success", "progress": 100}

    async def test_success_with_central_completed_sends_ack(self):
        conn = _FakeConn(DEV_A)
        await self._handle(
            conn,
            self._success_msg(),
            {"taskId": TASK_A, "deviceId": DEV_A, "state": "completed",
             "completed": True, "duplicate": False, "attemptCount": 1},
        )
        self.assertEqual(1, len(conn.websocket.sent))
        ack = json.loads(conn.websocket.sent[0])
        self.assertEqual("spine_ota_ack", ack["type"])
        self.assertEqual(TASK_A, ack["task_id"])
        self.assertEqual("completed", ack["status"])
        # 本地镜像同步为 completed
        self.assertEqual("completed", store.get_delivery(TASK_A)["state"])

    async def test_success_duplicate_still_acks_completed(self):
        conn = _FakeConn(DEV_A)
        for _ in range(2):
            await self._handle(
                conn,
                self._success_msg(),
                {"taskId": TASK_A, "deviceId": DEV_A, "state": "completed",
                 "completed": True, "duplicate": True, "attemptCount": 1},
            )
        self.assertEqual(2, len(conn.websocket.sent))
        for raw in conn.websocket.sent:
            self.assertEqual("completed", json.loads(raw)["status"])

    async def test_success_with_central_not_completed_does_not_ack(self):
        conn = _FakeConn(DEV_A)
        await self._handle(
            conn,
            self._success_msg(),
            {"taskId": TASK_A, "deviceId": DEV_A, "state": "cancelled",
             "completed": False, "duplicate": False, "attemptCount": 1},
        )
        self.assertEqual(0, len(conn.websocket.sent))

    async def test_central_ack_failure_does_not_ack(self):
        from core.handle.textHandler.spineOtaStatusMessageHandler import (
            SpineOtaStatusMessageHandler,
        )
        from config import manage_api_client

        conn = _FakeConn(DEV_A)
        client = MagicMock()
        client.request = AsyncMock(side_effect=RuntimeError("boom"))
        with patch.object(manage_api_client.ManageApiClient, "_instance", client):
            await SpineOtaStatusMessageHandler().handle(conn, self._success_msg())
        self.assertEqual(0, len(conn.websocket.sent))

    async def test_progress_phase_does_not_ack(self):
        conn = _FakeConn(DEV_A)
        client = await self._handle(
            conn,
            {"task_id": TASK_A, "pack_id": PACK, "phase": "downloading", "progress": 50},
            {"taskId": TASK_A, "deviceId": DEV_A, "state": "in_progress",
             "completed": False, "duplicate": False, "attemptCount": 1},
        )
        self.assertEqual(0, len(conn.websocket.sent))
        # 上报中央时携带连接 device_id，而非 payload
        body = client.request.await_args.kwargs["json"]
        self.assertEqual("downloading", body["phase"])
        self.assertEqual(DEV_A, client.request.await_args.kwargs["headers"]["X-Device-Id"])


if __name__ == "__main__":
    unittest.main()
