"""reminder_voice_request / asset：校验、去重、会话隔离、签名 URL。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from core.utils.reminder_voice import (
    FALLBACK_SCRIPT,
    MISSED_FALLBACK_SCRIPT,
    _reset_inflight_for_tests,
    build_fallback_script,
    build_missed_occurrence_script,
    build_reminder_script,
    process_reminder_voice_request,
    sanitize_script,
    validate_reminder_voice_asset,
    validate_reminder_voice_request,
)
from core.utils.reminder_voice_store import (
    MAX_ASSET_BYTES,
    MAX_ASSET_BYTES,
    ReminderVoiceStore,
    build_signed_url,
    verify_signed_request,
)
from core.utils.recipient_resolver import ProfileDirectory, ProfileRecord
from core.handle.textMessageType import TextMessageType
from core.handle.textMessageHandlerRegistry import TextMessageHandlerRegistry


def _minimal_ogg(size: int = 64) -> bytes:
    body = b"OggS" + b"\x00" * max(0, size - 4)
    return body[:size]


def _active_dir():
    return ProfileDirectory(
        account_id="acct_a",
        profiles=[ProfileRecord("usr_abc123", "小明", "active", "acct_a")],
    )



def _enable_local_outbound(conn, manager=None):
    from local_active_test_util import bind_local_active_registry

    bind_local_active_registry(conn, manager)
    return conn


class TestReminderVoiceHelpers(unittest.TestCase):
    def test_validate_ok(self):
        ok, reason = validate_reminder_voice_request(
            {
                "instance_id": "note:7:abc",
                "revision": 4,
                "voice_revision": 2,
                "recipient_person_id": "usr_abc123",
                "presence_generation": 18,
                "title": "拿鸡",
                "detail": "从冰箱里取出",
                "constraints": "one_fact_only",
                "source_type": "note",
            }
        )
        self.assertTrue(ok, reason)

    def test_validate_bad_fields(self):
        ok, reason = validate_reminder_voice_request(
            {"instance_id": "!!", "revision": 1, "voice_revision": 1, "presence_generation": 1}
        )
        self.assertFalse(ok)

    def test_sanitize_and_fallback(self):
        self.assertIsNotNone(sanitize_script("提醒你，该去拿鸡了。"))
        self.assertIsNone(sanitize_script("必须马上做否则后果自负" + "x" * 10))
        self.assertEqual(build_fallback_script(""), FALLBACK_SCRIPT)

    def test_generate_script_passes_string_prompt(self):
        captured = {}

        class _Llm:
            def response_no_stream(self, system, user_prompt, **kwargs):
                captured["user_prompt"] = user_prompt
                return "提醒你，该喝水了。"

        conn = MagicMock()
        conn.llm = _Llm()

        async def _run():
            from core.utils.reminder_voice import generate_reminder_script

            return await generate_reminder_script(
                conn, title="喝水", detail="两分钟后", constraints="one_fact_only"
            )

        out = asyncio.run(_run())
        self.assertEqual(out, "提醒你，该喝水了。")
        self.assertIsInstance(captured.get("user_prompt"), str)
        self.assertNotIsInstance(captured.get("user_prompt"), list)
        self.assertIn("喝水", captured["user_prompt"])

    def test_synthesize_skips_dual_stream_text_to_speak(self):
        from core.providers.tts.dto.dto import InterfaceType
        from core.utils.reminder_voice import synthesize_ogg_opus

        conn = MagicMock()
        conn.tts = MagicMock(spec=["text_to_speak", "interface_type"])
        conn.tts.interface_type = InterfaceType.DUAL_STREAM
        conn.tts.text_to_speak = MagicMock()

        async def _run():
            with self.assertRaises(RuntimeError) as ctx:
                await synthesize_ogg_opus(conn, "提醒你。")
            return str(ctx.exception)

        err = asyncio.run(_run())
        self.assertEqual(err, "tts_stream_unsupported")
        conn.tts.text_to_speak.assert_not_called()

    def test_synthesize_uses_isolated_wav_not_speaker(self):
        import wave

        from core.providers.tts.dto.dto import InterfaceType
        from core.utils.reminder_voice import synthesize_ogg_opus

        conn = MagicMock()
        conn.tts = MagicMock()
        conn.tts.interface_type = InterfaceType.DUAL_STREAM
        conn.tts.text_to_speak = MagicMock()

        async def _iso(script, wav_path):
            os.makedirs(os.path.dirname(wav_path) or ".", exist_ok=True)
            with wave.open(wav_path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(b"\x00\x00" * 1600)
            conn.tts.text_to_speak.assert_not_called()

        conn.tts.synthesize_wav_isolated = _iso

        async def _run():
            return await synthesize_ogg_opus(conn, "提醒你，该喝水了。")

        data = asyncio.run(_run())
        self.assertTrue(data.startswith(b"OggS"))
        self.assertLessEqual(len(data), MAX_ASSET_BYTES)
        conn.tts.text_to_speak.assert_not_called()

    def test_signed_url_https(self):
        store = ReminderVoiceStore(ttl_sec=60)
        asset = store.put(_minimal_ogg(100), device_id="d1", account_id="a1")
        url, exp = build_signed_url(
            public_base_url="https://public.example.com",
            secret="secret",
            asset_id=asset.asset_id,
            device_id="d1",
        )
        self.assertTrue(url.startswith("https://public.example.com/reminder-voice/"))
        self.assertIn("sig=", url)
        self.assertIn("device_id=d1", url)
        from urllib.parse import urlparse, parse_qs

        q = parse_qs(urlparse(url).query)
        self.assertTrue(
            verify_signed_request(
                secret="secret",
                asset_id=asset.asset_id,
                device_id=q["device_id"][0],
                exp=q["exp"][0],
                sig=q["sig"][0],
                expected_device_id="d1",
            )
        )
        self.assertFalse(
            verify_signed_request(
                secret="secret",
                asset_id=asset.asset_id,
                device_id="d1",
                exp=q["exp"][0],
                sig="0" * 64,
                expected_device_id="d1",
            )
        )

    def test_http_public_base_rejected(self):
        with self.assertRaises(ValueError):
            build_signed_url(
                public_base_url="http://public.example.com",
                secret="secret",
                asset_id="abc",
                device_id="d1",
            )

    def test_registry_has_types(self):
        reg = TextMessageHandlerRegistry()
        self.assertIsNotNone(reg.get_handler(TextMessageType.REMINDER_VOICE_REQUEST.value))
        self.assertIsNotNone(reg.get_handler(TextMessageType.REMINDER_EVENT.value))


class TestReminderVoiceNewFields(unittest.TestCase):
    def _base(self, **overrides):
        msg = {
            "instance_id": "note:7:abc",
            "revision": 4,
            "voice_revision": 2,
            "recipient_person_id": "usr_abc123",
            "presence_generation": 18,
            "title": "拿鸡",
            "detail": "从冰箱里取出",
            "constraints": "one_fact_only",
            "source_type": "note",
        }
        msg.update(overrides)
        return msg

    def test_unknown_field_tolerated(self):
        ok, reason = validate_reminder_voice_request(self._base(future_field="x"))
        self.assertTrue(ok, reason)

    def test_privacy_fields_ok(self):
        ok, reason = validate_reminder_voice_request(
            self._base(
                privacy_safe_required=True,
                privacy_safe_text="有一条提醒等你处理",
                pending_count=2,
                announce_pending_count=True,
                missed_occurrence=False,
            )
        )
        self.assertTrue(ok, reason)

    def test_privacy_safe_required_bad_type(self):
        ok, reason = validate_reminder_voice_request(
            self._base(privacy_safe_required="yes")
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "bad_privacy_safe_required")

    def test_announce_bad_type(self):
        ok, reason = validate_reminder_voice_request(
            self._base(announce_pending_count="true")
        )
        self.assertFalse(ok)

    def test_missed_bad_type(self):
        ok, reason = validate_reminder_voice_request(self._base(missed_occurrence=1))
        self.assertFalse(ok)

    def test_pending_count_bad_type(self):
        ok, reason = validate_reminder_voice_request(self._base(pending_count="two"))
        self.assertFalse(ok)

    def test_pending_count_negative(self):
        ok, reason = validate_reminder_voice_request(self._base(pending_count=-1))
        self.assertFalse(ok)
        self.assertEqual(reason, "bad_pending_count")

    def test_pending_count_zero_rejected(self):
        ok, reason = validate_reminder_voice_request(self._base(pending_count=0))
        self.assertFalse(ok)
        self.assertEqual(reason, "bad_pending_count")

    def test_privacy_safe_text_too_long(self):
        ok, reason = validate_reminder_voice_request(
            self._base(privacy_safe_text="x" * 257)
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "privacy_safe_text_too_long")


class TestBuildReminderScript(unittest.IsolatedAsyncioTestCase):
    def _conn(self):
        conn = MagicMock()
        conn.llm = None
        return conn

    async def test_legacy_privacy_fields_do_not_change_current_script_contract(self):
        conn = self._conn()
        for safe_text in ("有一条提醒等你处理", ""):
            with patch("core.utils.reminder_voice.generate_reminder_script",
                       new=AsyncMock(return_value="提醒你喝水。")) as gen:
                script = await build_reminder_script(conn, title="喝水", detail="",
                    constraints="one_sentence", privacy_safe_required=True,
                    privacy_safe_text=safe_text)
                gen.assert_awaited_once_with(conn, title="喝水", detail="",
                                            constraints="one_sentence")
                self.assertEqual(script, "提醒你喝水。")

    async def test_missed_occurrence_deterministic(self):
        conn = self._conn()
        with patch(
            "core.utils.reminder_voice.generate_reminder_script",
            new=AsyncMock(return_value="不该被使用"),
        ) as gen:
            script = await build_reminder_script(
                conn,
                title="喝水",
                detail="",
                constraints="",
                missed_occurrence=True,
            )
            gen.assert_not_called()
        self.assertIn("喝水", script)
        self.assertIn("之前有一条提醒", script)

    async def test_pending_prefix_deterministic(self):
        conn = self._conn()
        with patch(
            "core.utils.reminder_voice.generate_reminder_script",
            new=AsyncMock(return_value="该去拿鸡了。"),
        ):
            script = await build_reminder_script(
                conn,
                title="拿鸡",
                detail="",
                constraints="",
                pending_count=2,
                announce_pending_count=True,
            )
        self.assertTrue(script.startswith("有2项待处理事项，"))
        self.assertIn("该去拿鸡了", script)

    async def test_pending_and_missed_combined_no_llm(self):
        conn = self._conn()
        with patch(
            "core.utils.reminder_voice.generate_reminder_script",
            new=AsyncMock(return_value="不该被使用"),
        ) as gen:
            script = await build_reminder_script(
                conn,
                title="喝水",
                detail="",
                constraints="",
                pending_count=3,
                announce_pending_count=True,
                missed_occurrence=True,
            )
            gen.assert_not_called()
        self.assertIn("3项待处理", script)
        self.assertIn("错过", script)
        self.assertIn("喝水", script)
        self.assertNotIn("不该被使用", script)

    async def test_alarm_missed_occurrence(self):
        conn = self._conn()
        with patch(
            "core.utils.reminder_voice.generate_reminder_script",
            new=AsyncMock(return_value="不该被使用"),
        ) as gen:
            script = await build_reminder_script(
                conn,
                title="起床",
                detail="",
                constraints="",
                missed_occurrence=True,
                source_type="alarm",
            )
            gen.assert_not_called()
        self.assertIn("闹钟", script)
        self.assertIn("错过", script)

    async def test_alarm_pending_and_missed_combined(self):
        conn = self._conn()
        with patch(
            "core.utils.reminder_voice.generate_reminder_script",
            new=AsyncMock(return_value="不该被使用"),
        ) as gen:
            script = await build_reminder_script(
                conn,
                title="起床",
                detail="",
                constraints="",
                pending_count=3,
                announce_pending_count=True,
                missed_occurrence=True,
                source_type="alarm",
            )
            gen.assert_not_called()
        self.assertIn("3项待处理", script)
        self.assertIn("闹钟", script)
        self.assertIn("错过", script)

    async def test_pending_not_announced_when_single(self):
        conn = self._conn()
        with patch(
            "core.utils.reminder_voice.generate_reminder_script",
            new=AsyncMock(return_value="该去拿鸡了。"),
        ):
            script = await build_reminder_script(
                conn,
                title="拿鸡",
                detail="",
                constraints="",
                pending_count=1,
                announce_pending_count=True,
            )
        self.assertFalse(script.startswith("有1项待处理事项，"))


class TestValidateReminderVoiceAsset(unittest.TestCase):
    def _asset(self, **overrides):
        payload = {
            "type": "reminder_voice_asset",
            "instance_id": "note:7:abc",
            "revision": 1,
            "voice_revision": 1,
            "phase": "due",
            "script": "提醒你。",
            "url": "https://public.example.com/reminder-voice/x",
            "sha256": "a" * 64,
            "format": "ogg_opus",
            "bytes": 128,
            "recipient_person_id": "usr_abc123",
            "presence_generation": 1,
        }
        payload.update(overrides)
        return payload

    def test_ok(self):
        ok, reason = validate_reminder_voice_asset(self._asset())
        self.assertTrue(ok, reason)

    def test_missing_field(self):
        payload = self._asset()
        payload.pop("sha256")
        ok, reason = validate_reminder_voice_asset(payload)
        self.assertFalse(ok)
        self.assertEqual(reason, "missing_sha256")

    def test_missing_instance_id(self):
        payload = self._asset()
        payload.pop("instance_id")
        ok, reason = validate_reminder_voice_asset(payload)
        self.assertFalse(ok)
        self.assertEqual(reason, "missing_instance_id")

    def test_missing_script(self):
        payload = self._asset()
        payload.pop("script")
        ok, reason = validate_reminder_voice_asset(payload)
        self.assertFalse(ok)
        self.assertEqual(reason, "missing_script")

    def test_bad_format(self):
        ok, reason = validate_reminder_voice_asset(self._asset(format="mp3"))
        self.assertFalse(ok)
        self.assertEqual(reason, "bad_format")

    def test_bad_bytes(self):
        ok, reason = validate_reminder_voice_asset(self._asset(bytes="128"))
        self.assertFalse(ok)
        self.assertEqual(reason, "bad_bytes")

    def test_bytes_zero_rejected(self):
        ok, reason = validate_reminder_voice_asset(self._asset(bytes=0))
        self.assertFalse(ok)
        self.assertEqual(reason, "bad_bytes")

    def test_bytes_over_limit_rejected(self):
        ok, reason = validate_reminder_voice_asset(
            self._asset(bytes=MAX_ASSET_BYTES + 1)
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "bytes_too_large")

    def test_bad_url(self):
        ok, reason = validate_reminder_voice_asset(
            self._asset(url="http://public.example.com/reminder-voice/x")
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "bad_url")

    def test_bad_sha256(self):
        ok, reason = validate_reminder_voice_asset(self._asset(sha256="short"))
        self.assertFalse(ok)
        self.assertEqual(reason, "bad_sha256")

    def test_bad_sha256_non_hex(self):
        ok, reason = validate_reminder_voice_asset(self._asset(sha256="g" * 64))
        self.assertFalse(ok)
        self.assertEqual(reason, "bad_sha256")

    def test_sha256_uppercase_rejected(self):
        ok, reason = validate_reminder_voice_asset(
            self._asset(sha256=("a" * 32 + "A" * 32))
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "bad_sha256")

    def test_bytes_bool_rejected(self):
        ok, reason = validate_reminder_voice_asset(self._asset(bytes=True))
        self.assertFalse(ok)
        self.assertEqual(reason, "bad_bytes")

    def test_bad_instance_id_empty(self):
        ok, reason = validate_reminder_voice_asset(self._asset(instance_id="  "))
        self.assertFalse(ok)
        self.assertEqual(reason, "bad_instance_id")

    def test_bad_voice_revision_bool(self):
        ok, reason = validate_reminder_voice_asset(self._asset(voice_revision=True))
        self.assertFalse(ok)
        self.assertEqual(reason, "bad_voice_revision")

    def test_bad_phase(self):
        ok, reason = validate_reminder_voice_asset(self._asset(phase="unknown"))
        self.assertFalse(ok)
        self.assertEqual(reason, "bad_phase")

    def test_script_too_long(self):
        ok, reason = validate_reminder_voice_asset(
            self._asset(script="x" * 100)
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "script_too_long")

    def test_url_too_long(self):
        ok, reason = validate_reminder_voice_asset(
            self._asset(url="https://x.example.com/" + "a" * 3000)
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "bad_url")


class TestReminderVoicePipeline(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _reset_inflight_for_tests()
        self.cfg = {
            "server": {
                "auth_key": "unit-test-auth-key-32bytes!!",
                "public_base_url": "https://public.example.com",
                "reminder_voice_signing_key": "rv-sign-key-for-tests-only",
                "face": {"account_id": "acct_a"},
            }
        }

    def _conn(self, ws):
        conn = MagicMock()
        conn.device_id = "dev-1"
        conn.session_id = "sess-1"
        conn.account_id = "acct_a"
        conn.websocket = ws
        conn.config = self.cfg
        conn.llm = None
        conn.tts = MagicMock()
        conn._profile_directory = _active_dir()
        return _enable_local_outbound(conn)

    async def test_asset_sent_on_success(self):
        sent = []

        class WS:
            async def send(self, s):
                sent.append(json.loads(s))

        conn = self._conn(WS())
        ogg = _minimal_ogg(200)
        with patch(
            "core.utils.reminder_voice.generate_reminder_script",
            new=AsyncMock(return_value="提醒你，该去拿鸡了。"),
        ), patch(
            "core.utils.reminder_voice.synthesize_ogg_opus",
            new=AsyncMock(return_value=ogg),
        ):
            await process_reminder_voice_request(
                conn,
                {
                    "type": "reminder_voice_request",
                    "instance_id": "note:7:xyz",
                    "revision": 4,
                    "voice_revision": 2,
                    "recipient_person_id": "usr_abc123",
                    "presence_generation": 18,
                    "source_type": "note",
                    "title": "拿鸡",
                    "detail": "从冰箱里取出",
                    "constraints": "one_fact_only;one_sentence",
                },
            )
        self.assertEqual(len(sent), 1)
        asset = sent[0]
        self.assertEqual(asset["type"], "reminder_voice_asset")
        self.assertEqual(asset["format"], "ogg_opus")
        self.assertEqual(asset["bytes"], len(ogg))
        self.assertEqual(asset["sha256"], hashlib.sha256(ogg).hexdigest())
        self.assertTrue(asset["url"].startswith("https://"))
        self.assertIn("device_id=dev-1", asset["url"])

    async def test_too_large_no_fake_asset(self):
        sent = []

        class WS:
            async def send(self, s):
                sent.append(json.loads(s))

        conn = self._conn(WS())
        with patch(
            "core.utils.reminder_voice.generate_reminder_script",
            new=AsyncMock(return_value="提醒你，该去拿鸡了。"),
        ), patch(
            "core.utils.reminder_voice.synthesize_ogg_opus",
            new=AsyncMock(return_value=_minimal_ogg(MAX_ASSET_BYTES + 10)),
        ):
            await process_reminder_voice_request(
                conn,
                {
                    "instance_id": "note:7:big",
                    "revision": 1,
                    "voice_revision": 1,
                    "recipient_person_id": "usr_abc123",
                    "presence_generation": 1,
                    "source_type": "note",
                    "title": "x",
                    "detail": "y",
                },
            )
        self.assertEqual(sent, [])

    async def test_connection_closed_no_asset(self):
        conn = self._conn(None)
        await process_reminder_voice_request(
            conn,
            {
                "instance_id": "note:7:closed",
                "revision": 1,
                "voice_revision": 1,
                "recipient_person_id": "usr_abc123",
                "presence_generation": 1,
                "source_type": "note",
                "title": "x",
                "detail": "y",
            },
        )

    async def test_tts_failure_no_asset(self):
        sent = []

        class WS:
            async def send(self, s):
                sent.append(s)

        conn = self._conn(WS())
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
                    "instance_id": "note:8:fail",
                    "revision": 1,
                    "voice_revision": 1,
                    "recipient_person_id": "usr_abc123",
                    "presence_generation": 2,
                    "source_type": "note",
                    "title": "x",
                    "detail": "y",
                },
            )
        self.assertEqual(sent, [])

    async def test_stale_voice_generation_discarded(self):
        """较晚请求抬升代际后，较早的合成结果不得下发。"""
        sent = []

        class WS:
            async def send(self, s):
                sent.append(json.loads(s))

        conn = self._conn(WS())
        gate = asyncio.Event()
        synth_calls = {"n": 0}

        async def slow_tts(conn, script):
            synth_calls["n"] += 1
            if synth_calls["n"] == 1:
                await asyncio.wait_for(gate.wait(), timeout=5.0)
            return _minimal_ogg(120)

        base = {
            "instance_id": "note:gen:1",
            "revision": 1,
            "voice_revision": 9,
            "recipient_person_id": "usr_abc123",
            "presence_generation": 1,
            "source_type": "note",
            "title": "x",
            "detail": "y",
        }
        tasks = []
        try:
            with patch(
                "core.utils.reminder_voice.generate_reminder_script",
                new=AsyncMock(return_value="提醒你，该处理这件事了。"),
            ), patch(
                "core.utils.reminder_voice.synthesize_ogg_opus",
                new=slow_tts,
            ):
                t1 = asyncio.create_task(
                    process_reminder_voice_request(
                        conn, {**base, "phase": "due"}
                    )
                )
                tasks.append(t1)
                await asyncio.sleep(0.05)
                t2 = asyncio.create_task(
                    process_reminder_voice_request(
                        conn, {**base, "phase": "followup"}
                    )
                )
                tasks.append(t2)
                await asyncio.sleep(0.05)
                gate.set()
                await asyncio.wait_for(asyncio.gather(*tasks), timeout=10.0)
        finally:
            for t in tasks:
                if not t.done():
                    t.cancel()
            for t in tasks:
                try:
                    await t
                except Exception:
                    pass
        assets = [m for m in sent if m.get("type") == "reminder_voice_asset"]
        self.assertEqual(len(assets), 1)
        self.assertEqual(assets[0]["phase"], "followup")

    async def test_voice_revision_v2_supersedes_blocking_v1(self):
        """v1 阻塞合成时 v2 到达，释放 v1 后仅 v2 可 store/send。"""
        sent = []

        class WS:
            async def send(self, s):
                sent.append(json.loads(s))

        conn = self._conn(WS())
        gate = asyncio.Event()
        store_puts = []

        async def slow_tts(conn, script):
            await asyncio.wait_for(gate.wait(), timeout=5.0)
            return _minimal_ogg(120)

        real_put = __import__(
            "core.utils.reminder_voice_store", fromlist=["get_voice_store"]
        ).get_voice_store().put

        def tracking_put(ogg, **kwargs):
            store_puts.append(kwargs.get("device_id"))
            return real_put(ogg, **kwargs)

        base = {
            "instance_id": "note:ver:1",
            "revision": 1,
            "recipient_person_id": "usr_abc123",
            "presence_generation": 1,
            "source_type": "note",
            "phase": "due",
            "title": "x",
            "detail": "y",
        }
        tasks = []
        try:
            with patch(
                "core.utils.reminder_voice.generate_reminder_script",
                new=AsyncMock(return_value="提醒你。"),
            ), patch(
                "core.utils.reminder_voice.synthesize_ogg_opus",
                new=slow_tts,
            ), patch.object(
                __import__(
                    "core.utils.reminder_voice_store", fromlist=["get_voice_store"]
                ).get_voice_store(),
                "put",
                side_effect=tracking_put,
            ):
                t1 = asyncio.create_task(
                    process_reminder_voice_request(
                        conn, {**base, "voice_revision": 1}
                    )
                )
                tasks.append(t1)
                await asyncio.sleep(0.05)
                t2 = asyncio.create_task(
                    process_reminder_voice_request(
                        conn, {**base, "voice_revision": 2}
                    )
                )
                tasks.append(t2)
                await asyncio.sleep(0.05)
                gate.set()
                await asyncio.wait_for(asyncio.gather(*tasks), timeout=10.0)
        finally:
            for t in tasks:
                if not t.done():
                    t.cancel()
            for t in tasks:
                try:
                    await t
                except Exception:
                    pass
        assets = [m for m in sent if m.get("type") == "reminder_voice_asset"]
        self.assertEqual(len(assets), 1)
        self.assertEqual(assets[0]["voice_revision"], 2)
        self.assertEqual(len(store_puts), 1)

    async def test_superseded_connection_drops_asset(self):
        sent = []

        class WS:
            async def send(self, s):
                sent.append(json.loads(s))

        conn = self._conn(WS())
        ogg = _minimal_ogg(100)

        async def tts_then_supersede(conn, script):
            conn.superseded = True
            return ogg

        with patch(
            "core.utils.reminder_voice.generate_reminder_script",
            new=AsyncMock(return_value="提醒你。"),
        ), patch(
            "core.utils.reminder_voice.synthesize_ogg_opus",
            new=tts_then_supersede,
        ):
            await process_reminder_voice_request(
                conn,
                {
                    "instance_id": "note:sup:1",
                    "revision": 1,
                    "voice_revision": 1,
                    "recipient_person_id": "usr_abc123",
                    "presence_generation": 1,
                    "source_type": "note",
                    "phase": "due",
                    "title": "x",
                    "detail": "y",
                },
            )
        self.assertEqual(
            [m for m in sent if m.get("type") == "reminder_voice_asset"],
            [],
        )


if __name__ == "__main__":
    unittest.main()
