"""Reminder Control WSS：鉴权、白名单、capability、签名与隔离。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from local_active_test_util import FakeMainHost, bind_local_active_registry, make_integrated_server, wait_bounded, cancel_tasks

from core.auth import AuthManager, AuthenticationError, TokenClaims
from core.reminder_control import (
    ReminderControlContext,
    ReminderControlManager,
    authenticate_reminder_control,
    handle_reminder_control_connection,
    is_reminder_control_path,
)
from core.utils.reminder_control_capability import (
    build_reminder_control_capability,
    resolve_reminder_control_url,
    validate_public_wss_url,
)
from core.utils.reminder_voice import (
    _reset_inflight_for_tests,
    process_reminder_voice_request,
    validate_reminder_voice_request,
)
from core.utils.reminder_voice_store import (
    ReminderVoiceStore,
    build_signed_url,
    get_reminder_voice_signing_key,
    verify_signed_request,
)
from core.utils.recipient_resolver import ProfileDirectory, ProfileRecord
from core.providers.tools.device_mcp.mcp_handler import send_mcp_initialize_message


def _ogg(n=80):
    return b"OggS" + b"\x00" * (n - 4)



def _enable_local_outbound(conn, manager=None):
    """单元测试：local_active 经受控注册表 + guarded_ws_send。"""
    from local_active_test_util import bind_local_active_registry

    bind_local_active_registry(conn, manager)
    return conn


class FakeWS:
    def __init__(self, path="/reminder-control", headers=None):
        self.request = MagicMock()
        self.request.path = path
        self.request.headers = headers or {}
        self.sent = []
        self.closed_code = None
        self.closed_reason = None
        self._queue = asyncio.Queue()
        self._closed = False

    async def send(self, data):
        if self._closed:
            raise RuntimeError("closed")
        self.sent.append(data)

    async def recv(self):
        item = await self._queue.get()
        if isinstance(item, Exception):
            raise item
        return item

    async def close(self, code=1000, reason=""):
        self._closed = True
        self.closed_code = code
        self.closed_reason = reason

    def push(self, msg):
        self._queue.put_nowait(msg)


class TestCapability(unittest.TestCase):
    def test_wss_ok(self):
        ok, reason = validate_public_wss_url(
            "wss://public.example.com/reminder-control"
        )
        self.assertTrue(ok, reason)

    def test_ws_rejected(self):
        ok, reason = validate_public_wss_url(
            "ws://public.example.com/reminder-control"
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "not_wss")

    def test_localhost_rejected(self):
        ok, reason = validate_public_wss_url(
            "wss://127.0.0.1/reminder-control"
        )
        self.assertFalse(ok)

    def test_host_mismatch_with_public_base(self):
        url, reason = resolve_reminder_control_url(
            {
                "server": {
                    "public_base_url": "https://a.example.com",
                    "reminder_control_url": "wss://b.example.com/reminder-control",
                }
            }
        )
        self.assertIsNone(url)
        self.assertIn("host_mismatch", reason)

    def test_build_from_public_base(self):
        cap = build_reminder_control_capability(
            {"server": {"public_base_url": "https://public.example.com"}}
        )
        self.assertTrue(cap.ok, cap.reason)
        self.assertEqual(
            cap.capability["url"], "wss://public.example.com/reminder-control"
        )
        self.assertEqual(cap.capability["protocol_version"], 1)

    def test_mcp_initialize_includes_reminder_control(self):
        async def _run():
            sent = []

            class Conn:
                config = {
                    "server": {
                        "auth_key": "k" * 32,
                        "public_base_url": "https://public.example.com",
                        "vision_explain": "https://public.example.com/mcp/vision/explain",
                        "vision_identity": "https://public.example.com/mcp/vision/identify",
                        "face": {"account_id": "acct_a"},
                        "face_enrollment_upload_signing_key": "independent-signing-key-0123456789abcdef",
                    }
                }
                headers = {"device-id": "dev1"}
                device_id = "dev1"
                session_id = "s1"
                features = {"mcp": True}
                websocket = MagicMock()
                outbound_mode = None
                superseded = False
                _outbound_closed = False
                face_account_id = None
                device_user_id = None
                account_id = None
                stop_event = None
                server = MagicMock()
                server.is_current_connection = MagicMock(return_value=True)

                async def _send(msg):
                    sent.append(json.loads(msg) if isinstance(msg, str) else msg)

            conn = Conn()
            with patch(
                "core.providers.tools.device_mcp.mcp_handler.send_mcp_message",
                new=AsyncMock(side_effect=lambda c, p: sent.append(p)),
            ):
                await send_mcp_initialize_message(conn)
            self.assertTrue(sent)
            caps = sent[0]["params"]["capabilities"]
            self.assertIn("reminder_control", caps)
            self.assertTrue(
                caps["reminder_control"]["url"].startswith("wss://public.example.com/")
            )
            # 不下发密钥
            blob = json.dumps(caps)
            self.assertNotIn("signing", blob.lower())
            self.assertNotIn("secret", blob.lower())

        asyncio.run(_run())

    def test_mcp_no_capability_on_ws(self):
        async def _run():
            sent = []

            class Conn:
                config = {
                    "server": {
                        "auth_key": "k" * 32,
                        "public_base_url": "http://public.example.com",
                        "face": {"account_id": "acct_a"},
                    }
                }
                headers = {"device-id": "dev1"}
                device_id = "dev1"
                session_id = "s1"
                features = {"mcp": True}
                outbound_mode = None
                superseded = False
                _outbound_closed = False
                face_account_id = None
                device_user_id = None
                account_id = None
                stop_event = None
                server = MagicMock()
                server.is_current_connection = MagicMock(return_value=True)
                websocket = MagicMock()

            with patch(
                "core.providers.tools.device_mcp.mcp_handler.send_mcp_message",
                new=AsyncMock(side_effect=lambda c, p: sent.append(p)),
            ):
                await send_mcp_initialize_message(Conn())
            caps = sent[0]["params"]["capabilities"]
            self.assertNotIn("reminder_control", caps)

        asyncio.run(_run())


class TestAuthAndWhitelist(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.auth = AuthManager(secret_key="pair-secret", expire_seconds=86400)
        self.config = {
            "server": {
                "auth_key": "pair-secret",
                "face": {"account_id": "acct_a"},
            }
        }

    def _auth_ok_patches(self):
        claims = TokenClaims(
            version="v1", device_id="dev-1", iat=1, exp=9999999999
        )
        return (
            patch(
                "core.handle.connection_auth.verify_device_ws_token",
                new=AsyncMock(return_value=claims),
            ),
            patch.object(
                ReminderControlManager,
                "try_register",
                new=AsyncMock(return_value=True),
            ),
        )

    async def test_valid_device_auth(self):
        token = self.auth.generate_token("client-1", "dev-1")
        ws = FakeWS(
            headers={
                "device-id": "dev-1",
                "client-id": "client-1",
                "authorization": f"Bearer {token}",
            }
        )
        with self._auth_ok_patches()[0]:
            d, c, a = await authenticate_reminder_control(
                ws, self.config, self.auth, auth_enable=True, allowed_devices=set()
            )
        self.assertEqual(d, "dev-1")
        self.assertEqual(c, "client-1")
        self.assertEqual(a, "acct_a")

    async def test_missing_token_rejected(self):
        ws = FakeWS(headers={"device-id": "dev-1", "client-id": "client-1"})
        with self.assertRaises(AuthenticationError):
            await authenticate_reminder_control(
                ws, self.config, self.auth, auth_enable=True, allowed_devices=set()
            )

    async def test_wrong_device_id_rejected(self):
        token = self.auth.generate_token("client-1", "dev-1")
        ws = FakeWS(
            headers={
                "device-id": "dev-OTHER",
                "client-id": "client-1",
                "authorization": f"Bearer {token}",
            }
        )
        with self.assertRaises(AuthenticationError):
            await authenticate_reminder_control(
                ws, self.config, self.auth, auth_enable=True, allowed_devices=set()
            )

    async def test_missing_account_rejected(self):
        token = self.auth.generate_token("client-1", "dev-1")
        cfg = {"server": {"face": {"account_id": ""}}}
        ws = FakeWS(
            headers={
                "device-id": "dev-1",
                "client-id": "client-1",
                "authorization": f"Bearer {token}",
            }
        )
        with self.assertRaises(AuthenticationError):
            await authenticate_reminder_control(
                ws, cfg, self.auth, auth_enable=True, allowed_devices=set()
            )

    async def test_chat_message_closes(self):
        token = self.auth.generate_token("client-1", "dev-1")
        ws = FakeWS(
            headers={
                "device-id": "dev-1",
                "client-id": "client-1",
                "authorization": f"Bearer {token}",
            }
        )
        ws.push(json.dumps({"type": "listen", "state": "start"}))
        mgr = ReminderControlManager(max_per_device=2)
        auth_patch, reg_patch = self._auth_ok_patches()
        with auth_patch, reg_patch:
            await handle_reminder_control_connection(
                ws,
                config=self.config,
                auth_manager=self.auth,
                auth_enable=True,
                allowed_devices=set(),
                manager=mgr,
                idle_timeout_sec=2,
            )
        self.assertEqual(ws.closed_code, 1008)
        # 可能有 error 帧
        if ws.sent:
            err = json.loads(ws.sent[0])
            self.assertEqual(err["type"], "reminder_voice_error")

    async def test_binary_rejected(self):
        token = self.auth.generate_token("client-1", "dev-1")
        ws = FakeWS(
            headers={
                "device-id": "dev-1",
                "client-id": "client-1",
                "authorization": f"Bearer {token}",
            }
        )
        ws.push(b"\x00\x01audio")
        mgr = ReminderControlManager(max_per_device=2)
        auth_patch, reg_patch = self._auth_ok_patches()
        with auth_patch, reg_patch:
            await handle_reminder_control_connection(
                ws,
                config=self.config,
                auth_manager=self.auth,
                auth_enable=True,
                allowed_devices=set(),
                manager=mgr,
                idle_timeout_sec=2,
            )
        self.assertEqual(ws.closed_code, 1003)


class TestSigningAndPipeline(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _reset_inflight_for_tests()
        self.signing = "reminder-voice-sign-key-only"
        self.config = {
            "server": {
                "auth_key": "must-not-use-for-sign",
                "public_base_url": "https://public.example.com",
                "reminder_voice_signing_key": self.signing,
                "face": {"account_id": "acct_a"},
            }
        }

    def test_signing_key_not_auth_key(self):
        key = get_reminder_voice_signing_key(self.config)
        self.assertEqual(key, self.signing)
        self.assertNotEqual(key, self.config["server"]["auth_key"])

    def test_signed_url_binds_device_and_expiry(self):
        store = ReminderVoiceStore()
        asset = store.put(_ogg(), device_id="dev-1", account_id="acct_a")
        url, exp = build_signed_url(
            public_base_url="https://public.example.com",
            secret=self.signing,
            asset_id=asset.asset_id,
            device_id="dev-1",
            ttl_sec=60,
        )
        self.assertIn("device_id=dev-1", url)
        self.assertTrue(
            verify_signed_request(
                secret=self.signing,
                asset_id=asset.asset_id,
                device_id="dev-1",
                exp=str(exp),
                sig=url.split("sig=")[1],
                expected_device_id="dev-1",
            )
        )
        # 错 device
        self.assertFalse(
            verify_signed_request(
                secret=self.signing,
                asset_id=asset.asset_id,
                device_id="dev-OTHER",
                exp=str(exp),
                sig=url.split("sig=")[1],
                expected_device_id="dev-1",
            )
        )
        # 过期
        self.assertFalse(
            verify_signed_request(
                secret=self.signing,
                asset_id=asset.asset_id,
                device_id="dev-1",
                exp=str(int(time.time()) - 10),
                sig="00",
                expected_device_id="dev-1",
            )
        )

    async def test_recipient_inactive_rejected(self):
        sent = []

        class WS:
            async def send(self, s):
                sent.append(json.loads(s))

        conn = MagicMock()
        conn.device_id = "dev-1"
        conn.session_id = "s1"
        conn.account_id = "acct_a"
        conn.websocket = WS()
        conn.config = self.config
        conn._profile_directory = ProfileDirectory(
            account_id="acct_a",
            profiles=[
                ProfileRecord("usr_dead01", "旧人", "inactive", "acct_a"),
            ],
        )
        _enable_local_outbound(conn)
        await process_reminder_voice_request(
            conn,
            {
                "instance_id": "note:1:x",
                "revision": 1,
                "voice_revision": 1,
                "recipient_person_id": "usr_dead01",
                "presence_generation": 1,
                "source_type": "note",
                "title": "x",
                "detail": "y",
            },
            send_error_on_failure=True,
        )
        self.assertTrue(sent)
        self.assertEqual(sent[0]["type"], "reminder_voice_error")
        self.assertIn("recipient", sent[0]["code"])

    async def test_cross_account_recipient_rejected(self):
        sent = []

        class WS:
            async def send(self, s):
                sent.append(json.loads(s))

        conn = MagicMock()
        conn.device_id = "dev-1"
        conn.session_id = "s1"
        conn.account_id = "acct_a"
        conn.websocket = WS()
        conn.config = self.config
        conn._profile_directory = ProfileDirectory(
            account_id="acct_a",
            profiles=[ProfileRecord("usr_aaa111", "小明", "active", "acct_a")],
        )
        _enable_local_outbound(conn)
        await process_reminder_voice_request(
            conn,
            {
                "instance_id": "note:2:x",
                "revision": 1,
                "voice_revision": 1,
                "recipient_person_id": "usr_zzz999",
                "presence_generation": 1,
                "source_type": "note",
                "title": "x",
                "detail": "y",
            },
            send_error_on_failure=True,
        )
        self.assertEqual(sent[0]["type"], "reminder_voice_error")

    async def test_asset_only_to_same_connection(self):
        sent_a, sent_b = [], []

        class WSA:
            async def send(self, s):
                sent_a.append(json.loads(s))

        class WSB:
            async def send(self, s):
                sent_b.append(json.loads(s))

        def make_conn(ws):
            c = MagicMock()
            c.device_id = "dev-1"
            c.session_id = "s1"
            c.account_id = "acct_a"
            c.websocket = ws
            c.config = self.config
            c.llm = None
            c.tts = MagicMock()
            c._profile_directory = ProfileDirectory(
                account_id="acct_a",
                profiles=[
                    ProfileRecord("usr_abc123", "小明", "active", "acct_a"),
                ],
            )
            return _enable_local_outbound(c)

        conn = make_conn(WSA())
        other = make_conn(WSB())
        with patch(
            "core.utils.reminder_voice.generate_reminder_script",
            new=AsyncMock(return_value="提醒你，该处理这件事了。"),
        ), patch(
            "core.utils.reminder_voice.synthesize_ogg_opus",
            new=AsyncMock(return_value=_ogg(120)),
        ):
            await process_reminder_voice_request(
                conn,
                {
                    "instance_id": "note:7:xyz",
                    "revision": 4,
                    "voice_revision": 2,
                    "recipient_person_id": "usr_abc123",
                    "presence_generation": 18,
                    "source_type": "note",
                    "title": "事",
                    "detail": "细节",
                },
            )
        self.assertEqual(len(sent_a), 1)
        self.assertEqual(sent_a[0]["type"], "reminder_voice_asset")
        self.assertEqual(sent_b, [])
        self.assertTrue(sent_a[0]["url"].startswith("https://"))
        self.assertIn("device_id=dev-1", sent_a[0]["url"])

    async def test_tts_failure_no_fake_asset(self):
        sent = []

        class WS:
            async def send(self, s):
                sent.append(json.loads(s))

        conn = MagicMock()
        conn.device_id = "dev-1"
        conn.session_id = "s1"
        conn.account_id = "acct_a"
        conn.websocket = WS()
        conn.config = self.config
        conn._profile_directory = ProfileDirectory(
            account_id="acct_a",
            profiles=[ProfileRecord("usr_abc123", "小明", "active", "acct_a")],
        )
        _enable_local_outbound(conn)
        with patch(
            "core.utils.reminder_voice.generate_reminder_script",
            new=AsyncMock(return_value="提醒你，该处理这件事了。"),
        ), patch(
            "core.utils.reminder_voice.synthesize_ogg_opus",
            new=AsyncMock(side_effect=RuntimeError("tts_failed")),
        ):
            await process_reminder_voice_request(
                conn,
                {
                    "instance_id": "note:9:f",
                    "revision": 1,
                    "voice_revision": 1,
                    "recipient_person_id": "usr_abc123",
                    "presence_generation": 1,
                    "source_type": "note",
                    "title": "x",
                    "detail": "y",
                },
                send_error_on_failure=True,
            )
        self.assertTrue(all(m.get("type") != "reminder_voice_asset" for m in sent))
        self.assertTrue(any(m.get("type") == "reminder_voice_error" for m in sent))

    async def test_dedup(self):
        sent = []

        class WS:
            async def send(self, s):
                sent.append(json.loads(s))

        conn = MagicMock()
        conn.device_id = "dev-1"
        conn.session_id = "s1"
        conn.account_id = "acct_a"
        conn.websocket = WS()
        conn.config = self.config
        conn._profile_directory = ProfileDirectory(
            account_id="acct_a",
            profiles=[ProfileRecord("usr_abc123", "小明", "active", "acct_a")],
        )
        _enable_local_outbound(conn)
        msg = {
            "instance_id": "note:dedup:1",
            "revision": 1,
            "voice_revision": 3,
            "recipient_person_id": "usr_abc123",
            "presence_generation": 9,
            "source_type": "note",
            "phase": "due",
            "title": "x",
            "detail": "y",
        }
        gate = asyncio.Event()
        calls = {"n": 0}

        async def slow_tts(*a, **k):
            calls["n"] += 1
            await wait_bounded(
                gate.wait(),
                timeout=5.0,
                test_name="test_dedup",
                point="slow_tts gate.wait",
            )
            return _ogg(100)

        tasks = []
        try:
            with patch(
                "core.utils.reminder_voice.generate_reminder_script",
                new=AsyncMock(return_value="提醒你，该处理这件事了。"),
            ), patch(
                "core.utils.reminder_voice.synthesize_ogg_opus",
                new=slow_tts,
            ):
                t1 = asyncio.create_task(process_reminder_voice_request(conn, msg))
                t2 = asyncio.create_task(process_reminder_voice_request(conn, msg))
                tasks = [t1, t2]
                await asyncio.sleep(0.05)
                gate.set()
                await wait_bounded(
                    asyncio.gather(t1, t2),
                    timeout=10.0,
                    test_name="test_dedup",
                    point="gather voice requests",
                )
        finally:
            await cancel_tasks(tasks)
        self.assertEqual(calls["n"], 1)
        self.assertEqual(sum(1 for m in sent if m.get("type") == "reminder_voice_asset"), 1)

    def test_path_helper(self):
        self.assertTrue(is_reminder_control_path("/reminder-control"))
        self.assertTrue(is_reminder_control_path("/xiaozhi/reminder-control"))
        self.assertFalse(is_reminder_control_path("/xiaozhi/v1/"))

    def test_missing_recipient_invalid(self):
        ok, reason = validate_reminder_voice_request(
            {
                "instance_id": "note:1:a",
                "revision": 1,
                "voice_revision": 1,
                "presence_generation": 1,
                "source_type": "note",
            }
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "missing_recipient_person_id")


class BlockingFakeWS:
    """进入 send 后阻塞，直至 release。"""

    def __init__(self):
        self.sent = []
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def send(self, data):
        self.entered.set()
        await wait_bounded(
            self.release.wait(),
            timeout=5.0,
            test_name="BlockingFakeWS.send",
            point="release.wait",
        )
        self.sent.append(data)


class TestLocalActiveBlockingSendRace(unittest.IsolatedAsyncioTestCase):
    """RC send 与 RC register 同中心锁串行（含主连接代际绑定）。"""

    async def test_rc_register_waits_until_a1_send_completes(self):
        server = make_integrated_server()
        mgr = server._reminder_control_manager
        main_a1 = MagicMock()
        main_a1.session_id = "main-sess-a1"
        main_a1.superseded = False
        server._register_connection_unlocked("dev-a", main_a1)

        rc1 = ReminderControlContext(
            websocket=BlockingFakeWS(),
            config={},
            device_id="dev-a",
            client_id="c1",
            account_id="acct1",
        )
        rc1.session_id = "rc-sess-a1"
        mgr._register_connection_unlocked("dev-a", rc1)

        b_ws = FakeWS()
        rc_b = ReminderControlContext(
            websocket=b_ws,
            config={},
            device_id="dev-b",
            client_id="c1",
            account_id="acct1",
        )
        rc_b.session_id = "rc-sess-b"
        main_b = MagicMock()
        main_b.session_id = "main-sess-b"
        main_b.superseded = False
        server._register_connection_unlocked("dev-b", main_b)
        mgr._register_connection_unlocked("dev-b", rc_b)
        b_before = len(b_ws.sent)

        from core.utils.device_outbound import guarded_ws_send

        send_task = asyncio.create_task(
            guarded_ws_send(
                rc1,
                json.dumps({"type": "pong"}),
                command="pong",
                msg_type="pong",
            )
        )
        await asyncio.wait_for(rc1.websocket.entered.wait(), timeout=1.0)
        self.assertEqual(rc1.websocket.sent, [])

        rc2 = ReminderControlContext(
            websocket=FakeWS(),
            config={},
            device_id="dev-a",
            client_id="c1",
            account_id="acct1",
        )
        rc2.session_id = "rc-sess-a2"
        reg_task = asyncio.create_task(mgr.register_connection("dev-a", rc2))
        await asyncio.sleep(0.02)
        self.assertFalse(reg_task.done(), "RC2 register 须等待 RC1 send 完成")
        self.assertEqual(mgr._current_sessions.get("dev-a"), "rc-sess-a1")

        rc1.websocket.release.set()
        self.assertTrue(await send_task)
        await reg_task

        self.assertEqual(len(rc1.websocket.sent), 1)
        self.assertEqual(mgr._current_sessions.get("dev-a"), "rc-sess-a2")
        self.assertTrue(rc1.superseded)

        rc1_before = len(rc1.websocket.sent)
        rc2_before = len(rc2.websocket.sent)
        self.assertFalse(
            await guarded_ws_send(
                rc1, json.dumps({"type": "pong"}), command="pong", msg_type="pong"
            )
        )
        self.assertTrue(
            await guarded_ws_send(
                rc2, json.dumps({"type": "pong"}), command="pong", msg_type="pong"
            )
        )
        self.assertEqual(len(rc1.websocket.sent), rc1_before)
        self.assertEqual(len(rc2.websocket.sent), rc2_before + 1)
        self.assertEqual(len(b_ws.sent), b_before)

    async def test_rc_unregister_does_not_resurrect_old(self):
        server = make_integrated_server()
        mgr = server._reminder_control_manager
        main_a1 = MagicMock()
        main_a1.session_id = "main-sess-a1"
        main_a1.superseded = False
        server._register_connection_unlocked("dev-a", main_a1)

        rc1 = ReminderControlContext(
            websocket=FakeWS(),
            config={},
            device_id="dev-a",
            client_id="c1",
            account_id="acct1",
        )
        rc1.session_id = "rc-sess-a1"
        mgr._register_connection_unlocked("dev-a", rc1)

        rc2 = ReminderControlContext(
            websocket=FakeWS(),
            config={},
            device_id="dev-a",
            client_id="c1",
            account_id="acct1",
        )
        rc2.session_id = "rc-sess-a2"
        await mgr.register_connection("dev-a", rc2)
        self.assertEqual(mgr._current_sessions["dev-a"], "rc-sess-a2")

        await mgr.unregister_connection("dev-a", rc1)
        self.assertEqual(mgr._current_sessions.get("dev-a"), "rc-sess-a2")
        self.assertIn("rc-sess-a2", mgr._connections["dev-a"])

        await mgr.unregister_connection("dev-a", rc2)
        self.assertIsNone(mgr._current_sessions.get("dev-a"))
        from core.utils.device_outbound import guarded_ws_send

        self.assertFalse(
            await guarded_ws_send(
                rc1, json.dumps({"type": "pong"}), command="pong", msg_type="pong"
            )
        )
        self.assertEqual(rc1.websocket.sent, [])


class TestRcMainGenerationBinding(unittest.IsolatedAsyncioTestCase):
    """主连接代际与 RC parent 绑定：跨通道失效与共享中心锁。"""

    def _main_handler(self, device_id, session_id, server):
        h = MagicMock()
        h.device_id = device_id
        h.session_id = session_id
        h.superseded = False
        h.websocket = FakeWS()
        h.server = server
        h.stop_event = None
        h.tts = None
        return h

    async def test_main_a2_register_waits_rc1_send_then_invalidates_rc1(self):
        server = make_integrated_server()
        mgr = server._reminder_control_manager
        self.assertTrue(mgr.shares_device_lock_with(server))

        main_a1 = self._main_handler("dev-a", "main-sess-a1", server)
        server._register_connection_unlocked("dev-a", main_a1)

        rc1 = ReminderControlContext(
            websocket=BlockingFakeWS(),
            config={},
            device_id="dev-a",
            client_id="c1",
            account_id="acct1",
        )
        rc1.session_id = "rc-sess-a1"
        mgr._register_connection_unlocked("dev-a", rc1)
        self.assertEqual(rc1.parent_main_session_id, "main-sess-a1")

        from core.utils.device_outbound import guarded_ws_send

        send_task = asyncio.create_task(
            guarded_ws_send(rc1, json.dumps({"type": "pong"}), command="pong", msg_type="pong")
        )
        await asyncio.wait_for(rc1.websocket.entered.wait(), timeout=1.0)
        self.assertEqual(rc1.websocket.sent, [])

        main_a2 = self._main_handler("dev-a", "main-sess-a2", server)
        reg_task = asyncio.create_task(server.register_connection("dev-a", main_a2))
        await asyncio.sleep(0.02)
        self.assertFalse(reg_task.done(), "主 A2 register 须等待 RC1 send 完成")
        self.assertEqual(server.get_current_main_session_id("dev-a"), "main-sess-a1")

        rc1.websocket.release.set()
        self.assertTrue(await send_task)
        await wait_bounded(
            reg_task,
            timeout=5.0,
            test_name="test_main_a2_register_waits_rc1_send_then_invalidates_rc1",
            point="main_a2 register_connection",
        )

        self.assertEqual(len(rc1.websocket.sent), 1)
        self.assertEqual(server.get_current_main_session_id("dev-a"), "main-sess-a2")
        self.assertTrue(rc1.superseded)
        rc1_before = len(rc1.websocket.sent)
        self.assertFalse(
            await guarded_ws_send(rc1, json.dumps({"type": "pong"}), command="pong", msg_type="pong")
        )
        self.assertEqual(len(rc1.websocket.sent), rc1_before)

    async def test_stale_rc1_zero_send_after_main_a2(self):
        server = make_integrated_server()
        mgr = server._reminder_control_manager
        main_a1 = self._main_handler("dev-a", "main-sess-a1", server)
        server._register_connection_unlocked("dev-a", main_a1)
        rc1 = ReminderControlContext(
            websocket=FakeWS(),
            config={},
            device_id="dev-a",
            client_id="c1",
            account_id="acct1",
        )
        rc1.session_id = "rc-sess-a1"
        mgr._register_connection_unlocked("dev-a", rc1)

        main_a2 = self._main_handler("dev-a", "main-sess-a2", server)
        await server.register_connection("dev-a", main_a2)

        b_main = self._main_handler("dev-b", "main-sess-b", server)
        server._register_connection_unlocked("dev-b", b_main)
        rc_b = ReminderControlContext(
            websocket=FakeWS(),
            config={},
            device_id="dev-b",
            client_id="c1",
            account_id="acct1",
        )
        rc_b.session_id = "rc-sess-b"
        mgr._register_connection_unlocked("dev-b", rc_b)
        b_before = len(rc_b.websocket.sent)

        from core.utils.device_outbound import guarded_ws_send

        self.assertFalse(
            await guarded_ws_send(rc1, json.dumps({"type": "pong"}), command="pong", msg_type="pong")
        )
        self.assertEqual(rc1.websocket.sent, [])
        self.assertEqual(len(rc_b.websocket.sent), b_before)

    async def test_rc2_with_main_a2_survives_rc1_unregister(self):
        server = make_integrated_server()
        mgr = server._reminder_control_manager
        main_a2 = self._main_handler("dev-a", "main-sess-a2", server)
        await server.register_connection("dev-a", main_a2)

        rc1 = ReminderControlContext(
            websocket=FakeWS(),
            config={},
            device_id="dev-a",
            client_id="c1",
            account_id="acct1",
        )
        rc1.session_id = "rc-sess-a1"
        rc1.parent_main_session_id = "main-sess-a1"
        rc1.superseded = True
        rc1._outbound_closed = True
        mgr._connections.setdefault("dev-a", {})["rc-sess-a1"] = rc1

        rc2 = ReminderControlContext(
            websocket=FakeWS(),
            config={},
            device_id="dev-a",
            client_id="c1",
            account_id="acct1",
        )
        rc2.session_id = "rc-sess-a2"
        self.assertTrue(await mgr.register_connection("dev-a", rc2))
        self.assertEqual(rc2.parent_main_session_id, "main-sess-a2")

        from core.utils.device_outbound import guarded_ws_send

        self.assertTrue(
            await guarded_ws_send(rc2, json.dumps({"type": "pong"}), command="pong", msg_type="pong")
        )
        self.assertEqual(len(rc2.websocket.sent), 1)

        await mgr.unregister_connection("dev-a", rc1)
        self.assertEqual(len(rc2.websocket.sent), 1)
        self.assertTrue(
            await guarded_ws_send(rc2, json.dumps({"type": "pong"}), command="pong", msg_type="pong")
        )
        self.assertEqual(len(rc2.websocket.sent), 2)

        await server.unregister_connection("dev-a", main_a2)
        rc2_before = len(rc2.websocket.sent)
        self.assertFalse(
            await guarded_ws_send(rc2, json.dumps({"type": "pong"}), command="pong", msg_type="pong")
        )
        self.assertEqual(len(rc2.websocket.sent), rc2_before)

    async def test_rc_register_without_main_fail_closed(self):
        server = make_integrated_server()
        mgr = server._reminder_control_manager
        rc = ReminderControlContext(
            websocket=FakeWS(),
            config={},
            device_id="dev-a",
            client_id="c1",
            account_id="acct1",
        )
        rc.session_id = "rc-sess-a1"
        self.assertFalse(await mgr.register_connection("dev-a", rc))
        self.assertEqual(mgr.register_reject_reason("dev-a"), "no_main_session")

        from core.utils.device_outbound import guarded_ws_send

        rc.outbound_mode = "local_active"
        self.assertFalse(
            await guarded_ws_send(rc, json.dumps({"type": "pong"}), command="pong", msg_type="pong")
        )
        self.assertEqual(rc.websocket.sent, [])

    async def test_shared_lock_prevents_main_rc_interleaving(self):
        server = make_integrated_server()
        mgr = server._reminder_control_manager
        main_a1 = self._main_handler("dev-a", "main-sess-a1", server)
        server._register_connection_unlocked("dev-a", main_a1)
        rc1 = ReminderControlContext(
            websocket=BlockingFakeWS(),
            config={},
            device_id="dev-a",
            client_id="c1",
            account_id="acct1",
        )
        rc1.session_id = "rc-sess-a1"
        mgr._register_connection_unlocked("dev-a", rc1)

        from core.utils.device_outbound import guarded_ws_send

        send_task = asyncio.create_task(
            guarded_ws_send(rc1, json.dumps({"type": "pong"}), command="pong", msg_type="pong")
        )
        await asyncio.wait_for(rc1.websocket.entered.wait(), timeout=1.0)

        main_a2 = self._main_handler("dev-a", "main-sess-a2", server)
        main_reg = asyncio.create_task(server.register_connection("dev-a", main_a2))
        await asyncio.sleep(0.02)
        self.assertFalse(main_reg.done())
        self.assertIs(server._device_send_locks["dev-a"], mgr._device_send_locks["dev-a"])

        rc1.websocket.release.set()
        await send_task
        await wait_bounded(
            main_reg,
            timeout=5.0,
            test_name="test_shared_lock_prevents_main_rc_interleaving",
            point="main_a2 register_connection",
        )
        self.assertEqual(server.get_current_main_session_id("dev-a"), "main-sess-a2")
        self.assertTrue(rc1.superseded)


class TestDeviceOutboundQueueDrain(unittest.TestCase):
    def test_real_queue_drained_on_invalidate(self):
        import queue
        from core.utils.device_outbound import invalidate_connection

        conn = MagicMock()
        conn.device_id = "dev-q"
        conn.tts = MagicMock()
        conn.tts.tts_text_queue = queue.Queue()
        conn.tts.tts_audio_queue = queue.Queue()
        conn.tts.tts_text_queue.put("a")
        conn.tts.tts_audio_queue.put("b")
        conn._reminder_voice_tasks = set()
        conn._outbound_tasks = set()
        invalidate_connection(conn)
        self.assertTrue(conn.tts.tts_text_queue.empty())
        self.assertTrue(conn.tts.tts_audio_queue.empty())
        self.assertTrue(conn.superseded)

    def test_fake_queue_with_empty_drained(self):
        import queue
        from core.utils.device_outbound import invalidate_connection

        class ListQueue:
            def __init__(self):
                self._items = []

            def put(self, item):
                self._items.append(item)

            def get_nowait(self):
                if not self._items:
                    raise queue.Empty
                return self._items.pop(0)

            def empty(self):
                return not self._items

        conn = MagicMock()
        conn.device_id = "dev-f"
        conn.tts = MagicMock()
        conn.tts.tts_text_queue = ListQueue()
        conn.tts.tts_audio_queue = ListQueue()
        conn.tts.tts_text_queue.put("x")
        conn._reminder_voice_tasks = set()
        conn._outbound_tasks = set()
        invalidate_connection(conn)
        self.assertTrue(conn.tts.tts_text_queue.empty())


if __name__ == "__main__":
    unittest.main()

