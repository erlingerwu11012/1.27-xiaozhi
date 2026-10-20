"""core.utils.service_auth 单测（不依赖完整 app 启动路径）。"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.utils import service_auth


class ServiceAuthUnitTests(unittest.TestCase):
    def test_ok_compare_digest(self):
        self.assertTrue(
            service_auth.verify_bearer_service_secret("s3cret", "s3cret")
        )

    def test_missing_presented(self):
        self.assertFalse(service_auth.verify_bearer_service_secret("", "s3cret"))

    def test_mismatch(self):
        self.assertFalse(service_auth.verify_bearer_service_secret("a", "b"))
        self.assertFalse(
            service_auth.verify_bearer_service_secret("short", "longer-secret")
        )

    def test_placeholder_rejected(self):
        secret, reason = service_auth.get_service_secret(
            {"manager-api": {"secret": "你的密钥"}}
        )
        self.assertEqual(secret, "")
        self.assertEqual(reason, "secret_unconfigured")

    def test_no_fallback_to_server_auth_key_or_secret(self):
        secret, reason = service_auth.get_service_secret(
            {
                "manager-api": {},
                "server": {"auth_key": "ak", "secret": "ss"},
            }
        )
        self.assertEqual(secret, "")
        self.assertEqual(reason, "secret_unconfigured")

    def test_extract_bearer(self):
        self.assertEqual(
            service_auth.extract_bearer_token("Bearer abc"),
            "abc",
        )
        self.assertEqual(service_auth.extract_bearer_token(""), "")
        self.assertEqual(service_auth.extract_bearer_token("Basic x"), "")


if __name__ == "__main__":
    unittest.main()
