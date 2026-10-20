"""identity-snapshot 请求形态 + 出站日志脱敏行为测试。

运行:
  cd main/xiaozhi-server
  /root/miniconda3/envs/xiaozhi-esp32-server/bin/python test/test_identity_snapshot_request.py
"""

from __future__ import annotations

import io
import json
import logging
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))


class _FakeResp:
    def __init__(self, status=200, data=None):
        self.status = status
        self._data = data or {
            "enrolled_count": 0,
            "default_owner_person_id": "usr_owner01",
        }

    async def json(self):
        return self._data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _FakeSession:
    last_request = None

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def post(self, url, headers=None, data=None, json=None, params=None, **kwargs):
        _FakeSession.last_request = {
            "url": url,
            "headers": dict(headers or {}),
            "data": data,
            "json": json,
            "params": params,
            "kwargs": kwargs,
        }
        return _FakeResp()


class IdentitySnapshotRequestTests(unittest.IsolatedAsyncioTestCase):
    async def test_snapshot_request_has_no_account_id_outside_jwt(self):
        from core.utils.face_enrollment_capability import (
            fetch_identity_capability_snapshot,
        )

        conn = MagicMock()
        conn.config = {
            "server": {
                "face": {
                    "identify_url": "http://127.0.0.1:8765/face/identify",
                    "jwt_secret": "face-jwt-secret-for-unit-tests-only-32b",
                    "timeout": 1.0,
                }
            }
        }
        conn.session_id = "sess-1"
        conn.superseded = False
        conn.outbound_mode = "local_active"
        conn._outbound_closed = False
        conn.server = None
        conn.stop_event = None

        with patch(
            "core.utils.face_enrollment_capability.aiohttp.ClientSession",
            _FakeSession,
        ), patch(
            "core.utils.face_enrollment_capability.build_face_jwt_from_config",
            return_value="header.payload.sig",
        ), patch(
            "core.utils.face_enrollment_capability.is_outbound_allowed",
            return_value=True,
        ):
            result = await fetch_identity_capability_snapshot(
                conn,
                account_id="10086",
                device_id="aa:bb:cc:dd:ee:01",
                capture_session_id="sess-1",
            )

        self.assertTrue(result.ok)
        req = _FakeSession.last_request
        self.assertIsNotNone(req)
        # 真正空 body（aiohttp data=b""）；不得 json={}
        self.assertEqual(req["data"], b"")
        self.assertIsNone(req["json"])
        self.assertTrue(
            req["params"] is None or "account_id" not in (req["params"] or {})
        )
        # URL / query / 额外 header 不得含 account_id
        self.assertNotIn("account_id", req["url"])
        self.assertNotIn("10086", req["url"])
        header_keys = {k.lower() for k in req["headers"]}
        self.assertNotIn("x-account-id", header_keys)
        self.assertNotIn("account_id", header_keys)
        self.assertNotIn("account-id", header_keys)
        # Authorization 仅验证存在 Bearer JWT；不在断言/日志中输出 JWT 明文全文
        auth = req["headers"].get("Authorization") or req["headers"].get("authorization")
        self.assertIsNotNone(auth)
        self.assertTrue(str(auth).startswith("Bearer "))
        self.assertGreater(len(str(auth)), len("Bearer "))
        for k, v in req["headers"].items():
            if k.lower() == "authorization":
                continue
            self.assertNotIn("10086", str(v))
            self.assertNotIn("account_id", str(v).lower())

    async def test_snapshot_failure_omits_both_dynamic_fields(self):
        from core.providers.tools.device_mcp.mcp_handler import (
            send_mcp_initialize_message,
        )
        from core.utils.face_enrollment_capability import IdentitySnapshotResult

        conn = MagicMock()
        conn.features = {"mcp": True}
        conn.websocket = AsyncMock()
        conn.config = {
            "server": {
                "public_base_url": "https://public.example.com",
                "auth_key": "device-pairing-secret-not-enroll-012345",
                "face": {
                    "account_id": "",
                    "identify_url": "http://127.0.0.1:8765/face/identify",
                    "jwt_secret": "face-jwt-secret-for-unit-tests-only-32b",
                    "timeout": 1.0,
                },
                "face_enrollment_upload_signing_key": "independent-signing-key-0123456789abcdef",
            }
        }
        conn.headers = {"device-id": "aa:bb:cc:dd:ee:01"}
        conn.device_id = "aa:bb:cc:dd:ee:01"
        conn.session_id = "sess-x"
        conn.face_account_id = "10086"
        conn.device_user_id = "10086"
        conn.account_id = "10086"
        conn.outbound_mode = None
        conn.superseded = False
        conn._outbound_closed = False
        conn.server = MagicMock()
        conn.stop_event = None

        async def _send_to_current(device_id, data, handler=None, **kwargs):
            await conn.websocket.send(data)
            return True

        conn.server.send_to_current = AsyncMock(side_effect=_send_to_current)
        conn.server.is_current_connection = MagicMock(return_value=True)

        with patch(
            "core.utils.face_enrollment_capability.fetch_identity_capability_snapshot",
            new=AsyncMock(
                return_value=IdentitySnapshotResult(ok=False, reason="http_401")
            ),
        ):
            await send_mcp_initialize_message(conn)

        caps = json.loads(conn.websocket.send.call_args[0][0])["payload"]["params"]["capabilities"]
        self.assertNotIn("face_enrollment", caps)  # No usable enrollment grant after 401.
        self.assertNotIn("identity_context", caps)


class OutboundLogPrivacyTests(unittest.IsolatedAsyncioTestCase):
    async def test_device_send_log_has_no_private_payload_text(self):
        from core.websocket_server import WebSocketServer

        server = WebSocketServer.__new__(WebSocketServer)
        server.logger = MagicMock()
        bind_logger = MagicMock()
        server.logger.bind.return_value = bind_logger
        server._connections = {}
        server._current_sessions = {}
        server._device_send_locks = {}
        server._reminder_control_manager = None

        h = MagicMock()
        h.device_id = "dev-a"
        h.session_id = "sess-1"
        h.correlation_id = "corr-1"
        h.superseded = False
        h.stop_event = None
        h.server = server

        class WS:
            def __init__(self):
                self.sent = []

            async def send(self, data):
                self.sent.append(data)

        h.websocket = WS()
        server._register_connection("dev-a", h)

        private = {
            "type": "mcp",
            "payload": {
                "method": "tools/call",
                "params": {"name": "note", "arguments": {"text": "记得喝水，私密内容XYZ"}},
            },
        }
        ok = await server.send_to_current(
            "dev-a",
            json.dumps(private, ensure_ascii=False),
            handler=h,
            command="mcp",
            msg_type="mcp",
            task_id="task-privacy",
        )
        self.assertTrue(ok)
        self.assertEqual(len(h.websocket.sent), 1)

        # 所有 info/error 日志不得包含私密正文
        logged = []
        for call in bind_logger.info.call_args_list + bind_logger.error.call_args_list:
            logged.append(" ".join(str(a) for a in call.args))
        blob = "\n".join(logged)
        self.assertNotIn("喝水", blob)
        self.assertNotIn("私密内容XYZ", blob)
        self.assertIn("payload_bytes=", blob)
        self.assertIn("target_device_id=dev-a", blob)
        self.assertIn("session_id=sess-1", blob)


if __name__ == "__main__":
    unittest.main()
