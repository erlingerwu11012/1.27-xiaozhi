"""Guided Burst V2-only：capability、网关鉴权与响应契约。"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from aiohttp import FormData, web
from aiohttp.test_utils import TestClient, TestServer

from core.api.face_enrollment_handler import FaceEnrollmentHandler
from core.auth import AuthManager
from core.utils.face_enrollment_capability import (
    build_face_enrollment_capability,
    build_face_enrollment_capability_for_conn,
)
from core.utils.face_enrollment_limits import reset_limiters_for_tests, reset_metrics_for_tests
from core.utils.face_enrollment_v2 import (
    DRAFT_READY_FIELD_MISSING,
    GUIDANCE_CODES,
    UPLOAD_TOKEN_SCOPE_V2,
    V2_CREATE_JSON_MAX_BYTES,
    V2_CREATE_TIMEOUT_SLACK_SECONDS,
    V2_SESSION_TIMEOUT_SECONDS,
    build_v2_guidance_payload,
    is_device_allowed_for_v2,
    parse_accepted_count,
    reset_session_policies_for_tests,
    resolve_v2_session_url,
    sanitize_guidance_code,
    v2_error_body,
    v2_guidance_ok,
)

INDEPENDENT_KEY = "enroll-upload-signing-key-32chars!!"


def _v2_upstream(session_id: str = "siddeadbeef0001", **overrides):
    """完整合法的 face-api V2 create 成功体。"""
    body = {
        "session_id": session_id,
        "expires_at": 9999999999,
        "protocol_version": 2,
        "guided_burst_v1": True,
        "required_frames": 3,
        "max_frames": 3,
    }
    body.update(overrides)
    return body


def _cfg(**overrides):
    cfg = {
        "server": {
            "auth_key": "device-pairing-secret-not-enroll",
            "public_base_url": "https://public.example.com",
            "websocket": "wss://public.example.com/xiaozhi/v1/",
            "auth": {"enabled": True, "expire_seconds": 86400},
            "face": {
                "account_id": "acct_a",
                "jwt_secret": "face-jwt-secret-not-for-device-xx",
                "identify_url": "http://127.0.0.1:8765/face/identify",
                "timeout": 2.0,
            },
            "face_enrollment_upload_signing_key": INDEPENDENT_KEY,
        }
    }
    cfg["server"].update(overrides)
    return cfg


class V2FlagAndCapabilityTests(unittest.IsolatedAsyncioTestCase):
    def test_capability_always_v2(self):
        r = build_face_enrollment_capability(_cfg())
        self.assertTrue(r.ok)
        cap = r.capability
        self.assertEqual(cap["protocol_version"], 2)
        self.assertTrue(cap["guided_burst_v1"] is True)
        self.assertEqual(cap["session_timeout_seconds"], 240)
        self.assertEqual(cap["required_frames"], 3)
        self.assertEqual(cap["max_frames"], 3)
        self.assertTrue(cap["session_url"].endswith("/mcp/face-enrollment/session"))

    def test_allowlist_stubs_always_allow(self):
        self.assertTrue(
            is_device_allowed_for_v2(
                _cfg(
                    face_enrollment_guided_burst_v2_enabled=False,
                    face_enrollment_guided_burst_v2_allowed_device_ids=[],
                ),
                "aa:bb:cc:dd:ee:ff",
            )
        )
        self.assertFalse(is_device_allowed_for_v2(_cfg(), ""))

    async def test_any_device_gets_v2_capability(self):
        device = "aa:bb:cc:dd:ee:ff"
        cfg = _cfg()
        conn = MagicMock()
        conn.config = cfg
        conn.session_id = "sess-1"
        conn.device_id = device
        conn.headers = {"device-id": device}

        with patch(
            "core.utils.face_enrollment_capability.resolve_face_account_id",
            return_value="",
        ):
            r = await build_face_enrollment_capability_for_conn(conn)
        self.assertTrue(r.ok)
        cap = r.capability
        self.assertEqual(cap["protocol_version"], 2)
        self.assertTrue(cap["guided_burst_v1"] is True)
        self.assertEqual(cap["session_timeout_seconds"], 240)
        self.assertEqual(
            cap["session_url"],
            "https://public.example.com/mcp/face-enrollment/session",
        )

    def test_bad_url_fail_closed_no_v1(self):
        r = build_face_enrollment_capability(
            _cfg(public_base_url="http://public.example.com")
        )
        self.assertFalse(r.ok)
        self.assertIsNone(r.capability)

    async def test_capability_guidance_profiles_when_allowed(self):
        from core.utils.face_enrollment_capability import IdentitySnapshotResult

        device = "aa:bb:cc:dd:ee:ff"
        cfg = _cfg()
        cfg["server"]["face_enrollment_front_only_enabled"] = True
        cfg["server"]["face_enrollment_front_only_allowlist"] = [
            {"account_id": "acct_a", "device_id": device}
        ]
        cfg["server"]["face_enrollment_user_relative_enabled"] = True
        cfg["server"]["face_enrollment_user_relative_allowlist"] = [
            {"account_id": "acct_a", "device_id": device}
        ]
        conn = MagicMock()
        conn.config = cfg
        conn.session_id = "sess-1"
        conn.device_id = device
        conn.headers = {"device-id": device}

        with patch(
            "core.utils.face_enrollment_capability.resolve_face_account_id",
            return_value="acct_a",
        ), patch(
            "core.utils.face_enrollment_capability.fetch_identity_capability_snapshot",
            new=AsyncMock(return_value=IdentitySnapshotResult(ok=False, reason="test")),
        ), patch(
            "core.utils.face_enrollment_capability.is_outbound_allowed",
            return_value=True,
        ):
            r = await build_face_enrollment_capability_for_conn(conn)
        self.assertTrue(r.ok)
        self.assertIn("supported_capture_modes", r.capability)
        self.assertIn("supported_guidance_profiles", r.capability)
        self.assertEqual(
            r.capability["supported_guidance_profiles"], ["user_relative_v1"]
        )

    async def test_capability_no_guidance_profiles_when_not_allowed(self):
        from core.utils.face_enrollment_capability import IdentitySnapshotResult

        device = "aa:bb:cc:dd:ee:ff"
        cfg = _cfg()
        # user_relative 未开启 → 不下发 supported_guidance_profiles
        conn = MagicMock()
        conn.config = cfg
        conn.session_id = "sess-1"
        conn.device_id = device
        conn.headers = {"device-id": device}

        with patch(
            "core.utils.face_enrollment_capability.resolve_face_account_id",
            return_value="acct_a",
        ), patch(
            "core.utils.face_enrollment_capability.fetch_identity_capability_snapshot",
            new=AsyncMock(return_value=IdentitySnapshotResult(ok=False, reason="test")),
        ), patch(
            "core.utils.face_enrollment_capability.is_outbound_allowed",
            return_value=True,
        ):
            r = await build_face_enrollment_capability_for_conn(conn)
        self.assertTrue(r.ok)
        self.assertNotIn("supported_guidance_profiles", r.capability)


class V2UrlGuardTests(unittest.TestCase):
    def test_http_fail_closed(self):
        url, reason = resolve_v2_session_url(
            _cfg(public_base_url="http://public.example.com")
        )
        self.assertIsNone(url)
        self.assertEqual(reason, "not_https")

    def test_localhost_fail_closed(self):
        url, reason = resolve_v2_session_url(
            _cfg(
                public_base_url="https://localhost",
                websocket="wss://localhost/xiaozhi/v1/",
            )
        )
        self.assertIsNone(url)

    def test_127_fail_closed(self):
        url, reason = resolve_v2_session_url(
            _cfg(
                public_base_url="https://127.0.0.1",
                websocket="wss://127.0.0.1/xiaozhi/v1/",
            )
        )
        self.assertIsNone(url)

    def test_private_host_fail_closed(self):
        url, reason = resolve_v2_session_url(
            _cfg(
                public_base_url="https://192.168.1.2",
                websocket="wss://192.168.1.2/xiaozhi/v1/",
            )
        )
        self.assertIsNone(url)

    def test_host_mismatch_fail_closed(self):
        url, reason = resolve_v2_session_url(
            _cfg(
                public_base_url="https://a.example.com",
                websocket="wss://b.example.com/xiaozhi/v1/",
            )
        )
        self.assertIsNone(url)
        self.assertEqual(reason, "host_mismatch")

    def test_wss_missing_fail_closed(self):
        url, reason = resolve_v2_session_url(_cfg(websocket=""))
        self.assertIsNone(url)
        self.assertIn("wss", reason)

    def test_wss_http_scheme_fail_closed(self):
        url, reason = resolve_v2_session_url(
            _cfg(websocket="ws://public.example.com/xiaozhi/v1/")
        )
        self.assertIsNone(url)


class V2GuidanceContractTests(unittest.TestCase):
    def test_unknown_guidance_rejected(self):
        self.assertIsNone(sanitize_guidance_code("HACK"))
        self.assertIn("ALIGN_READY", GUIDANCE_CODES)
        payload, err = build_v2_guidance_payload(
            session_id="s",
            guidance_code="NOT_A_REAL_CODE",
            accepted_count=0,
        )
        self.assertIsNone(payload)
        self.assertEqual(err, "internal_error")

    def test_legitimate_service_error_allowed(self):
        payload, err = build_v2_guidance_payload(
            session_id="s",
            guidance_code="SERVICE_ERROR",
            accepted_count=0,
        )
        self.assertIsNone(err)
        self.assertEqual(payload["guidance_code"], "SERVICE_ERROR")
        self.assertFalse(payload["draft_ready"])

    def test_accepted_count_range(self):
        for bad in (-1, 4, "x", True):
            payload, err = build_v2_guidance_payload(
                session_id="s",
                guidance_code="ALIGN_READY",
                accepted_count=bad,
            )
            self.assertIsNone(payload)
            self.assertEqual(err, "internal_error")
        for good in (0, 1, 2, 3):
            payload, err = build_v2_guidance_payload(
                session_id="s",
                guidance_code="ALIGN_READY" if good < 3 else "DRAFT_READY",
                accepted_count=good,
                draft_ready=(good == 3),
            )
            self.assertIsNone(err)
            self.assertEqual(payload["accepted_count"], good)

    def test_draft_ready_strict(self):
        payload, err = build_v2_guidance_payload(
            session_id="s",
            guidance_code="ALIGN_READY",
            accepted_count=3,
            draft_ready=True,
        )
        self.assertIsNone(payload)
        self.assertEqual(err, "internal_error")
        ok = v2_guidance_ok(
            session_id="s",
            guidance_code="DRAFT_READY",
            accepted_count=3,
            draft_ready=True,
        )
        self.assertEqual(ok["guidance_code"], "DRAFT_READY")
        self.assertTrue(ok["draft_ready"])

    def test_front_only_draft_ready_count_one(self):
        payload, err = build_v2_guidance_payload(
            session_id="s",
            guidance_code="DRAFT_READY",
            accepted_count=1,
            draft_ready=True,
            capture_mode="front_only_v1",
            required_frames=1,
        )
        self.assertIsNone(err)
        self.assertEqual(payload["accepted_count"], 1)
        self.assertTrue(payload["draft_ready"])
        bad, err2 = build_v2_guidance_payload(
            session_id="s",
            guidance_code="DRAFT_READY",
            accepted_count=1,
            draft_ready=True,
        )
        self.assertIsNone(bad)
        self.assertEqual(err2, "internal_error")

    def test_front_only_rejects_wrong_required_frames(self):
        from core.utils.face_enrollment_v2 import resolve_session_frame_limits

        mode, req, err = resolve_session_frame_limits(
            capture_mode="front_only_v1", required_frames=3
        )
        self.assertIsNone(mode)
        self.assertEqual(err, "required_frames_mismatch")
        mode2, req2, err2 = resolve_session_frame_limits(
            capture_mode="front_only_v1", required_frames="bad"
        )
        self.assertIsNone(mode2)
        self.assertEqual(err2, "required_frames_invalid")
        payload, gerr = build_v2_guidance_payload(
            session_id="s",
            guidance_code="DRAFT_READY",
            accepted_count=1,
            draft_ready=True,
            capture_mode="front_only_v1",
            required_frames=3,
        )
        self.assertIsNone(payload)
        self.assertEqual(gerr, "internal_error")
        payload2, gerr2 = build_v2_guidance_payload(
            session_id="s",
            guidance_code="ALIGN_READY",
            accepted_count=0,
            capture_mode="front_only_v1",
            required_frames="bad",
        )
        self.assertIsNone(payload2)
        self.assertEqual(gerr2, "internal_error")

    def test_unknown_mode_and_bool_count_rejected(self):
        payload, err = build_v2_guidance_payload(
            session_id="s",
            guidance_code="ALIGN_READY",
            accepted_count=0,
            capture_mode="front_only_v0",
        )
        self.assertIsNone(payload)
        self.assertEqual(err, "internal_error")
        payload2, err2 = build_v2_guidance_payload(
            session_id="s",
            guidance_code="ALIGN_READY",
            accepted_count=True,
            capture_mode="front_only_v1",
            required_frames=1,
        )
        self.assertIsNone(payload2)
        self.assertEqual(err2, "internal_error")

    def test_old_mode_not_inferred_from_count_one(self):
        payload, err = build_v2_guidance_payload(
            session_id="s",
            guidance_code="DRAFT_READY",
            accepted_count=1,
            draft_ready=True,
            capture_mode=None,
        )
        self.assertIsNone(payload)
        self.assertEqual(err, "internal_error")

    def test_v2_error_no_message(self):
        body = v2_error_body("auth_invalid")
        self.assertEqual(set(body.keys()), {"ok", "error_code", "retryable"})
        self.assertNotIn("message", body)


class V2GatewayTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        reset_limiters_for_tests()
        reset_metrics_for_tests()
        reset_session_policies_for_tests()
        self.device_id = "aa:bb:cc:dd:ee:ff"
        self.client_id = "client-1"
        self.config = _cfg()
        self.auth = AuthManager(
            secret_key="device-pairing-secret-not-enroll", expire_seconds=86400
        )
        self.token = self.auth.generate_token(self.client_id, self.device_id)

    def _headers(self, **extra):
        h = {
            "Authorization": f"Bearer {self.token}",
            "Device-Id": self.device_id,
            "Client-Id": self.client_id,
        }
        h.update(extra)
        return h

    async def _client(self, handler, middlewares=None):
        app = web.Application(middlewares=list(middlewares or ()))
        app.router.add_post(
            "/mcp/face-enrollment/session", handler.handle_v2_create_session
        )
        app.router.add_post(
            "/mcp/face-enrollment/assess/{session_id}", handler.handle_v2_assess
        )
        app.router.add_post(
            "/mcp/face-enrollment/capture/{session_id}", handler.handle_v2_capture
        )
        app.router.add_delete(
            "/mcp/face-enrollment/cancel/{session_id}", handler.handle_v2_cancel
        )
        server = TestServer(app)
        client = TestClient(server)
        await client.start_server()
        return client

    async def _close_client(self, client):
        """关闭 TestClient；尽量释放 transport，不重构生产网络代码。"""
        try:
            await client.close()
        finally:
            await asyncio.sleep(0)

    async def _chunked_post(self, client, path, raw: bytes, headers: dict):
        async def gen():
            if not raw:
                return
            step = max(1, len(raw) // 4)
            for i in range(0, len(raw), step):
                yield raw[i : i + step]

        h = dict(headers)
        h.pop("Content-Length", None)
        h["Content-Type"] = "application/json"
        return await client.post(path, data=gen(), headers=h)

    def _cl_probe_middleware(self, probe: dict):
        @web.middleware
        async def _probe(request, handler):
            probe["content_length"] = request.headers.get("Content-Length")
            probe["transfer_encoding"] = (
                request.headers.get("Transfer-Encoding") or ""
            ).lower()
            return await handler(request)

        return _probe

    async def _post_multi_part_chunked(self, client, path, parts, headers):
        """真正分多批 chunked 发送；批次间用事件同步（非单靠 sleep）。

        返回 (task, gates, first_sent)。第一批发出后 first_sent 置位，
        后续批次由 gates[i] 逐个放行。调用方在放行前可断言上游未创建。
        """
        gates = [asyncio.Event() for _ in range(len(parts) - 1)]
        first_sent = asyncio.Event()

        async def gen():
            for i, part in enumerate(parts):
                if part:
                    yield part
                if i == 0:
                    first_sent.set()
                if i < len(parts) - 1:
                    await gates[i].wait()

        h = dict(headers)
        h.pop("Content-Length", None)
        h["Content-Type"] = "application/json"
        task = asyncio.ensure_future(client.post(path, data=gen(), headers=h))
        await first_sent.wait()
        return task, gates, first_sent

    async def test_v1_gateway_routes_not_registered(self):
        """V1 /sessions /frames 路由不得注册。"""
        handler = FaceEnrollmentHandler(self.config)
        client = await self._client(handler)
        try:
            resp = await client.post(
                "/mcp/face-enrollment/sessions", headers=self._headers()
            )
            self.assertEqual(resp.status, 404)
            resp2 = await client.post(
                "/mcp/face-enrollment/sessions/siddeadbeef0001/frames",
                headers=self._headers(),
            )
            self.assertEqual(resp2.status, 404)
            resp3 = await client.delete(
                "/mcp/face-enrollment/sessions/siddeadbeef0001",
                headers=self._headers(),
            )
            self.assertEqual(resp3.status, 404)
            self.assertFalse(hasattr(handler, "allowed_devices"))
            self.assertFalse(hasattr(handler, "handle_create_session"))
        finally:
            await self._close_client(client)

    async def test_create_success_and_token_header_only(self):
        handler = FaceEnrollmentHandler(self.config)
        upstream = _v2_upstream("siddeadbeef0001")
        seen = {"timeout": None}

        async def fake_face_json(method, path, *a, json_body=None, **k):
            if method == "POST" and path.endswith("/sessions"):
                seen["timeout"] = (json_body or {}).get("timeout_seconds")
            return 200, upstream

        handler._face_json = fake_face_json  # type: ignore
        client = await self._client(handler)
        try:
            resp = await client.post(
                "/mcp/face-enrollment/session", headers=self._headers()
            )
            self.assertEqual(resp.status, 200)
            body = await resp.json()
            self.assertTrue(body["ok"])
            self.assertEqual(body["session_id"], "siddeadbeef0001")
            self.assertIn("upload_token", body)
            self.assertIn("/mcp/face-enrollment/assess/", body["assess_url"])
            self.assertIn("/mcp/face-enrollment/capture/", body["capture_url"])
            self.assertIn("/mcp/face-enrollment/cancel/", body["cancel_url"])
            self.assertEqual(body["required_frames"], 3)
            # 内部余量发给 face-api；不暴露在 capability
            self.assertEqual(
                seen["timeout"],
                V2_SESSION_TIMEOUT_SECONDS + V2_CREATE_TIMEOUT_SLACK_SECONDS,
            )
            self.assertEqual(seen["timeout"], 245)
            token = body["upload_token"]
            # token 至少覆盖 240s 窗口（expires_at 远未来 → ttl >= 240）
            self.assertGreaterEqual(
                int(body["expires_at"]) - int(time.time()),
                V2_SESSION_TIMEOUT_SECONDS,
            )

            # 缺 token 拒绝
            resp2 = await client.delete(
                f"/mcp/face-enrollment/cancel/{body['session_id']}",
                headers=self._headers(),
            )
            self.assertEqual(resp2.status, 403)
            b2 = await resp2.json()
            self.assertEqual(b2["error_code"], "upload_token_invalid")
            self.assertNotIn("message", b2)

            # query token 不得生效
            resp3 = await client.delete(
                f"/mcp/face-enrollment/cancel/{body['session_id']}?upload_token={token}",
                headers=self._headers(),
            )
            self.assertEqual(resp3.status, 403)

            # header token + 上游 cancel
            async def fake_cancel(*a, **k):
                return 200, {"status": "ok"}

            handler._face_json = fake_cancel  # type: ignore
            resp4 = await client.delete(
                f"/mcp/face-enrollment/cancel/{body['session_id']}",
                headers=self._headers(**{"X-Enrollment-Token": token}),
            )
            self.assertEqual(resp4.status, 200)
            b4 = await resp4.json()
            self.assertEqual(b4["guidance_code"], "CANCELLED")
            self.assertNotIn("accepted_count", b4)
            self.assertNotIn("draft_ready", b4)
            self.assertEqual(set(b4.keys()), {"ok", "session_id", "guidance_code"})
        finally:
            await self._close_client(client)

    async def test_v2_create_expires_at_min_240(self):
        """expires_at 剩余 <240 拒绝；>=240 通过；create 请求带内部余量。"""
        handler = FaceEnrollmentHandler(self.config)
        client = await self._client(handler)
        fixed_now = 1_700_000_000
        try:
            seen = {"timeout": None}

            # 239 秒剩余 → 拒绝、不签发
            reset_limiters_for_tests()
            short = _v2_upstream(
                "siddeadbeef0239",
                expires_at=fixed_now + 239,
            )

            async def fake_short(method, path, *a, json_body=None, **k):
                if method == "DELETE":
                    return 200, {"status": "ok"}
                if method == "POST":
                    seen["timeout"] = (json_body or {}).get("timeout_seconds")
                return 200, short

            handler._face_json = fake_short  # type: ignore
            with patch(
                "core.api.face_enrollment_handler.time.time", return_value=fixed_now
            ):
                resp = await client.post(
                    "/mcp/face-enrollment/session", headers=self._headers()
                )
                body = await resp.json()
            self.assertFalse(body["ok"])
            self.assertEqual(body["error_code"], "internal_error")
            self.assertNotIn("upload_token", body)
            self.assertEqual(
                seen["timeout"],
                V2_SESSION_TIMEOUT_SECONDS + V2_CREATE_TIMEOUT_SLACK_SECONDS,
            )

            # 恰好 240 秒 → 通过
            reset_limiters_for_tests()
            ok_up = _v2_upstream(
                "siddeadbeef0240",
                expires_at=fixed_now + V2_SESSION_TIMEOUT_SECONDS,
            )

            async def fake_ok(*a, **k):
                return 200, ok_up

            handler._face_json = fake_ok  # type: ignore
            with patch(
                "core.api.face_enrollment_handler.time.time", return_value=fixed_now
            ):
                resp2 = await client.post(
                    "/mcp/face-enrollment/session", headers=self._headers()
                )
                body2 = await resp2.json()
            self.assertTrue(body2["ok"])
            self.assertIn("upload_token", body2)
            self.assertGreaterEqual(
                int(body2["expires_at"]) - fixed_now,
                V2_SESSION_TIMEOUT_SECONDS,
            )
        finally:
            await self._close_client(client)

    async def test_v2_cancel_no_count_regression(self):
        """修复1：V2 cancel 不含 accepted_count，避免倒退。"""
        handler = FaceEnrollmentHandler(self.config)
        token, _ = handler.issue_upload_token(
            session_id="sid-front-01",
            device_id=self.device_id,
            account_id="acct_a",
            ttl=240,
            scope=UPLOAD_TOKEN_SCOPE_V2,
        )

        async def fake_cancel(method, path, **kwargs):
            self.assertIn("/guided-burst", path)
            return 200, {"status": "ok", "session_id": "sid-front-01"}

        handler._face_json = fake_cancel  # type: ignore
        client = await self._client(handler)
        try:
            resp = await client.delete(
                "/mcp/face-enrollment/cancel/sid-front-01",
                headers=self._headers(**{"X-Enrollment-Token": token}),
            )
            self.assertEqual(resp.status, 200)
            body = await resp.json()
            self.assertTrue(body["ok"])
            self.assertEqual(body["guidance_code"], "CANCELLED")
            self.assertNotIn("accepted_count", body)
            self.assertNotIn("draft_ready", body)
        finally:
            await self._close_client(client)


    async def test_token_wrong_session_rejected(self):
        handler = FaceEnrollmentHandler(self.config)
        token, _ = handler.issue_upload_token(
            session_id="sess-a",
            device_id=self.device_id,
            account_id="acct_a",
            ttl=240,
            scope=UPLOAD_TOKEN_SCOPE_V2,
        )
        client = await self._client(handler)
        try:
            resp = await client.post(
                "/mcp/face-enrollment/assess/sess-b",
                headers=self._headers(**{"X-Enrollment-Token": token}),
                data=b"not-multipart",
            )
            self.assertIn(resp.status, (403, 422))
            body = await resp.json()
            self.assertFalse(body["ok"])
            self.assertNotIn("message", body)
        finally:
            await self._close_client(client)

    async def test_v1_scope_token_rejected_on_v2(self):
        """旧 enrollment_upload scope 不得用于 V2 端点。"""
        handler = FaceEnrollmentHandler(self.config)
        token, _ = handler.issue_upload_token(
            session_id="sess-a",
            device_id=self.device_id,
            account_id="acct_a",
            ttl=240,
            scope="enrollment_upload",
        )
        client = await self._client(handler)
        try:
            resp = await client.delete(
                "/mcp/face-enrollment/cancel/sess-a",
                headers=self._headers(**{"X-Enrollment-Token": token}),
            )
            self.assertEqual(resp.status, 403)
            body = await resp.json()
            self.assertEqual(body["error_code"], "upload_token_invalid")
        finally:
            await self._close_client(client)

    async def test_v2_requires_pairing_auth_even_if_allowed_devices(self):
        """enrollment 从不使用 allowed_devices 旁路 pairing Authorization。"""
        cfg = _cfg()
        cfg["server"]["auth"]["allowed_devices"] = [self.device_id]
        handler = FaceEnrollmentHandler(cfg)
        self.assertFalse(hasattr(handler, "allowed_devices"))
        client = await self._client(handler)
        try:
            # 无 Authorization
            resp = await client.post(
                "/mcp/face-enrollment/session",
                headers={
                    "Device-Id": self.device_id,
                    "Client-Id": self.client_id,
                },
            )
            self.assertEqual(resp.status, 401)
            body = await resp.json()
            self.assertEqual(body["error_code"], "auth_invalid")
            self.assertNotIn("message", body)

            # 无效 Authorization
            resp2 = await client.post(
                "/mcp/face-enrollment/session",
                headers={
                    "Authorization": "Bearer totally-invalid",
                    "Device-Id": self.device_id,
                    "Client-Id": self.client_id,
                },
            )
            self.assertEqual(resp2.status, 401)
            self.assertEqual((await resp2.json())["error_code"], "auth_invalid")
        finally:
            await self._close_client(client)

    async def test_enrollment_never_uses_allowed_devices_bypass(self):
        """即使配置 allowed_devices，无 Bearer 也必须 auth_invalid。"""
        cfg = _cfg()
        cfg["server"]["auth"]["allowed_devices"] = [self.device_id]
        handler = FaceEnrollmentHandler(cfg)
        self.assertFalse(hasattr(handler, "allowed_devices"))
        client = await self._client(handler)
        try:
            resp = await client.post(
                "/mcp/face-enrollment/session",
                headers={
                    "Device-Id": self.device_id,
                    "Client-Id": self.client_id,
                },
            )
            self.assertEqual(resp.status, 401)
            body = await resp.json()
            self.assertEqual(body["error_code"], "auth_invalid")
        finally:
            await self._close_client(client)

    async def test_cancel_after_flag_disabled(self):
        """遗留 flag 关闭后既有 session 仍可 cancel。"""
        handler = FaceEnrollmentHandler(self.config)
        upstream = _v2_upstream("siddeadbeef0002")

        async def fake_create(*a, **k):
            return 200, upstream

        handler._face_json = fake_create  # type: ignore
        client = await self._client(handler)
        try:
            resp = await client.post(
                "/mcp/face-enrollment/session", headers=self._headers()
            )
            self.assertEqual(resp.status, 200)
            body = await resp.json()
            token = body["upload_token"]
            sid = body["session_id"]

            # 关闭 flag / 清空 allowlist
            handler.config["server"]["face_enrollment_guided_burst_v2_enabled"] = False
            handler.config["server"][
                "face_enrollment_guided_burst_v2_allowed_device_ids"
            ] = []

            called = {"n": 0}

            async def fake_cancel(method, path, **kwargs):
                called["n"] += 1
                self.assertEqual(method, "DELETE")
                self.assertIn("/guided-burst", path)
                return 200, {"status": "ok"}

            handler._face_json = fake_cancel  # type: ignore
            resp2 = await client.delete(
                f"/mcp/face-enrollment/cancel/{sid}",
                headers=self._headers(**{"X-Enrollment-Token": token}),
            )
            self.assertEqual(resp2.status, 200)
            b2 = await resp2.json()
            self.assertNotEqual(b2.get("error_code"), "v2_not_allowed")
            self.assertEqual(b2.get("guidance_code"), "CANCELLED")
            self.assertNotIn("accepted_count", b2)
            self.assertEqual(called["n"], 1)
        finally:
            await self._close_client(client)

    async def test_v2_cancel_late_request_rejected(self):
        """修复2：第二次 V2 cancel 必须非成功。"""
        handler = FaceEnrollmentHandler(self.config)
        upstream = _v2_upstream("siddeadbeef0003")
        calls = {"n": 0}

        async def fake_face(method, path, **kwargs):
            if method == "POST" and path.endswith("/sessions"):
                return 200, upstream
            if method == "DELETE" and path.endswith("/guided-burst"):
                calls["n"] += 1
                if calls["n"] == 1:
                    return 200, {"status": "ok", "session_id": upstream["session_id"]}
                return 404, {"detail": {"code": "not_found", "message": "x"}}
            if method == "POST" and "/assess" in path:
                return 404, {"detail": {"code": "not_found", "message": "x"}}
            return 500, {"detail": {"code": "internal_error"}}

        handler._face_json = fake_face  # type: ignore
        client = await self._client(handler)
        try:
            created = await client.post(
                "/mcp/face-enrollment/session", headers=self._headers()
            )
            body = await created.json()
            token = body["upload_token"]
            sid = body["session_id"]

            r1 = await client.delete(
                f"/mcp/face-enrollment/cancel/{sid}",
                headers=self._headers(**{"X-Enrollment-Token": token}),
            )
            self.assertEqual(r1.status, 200)
            self.assertTrue((await r1.json())["ok"])

            r2 = await client.delete(
                f"/mcp/face-enrollment/cancel/{sid}",
                headers=self._headers(**{"X-Enrollment-Token": token}),
            )
            self.assertNotEqual(r2.status, 200)
            b2 = await r2.json()
            self.assertFalse(b2["ok"])
            self.assertEqual(b2["error_code"], "session_not_found")
            self.assertNotIn("message", b2)

            form = FormData()
            form.add_field(
                "image",
                b"\xff\xd8\xff" + b"0" * 64,
                filename="a.jpg",
                content_type="image/jpeg",
            )
            r3 = await client.post(
                f"/mcp/face-enrollment/assess/{sid}",
                data=form,
                headers=self._headers(**{"X-Enrollment-Token": token}),
            )
            self.assertNotEqual(r3.status, 200)
            self.assertFalse((await r3.json())["ok"])
        finally:
            await self._close_client(client)

    async def test_upstream_bad_count_and_unknown_guidance(self):
        """修复3/4：超范围 count / 未知 guidance → 非成功错误体。"""
        handler = FaceEnrollmentHandler(self.config)
        token, _ = handler.issue_upload_token(
            session_id="sess-x",
            device_id=self.device_id,
            account_id="acct_a",
            ttl=240,
            scope=UPLOAD_TOKEN_SCOPE_V2,
        )
        client = await self._client(handler)
        try:
            async def fake_bad_count(*a, **k):
                return 200, {
                    "ok": True,
                    "session_id": "sess-x",
                    "guidance_code": "ALIGN_READY",
                    "accepted_count": 4,
                    "draft_ready": False,
                }

            handler._face_json = fake_bad_count  # type: ignore
            form = FormData()
            form.add_field(
                "image",
                b"\xff\xd8\xff" + b"0" * 64,
                filename="a.jpg",
                content_type="image/jpeg",
            )
            resp = await client.post(
                "/mcp/face-enrollment/assess/sess-x",
                data=form,
                headers=self._headers(**{"X-Enrollment-Token": token}),
            )
            body = await resp.json()
            self.assertFalse(body["ok"])
            self.assertEqual(body["error_code"], "internal_error")
            self.assertNotIn("guidance_code", body)
            self.assertNotIn("message", body)

            async def fake_unknown(*a, **k):
                return 200, {
                    "ok": True,
                    "session_id": "sess-x",
                    "guidance_code": "NOT_A_REAL_CODE",
                    "accepted_count": 0,
                    "draft_ready": False,
                }

            handler._face_json = fake_unknown  # type: ignore
            form2 = FormData()
            form2.add_field(
                "image",
                b"\xff\xd8\xff" + b"0" * 64,
                filename="a.jpg",
                content_type="image/jpeg",
            )
            resp2 = await client.post(
                "/mcp/face-enrollment/assess/sess-x",
                data=form2,
                headers=self._headers(**{"X-Enrollment-Token": token}),
            )
            b2 = await resp2.json()
            self.assertFalse(b2["ok"])
            self.assertEqual(b2["error_code"], "internal_error")
            blob = json.dumps(b2)
            self.assertNotIn("NOT_A_REAL_CODE", blob)

            async def fake_svc_err(*a, **k):
                return 200, {
                    "ok": True,
                    "session_id": "sess-x",
                    "guidance_code": "SERVICE_ERROR",
                    "accepted_count": 0,
                    "draft_ready": False,
                }

            handler._face_json = fake_svc_err  # type: ignore
            form3 = FormData()
            form3.add_field(
                "image",
                b"\xff\xd8\xff" + b"0" * 64,
                filename="a.jpg",
                content_type="image/jpeg",
            )
            resp3 = await client.post(
                "/mcp/face-enrollment/assess/sess-x",
                data=form3,
                headers=self._headers(**{"X-Enrollment-Token": token}),
            )
            b3 = await resp3.json()
            self.assertTrue(b3["ok"])
            self.assertEqual(b3["guidance_code"], "SERVICE_ERROR")
        finally:
            await self._close_client(client)

    async def test_multipart_rejects_duplicates_and_extra(self):
        """修复7：重复/额外 candidate 拒绝。"""
        handler = FaceEnrollmentHandler(self.config)
        token, _ = handler.issue_upload_token(
            session_id="sess-m",
            device_id=self.device_id,
            account_id="acct_a",
            ttl=240,
            scope=UPLOAD_TOKEN_SCOPE_V2,
        )
        client = await self._client(handler)
        jpeg = b"\xff\xd8\xff" + b"0" * 64
        try:
            form = FormData()
            form.add_field("pose", "front")
            form.add_field("round", "1")
            form.add_field("candidate_0", jpeg, filename="a.jpg", content_type="image/jpeg")
            form.add_field("candidate_0", jpeg, filename="b.jpg", content_type="image/jpeg")
            form.add_field("candidate_1", jpeg, filename="c.jpg", content_type="image/jpeg")
            form.add_field("candidate_2", jpeg, filename="d.jpg", content_type="image/jpeg")
            resp = await client.post(
                "/mcp/face-enrollment/capture/sess-m",
                data=form,
                headers=self._headers(**{"X-Enrollment-Token": token}),
            )
            body = await resp.json()
            self.assertFalse(body["ok"])
            self.assertEqual(body["error_code"], "invalid_content_type")

            form2 = FormData()
            form2.add_field("pose", "front")
            form2.add_field("round", "1")
            for i in range(4):
                form2.add_field(
                    f"candidate_{i}",
                    jpeg,
                    filename=f"c{i}.jpg",
                    content_type="image/jpeg",
                )
            resp2 = await client.post(
                "/mcp/face-enrollment/capture/sess-m",
                data=form2,
                headers=self._headers(**{"X-Enrollment-Token": token}),
            )
            self.assertFalse((await resp2.json())["ok"])

            form3 = FormData()
            form3.add_field(
                "image", jpeg, filename="a.jpg", content_type="image/jpeg"
            )
            form3.add_field(
                "image", jpeg, filename="b.jpg", content_type="image/jpeg"
            )
            resp3 = await client.post(
                "/mcp/face-enrollment/assess/sess-m",
                data=form3,
                headers=self._headers(**{"X-Enrollment-Token": token}),
            )
            self.assertFalse((await resp3.json())["ok"])

            # 额外文本字段也必须拒绝
            form4 = FormData()
            form4.add_field(
                "image", jpeg, filename="a.jpg", content_type="image/jpeg"
            )
            form4.add_field("debug", "1")
            resp4 = await client.post(
                "/mcp/face-enrollment/assess/sess-m",
                data=form4,
                headers=self._headers(**{"X-Enrollment-Token": token}),
            )
            self.assertEqual((await resp4.json())["error_code"], "invalid_content_type")

            form5 = FormData()
            form5.add_field(
                "image", jpeg, filename="a.jpg", content_type="image/jpeg"
            )
            form5.add_field("pose", "front")
            resp5 = await client.post(
                "/mcp/face-enrollment/assess/sess-m",
                data=form5,
                headers=self._headers(**{"X-Enrollment-Token": token}),
            )
            self.assertFalse((await resp5.json())["ok"])
        finally:
            await self._close_client(client)

    async def test_create_rejects_incomplete_upstream(self):
        """V2 create：上游契约不完整/不精确时不签发 token，并 best-effort cleanup。"""
        handler = FaceEnrollmentHandler(self.config)
        client = await self._client(handler)
        base = _v2_upstream("siddeadbeef00aa")
        cases = [
            # 缺字段
            {k: v for k, v in base.items() if k != "protocol_version"},
            {k: v for k, v in base.items() if k != "guided_burst_v1"},
            {k: v for k, v in base.items() if k != "required_frames"},
            {k: v for k, v in base.items() if k != "max_frames"},
            {k: v for k, v in base.items() if k != "expires_at"},
            # 非法 session
            _v2_upstream(""),
            {k: v for k, v in base.items() if k != "session_id"},
            # 类型/取值错误
            _v2_upstream("siddeadbeef00ab", protocol_version=1),
            _v2_upstream("siddeadbeef00ac", protocol_version="2"),
            _v2_upstream("siddeadbeef00ad", guided_burst_v1="true"),
            _v2_upstream("siddeadbeef00ae", guided_burst_v1=1),
            _v2_upstream("siddeadbeef00af", guided_burst_v1=False),
            _v2_upstream("siddeadbeef00b0", required_frames=5, max_frames=5),
            _v2_upstream("siddeadbeef00b1", required_frames="3"),
            _v2_upstream("siddeadbeef00b2", max_frames=True),  # bool 伪 int
            _v2_upstream("siddeadbeef00b3", expires_at=int(time.time()) - 10),
        ]
        try:
            for upstream in cases:
                reset_limiters_for_tests()
                cleanup = {"n": 0, "path": None}

                async def fake(method, path, *a, _u=upstream, _c=cleanup, **k):
                    if method == "DELETE":
                        _c["n"] += 1
                        _c["path"] = path
                        return 200, {"status": "ok"}
                    return 200, _u

                handler._face_json = fake  # type: ignore
                resp = await client.post(
                    "/mcp/face-enrollment/session", headers=self._headers()
                )
                body = await resp.json()
                self.assertFalse(body["ok"], upstream)
                self.assertEqual(body["error_code"], "internal_error")
                self.assertNotIn("upload_token", body)
                self.assertNotIn("assess_url", body)
                self.assertNotIn("capture_url", body)
                self.assertNotIn("cancel_url", body)
                self.assertNotIn("message", body)
                # 安全 session_id 存在时应发起 V2 专用 cleanup
                sid = upstream.get("session_id")
                if FaceEnrollmentHandler._is_safe_v2_session_id(sid):
                    self.assertEqual(cleanup["n"], 1, upstream)
                    self.assertIn("/guided-burst", cleanup["path"] or "")
                    self.assertIn(str(sid), cleanup["path"] or "")
                else:
                    self.assertEqual(cleanup["n"], 0, upstream)

            # cleanup 失败不得掩盖 create 失败、不得泄露详情
            reset_limiters_for_tests()
            bad = _v2_upstream("siddeadbeef00c0", protocol_version=1)

            async def fake_cleanup_fail(method, path, **kwargs):
                if method == "DELETE":
                    raise RuntimeError("upstream down")
                return 200, bad

            handler._face_json = fake_cleanup_fail  # type: ignore
            resp_fail = await client.post(
                "/mcp/face-enrollment/session", headers=self._headers()
            )
            body_fail = await resp_fail.json()
            self.assertFalse(body_fail["ok"])
            self.assertEqual(body_fail["error_code"], "internal_error")
            self.assertNotIn("upload_token", body_fail)
            self.assertNotIn("message", body_fail)
            dumped = json.dumps(body_fail)
            self.assertNotIn("upstream down", dumped)
            self.assertNotIn("protocol_version", dumped)

            # 不安全 session_id：不拼接 cleanup URL
            reset_limiters_for_tests()
            unsafe = _v2_upstream("../evilpath", protocol_version=1)
            cleanup2 = {"n": 0}

            async def fake_unsafe(method, path, **kwargs):
                if method == "DELETE":
                    cleanup2["n"] += 1
                    return 200, {"status": "ok"}
                return 200, unsafe

            handler._face_json = fake_unsafe  # type: ignore
            resp_u = await client.post(
                "/mcp/face-enrollment/session", headers=self._headers()
            )
            self.assertFalse((await resp_u.json())["ok"])
            self.assertEqual(cleanup2["n"], 0)

            # 完整合法仍签发
            reset_limiters_for_tests()

            async def fake_ok(*a, **k):
                return 200, _v2_upstream("siddeadbeef0007")

            handler._face_json = fake_ok  # type: ignore
            ok = await client.post(
                "/mcp/face-enrollment/session", headers=self._headers()
            )
            bob = await ok.json()
            self.assertTrue(bob["ok"])
            self.assertIn("upload_token", bob)
            self.assertEqual(bob["required_frames"], 3)
            self.assertEqual(bob["max_frames"], 3)
            self.assertIn("assess_url", bob)
        finally:
            await self._close_client(client)

    async def test_front_only_create_rebuilds_frames_one(self):
        cfg = _cfg()
        cfg["server"]["face_enrollment_front_only_enabled"] = True
        cfg["server"]["face_enrollment_front_only_allowlist"] = [
            {"account_id": "acct_a", "device_id": "aa:bb:cc:dd:ee:ff"}
        ]
        handler = FaceEnrollmentHandler(cfg)
        seen = {"body": None}

        async def fake(method, path, *a, json_body=None, **k):
            seen["body"] = json_body
            return 200, _v2_upstream(
                "siddeadbeef00f1",
                capture_mode="front_only_v1",
                required_frames=1,
                max_frames=1,
            )

        handler._face_json = fake  # type: ignore
        client = await self._client(handler)
        try:
            resp = await client.post(
                "/mcp/face-enrollment/session",
                headers=self._headers(),
                json={"capture_mode": "front_only_v1", "required_frames": 0},
            )
            body = await resp.json()
            self.assertTrue(body["ok"])
            self.assertEqual(body["required_frames"], 1)
            self.assertEqual(body["max_frames"], 1)
            self.assertEqual(body["capture_mode"], "front_only_v1")
            self.assertNotIn("required_frames", seen["body"] or {})
            self.assertEqual(seen["body"]["capture_mode"], "front_only_v1")
        finally:
            await self._close_client(client)

    async def test_request_front_only_upstream_old_rejected(self):
        cfg = _cfg()
        cfg["server"]["face_enrollment_front_only_enabled"] = True
        cfg["server"]["face_enrollment_front_only_allowlist"] = [
            {"account_id": "acct_a", "device_id": "aa:bb:cc:dd:ee:ff"}
        ]
        handler = FaceEnrollmentHandler(cfg)
        cleanup = {"n": 0}

        async def fake(method, path, *a, json_body=None, **k):
            if method == "DELETE":
                cleanup["n"] += 1
                return 200, {"status": "ok"}
            # 请求 front_only，上游却返回旧三姿态
            return 200, _v2_upstream("siddeadbeef00m1")

        handler._face_json = fake  # type: ignore
        client = await self._client(handler)
        try:
            resp = await client.post(
                "/mcp/face-enrollment/session",
                headers=self._headers(),
                json={"capture_mode": "front_only_v1"},
            )
            body = await resp.json()
            self.assertFalse(body["ok"])
            self.assertEqual(body["error_code"], "internal_error")
            self.assertNotIn("upload_token", body)
            self.assertEqual(cleanup["n"], 1)
        finally:
            await self._close_client(client)

    async def test_request_old_upstream_front_only_rejected(self):
        handler = FaceEnrollmentHandler(self.config)
        cleanup = {"n": 0}

        async def fake(method, path, *a, json_body=None, **k):
            if method == "DELETE":
                cleanup["n"] += 1
                return 200, {"status": "ok"}
            return 200, _v2_upstream(
                "siddeadbeef00m2",
                capture_mode="front_only_v1",
                required_frames=1,
                max_frames=1,
            )

        handler._face_json = fake  # type: ignore
        client = await self._client(handler)
        try:
            resp = await client.post(
                "/mcp/face-enrollment/session",
                headers=self._headers(),
                json={},
            )
            body = await resp.json()
            self.assertFalse(body["ok"])
            self.assertEqual(body["error_code"], "internal_error")
            self.assertEqual(cleanup["n"], 1)
        finally:
            await self._close_client(client)

    async def test_invalid_json_body_not_silent_old_mode(self):
        handler = FaceEnrollmentHandler(self.config)
        called = {"n": 0}

        async def fake(*a, **k):
            called["n"] += 1
            return 200, _v2_upstream("siddeadbeef00m3")

        handler._face_json = fake  # type: ignore
        client = await self._client(handler)
        try:
            resp = await client.post(
                "/mcp/face-enrollment/session",
                headers={**self._headers(), "Content-Type": "application/json"},
                data=b"{not-json",
            )
            body = await resp.json()
            self.assertFalse(body["ok"])
            self.assertEqual(body["error_code"], "invalid_capture_mode")
            self.assertEqual(called["n"], 0)
        finally:
            await self._close_client(client)

    async def test_empty_object_create_still_old_compatible(self):
        handler = FaceEnrollmentHandler(self.config)

        async def fake(method, path, *a, json_body=None, **k):
            self.assertNotIn("capture_mode", json_body or {})
            return 200, _v2_upstream("siddeadbeef00m4")

        handler._face_json = fake  # type: ignore
        client = await self._client(handler)
        try:
            resp = await client.post(
                "/mcp/face-enrollment/session",
                headers=self._headers(),
                json={},
            )
            body = await resp.json()
            self.assertTrue(body["ok"])
            self.assertEqual(body["required_frames"], 3)
            self.assertNotIn("capture_mode", body)
        finally:
            await self._close_client(client)

    async def test_front_only_not_allowlisted_rejected(self):
        handler = FaceEnrollmentHandler(self.config)
        client = await self._client(handler)
        try:
            resp = await client.post(
                "/mcp/face-enrollment/session",
                headers=self._headers(),
                json={"capture_mode": "front_only_v1"},
            )
            body = await resp.json()
            self.assertFalse(body["ok"])
            self.assertEqual(body["error_code"], "capture_mode_not_allowed")
        finally:
            await self._close_client(client)

    async def test_front_only_upstream_frames_three_rejected(self):
        cfg = _cfg()
        cfg["server"]["face_enrollment_front_only_enabled"] = True
        cfg["server"]["face_enrollment_front_only_allowlist"] = [
            {"account_id": "acct_a", "device_id": "aa:bb:cc:dd:ee:ff"}
        ]
        handler = FaceEnrollmentHandler(cfg)
        cleanup = {"n": 0}

        async def fake(method, path, *a, json_body=None, **k):
            if method == "DELETE":
                cleanup["n"] += 1
                return 200, {"status": "ok"}
            return 200, _v2_upstream(
                "siddeadbeef00m5",
                capture_mode="front_only_v1",
                required_frames=3,
                max_frames=3,
            )

        handler._face_json = fake  # type: ignore
        client = await self._client(handler)
        try:
            resp = await client.post(
                "/mcp/face-enrollment/session",
                headers=self._headers(),
                json={"capture_mode": "front_only_v1"},
            )
            body = await resp.json()
            self.assertFalse(body["ok"])
            self.assertEqual(body["error_code"], "internal_error")
            self.assertNotIn("upload_token", body)
            self.assertEqual(cleanup["n"], 1)
        finally:
            await self._close_client(client)

    async def test_front_only_upstream_frames_bad_rejected(self):
        cfg = _cfg()
        cfg["server"]["face_enrollment_front_only_enabled"] = True
        cfg["server"]["face_enrollment_front_only_allowlist"] = [
            {"account_id": "acct_a", "device_id": "aa:bb:cc:dd:ee:ff"}
        ]
        handler = FaceEnrollmentHandler(cfg)

        async def fake(method, path, *a, json_body=None, **k):
            if method == "DELETE":
                return 200, {"status": "ok"}
            return 200, _v2_upstream(
                "siddeadbeef00m6",
                capture_mode="front_only_v1",
                required_frames="bad",
                max_frames=1,
            )

        handler._face_json = fake  # type: ignore
        client = await self._client(handler)
        try:
            resp = await client.post(
                "/mcp/face-enrollment/session",
                headers=self._headers(),
                json={"capture_mode": "front_only_v1"},
            )
            body = await resp.json()
            self.assertFalse(body["ok"])
            self.assertEqual(body["error_code"], "internal_error")
            self.assertNotIn("upload_token", body)
        finally:
            await self._close_client(client)

    async def test_gateway_does_not_wash_bad_assess_guidance(self):
        handler = FaceEnrollmentHandler(self.config)
        upstream = _v2_upstream("siddeadbeef00m7")
        token_box = {}

        async def fake(method, path, *a, json_body=None, **k):
            if method == "POST" and path.endswith("/sessions"):
                return 200, upstream
            # 矛盾：旧会话却报 front_only + count=1 完成
            return 200, {
                "guidance_code": "DRAFT_READY",
                "accepted_count": 1,
                "draft_ready": True,
                "capture_mode": "front_only_v1",
                "required_frames": 1,
                "max_frames": 1,
            }

        handler._face_json = fake  # type: ignore
        client = await self._client(handler)
        try:
            created = await client.post(
                "/mcp/face-enrollment/session", headers=self._headers(), json={}
            )
            cbody = await created.json()
            self.assertTrue(cbody["ok"])
            token_box["t"] = cbody["upload_token"]
            form = FormData()
            form.add_field(
                "image", b"\xff\xd8\xfffakejpg", filename="a.jpg", content_type="image/jpeg"
            )
            resp = await client.post(
                f"/mcp/face-enrollment/assess/{cbody['session_id']}",
                headers={
                    **self._headers(),
                    "X-Enrollment-Token": token_box["t"],
                },
                data=form,
            )
            body = await resp.json()
            # 网关不得把非法/矛盾上游洗成 ok:true
            self.assertFalse(body.get("ok", False))
            self.assertEqual(body["error_code"], "internal_error")
            self.assertNotIn("accepted_count", body)
        finally:
            await self._close_client(client)

    async def test_old_create_omits_capture_mode(self):
        handler = FaceEnrollmentHandler(self.config)
        seen = {"body": None}

        async def fake(method, path, *a, json_body=None, **k):
            seen["body"] = json_body
            return 200, _v2_upstream("siddeadbeef00f2")

        handler._face_json = fake  # type: ignore
        client = await self._client(handler)
        try:
            resp = await client.post(
                "/mcp/face-enrollment/session", headers=self._headers()
            )
            body = await resp.json()
            self.assertTrue(body["ok"])
            self.assertEqual(body["required_frames"], 3)
            self.assertNotIn("capture_mode", body)
            self.assertNotIn("capture_mode", seen["body"] or {})
        finally:
            await self._close_client(client)

    async def test_capability_static_required_frames_still_three(self):
        r = build_face_enrollment_capability(_cfg())
        self.assertEqual(r.capability["required_frames"], 3)
        self.assertNotIn("supported_capture_modes", r.capability)

    async def test_chunked_front_only_same_as_normal(self):
        cfg = _cfg()
        cfg["server"]["face_enrollment_front_only_enabled"] = True
        cfg["server"]["face_enrollment_front_only_allowlist"] = [
            {"account_id": "acct_a", "device_id": "aa:bb:cc:dd:ee:ff"}
        ]
        handler = FaceEnrollmentHandler(cfg)
        creates = {"n": 0}

        async def fake(method, path, *a, json_body=None, **k):
            if method == "POST" and str(path).endswith("/sessions"):
                creates["n"] += 1
                self.assertEqual(json_body.get("capture_mode"), "front_only_v1")
                return 200, _v2_upstream(
                    "siddeadbeef00ch1",
                    capture_mode="front_only_v1",
                    required_frames=1,
                    max_frames=1,
                )
            return 200, {"status": "ok"}

        handler._face_json = fake  # type: ignore
        raw = b'{"capture_mode":"front_only_v1"}'
        probe = {}
        client = await self._client(
            handler, middlewares=[self._cl_probe_middleware(probe)]
        )
        try:
            resp_n = await client.post(
                "/mcp/face-enrollment/session",
                headers=self._headers(),
                data=raw,
            )
            body_n = await resp_n.json()
            self.assertTrue(body_n["ok"])
            self.assertEqual(body_n["required_frames"], 1)
            self.assertEqual(body_n["max_frames"], 1)
            self.assertEqual(body_n["capture_mode"], "front_only_v1")

            probe.clear()
            resp_c = await self._chunked_post(
                client, "/mcp/face-enrollment/session", raw, self._headers()
            )
            body_c = await resp_c.json()
            self.assertIsNone(
                probe.get("content_length"),
                msg=f"chunked request must omit Content-Length, got {probe}",
            )
            te = probe.get("transfer_encoding") or ""
            self.assertTrue(
                "chunked" in te or probe.get("content_length") is None,
                msg=f"expected chunked transfer, probe={probe}",
            )
            self.assertTrue(body_c["ok"])
            self.assertEqual(body_c["required_frames"], 1)
            self.assertEqual(body_c["max_frames"], 1)
            self.assertEqual(body_c["capture_mode"], "front_only_v1")
            self.assertEqual(creates["n"], 2)
        finally:
            await self._close_client(client)

    async def test_chunked_invalid_json_no_upstream(self):
        handler = FaceEnrollmentHandler(self.config)
        creates = {"n": 0}

        async def fake(*a, **k):
            creates["n"] += 1
            return 200, _v2_upstream("siddeadbeef00ch2")

        handler._face_json = fake  # type: ignore
        probe = {}
        client = await self._client(
            handler, middlewares=[self._cl_probe_middleware(probe)]
        )
        try:
            resp = await self._chunked_post(
                client,
                "/mcp/face-enrollment/session",
                b"{not-json",
                self._headers(),
            )
            body = await resp.json()
            self.assertIsNone(probe.get("content_length"))
            self.assertFalse(body["ok"])
            self.assertEqual(body["error_code"], "invalid_capture_mode")
            self.assertEqual(creates["n"], 0)
            self.assertNotIn("upload_token", body)
        finally:
            await self._close_client(client)

    async def test_chunked_non_object_json_no_upstream(self):
        handler = FaceEnrollmentHandler(self.config)
        creates = {"n": 0}

        async def fake(*a, **k):
            creates["n"] += 1
            return 200, _v2_upstream("siddeadbeef00ch3")

        handler._face_json = fake  # type: ignore
        probe = {}
        client = await self._client(
            handler, middlewares=[self._cl_probe_middleware(probe)]
        )
        try:
            for raw in (b"null", b"[1]", b'"front_only_v1"', b"1"):
                creates["n"] = 0
                probe.clear()
                resp = await self._chunked_post(
                    client, "/mcp/face-enrollment/session", raw, self._headers()
                )
                body = await resp.json()
                self.assertIsNone(probe.get("content_length"))
                self.assertFalse(body["ok"])
                self.assertEqual(body["error_code"], "invalid_capture_mode")
                self.assertEqual(creates["n"], 0)
        finally:
            await self._close_client(client)

    async def test_chunked_front_only_not_allowlisted_no_upstream(self):
        handler = FaceEnrollmentHandler(self.config)
        creates = {"n": 0}

        async def fake(*a, **k):
            creates["n"] += 1
            return 200, _v2_upstream("siddeadbeef00ch4")

        handler._face_json = fake  # type: ignore
        probe = {}
        client = await self._client(
            handler, middlewares=[self._cl_probe_middleware(probe)]
        )
        try:
            resp = await self._chunked_post(
                client,
                "/mcp/face-enrollment/session",
                b'{"capture_mode":"front_only_v1"}',
                self._headers(),
            )
            body = await resp.json()
            self.assertIsNone(probe.get("content_length"))
            self.assertFalse(body["ok"])
            self.assertEqual(body["error_code"], "capture_mode_not_allowed")
            self.assertEqual(creates["n"], 0)
        finally:
            await self._close_client(client)

    async def test_multipart_json_two_batches_delayed_second(self):
        """A. JSON 拆两批，第二批延迟到达：完整读取后 front_only 成功。"""
        cfg = _cfg()
        cfg["server"]["face_enrollment_front_only_enabled"] = True
        cfg["server"]["face_enrollment_front_only_allowlist"] = [
            {"account_id": "acct_a", "device_id": "aa:bb:cc:dd:ee:ff"}
        ]
        handler = FaceEnrollmentHandler(cfg)
        creates = {"n": 0}

        async def fake(method, path, *a, json_body=None, **k):
            if method == "POST" and str(path).endswith("/sessions"):
                creates["n"] += 1
                self.assertEqual(json_body.get("capture_mode"), "front_only_v1")
                return 200, _v2_upstream(
                    "siddeadbeef00mp1",
                    capture_mode="front_only_v1",
                    required_frames=1,
                    max_frames=1,
                )
            return 200, {"status": "ok"}

        handler._face_json = fake  # type: ignore
        probe = {}
        client = await self._client(
            handler, middlewares=[self._cl_probe_middleware(probe)]
        )
        try:
            parts = [b'{"capture_', b'mode":"front_only_v1"}']
            task, gates, _ = await self._post_multi_part_chunked(
                client, "/mcp/face-enrollment/session", parts, self._headers()
            )
            # EOF 前不得创建上游
            self.assertEqual(creates["n"], 0)
            gates[0].set()
            resp = await task
            body = await resp.json()
            self.assertIsNone(probe.get("content_length"))
            self.assertTrue(body["ok"])
            self.assertEqual(body["required_frames"], 1)
            self.assertEqual(body["max_frames"], 1)
            self.assertEqual(body["capture_mode"], "front_only_v1")
            self.assertEqual(creates["n"], 1)
        finally:
            await self._close_client(client)

    async def test_leading_whitespace_then_json_not_old_mode(self):
        """B. 第一批仅空白，第二批才是 front_only：不得按旧三姿态创建。"""
        cfg = _cfg()
        cfg["server"]["face_enrollment_front_only_enabled"] = True
        cfg["server"]["face_enrollment_front_only_allowlist"] = [
            {"account_id": "acct_a", "device_id": "aa:bb:cc:dd:ee:ff"}
        ]
        handler = FaceEnrollmentHandler(cfg)
        creates = {"n": 0}

        async def fake(method, path, *a, json_body=None, **k):
            if method == "POST" and str(path).endswith("/sessions"):
                creates["n"] += 1
                self.assertEqual(json_body.get("capture_mode"), "front_only_v1")
                return 200, _v2_upstream(
                    "siddeadbeef00mp2",
                    capture_mode="front_only_v1",
                    required_frames=1,
                    max_frames=1,
                )
            return 200, {"status": "ok"}

        handler._face_json = fake  # type: ignore
        client = await self._client(handler)
        try:
            parts = [b"   ", b'{"capture_mode":"front_only_v1"}']
            task, gates, _ = await self._post_multi_part_chunked(
                client, "/mcp/face-enrollment/session", parts, self._headers()
            )
            # 第一批空白后未 EOF，不得按空体/旧三姿态处理
            self.assertEqual(creates["n"], 0)
            gates[0].set()
            resp = await task
            body = await resp.json()
            self.assertTrue(body["ok"])
            self.assertEqual(body["required_frames"], 1)
            self.assertEqual(body["capture_mode"], "front_only_v1")
        finally:
            await self._close_client(client)

    async def test_valid_json_then_garbage_rejected(self):
        """C. 第一批完整合法 JSON，第二批追加非法内容：拒绝且不创建。"""
        cfg = _cfg()
        cfg["server"]["face_enrollment_front_only_enabled"] = True
        cfg["server"]["face_enrollment_front_only_allowlist"] = [
            {"account_id": "acct_a", "device_id": "aa:bb:cc:dd:ee:ff"}
        ]
        handler = FaceEnrollmentHandler(cfg)
        creates = {"n": 0}

        async def fake(*a, **k):
            creates["n"] += 1
            return 200, _v2_upstream("siddeadbeef00mp3")

        handler._face_json = fake  # type: ignore
        client = await self._client(handler)
        try:
            parts = [b'{"capture_mode":"front_only_v1"}', b"EXTRA-GARBAGE"]
            task, gates, _ = await self._post_multi_part_chunked(
                client, "/mcp/face-enrollment/session", parts, self._headers()
            )
            self.assertEqual(creates["n"], 0)
            gates[0].set()
            resp = await task
            body = await resp.json()
            self.assertFalse(body["ok"])
            self.assertEqual(body["error_code"], "invalid_capture_mode")
            self.assertEqual(creates["n"], 0)
            self.assertNotIn("upload_token", body)
        finally:
            await self._close_client(client)

    async def test_valid_json_then_whitespace_oversize_rejected(self):
        """D. 合法 JSON + 后续空白使总量超限：payload_too_large 且不创建。"""
        cfg = _cfg()
        cfg["server"]["face_enrollment_front_only_enabled"] = True
        cfg["server"]["face_enrollment_front_only_allowlist"] = [
            {"account_id": "acct_a", "device_id": "aa:bb:cc:dd:ee:ff"}
        ]
        handler = FaceEnrollmentHandler(cfg)
        creates = {"n": 0}

        async def fake(*a, **k):
            creates["n"] += 1
            return 200, _v2_upstream("siddeadbeef00mp4")

        handler._face_json = fake  # type: ignore
        client = await self._client(handler)
        try:
            pad = b" " * (V2_CREATE_JSON_MAX_BYTES + 8)
            parts = [b'{"capture_mode":"front_only_v1"}', pad]
            task, gates, _ = await self._post_multi_part_chunked(
                client, "/mcp/face-enrollment/session", parts, self._headers()
            )
            self.assertEqual(creates["n"], 0)
            gates[0].set()
            resp = await task
            body = await resp.json()
            self.assertFalse(body["ok"])
            self.assertEqual(body["error_code"], "payload_too_large")
            self.assertEqual(creates["n"], 0)
        finally:
            await self._close_client(client)

    async def test_multibatch_utf8_cross_boundary(self):
        """E. 跨批次 UTF-8 多字节字符：完整读取后正常解析。"""
        cfg = _cfg()
        cfg["server"]["face_enrollment_front_only_enabled"] = True
        cfg["server"]["face_enrollment_front_only_allowlist"] = [
            {"account_id": "acct_a", "device_id": "aa:bb:cc:dd:ee:ff"}
        ]
        handler = FaceEnrollmentHandler(cfg)
        creates = {"n": 0}

        async def fake(method, path, *a, json_body=None, **k):
            if method == "POST" and str(path).endswith("/sessions"):
                creates["n"] += 1
                self.assertEqual(json_body.get("capture_mode"), "front_only_v1")
                return 200, _v2_upstream(
                    "siddeadbeef00mp5",
                    capture_mode="front_only_v1",
                    required_frames=1,
                    max_frames=1,
                )
            return 200, {"status": "ok"}

        handler._face_json = fake  # type: ignore
        client = await self._client(handler)
        try:
            full = '{"capture_mode":"front_only_v1","z":"脸"}'.encode("utf-8")
            marker = "脸".encode("utf-8")
            idx = full.index(marker)
            # 第一批结束于多字节字符的第一个字节，跨批次
            parts = [full[: idx + 1], full[idx + 1 :]]
            task, gates, _ = await self._post_multi_part_chunked(
                client, "/mcp/face-enrollment/session", parts, self._headers()
            )
            self.assertEqual(creates["n"], 0)
            gates[0].set()
            resp = await task
            body = await resp.json()
            self.assertTrue(body["ok"])
            self.assertEqual(body["capture_mode"], "front_only_v1")
            self.assertEqual(creates["n"], 1)
        finally:
            await self._close_client(client)

    async def test_client_abort_no_upstream(self):
        """网络读取失败/客户端中断：不得创建上游会话。"""
        handler = FaceEnrollmentHandler(self.config)
        creates = {"n": 0}

        async def fake(*a, **k):
            creates["n"] += 1
            return 200, _v2_upstream("siddeadbeef00mp6")

        handler._face_json = fake  # type: ignore
        client = await self._client(handler)
        try:
            async def gen():
                yield b'{"capture_'
                raise RuntimeError("simulated client abort")

            h = {**self._headers(), "Content-Type": "application/json"}
            task = asyncio.ensure_future(
                client.post("/mcp/face-enrollment/session", data=gen(), headers=h)
            )
            try:
                await task
            except Exception:
                pass
            # 给服务端事件循环机会处理断连，再断言未创建
            for _ in range(20):
                await asyncio.sleep(0)
            self.assertEqual(creates["n"], 0)
        finally:
            await self._close_client(client)

    async def test_empty_and_empty_object_still_old_mode(self):
        handler = FaceEnrollmentHandler(self.config)
        creates = {"n": 0}

        async def fake(method, path, *a, json_body=None, **k):
            creates["n"] += 1
            self.assertNotIn("capture_mode", json_body or {})
            return 200, _v2_upstream(f"siddeadbeef00e{creates['n']}")

        handler._face_json = fake  # type: ignore
        client = await self._client(handler)
        try:
            r1 = await client.post(
                "/mcp/face-enrollment/session", headers=self._headers()
            )
            b1 = await r1.json()
            self.assertTrue(b1["ok"])
            self.assertEqual(b1["required_frames"], 3)

            r2 = await client.post(
                "/mcp/face-enrollment/session",
                headers=self._headers(),
                json={},
            )
            b2 = await r2.json()
            self.assertTrue(b2["ok"])
            self.assertEqual(b2["required_frames"], 3)
            self.assertEqual(creates["n"], 2)
        finally:
            await self._close_client(client)

    async def test_create_body_oversize_no_upstream(self):
        handler = FaceEnrollmentHandler(self.config)
        creates = {"n": 0}

        async def fake(*a, **k):
            creates["n"] += 1
            return 200, _v2_upstream("siddeadbeef00os")

        handler._face_json = fake  # type: ignore
        client = await self._client(handler)
        try:
            huge = b"{" + (b"a" * (V2_CREATE_JSON_MAX_BYTES + 64)) + b"}"
            resp = await client.post(
                "/mcp/face-enrollment/session",
                headers={
                    **self._headers(),
                    "Content-Type": "application/json",
                    "Content-Length": str(len(huge)),
                },
                data=huge,
            )
            body = await resp.json()
            self.assertFalse(body["ok"])
            self.assertEqual(body["error_code"], "payload_too_large")
            self.assertEqual(creates["n"], 0)
        finally:
            await self._close_client(client)

    async def test_handler_rejects_coerced_complete_fields(self):
        """畸形 accepted_count/draft_ready 不得经 assess/capture 洗成完成。"""
        handler = FaceEnrollmentHandler(self.config)
        sid = "siddeadbeef00cg"
        token, _ = handler.issue_upload_token(
            session_id=sid,
            device_id=self.device_id,
            account_id="acct_a",
            ttl=240,
            scope=UPLOAD_TOKEN_SCOPE_V2,
        )
        from core.utils.face_enrollment_v2 import remember_session_policy

        remember_session_policy(sid, "guided_burst_v1", 3)

        cases = [
            {
                "guidance_code": "DRAFT_READY",
                "accepted_count": 1.9,
                "draft_ready": True,
            },
            {
                "guidance_code": "DRAFT_READY",
                "accepted_count": 3,
                "draft_ready": "false",
            },
            {
                "guidance_code": "DRAFT_READY",
                "accepted_count": 3,
                "draft_ready": False,
            },
            {
                "guidance_code": "ALIGN_READY",
                "accepted_count": 0,
                "draft_ready": True,
            },
            {
                "guidance_code": "DRAFT_READY",
                "accepted_count": "1",
                "draft_ready": True,
            },
            {
                "guidance_code": "DRAFT_READY",
                "accepted_count": True,
                "draft_ready": True,
            },
            {
                "guidance_code": "DRAFT_READY",
                "accepted_count": None,
                "draft_ready": True,
            },
            {
                "guidance_code": "DRAFT_READY",
                "accepted_count": 3,
                "draft_ready": "true",
            },
            {
                "guidance_code": "DRAFT_READY",
                "accepted_count": 3,
                "draft_ready": 1,
            },
        ]
        client = await self._client(handler)
        try:
            for case in cases:
                async def fake(*a, body=case, **k):
                    return 200, dict(body)

                handler._face_json = fake  # type: ignore
                form = FormData()
                form.add_field(
                    "image",
                    b"\xff\xd8\xff" + b"0" * 64,
                    filename="a.jpg",
                    content_type="image/jpeg",
                )
                resp = await client.post(
                    f"/mcp/face-enrollment/assess/{sid}",
                    data=form,
                    headers=self._headers(**{"X-Enrollment-Token": token}),
                )
                body = await resp.json()
                self.assertFalse(body.get("ok", False), msg=f"assess {case}")
                self.assertEqual(body["error_code"], "internal_error")
                self.assertNotIn("accepted_count", body)

                # capture 路径同样不得洗成成功
                form_c = FormData()
                form_c.add_field("pose", "front")
                form_c.add_field("round", "1")
                for i in range(3):
                    form_c.add_field(
                        f"candidate_{i}",
                        b"\xff\xd8\xff" + b"0" * 64,
                        filename=f"c{i}.jpg",
                        content_type="image/jpeg",
                    )
                resp_c = await client.post(
                    f"/mcp/face-enrollment/capture/{sid}",
                    data=form_c,
                    headers=self._headers(**{"X-Enrollment-Token": token}),
                )
                body_c = await resp_c.json()
                self.assertFalse(body_c.get("ok", False), msg=f"capture {case}")
                self.assertEqual(body_c["error_code"], "internal_error")
        finally:
            await self._close_client(client)

    async def test_handler_accepts_strict_complete_and_incomplete(self):
        handler = FaceEnrollmentHandler(self.config)
        sid = "siddeadbeef00ok"
        token, _ = handler.issue_upload_token(
            session_id=sid,
            device_id=self.device_id,
            account_id="acct_a",
            ttl=240,
            scope=UPLOAD_TOKEN_SCOPE_V2,
        )
        from core.utils.face_enrollment_v2 import remember_session_policy

        remember_session_policy(sid, "guided_burst_v1", 3)
        client = await self._client(handler)
        try:
            async def fake_ok(*a, **k):
                return 200, {
                    "guidance_code": "DRAFT_READY",
                    "accepted_count": 3,
                    "draft_ready": True,
                }

            handler._face_json = fake_ok  # type: ignore
            form = FormData()
            form.add_field(
                "image",
                b"\xff\xd8\xff" + b"0" * 64,
                filename="a.jpg",
                content_type="image/jpeg",
            )
            resp = await client.post(
                f"/mcp/face-enrollment/assess/{sid}",
                data=form,
                headers=self._headers(**{"X-Enrollment-Token": token}),
            )
            body = await resp.json()
            self.assertTrue(body["ok"])
            self.assertEqual(body["accepted_count"], 3)
            self.assertTrue(body["draft_ready"])

            async def fake_inc(*a, **k):
                return 200, {
                    "guidance_code": "ALIGN_READY",
                    "accepted_count": 0,
                    "draft_ready": False,
                }

            handler._face_json = fake_inc  # type: ignore
            form2 = FormData()
            form2.add_field(
                "image",
                b"\xff\xd8\xff" + b"0" * 64,
                filename="a.jpg",
                content_type="image/jpeg",
            )
            resp2 = await client.post(
                f"/mcp/face-enrollment/assess/{sid}",
                data=form2,
                headers=self._headers(**{"X-Enrollment-Token": token}),
            )
            b2 = await resp2.json()
            self.assertTrue(b2["ok"])
            self.assertEqual(b2["accepted_count"], 0)
            self.assertFalse(b2["draft_ready"])
        finally:
            await self._close_client(client)

    # ── user_relative_v1 指导能力协商 ────────────────────────────────

    def _user_relative_cfg(self):
        cfg = _cfg()
        cfg["server"]["face_enrollment_front_only_enabled"] = True
        cfg["server"]["face_enrollment_front_only_allowlist"] = [
            {"account_id": "acct_a", "device_id": self.device_id}
        ]
        cfg["server"]["face_enrollment_user_relative_enabled"] = True
        cfg["server"]["face_enrollment_user_relative_allowlist"] = [
            {"account_id": "acct_a", "device_id": self.device_id}
        ]
        return cfg

    async def test_user_relative_create_ok_echo(self):
        from core.utils.face_enrollment_v2 import get_session_guidance_profile

        cfg = self._user_relative_cfg()
        handler = FaceEnrollmentHandler(cfg)
        seen = {"body": None}

        async def fake(method, path, *a, json_body=None, **k):
            seen["body"] = json_body
            return 200, _v2_upstream(
                "siddeadbeef00u1",
                capture_mode="front_only_v1",
                required_frames=1,
                max_frames=1,
                guidance_profile="user_relative_v1",
            )

        handler._face_json = fake  # type: ignore
        client = await self._client(handler)
        try:
            resp = await client.post(
                "/mcp/face-enrollment/session",
                headers=self._headers(),
                json={
                    "capture_mode": "front_only_v1",
                    "guidance_profile": "user_relative_v1",
                },
            )
            body = await resp.json()
            self.assertTrue(body["ok"])
            self.assertEqual(body["guidance_profile"], "user_relative_v1")
            self.assertEqual(body["capture_mode"], "front_only_v1")
            self.assertEqual(seen["body"]["guidance_profile"], "user_relative_v1")
            self.assertEqual(
                get_session_guidance_profile(body["session_id"]), "user_relative_v1"
            )
        finally:
            await self._close_client(client)

    async def test_user_relative_unknown_profile_rejected(self):
        cfg = self._user_relative_cfg()
        handler = FaceEnrollmentHandler(cfg)
        called = {"n": 0}

        async def fake(method, path, *a, json_body=None, **k):
            called["n"] += 1
            return 200, _v2_upstream("siddeadbeef00u2")

        handler._face_json = fake  # type: ignore
        client = await self._client(handler)
        try:
            resp = await client.post(
                "/mcp/face-enrollment/session",
                headers=self._headers(),
                json={
                    "capture_mode": "front_only_v1",
                    "guidance_profile": "foo_v1",
                },
            )
            body = await resp.json()
            self.assertFalse(body["ok"])
            self.assertEqual(body["error_code"], "invalid_guidance_profile")
            self.assertEqual(called["n"], 0)
        finally:
            await self._close_client(client)

    async def test_user_relative_without_front_only_rejected(self):
        cfg = self._user_relative_cfg()
        handler = FaceEnrollmentHandler(cfg)
        called = {"n": 0}

        async def fake(method, path, *a, json_body=None, **k):
            called["n"] += 1
            return 200, _v2_upstream("siddeadbeef00u3")

        handler._face_json = fake  # type: ignore
        client = await self._client(handler)
        try:
            resp = await client.post(
                "/mcp/face-enrollment/session",
                headers=self._headers(),
                json={"guidance_profile": "user_relative_v1"},
            )
            body = await resp.json()
            self.assertFalse(body["ok"])
            self.assertEqual(body["error_code"], "invalid_guidance_profile")
            self.assertEqual(called["n"], 0)
        finally:
            await self._close_client(client)

    async def test_user_relative_not_allowlisted_rejected(self):
        cfg = self._user_relative_cfg()
        # 设备在 front_only 名单但不在 user_relative 名单
        cfg["server"]["face_enrollment_user_relative_allowlist"] = [
            {"account_id": "acct_a", "device_id": "zz:zz:zz:zz:zz:zz"}
        ]
        handler = FaceEnrollmentHandler(cfg)
        called = {"n": 0}

        async def fake(method, path, *a, json_body=None, **k):
            called["n"] += 1
            return 200, _v2_upstream("siddeadbeef00u4")

        handler._face_json = fake  # type: ignore
        client = await self._client(handler)
        try:
            resp = await client.post(
                "/mcp/face-enrollment/session",
                headers=self._headers(),
                json={
                    "capture_mode": "front_only_v1",
                    "guidance_profile": "user_relative_v1",
                },
            )
            body = await resp.json()
            self.assertFalse(body["ok"])
            self.assertEqual(body["error_code"], "guidance_profile_not_allowed")
            self.assertEqual(called["n"], 0)
        finally:
            await self._close_client(client)

    async def test_user_relative_upstream_no_echo_rejected(self):
        cfg = self._user_relative_cfg()
        handler = FaceEnrollmentHandler(cfg)
        cleanup = {"n": 0}

        async def fake(method, path, *a, json_body=None, **k):
            if method == "DELETE":
                cleanup["n"] += 1
                return 200, {"status": "ok"}
            return 200, _v2_upstream(
                "siddeadbeef00u5",
                capture_mode="front_only_v1",
                required_frames=1,
                max_frames=1,
            )

        handler._face_json = fake  # type: ignore
        client = await self._client(handler)
        try:
            resp = await client.post(
                "/mcp/face-enrollment/session",
                headers=self._headers(),
                json={
                    "capture_mode": "front_only_v1",
                    "guidance_profile": "user_relative_v1",
                },
            )
            body = await resp.json()
            self.assertFalse(body["ok"])
            self.assertEqual(body["error_code"], "internal_error")
            self.assertEqual(cleanup["n"], 1)
        finally:
            await self._close_client(client)

    async def test_user_relative_unrequested_echo_rejected(self):
        cfg = self._user_relative_cfg()
        handler = FaceEnrollmentHandler(cfg)
        cleanup = {"n": 0}

        async def fake(method, path, *a, json_body=None, **k):
            if method == "DELETE":
                cleanup["n"] += 1
                return 200, {"status": "ok"}
            return 200, _v2_upstream(
                "siddeadbeef00u6",
                capture_mode="front_only_v1",
                required_frames=1,
                max_frames=1,
                guidance_profile="user_relative_v1",
            )

        handler._face_json = fake  # type: ignore
        client = await self._client(handler)
        try:
            resp = await client.post(
                "/mcp/face-enrollment/session",
                headers=self._headers(),
                json={"capture_mode": "front_only_v1"},
            )
            body = await resp.json()
            self.assertFalse(body["ok"])
            self.assertEqual(body["error_code"], "internal_error")
            self.assertEqual(cleanup["n"], 1)
        finally:
            await self._close_client(client)

    async def test_move_user_code_rejected_in_non_profile_session(self):
        from core.utils.face_enrollment_v2 import remember_session_policy

        handler = FaceEnrollmentHandler(self.config)
        sid = "siddeadbeef00m1"
        token, _ = handler.issue_upload_token(
            session_id=sid,
            device_id=self.device_id,
            account_id="acct_a",
            ttl=240,
            scope=UPLOAD_TOKEN_SCOPE_V2,
        )
        remember_session_policy(sid, "guided_burst_v1", 3)
        client = await self._client(handler)
        try:

            async def fake(*a, **k):
                return 200, {
                    "guidance_code": "MOVE_USER_LEFT",
                    "accepted_count": 0,
                    "draft_ready": False,
                }

            handler._face_json = fake  # type: ignore
            form = FormData()
            form.add_field(
                "image",
                b"\xff\xd8\xff" + b"0" * 64,
                filename="a.jpg",
                content_type="image/jpeg",
            )
            resp = await client.post(
                f"/mcp/face-enrollment/assess/{sid}",
                data=form,
                headers=self._headers(**{"X-Enrollment-Token": token}),
            )
            body = await resp.json()
            self.assertFalse(body["ok"])
            self.assertEqual(body["error_code"], "internal_error")
        finally:
            await self._close_client(client)

    async def test_move_user_code_ok_in_profile_session(self):
        from core.utils.face_enrollment_v2 import (
            remember_session_guidance_profile,
            remember_session_policy,
        )

        handler = FaceEnrollmentHandler(self.config)
        sid = "siddeadbeef00m2"
        token, _ = handler.issue_upload_token(
            session_id=sid,
            device_id=self.device_id,
            account_id="acct_a",
            ttl=240,
            scope=UPLOAD_TOKEN_SCOPE_V2,
        )
        remember_session_policy(sid, "front_only_v1", 1)
        remember_session_guidance_profile(sid, "user_relative_v1")
        client = await self._client(handler)
        try:

            async def fake(*a, **k):
                return 200, {
                    "guidance_code": "MOVE_USER_RIGHT",
                    "accepted_count": 0,
                    "draft_ready": False,
                    "capture_mode": "front_only_v1",
                    "required_frames": 1,
                }

            handler._face_json = fake  # type: ignore
            form = FormData()
            form.add_field(
                "image",
                b"\xff\xd8\xff" + b"0" * 64,
                filename="a.jpg",
                content_type="image/jpeg",
            )
            resp = await client.post(
                f"/mcp/face-enrollment/assess/{sid}",
                data=form,
                headers=self._headers(**{"X-Enrollment-Token": token}),
            )
            body = await resp.json()
            self.assertTrue(body["ok"])
            self.assertEqual(body["guidance_code"], "MOVE_USER_RIGHT")
        finally:
            await self._close_client(client)


class V2StrictGuidanceFieldTests(unittest.TestCase):
    def test_parse_accepted_count_rejects_coercion(self):
        for bad in (1.9, 1.0, "1", True, False, None, [], {}):
            self.assertIsNone(parse_accepted_count(bad, max_count=3))
        self.assertEqual(parse_accepted_count(0, max_count=3), 0)
        self.assertEqual(parse_accepted_count(3, max_count=3), 3)
        self.assertIsNone(parse_accepted_count(4, max_count=3))

    def test_draft_ready_string_and_null_rejected(self):
        for bad in ("false", "true", 0, 1, None):
            payload, err = build_v2_guidance_payload(
                session_id="s",
                guidance_code="ALIGN_READY",
                accepted_count=0,
                draft_ready=bad,
            )
            self.assertIsNone(payload)
            self.assertEqual(err, "internal_error")

    def test_draft_ready_false_with_draft_ready_code_rejected(self):
        payload, err = build_v2_guidance_payload(
            session_id="s",
            guidance_code="DRAFT_READY",
            accepted_count=3,
            draft_ready=False,
        )
        self.assertIsNone(payload)
        self.assertEqual(err, "internal_error")

    def test_draft_ready_true_with_non_complete_code_rejected(self):
        payload, err = build_v2_guidance_payload(
            session_id="s",
            guidance_code="ALIGN_READY",
            accepted_count=0,
            draft_ready=True,
        )
        self.assertIsNone(payload)
        self.assertEqual(err, "internal_error")

    def test_front_only_strict_complete(self):
        payload, err = build_v2_guidance_payload(
            session_id="s",
            guidance_code="DRAFT_READY",
            accepted_count=1,
            draft_ready=True,
            capture_mode="front_only_v1",
            required_frames=1,
        )
        self.assertIsNone(err)
        self.assertEqual(payload["accepted_count"], 1)
        self.assertTrue(payload["draft_ready"])

    def test_old_mode_strict_complete(self):
        payload, err = build_v2_guidance_payload(
            session_id="s",
            guidance_code="DRAFT_READY",
            accepted_count=3,
            draft_ready=True,
        )
        self.assertIsNone(err)
        self.assertEqual(payload["accepted_count"], 3)
        self.assertTrue(payload["draft_ready"])

    def test_incomplete_int_false_ok(self):
        payload, err = build_v2_guidance_payload(
            session_id="s",
            guidance_code="ALIGN_READY",
            accepted_count=0,
            draft_ready=False,
        )
        self.assertIsNone(err)
        self.assertEqual(payload["accepted_count"], 0)
        self.assertFalse(payload["draft_ready"])

    def test_missing_draft_ready_compat_for_complete(self):
        """字段缺失时可推断 DRAFT_READY；显式 False/null 不可。"""
        ok, err = build_v2_guidance_payload(
            session_id="s",
            guidance_code="DRAFT_READY",
            accepted_count=3,
            draft_ready=DRAFT_READY_FIELD_MISSING,
        )
        self.assertIsNone(err)
        self.assertTrue(ok["draft_ready"])
        bad, err2 = build_v2_guidance_payload(
            session_id="s",
            guidance_code="DRAFT_READY",
            accepted_count=3,
            draft_ready=False,
        )
        self.assertIsNone(bad)
        self.assertEqual(err2, "internal_error")
        bad_null, err3 = build_v2_guidance_payload(
            session_id="s",
            guidance_code="DRAFT_READY",
            accepted_count=3,
            draft_ready=None,
        )
        self.assertIsNone(bad_null)
        self.assertEqual(err3, "internal_error")

    def test_float_accepted_count_not_truncated_to_complete(self):
        payload, err = build_v2_guidance_payload(
            session_id="s",
            guidance_code="DRAFT_READY",
            accepted_count=1.9,
            draft_ready=True,
            capture_mode="front_only_v1",
            required_frames=1,
        )
        self.assertIsNone(payload)
        self.assertEqual(err, "internal_error")
        payload2, err2 = build_v2_guidance_payload(
            session_id="s",
            guidance_code="DRAFT_READY",
            accepted_count=1.0,
            draft_ready=True,
            capture_mode="front_only_v1",
            required_frames=1,
        )
        self.assertIsNone(payload2)
        self.assertEqual(err2, "internal_error")


if __name__ == "__main__":
    unittest.main()
