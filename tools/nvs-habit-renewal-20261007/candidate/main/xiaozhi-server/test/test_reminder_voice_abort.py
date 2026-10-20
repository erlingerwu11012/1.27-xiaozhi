"""提醒语音 abort / 取消 / 代际安全测试。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.handle.abortHandle import handleAbortMessage
from core.utils.recipient_resolver import ProfileDirectory, ProfileRecord
from core.utils.reminder_voice import (
    _reset_inflight_for_tests,
    process_reminder_voice_request,
)
from core.utils.reminder_voice_store import ReminderVoiceStore


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


class TestAbortDoesNotDeleteStore(unittest.IsolatedAsyncioTestCase):
    async def test_abort_preserves_committed_asset(self):
        store = ReminderVoiceStore(ttl_sec=60)
        asset = store.put(_minimal_ogg(80), device_id="dev-1", account_id="acct_a")
        conn = MagicMock()
        conn.device_id = "dev-1"
        conn.session_id = "s1"
        conn.config = {}
        conn.client_abort = False
        conn.clear_queues = MagicMock()
        conn.clearSpeakStatus = MagicMock()
        _enable_local_outbound(conn)
        with patch(
            "core.handle.abortHandle.guarded_ws_send",
            new=AsyncMock(return_value=True),
        ):
            await handleAbortMessage(conn)
        self.assertIsNotNone(store.get(asset.asset_id))


class TestCancelDiscardsPendingAsset(unittest.IsolatedAsyncioTestCase):
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

    def _conn(self):
        conn = MagicMock()
        conn.device_id = "dev-1"
        conn.session_id = "sess-1"
        conn.account_id = "acct_a"
        conn.websocket = MagicMock()
        conn.config = self.cfg
        conn.llm = None
        conn.tts = MagicMock()
        conn._profile_directory = _active_dir()
        return _enable_local_outbound(conn)

    def _msg(self):
        return {
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
        }

    async def test_cancel_before_send_discards_store_asset(self):
        conn = self._conn()
        store = ReminderVoiceStore(ttl_sec=60)
        gate = asyncio.Event()
        pending_ids = []

        async def slow_send(*args, **kwargs):
            await gate.wait()
            return True

        orig_put = store.put

        def track_put(*args, **kwargs):
            asset = orig_put(*args, **kwargs)
            pending_ids.append(asset.asset_id)
            return asset

        with patch(
            "core.utils.reminder_voice.get_voice_store",
            return_value=store,
        ), patch(
            "core.utils.reminder_voice.generate_reminder_script",
            new=AsyncMock(return_value="提醒你，该去拿鸡了。"),
        ), patch(
            "core.utils.reminder_voice.synthesize_ogg_opus",
            new=AsyncMock(return_value=_minimal_ogg(120)),
        ), patch.object(store, "put", side_effect=track_put), patch(
            "core.utils.device_outbound.guarded_ws_send",
            new=slow_send,
        ):
            task = asyncio.create_task(
                process_reminder_voice_request(conn, self._msg())
            )
            for _ in range(50):
                if pending_ids:
                    break
                await asyncio.sleep(0.02)
            self.assertTrue(pending_ids, "asset should be stored before send")
            asset_id = pending_ids[0]
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertIsNone(store.get(asset_id))


class TestSupersedeDiscardsPending(unittest.IsolatedAsyncioTestCase):
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

    async def test_superseded_generation_discards_before_send(self):
        sent = []

        class WS:
            async def send(self, s):
                sent.append(json.loads(s))

        conn = self._conn(WS())
        store = ReminderVoiceStore(ttl_sec=60)
        ogg = _minimal_ogg(120)

        from core.utils import reminder_voice as rv

        async def synth_then_supersede(*args, **kwargs):
            rv._register_voice_generation("dev-1", "note:7:xyz", 99, conn)
            return ogg

        with patch.object(rv, "get_voice_store", return_value=store), patch(
            "core.utils.reminder_voice.generate_reminder_script",
            new=AsyncMock(return_value="提醒你。"),
        ), patch(
            "core.utils.reminder_voice.synthesize_ogg_opus",
            new=synth_then_supersede,
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
                    "detail": "",
                    "constraints": "one_fact_only",
                },
            )
        self.assertEqual(len(sent), 0)
        self.assertEqual(len(store._items), 0)


if __name__ == "__main__":
    unittest.main()
