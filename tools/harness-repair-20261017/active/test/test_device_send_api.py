"""HTTP /api/v1/device/send 真实 ASGI 路由测试（httpx.AsyncClient + ASGITransport）。

运行:
  cd main/xiaozhi-server
  /root/miniconda3/envs/xiaozhi-esp32-server/bin/python test/test_device_send_api.py
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from unittest.mock import MagicMock

import httpx
from httpx import ASGITransport

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import broadcast_app
from core.utils import service_auth
from core.websocket_server import WebSocketServer


SECRET = "unit-test-service-secret-not-for-prod"
AUTH_KEY = "should-never-be-used-as-service-secret"
SERVER_SECRET_FALLBACK = "python-server-secret-must-not-be-used"


class FakeWS:
    def __init__(self):
        self.sent = []

    async def send(self, data):
        self.sent.append(data)


def _handler(device_id: str, session_id: str):
    h = MagicMock()
    h.device_id = device_id
    h.session_id = session_id
    h.correlation_id = "corr-" + session_id
    h.websocket = FakeWS()
    h.superseded = False
    h.stop_event = None
    h.server = None
    return h


def _build_server():
    server = WebSocketServer.__new__(WebSocketServer)
    server.logger = MagicMock()
    server._connections = {}
    server._current_sessions = {}
    server._device_send_locks = {}
    server._reminder_control_manager = None
    return server


class DeviceSendApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.server = _build_server()
        self.a = _handler("dev-a", "sess-a-cur")
        self.b = _handler("dev-b", "sess-b-cur")
        self.server._register_connection("dev-a", self.a)
        self.server._register_connection("dev-b", self.b)
        self.a_old = _handler("dev-a", "sess-a-old")
        self.a_old.superseded = True
        self.server._connections["dev-a"]["sess-a-old"] = self.a_old
        self.server._current_sessions["dev-a"] = "sess-a-cur"

        broadcast_app.state.ws_server = self.server
        broadcast_app.state.config = {
            "manager-api": {"secret": SECRET},
            "server": {
                "auth_key": AUTH_KEY,
                "secret": SERVER_SECRET_FALLBACK,
            },
        }
        transport = ASGITransport(app=broadcast_app)
        self.client = httpx.AsyncClient(transport=transport, base_url="http://testserver")

    async def asyncTearDown(self):
        await self.client.aclose()

    async def _post(self, body, headers=None, params=None):
        return await self.client.post(
            "/api/v1/device/send",
            json=body,
            headers=headers or {},
            params=params or {},
        )

    def _assert_zero_send(self):
        self.assertEqual(self.a.websocket.sent, [])
        self.assertEqual(self.b.websocket.sent, [])
        self.assertEqual(self.a_old.websocket.sent, [])

    async def test_broadcast_route_is_404(self):
        r = await self.client.post("/api/v1/broadcast", json={"text": "x"})
        self.assertEqual(r.status_code, 404)

    async def test_missing_secret_401_zero_send(self):
        r = await self._post(
            {"device_id": "dev-a", "payload": {"type": "system", "command": "ping"}}
        )
        self.assertEqual(r.status_code, 401)
        self._assert_zero_send()

    async def test_wrong_secret_401_zero_send(self):
        r = await self._post(
            {"device_id": "dev-a", "payload": {"type": "system", "command": "ping"}},
            headers={"Authorization": "Bearer wrong-secret"},
        )
        self.assertEqual(r.status_code, 401)
        self._assert_zero_send()

    async def test_unconfigured_dedicated_secret_401_zero_send(self):
        broadcast_app.state.config = {
            "manager-api": {},
            "server": {"auth_key": AUTH_KEY, "secret": SERVER_SECRET_FALLBACK},
        }
        r = await self._post(
            {"device_id": "dev-a", "payload": {"type": "system", "command": "ping"}},
            headers={"Authorization": f"Bearer {SERVER_SECRET_FALLBACK}"},
        )
        self.assertEqual(r.status_code, 401)
        self._assert_zero_send()

        r2 = await self._post(
            {"device_id": "dev-a", "payload": {"type": "system", "command": "ping"}},
            headers={"Authorization": f"Bearer {AUTH_KEY}"},
        )
        self.assertEqual(r2.status_code, 401)
        self._assert_zero_send()

    async def test_placeholder_secret_401_zero_send(self):
        broadcast_app.state.config = {
            "manager-api": {"secret": "changeme"},
            "server": {"auth_key": AUTH_KEY},
        }
        r = await self._post(
            {"device_id": "dev-a", "payload": {"type": "system", "command": "ping"}},
            headers={"Authorization": "Bearer changeme"},
        )
        self.assertEqual(r.status_code, 401)
        self._assert_zero_send()

    async def test_correct_header_plus_body_secret_401_zero_send(self):
        r = await self._post(
            {
                "device_id": "dev-a",
                "payload": {"type": "system", "command": "ping"},
                "secret": SECRET,
            },
            headers={"Authorization": f"Bearer {SECRET}"},
        )
        self.assertEqual(r.status_code, 401)
        self._assert_zero_send()

    async def test_correct_header_plus_query_token_401_zero_send(self):
        r = await self._post(
            {"device_id": "dev-a", "payload": {"type": "system", "command": "ping"}},
            headers={"Authorization": f"Bearer {SECRET}"},
            params={"token": SECRET},
        )
        self.assertEqual(r.status_code, 401)
        self._assert_zero_send()

    async def test_correct_header_plus_query_authorization_401_zero_send(self):
        r = await self._post(
            {"device_id": "dev-a", "payload": {"type": "system", "command": "ping"}},
            headers={"Authorization": f"Bearer {SECRET}"},
            params={"authorization": f"Bearer {SECRET}"},
        )
        self.assertEqual(r.status_code, 401)
        self._assert_zero_send()

    async def test_correct_header_plus_body_account_id_400_zero_send(self):
        r = await self._post(
            {
                "device_id": "dev-a",
                "account_id": "10086",
                "payload": {"type": "system", "command": "ping"},
            },
            headers={"Authorization": f"Bearer {SECRET}"},
        )
        self.assertEqual(r.status_code, 400)
        self._assert_zero_send()

    async def test_correct_header_plus_body_user_id_400_zero_send(self):
        r = await self._post(
            {
                "user_id": "10086",
                "payload": {"type": "system", "command": "ping"},
            },
            headers={"Authorization": f"Bearer {SECRET}"},
        )
        self.assertEqual(r.status_code, 400)
        self._assert_zero_send()

    async def test_valid_secret_sends_only_a_current(self):
        r = await self._post(
            {
                "device_id": "dev-a",
                "payload": {
                    "type": "system",
                    "command": "update_spine",
                    "task_id": "t1",
                },
            },
            headers={"Authorization": f"Bearer {SECRET}"},
        )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json().get("ok"))
        self.assertEqual(len(self.a.websocket.sent), 1)
        self.assertEqual(self.b.websocket.sent, [])
        self.assertEqual(self.a_old.websocket.sent, [])
        body = json.loads(self.a.websocket.sent[0])
        self.assertEqual(body["command"], "update_spine")

    async def test_stale_session_id_zero_send(self):
        r = await self._post(
            {
                "device_id": "dev-a",
                "session_id": "sess-a-old",
                "payload": {"type": "system", "command": "ping"},
            },
            headers={"Authorization": f"Bearer {SECRET}"},
        )
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json().get("ok"))
        self._assert_zero_send()

    async def test_device_id_null_400_zero_send(self):
        r = await self._post(
            {"device_id": None, "payload": {"type": "system", "command": "ping"}},
            headers={"Authorization": f"Bearer {SECRET}"},
        )
        self.assertEqual(r.status_code, 400)
        self._assert_zero_send()

    async def test_get_service_secret_no_auth_key_fallback(self):
        secret, reason = service_auth.get_service_secret(
            {"manager-api": {}, "server": {"auth_key": AUTH_KEY, "secret": "x"}}
        )
        self.assertEqual(secret, "")
        self.assertEqual(reason, "secret_unconfigured")
        secret2, reason2 = service_auth.get_service_secret(
            {"manager-api": {"secret": SECRET}}
        )
        self.assertEqual(secret2, SECRET)
        self.assertEqual(reason2, "")


if __name__ == "__main__":
    unittest.main()
