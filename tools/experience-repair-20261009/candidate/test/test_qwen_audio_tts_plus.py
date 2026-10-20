"""Simulated Qwen Audio TTS Plus: PCM framing, abort isolation, no Aliyun Key."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import threading
import unittest
import uuid
from collections import OrderedDict
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config.config_loader as config_loader


def _offline_config(config):
    local = dict(config)
    local["read_config_from_api"] = False
    return local


config_loader.get_config_from_api = _offline_config

import websockets

from core.handle.abortHandle import handleAbortMessage
from core.providers.tts.dto.dto import ContentType, SentenceType, TTSMessageDTO
from core.utils.device_outbound import (
    enqueue_tts,
    resolve_enqueue_abort_epoch,
    begin_tts_turn,
    TTS_SENTENCE_EPOCH_LIMIT,
)
from core.providers.tts.qwen_audio_tts_plus import (
    DEVICE_SAMPLE_RATE,
    QwenTtsExpired,
    QwenTtsTimeout,
    TTSProvider,
    _bearer,
    resample_pcm16_mono,
    to_uuid,
)
from core.utils import opus_encoder_utils


RUN_TASK_KEYS = ("task_group", "task", "function", "model", "parameters", "input")
RUN_TASK_PARAM_KEYS = (
    "text_type",
    "voice",
    "format",
    "sample_rate",
    "volume",
    "rate",
    "pitch",
)


class FakeWS:
    def __init__(self):
        self.incoming = asyncio.Queue()
        self.outgoing = asyncio.Queue()
        self.closed = False
        self.close_calls = 0

    async def send(self, data):
        if self.closed:
            raise websockets.ConnectionClosed(None, None)
        await self.outgoing.put(data)

    async def recv(self):
        item = await self.incoming.get()
        if item is None or self.closed:
            raise websockets.ConnectionClosed(None, None)
        return item

    async def close(self):
        self.close_calls += 1
        if self.closed:
            return
        self.closed = True
        try:
            self.incoming.put_nowait(None)
        except Exception:
            pass


class FakeServer:
    def is_current_connection(self, device_id, conn):
        return True

    async def send_to_current(self, device_id, data, **kwargs):
        return True


class FakeConn:
    def __init__(self, loop, session_id="sess-tts", device_id="b8:f8:62:7e:ca:58"):
        self.loop = loop
        self.session_id = session_id
        self.device_id = device_id
        self.sentence_id = uuid.uuid4().hex
        self.stop_event = asyncio.Event()
        self.client_abort = False
        self.tts_abort_epoch = 0
        self.tts_sentence_epochs = OrderedDict()
        self.tts_MessageText = None
        self.superseded = False
        self.server = FakeServer()
        self.tts = None
        self.logger = MagicMock()
        self.logger.bind.return_value = self.logger
        self.asr = None

    def clear_queues(self):
        tts = getattr(self, "tts", None)
        if tts is None:
            return
        for name in ("tts_text_queue", "tts_audio_queue"):
            q = getattr(tts, name, None)
            if q is None or not hasattr(q, "get_nowait"):
                continue
            try:
                while True:
                    q.get_nowait()
            except Exception:
                break

    def clearSpeakStatus(self):
        self.client_is_speaking = False

    def _mask(self, value):
        return value


def _assert_run_task_shape(testcase, msg):
    testcase.assertEqual(msg["header"]["action"], "run-task")
    testcase.assertEqual(msg["header"]["streaming"], "duplex")
    testcase.assertTrue(msg["header"]["task_id"])
    testcase.assertEqual(set(msg["payload"].keys()), set(RUN_TASK_KEYS))
    testcase.assertEqual(msg["payload"]["task_group"], "audio")
    testcase.assertEqual(msg["payload"]["task"], "tts")
    testcase.assertEqual(msg["payload"]["function"], "SpeechSynthesizer")
    testcase.assertEqual(msg["payload"]["model"], "qwen-audio-3.0-tts-plus")
    testcase.assertEqual(msg["payload"]["input"], {})
    testcase.assertEqual(set(msg["payload"]["parameters"].keys()), set(RUN_TASK_PARAM_KEYS))
    params = msg["payload"]["parameters"]
    testcase.assertEqual(params["text_type"], "PlainText")
    testcase.assertEqual(params["voice"], "longanlingxi")
    testcase.assertEqual(params["format"], "pcm")
    testcase.assertEqual(params["sample_rate"], 16000)
    testcase.assertEqual(params["volume"], 50)
    testcase.assertEqual(params["rate"], 1.0)
    testcase.assertEqual(params["pitch"], 1.0)


def _assert_continue_task_shape(testcase, msg, task_id):
    testcase.assertEqual(msg["header"]["action"], "continue-task")
    testcase.assertEqual(msg["header"]["streaming"], "duplex")
    testcase.assertEqual(msg["header"]["task_id"], task_id)
    testcase.assertEqual(set(msg["payload"].keys()), {"input"})
    testcase.assertEqual(set(msg["payload"]["input"].keys()), {"text"})
    testcase.assertTrue(msg["payload"]["input"]["text"])


def _assert_finish_task_shape(testcase, msg, task_id):
    testcase.assertEqual(msg["header"]["action"], "finish-task")
    testcase.assertEqual(msg["header"]["streaming"], "duplex")
    testcase.assertEqual(msg["header"]["task_id"], task_id)
    testcase.assertEqual(msg["payload"], {"input": {}})


class TtsHelperTests(unittest.TestCase):
    def test_uuid_and_pcm_frame_size(self):
        dashed = to_uuid("a" * 32)
        self.assertEqual(len(dashed), 36)
        encoder = opus_encoder_utils.OpusEncoderUtils(
            sample_rate=DEVICE_SAMPLE_RATE, channels=1, frame_size_ms=60
        )
        self.assertEqual(encoder.frame_size, 960)
        frames = []
        pcm = b"\x00\x01" * 960
        encoder.encode_pcm_to_opus_stream(pcm, False, callback=frames.append)
        self.assertEqual(len(frames), 1)
        encoder.encode_pcm_to_opus_stream(b"\x00\x01" * 100, True, callback=frames.append)
        self.assertEqual(len(frames), 2)

    def test_resample_keeps_carry(self):
        pcm, carry = resample_pcm16_mono(b"\x00\x10" * 24, 24000, 16000, b"")
        self.assertTrue(len(pcm) % 2 == 0)
        self.assertTrue(carry)

    def test_bearer_prefixes_sk_like_asr(self):
        self.assertTrue(_bearer("GbYexampletoken").startswith("sk-"))
        self.assertEqual(_bearer("sk-already"), "sk-already")

    def test_strip_emotion_tags(self):
        from core.utils.textUtils import strip_all_emotion_tags

        self.assertEqual(strip_all_emotion_tags("[emotion:happy]你好"), "你好")
        self.assertEqual(strip_all_emotion_tags("[emotion: neutral]嘿"), "嘿")
        self.assertEqual(strip_all_emotion_tags(""), "")

    def test_strip_emotion_tags(self):
        from core.utils.textUtils import strip_all_emotion_tags

        self.assertEqual(strip_all_emotion_tags("[emotion:happy]你好"), "你好")
        self.assertEqual(strip_all_emotion_tags("[emotion: neutral]嘿"), "嘿")
        self.assertEqual(strip_all_emotion_tags(""), "")


class TtsStreamTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.loop = asyncio.get_running_loop()
        self.ws = FakeWS()
        self.conn = FakeConn(self.loop)
        self.provider = TTSProvider(
            {
                "api_key": "sk-test",
                "ws_url": "ws://127.0.0.1:3011/bailian/api-ws/v1/inference",
                "model": "qwen-audio-3.0-tts-plus",
                "voice": "longanlingxi",
                "sample_rate": 16000,
                "_connect": lambda url, headers: self._connect(url, headers),
            },
            True,
        )
        self.provider.conn = self.conn
        self.conn.tts = self.provider
        self.encoded = []
        self.provider.handle_opus = lambda data: self.encoded.append(data)

    async def asyncTearDown(self):
        try:
            await self.provider.close()
        except Exception:
            pass

    async def _connect(self, url, headers):
        self.assertIn("/bailian/api-ws/v1/inference", url)
        self.assertTrue(headers["Authorization"].startswith("Bearer sk-"))
        return self.ws

    async def _start_and_ack(self, ws=None):
        ws = ws or self.ws
        start = asyncio.create_task(self.provider.start_session(self.conn.sentence_id))
        run = json.loads(await asyncio.wait_for(ws.outgoing.get(), 1))
        _assert_run_task_shape(self, run)
        await ws.incoming.put(
            json.dumps(
                {
                    "header": {
                        "event": "task-started",
                        "task_id": run["header"]["task_id"],
                    }
                }
            )
        )
        await start
        return run

    async def test_wait_for_task_started_then_stream_pcm(self):
        run = await self._start_and_ack()
        await self.provider.text_to_speak("你好", None)
        cont = json.loads(await asyncio.wait_for(self.ws.outgoing.get(), 1))
        _assert_continue_task_shape(self, cont, run["header"]["task_id"])
        await self.ws.incoming.put(b"\x00\x01" * 960)
        await asyncio.sleep(0.05)
        self.assertGreaterEqual(len(self.encoded), 1)
        finish = asyncio.create_task(self.provider.finish_session(self.provider.task_id))
        fin = json.loads(await asyncio.wait_for(self.ws.outgoing.get(), 1))
        _assert_finish_task_shape(self, fin, run["header"]["task_id"])
        await self.ws.incoming.put(
            json.dumps(
                {
                    "header": {
                        "event": "task-finished",
                        "task_id": self.provider.task_id,
                    }
                }
            )
        )
        await finish
        self.assertTrue(self.encoded)

    async def test_official_caption_does_not_emit_legacy_full_turn_again(self):
        self.conn.tts_MessageText = '[apologetic]这是一整段旧旁路字幕。'
        seen = []
        self.provider._put_audio = lambda sess, message: seen.append(message)
        start = asyncio.create_task(self.provider.start_session(
            self.conn.sentence_id, caption_text='这是一句正确字幕。'))
        run = json.loads(await asyncio.wait_for(self.ws.outgoing.get(), 1))
        task_id = run['header']['task_id']
        await self.ws.incoming.put(json.dumps({'header': {'event': 'task-started', 'task_id': task_id}}))
        await start
        await self.ws.incoming.put(json.dumps({'header': {'event': 'result-generated', 'task_id': task_id}}))
        await self.ws.incoming.put(json.dumps({'header': {'event': 'result-generated', 'task_id': task_id}}))
        await asyncio.sleep(.02)
        self.assertEqual([m for m in seen if m[0] == SentenceType.FIRST],
                         [(SentenceType.FIRST, [], '这是一句正确字幕。')])

    async def test_emotion_tags_are_stripped_before_speak(self):
        run = await self._start_and_ack()
        await self.provider.text_to_speak("[emotion:happy]你好呀", None)
        cont = json.loads(await asyncio.wait_for(self.ws.outgoing.get(), 1))
        _assert_continue_task_shape(self, cont, run["header"]["task_id"])
        self.assertEqual(cont["payload"]["input"]["text"], "你好呀")
        self.assertNotIn("emotion", cont["payload"]["input"]["text"])

    async def test_emotion_tags_are_stripped_before_speak(self):
        run = await self._start_and_ack()
        await self.provider.text_to_speak("[emotion:happy]你好呀", None)
        cont = json.loads(await asyncio.wait_for(self.ws.outgoing.get(), 1))
        _assert_continue_task_shape(self, cont, run["header"]["task_id"])
        self.assertEqual(cont["payload"]["input"]["text"], "你好呀")
        self.assertNotIn("emotion", cont["payload"]["input"]["text"])

    async def test_abort_stops_old_session(self):
        await self._start_and_ack()
        self.conn.client_abort = True
        self.conn.tts_abort_epoch = 1
        close = self.provider.cancel_session()
        if asyncio.iscoroutine(close):
            await close
        self.assertTrue(self.ws.closed)
        self.assertIsNone(self.provider.ws)


class TtsAbortRecoverTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.loop = asyncio.get_running_loop()
        self.sockets = []
        self.connect_gate = asyncio.Event()
        self.connect_gate.set()
        self.connect_delay_event = None
        self.conn = FakeConn(self.loop)
        self.provider = TTSProvider(
            {
                "api_key": "sk-test",
                "ws_url": "ws://127.0.0.1:3011/bailian/api-ws/v1/inference",
                "model": "qwen-audio-3.0-tts-plus",
                "voice": "longanlingxi",
                "sample_rate": 16000,
                "_connect": self._connect,
            },
            True,
        )
        self.provider.conn = self.conn
        self.conn.tts = self.provider
        self.encoded = []
        self.provider.handle_opus = lambda data: self.encoded.append(data)

    async def asyncTearDown(self):
        self.conn.stop_event.set()
        try:
            await self.provider.close()
        except Exception:
            pass

    async def _connect(self, url, headers):
        self.assertIn("/bailian/api-ws/v1/inference", url)
        self.assertTrue(headers["Authorization"].startswith("Bearer sk-"))
        await self.connect_gate.wait()
        if self.connect_delay_event is not None:
            await self.connect_delay_event.wait()
        ws = FakeWS()
        self.sockets.append(ws)
        return ws

    async def _ack_started(self, ws):
        run = json.loads(await asyncio.wait_for(ws.outgoing.get(), 2))
        _assert_run_task_shape(self, run)
        await ws.incoming.put(
            json.dumps(
                {"header": {"event": "task-started", "task_id": run["header"]["task_id"]}}
            )
        )
        return run

    async def _round(self, text="hello"):
        sentence = uuid.uuid4().hex
        self.conn.sentence_id = sentence
        before = len(self.sockets)
        start = asyncio.create_task(self.provider.start_session(sentence))
        ws = None
        for _ in range(80):
            if len(self.sockets) > before:
                ws = self.sockets[-1]
                break
            await asyncio.sleep(0.01)
        self.assertIsNotNone(ws)
        run = await self._ack_started(ws)
        await start
        await self.provider.text_to_speak(text, None)
        cont = json.loads(await asyncio.wait_for(ws.outgoing.get(), 2))
        _assert_continue_task_shape(self, cont, run["header"]["task_id"])
        encoded_before = len(self.encoded)
        await ws.incoming.put(b"\x00\x01" * 960)
        for _ in range(50):
            if len(self.encoded) > encoded_before:
                break
            await asyncio.sleep(0.01)
        self.assertGreater(len(self.encoded), encoded_before)
        return ws, run

    async def _wait_closed(self, ws, timeout=2):
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            if ws is not None and ws.closed:
                return
            await asyncio.sleep(0)
        self.assertTrue(ws.closed)

    async def _abort(self, ws=None):
        await handleAbortMessage(self.conn)
        target = ws
        if target is None:
            sess = getattr(self.provider, "last_cancel_session", None)
            target = getattr(sess, "ws", None) if sess is not None else None
        if target is not None:
            await self._wait_closed(target)

    async def test_three_abort_recover_rounds_same_provider(self):
        """Same connection + same Provider: speak, abort, speak, three times via FIRST."""
        thread = threading.Thread(
            target=self.provider.tts_text_priority_thread, daemon=True
        )
        thread.start()
        task_ids = []
        try:
            for i in range(3):
                sentence = uuid.uuid4().hex
                self.conn.sentence_id = sentence
                before = len(self.sockets)
                self.assertTrue(
                    begin_tts_turn(self.conn, sentence)[1] == self.conn.tts_abort_epoch
                )
                self.assertTrue(
                    enqueue_tts(
                        self.conn,
                        TTSMessageDTO(
                            sentence_id=sentence,
                            sentence_type=SentenceType.FIRST,
                            content_type=ContentType.ACTION,
                        ),
                    )
                )
                ws = None
                for _ in range(80):
                    if len(self.sockets) > before:
                        ws = self.sockets[-1]
                        break
                    await asyncio.sleep(0.01)
                self.assertIsNotNone(ws, f"round {i} did not open upstream")
                run = await self._ack_started(ws)
                task_ids.append(run["header"]["task_id"])
                self.assertTrue(
                    enqueue_tts(
                        self.conn,
                        TTSMessageDTO(
                            sentence_id=sentence,
                            sentence_type=SentenceType.MIDDLE,
                            content_type=ContentType.TEXT,
                            content_detail=f"round-{i}",
                        ),
                    )
                )
                cont = json.loads(await asyncio.wait_for(ws.outgoing.get(), 2))
                _assert_continue_task_shape(self, cont, run["header"]["task_id"])
                encoded_before = len(self.encoded)
                await ws.incoming.put(b"\x00\x01" * 960)
                for _ in range(50):
                    if len(self.encoded) > encoded_before:
                        break
                    await asyncio.sleep(0.01)
                self.assertGreater(len(self.encoded), encoded_before)
                await self._abort(ws)
                self.assertTrue(ws.closed)
                self.assertTrue(self.conn.client_abort)
                self.assertEqual(self.conn.tts_abort_epoch, i + 1)
        finally:
            self.conn.stop_event.set()
            thread.join(2)
        self.assertEqual(len(set(task_ids)), 3)
        self.assertIs(self.provider.conn, self.conn)

    async def test_stale_first_does_not_clear_abort_or_start(self):
        started = []
        original = self.provider.start_session

        async def wrapped(session_id, abort_epoch=None):
            started.append((session_id, abort_epoch))
            return await original(session_id, abort_epoch=abort_epoch)

        self.provider.start_session = wrapped
        dequeued = threading.Event()
        proceed = threading.Event()

        def hook(message):
            if not dequeued.is_set():
                dequeued.set()
                proceed.wait(2)
                self.conn.tts_abort_epoch += 1
                self.conn.client_abort = True

        self.provider._after_dequeue_hook = hook
        dto = TTSMessageDTO(
            sentence_id=self.conn.sentence_id,
            sentence_type=SentenceType.FIRST,
            content_type=ContentType.ACTION,
            abort_epoch=0,
            session_id=self.conn.session_id,
        )
        self.provider.tts_text_queue.put(dto)
        thread = threading.Thread(target=self.provider.tts_text_priority_thread, daemon=True)
        thread.start()
        self.assertTrue(dequeued.wait(2))
        proceed.set()
        for _ in range(50):
            if self.provider.tts_text_queue.empty():
                break
            await asyncio.sleep(0.01)
        self.conn.stop_event.set()
        thread.join(2)
        self.assertTrue(self.conn.client_abort)
        self.assertEqual(self.conn.tts_abort_epoch, 1)
        self.assertEqual(started, [])

    async def test_abort_during_connect_drops_late_socket(self):
        self.connect_delay_event = asyncio.Event()
        start = asyncio.create_task(self.provider.start_session(self.conn.sentence_id))
        await asyncio.sleep(0.05)
        await self._abort()
        self.connect_delay_event.set()
        with self.assertRaises(QwenTtsExpired):
            await start
        self.assertTrue(self.sockets)
        self.assertTrue(self.sockets[0].closed)
        self.conn.client_abort = False
        recover = asyncio.create_task(self.provider.start_session(uuid.uuid4().hex))
        ws = None
        for _ in range(50):
            if len(self.sockets) >= 2:
                ws = self.sockets[-1]
                break
            await asyncio.sleep(0.01)
        run = await self._ack_started(ws)
        await recover
        self.assertEqual(run["payload"]["model"], "qwen-audio-3.0-tts-plus")
        self.assertIs(self.provider.ws, ws)
        self.assertFalse(ws.closed)

    async def test_abort_while_waiting_task_started(self):
        start = asyncio.create_task(self.provider.start_session(self.conn.sentence_id))
        ws = None
        for _ in range(50):
            if self.sockets:
                ws = self.sockets[0]
                break
            await asyncio.sleep(0.01)
        run = json.loads(await asyncio.wait_for(ws.outgoing.get(), 2))
        _assert_run_task_shape(self, run)
        await self._abort()
        with self.assertRaises(QwenTtsExpired):
            await start
        self.conn.client_abort = False
        recover = asyncio.create_task(self.provider.start_session(uuid.uuid4().hex))
        for _ in range(50):
            if len(self.sockets) >= 2:
                break
            await asyncio.sleep(0.01)
        await self._ack_started(self.sockets[-1])
        await recover
        self.assertIs(self.provider.ws, self.sockets[-1])

    async def test_delayed_old_cancel_does_not_close_new_session(self):
        ws_a, run_a = await self._round()
        sess_a = self.provider._current
        self.assertIsNotNone(sess_a)
        self.conn.tts_abort_epoch += 1
        self.conn.client_abort = True
        delayed = self.provider.cancel_session()
        self.assertTrue(asyncio.iscoroutine(delayed))
        self.conn.client_abort = False
        start_b = asyncio.create_task(self.provider.start_session(uuid.uuid4().hex))
        for _ in range(50):
            if len(self.sockets) >= 2:
                break
            await asyncio.sleep(0.01)
        ws_b = self.sockets[-1]
        await self._ack_started(ws_b)
        await start_b
        self.assertIs(self.provider.ws, ws_b)
        await delayed
        self.assertFalse(ws_b.closed)
        self.assertIs(self.provider.ws, ws_b)
        self.assertEqual(self.provider.task_id, self.provider._current.task_id)
        self.assertNotEqual(self.provider.task_id, run_a["header"]["task_id"])

    async def test_late_old_events_do_not_affect_new_session(self):
        ws_a, run_a = await self._round()
        await self._abort()
        self.conn.client_abort = False
        start_b = asyncio.create_task(self.provider.start_session(uuid.uuid4().hex))
        for _ in range(50):
            if len(self.sockets) >= 2:
                break
            await asyncio.sleep(0.01)
        ws_b = self.sockets[-1]
        run_b = await self._ack_started(ws_b)
        await start_b
        encoded_before = len(self.encoded)
        started_event = self.provider._current.started
        await ws_a.incoming.put(
            json.dumps(
                {"header": {"event": "task-started", "task_id": run_a["header"]["task_id"]}}
            )
        )
        await ws_a.incoming.put(b"\x00\x01" * 960)
        await ws_a.incoming.put(
            json.dumps(
                {"header": {"event": "task-finished", "task_id": run_a["header"]["task_id"]}}
            )
        )
        await ws_b.incoming.put(
            json.dumps(
                {"header": {"event": "task-started", "task_id": run_a["header"]["task_id"]}}
            )
        )
        await asyncio.sleep(0.05)
        self.assertEqual(len(self.encoded), encoded_before)
        self.assertTrue(started_event.is_set())
        self.assertEqual(self.provider.task_id, run_b["header"]["task_id"])
        self.assertFalse(self.provider._current.finished.is_set())

    async def test_finish_abort_repeat_close_and_disconnect(self):
        ws, run = await self._round()
        finish = asyncio.create_task(self.provider.finish_session(run["header"]["task_id"]))
        abort = asyncio.create_task(self._abort())
        await asyncio.wait({finish, abort}, timeout=2)
        await self.provider.close()
        await self.provider.close()
        coro = self.provider.cancel_session()
        if asyncio.iscoroutine(coro):
            await coro
        self.conn.stop_event.set()
        await self.provider.close()
        pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()]
        # Allow abortHandle's create_task close to settle.
        await asyncio.sleep(0.05)
        self.assertTrue(ws.closed)

    async def test_start_timeout_is_not_silent_success(self):
        original_wait = self.provider._wait_started

        async def fast_timeout(sess, timeout=10):
            raise QwenTtsTimeout("task_started_timeout")

        self.provider._wait_started = fast_timeout
        with self.assertRaises(QwenTtsTimeout):
            await self.provider.start_session(self.conn.sentence_id)
        self.assertIsNone(self.provider._current)
        self.provider._wait_started = original_wait
        self.conn.client_abort = False
        before = len(self.sockets)
        recover = asyncio.create_task(self.provider.start_session(uuid.uuid4().hex))
        ws = None
        for _ in range(80):
            if len(self.sockets) > before:
                ws = self.sockets[-1]
                break
            await asyncio.sleep(0.01)
        await self._ack_started(ws)
        await recover
        self.assertIsNotNone(self.provider._current)
        self.assertTrue(self.provider._current.started.is_set())

    async def test_two_devices_abort_isolated(self):
        conn_b = FakeConn(self.loop, session_id="sess-b", device_id="aa:bb:cc:dd:ee:ff")
        sockets_b = []

        async def connect_b(url, headers):
            ws = FakeWS()
            sockets_b.append(ws)
            return ws

        provider_b = TTSProvider(
            {
                "api_key": "sk-test",
                "ws_url": "ws://127.0.0.1:3011/bailian/api-ws/v1/inference",
                "model": "qwen-audio-3.0-tts-plus",
                "voice": "longanlingxi",
                "sample_rate": 16000,
                "_connect": connect_b,
            },
            True,
        )
        provider_b.conn = conn_b
        conn_b.tts = provider_b
        encoded_b = []
        provider_b.handle_opus = lambda data: encoded_b.append(data)
        start_b = asyncio.create_task(provider_b.start_session(conn_b.sentence_id))
        for _ in range(50):
            if sockets_b:
                break
            await asyncio.sleep(0.01)
        run_b = json.loads(await asyncio.wait_for(sockets_b[0].outgoing.get(), 2))
        await sockets_b[0].incoming.put(
            json.dumps(
                {"header": {"event": "task-started", "task_id": run_b["header"]["task_id"]}}
            )
        )
        await start_b
        await self._round()
        await self._abort()
        self.assertTrue(self.conn.client_abort)
        self.assertFalse(conn_b.client_abort)
        self.assertEqual(conn_b.tts_abort_epoch, 0)
        self.assertFalse(sockets_b[0].closed)
        await provider_b.text_to_speak("device-b", None)
        cont = json.loads(await asyncio.wait_for(sockets_b[0].outgoing.get(), 2))
        self.assertEqual(cont["header"]["action"], "continue-task")
        await provider_b.close()

    async def test_enqueue_binds_abort_epoch_and_legacy_dto_starts(self):
        self.conn.tts_abort_epoch = 4
        dto = TTSMessageDTO(
            sentence_id=self.conn.sentence_id,
            sentence_type=SentenceType.FIRST,
            content_type=ContentType.ACTION,
        )
        self.assertIsNone(dto.abort_epoch)
        begin_tts_turn(self.conn, dto.sentence_id)
        self.assertTrue(enqueue_tts(self.conn, dto))
        self.assertEqual(dto.abort_epoch, 4)
        self.assertEqual(dto.session_id, self.conn.session_id)
        legacy = TTSMessageDTO(
            sentence_id=self.conn.sentence_id,
            sentence_type=SentenceType.FIRST,
            content_type=ContentType.ACTION,
        )
        self.conn.tts_abort_epoch = 0
        self.conn.client_abort = False
        before = len(self.sockets)
        start = asyncio.create_task(
            self.provider.start_session(legacy.sentence_id, abort_epoch=legacy.abort_epoch)
        )
        ws = None
        for _ in range(80):
            if len(self.sockets) > before:
                ws = self.sockets[-1]
                break
            await asyncio.sleep(0.01)
        await self._ack_started(ws)
        await start
        self.assertIsNotNone(self.provider._current)
        self.assertEqual(self.provider._current.abort_epoch, 0)

    async def test_stale_llm_enqueue_after_abort_does_not_adopt_new_epoch(self):
        """Old LLM generation that enqueues after abort must not restamp the new epoch."""
        sentence = self.conn.sentence_id
        first = TTSMessageDTO(
            sentence_id=sentence,
            sentence_type=SentenceType.FIRST,
            content_type=ContentType.ACTION,
        )
        begin_tts_turn(self.conn, sentence)
        self.assertTrue(enqueue_tts(self.conn, first))
        self.assertEqual(first.abort_epoch, 0)
        self.assertEqual(self.conn.tts_sentence_epochs[sentence], 0)

        await handleAbortMessage(self.conn)
        self.assertEqual(self.conn.tts_abort_epoch, 1)
        self.conn.client_abort = False

        leftover_middle = TTSMessageDTO(
            sentence_id=sentence,
            sentence_type=SentenceType.MIDDLE,
            content_type=ContentType.TEXT,
            content_detail="old-llm-text",
        )
        leftover_first = TTSMessageDTO(
            sentence_id=sentence,
            sentence_type=SentenceType.FIRST,
            content_type=ContentType.ACTION,
        )
        bound_middle = resolve_enqueue_abort_epoch(self.conn, leftover_middle)
        bound_first = resolve_enqueue_abort_epoch(self.conn, leftover_first)
        self.assertEqual(bound_middle, 0)
        self.assertEqual(bound_first, 0)
        self.assertNotEqual(bound_middle, self.conn.tts_abort_epoch)
        self.assertFalse(enqueue_tts(self.conn, leftover_middle))
        self.assertEqual(leftover_middle.abort_epoch, 0)
        self.assertFalse(enqueue_tts(self.conn, leftover_first))
        self.assertEqual(leftover_first.abort_epoch, 0)

        started = []
        original = self.provider.start_session

        async def wrapped(session_id, abort_epoch=None):
            started.append((session_id, abort_epoch))
            return await original(session_id, abort_epoch=abort_epoch)

        self.provider.start_session = wrapped
        thread = threading.Thread(
            target=self.provider.tts_text_priority_thread, daemon=True
        )
        thread.start()
        await asyncio.sleep(0.05)
        self.conn.stop_event.set()
        thread.join(2)
        self.assertEqual(started, [])
        self.assertEqual(self.conn.tts_sentence_epochs[sentence], 0)

        self.conn.stop_event = asyncio.Event()
        new_sentence = uuid.uuid4().hex
        self.conn.sentence_id = new_sentence
        self.conn.client_abort = False
        begin_tts_turn(self.conn, new_sentence)
        new_first = TTSMessageDTO(
            sentence_id=new_sentence,
            sentence_type=SentenceType.FIRST,
            content_type=ContentType.ACTION,
        )
        self.assertTrue(enqueue_tts(self.conn, new_first))
        self.assertEqual(new_first.abort_epoch, 1)

    async def test_turn_bound_before_first_enqueue_survives_abort(self):
        """Generation starts (bind) before abort; first enqueue after abort keeps old epoch."""
        old_sid, old_epoch = begin_tts_turn(self.conn, self.conn.sentence_id)
        self.assertEqual(old_epoch, 0)
        await handleAbortMessage(self.conn)
        self.conn.client_abort = False
        late = TTSMessageDTO(
            sentence_id=old_sid,
            sentence_type=SentenceType.MIDDLE,
            content_type=ContentType.TEXT,
            content_detail="late-first-output",
        )
        self.assertEqual(resolve_enqueue_abort_epoch(self.conn, late), 0)
        self.assertFalse(enqueue_tts(self.conn, late))
        self.assertEqual(late.abort_epoch, 0)
        self.assertNotEqual(late.abort_epoch, self.conn.tts_abort_epoch)

    async def test_late_output_keeps_old_sentence_after_conn_id_switch(self):
        old_sid, old_epoch = begin_tts_turn(self.conn, self.conn.sentence_id)
        await handleAbortMessage(self.conn)
        self.conn.client_abort = False
        new_sid = uuid.uuid4().hex
        self.conn.sentence_id = new_sid
        begin_tts_turn(self.conn, new_sid)
        captured_old = TTSMessageDTO(
            sentence_id=old_sid,
            sentence_type=SentenceType.MIDDLE,
            content_type=ContentType.TEXT,
            content_detail="old-turn-text",
            abort_epoch=old_epoch,
        )
        self.assertFalse(enqueue_tts(self.conn, captured_old))
        self.assertEqual(captured_old.sentence_id, old_sid)
        self.assertEqual(captured_old.abort_epoch, 0)
        new_dto = TTSMessageDTO(
            sentence_id=new_sid,
            sentence_type=SentenceType.MIDDLE,
            content_type=ContentType.TEXT,
            content_detail="new-turn-text",
        )
        self.assertTrue(enqueue_tts(self.conn, new_dto))
        self.assertEqual(new_dto.abort_epoch, 1)
        self.assertEqual(new_dto.sentence_id, new_sid)

    async def test_sentence_epoch_map_prunes_without_rebind(self):
        kept = []
        for i in range(TTS_SENTENCE_EPOCH_LIMIT + 8):
            sid = f"sent-{i:03d}"
            begin_tts_turn(self.conn, sid, epoch=0)
            kept.append(sid)
        mapping = self.conn.tts_sentence_epochs
        self.assertLessEqual(len(mapping), TTS_SENTENCE_EPOCH_LIMIT)
        evicted = kept[0]
        self.assertNotIn(evicted, mapping)
        self.conn.tts_abort_epoch = 3
        late = TTSMessageDTO(
            sentence_id=evicted,
            sentence_type=SentenceType.MIDDLE,
            content_type=ContentType.TEXT,
            content_detail="evicted-late",
        )
        self.assertIsNone(resolve_enqueue_abort_epoch(self.conn, late))
        self.assertFalse(enqueue_tts(self.conn, late))
        self.assertIsNone(late.abort_epoch)
        self.assertNotIn(evicted, self.conn.tts_sentence_epochs)

    def _attach_websocket_server(self):
        from core.websocket_server import WebSocketServer

        server = WebSocketServer.__new__(WebSocketServer)
        server.logger = MagicMock()
        server.logger.bind.return_value = server.logger
        server._connections = {}
        server._current_sessions = {}
        server._device_send_locks = {}
        server._reminder_control_manager = None
        self.conn.server = server
        self.conn.correlation_id = "corr-" + self.conn.session_id
        server._register_connection(self.conn.device_id, self.conn)
        return server

    def _enqueue_like_play_music(self, text, music_path="/tmp/fake-song.mp3"):
        sid, epoch = begin_tts_turn(self.conn, getattr(self.conn, "sentence_id", None))
        queued = []
        for dto in (
            TTSMessageDTO(
                sentence_id=sid,
                sentence_type=SentenceType.FIRST,
                content_type=ContentType.ACTION,
                abort_epoch=epoch,
            ),
            TTSMessageDTO(
                sentence_id=sid,
                sentence_type=SentenceType.MIDDLE,
                content_type=ContentType.TEXT,
                content_detail=text,
                abort_epoch=epoch,
            ),
            TTSMessageDTO(
                sentence_id=sid,
                sentence_type=SentenceType.MIDDLE,
                content_type=ContentType.FILE,
                content_file=music_path,
                abort_epoch=epoch,
            ),
            TTSMessageDTO(
                sentence_id=sid,
                sentence_type=SentenceType.LAST,
                content_type=ContentType.ACTION,
                abort_epoch=epoch,
            ),
        ):
            queued.append(enqueue_tts(self.conn, dto))
        return sid, epoch, queued

    async def _run_consumer_until(self, predicate, timeout=2.0):
        thread = threading.Thread(
            target=self.provider.tts_text_priority_thread, daemon=True
        )
        thread.start()
        deadline = asyncio.get_running_loop().time() + timeout
        try:
            while asyncio.get_running_loop().time() < deadline:
                if predicate():
                    break
                await asyncio.sleep(0.01)
            return predicate()
        finally:
            self.conn.stop_event.set()
            thread.join(2)
            self.conn.stop_event = asyncio.Event()

    async def test_websocket_and_play_music_normal_calls_still_play(self):
        """1. websocket_server / play_music 正常调用仍能被同一消费者播放。"""
        started = []
        spoken = []
        files = []
        original_start = self.provider.start_session
        original_speak = self.provider.text_to_speak

        async def wrap_start(session_id, abort_epoch=None):
            started.append((session_id, abort_epoch))
            return await original_start(session_id, abort_epoch=abort_epoch)

        async def wrap_speak(text, file):
            spoken.append(text)
            return await original_speak(text, file)

        async def wrap_finish(session_id):
            return None

        self.provider.start_session = wrap_start
        self.provider.text_to_speak = wrap_speak
        self.provider.finish_session = wrap_finish
        self.provider._process_audio_file_stream = lambda path, callback=None: files.append(path)

        server = self._attach_websocket_server()
        thread = threading.Thread(
            target=self.provider.tts_text_priority_thread, daemon=True
        )
        thread.start()
        try:
            before = len(self.sockets)
            ok = await server.send_tts_to_device("hello-ws", self.conn.device_id)
            self.assertTrue(ok)
            ws = None
            for _ in range(80):
                if len(self.sockets) > before:
                    ws = self.sockets[-1]
                    break
                await asyncio.sleep(0.01)
            self.assertIsNotNone(ws)
            await self._ack_started(ws)
            for _ in range(80):
                if "hello-ws" in spoken:
                    break
                await asyncio.sleep(0.01)
            self.assertIn("hello-ws", spoken)
            self.assertEqual(started[-1][1], 0)

            fd, music_path = tempfile.mkstemp(suffix=".mp3")
            os.close(fd)
            try:
                self.conn.sentence_id = uuid.uuid4().hex
                before_music = len(self.sockets)
                sid, epoch, queued = self._enqueue_like_play_music(
                    "正在为您播放", music_path=music_path
                )
                self.assertTrue(all(queued))
                self.assertEqual(epoch, 0)
                ws_music = None
                for _ in range(80):
                    if len(self.sockets) > before_music:
                        ws_music = self.sockets[-1]
                        break
                    await asyncio.sleep(0.01)
                self.assertIsNotNone(ws_music)
                await self._ack_started(ws_music)
                for _ in range(80):
                    if files:
                        break
                    await asyncio.sleep(0.01)
                self.assertEqual(files, [music_path])
                self.assertIn("正在为您播放", spoken)
            finally:
                os.unlink(music_path)
        finally:
            self.conn.stop_event.set()
            thread.join(2)
            self.conn.stop_event = asyncio.Event()

        import plugins_func.functions.play_music as play_music_mod

        self.conn.intent_type = "intent_llm"
        self.conn.dialogue = MagicMock()
        play_music_mod.MUSIC_CACHE = {
            "music_dir": "/tmp/music-cache",
            "music_files": ["song.mp3"],
        }
        with patch.object(play_music_mod, "send_stt_message", new_callable=AsyncMock), patch.object(
            play_music_mod.os.path, "exists", return_value=True
        ):
            await play_music_mod.play_local_music(self.conn, specific_file="song.mp3")
        items = []
        while True:
            try:
                items.append(self.provider.tts_text_queue.get_nowait())
            except Exception:
                break
        self.assertGreaterEqual(len(items), 3)
        epochs = {getattr(item, "abort_epoch", None) for item in items}
        self.assertEqual(epochs, {0})
        self.assertTrue(any(item.content_type == ContentType.FILE for item in items))

    async def test_websocket_and_play_music_stale_queue_does_not_resume_after_abort(self):
        """2. 打断前已排队、打断后才消费的旧消息不得恢复旧播放。"""
        started = []
        files = []
        original_start = self.provider.start_session

        async def wrap_start(session_id, abort_epoch=None):
            started.append((session_id, abort_epoch))
            return await original_start(session_id, abort_epoch=abort_epoch)

        self.provider.start_session = wrap_start
        self.provider._process_audio_file_stream = lambda path, callback=None: files.append(path)

        server = self._attach_websocket_server()
        ok = await server.send_tts_to_device("old-ws", self.conn.device_id)
        self.assertTrue(ok)
        self.assertFalse(self.provider.tts_text_queue.empty())

        self.conn.tts_abort_epoch += 1
        self.conn.client_abort = False
        consumed = await self._run_consumer_until(
            lambda: self.provider.tts_text_queue.empty()
        )
        self.assertTrue(consumed)
        self.assertEqual(started, [])
        self.assertEqual(self.sockets, [])

        self.conn.sentence_id = uuid.uuid4().hex
        begin_tts_turn(self.conn, self.conn.sentence_id, epoch=0)
        sid, epoch, queued = self._enqueue_like_play_music("old-music")
        self.assertFalse(any(queued))
        self.assertEqual(epoch, 0)
        self.assertNotEqual(epoch, self.conn.tts_abort_epoch)
        self.assertTrue(self.provider.tts_text_queue.empty())

        leftover = TTSMessageDTO(
            sentence_id=sid,
            sentence_type=SentenceType.MIDDLE,
            content_type=ContentType.FILE,
            content_file="/tmp/fake-song.mp3",
            abort_epoch=0,
            session_id=self.conn.session_id,
        )
        self.provider.tts_text_queue.put(leftover)
        self.assertFalse(self.provider.tts_text_queue.empty())
        consumed = await self._run_consumer_until(
            lambda: self.provider.tts_text_queue.empty()
        )
        self.assertTrue(consumed)
        self.assertEqual(started, [])
        self.assertEqual(files, [])

    async def test_websocket_play_music_missing_epoch_neither_reject_all_nor_adopt_current(self):
        """3. 缺少 abort_epoch 不全部拒绝，也不得在消费时改盖当前 epoch 绕过隔离。"""
        bound_sid, bound_epoch = begin_tts_turn(self.conn, self.conn.sentence_id)
        missing = TTSMessageDTO(
            sentence_id=bound_sid,
            sentence_type=SentenceType.FIRST,
            content_type=ContentType.ACTION,
        )
        self.assertIsNone(missing.abort_epoch)
        self.assertTrue(enqueue_tts(self.conn, missing))
        self.assertEqual(missing.abort_epoch, 0)
        self.assertEqual(bound_epoch, 0)
        try:
            while True:
                self.provider.tts_text_queue.get_nowait()
        except Exception:
            pass

        unbound = TTSMessageDTO(
            sentence_id=uuid.uuid4().hex,
            sentence_type=SentenceType.FIRST,
            content_type=ContentType.ACTION,
        )
        self.assertFalse(enqueue_tts(self.conn, unbound))
        self.assertIsNone(unbound.abort_epoch)

        await handleAbortMessage(self.conn)
        self.conn.client_abort = False
        leftover = TTSMessageDTO(
            sentence_id=bound_sid,
            sentence_type=SentenceType.FIRST,
            content_type=ContentType.ACTION,
        )
        self.assertFalse(enqueue_tts(self.conn, leftover))
        self.assertEqual(leftover.abort_epoch, 0)
        self.assertNotEqual(leftover.abort_epoch, self.conn.tts_abort_epoch)

        started = []
        original_start = self.provider.start_session

        async def wrap_start(session_id, abort_epoch=None):
            started.append((session_id, abort_epoch))
            return await original_start(session_id, abort_epoch=abort_epoch)

        self.provider.start_session = wrap_start
        stale_no_epoch = TTSMessageDTO(
            sentence_id=bound_sid,
            sentence_type=SentenceType.FIRST,
            content_type=ContentType.ACTION,
            session_id=self.conn.session_id,
        )
        self.assertIsNone(stale_no_epoch.abort_epoch)
        self.conn.tts_abort_epoch = 0
        self.provider.tts_text_queue.put(stale_no_epoch)
        self.assertEqual(stale_no_epoch.stream_token[2], 0)
        self.conn.tts_abort_epoch = 1
        consumed = await self._run_consumer_until(
            lambda: self.provider.tts_text_queue.empty()
        )
        self.assertTrue(consumed)
        self.assertEqual(started, [])
        self.assertNotEqual(stale_no_epoch.stream_token[2], self.conn.tts_abort_epoch)

        new_sid = uuid.uuid4().hex
        self.conn.sentence_id = new_sid
        begin_tts_turn(self.conn, new_sid)
        fresh = TTSMessageDTO(
            sentence_id=new_sid,
            sentence_type=SentenceType.FIRST,
            content_type=ContentType.ACTION,
        )
        self.assertIsNone(fresh.abort_epoch)
        self.assertTrue(enqueue_tts(self.conn, fresh))
        self.assertEqual(fresh.abort_epoch, 1)


class TtsAbortHandleBindTests(unittest.IsolatedAsyncioTestCase):
    async def test_abort_binds_session_before_create_task(self):
        loop = asyncio.get_running_loop()
        conn = FakeConn(loop)
        bound = []

        class DummyTTS:
            def __init__(self):
                self.last_cancel_session = None
                self.tts_text_queue = None
                self.tts_audio_queue = None

            def cancel_session(self):
                sess = type("S", (), {"task_id": "bound-task"})()
                self.last_cancel_session = sess
                bound.append("bound")

                async def later():
                    bound.append("ran")

                return later()

        conn.tts = DummyTTS()
        await handleAbortMessage(conn)
        self.assertEqual(bound[0], "bound")
        self.assertEqual(conn.tts_abort_epoch, 1)
        self.assertTrue(conn.client_abort)
        await asyncio.sleep(0.05)
        self.assertIn("ran", bound)
        self.assertEqual(bound, ["bound", "ran"])
        pending = [t for t in getattr(conn, "_tts_cancel_tasks", set()) if not t.done()]
        self.assertEqual(pending, [])

    async def test_async_cancel_session_with_session_id_runs_once(self):
        loop = asyncio.get_running_loop()
        conn = FakeConn(loop)
        calls = []

        class HuoshanLikeTTS:
            def __init__(self):
                self.task_id = "huoshan-session"
                self.tts_text_queue = None
                self.tts_audio_queue = None

            async def cancel_session(self, session_id):
                calls.append(session_id)

        conn.tts = HuoshanLikeTTS()
        current = asyncio.current_task()
        await handleAbortMessage(conn)
        for _ in range(20):
            if calls:
                break
            await asyncio.sleep(0)
        self.assertEqual(calls, ["huoshan-session"])
        self.assertEqual(conn.tts_abort_epoch, 1)
        pending = [t for t in getattr(conn, "_tts_cancel_tasks", set()) if not t.done()]
        self.assertEqual(pending, [])
        leftovers = [
            t
            for t in asyncio.all_tasks()
            if t is not current and not t.done() and t.get_coro().__qualname__.endswith("cancel_session")
        ]
        self.assertEqual(leftovers, [])

    async def test_repeat_abort_schedules_separate_cancels_without_leak(self):
        loop = asyncio.get_running_loop()
        conn = FakeConn(loop)
        runs = []
        n = [0]

        class DummyTTS:
            def __init__(self):
                self.last_cancel_session = None
                self.tts_text_queue = None
                self.tts_audio_queue = None

            def cancel_session(self):
                n[0] += 1
                sess = type("S", (), {"task_id": f"t-{n[0]}"})()
                self.last_cancel_session = sess

                async def later():
                    runs.append(sess.task_id)

                return later()

        conn.tts = DummyTTS()
        await handleAbortMessage(conn)
        await handleAbortMessage(conn)
        for _ in range(40):
            if len(runs) >= 2:
                break
            await asyncio.sleep(0)
        self.assertEqual(runs, ["t-1", "t-2"])
        pending = [t for t in getattr(conn, "_tts_cancel_tasks", set()) if not t.done()]
        self.assertEqual(pending, [])


if __name__ == "__main__":
    unittest.main()
