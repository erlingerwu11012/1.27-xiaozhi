"""HTTP ASR and other stream providers stay compatible. No paid upstream calls."""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.providers.asr.base import ASRProviderBase
from core.providers.asr.aliyun_stream import ASRProvider as AliyunStream
from core.utils.utterance_state import on_listen_start, on_listen_stop


class DummyHTTP(ASRProviderBase):
    def __init__(self):
        super().__init__()
        self.stops = []

    async def speech_to_text(self, opus_data, session_id, audio_format="opus"):
        return "ok", None

    async def handle_voice_stop(self, conn, asr_audio_task, *, final_text=None, listen_epoch=None):
        self.stops.append(
            {
                "frames": list(asr_audio_task),
                "text": final_text,
                "epoch": listen_epoch,
            }
        )


class Conn:
    def __init__(self):
        self.listen_epoch = 1
        self.session_id = "http-sess"
        self.asr_audio = []
        self.client_listen_mode = "auto"
        self.client_have_voice = False
        self.client_voice_stop = False
        self.audio_format = "pcm"
        self.logger = MagicMock()
        self.logger.bind.return_value = self.logger
        on_listen_start(self)

    def reset_vad_states(self, utterance_id=None):
        from core.utils.utterance_state import finish_utterance

        finish_utterance(self, utterance_id)


def _frame(tag):
    return bytes([tag, 0]) * 16


class HttpAsrCompatTests(unittest.IsolatedAsyncioTestCase):
    async def test_listen_start_silence_does_not_submit(self):
        conn = Conn()
        asr = DummyHTTP()
        for i in range(12):
            await asr.receive_audio(conn, _frame(i), False)
        self.assertEqual(asr.stops, [])
        self.assertLessEqual(len(conn.asr_audio), 10)

    async def test_short_command_over_threshold_submits_once(self):
        conn = Conn()
        asr = DummyHTTP()
        conn.client_have_voice = True
        frames = [_frame(i) for i in range(16)]
        for frame in frames:
            await asr.receive_audio(conn, frame, True)
        conn.client_voice_stop = True
        await asr.receive_audio(conn, _frame(99), False)
        self.assertEqual(len(asr.stops), 1)
        self.assertEqual([f[0] for f in asr.stops[0]["frames"][:-1]], list(range(16)))

    async def test_silence_below_threshold_not_guessed(self):
        conn = Conn()
        asr = DummyHTTP()
        conn.client_have_voice = True
        for i in range(8):
            await asr.receive_audio(conn, _frame(i), True)
        conn.client_voice_stop = True
        await asr.receive_audio(conn, _frame(9), False)
        self.assertEqual(asr.stops, [])

    async def test_manual_mode_still_uses_existing_branch(self):
        conn = Conn()
        conn.client_listen_mode = "manual"
        asr = DummyHTTP()
        await asr.receive_audio(conn, _frame(1), False)
        self.assertEqual(asr.stops, [])
        conn.client_have_voice = True
        for i in range(16):
            await asr.receive_audio(conn, _frame(i), False)
        conn.client_voice_stop = True
        await asr.receive_audio(conn, _frame(20), False)
        self.assertEqual(len(asr.stops), 1)


class AliyunStreamCompatTests(unittest.IsolatedAsyncioTestCase):
    async def test_listen_hooks_accept_reason(self):
        provider = AliyunStream({"token": "test-token"}, delete_audio_file=False)
        conn = Conn()
        conn.asr_audio = [b"x"]
        conn.asr_audio_for_voiceprint = [b"x"]
        await provider.start_listening(conn, reason="new_listen")
        self.assertEqual(conn.asr_audio, [])
        await provider.stop_listening(conn, reason="device_stop")
        on_listen_stop(conn)
        self.assertFalse(conn.device_listening)


if __name__ == "__main__":
    unittest.main()
