"""MCP initialize face_enrollment 动态身份字段（追踪到最终 send）。

运行:
  cd main/xiaozhi-server
  /root/miniconda3/envs/xiaozhi-esp32-server/bin/python test/test_mcp_initialize_identity.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.utils.face_enrollment_capability import (
    IdentitySnapshotResult,
    build_face_enrollment_capability,
    merge_identity_into_face_enrollment,
    _validate_snapshot_payload,
)


INDEPENDENT_KEY = "independent-signing-key-0123456789abcdef"


def _base_config(**overrides):
    server = {
        "public_base_url": "https://public.example.com",
        "websocket": "wss://public.example.com/xiaozhi/v1/",
        "auth_key": "device-pairing-secret-not-enroll-012345",
        "face": {
            "account_id": "",
            "identify_url": "http://127.0.0.1:8765/face/identify",
            "jwt_secret": "face-jwt-secret-for-unit-tests-only-32b",
            "timeout": 1.0,
        },
        "face_enrollment_upload_signing_key": INDEPENDENT_KEY,
    }
    server.update(overrides)
    return {"server": server}


def _conn(*, session_id="sess-a1", device_id="aa:bb:cc:dd:ee:01", account="10086"):
    conn = MagicMock()
    conn.features = {"mcp": True}
    conn.websocket = AsyncMock()
    conn.config = _base_config()
    conn.headers = {"device-id": device_id}
    conn.device_id = device_id
    conn.session_id = session_id
    conn.face_account_id = account
    conn.device_user_id = account
    conn.account_id = account
    conn.outbound_mode = None
    conn.superseded = False
    conn._outbound_closed = False
    conn.server = MagicMock()

    async def _send_to_current(device_id, data, handler=None, **kwargs):
        await handler.websocket.send(data)
        return True

    conn.server.send_to_current = AsyncMock(side_effect=_send_to_current)
    conn.server.is_current_connection = MagicMock(return_value=True)
    conn.stop_event = None
    return conn


class SnapshotValidationTests(unittest.TestCase):
    def test_valid_zero_faces(self):
        r = _validate_snapshot_payload(
            {"default_owner_person_id": "usr_aabbcc", "enrolled_count": 0}
        )
        self.assertTrue(r.ok)
        self.assertEqual(r.enrolled_count, 0)

    def test_missing_count_not_zero(self):
        r = _validate_snapshot_payload({"default_owner_person_id": "usr_aabbcc"})
        self.assertFalse(r.ok)

    def test_reject_bad_owner(self):
        for bad in ("default", "aa:bb:cc:dd:ee:ff", "10086", "usr_", None, 10086):
            r = _validate_snapshot_payload(
                {"default_owner_person_id": bad, "enrolled_count": 0}
            )
            self.assertFalse(r.ok, bad)

    def test_personal_mode_has_no_default_user(self):
        r=_validate_snapshot_payload({"default_owner_person_id":"","enrolled_count":2})
        self.assertTrue(r.ok)
        self.assertEqual(r.default_owner_person_id,"")
        self.assertFalse(_validate_snapshot_payload({"enrolled_count":2}).ok)

    def test_merge_fail_closed_omits_fields(self):
        static = build_face_enrollment_capability(_base_config()).capability
        merged = merge_identity_into_face_enrollment(
            static, IdentitySnapshotResult(ok=False, reason="http_401")
        )
        self.assertIn("session_url", merged)
        self.assertNotIn("enrolled_count", merged)
        self.assertNotIn("default_owner_person_id", merged)


class McpInitializeIdentitySendTests(unittest.IsolatedAsyncioTestCase):
    async def test_noface_bound_account_sends_count_zero_and_owner(self):
        from core.providers.tools.device_mcp.mcp_handler import (
            send_mcp_initialize_message,
        )

        conn = _conn()
        snap = IdentitySnapshotResult(
            ok=True,
            enrolled_count=0,
            default_owner_person_id="usr_owner01",
            reason="ok",
        )
        with patch(
            "core.utils.face_enrollment_capability.fetch_identity_capability_snapshot",
            new=AsyncMock(return_value=snap),
        ):
            await send_mcp_initialize_message(conn)
        self.assertTrue(conn.websocket.send.called)
        raw = conn.websocket.send.call_args[0][0]
        obj = json.loads(raw)
        fe = obj["payload"]["params"]["capabilities"]["face_enrollment"]
        self.assertEqual(fe["enrolled_count"], 0)
        self.assertEqual(fe["default_owner_person_id"], "usr_owner01")
        self.assertIn("session_url", fe)

    async def test_with_faces_count_is_template_total(self):
        from core.providers.tools.device_mcp.mcp_handler import (
            send_mcp_initialize_message,
        )

        conn = _conn()
        snap = IdentitySnapshotResult(
            ok=True,
            enrolled_count=3,
            default_owner_person_id="usr_owner01",
            reason="ok",
        )
        with patch(
            "core.utils.face_enrollment_capability.fetch_identity_capability_snapshot",
            new=AsyncMock(return_value=snap),
        ):
            await send_mcp_initialize_message(conn)
        fe = json.loads(conn.websocket.send.call_args[0][0])["payload"]["params"][
            "capabilities"
        ]["face_enrollment"]
        self.assertEqual(fe["enrolled_count"], 3)
        self.assertTrue(str(fe["default_owner_person_id"]).startswith("usr_"))

    async def test_same_account_ab_same_owner_separate_sends(self):
        from core.providers.tools.device_mcp.mcp_handler import (
            send_mcp_initialize_message,
        )

        snap = IdentitySnapshotResult(
            ok=True,
            enrolled_count=0,
            default_owner_person_id="usr_shared1",
            reason="ok",
        )
        a = _conn(session_id="sess-a", device_id="aa:aa:aa:aa:aa:01")
        b = _conn(session_id="sess-b", device_id="bb:bb:bb:bb:bb:02")
        with patch(
            "core.utils.face_enrollment_capability.fetch_identity_capability_snapshot",
            new=AsyncMock(return_value=snap),
        ):
            await send_mcp_initialize_message(a)
            await send_mcp_initialize_message(b)
        fe_a = json.loads(a.websocket.send.call_args[0][0])["payload"]["params"][
            "capabilities"
        ]["face_enrollment"]
        fe_b = json.loads(b.websocket.send.call_args[0][0])["payload"]["params"][
            "capabilities"
        ]["face_enrollment"]
        self.assertEqual(fe_a["default_owner_person_id"], fe_b["default_owner_person_id"])
        self.assertEqual(a.websocket.send.await_count, 1)
        self.assertEqual(b.websocket.send.await_count, 1)

    async def test_different_accounts_different_owners(self):
        from core.providers.tools.device_mcp.mcp_handler import (
            send_mcp_initialize_message,
        )

        async def snap_for(conn, **kwargs):
            aid = kwargs.get("account_id") or ""
            return IdentitySnapshotResult(
                ok=True,
                enrolled_count=0,
                default_owner_person_id=f"usr_{aid[-6:].rjust(6, '0')}",
                reason="ok",
            )

        a = _conn(account="111111")
        b = _conn(device_id="cc:cc:cc:cc:cc:03", session_id="sess-c", account="222222")
        with patch(
            "core.utils.face_enrollment_capability.fetch_identity_capability_snapshot",
            new=snap_for,
        ):
            await send_mcp_initialize_message(a)
            await send_mcp_initialize_message(b)
        oa = json.loads(a.websocket.send.call_args[0][0])["payload"]["params"][
            "capabilities"
        ]["face_enrollment"]["default_owner_person_id"]
        ob = json.loads(b.websocket.send.call_args[0][0])["payload"]["params"][
            "capabilities"
        ]["face_enrollment"]["default_owner_person_id"]
        self.assertNotEqual(oa, ob)

    async def test_unbound_or_api_fail_omits_dynamic_fields(self):
        from core.providers.tools.device_mcp.mcp_handler import (
            send_mcp_initialize_message,
        )

        # 无 userId
        unbound = _conn(account=None)
        unbound.face_account_id = None
        unbound.device_user_id = None
        unbound.account_id = None
        unbound.config["server"]["face"]["account_id"] = ""
        await send_mcp_initialize_message(unbound)
        fe = json.loads(unbound.websocket.send.call_args[0][0])["payload"]["params"][
            "capabilities"
        ]["face_enrollment"]
        self.assertNotIn("enrolled_count", fe)
        self.assertNotIn("default_owner_person_id", fe)

        # API 401 / 超时 / 非法响应：均不伪造 count=0
        for reason in ("http_401", "network", "invalid_owner", "invalid_count"):
            conn = _conn()
            with patch(
                "core.utils.face_enrollment_capability.fetch_identity_capability_snapshot",
                new=AsyncMock(
                    return_value=IdentitySnapshotResult(ok=False, reason=reason)
                ),
            ):
                await send_mcp_initialize_message(conn)
            fe2 = json.loads(conn.websocket.send.call_args[0][0])["payload"]["params"][
                "capabilities"
            ]["face_enrollment"]
            self.assertNotIn("enrolled_count", fe2, reason)
            self.assertNotIn("default_owner_person_id", fe2, reason)

    async def test_firmware_unknown_when_fields_absent(self):
        """新固件契约：两字段均缺失时不得视为 enrolled_count==0 旁路。"""
        from core.providers.tools.device_mcp.mcp_handler import (
            send_mcp_initialize_message,
        )

        conn = _conn()
        with patch(
            "core.utils.face_enrollment_capability.fetch_identity_capability_snapshot",
            new=AsyncMock(
                return_value=IdentitySnapshotResult(ok=False, reason="network")
            ),
        ):
            await send_mcp_initialize_message(conn)
        fe = json.loads(conn.websocket.send.call_args[0][0])["payload"]["params"][
            "capabilities"
        ]["face_enrollment"]
        # 固件侧：缺字段 = unknown；此处断言服务端绝不伪造 0
        self.assertTrue("enrolled_count" not in fe or fe.get("enrolled_count") is None)
        self.assertNotIn("default_owner_person_id", fe)

    async def test_reconnect_during_fetch_old_session_no_send(self):
        from core.providers.tools.device_mcp.mcp_handler import (
            send_mcp_initialize_message,
        )

        conn = _conn(session_id="sess-old")

        async def slow_snap(*a, **k):
            # 模拟请求期间会话被替换
            conn.session_id = "sess-new"
            conn.superseded = True
            return IdentitySnapshotResult(
                ok=True,
                enrolled_count=0,
                default_owner_person_id="usr_owner01",
                reason="ok",
            )

        with patch(
            "core.utils.face_enrollment_capability.fetch_identity_capability_snapshot",
            new=slow_snap,
        ):
            await send_mcp_initialize_message(conn)
        # 旧连接 superseded → initialize 整包跳过
        self.assertFalse(conn.websocket.send.called)

    async def test_legacy_firmware_static_fields_preserved(self):
        from core.providers.tools.device_mcp.mcp_handler import (
            send_mcp_initialize_message,
        )

        conn = _conn()
        snap = IdentitySnapshotResult(
            ok=True,
            enrolled_count=0,
            default_owner_person_id="usr_owner01",
            reason="ok",
        )
        with patch(
            "core.utils.face_enrollment_capability.fetch_identity_capability_snapshot",
            new=AsyncMock(return_value=snap),
        ):
            await send_mcp_initialize_message(conn)
        fe = json.loads(conn.websocket.send.call_args[0][0])["payload"]["params"][
            "capabilities"
        ]["face_enrollment"]
        for k in (
            "session_url",
            "protocol_version",
            "required_frames",
            "max_frames",
            "max_frame_bytes",
            "guided_burst_v1",
        ):
            self.assertIn(k, fe)
        self.assertEqual(fe["protocol_version"], 2)
        self.assertTrue(fe["guided_burst_v1"] is True)
        self.assertTrue(fe["session_url"].endswith("/mcp/face-enrollment/session"))



class ConcurrentIdentityAndReminderGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_accounts_distinct_enrolled_counts(self):
        """账号 A enrolled=0 / 账号 B enrolled=2，initialize 字段互不污染；mock 到最终 websocket.send。"""
        from core.providers.tools.device_mcp.mcp_handler import (
            send_mcp_initialize_message,
        )

        async def snap_for(conn, **kwargs):
            aid = kwargs.get("account_id") or ""
            if aid == "10001":
                return IdentitySnapshotResult(
                    ok=True,
                    enrolled_count=0,
                    default_owner_person_id="usr_aaaa01",
                    reason="ok",
                )
            if aid == "10002":
                return IdentitySnapshotResult(
                    ok=True,
                    enrolled_count=2,
                    default_owner_person_id="usr_bbbb02",
                    reason="ok",
                )
            return IdentitySnapshotResult(ok=False, reason="unexpected_account")

        a = _conn(account="10001", device_id="aa:aa:aa:aa:aa:01", session_id="sess-a")
        b = _conn(account="10002", device_id="bb:bb:bb:bb:bb:02", session_id="sess-b")
        with patch(
            "core.utils.face_enrollment_capability.fetch_identity_capability_snapshot",
            new=snap_for,
        ):
            await send_mcp_initialize_message(a)
            await send_mcp_initialize_message(b)

        fe_a = json.loads(a.websocket.send.call_args[0][0])["payload"]["params"][
            "capabilities"
        ]["face_enrollment"]
        fe_b = json.loads(b.websocket.send.call_args[0][0])["payload"]["params"][
            "capabilities"
        ]["face_enrollment"]
        self.assertEqual(fe_a["enrolled_count"], 0)
        self.assertEqual(fe_a["default_owner_person_id"], "usr_aaaa01")
        self.assertEqual(fe_b["enrolled_count"], 2)
        self.assertEqual(fe_b["default_owner_person_id"], "usr_bbbb02")
        self.assertEqual(a.websocket.send.await_count, 1)
        self.assertEqual(b.websocket.send.await_count, 1)
        # 互不污染
        self.assertNotEqual(a.device_id, b.device_id)
        self.assertNotEqual(fe_a["default_owner_person_id"], fe_b["default_owner_person_id"])

    async def test_identity_fail_omits_fields_and_blocks_private_reminder(self):
        from core.providers.tools.device_mcp.mcp_handler import (
            send_mcp_initialize_message,
        )
        from core.utils.proactive_greeting import can_dispatch_private_device_reminder

        conn = _conn()
        with patch(
            "core.utils.face_enrollment_capability.fetch_identity_capability_snapshot",
            new=AsyncMock(
                return_value=IdentitySnapshotResult(ok=False, reason="http_401")
            ),
        ), patch(
            "core.utils.reminder_voice.process_reminder_voice_request",
            new=AsyncMock(),
        ) as reminder_mock:
            await send_mcp_initialize_message(conn)
            fe = json.loads(conn.websocket.send.call_args[0][0])["payload"]["params"][
                "capabilities"
            ]["face_enrollment"]
            self.assertNotIn("enrolled_count", fe)
            self.assertNotIn("default_owner_person_id", fe)
            self.assertFalse(can_dispatch_private_device_reminder(conn))
            reminder_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
