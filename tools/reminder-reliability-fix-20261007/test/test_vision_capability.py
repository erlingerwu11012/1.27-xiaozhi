"""MCP vision capabilities：HTTPS identity_url / token 合约测试。"""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.utils.auth import AuthToken
from core.utils.vision_capability import (
    build_vision_capabilities,
    resolve_vision_urls,
    validate_public_https_url,
)


class TestVisionCapability(unittest.TestCase):
    def test_https_ok_same_host(self):
        ok, reason = validate_public_https_url(
            "https://public.example.com/mcp/vision/identify"
        )
        self.assertTrue(ok, reason)

    def test_http_rejected(self):
        ok, reason = validate_public_https_url(
            "http://public.example.com/mcp/vision/identify"
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "not_https")

    def test_localhost_rejected(self):
        ok, reason = validate_public_https_url(
            "https://127.0.0.1/mcp/vision/identify"
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "blocked_host")

    def test_host_mismatch_rejected(self):
        explain, identity, reason = resolve_vision_urls(
            {
                "server": {
                    "vision_explain": "https://a.example.com/mcp/vision/explain",
                    "vision_identity": "https://b.example.com/mcp/vision/identify",
                }
            }
        )
        self.assertIsNone(explain)
        self.assertIsNone(identity)
        self.assertIn("host_mismatch", reason)

    def test_public_base_generates_both(self):
        explain, identity, reason = resolve_vision_urls(
            {
                "server": {
                    "public_base_url": "https://public.example.com",
                    "vision_explain": "",
                    "vision_identity": "",
                }
            }
        )
        self.assertEqual(reason, "ok")
        self.assertEqual(explain, "https://public.example.com/mcp/vision/explain")
        self.assertEqual(identity, "https://public.example.com/mcp/vision/identify")

    def test_no_splice_from_explain_alone(self):
        explain, identity, reason = resolve_vision_urls(
            {
                "server": {
                    "vision_explain": "https://public.example.com/mcp/vision/explain",
                    "vision_identity": "",
                    "public_base_url": "",
                }
            }
        )
        self.assertIsNone(identity)
        self.assertEqual(reason, "vision_identity_unconfigured")

    def test_build_fail_closed_no_account(self):
        cfg = {
            "server": {
                "auth_key": "k" * 32,
                "public_base_url": "https://public.example.com",
                "face": {},
            }
        }
        cap = build_vision_capabilities(cfg, device_id="dev1", account_id="")
        self.assertFalse(cap.ok)
        self.assertEqual(cap.reason, "account_id_missing")
        self.assertIsNone(cap.vision)

    def test_build_issues_identity_and_token_claims(self):
        cfg = {
            "server": {
                "auth_key": "unit-test-auth-key-32bytes!!",
                "public_base_url": "https://public.example.com",
                "face": {"account_id": "acct_a"},
            }
        }
        cap = build_vision_capabilities(
            cfg, device_id="aa:bb:cc", account_id="acct_a", session_id="sess1"
        )
        self.assertTrue(cap.ok, cap.reason)
        vision = cap.vision
        self.assertEqual(
            vision["identity_url"],
            "https://public.example.com/mcp/vision/identify",
        )
        self.assertEqual(
            vision["url"], "https://public.example.com/mcp/vision/explain"
        )
        self.assertIn("expires_at", vision)
        token = vision["token"]
        # 不在断言消息中打印 token
        self.assertTrue(isinstance(token, str) and len(token) > 20)
        auth = AuthToken(cfg["server"]["auth_key"])
        ok, claims = auth.verify_token_claims(token)
        self.assertTrue(ok)
        self.assertEqual(claims["device_id"], "aa:bb:cc")
        self.assertEqual(claims["account_id"], "acct_a")
        self.assertEqual(claims["scope"], "vision")

    def test_logs_do_not_contain_token(self):
        cfg = {
            "server": {
                "auth_key": "unit-test-auth-key-32bytes!!",
                "public_base_url": "https://public.example.com",
                "face": {"account_id": "acct_a"},
            }
        }
        with patch("core.utils.vision_capability.logger") as mock_logger:
            bind = MagicMock()
            mock_logger.bind.return_value = bind
            cap = build_vision_capabilities(
                cfg, device_id="aa:bb:cc", account_id="acct_a"
            )
            self.assertTrue(cap.ok)
            # 检查 info 调用参数不含 token 字符串
            for call in bind.info.call_args_list:
                msg = str(call)
                self.assertNotIn(cap.vision["token"], msg)


class TestIdentifyAccountMismatch(unittest.IsolatedAsyncioTestCase):
    async def test_token_account_mismatch_forbidden(self):
        from core.api.vision_handler import VisionHandler

        cfg = {
            "server": {
                "auth_key": "unit-test-auth-key-32bytes!!",
                "face": {
                    "enabled": True,
                    "account_id": "acct_a",
                    "identify_url": "http://face.test/face/identify",
                    "jwt_secret": "face-secret",
                    "identity_match_threshold": 0.80,
                },
            }
        }
        handler = VisionHandler(cfg)
        auth = AuthToken(cfg["server"]["auth_key"])
        token = auth.generate_token(
            "dev-1", account_id="acct_B", scope="vision"
        )

        class Req:
            method = "POST"
            headers = {
                "Authorization": f"Bearer {token}",
                "Device-Id": "dev-1",
            }

            async def multipart(self):
                raise AssertionError("should not read body on 401")

        resp = await handler.handle_identify(Req())
        self.assertEqual(resp.status, 403)


if __name__ == "__main__":
    unittest.main()
