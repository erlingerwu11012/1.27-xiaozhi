"""TTS / listen 交叉观测与 listen 幂等单测。"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.providers.tts.dto.dto import SentenceType
from core.handle.sendAudioHandle import sendAudioMessage
from core.handle.textHandler.listenMessageHandler import ListenTextMessageHandler
from core.utils.tts_listen_observe import (
    classify_listen_start,
    log_listen_during_tts,
    note_tts_start_sent,
    note_tts_stop_sent,
    tts_send_in_progress,
)
from core.utils.audio_ingress import begin_listen


class FakeWS:
    def __init__(self):
        self.sent = []

    async def send(self, data):
        self.sent.append(data)


class _Conn:
    def __init__(self):
        self.websocket = FakeWS()
        self.logger = MagicMock()
        self.session_id = "sess-test"
        self.device_id = "dev-test"
        self.sentence_id = "sent-1"
        self.tts_abort_epoch = 0
        self.client_abort = False
        self.client_is_speaking = False
        self.client_listen_mode = "auto"
        self.device_listening = False
        self.listen_epoch = 0
        self.vad_speech_confirmed = False
        self.client_have_voice = False
        self.config = {"tts_audio_send_delay": -1}
        self.conn_from_mqtt_gateway = False
        self.audio_protocol_version = 0
        self.close_after_chat = False
        self.server = MagicMock()
        self.server.is_current_connection = MagicMock(return_value=True)

        async def _send_to_current(device_id, data, **kwargs):
            await self.websocket.send(data)
            return True

        self.server.send_to_current = _send_to_current
        self.tts = MagicMock()
        self.tts.tts_audio_first_sentence = True
        self.asr = MagicMock()
        self.asr.start_listening = MagicMock(return_value=None)
        self.asr_audio = []
        self._mask = lambda x: x or ""
        self._cid = lambda: "cid=test"

        from core.utils.tts_sentence_telemetry import TTSSentenceTelemetry

        self.tts_sentence_telemetry = TTSSentenceTelemetry()

    def clearSpeakStatus(self):
        self.client_is_speaking = False


class TestTtsListenObserve(unittest.TestCase):
    def test_tts_order_start_audio_stop(self):
        async def _run():
            conn = _Conn()
            await sendAudioMessage(conn, SentenceType.FIRST, b"\x01\x02", "你好")
            await sendAudioMessage(conn, SentenceType.MIDDLE, b"\x03\x04", None)
            await sendAudioMessage(conn, SentenceType.LAST, [], None)
            types = []
            for item in conn.websocket.sent:
                if isinstance(item, str):
                    obj = json.loads(item)
                    if obj.get("type") == "tts":
                        types.append(obj.get("state"))
                else:
                    types.append("audio")
            # start → sentence_start → audio* → stop；stop 在最后一帧音频之后
            self.assertEqual(types[0], "start")
            self.assertIn("sentence_start", types)
            self.assertIn("audio", types)
            self.assertEqual(types[-1], "stop")
            audio_idx = types.index("audio")
            stop_idx = types.index("stop")
            self.assertLess(audio_idx, stop_idx)
            self.assertFalse(tts_send_in_progress(conn))
            self.assertTrue(conn.tts_stop_sent)

        asyncio.run(_run())

    def test_listen_during_tts_logs_observe_only(self):
        conn = _Conn()
        note_tts_start_sent(conn)
        conn.client_is_speaking = True
        log_listen_during_tts(
            conn, {"state": "start", "mode": "auto", "generation": 1}, tag="test"
        )
        bound = conn.logger.bind.return_value
        logged = " ".join(
            str(c.args[0]) for c in bound.info.call_args_list if c.args
        )
        self.assertIn("[listen_during_tts]", logged)
        self.assertIn("observe_only", logged)

    def test_idempotent_same_generation(self):
        conn = _Conn()
        begin_listen(conn, 7)
        conn.device_listening = True
        conn.client_listen_mode = "auto"
        reason, skip = classify_listen_start(
            conn, {"state": "start", "mode": "auto", "generation": 7}
        )
        self.assertEqual(reason, "same_generation_idle")
        self.assertTrue(skip)

    def test_no_generation_does_not_skip(self):
        conn = _Conn()
        begin_listen(conn, None)
        conn.device_listening = True
        reason, skip = classify_listen_start(
            conn, {"state": "start", "mode": "auto"}
        )
        self.assertEqual(reason, "no_generation_id")
        self.assertFalse(skip)

    def test_speech_active_does_not_skip(self):
        conn = _Conn()
        begin_listen(conn, 3)
        conn.device_listening = True
        conn.vad_speech_confirmed = True
        reason, skip = classify_listen_start(
            conn, {"state": "start", "mode": "auto", "generation": 3}
        )
        self.assertEqual(reason, "speech_active")
        self.assertFalse(skip)

    def test_handler_idempotent_skips_begin_listen(self):
        async def _run():
            conn = _Conn()
            begin_listen(conn, 9)
            epoch_before = conn.listen_epoch
            handler = ListenTextMessageHandler()
            await handler.handle(
                conn, {"state": "start", "mode": "auto", "generation": 9}
            )
            self.assertEqual(conn.listen_epoch, epoch_before)
            conn.asr.start_listening.assert_not_called()

        asyncio.run(_run())

    def test_abort_resets_tts_outbound(self):
        conn = _Conn()
        note_tts_start_sent(conn)
        self.assertTrue(tts_send_in_progress(conn))
        note_tts_stop_sent(conn)
        self.assertFalse(tts_send_in_progress(conn))


if __name__ == "__main__":
    unittest.main()
