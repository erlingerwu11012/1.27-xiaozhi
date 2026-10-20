"""设备 enrollment HTTP 契约：V2 ok/error_code/retryable + 上传防护 + 限流。"""

from __future__ import annotations

import json
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from aiohttp import FormData, web
from aiohttp.test_utils import TestClient, TestServer

from core.api.face_enrollment_handler import FaceEnrollmentHandler
from core.auth import AuthManager
from core.utils.face_enrollment_limits import (
    DEVICE_CREATE_LIMIT,
    reset_limiters_for_tests,
    reset_metrics_for_tests,
)
from core.utils.face_enrollment_v2 import (
    UPLOAD_TOKEN_SCOPE_V2,
    V2_ERROR_CODES,
    v2_error_body,
)

INDEPENDENT_KEY = "enroll-upload-signing-key-32chars!!"


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


def _v2_upstream(session_id: str = "abc123def4567890", **overrides):
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


class ContractSchemaTests(unittest.TestCase):
    def test_v2_error_codes_complete(self):
        required = {
            "enrollment_disabled",
            "capability_invalid",
            "enrollment_already_active",
            "session_not_found",
            "session_expired",
            "session_cancelled",
            "session_already_consumed",
            "device_mismatch",
            "account_mismatch",
            "auth_invalid",
            "upload_token_invalid",
            "upload_token_expired",
            "upload_limit_reached",
            "account_draft_quota_exceeded",
            "invalid_content_type",
            "payload_too_large",
            "invalid_jpeg",
            "image_dimensions_invalid",
            "enrollment_busy",
            "internal_error",
        }
        self.assertTrue(required.issubset(V2_ERROR_CODES))

    def test_v2_error_body_shape(self):
        body = v2_error_body("auth_invalid")
        self.assertEqual(set(body.keys()), {"ok", "error_code", "retryable"})
        self.assertFalse(body["ok"])
        self.assertEqual(body["error_code"], "auth_invalid")
        self.assertNotIn("message", body)


class DeviceHttpContractTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        reset_limiters_for_tests()
        reset_metrics_for_tests()
        self.config = _cfg()
        self.auth = AuthManager(
            secret_key="device-pairing-secret-not-enroll", expire_seconds=86400
        )
        self.device_id = "aa:bb:cc:dd:ee:ff"
        self.client_id = "client-1"
        self.token = self.auth.generate_token(self.client_id, self.device_id)

    def _headers(self, **extra):
        h = {
            "Authorization": f"Bearer {self.token}",
            "Device-Id": self.device_id,
            "Client-Id": self.client_id,
        }
        h.update(extra)
        return h

    async def _client(self, handler):
        app = web.Application()
        app.router.add_post(
            "/mcp/face-enrollment/session", handler.handle_v2_create_session
        )
        app.router.add_post(
            "/mcp/face-enrollment/assess/{session_id}", handler.handle_v2_assess
        )
        app.router.add_delete(
            "/mcp/face-enrollment/cancel/{session_id}", handler.handle_v2_cancel
        )
        server = TestServer(app)
        client = TestClient(server)
        await client.start_server()
        return client

    async def test_create_auth_invalid_schema(self):
        handler = FaceEnrollmentHandler(self.config)
        client = await self._client(handler)
        try:
            resp = await client.post("/mcp/face-enrollment/session")
            self.assertEqual(resp.status, 401)
            body = await resp.json()
            self.assertEqual(body["ok"], False)
            self.assertEqual(body["error_code"], "auth_invalid")
            self.assertIn("retryable", body)
            self.assertNotIn("message", body)
        finally:
            await client.close()

    async def test_create_disabled_without_signing_key(self):
        handler = FaceEnrollmentHandler(_cfg(face_enrollment_upload_signing_key=""))
        client = await self._client(handler)
        try:
            resp = await client.post(
                "/mcp/face-enrollment/session", headers=self._headers()
            )
            self.assertEqual(resp.status, 503)
            body = await resp.json()
            self.assertEqual(body["error_code"], "enrollment_disabled")
            self.assertNotIn("message", body)
        finally:
            await client.close()

    async def test_create_success_ok_true(self):
        handler = FaceEnrollmentHandler(self.config)

        async def fake_face_json(method, path, **kwargs):
            return 200, _v2_upstream()

        handler._face_json = fake_face_json  # type: ignore
        client = await self._client(handler)
        try:
            resp = await client.post(
                "/mcp/face-enrollment/session", headers=self._headers()
            )
            self.assertEqual(resp.status, 200)
            body = await resp.json()
            self.assertTrue(body["ok"])
            self.assertIn("upload_token", body)
            self.assertIn("assess_url", body)
            self.assertNotIn("embedding", body)
            self.assertNotIn("display_name", body)
            self.assertNotIn("account_id", body)
            dumped = json.dumps(body)
            self.assertNotIn(INDEPENDENT_KEY, dumped)
            self.assertEqual(
                handler.verify_upload_token(
                    body["upload_token"],
                    session_id=body["session_id"],
                    device_id=self.device_id,
                    account_id="acct_a",
                    scope=UPLOAD_TOKEN_SCOPE_V2,
                ),
                "ok",
            )
        finally:
            await client.close()

    async def test_assess_success_schema(self):
        handler = FaceEnrollmentHandler(self.config)
        token, _ = handler.issue_upload_token(
            session_id="sidupload01abcdef",
            device_id=self.device_id,
            account_id="acct_a",
            ttl=240,
            scope=UPLOAD_TOKEN_SCOPE_V2,
        )

        async def fake_face_json(method, path, **kwargs):
            return 200, {
                "guidance_code": "HOLD_STILL",
                "accepted_count": 0,
                "draft_ready": False,
            }

        handler._face_json = fake_face_json  # type: ignore
        client = await self._client(handler)
        try:
            form = FormData()
            form.add_field(
                "image",
                b"\xff\xd8\xff" + b"0" * 100,
                filename="a.jpg",
                content_type="image/jpeg",
            )
            resp = await client.post(
                "/mcp/face-enrollment/assess/sidupload01abcdef",
                data=form,
                headers={**self._headers(), "X-Enrollment-Token": token},
            )
            self.assertEqual(resp.status, 200)
            body = await resp.json()
            self.assertTrue(body["ok"])
            self.assertEqual(body["guidance_code"], "HOLD_STILL")
            self.assertEqual(body["accepted_count"], 0)
            self.assertFalse(body["draft_ready"])
            self.assertNotIn("embedding", body)
            self.assertNotIn("message", body)
        finally:
            await client.close()

    async def test_upload_token_expired(self):
        handler = FaceEnrollmentHandler(self.config)
        token, _ = handler.issue_upload_token(
            session_id="sid1aaaa",
            device_id=self.device_id,
            account_id="acct_a",
            ttl=-5,
            scope=UPLOAD_TOKEN_SCOPE_V2,
        )
        self.assertEqual(
            handler.verify_upload_token(
                token,
                session_id="sid1aaaa",
                device_id=self.device_id,
                account_id="acct_a",
                scope=UPLOAD_TOKEN_SCOPE_V2,
            ),
            "expired",
        )
        client = await self._client(handler)
        try:
            form = FormData()
            form.add_field(
                "image",
                b"\xff\xd8\xff" + b"0" * 20,
                filename="a.jpg",
                content_type="image/jpeg",
            )
            resp = await client.post(
                "/mcp/face-enrollment/assess/sid1aaaa",
                data=form,
                headers={**self._headers(), "X-Enrollment-Token": token},
            )
            self.assertEqual(resp.status, 403)
            body = await resp.json()
            self.assertEqual(body["error_code"], "upload_token_expired")
            self.assertNotIn("message", body)
        finally:
            await client.close()

    async def test_content_length_too_large(self):
        handler = FaceEnrollmentHandler(self.config)
        token, _ = handler.issue_upload_token(
            session_id="sidbig01",
            device_id=self.device_id,
            account_id="acct_a",
            ttl=240,
            scope=UPLOAD_TOKEN_SCOPE_V2,
        )
        client = await self._client(handler)
        try:
            resp = await client.post(
                "/mcp/face-enrollment/assess/sidbig01",
                data=b"x",
                headers={
                    **self._headers(),
                    "X-Enrollment-Token": token,
                    "Content-Type": "multipart/form-data; boundary=x",
                    "Content-Length": str(1024 * 1024),
                },
            )
            self.assertEqual(resp.status, 413)
            body = await resp.json()
            self.assertEqual(body["error_code"], "payload_too_large")
            self.assertNotIn("message", body)
        finally:
            await client.close()

    async def test_invalid_jpeg_rejected(self):
        handler = FaceEnrollmentHandler(self.config)
        token, _ = handler.issue_upload_token(
            session_id="sidbad01",
            device_id=self.device_id,
            account_id="acct_a",
            ttl=240,
            scope=UPLOAD_TOKEN_SCOPE_V2,
        )
        client = await self._client(handler)
        try:
            form = FormData()
            form.add_field(
                "image",
                b"not-jpeg",
                filename="a.jpg",
                content_type="image/jpeg",
            )
            resp = await client.post(
                "/mcp/face-enrollment/assess/sidbad01",
                data=form,
                headers={**self._headers(), "X-Enrollment-Token": token},
            )
            self.assertEqual(resp.status, 422)
            body = await resp.json()
            self.assertEqual(body["error_code"], "invalid_jpeg")
            self.assertNotIn("message", body)
        finally:
            await client.close()

    async def test_upstream_session_not_found_mapped(self):
        handler = FaceEnrollmentHandler(self.config)
        token, _ = handler.issue_upload_token(
            session_id="sidnf0001",
            device_id=self.device_id,
            account_id="acct_a",
            ttl=240,
            scope=UPLOAD_TOKEN_SCOPE_V2,
        )

        async def fake_face_json(method, path, **kwargs):
            return 404, {"detail": {"code": "not_found", "message": "x"}}

        handler._face_json = fake_face_json  # type: ignore
        client = await self._client(handler)
        try:
            form = FormData()
            form.add_field(
                "image",
                b"\xff\xd8\xff" + b"0" * 40,
                filename="a.jpg",
                content_type="image/jpeg",
            )
            resp = await client.post(
                "/mcp/face-enrollment/assess/sidnf0001",
                data=form,
                headers={**self._headers(), "X-Enrollment-Token": token},
            )
            self.assertEqual(resp.status, 404)
            body = await resp.json()
            self.assertEqual(body["error_code"], "session_not_found")
            self.assertNotIn("message", body)
        finally:
            await client.close()

    async def test_create_rate_limited(self):
        handler = FaceEnrollmentHandler(self.config)

        async def fake_face_json(method, path, **kwargs):
            return 200, _v2_upstream(session_id="x" * 16)

        handler._face_json = fake_face_json  # type: ignore
        client = await self._client(handler)
        try:
            last = None
            for _ in range(DEVICE_CREATE_LIMIT + 1):
                last = await client.post(
                    "/mcp/face-enrollment/session", headers=self._headers()
                )
            self.assertEqual(last.status, 429)
            body = await last.json()
            self.assertEqual(body["error_code"], "rate_limited")
            self.assertNotIn("message", body)
        finally:
            await client.close()

    async def test_cancel_ok_schema(self):
        handler = FaceEnrollmentHandler(self.config)
        token, _ = handler.issue_upload_token(
            session_id="sidcancel01abcd",
            device_id=self.device_id,
            account_id="acct_a",
            ttl=240,
            scope=UPLOAD_TOKEN_SCOPE_V2,
        )

        async def fake_face_json(method, path, **kwargs):
            self.assertIn("/guided-burst", path)
            return 200, {"status": "ok"}

        handler._face_json = fake_face_json  # type: ignore
        client = await self._client(handler)
        try:
            resp = await client.delete(
                "/mcp/face-enrollment/cancel/sidcancel01abcd",
                headers={**self._headers(), "X-Enrollment-Token": token},
            )
            self.assertEqual(resp.status, 200)
            body = await resp.json()
            self.assertTrue(body["ok"])
            self.assertEqual(body["guidance_code"], "CANCELLED")
            self.assertNotIn("accepted_count", body)
            self.assertNotIn("message", body)
        finally:
            await client.close()


class SmokeScriptTests(unittest.TestCase):
    def test_smoke_fail_closed_without_key(self):
        from scripts.face_enrollment_smoke_check import check_capability

        fails = check_capability(
            {
                "server": {
                    "public_base_url": "https://public.example.com",
                    "websocket": "wss://public.example.com/xiaozhi/v1/",
                    "auth_key": "x" * 40,
                    "face": {"account_id": "acct_a", "jwt_secret": "y" * 40},
                    "face_enrollment_upload_signing_key": "",
                }
            }
        )
        # capability fail-closed 本身是 OK，不应列为 failure
        self.assertEqual(fails, [])


if __name__ == "__main__":
    unittest.main()
