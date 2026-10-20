"""700 天 v2 WSS token + bootstrap 门禁 + v1 legacy 吊销 + 无缓存立即失效。"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from core.auth import (
    DEVICE_TOKEN_TTL_SECONDS,
    AuthenticationError,
    AuthManager,
)
from core.handle.connection_auth import (
    WS_AUTH_CLOSE_CODE,
    send_auth_error_and_close,
    verify_device_ws_token,
)
from core.utils.device_ws_auth_state import (
    AuthStateUnavailable,
    DeviceWsAuthState,
    clear_auth_state_cache,
    fetch_device_ws_auth_state,
)
from local_active_test_util import make_integrated_server


SECRET = "unit-test-wss-secret-do-not-use-in-prod"
DEVICE_A = "aa:bb:cc:dd:ee:01"
DEVICE_B = "aa:bb:cc:dd:ee:02"


class FakeWS:
    def __init__(self):
        self.sent = []
        self.closed = []
        self.request = MagicMock()
        self.request.headers = {}

    async def send(self, data):
        self.sent.append(data)

    async def close(self, code=1000, reason=""):
        self.closed.append({"code": code, "reason": reason})


class DeviceWsTokenV2Tests(unittest.TestCase):
    def setUp(self):
        clear_auth_state_cache()
        self.auth = AuthManager(SECRET, expire_seconds=DEVICE_TOKEN_TTL_SECONDS)

    def test_ttl_constant_700_days(self):
        self.assertEqual(DEVICE_TOKEN_TTL_SECONDS, 700 * 24 * 60 * 60)
        self.assertEqual(DEVICE_TOKEN_TTL_SECONDS, 60_480_000)

    def test_v2_exp_equals_iat_plus_ttl(self):
        before = int(time.time())
        token = self.auth.generate_token("c1", DEVICE_A, credential_version=2)
        after = int(time.time())
        parts = token.split(".")
        self.assertEqual(parts[0], "v2")
        self.assertEqual(len(parts), 5)
        iat, exp, ver = int(parts[2]), int(parts[3]), int(parts[4])
        self.assertEqual(ver, 2)
        self.assertEqual(exp - iat, DEVICE_TOKEN_TTL_SECONDS)
        self.assertGreaterEqual(iat, before)
        self.assertLessEqual(iat, after)

    def test_v2_tamper_rejects(self):
        token = self.auth.generate_token("c1", DEVICE_A, credential_version=1)
        parts = token.split(".")
        bad_sig = parts.copy()
        bad_sig[1] = "A" * len(parts[1])
        self.assertEqual(
            self.auth.verify_token_status(".".join(bad_sig), username=DEVICE_A),
            "invalid",
        )
        bad_exp = parts.copy()
        bad_exp[3] = str(int(parts[3]) + 99)
        self.assertEqual(
            self.auth.verify_token_status(".".join(bad_exp), username=DEVICE_A),
            "invalid",
        )
        bad_iat = parts.copy()
        bad_iat[2] = str(int(parts[2]) - 10)
        self.assertEqual(
            self.auth.verify_token_status(".".join(bad_iat), username=DEVICE_A),
            "invalid",
        )
        bad_ver = parts.copy()
        bad_ver[0] = "v3"
        self.assertEqual(
            self.auth.verify_token_status(".".join(bad_ver), username=DEVICE_A),
            "malformed",
        )
        self.assertEqual(
            self.auth.verify_token_status(token, username=DEVICE_B),
            "invalid",
        )
        bad_cv = parts.copy()
        bad_cv[4] = str(int(parts[4]) + 1)
        self.assertEqual(
            self.auth.verify_token_status(".".join(bad_cv), username=DEVICE_A),
            "invalid",
        )

    def test_ota_issues_v2_shape_not_v1(self):
        token = self.auth.generate_token("c1", DEVICE_A, credential_version=1)
        self.assertTrue(token.startswith("v2."))
        self.assertEqual(len(token.split(".")), 5)


class VerifyWithAuthStateTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        clear_auth_state_cache()
        self.auth = AuthManager(SECRET)

    async def test_v1_unbind_then_rebind_still_rejects_old_v1(self):
        v1 = self.auth.generate_v1_token("c1", DEVICE_A, expire_seconds=600)
        claims, st = self.auth.parse_and_verify(v1, username=DEVICE_A)
        self.assertEqual(st, "ok")
        iat = claims.iat

        active = DeviceWsAuthState(
            DEVICE_A.replace(":", ""), 1, "active", legacy_revoked_before_iat=None
        )
        with patch(
            "core.handle.connection_auth.fetch_device_ws_auth_state",
            new=AsyncMock(return_value=active),
        ):
            ok = await verify_device_ws_token(self.auth, token=v1, device_id=DEVICE_A)
            self.assertEqual(ok.version, "v1")

        unbound = DeviceWsAuthState(
            DEVICE_A.replace(":", ""),
            2,
            "unbound",
            legacy_revoked_before_iat=iat + 1,
        )
        with patch(
            "core.handle.connection_auth.fetch_device_ws_auth_state",
            new=AsyncMock(return_value=unbound),
        ):
            with self.assertRaises(AuthenticationError) as ctx:
                await verify_device_ws_token(self.auth, token=v1, device_id=DEVICE_A)
            self.assertEqual(ctx.exception.code, "device_unbound")

        # 重绑后 active，但 legacy 边界仍在 → 旧 v1 永久拒绝
        rebind = DeviceWsAuthState(
            DEVICE_A.replace(":", ""),
            3,
            "active",
            legacy_revoked_before_iat=iat + 1,
        )
        with patch(
            "core.handle.connection_auth.fetch_device_ws_auth_state",
            new=AsyncMock(return_value=rebind),
        ):
            with self.assertRaises(AuthenticationError) as ctx2:
                await verify_device_ws_token(self.auth, token=v1, device_id=DEVICE_A)
            self.assertEqual(ctx2.exception.code, "credential_revoked")

    async def test_unbind_rejects_same_v2_token(self):
        token = self.auth.generate_token("c1", DEVICE_A, credential_version=1)
        active = DeviceWsAuthState(DEVICE_A.replace(":", ""), 1, "active")
        with patch(
            "core.handle.connection_auth.fetch_device_ws_auth_state",
            new=AsyncMock(return_value=active),
        ):
            claims = await verify_device_ws_token(
                self.auth, token=token, device_id=DEVICE_A
            )
            self.assertEqual(claims.credential_version, 1)

        unbound = DeviceWsAuthState(DEVICE_A.replace(":", ""), 2, "unbound")
        with patch(
            "core.handle.connection_auth.fetch_device_ws_auth_state",
            new=AsyncMock(return_value=unbound),
        ):
            with self.assertRaises(AuthenticationError) as ctx:
                await verify_device_ws_token(
                    self.auth, token=token, device_id=DEVICE_A
                )
            self.assertEqual(ctx.exception.code, "device_unbound")

    async def test_rebind_new_v2_ok_old_rejected(self):
        old_token = self.auth.generate_token("c1", DEVICE_A, credential_version=1)
        new_token = self.auth.generate_token("c1", DEVICE_A, credential_version=2)
        state_v2 = DeviceWsAuthState(DEVICE_A.replace(":", ""), 2, "active")
        with patch(
            "core.handle.connection_auth.fetch_device_ws_auth_state",
            new=AsyncMock(return_value=state_v2),
        ):
            ok = await verify_device_ws_token(
                self.auth, token=new_token, device_id=DEVICE_A
            )
            self.assertEqual(ok.credential_version, 2)
            with self.assertRaises(AuthenticationError) as ctx:
                await verify_device_ws_token(
                    self.auth, token=old_token, device_id=DEVICE_A
                )
            self.assertEqual(ctx.exception.code, "credential_revoked")

    async def test_no_active_cache_window_after_unbind(self):
        """先读 active，解绑后立即用旧 token 握手必须拒绝（无 2s 放行窗）。"""
        token = self.auth.generate_token("c1", DEVICE_A, credential_version=1)
        states = [
            DeviceWsAuthState(DEVICE_A.replace(":", ""), 1, "active"),
            DeviceWsAuthState(DEVICE_A.replace(":", ""), 2, "unbound"),
        ]

        async def _fetch(_device_id, **kwargs):
            self.assertFalse(kwargs.get("use_cache", False))
            return states.pop(0)

        with patch(
            "core.handle.connection_auth.fetch_device_ws_auth_state",
            new=AsyncMock(side_effect=_fetch),
        ):
            await verify_device_ws_token(self.auth, token=token, device_id=DEVICE_A)
            with self.assertRaises(AuthenticationError) as ctx:
                await verify_device_ws_token(self.auth, token=token, device_id=DEVICE_A)
            self.assertEqual(ctx.exception.code, "device_unbound")

    async def test_auth_state_timeout_fail_closed(self):
        ws = FakeWS()
        token = self.auth.generate_token("c1", DEVICE_A, credential_version=1)
        with patch(
            "core.handle.connection_auth.fetch_device_ws_auth_state",
            new=AsyncMock(side_effect=AuthStateUnavailable("timeout")),
        ):
            with self.assertRaises(AuthenticationError) as ctx:
                await verify_device_ws_token(
                    self.auth, token=token, device_id=DEVICE_A
                )
            self.assertEqual(ctx.exception.code, "invalid_token")
        self.assertEqual(len(ws.sent), 0)
        self.assertEqual(len(ws.closed), 0)

    async def test_fetch_defaults_use_cache_false(self):
        with patch("config.manage_api_client.ManageApiClient") as mock_cls:
            mock_cls._instance = None
            with self.assertRaises(AuthStateUnavailable):
                await fetch_device_ws_auth_state(DEVICE_A)
            # 显式确认默认参数：通过 signature
            import inspect

            sig = inspect.signature(fetch_device_ws_auth_state)
            self.assertFalse(sig.parameters["use_cache"].default)


class AuthErrorProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_auth_failure_sends_json_then_close_1008(self):
        ws = FakeWS()
        await send_auth_error_and_close(ws, "token_expired")
        self.assertEqual(len(ws.sent), 1)
        obj = json.loads(ws.sent[0])
        self.assertEqual(obj["type"], "error")
        self.assertEqual(obj["code"], "token_expired")
        self.assertEqual(ws.closed[0]["code"], WS_AUTH_CLOSE_CODE)
        self.assertEqual(ws.closed[0]["reason"], "token_expired")
        self.assertNotEqual(ws.sent[0], "认证失败")
        self.assertTrue(ws.sent[0].startswith("{"))


class RevokeIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def test_revoke_closes_a_not_b(self):
        server = make_integrated_server()
        server.logger = MagicMock()

        class H:
            def __init__(self, did, sid):
                self.device_id = did
                self.session_id = sid
                self.superseded = False
                self.websocket = FakeWS()

        a_main = H(DEVICE_A, "sess-a")
        b_main = H(DEVICE_B, "sess-b")
        await server.register_connection(DEVICE_A, a_main)
        await server.register_connection(DEVICE_B, b_main)

        from core.reminder_control import ReminderControlContext

        rc_a = ReminderControlContext(
            websocket=FakeWS(),
            config={},
            device_id=DEVICE_A,
            client_id="c-a",
            account_id="1001",
        )
        ok = await server._reminder_control_manager.try_register(DEVICE_A, rc_a)
        self.assertTrue(ok)

        result = await server.revoke_device_connections(
            DEVICE_A, credential_version=2, status="unbound"
        )
        self.assertTrue(result["ok"])
        self.assertGreaterEqual(result["closed_main"], 1)
        self.assertGreaterEqual(result["closed_rc"], 1)

        self.assertIsNone(server._current_connection(DEVICE_A))
        self.assertIs(server._current_connection(DEVICE_B), b_main)
        self.assertEqual(len(b_main.websocket.closed), 0)

    async def test_revoke_missing_device_id(self):
        server = make_integrated_server()
        server.logger = MagicMock()
        r = await server.revoke_device_connections("")
        self.assertFalse(r["ok"])


class RevokeHttpAuthTests(unittest.IsolatedAsyncioTestCase):
    async def test_revoke_endpoint_secret_gate(self):
        from httpx import ASGITransport, AsyncClient
        from app import broadcast_app

        broadcast_app.state.config = {
            "manager-api": {"secret": "svc-secret-abc"},
        }
        server = make_integrated_server()
        server.logger = MagicMock()
        server.revoke_device_connections = AsyncMock(
            return_value={"ok": True, "closed_main": 0, "closed_rc": 0}
        )
        broadcast_app.state.ws_server = server

        transport = ASGITransport(app=broadcast_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r0 = await client.post(
                "/api/v1/device/revoke", json={"device_id": DEVICE_A}
            )
            self.assertEqual(r0.status_code, 401)
            server.revoke_device_connections.assert_not_called()
            self.assertNotIn("svc-secret", r0.text)

            r1 = await client.post(
                "/api/v1/device/revoke",
                json={"device_id": DEVICE_A},
                headers={"Authorization": "Bearer wrong"},
            )
            self.assertEqual(r1.status_code, 401)
            server.revoke_device_connections.assert_not_called()
            self.assertNotIn("svc-secret", r1.text)

            r2 = await client.post(
                "/api/v1/device/revoke",
                json={"device_id": DEVICE_A, "credential_version": 3},
                headers={"Authorization": "Bearer svc-secret-abc"},
            )
            self.assertEqual(r2.status_code, 200)
            self.assertTrue(r2.json().get("ok"))
            server.revoke_device_connections.assert_awaited()
            args, kwargs = server.revoke_device_connections.await_args
            self.assertEqual(args[0], DEVICE_A)


class StaticNoBroadcastTests(unittest.TestCase):
    def test_revoke_api_source_forbids_account_keys(self):
        path = os.path.join(os.path.dirname(__file__), "..", "app.py")
        with open(path, encoding="utf-8") as f:
            src = f.read()
        self.assertIn("account_dispatch_forbidden", src)
        self.assertIn("/api/v1/device/revoke", src)
        ws_path = os.path.join(
            os.path.dirname(__file__), "..", "core", "websocket_server.py"
        )
        with open(ws_path, encoding="utf-8") as f:
            ws_src = f.read()
        self.assertIn("async def revoke_device_connections", ws_src)
        self.assertIn("_get_device_send_lock(did)", ws_src)
        self.assertNotIn("for device_id in self._connections", ws_src)
        revoke_body = ws_src.split("async def revoke_device_connections")[1][:1200]
        self.assertNotIn("device_id=None", revoke_body)


class BootstrapGateDocTests(unittest.TestCase):
    """静态确认 OTA 签发路径要求 Authorization / X-Activation-Code，禁止仅 MAC。"""

    def test_ota_controller_passes_authorization(self):
        path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "manager-api",
            "src",
            "main",
            "java",
            "xiaozhi",
            "modules",
            "device",
            "controller",
            "OTAController.java",
        )
        with open(path, encoding="utf-8") as f:
            src = f.read()
        self.assertIn("Authorization", src)
        self.assertIn("X-Activation-Code", src)
        self.assertIn("authorization, activationCode", src)

    def test_device_service_requires_bootstrap_paths(self):
        path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "manager-api",
            "src",
            "main",
            "java",
            "xiaozhi",
            "modules",
            "device",
            "service",
            "impl",
            "DeviceServiceImpl.java",
        )
        with open(path, encoding="utf-8") as f:
            src = f.read()
        self.assertIn("verifyBootstrapKey", src)
        self.assertIn("redeemBootstrap", src)
        self.assertIn("attachWebsocketUrlOnly", src)
        self.assertIn("looksLikeWsToken", src)
        self.assertNotIn("isValidRefreshToken", src)
        self.assertNotIn("仍仅凭已绑定 MAC 即可领取 token", src)


if __name__ == "__main__":
    unittest.main()
