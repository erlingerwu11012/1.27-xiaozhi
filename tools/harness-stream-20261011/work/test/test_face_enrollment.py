"""设备人脸采集网关：独立 upload signing key + AuthManager + V2 fail-closed。"""

from __future__ import annotations

import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from aiohttp import FormData, web
from aiohttp.test_utils import TestClient, TestServer

from core.api.face_enrollment_handler import FaceEnrollmentHandler
from core.auth import AuthManager
from core.utils.face_enrollment_capability import (
    MIN_UPLOAD_SIGNING_KEY_LEN,
    build_face_enrollment_capability,
    get_face_enrollment_upload_signing_key,
    validate_face_enrollment_signing_at_startup,
)
from core.utils.face_enrollment_v2 import UPLOAD_TOKEN_SCOPE_V2

INDEPENDENT_KEY = "enroll-upload-signing-key-32chars!!"  # len >= 32


def _base_config(**overrides):
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


class SigningKeyTests(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("FACE_ENROLLMENT_UPLOAD_SIGNING_KEY", None)
        os.environ.pop("XIAOZHI_ENV", None)

    def test_missing_key_fail_closed(self):
        cfg = _base_config(face_enrollment_upload_signing_key="")
        r = build_face_enrollment_capability(cfg)
        self.assertFalse(r.ok)
        self.assertEqual(r.reason, "upload_signing_key_missing")

    def test_too_short_fail_closed(self):
        cfg = _base_config(face_enrollment_upload_signing_key="short")
        r = build_face_enrollment_capability(cfg)
        self.assertFalse(r.ok)
        self.assertEqual(r.reason, "upload_signing_key_too_short")

    def test_reuse_auth_key_fail_closed(self):
        auth = "x" * MIN_UPLOAD_SIGNING_KEY_LEN
        cfg = _base_config(
            auth_key=auth, face_enrollment_upload_signing_key=auth
        )
        r = build_face_enrollment_capability(cfg)
        self.assertFalse(r.ok)
        self.assertEqual(r.reason, "upload_signing_key_reuses_auth_key")

    def test_reuse_face_jwt_fail_closed(self):
        jwt = "y" * MIN_UPLOAD_SIGNING_KEY_LEN
        cfg = _base_config(face_enrollment_upload_signing_key=jwt)
        cfg["server"]["face"]["jwt_secret"] = jwt
        r = build_face_enrollment_capability(cfg)
        self.assertFalse(r.ok)
        self.assertEqual(r.reason, "upload_signing_key_reuses_face_jwt")

    def test_no_fallback_to_auth_key(self):
        cfg = _base_config(face_enrollment_upload_signing_key="")
        cfg["server"]["auth_key"] = "z" * 40
        key, reason = get_face_enrollment_upload_signing_key(cfg)
        self.assertEqual(key, "")
        self.assertEqual(reason, "upload_signing_key_missing")

    def test_env_key_ok(self):
        os.environ["FACE_ENROLLMENT_UPLOAD_SIGNING_KEY"] = INDEPENDENT_KEY
        cfg = _base_config(face_enrollment_upload_signing_key="")
        key, reason = get_face_enrollment_upload_signing_key(cfg)
        self.assertEqual(key, INDEPENDENT_KEY)
        self.assertEqual(reason, "")

    def test_prod_startup_fail_closed(self):
        os.environ["XIAOZHI_ENV"] = "production"
        cfg = _base_config(face_enrollment_upload_signing_key="")
        with self.assertRaises(RuntimeError):
            validate_face_enrollment_signing_at_startup(cfg)


class CapabilityTests(unittest.TestCase):
    def test_https_ok_v2(self):
        r = build_face_enrollment_capability(_base_config())
        self.assertTrue(r.ok)
        self.assertEqual(
            r.capability["session_url"],
            "https://public.example.com/mcp/face-enrollment/session",
        )
        self.assertEqual(r.capability["protocol_version"], 2)
        self.assertTrue(r.capability["guided_burst_v1"] is True)
        self.assertEqual(r.capability["session_timeout_seconds"], 240)
        dumped = json.dumps(r.capability).lower()
        self.assertNotIn("jwt", dumped)
        self.assertNotIn("secret", dumped)
        self.assertNotIn(INDEPENDENT_KEY.lower(), dumped)

    def test_http_fail_closed(self):
        r = build_face_enrollment_capability(
            _base_config(public_base_url="http://public.example.com")
        )
        self.assertFalse(r.ok)

    def test_missing_account_still_static_ok(self):
        """静态 capability 不再依赖 config account_id；动态字段由 conn 路径附加。"""
        cfg = _base_config()
        cfg["server"]["face"]["account_id"] = ""
        r = build_face_enrollment_capability(cfg)
        self.assertTrue(r.ok)
        self.assertNotIn("enrolled_count", r.capability or {})
        self.assertNotIn("default_owner_person_id", r.capability or {})

    def test_missing_auth_key_fail_closed(self):
        r = build_face_enrollment_capability(_base_config(auth_key=""))
        self.assertFalse(r.ok)


class FaceEnrollmentGatewayTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.config = _base_config()
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

    async def _client(self, handler: FaceEnrollmentHandler):
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

    async def test_create_requires_auth(self):
        handler = FaceEnrollmentHandler(self.config)
        client = await self._client(handler)
        try:
            resp = await client.post("/mcp/face-enrollment/session")
            self.assertEqual(resp.status, 401)
        finally:
            await client.close()

    async def test_wrong_device_id_rejected(self):
        handler = FaceEnrollmentHandler(self.config)
        client = await self._client(handler)
        try:
            resp = await client.post(
                "/mcp/face-enrollment/session",
                headers=self._headers(**{"Device-Id": "ff:ee:dd:cc:bb:aa"}),
            )
            self.assertEqual(resp.status, 401)
        finally:
            await client.close()

    async def test_create_rejected_without_independent_key(self):
        cfg = _base_config(face_enrollment_upload_signing_key="")
        handler = FaceEnrollmentHandler(cfg)
        client = await self._client(handler)
        try:
            resp = await client.post(
                "/mcp/face-enrollment/session", headers=self._headers()
            )
            self.assertEqual(resp.status, 503)
        finally:
            await client.close()

    async def test_create_session_ok_issues_scoped_upload_token(self):
        handler = FaceEnrollmentHandler(self.config)
        upstream = _v2_upstream()

        async def fake_face_json(method, path, **kwargs):
            return 200, upstream

        handler._face_json = fake_face_json  # type: ignore
        client = await self._client(handler)
        try:
            resp = await client.post(
                "/mcp/face-enrollment/session", headers=self._headers()
            )
            self.assertEqual(resp.status, 200)
            body = await resp.json()
            self.assertTrue(body.get("ok"))
            self.assertIn("upload_token", body)
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
            self.assertEqual(
                handler.verify_upload_token(
                    body["upload_token"],
                    session_id=body["session_id"],
                    device_id="other-device",
                    account_id="acct_a",
                    scope=UPLOAD_TOKEN_SCOPE_V2,
                ),
                "invalid",
            )
            self.assertEqual(
                handler.verify_upload_token(
                    body["upload_token"],
                    session_id=body["session_id"],
                    device_id=self.device_id,
                    account_id="acct_b",
                    scope=UPLOAD_TOKEN_SCOPE_V2,
                ),
                "invalid",
            )
            self.assertEqual(UPLOAD_TOKEN_SCOPE_V2, "enrollment_upload_v2")
        finally:
            await client.close()

    async def test_expired_upload_token_rejected(self):
        handler = FaceEnrollmentHandler(self.config)
        token, _ = handler.issue_upload_token(
            session_id="sid1aaaa",
            device_id=self.device_id,
            account_id="acct_a",
            ttl=-10,
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
                b"\xff\xd8\xff" + b"0" * 100,
                filename="a.jpg",
                content_type="image/jpeg",
            )
            resp = await client.post(
                "/mcp/face-enrollment/assess/sid1aaaa",
                data=form,
                headers={
                    **self._headers(),
                    "X-Enrollment-Token": token,
                },
            )
            self.assertEqual(resp.status, 403)
            body = await resp.json()
            self.assertEqual(body.get("error_code"), "upload_token_expired")
            self.assertNotIn("message", body)
        finally:
            await client.close()

    async def test_logs_redacted(self):
        from core.api import face_enrollment_handler as mod

        with patch.object(mod, "logger") as mlog:
            b = MagicMock()
            recorded = []

            def info(msg):
                recorded.append(msg)

            b.info = info
            mlog.bind.return_value = b
            mod._log(
                "session_created",
                session="abcd...wxyz",
                device="aabb...eeff",
                http=200,
            )
            blob = "\n".join(recorded)
            self.assertIn("[FACE_ENROLL]", blob)
            self.assertNotIn(INDEPENDENT_KEY, blob)
            self.assertNotIn("face-jwt-secret", blob)


if __name__ == "__main__":
    unittest.main()
