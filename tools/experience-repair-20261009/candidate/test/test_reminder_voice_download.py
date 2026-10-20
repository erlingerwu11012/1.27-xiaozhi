"""Reminder Voice HTTPS 下载：Device-Id 头绑定与独立签名密钥。"""

from __future__ import annotations

import io
import json
import os
import sys
import time
import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from core.api.reminder_voice_handler import ReminderVoiceHandler
from core.utils.reminder_voice_store import (
    ReminderVoiceStore,
    build_signed_url,
    can_issue_reminder_voice_urls,
    get_reminder_voice_signing_key,
    get_voice_store,
    redact_asset_id,
    validate_reminder_voice_signing_at_startup,
)


def _ogg(n: int = 64) -> bytes:
    return (b"OggS" + b"\x00" * max(0, n - 4))[:n]


class ReminderVoiceDownloadTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.signing = "rv-download-sign-key-independent"
        self.config = {
            "server": {
                "auth_key": "must-not-reuse-as-signing",
                "public_base_url": "https://public.example.com",
                "reminder_voice_signing_key": self.signing,
                "face": {
                    "account_id": "acct_a",
                    "jwt_secret": "face-jwt-must-not-reuse",
                },
            }
        }
        # 使用隔离 store
        self.store = ReminderVoiceStore(ttl_sec=120)
        self.asset = self.store.put(
            _ogg(120), device_id="aa:bb:cc:dd:ee:ff", account_id="acct_a"
        )
        self.url, self.exp = build_signed_url(
            public_base_url="https://public.example.com",
            secret=self.signing,
            asset_id=self.asset.asset_id,
            device_id="aa:bb:cc:dd:ee:ff",
            ttl_sec=120,
        )
        self.q = parse_qs(urlparse(self.url).query)

    async def _client(self):
        handler = ReminderVoiceHandler(self.config)

        async def get_asset(request):
            with patch(
                "core.api.reminder_voice_handler.get_voice_store",
                return_value=self.store,
            ):
                return await handler.handle_get(request)

        app = web.Application()
        app.router.add_get("/reminder-voice/{asset_id}", get_asset)
        server = TestServer(app)
        client = TestClient(server)
        await client.start_server()
        return client

    async def test_ok_with_device_id_header(self):
        client = await self._client()
        try:
            resp = await client.get(
                f"/reminder-voice/{self.asset.asset_id}",
                params={
                    "exp": self.q["exp"][0],
                    "device_id": self.q["device_id"][0],
                    "sig": self.q["sig"][0],
                },
                headers={"Device-Id": "aa:bb:cc:dd:ee:ff"},
            )
            self.assertEqual(resp.status, 200)
            body = await resp.read()
            self.assertTrue(body.startswith(b"OggS"))
            self.assertEqual(len(body), 120)
        finally:
            await client.close()

    async def test_esp32s3_http_client_can_download(self):
        """模拟 ESP32-S3 esp_http_client：HTTP/1.1 + Device-Id + 短 UA。"""
        client = await self._client()
        try:
            resp = await client.get(
                f"/reminder-voice/{self.asset.asset_id}",
                params={
                    "exp": self.q["exp"][0],
                    "device_id": self.q["device_id"][0],
                    "sig": self.q["sig"][0],
                },
                headers={
                    "Device-Id": "aa:bb:cc:dd:ee:ff",
                    "User-Agent": "ESP32 HTTP Client",
                    "Connection": "close",
                    "Accept": "*/*",
                },
            )
            self.assertEqual(resp.status, 200)
            self.assertEqual(resp.content_type, "audio/ogg")
            body = await resp.read()
            self.assertTrue(body.startswith(b"OggS"))
            self.assertEqual(len(body), 120)
            self.assertEqual(resp.headers.get("Cache-Control"), "no-store")
        finally:
            await client.close()

    async def test_esp32_lowercase_device_id_header(self):
        client = await self._client()
        try:
            resp = await client.get(
                f"/reminder-voice/{self.asset.asset_id}",
                params={
                    "exp": self.q["exp"][0],
                    "device_id": self.q["device_id"][0],
                    "sig": self.q["sig"][0],
                },
                headers={
                    "device-id": "aa:bb:cc:dd:ee:ff",
                    "User-Agent": "ESP32 HTTP Client",
                },
            )
            self.assertEqual(resp.status, 200)
            body = await resp.read()
            self.assertTrue(body.startswith(b"OggS"))
        finally:
            await client.close()

    async def test_missing_device_id_header(self):
        client = await self._client()
        try:
            resp = await client.get(
                f"/reminder-voice/{self.asset.asset_id}",
                params={
                    "exp": self.q["exp"][0],
                    "device_id": self.q["device_id"][0],
                    "sig": self.q["sig"][0],
                },
            )
            self.assertIn(resp.status, (401, 403))
        finally:
            await client.close()

    async def test_wrong_device_id_header(self):
        client = await self._client()
        try:
            resp = await client.get(
                f"/reminder-voice/{self.asset.asset_id}",
                params={
                    "exp": self.q["exp"][0],
                    "device_id": self.q["device_id"][0],
                    "sig": self.q["sig"][0],
                },
                headers={"Device-Id": "11:22:33:44:55:66"},
            )
            self.assertIn(resp.status, (401, 403))
        finally:
            await client.close()

    async def test_tampered_signature(self):
        client = await self._client()
        try:
            resp = await client.get(
                f"/reminder-voice/{self.asset.asset_id}",
                params={
                    "exp": self.q["exp"][0],
                    "device_id": self.q["device_id"][0],
                    "sig": "0" * 64,
                },
                headers={"Device-Id": "aa:bb:cc:dd:ee:ff"},
            )
            self.assertEqual(resp.status, 403)
        finally:
            await client.close()

    async def test_tampered_expiry(self):
        client = await self._client()
        try:
            resp = await client.get(
                f"/reminder-voice/{self.asset.asset_id}",
                params={
                    "exp": str(int(self.q["exp"][0]) + 99999),
                    "device_id": self.q["device_id"][0],
                    "sig": self.q["sig"][0],
                },
                headers={"Device-Id": "aa:bb:cc:dd:ee:ff"},
            )
            self.assertEqual(resp.status, 403)
        finally:
            await client.close()

    async def test_expired(self):
        # 用已过期 exp 重新签名
        past = int(time.time()) - 30
        from core.utils.reminder_voice_store import _sign

        sig = _sign(self.signing, self.asset.asset_id, "aa:bb:cc:dd:ee:ff", past)
        client = await self._client()
        try:
            resp = await client.get(
                f"/reminder-voice/{self.asset.asset_id}",
                params={
                    "exp": str(past),
                    "device_id": "aa:bb:cc:dd:ee:ff",
                    "sig": sig,
                },
                headers={"Device-Id": "aa:bb:cc:dd:ee:ff"},
            )
            self.assertEqual(resp.status, 403)
        finally:
            await client.close()

    async def test_leaked_url_without_header_denied(self):
        """仅凭完整签名 URL、无 Device-Id 头不得下载。"""
        client = await self._client()
        try:
            resp = await client.get(
                f"/reminder-voice/{self.asset.asset_id}?exp={self.q['exp'][0]}"
                f"&device_id={self.q['device_id'][0]}&sig={self.q['sig'][0]}"
            )
            self.assertEqual(resp.status, 401)
        finally:
            await client.close()

    def test_no_fallback_to_auth_or_face_key(self):
        cfg = {
            "server": {
                "auth_key": "shared-auth",
                "reminder_voice_signing_key": "shared-auth",  # 故意等同 auth
                "face": {"jwt_secret": "face-secret"},
            }
        }
        self.assertEqual(get_reminder_voice_signing_key(cfg), "")
        cfg2 = {
            "server": {
                "auth_key": "auth-only",
                "reminder_voice_signing_key": "face-secret",
                "face": {"jwt_secret": "face-secret"},
            }
        }
        self.assertEqual(get_reminder_voice_signing_key(cfg2), "")
        ok, reason = can_issue_reminder_voice_urls(
            {
                "server": {
                    "public_base_url": "https://public.example.com",
                    "auth_key": "x",
                    # 无独立密钥
                }
            }
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "signing_key_missing")

    def test_startup_prod_fail_closed(self):
        cfg = {
            "server": {
                "public_base_url": "https://public.example.com",
                "auth_key": "a",
            }
        }
        with patch.dict(os.environ, {"XIAOZHI_ENV": "production"}, clear=False):
            # 清掉可能存在的 env signing key
            env = {k: v for k, v in os.environ.items() if k != "REMINDER_VOICE_SIGNING_KEY"}
            env["XIAOZHI_ENV"] = "production"
            with patch.dict(os.environ, env, clear=True):
                with self.assertRaises(RuntimeError):
                    validate_reminder_voice_signing_at_startup(cfg)

    async def test_reject_log_has_no_query_or_token(self):
        logs = []

        class Bind:
            def warning(self, msg):
                logs.append(msg)

            def info(self, msg):
                logs.append(msg)

            def error(self, msg):
                logs.append(msg)

        handler = ReminderVoiceHandler(self.config)

        class FakeReq:
            pass

        req = FakeReq()
        req.match_info = {"asset_id": self.asset.asset_id}
        req.headers = {}
        req.rel_url = MagicMock()
        req.rel_url.query = {
            "exp": self.q["exp"][0],
            "device_id": self.q["device_id"][0],
            "sig": self.q["sig"][0],
        }

        with patch("core.api.reminder_voice_handler.logger") as mock_logger:
            mock_logger.bind.return_value = Bind()
            with patch(
                "core.api.reminder_voice_handler.get_voice_store",
                return_value=self.store,
            ):
                resp = await handler.handle_get(req)
                self.assertEqual(resp.status, 401)
        blob = "\n".join(logs)
        self.assertNotIn(self.q["sig"][0], blob)
        self.assertNotIn("exp=", blob)
        self.assertNotIn(self.signing, blob)
        self.assertIn("missing_device_id_header", blob)
        self.assertIn(redact_asset_id(self.asset.asset_id), blob)


if __name__ == "__main__":
    unittest.main()
