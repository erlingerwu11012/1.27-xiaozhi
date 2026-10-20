"""Simulated Qwen3 ASR Realtime provider: no upstream Key, no production logs of audio."""
from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config.config_loader as config_loader


def _offline_config(config):
    local = dict(config)
    local["read_config_from_api"] = False
    return local


config_loader.get_config_from_api = _offline_config

from core.handle.abortHandle import handleAbortMessage
from core.handle.textHandler.listenMessageHandler import ListenTextMessageHandler
from core.providers.asr.qwen3_asr_realtime import (
    ASRProvider,
    Recognition,
    append_payload,
    session_update_payload,
)
from core.utils.speech_emotion import (
    UNKNOWN_CODE,
    build_llm_hint,
    inject_emotion_enabled,
    normalize_emotion,
    preview_text,
)
from core.utils.utterance_state import (
    confirm_speech,
    finish_utterance,
    on_listen_start,
    request_stop,
)


class FakeWS:
    def __init__(self):
        self.incoming = asyncio.Queue()
        self.outgoing = asyncio.Queue()
        self.closed = False
        self.fail_send_after = None
        self.sent_count = 0

    async def send(self, data):
        self.sent_count += 1
        if self.fail_send_after is not None and self.sent_count > self.fail_send_after:
            raise ConnectionError("upstream send failed")
        await self.outgoing.put(data)

    async def recv(self):
        return await self.incoming.get()

    async def close(self):
        self.closed = True


class FakeConn:
    def __init__(self, loop):
        self.loop = loop
        self.listen_epoch = 1
        self.session_id = "sess-test"
        self.stop_event = asyncio.Event()
        self.asr_audio = []
        self.client_listen_mode = "auto"
        self.audio_format = "pcm"
        self.client_voice_stop = False
        self.client_have_voice = False
        self.device_listening = True
        self.utterance_id = 0
        self.vad_speech_confirmed = False
        self.utterance_stop_id = 0
        self.utterance_stop_reason = None
        self.speech_turn_result = None
        self._audio_ingress_stats = {}
        self.delivered = []
        self.client_abort = False
        self.tts_abort_epoch = 0
        self.clear_queues = MagicMock()
        self.clearSpeakStatus = MagicMock()
        self.logger = MagicMock()
        self.logger.bind.return_value = self.logger
        self.config = {}
        on_listen_start(self)
        self.listen_epoch = 1
        self.device_listening = True

    def reset_vad_states(self, utterance_id=None):
        finish_utterance(self, utterance_id)


def _pcm_frame(tag=0, n=960):
    return bytes([tag & 0xFF, 0x01]) * n


def _append_tag(event):
    audio = base64.b64decode(event.get("audio") or "")
    return audio[0] if audio else None


async def _next_json(ws, timeout=1):
    return json.loads(await asyncio.wait_for(ws.outgoing.get(), timeout))


class SpeechEmotionTests(unittest.TestCase):
    def test_official_enum_and_unknown(self):
        self.assertEqual(normalize_emotion("happy"), "happy")
        self.assertEqual(normalize_emotion("HAPPY"), "happy")
        self.assertEqual(normalize_emotion(""), UNKNOWN_CODE)
        self.assertEqual(normalize_emotion("excited"), UNKNOWN_CODE)
        self.assertEqual(normalize_emotion(None), UNKNOWN_CODE)

    def test_preview_is_text_plus_stash_not_incremental_sum(self):
        self.assertEqual(preview_text("今天", "天气"), "今天天气")
        self.assertEqual(preview_text("今天天气不错，", ""), "今天天气不错，")

    def test_hint_is_reference_and_switch(self):
        self.assertFalse(inject_emotion_enabled({}))
        self.assertTrue(inject_emotion_enabled({"inject_emotion_hint": True}))
        hint = build_llm_hint({"emotion": "happy", "transcript": "你好"})
        self.assertIn("愉快", hint)
        self.assertIn("不是确定事实", hint)
        self.assertNotIn("你好", hint)


class RealtimeAsrProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.loop = asyncio.get_running_loop()
        self.sockets = []
        self.connect_gate = None
        self.connect_delay = 0
        self.connect_error = None
        self.conn = FakeConn(self.loop)
        self.provider = ASRProvider(
            {
                "api_key": "sk-test",
                "ws_url": "ws://mock/v1/realtime",
                "inject_emotion_hint": True,
                "ready_timeout": 1,
                "result_timeout": 1,
                "_connect": lambda url, headers: self._connect(url, headers),
            },
            True,
        )
        self.provider.handle_voice_stop = self._deliver
        self.ws = None

    async def asyncTearDown(self):
        await self.provider.close()

    async def _connect(self, url, headers):
        self.assertTrue(headers["Authorization"].startswith("Bearer sk-"))
        self.assertNotIn("dashscope", url)
        if self.connect_error:
            raise self.connect_error
        if self.connect_gate is not None:
            await self.connect_gate.wait()
        if self.connect_delay:
            await asyncio.sleep(self.connect_delay)
        ws = FakeWS()
        self.sockets.append(ws)
        self.ws = ws
        return ws

    async def _deliver(self, conn, audio, final_text=None, listen_epoch=None):
        conn.delivered.append(
            {
                "text": final_text,
                "epoch": listen_epoch,
                "emotion": getattr(conn, "speech_turn_result", None),
                "frames": list(audio),
                "tags": [f[0] for f in audio if f],
            }
        )

    async def _wait_ws(self, timeout=1):
        end = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < end:
            ctx = self.provider._current
            if ctx and ctx.reader and ctx.ws is not None:
                self.ws = ctx.ws
                return ctx.ws
            await asyncio.sleep(0.01)
        self.fail("upstream websocket was not created")

    async def _wait_idle(self, timeout=1):
        end = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < end:
            if self.provider._current is None:
                return
            await asyncio.sleep(0.01)
        self.fail("recognition did not close")

    async def _handshake(self, first_frame, have_voice=True):
        await self.provider.receive_audio(self.conn, first_frame, have_voice)
        ws = await self._wait_ws()
        await ws.incoming.put(json.dumps({"type": "session.created"}))
        update = await _next_json(ws)
        self.assertEqual(update["type"], "session.update")
        self.assertIsNone(update["session"]["turn_detection"])
        self.assertEqual(update["session"]["sample_rate"], 16000)
        self.assertNotIn("language", update["session"])
        await ws.incoming.put(
            json.dumps(
                {
                    "type": "session.updated",
                    "session": {
                        "model": "qwen3-asr-flash-realtime",
                        "input_audio_format": "pcm",
                        "sample_rate": 16000,
                    },
                }
            )
        )
        await asyncio.sleep(0.05)
        return ws

    async def _drain(self, ws, timeout=0.2):
        events = []
        while True:
            try:
                events.append(await _next_json(ws, timeout))
            except asyncio.TimeoutError:
                break
        return events

    async def _complete(self, ws, transcript, item_id="item-1", emotion="happy"):
        await ws.incoming.put(
            json.dumps(
                {
                    "type": "conversation.item.input_audio_transcription.completed",
                    "item_id": item_id,
                    "transcript": transcript,
                    "emotion": emotion,
                }
            )
        )
        await asyncio.sleep(0.05)

    async def test_streaming_commit_once_and_final_emotion(self):
        frames = [_pcm_frame(i + 1) for i in range(4)]
        ws = await self._handshake(frames[0])
        for frame in frames[1:]:
            await self.provider.receive_audio(self.conn, frame, True)
        request_stop(self.conn, "vad_silence")
        await self.provider.stop_listening(self.conn, reason="vad_silence")
        events = await self._drain(ws)
        appends = [e for e in events if e.get("type") == "input_audio_buffer.append"]
        commits = [e for e in events if e.get("type") == "input_audio_buffer.commit"]
        self.assertGreaterEqual(len(appends), 1)
        self.assertEqual(len(commits), 1)
        self.assertEqual([_append_tag(e) for e in appends], [1, 2, 3, 4])
        await ws.incoming.put(
            json.dumps(
                {
                    "type": "conversation.item.input_audio_transcription.text",
                    "item_id": "item-1",
                    "text": "今",
                    "stash": "天",
                    "emotion": "happy",
                }
            )
        )
        await ws.incoming.put(
            json.dumps(
                {
                    "type": "conversation.item.input_audio_transcription.text",
                    "item_id": "item-1",
                    "text": "今天",
                    "stash": "好",
                    "emotion": "happy",
                }
            )
        )
        await self._complete(ws, "今天好")
        finish = next(
            (e for e in await self._drain(ws, 0.3) if e.get("type") == "session.finish"),
            None,
        )
        if finish is None:
            finish = await _next_json(ws, 0.5)
        self.assertEqual(finish["type"], "session.finish")
        await asyncio.sleep(0.05)
        self.assertEqual(len(self.conn.delivered), 1)
        self.assertEqual(self.conn.delivered[0]["text"], "今天好")
        self.assertEqual(self.conn.delivered[0]["emotion"]["emotion"], "happy")
        self.assertEqual(self.conn.delivered[0]["emotion"]["item_id"], "item-1")

    async def test_empty_transcript_does_not_chat(self):
        frames = [_pcm_frame(1), _pcm_frame(2)]
        ws = await self._handshake(frames[0])
        request_stop(self.conn, "vad_silence")
        await self.provider.receive_audio(self.conn, frames[-1], False)
        await self._drain(ws)
        await self._complete(ws, "  ", item_id="item-2", emotion="neutral")
        await self._wait_idle()
        self.assertEqual(self.conn.delivered, [])

    async def test_silence_after_listen_does_not_open_session(self):
        starts = []
        orig = self.provider._start_recognition

        async def wrapped(conn):
            starts.append(1)
            await orig(conn)

        self.provider._start_recognition = wrapped
        for i in range(20):
            await self.provider.receive_audio(self.conn, _pcm_frame(i), False)
        self.assertEqual(starts, [])
        self.assertIsNone(self.provider._current)
        self.assertEqual(self.conn._audio_ingress_stats.get("empty_transcript", 0), 0)

    async def test_empty_then_full_sentence_same_listen(self):
        ws = await self._handshake(_pcm_frame(1))
        request_stop(self.conn, "vad_silence")
        await self.provider.receive_audio(self.conn, _pcm_frame(2), False)
        await self._drain(ws)
        await self._complete(ws, "   ", item_id="empty")
        await self._wait_idle()
        self.assertEqual(self.conn.delivered, [])
        self.ws = None
        ws2 = await self._handshake(_pcm_frame(10))
        await self.provider.receive_audio(self.conn, _pcm_frame(11), True)
        request_stop(self.conn, "vad_silence")
        await self.provider.receive_audio(self.conn, _pcm_frame(12), False)
        events = await self._drain(ws2)
        appends = [e for e in events if e.get("type") == "input_audio_buffer.append"]
        commits = [e for e in events if e.get("type") == "input_audio_buffer.commit"]
        self.assertEqual(len(commits), 1)
        self.assertEqual([_append_tag(e) for e in appends], [10, 11, 12])
        await self._complete(ws2, "把音量调大", item_id="item-ok")
        await self._wait_idle()
        self.assertEqual([d["text"] for d in self.conn.delivered], ["把音量调大"])

    async def test_modes_auto_manual_realtime(self):
        for mode in ("auto", "manual", "realtime"):
            with self.subTest(mode=mode):
                self.conn.client_listen_mode = mode
                self.ws = None
                await self.provider.close()
                self.provider._closed = False
                self.conn.delivered.clear()
                on_listen_start(self.conn)
                self.conn.device_listening = True
                ws = await self._handshake(_pcm_frame(1))
                request_stop(self.conn, "vad_silence")
                await self.provider.receive_audio(self.conn, _pcm_frame(2), False)
                await self._drain(ws)
                await self._complete(ws, f"模式{mode}", item_id=mode)
                await self._wait_idle()
                self.assertEqual(self.conn.delivered[-1]["text"], f"模式{mode}")

    async def test_manual_without_listen_stop_does_two_sentences(self):
        self.conn.client_listen_mode = "manual"
        ws = await self._handshake(_pcm_frame(1))
        request_stop(self.conn, "vad_silence")
        await self.provider.receive_audio(self.conn, _pcm_frame(2), False)
        await self._drain(ws)
        await self._complete(ws, "第一句", item_id="u1")
        await self._wait_idle()
        self.ws = None
        ws2 = await self._handshake(_pcm_frame(8))
        request_stop(self.conn, "vad_silence")
        await self.provider.receive_audio(self.conn, _pcm_frame(9), False)
        await self._drain(ws2)
        await self._complete(ws2, "第二句", item_id="u2")
        await self._wait_idle()
        self.assertEqual([d["text"] for d in self.conn.delivered], ["第一句", "第二句"])

    async def test_device_stop_flushes_then_commits_once(self):
        ws = await self._handshake(_pcm_frame(1))
        await self.provider.receive_audio(self.conn, _pcm_frame(2), True)
        await self.provider.receive_audio(self.conn, _pcm_frame(3), True)
        request_stop(self.conn, "device_stop")
        await self.provider.stop_listening(self.conn, reason="device_stop")
        events = await self._drain(ws)
        appends = [e for e in events if e.get("type") == "input_audio_buffer.append"]
        commits = [e for e in events if e.get("type") == "input_audio_buffer.commit"]
        self.assertEqual([_append_tag(e) for e in appends], [1, 2, 3])
        self.assertEqual(len(commits), 1)
        await self.provider.stop_listening(self.conn, reason="device_stop")
        extra = await self._drain(ws, 0.1)
        self.assertEqual(
            [e for e in extra if e.get("type") == "input_audio_buffer.commit"], []
        )

    async def test_audio_and_stop_while_waiting_session_updated(self):
        await self.provider.receive_audio(self.conn, _pcm_frame(1), True)
        ws = await self._wait_ws()
        await ws.incoming.put(json.dumps({"type": "session.created"}))
        await _next_json(ws)
        await self.provider.receive_audio(self.conn, _pcm_frame(2), True)
        request_stop(self.conn, "vad_silence")
        await self.provider.receive_audio(self.conn, _pcm_frame(3), False)
        await ws.incoming.put(json.dumps({"type": "session.updated", "session": {}}))
        events = await self._drain(ws, 0.4)
        appends = [e for e in events if e.get("type") == "input_audio_buffer.append"]
        commits = [e for e in events if e.get("type") == "input_audio_buffer.commit"]
        self.assertEqual([_append_tag(e) for e in appends], [1, 2, 3])
        self.assertEqual(len(commits), 1)

    async def test_handoff_next_sentence_not_mixed(self):
        ws = await self._handshake(_pcm_frame(1))
        await self.provider.receive_audio(self.conn, _pcm_frame(2), True)
        request_stop(self.conn, "vad_silence")
        await self.provider.stop_listening(self.conn, reason="vad_silence")
        first = await self._drain(ws)
        first_tags = [
            _append_tag(e)
            for e in first
            if e.get("type") == "input_audio_buffer.append"
        ]
        self.assertEqual(first_tags, [1, 2])
        await self.provider.receive_audio(self.conn, _pcm_frame(20), True)
        await self.provider.receive_audio(self.conn, _pcm_frame(21), True)
        ctx = self.provider._current
        self.assertEqual([f[0] for f in ctx.handoff], [20, 21])
        await self._complete(ws, "上一句", item_id="old")
        await asyncio.sleep(0.05)
        ws2 = await self._wait_ws()
        await ws2.incoming.put(json.dumps({"type": "session.created"}))
        await _next_json(ws2)
        await ws2.incoming.put(json.dumps({"type": "session.updated", "session": {}}))
        await self.provider.receive_audio(self.conn, _pcm_frame(22), True)
        request_stop(self.conn, "vad_silence")
        await self.provider.receive_audio(self.conn, _pcm_frame(23), False)
        second = await self._drain(ws2, 0.4)
        second_tags = [
            _append_tag(e)
            for e in second
            if e.get("type") == "input_audio_buffer.append"
        ]
        self.assertTrue(set(second_tags).isdisjoint({1, 2}))
        self.assertEqual(second_tags[:2], [20, 21])
        await self._complete(ws2, "下一句", item_id="new")
        await self._wait_idle()
        self.assertEqual([d["text"] for d in self.conn.delivered], ["上一句", "下一句"])
        self.assertNotIn(1, self.conn.delivered[1]["tags"])
        self.assertIn(20, self.conn.delivered[1]["tags"])

    async def test_duplicate_and_late_results_rejected(self):
        ws = await self._handshake(_pcm_frame(1))
        request_stop(self.conn, "vad_silence")
        await self.provider.receive_audio(self.conn, _pcm_frame(1), False)
        await self._drain(ws)
        await ws.incoming.put(
            json.dumps(
                {
                    "type": "conversation.item.input_audio_transcription.text",
                    "item_id": "keep",
                    "text": "好",
                    "stash": "",
                }
            )
        )
        await self._complete(ws, "好", item_id="keep")
        await self._complete(ws, "好重复", item_id="keep")
        await self._wait_idle()
        self.assertEqual([d["text"] for d in self.conn.delivered], ["好"])
        await ws.incoming.put(
            json.dumps(
                {
                    "type": "conversation.item.input_audio_transcription.completed",
                    "item_id": "late",
                    "transcript": "迟到",
                }
            )
        )
        await asyncio.sleep(0.05)
        self.assertEqual([d["text"] for d in self.conn.delivered], ["好"])

    async def test_stale_epoch_is_dropped(self):
        await self.provider.receive_audio(self.conn, _pcm_frame(), True)
        ws = await self._wait_ws()
        await ws.incoming.put(json.dumps({"type": "session.created"}))
        await _next_json(ws)
        self.conn.listen_epoch = 2
        await ws.incoming.put(
            json.dumps(
                {
                    "type": "session.updated",
                    "session": {"sample_rate": 16000, "input_audio_format": "pcm"},
                }
            )
        )
        await ws.incoming.put(
            json.dumps(
                {
                    "type": "conversation.item.input_audio_transcription.completed",
                    "item_id": "old",
                    "transcript": "过期结果",
                    "emotion": "sad",
                }
            )
        )
        await asyncio.sleep(0.05)
        self.assertEqual(self.conn.delivered, [])

    async def test_new_listen_abort_and_disconnect(self):
        ws = await self._handshake(_pcm_frame(1))
        await self.provider.start_listening(self.conn, reason="new_listen")
        await asyncio.sleep(0.05)
        self.assertTrue(ws.closed)
        self.assertEqual(self.conn.delivered, [])
        ws2 = await self._handshake(_pcm_frame(5))
        await self.provider.abort_listening(self.conn)
        await asyncio.sleep(0.05)
        self.assertTrue(ws2.closed)
        self.ws = None
        ws3 = await self._handshake(_pcm_frame(7))
        self.conn.stop_event.set()
        await self.provider.close()
        await asyncio.sleep(0.05)
        self.assertTrue(ws3.closed)
        self.assertTrue(self.provider._closed)

    async def test_short_command_commits_without_15_frame_gate(self):
        ws = await self._handshake(_pcm_frame(1))
        await self.provider.receive_audio(self.conn, _pcm_frame(2), True)
        request_stop(self.conn, "vad_silence")
        await self.provider.receive_audio(self.conn, _pcm_frame(3), False)
        events = await self._drain(ws)
        self.assertEqual(
            len([e for e in events if e.get("type") == "input_audio_buffer.commit"]), 1
        )
        await self._complete(ws, "好", item_id="short")
        await self._wait_idle()
        self.assertEqual(self.conn.delivered[0]["text"], "好")

    async def test_ready_timeout_and_result_timeout_and_send_fail_and_buffer_full(self):
        self.provider.ready_timeout = 0.05
        await self.provider.receive_audio(self.conn, _pcm_frame(1), True)
        ws = await self._wait_ws()
        await asyncio.sleep(0.2)
        await self._wait_idle()
        self.assertTrue(ws.closed)
        self.assertEqual(self.conn.delivered, [])

        self.provider.ready_timeout = 1
        self.provider.result_timeout = 0.05
        self.ws = None
        on_listen_start(self.conn)
        self.conn.device_listening = True
        ws = await self._handshake(_pcm_frame(2))
        request_stop(self.conn, "vad_silence")
        await self.provider.receive_audio(self.conn, _pcm_frame(2), False)
        await self._drain(ws)
        await asyncio.sleep(0.2)
        await self._wait_idle()
        self.assertEqual(self.conn.delivered, [])

        self.provider.result_timeout = 1
        self.ws = None
        on_listen_start(self.conn)
        self.conn.device_listening = True
        self.connect_error = ConnectionError("boom")
        await self.provider.receive_audio(self.conn, _pcm_frame(3), True)
        await asyncio.sleep(0.1)
        self.assertIsNone(self.provider._current)
        self.connect_error = None

        self.ws = None
        on_listen_start(self.conn)
        self.conn.device_listening = True
        self.connect_gate = asyncio.Event()
        await self.provider.receive_audio(self.conn, _pcm_frame(1), True)
        for i in range(60):
            await self.provider.receive_audio(self.conn, _pcm_frame(i + 2), True)
        ctx = self.provider._current
        self.assertLessEqual(len(ctx.pending), 50)
        self.assertGreaterEqual(
            self.conn._audio_ingress_stats.get("drop_ready_buffer_full", 0), 1
        )
        self.connect_gate.set()
        await self._wait_ws()
        self.connect_gate = None

    async def test_two_sessions_use_isolated_state(self):
        a = Recognition(epoch=1, session_id="a")
        b = Recognition(epoch=2, session_id="b")
        a.decoder = object()
        b.decoder = object()
        self.assertIsNot(a.decoder, b.decoder)
        a.transcript = "one"
        self.assertEqual(b.transcript, "")
        p2 = ASRProvider(
            {
                "api_key": "sk-test",
                "ws_url": "ws://mock/v1/realtime",
                "_connect": lambda url, headers: self._connect(url, headers),
            },
            True,
        )
        c2 = FakeConn(self.loop)
        c2.session_id = "sess-b"
        p2.handle_voice_stop = self._deliver
        await self.provider.receive_audio(self.conn, _pcm_frame(1), True)
        await p2.receive_audio(c2, _pcm_frame(9), True)
        await asyncio.sleep(0.05)
        self.assertIsNot(self.provider._current, p2._current)
        self.assertIsNot(self.provider._current.decoder, p2._current.decoder)
        await p2.close()

    def test_session_update_does_not_force_zh(self):
        payload = session_update_payload(16000, None)
        self.assertNotIn("language", json.dumps(payload))
        self.assertIsNone(payload["session"]["turn_detection"])
        chunk = append_payload(_pcm_frame())
        self.assertEqual(chunk["type"], "input_audio_buffer.append")


