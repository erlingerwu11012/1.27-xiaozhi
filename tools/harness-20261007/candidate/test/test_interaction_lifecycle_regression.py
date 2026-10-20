"""提醒交互生命周期集成回归（mock，不连真实 WS/ASR）。"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.handle.receiveAudioHandle import no_voice_close_connect
from core.handle.textHandler.reminderEventMessageHandler import (
    ReminderEventMessageHandler,
)
from core.providers.asr.aliyun_stream import ASRProvider
from core.utils.reminder_interaction import (
    close_interaction,
    is_interaction_active,
    open_interaction,
)


class TestInteractionListenStopSuppression(unittest.IsolatedAsyncioTestCase):
    async def test_listen_stop_skipped_when_interaction_active(self):
        conn = MagicMock()
        conn.device_id = "dev-1"
        conn.session_id = "s1"
        open_interaction(
            conn,
            instance_id="note:1:1",
            revision=1,
            expires_at=int(time.time()) + 60,
        )
        provider = ASRProvider({"token": "test-token"}, delete_audio_file=False)
        with patch(
            "core.providers.asr.aliyun_stream.guarded_ws_send",
            new=AsyncMock(),
        ) as mock_send:
            await provider._send_listen_stop_to_client(conn, "完成")
        mock_send.assert_not_called()

    async def test_listen_stop_sent_when_inactive(self):
        conn = MagicMock()
        conn.device_id = "dev-1"
        conn.session_id = "s1"
        provider = ASRProvider({"token": "test-token"}, delete_audio_file=False)
        with patch(
            "core.providers.asr.aliyun_stream.guarded_ws_send",
            new=AsyncMock(return_value=True),
        ) as mock_send:
            await provider._send_listen_stop_to_client(conn)
        mock_send.assert_called_once()
        payload = json.loads(mock_send.call_args[0][1])
        self.assertEqual(payload["type"], "listen")
        self.assertEqual(payload["state"], "stop")


class TestInteractionIdleCloseSuppression(unittest.IsolatedAsyncioTestCase):
    async def test_no_voice_close_skipped_when_interaction_active(self):
        conn = MagicMock()
        conn.device_id = "dev-1"
        conn.last_activity_time = 0.0
        conn.close_after_chat = False
        conn.config = {"close_connection_no_voice_time": 1}
        open_interaction(
            conn,
            instance_id="note:1:1",
            revision=1,
            expires_at=int(time.time()) + 60,
        )
        with patch(
            "core.handle.receiveAudioHandle.startToChat",
            new=AsyncMock(),
        ) as mock_chat:
            await no_voice_close_connect(conn, have_voice=False)
        mock_chat.assert_not_called()

    async def test_no_voice_close_runs_when_inactive(self):
        conn = MagicMock()
        conn.device_id = "dev-1"
        conn.last_activity_time = time.time() * 1000 - 5000
        conn.close_after_chat = False
        conn.config = {"close_connection_no_voice_time": 1}
        with patch(
            "core.handle.receiveAudioHandle.startToChat",
            new=AsyncMock(),
        ) as mock_chat:
            await no_voice_close_connect(conn, have_voice=False)
        mock_chat.assert_called_once()


class TestInteractionCloseReasons(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.handler = ReminderEventMessageHandler()
        self.conn = MagicMock()
        self.conn.device_id = "dev-1"
        self.conn.session_id = "s1"
        self.conn._outbound_tasks = set()

    async def _open(self):
        await self.handler.handle(
            self.conn,
            {
                "type": "reminder_event",
                "event": "interaction_opened",
                "instance_id": "note:1:1",
                "revision": 2,
                "expires_at": int(time.time()) + 120,
            },
        )
        self.assertTrue(is_interaction_active(self.conn))

    async def test_close_reasons_restore_inactive(self):
        for reason in ("resolved", "timeout", "presence_lost", "preempted"):
            with self.subTest(reason=reason):
                await self._open()
                await self.handler.handle(
                    self.conn,
                    {
                        "type": "reminder_event",
                        "event": "interaction_closed",
                        "instance_id": "note:1:1",
                        "reason": reason,
                    },
                )
                self.assertFalse(is_interaction_active(self.conn))


class TestLegacyFirmwareNoInteraction(unittest.TestCase):
    def test_no_events_means_not_active(self):
        conn = MagicMock()
        conn.device_id = "dev-1"
        self.assertFalse(is_interaction_active(conn))

    def test_manual_close_clears_state(self):
        conn = MagicMock()
        conn.device_id = "dev-1"
        open_interaction(
            conn,
            instance_id="note:1:1",
            revision=1,
            expires_at=int(time.time()) + 30,
        )
        close_interaction(conn, reason="resolved")
        self.assertFalse(is_interaction_active(conn))


if __name__ == "__main__":
    unittest.main()
