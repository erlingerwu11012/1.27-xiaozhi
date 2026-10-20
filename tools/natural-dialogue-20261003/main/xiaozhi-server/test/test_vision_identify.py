"""纯识人：身份阈值、鉴权、不调用 VLM。"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.api.vision_handler import VisionHandler


def _minimal_jpeg() -> bytes:
    return (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t"
        b"\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e"
        b"\x1d\x1a\x1c\x1c $.\' \",#\x1c\x1c(7),01444\x1f\'9=82<.342"
        b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
        b"\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00"
        b"\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b"
        b"\xff\xda\x00\x08\x01\x01\x00\x00?\x00\x7f\xff\xd9"
    )


class FakeMultipartField:
    def __init__(self, name, data: bytes):
        self.name = name
        self._data = data
        self.headers = {"Content-Type": "image/jpeg"}

    async def read(self):
        return self._data

    async def text(self):
        return self._data.decode("utf-8", errors="ignore")


class FakeMultipartReader:
    def __init__(self, fields):
        self._fields = list(fields)
        self._i = 0

    async def next(self):
        if self._i >= len(self._fields):
            return None
        f = self._fields[self._i]
        self._i += 1
        return f


class FakeRequest:
    def __init__(self, method="POST", headers=None, multipart=None, path="/mcp/vision/identify"):
        self.method = method
        self.headers = headers or {}
        self._multipart = multipart
        self.path = path

    async def multipart(self):
        return self._multipart


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
        except Exception:
            pass
        loop.close()
        asyncio.set_event_loop(None)


class VisionIdentifyTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            "server": {
                "auth_key": "test-auth-key-for-vision",
                "face": {
                    "enabled": True,
                    "identify_url": "http://face.test/face/identify",
                    "jwt_secret": "",
                    "account_id": "acct_test",
                    "identity_match_threshold": 0.80,
                    "timeout": 1.0,
                },
            },
            "selected_module": {"VLLM": "MockVLLM"},
            "VLLM": {"MockVLLM": {"type": "openai"}},
        }
        self.handler = VisionHandler(self.config)
        self.jpeg = _minimal_jpeg()

    def test_identify_known_keeps_user_id(self):
        async def run():
            with patch.object(
                self.handler,
                "_call_face_identify",
                AsyncMock(
                    return_value={
                        "status": "known",
                        "user_id": "usr_aabbcc",
                        "display_name": "小王",
                        "confidence": 0.91,
                    }
                ),
            ):
                with patch.object(
                    self.handler,
                    "_verify_auth_claims",
                    return_value=(True, {"device_id": "dev1", "account_id": "acct_test"}),
                ):
                    req = FakeRequest(
                        headers={"Device-Id": "dev1", "Authorization": "Bearer x"},
                        multipart=FakeMultipartReader(
                            [FakeMultipartField("image", self.jpeg)]
                        ),
                    )
                    with patch(
                        "core.api.vision_handler.is_valid_image_file", return_value=True
                    ):
                        with patch("core.utils.vllm.create_instance") as create_vllm:
                            resp = await self.handler.handle_identify(req)
                            create_vllm.assert_not_called()
                            body = json.loads(resp.text)
                            self.assertEqual(body["status"], "known")
                            self.assertEqual(body["user_id"], "usr_aabbcc")
                            self.assertEqual(body["display_name"], "小王")

        _run(run())

    def test_identify_unknown_no_identity_leak(self):
        async def run():
            with patch.object(
                self.handler,
                "_call_face_identify",
                AsyncMock(return_value={"status": "unknown", "confidence": 0.0}),
            ):
                with patch.object(
                    self.handler,
                    "_verify_auth_claims",
                    return_value=(True, {"device_id": "dev1", "account_id": "acct_test"}),
                ):
                    req = FakeRequest(
                        headers={"Device-Id": "dev1", "Authorization": "Bearer x"},
                        multipart=FakeMultipartReader(
                            [FakeMultipartField("image", self.jpeg)]
                        ),
                    )
                    with patch(
                        "core.api.vision_handler.is_valid_image_file", return_value=True
                    ):
                        resp = await self.handler.handle_identify(req)
                        body = json.loads(resp.text)
                        self.assertEqual(body["status"], "unknown")
                        self.assertEqual(body["reason"], "no_match")
                        self.assertIn("没有匹配到", body.get("message") or "")
                        self.assertNotIn("user_id", body)
                        self.assertNotIn("display_name", body)

        _run(run())

    def test_unauthenticated_identify_rejected(self):
        async def run():
            req = FakeRequest(
                headers={"Device-Id": "dev1"},
                multipart=FakeMultipartReader(
                    [FakeMultipartField("image", self.jpeg)]
                ),
            )
            with patch.object(
                self.handler, "_verify_auth_claims", return_value=(False, None)
            ):
                resp = await self.handler.handle_identify(req)
                self.assertEqual(resp.status, 401)
                body = json.loads(resp.text)
                self.assertFalse(body.get("success", True))

        _run(run())

    def test_device_mismatch_rejected(self):
        async def run():
            req = FakeRequest(
                headers={"Device-Id": "dev-other", "Authorization": "Bearer x"},
                multipart=FakeMultipartReader(
                    [FakeMultipartField("image", self.jpeg)]
                ),
            )
            with patch.object(
                self.handler,
                "_verify_auth_claims",
                return_value=(True, {"device_id": "dev1", "account_id": "acct_test"}),
            ):
                resp = await self.handler.handle_identify(req)
                self.assertEqual(resp.status, 403)
                body = json.loads(resp.text)
                self.assertEqual(body.get("reason"), "permission_denied")

        _run(run())

    def test_missing_device_id_rejected(self):
        async def run():
            req = FakeRequest(
                headers={"Authorization": "Bearer x"},
                multipart=FakeMultipartReader(
                    [FakeMultipartField("image", self.jpeg)]
                ),
            )
            with patch.object(
                self.handler,
                "_verify_auth_claims",
                return_value=(True, {"device_id": "dev1", "account_id": "acct_test"}),
            ):
                resp = await self.handler.handle_identify(req)
                self.assertEqual(resp.status, 403)
                body = json.loads(resp.text)
                self.assertEqual(body.get("reason"), "permission_denied")

        _run(run())

    def test_missing_account_id_rejected(self):
        async def run():
            self.config["server"]["face"]["account_id"] = ""
            handler = VisionHandler(self.config)
            req = FakeRequest(
                headers={"Device-Id": "dev1", "Authorization": "Bearer x"},
                multipart=FakeMultipartReader(
                    [FakeMultipartField("image", self.jpeg)]
                ),
            )
            with patch.object(
                handler,
                "_verify_auth_claims",
                return_value=(True, {"device_id": "dev1"}),
            ):
                resp = await handler.handle_identify(req)
                self.assertEqual(resp.status, 503)

        _run(run())

    def test_token_account_used_when_config_empty(self):
        async def run():
            self.config["server"]["face"]["account_id"] = ""
            handler = VisionHandler(self.config)
            captured = {}

            async def fake_call(image_data, device_id="vision", account_id=None):
                captured["account_id"] = account_id
                return {
                    "status": "known",
                    "user_id": "usr_aabbcc",
                    "display_name": "小王",
                    "confidence": 0.91,
                }

            req = FakeRequest(
                headers={"Device-Id": "dev1", "Authorization": "Bearer x"},
                multipart=FakeMultipartReader(
                    [FakeMultipartField("image", self.jpeg)]
                ),
            )
            with patch.object(handler, "_call_face_identify", side_effect=fake_call):
                with patch.object(
                    handler,
                    "_verify_auth_claims",
                    return_value=(
                        True,
                        {"device_id": "dev1", "account_id": "2062102710978256898"},
                    ),
                ):
                    with patch(
                        "core.api.vision_handler.is_valid_image_file", return_value=True
                    ):
                        resp = await handler.handle_identify(req)
                        self.assertEqual(resp.status, 200)
                        body = json.loads(resp.text)
                        self.assertEqual(body["status"], "known")
                        self.assertEqual(captured["account_id"], "2062102710978256898")

        _run(run())

    def test_empty_gallery_returns_no_content(self):
        async def run():
            with patch.object(
                self.handler,
                "_call_face_identify",
                AsyncMock(return_value={"status": "empty", "confidence": 0.0}),
            ):
                with patch.object(
                    self.handler,
                    "_verify_auth_claims",
                    return_value=(True, {"device_id": "dev1", "account_id": "acct_test"}),
                ):
                    req = FakeRequest(
                        headers={"Device-Id": "dev1", "Authorization": "Bearer x"},
                        multipart=FakeMultipartReader(
                            [FakeMultipartField("image", self.jpeg)]
                        ),
                    )
                    with patch(
                        "core.api.vision_handler.is_valid_image_file", return_value=True
                    ):
                        resp = await self.handler.handle_identify(req)
                        body = json.loads(resp.text)
                        self.assertEqual(resp.status, 200)
                        self.assertEqual(body["status"], "empty")
                        self.assertEqual(body["reason"], "no_content")
                        self.assertIn("还没有录入", body.get("message") or "")
                        self.assertNotIn("user_id", body)
                        self.assertNotIn("display_name", body)

        _run(run())

    def test_below_identity_threshold_becomes_unknown(self):
        async def run():
            class FakeResp:
                status = 200

                async def json(self):
                    # face-api 若误返回 known+0.50，主控必须降为 unknown
                    return {
                        "status": "known",
                        "user_id": "usr_112233",
                        "name": "小李",
                        "confidence": 0.50,
                    }

                async def __aenter__(self):
                    return self

                async def __aexit__(self, *a):
                    return False

            class FakeSession:
                def __init__(self, *a, **k):
                    pass

                async def __aenter__(self):
                    return self

                async def __aexit__(self, *a):
                    return False

                def post(self, *a, **k):
                    return FakeResp()

            with patch("aiohttp.ClientSession", FakeSession):
                result = await self.handler._call_face_identify(self.jpeg, "dev1")
                self.assertEqual(result["status"], "unknown")
                self.assertNotIn("user_id", result)
                self.assertNotIn("display_name", result)

        _run(run())

    def test_at_identity_threshold_known(self):
        async def run():
            class FakeResp:
                status = 200

                async def json(self):
                    return {
                        "status": "known",
                        "user_id": "usr_112233",
                        "name": "小李",
                        "confidence": 0.80,
                    }

                async def __aenter__(self):
                    return self

                async def __aexit__(self, *a):
                    return False

            class FakeSession:
                def __init__(self, *a, **k):
                    pass

                async def __aenter__(self):
                    return self

                async def __aexit__(self, *a):
                    return False

                def post(self, *a, **k):
                    return FakeResp()

            with patch("aiohttp.ClientSession", FakeSession):
                with patch("core.utils.vllm.create_instance") as create_vllm:
                    result = await self.handler._call_face_identify(self.jpeg, "dev1")
                    create_vllm.assert_not_called()
                    self.assertEqual(result["status"], "known")
                    self.assertEqual(result["user_id"], "usr_112233")
                    self.assertEqual(result["display_name"], "小李")

        _run(run())

    def test_call_face_identify_does_not_touch_vllm(self):
        async def run():
            class FakeResp:
                status = 200

                async def json(self):
                    return {
                        "status": "known",
                        "user_id": "usr_112233",
                        "name": "小李",
                        "confidence": 0.88,
                    }

                async def __aenter__(self):
                    return self

                async def __aexit__(self, *a):
                    return False

            class FakeSession:
                def __init__(self, *a, **k):
                    pass

                async def __aenter__(self):
                    return self

                async def __aexit__(self, *a):
                    return False

                def post(self, *a, **k):
                    return FakeResp()

            with patch("aiohttp.ClientSession", FakeSession):
                with patch("core.utils.vllm.create_instance") as create_vllm:
                    result = await self.handler._call_face_identify(self.jpeg, "dev1")
                    create_vllm.assert_not_called()
                    self.assertEqual(result["status"], "known")

        _run(run())


class VisionAuthRejectLogTests(unittest.TestCase):
    """精确拒绝日志：对外仍 permission_denied，对内区分 mismatch 码。"""

    def setUp(self):
        self.config = {
            "server": {
                "auth_key": "test-auth-key-for-vision",
                "face": {
                    "enabled": True,
                    "identify_url": "http://127.0.0.1:9/face/identify",
                    "jwt_secret": "x" * 32,
                    "account_id": "",
                    "account_mode": "multi_tenant",
                    "allow_legacy_vision_tokens": True,
                },
            }
        }
        self.handler = VisionHandler(self.config)

    def test_device_mismatch_logs_precise_code_keeps_client_permission_denied(self):
        from core.api.vision_handler import VisionRequestError

        req = FakeRequest(
            path="/mcp/vision/explain",
            headers={
                "Device-Id": "dev-other",
                "Authorization": "Bearer x",
                "Client-Id": "corr-device-1",
            },
        )
        with patch.object(
            self.handler,
            "_verify_auth_claims",
            return_value=(True, {"device_id": "dev1", "account_id": "acct_a", "scope": "vision"}),
        ):
            with patch.object(self.handler, "_log_vision_auth_reject") as log_reject:
                with self.assertRaises(VisionRequestError) as ctx:
                    self.handler._authorize_vision(req)
        self.assertEqual(ctx.exception.status, 403)
        self.assertEqual(ctx.exception.reason, "permission_denied")
        self.assertEqual(ctx.exception.reject_code, "device_mismatch")
        self.assertTrue(log_reject.called)
        self.assertEqual(log_reject.call_args.args[1], "device_mismatch")
        self.assertEqual(self.handler._vision_endpoint(req), "/mcp/vision/explain")
        self.assertEqual(self.handler._vision_correlation_id(req), "corr-device-1")

    def test_scope_mismatch_logs_precise_code(self):
        from core.api.vision_handler import VisionRequestError

        req = FakeRequest(
            path="/mcp/vision/explain",
            headers={"Device-Id": "dev1", "Authorization": "Bearer x", "Client-Id": "corr-scope"},
        )
        self.config["server"]["face"]["allow_legacy_vision_tokens"] = False
        handler = VisionHandler(self.config)
        with patch.object(
            handler,
            "_verify_auth_claims",
            return_value=(True, {"device_id": "dev1", "account_id": "acct_a", "scope": "other"}),
        ):
            with patch.object(handler, "_log_vision_auth_reject") as log_reject:
                with self.assertRaises(VisionRequestError) as ctx:
                    handler._authorize_vision(req)
        self.assertEqual(ctx.exception.reject_code, "scope_mismatch")
        self.assertEqual(ctx.exception.reason, "permission_denied")
        self.assertEqual(log_reject.call_args.args[1], "scope_mismatch")

    def test_account_mismatch_logs_precise_code(self):
        from core.api.vision_handler import VisionRequestError

        self.config["server"]["face"]["account_mode"] = "single_tenant"
        self.config["server"]["face"]["account_id"] = "acct_cfg"
        handler = VisionHandler(self.config)
        req = FakeRequest(
            path="/mcp/vision/identify",
            headers={"Device-Id": "dev1", "Authorization": "Bearer x", "Client-Id": "corr-acct"},
        )
        with patch.object(
            handler,
            "_verify_auth_claims",
            return_value=(True, {"device_id": "dev1", "account_id": "acct_other", "scope": "vision"}),
        ):
            with patch.object(handler, "_log_vision_auth_reject") as log_reject:
                with self.assertRaises(VisionRequestError) as ctx:
                    handler._authorize_vision(req)
        self.assertEqual(ctx.exception.reject_code, "account_mismatch")
        self.assertEqual(log_reject.call_args.args[1], "account_mismatch")

    def test_session_mismatch_logs_precise_code(self):
        from core.api.vision_handler import VisionRequestError

        req = FakeRequest(
            path="/mcp/vision/explain",
            headers={
                "Device-Id": "dev1",
                "Authorization": "Bearer x",
                "Session-Id": "sess-header",
                "Client-Id": "corr-sess",
            },
        )
        with patch.object(
            self.handler,
            "_verify_auth_claims",
            return_value=(
                True,
                {
                    "device_id": "dev1",
                    "account_id": "acct_a",
                    "scope": "vision",
                    "session_id": "sess-token",
                },
            ),
        ):
            with patch.object(self.handler, "_log_vision_auth_reject") as log_reject:
                with self.assertRaises(VisionRequestError) as ctx:
                    self.handler._authorize_vision(req)
        self.assertEqual(ctx.exception.reject_code, "session_mismatch")
        self.assertEqual(log_reject.call_args.args[1], "session_mismatch")
        kwargs = log_reject.call_args.kwargs
        self.assertIs(kwargs.get("session_consistent"), False)
        self.assertTrue(kwargs.get("token_session_present"))
        self.assertTrue(kwargs.get("header_session_present"))

    def test_log_line_omits_secrets(self):
        req = FakeRequest(
            path="/mcp/vision/explain",
            headers={"Client-Id": "corr-1", "Authorization": "Bearer SUPERSECRET"},
        )
        with patch.object(self.handler.logger, "bind") as bind_mock:
            logger = bind_mock.return_value
            self.handler._log_vision_auth_reject(
                req,
                "session_mismatch",
                session_consistent=False,
                token_session_present=True,
                header_session_present=True,
            )
            msg = logger.warning.call_args.args[0]
        self.assertIn("reject=session_mismatch", msg)
        self.assertIn("endpoint=/mcp/vision/explain", msg)
        self.assertIn("correlation_id=corr-1", msg)
        self.assertIn("session_consistent=0", msg)
        self.assertNotIn("SUPERSECRET", msg)
        self.assertNotIn("Bearer", msg)


class FaceEnrollmentGuardTests(unittest.TestCase):
    def test_register_blocked(self):
        from core.utils.face_enrollment_guard import maybe_intercept_face_enrollment_tool

        for name in (
            "camera.face.register",
            "camera_face_register",
            "self.camera.face.register",
        ):
            r = maybe_intercept_face_enrollment_tool(name, {"name": "小王"})
            self.assertIsNotNone(r)
            self.assertIn("管理网页", r.response)

    def test_delete_blocked(self):
        from core.utils.face_enrollment_guard import maybe_intercept_face_enrollment_tool

        r = maybe_intercept_face_enrollment_tool("camera.face.delete", {"name": "小王"})
        self.assertIsNotNone(r)
        self.assertIn("禁止", r.response)

    def test_other_camera_ok(self):
        from core.utils.face_enrollment_guard import maybe_intercept_face_enrollment_tool

        self.assertIsNone(maybe_intercept_face_enrollment_tool("camera.open", {}))


if __name__ == "__main__":
    unittest.main()