class ListenHandlerModeTests(unittest.IsolatedAsyncioTestCase):
    async def test_listen_start_does_not_mark_speech(self):
        conn = FakeConn(asyncio.get_running_loop())
        conn.asr = MagicMock()
        conn.asr.start_listening = MagicMock(return_value=None)
        handler = ListenTextMessageHandler()
        await handler.handle(conn, {"type": "listen", "state": "start", "mode": "manual"})
        self.assertEqual(conn.client_listen_mode, "manual")
        self.assertTrue(conn.device_listening)
        self.assertFalse(conn.client_have_voice)
        self.assertFalse(conn.vad_speech_confirmed)

    async def test_listen_stop_source_is_device(self):
        conn = FakeConn(asyncio.get_running_loop())
        conn.asr = MagicMock()
        conn.asr.stop_listening = MagicMock(return_value=None)
        confirm_speech(conn)
        handler = ListenTextMessageHandler()
        await handler.handle(conn, {"type": "listen", "state": "stop", "mode": "auto"})
        self.assertEqual(conn.utterance_stop_reason, "device_stop")
        self.assertFalse(conn.device_listening)

    async def test_abort_cancels_asr(self):
        loop = asyncio.get_running_loop()
        conn = FakeConn(loop)
        cancelled = []

        async def abort_listening(_conn):
            cancelled.append(True)

        conn.asr = MagicMock()
        conn.asr.abort_listening = abort_listening
        conn.tts = None
        conn._mask = lambda x: x
        conn.tts_sentence_telemetry = None
        with patch(
            "core.handle.abortHandle.guarded_ws_send",
            new=AsyncMock(return_value=True),
        ):
            await handleAbortMessage(conn)
        self.assertEqual(cancelled, [True])


if __name__ == "__main__":
    unittest.main()
