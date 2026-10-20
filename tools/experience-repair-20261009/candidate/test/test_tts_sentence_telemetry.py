"""下行 TTS 句级遥测单测。

覆盖：
- 多帧正常句：frame_count / total_bytes / max_gap / stop 时差正确；
- abort：只输出一次 aborted 终态；
- SessionFinished 迟到：gap / stop 时差正确；
- 连接关闭前未 stop：reason=missing_stop_observed；
- 事件缺失：相关字段 n/a；
- preinit audio 连续到达：不刷屏、关闭时计数正确；
- 日志不含正文 / 音频 / Token。
不依赖完整 app 依赖，仅用轻量 FakeWS + FakeClock + mock。
"""

from __future__ import annotations

import asyncio
import json
import struct
import sys
import os
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.connection import ConnectionHandler
from core.providers.tts.dto.dto import SentenceType
from core.handle.sendAudioHandle import sendAudioMessage
from core.handle.abortHandle import handleAbortMessage
from core.utils.tts_sentence_telemetry import TTSSentenceTelemetry


class FakeWS:
    def __init__(self):
        self.sent = []

    async def send(self, data):
        self.sent.append(data)


class FakeClock:
    def __init__(self):
        self.t = 0

    def __call__(self):
        return self.t

    def advance(self, ms):
        self.t += ms


def _v2_frame(payload=b"\x01\x02\x03"):
    header = struct.pack("!HHIII", 2, 0, 0, 0, len(payload))
    return header + payload


def _find_logs(logger_mock, prefix):
    out = []
    for call in logger_mock.bind.return_value.info.call_args_list:
        arg = call.args[0] if call.args else ""
        if isinstance(arg, str) and arg.startswith(prefix):
            out.append(arg)
    return out


def _find_warns(logger_mock, prefix):
    out = []
    for call in logger_mock.bind.return_value.warning.call_args_list:
        arg = call.args[0] if call.args else ""
        if isinstance(arg, str) and arg.startswith(prefix):
            out.append(arg)
    return out


class _FakeTTSConn:
    """最小连接对象，用于驱动 sendAudioMessage / handleAbortMessage。"""

    def __init__(self, clock):
        self.websocket = FakeWS()
        self.logger = MagicMock()
        self.session_id = "session-abcdef12345678"
        self.device_id = "aa:bb:cc:dd:ee:ff"
        self.sentence_id = "sent-1"
        self.client_abort = False
        self.client_is_speaking = False
        self.close_after_chat = False
        self.last_activity_time = 0
        self.config = {"tts_audio_send_delay": -1, "enable_stop_tts_notify": False}
        self.conn_from_mqtt_gateway = False
        self.audio_protocol_version = 0
        self.tts = MagicMock()
        self.tts.tts_audio_first_sentence = False
        self.tts_sentence_telemetry = TTSSentenceTelemetry(clock=clock)
        self.clearSpeakStatus_called = False
        self.superseded = False
        self._outbound_closed = False
        self.server = None
        self.stop_event = None
        sys.path.insert(0, os.path.dirname(__file__))
        from local_active_test_util import bind_local_active_registry

        bind_local_active_registry(self)

    def _mask(self, value):
        return ConnectionHandler._mask(value)

    def _cid(self):
        return "correlation_id=testcid device_id=aa:bb:cc:dd:ee:ff"

    def clearSpeakStatus(self):
        self.clearSpeakStatus_called = True
        self.client_is_speaking = False

    def clear_queues(self):
        pass


class TestTtsSentenceTelemetry(unittest.TestCase):
    def _telemetry(self):
        clock = FakeClock()
        return TTSSentenceTelemetry(clock=clock), clock

    def test_multi_frame_counts_and_max_gap(self):
        t, c = self._telemetry()
        t.note_sentence_started("s1")
        for n in (40, 60, 30):
            c.advance(100)
            t.note_audio_sent("s1", n)
        self.assertEqual(t.frame_count, 3)
        self.assertEqual(t.total_payload_bytes, 130)
        self.assertEqual(t.max_interframe_gap_ms, 100)
        self.assertEqual(t.first_send_ms, 100)
        self.assertEqual(t.last_send_ms, 300)

    def test_finalize_abort_once(self):
        t, c = self._telemetry()
        t.note_sentence_started("s1")
        t.note_audio_sent("s1", 40)
        t.mark_aborted("s1")
        line = t.finalize("abort", "ses***...")
        self.assertIn("reason=abort", line)
        self.assertIn("aborted=1", line)
        self.assertIsNone(t.finalize("abort", "ses***..."))

    def test_session_finished_diff(self):
        t, c = self._telemetry()
        t.note_sentence_started("s1")
        c.advance(10)
        t.note_tts_sentence_start("s1")  # t=10
        c.advance(10)
        t.note_tts_response("s1")  # t=20 (first)
        c.advance(10)
        t.note_tts_response("s1")  # t=30 (last)
        c.advance(10)
        t.note_tts_sentence_end("s1")  # t=40
        c.advance(10)
        t.note_audio_sent("s1", 50)  # t=50 (last send)
        c.advance(20)
        t.note_session_finished("s1")  # t=70
        c.advance(10)
        t.note_stop_dispatched("s1")  # t=80
        line = t.finalize("session_finished", "ses***...")
        self.assertIn("reason=session_finished", line)
        self.assertIn("last_tts_response_to_last_send_ms=20", line)
        self.assertIn("sentence_end_to_last_send_ms=10", line)
        self.assertIn("session_finished_to_stop_ms=10", line)
        self.assertIn("first_to_last_ms=0", line)

    def test_missing_stop(self):
        t, c = self._telemetry()
        t.note_sentence_started("s1")
        t.note_audio_sent("s1", 40)
        line = t.finalize("missing_stop_observed", "ses***...")
        self.assertIn("reason=missing_stop_observed", line)
        self.assertIn("frames=1", line)

    def test_event_missing_na(self):
        t, c = self._telemetry()
        t.note_sentence_started("s1")
        t.note_audio_sent("s1", 40)
        t.note_stop_dispatched("s1")
        line = t.finalize("normal_stop", "ses***...")
        self.assertIn("reason=normal_stop", line)
        self.assertIn("session_finished_to_stop_ms=n/a", line)
        self.assertIn("last_tts_response_to_last_send_ms=n/a", line)
        self.assertIn("sentence_end_to_last_send_ms=n/a", line)

    def test_log_line_has_no_text(self):
        t, c = self._telemetry()
        t.note_sentence_started("s1")
        t.note_audio_sent("s1", 40)
        line = t.finalize("normal_stop", "ses***...")
        for sentinel in ("TOP-SECRET", "秘密内容", "audio", "token"):
            self.assertNotIn(sentinel, line)

    def test_epoch_increments_on_new_sentence(self):
        t, c = self._telemetry()
        t.note_sentence_started("s1")
        self.assertEqual(t.epoch, 1)
        t.finalize("normal_stop", "x")
        t.note_sentence_started("s1")  # 同 id 但已终结 → 新 epoch
        self.assertEqual(t.epoch, 2)
        t.note_sentence_started("s2")  # 新 id
        self.assertEqual(t.epoch, 3)


class TestTtsSentenceIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_send_audio_multi_frame_normal(self):
        clock = FakeClock()
        conn = _FakeTTSConn(clock)
        await sendAudioMessage(conn, SentenceType.FIRST, [], "TOP-SECRET-TEXT")
        for n in (40, 60, 30):
            clock.advance(120)
            await sendAudioMessage(conn, SentenceType.MIDDLE, b"\x01" * n, None)
        conn.tts_sentence_telemetry.note_session_finished(conn.sentence_id)
        clock.advance(50)
        await sendAudioMessage(conn, SentenceType.LAST, [], "TOP-SECRET-TEXT")

        t = conn.tts_sentence_telemetry
        self.assertEqual(t.frame_count, 3)
        self.assertEqual(t.total_payload_bytes, 130)
        self.assertEqual(t.max_interframe_gap_ms, 120)

        done_lines = _find_logs(conn.logger, "[tts_sentence_done]")
        self.assertEqual(len(done_lines), 1)
        self.assertIn("reason=session_finished", done_lines[0])
        self.assertIn("session_finished_to_stop_ms=50", done_lines[0])
        self.assertIn("frames=3", done_lines[0])
        self.assertIn("bytes=130", done_lines[0])
        self.assertIn("max_gap_ms=120", done_lines[0])
        self.assertIn("aborted=0", done_lines[0])
        self.assertNotIn("TOP-SECRET-TEXT", done_lines[0])

    async def test_abort_terminal_once(self):
        clock = FakeClock()
        conn = _FakeTTSConn(clock)
        conn.tts_sentence_telemetry.note_sentence_started(conn.sentence_id)
        conn.tts_sentence_telemetry.note_audio_sent(conn.sentence_id, 40)
        await handleAbortMessage(conn)
        await handleAbortMessage(conn)
        done_lines = _find_logs(conn.logger, "[tts_sentence_done]")
        self.assertEqual(len(done_lines), 1)
        self.assertIn("reason=abort", done_lines[0])
        self.assertIn("aborted=1", done_lines[0])


class TestPreinitAudioDrop(unittest.IsolatedAsyncioTestCase):
    def _make_min_handler(self, **attrs):
        h = ConnectionHandler.__new__(ConnectionHandler)
        h.correlation_id = "testcid"
        h.device_id = "aa:bb:cc:dd:ee:ff"
        h.session_id = "session-current"
        h.hello_received = False
        h.protocol_version = None
        h.vad = None
        h.asr = None
        h.logger = MagicMock()
        h.websocket = FakeWS()
        h._binary_received_logged = False
        # 上行音频可观测性字段（_note_audio_frame 依赖）
        h.frames_received = 0
        h.frames_parsed_ok = 0
        h.frames_parse_failed = 0
        h.first_frame_monotonic_ms = None
        h.last_frame_monotonic_ms = None
        h.last_payload_bytes = 0
        h.total_payload_bytes = 0
        h.close_category = None
        for k, v in attrs.items():
            setattr(h, k, v)
        return h

    async def test_preinit_audio_drop_rate_limited(self):
        h = self._make_min_handler(hello_received=True, protocol_version=2)
        clock = FakeClock()
        h._monotonic_ms = clock
        for i in range(10):
            await h._route_message_inner(_v2_frame(payload=b"\x01" * 32))
            if i == 4:
                clock.advance(5001)
            else:
                clock.advance(10)
        self.assertEqual(h.preinit_audio_dropped, 10)
        warns = _find_warns(h.logger, "[preinit_audio_drop]")
        self.assertEqual(len(warns), 2)
        self.assertEqual(h._preinit_drop_field(), "preinit_audio_dropped=10")

    def test_note_audio_frame_version_none_is_na(self):
        h = self._make_min_handler()  # protocol_version=None
        clock = FakeClock()
        h._monotonic_ms = clock
        h._note_audio_frame(b"\x00" * 46)
        self.assertEqual(h.total_payload_bytes, 0)
        self.assertEqual(h.last_payload_bytes, 0)
        info = _find_logs(h.logger, "[audio_frame]")
        self.assertEqual(len(info), 1)
        self.assertIn("bytes=n/a", info[0])
        self.assertIn("total_bytes=0", info[0])


if __name__ == "__main__":
    unittest.main()
