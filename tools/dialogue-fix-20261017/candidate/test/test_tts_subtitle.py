"""TTS 字幕时序统一出站层测试。"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.handle.intentHandler import speak_txt
from core.handle.receiveAudioHandle import check_bind_device, max_out_size
from core.handle.sendAudioHandle import sendAudioMessage, send_tts_message, speak_text_with_subtitle
from core.providers.tts.base import TTSProviderBase
from core.providers.tts.dto.dto import ContentType, SentenceType


class TtsSequenceRecorder:
    """记录 tts.start / sentence_start / audio / stop 顺序。"""

    def __init__(self):
        self.events = []

    def note(self, kind, **meta):
        self.events.append((kind, meta))

    def assert_single_cycle(self, testcase):
        starts = [i for i, e in enumerate(self.events) if e[0] == "start"]
        stops = [i for i, e in enumerate(self.events) if e[0] == "stop"]
        ss = [i for i, e in enumerate(self.events) if e[0] == "sentence_start"]
        audios = [i for i, e in enumerate(self.events) if e[0] == "audio"]
        testcase.assertEqual(len(starts), 1, self.events)
        testcase.assertEqual(len(stops), 1, self.events)
        testcase.assertEqual(len(ss), 1, self.events)
        testcase.assertGreaterEqual(len(audios), 1, self.events)
        testcase.assertLess(starts[0], ss[0], self.events)
        testcase.assertLess(ss[0], audios[0], self.events)
        testcase.assertLess(audios[-1], stops[0], self.events)


def _make_conn(recorder: TtsSequenceRecorder):
    conn = MagicMock()
    conn.session_id = "s1"
    conn.sentence_id = "sent-1"
    conn.device_id = "dev-1"
    conn.superseded = False
    conn._outbound_closed = False
    conn.client_abort = False
    conn.client_is_speaking = False
    conn.close_after_chat = False
    conn.last_activity_time = 0
    conn.config = {"enable_stop_tts_notify": False, "tts_audio_send_delay": -1}
    conn.conn_from_mqtt_gateway = False
    conn.audio_protocol_version = 0
    conn._tts_start_sent = False
    conn.tts = MagicMock()
    conn.tts.tts_audio_first_sentence = True
    conn.tts.tts_text_queue = MagicMock()
    conn.tts.tts_audio_queue = MagicMock()
    conn.logger = MagicMock()
    conn.clearSpeakStatus = MagicMock()
    conn._cid = MagicMock(return_value="cid=test")
    conn.has_pending_mcp_calls = MagicMock(return_value=False)
    conn.close = AsyncMock()

    async def _send_tts(conn, state, text=None):
        recorder.note(state, text=text)

    async def _send_audio(conn, audios, frame_duration=60, *, subtitle_exempt=False):
        if subtitle_exempt:
            recorder.note("audio_exempt")
        else:
            recorder.note("audio", bytes=len(audios) if isinstance(audios, bytes) else "list")

    conn._recorder = recorder
    return conn


class TestSpeakTextWithSubtitle(unittest.TestCase):
    def test_enqueues_first_middle_last_for_text(self):
        conn = MagicMock()
        conn.session_id = "s1"
        conn.sentence_id = "sent-1"
        conn.tts = MagicMock()
        conn.tts.tts_text_queue = MagicMock()
        conn.tts.tts_audio_queue = MagicMock()
        conn.logger = MagicMock()
        with patch(
            "core.handle.sendAudioHandle.enqueue_tts",
            side_effect=lambda c, dto: c.tts.tts_text_queue.put(dto),
        ):
            speak_text_with_subtitle(conn, "你好世界")
        calls = conn.tts.tts_text_queue.put.call_args_list
        types = [c[0][0].sentence_type for c in calls]
        self.assertEqual(types[0], SentenceType.FIRST)
        self.assertEqual(types[-1], SentenceType.LAST)

    def test_subtitle_exempt_skips_text_queue(self):
        conn = MagicMock()
        conn.session_id = "s1"
        conn.logger = MagicMock()
        conn.tts = MagicMock()
        conn.tts.tts_text_queue = MagicMock()
        conn.tts.tts_audio_queue = MagicMock()
        speak_text_with_subtitle(conn, "", audio_packets=[b"\x00"], subtitle_exempt=True)
        conn.tts.tts_text_queue.put.assert_not_called()
        conn.tts.tts_audio_queue.put.assert_called()


class TestTtsSequencePaths(unittest.IsolatedAsyncioTestCase):
    async def _run_send_audio_message_cycle(self, conn, recorder):
        async def record_control(c,state,text=None):
            recorder.note(state,text=text)
            from core.utils.tts_stream import current_stream
            if state=='start':
                c._tts_start_sent=True;c._tts_start_owner=current_stream(c)
            elif state=='stop':c._tts_start_sent=False
        with patch(
            "core.handle.sendAudioHandle.send_tts_message",
            side_effect=record_control,
        ), patch(
            "core.handle.sendAudioHandle.sendAudio",
            side_effect=lambda c, audios, **kw: recorder.note("audio"),
        ), patch(
            "core.handle.sendAudioHandle.is_outbound_allowed",
            return_value=True,
        ):
            await sendAudioMessage(conn, SentenceType.FIRST, [], "测试文本")
            await sendAudioMessage(conn, SentenceType.MIDDLE, b"\x01" * 20, None)
            await sendAudioMessage(conn, SentenceType.LAST, [], "测试文本")

    async def test_llm_speak_txt_sequence(self):
        recorder = TtsSequenceRecorder()
        conn = _make_conn(recorder)
        conn.dialogue = MagicMock()
        with patch(
            "core.handle.sendAudioHandle.enqueue_tts",
            side_effect=lambda c, dto: c.tts.tts_text_queue.put(dto),
        ):
            speak_txt(conn, "这是 LLM 回复。")
        calls = conn.tts.tts_text_queue.put.call_args_list
        types = [c[0][0].sentence_type for c in calls]
        self.assertEqual(types[0], SentenceType.FIRST)
        self.assertEqual(types[-1], SentenceType.LAST)

    async def test_max_out_size_sequence(self):
        recorder = TtsSequenceRecorder()
        conn = _make_conn(recorder)
        conn.bind_code = None
        conn.need_bind = False
        with patch(
            "core.handle.receiveAudioHandle.send_stt_message",
            new=AsyncMock(),
        ), patch(
            "core.handle.receiveAudioHandle.audio_to_data",
            return_value=[b"\x00", b"\x01"],
        ), patch(
            "core.handle.receiveAudioHandle.speak_text_with_subtitle",
            wraps=speak_text_with_subtitle,
        ) as mocked:
            await max_out_size(conn)
            mocked.assert_called_once()
            args = mocked.call_args
            self.assertIn("不好意思", args[0][1])
            self.assertIsNotNone(args[0][2])

    async def test_bind_code_full_digits_single_cycle(self):
        recorder = TtsSequenceRecorder()
        conn = _make_conn(recorder)
        conn.bind_code = "123456"
        with patch(
            "core.handle.receiveAudioHandle.send_stt_message",
            new=AsyncMock(),
        ), patch(
            "core.handle.receiveAudioHandle.audio_to_data",
            side_effect=lambda path, **kw: [path.encode()],
        ), patch(
            "core.handle.receiveAudioHandle.speak_text_with_subtitle",
            wraps=speak_text_with_subtitle,
        ) as mocked:
            await check_bind_device(conn)
            mocked.assert_called_once()
            text, packets = mocked.call_args[0][1], mocked.call_args[0][2]
            self.assertIn("123456", text)
            self.assertEqual(len(packets), 7)

    async def test_tts_one_sentence_delegates_unified(self):
        conn = MagicMock()
        conn.session_id = "s1"
        conn.sentence_id = "sent-1"
        with patch(
            "core.handle.sendAudioHandle.speak_text_with_subtitle"
        ) as mocked:
            TTSProviderBase.tts_one_sentence(
                MagicMock(), conn, ContentType.TEXT, content_detail="工具直返。"
            )
            mocked.assert_called_once_with(conn, "工具直返。")

    async def test_stop_tts_notify_subtitle_exempt(self):
        recorder = TtsSequenceRecorder()
        conn = _make_conn(recorder)
        conn.config = {"enable_stop_tts_notify": True, "stop_tts_notify_voice": "x.wav"}
        with patch(
            "core.handle.sendAudioHandle.is_outbound_allowed",
            return_value=True,
        ), patch(
            "core.handle.sendAudioHandle.audio_to_data",
            return_value=[b"\x00"],
        ), patch(
            "core.handle.sendAudioHandle.sendAudio",
            side_effect=lambda c, audios, **kw: recorder.note(
                "audio_exempt" if kw.get("subtitle_exempt") else "audio"
            ),
        ), patch(
            "core.handle.sendAudioHandle._device_send",
            new=AsyncMock(return_value=(True, 1.0)),
        ):
            await send_tts_message(conn, "stop", None)
        self.assertIn(("audio_exempt", {}), recorder.events)
        ss = [e for e in recorder.events if e[0] == "sentence_start"]
        self.assertEqual(ss, [])

    async def test_send_audio_message_single_start_stop(self):
        recorder = TtsSequenceRecorder()
        conn = _make_conn(recorder)
        await self._run_send_audio_message_cycle(conn, recorder)
        recorder.assert_single_cycle(self)

    async def test_abort_after_first_does_not_reset_abort_flag(self):
        recorder = TtsSequenceRecorder()
        conn = _make_conn(recorder)
        conn.client_abort = True
        with patch(
            "core.handle.sendAudioHandle.send_tts_message",
            new=AsyncMock(),
        ), patch(
            "core.handle.sendAudioHandle.sendAudio",
            new=AsyncMock(),
        ), patch(
            "core.handle.sendAudioHandle.is_outbound_allowed",
            return_value=True,
        ):
            await sendAudioMessage(conn, SentenceType.FIRST, [], "x")
        self.assertTrue(conn.client_abort)


if __name__ == "__main__":
    unittest.main()
