"""Pre-deploy guards: Silero RNN isolation, DTX gaps, listen-stop drain.

No paid upstream. Uses local Silero weights and an in-process mock ASR.
"""
from __future__ import annotations

import asyncio
import json
import os
import queue
import sys
import threading
import time
import unittest
from collections import deque
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _ROOT)

import config.config_loader as config_loader


def _offline_config(config):
    local = dict(config)
    local["read_config_from_api"] = False
    return local


config_loader.get_config_from_api = _offline_config

from core.handle.receiveAudioHandle import handleAudioMessage
from core.handle.textHandler.listenMessageHandler import ListenTextMessageHandler
from core.providers.asr.base import ASRProviderBase
from core.providers.asr.qwen3_asr_realtime import ASRProvider
from core.providers.vad.silero import VADProvider
from core.utils.audio_ingress import (
    DTX_FRAME_MS,
    drain_queued_audio,
    note_short_payload_gap,
    on_listen_start,
    queue_audio,
)
from core.utils.utterance_state import confirm_speech, request_stop


class _DummyPriorityAsr(ASRProviderBase):
    async def speech_to_text(self, opus_data, session_id, audio_format="opus"):
        return "", None


def _conn():
    conn = SimpleNamespace()
    conn.listen_epoch = 1
    conn.session_id = "s"
    conn.device_id = "dev"
    conn.agent_id = "ag"
    conn.client_listen_mode = "auto"
    conn.client_have_voice = False
    conn.client_voice_stop = False
    conn.client_is_speaking = False
    conn.just_woken_up = False
    conn.close_after_chat = False
    conn.config = {}
    conn.client_voice_window = deque(maxlen=5)
    conn.client_audio_buffer = bytearray()
    conn.last_is_voice = False
    conn.last_activity_time = 0.0
    conn.asr_audio = []
    conn.asr_audio_queue = queue.Queue()
    conn.asr_audio_inflight = 0
    conn._audio_seq = 0
    conn._audio_processed_seq = 0
    conn._audio_inflight_seq = 0
    conn.stop_event = threading.Event()
    conn.logger = MagicMock()
    conn.logger.bind.return_value = conn.logger
    conn._cid = lambda: "test-cid"
    conn._audio_ingress_stats = {}
    on_listen_start(conn)
    conn.device_listening = True
    return conn


def _opus_frame(seed, n=960):
    import opuslib_next

    rng = np.random.RandomState(seed)
    pcm = (rng.randn(n) * 8000).astype(np.int16).tobytes()
    enc = opuslib_next.Encoder(16000, 1, opuslib_next.APPLICATION_AUDIO)
    return enc.encode(pcm, n)


def _tensor_np(state, name):
    return state[name].detach().cpu().numpy()


class SileroRnnIsolationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vad = VADProvider(
            {
                "model_dir": os.path.join(_ROOT, "models/snakers4_silero-vad"),
                "threshold": "0.5",
                "threshold_low": "0.2",
                "min_silence_duration_ms": "200",
            }
        )

    def test_interleaved_connections_match_serial_control(self):
        packets = [_opus_frame(i) for i in range(6)]
        noise = [_opus_frame(100 + i) for i in range(6)]
        control = _conn()
        isolated = _conn()
        other = _conn()
        for pkt in packets:
            self.vad.is_vad(control, pkt)
        for i, pkt in enumerate(packets):
            self.vad.is_vad(isolated, pkt)
            self.vad.is_vad(other, noise[i])
        a = isolated._silero_rnn_state
        b = control._silero_rnn_state
        c = other._silero_rnn_state
        self.assertIsNotNone(a)
        self.assertIsNotNone(b)
        self.assertIsNotNone(c)
        self.assertNotEqual(id(a["_state"]), id(c["_state"]))
        self.assertNotEqual(id(a["_state"]), id(self.vad.model._state))
        for name in ("_state", "_context"):
            self.assertTrue(
                np.allclose(_tensor_np(a, name), _tensor_np(b, name), atol=1e-6),
                f"{name} diverged across connections",
            )
            self.assertFalse(
                np.allclose(_tensor_np(a, name), _tensor_np(c, name), atol=1e-5),
                f"{name} leaked between connections",
            )

    def test_without_restore_interleaved_state_is_contaminated(self):
        packets = [_opus_frame(i) for i in range(6)]
        noise = [_opus_frame(100 + i) for i in range(6)]
        restore = self.vad._restore_rnn
        save = self.vad._save_rnn
        control = _conn()
        for pkt in packets:
            self.vad.is_vad(control, pkt)
        expected = {
            name: control._silero_rnn_state[name].detach().clone()
            for name in ("_state", "_context")
        }
        self.vad._restore_rnn = lambda conn: None
        self.vad._save_rnn = lambda conn: None
        try:
            self.vad.model.reset_states()
            isolated = _conn()
            other = _conn()
            for i, pkt in enumerate(packets):
                self.vad.is_vad(isolated, pkt)
                self.vad.is_vad(other, noise[i])
            live = {
                "_state": self.vad.model._state.detach().clone(),
                "_context": self.vad.model._context.detach().clone(),
            }
            self.assertFalse(
                np.allclose(live["_state"].numpy(), expected["_state"].numpy(), atol=1e-5),
                "shared RNN should contaminate without per-conn restore",
            )
        finally:
            self.vad._restore_rnn = restore
            self.vad._save_rnn = save
            self.vad.model.reset_states()


class DtxSilenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_short_packets_after_speech_can_end_utterance(self):
        conn = _conn()
        confirm_speech(conn)
        conn.vad_last_speech_audio_ms = 0.0
        conn.vad_audio_ms = 0.0
        conn.vad = SimpleNamespace(silence_threshold_ms=200)
        stops = []

        class Asr:
            async def receive_audio(self, _conn, audio, have_voice):
                stops.append((audio, have_voice, _conn.client_voice_stop))

        conn.asr = Asr()
        conn.loop = asyncio.get_running_loop()
        conn.vad_called = []
        conn.vad.is_vad = lambda _c, audio: conn.vad_called.append(audio) or False
        for i in range(5):
            note_short_payload_gap(
                conn, protocol=2, payload_bytes=1, timestamp=1000 + i * 60
            )
        self.assertGreaterEqual(conn._audio_seq, 4)
        while True:
            try:
                item = conn.asr_audio_queue.get_nowait()
            except queue.Empty:
                break
            self.assertEqual(item.kind, "dtx_gap")
            self.assertGreaterEqual(item.gap_ms, 60)
            await handleAudioMessage(conn, item)
        self.assertTrue(conn.client_voice_stop)
        self.assertEqual(conn.utterance_stop_reason, "vad_silence")
        self.assertGreaterEqual(len(stops), 1)
        self.assertEqual(stops[0][0], b"")
        self.assertEqual(conn.vad_called, [])

    async def test_short_packets_before_speech_do_not_start(self):
        conn = _conn()
        conn.vad_speech_confirmed = False
        for _ in range(8):
            note_short_payload_gap(conn, protocol=2, payload_bytes=1)
        self.assertEqual(getattr(conn, "_audio_seq", 0), 0)
        self.assertTrue(conn.asr_audio_queue.empty())
        self.assertFalse(conn.client_voice_stop)

    async def test_dropping_short_packets_cannot_end_utterance(self):
        conn = _conn()
        confirm_speech(conn)
        conn.vad_last_speech_audio_ms = 0.0
        conn.vad_audio_ms = 0.0
        conn.vad = SimpleNamespace(silence_threshold_ms=200)
        for _ in range(20):
            pass
        self.assertFalse(conn.client_voice_stop)
        self.assertTrue(conn.asr_audio_queue.empty())
        self.assertEqual(conn.vad_audio_ms, 0.0)

    async def test_dtx_timestamp_branches_are_media_clock_not_arrival(self):
        conn = _conn()
        confirm_speech(conn)

        note_short_payload_gap(conn, protocol=2, payload_bytes=1, timestamp=1000)
        first = conn.asr_audio_queue.get_nowait()
        self.assertEqual(first.gap_ms, DTX_FRAME_MS)
        self.assertEqual(conn._audio_last_timestamp, 1000)

        note_short_payload_gap(conn, protocol=2, payload_bytes=1, timestamp=1000)
        self.assertTrue(conn.asr_audio_queue.empty())
        self.assertEqual(conn._audio_ingress_stats.get("dtx_ts_duplicate"), 1)
        self.assertEqual(conn._audio_last_timestamp, 1000)

        note_short_payload_gap(conn, protocol=2, payload_bytes=1, timestamp=900)
        self.assertTrue(conn.asr_audio_queue.empty())
        self.assertEqual(conn._audio_ingress_stats.get("dtx_ts_out_of_order"), 1)
        self.assertEqual(conn._audio_last_timestamp, 1000)

        note_short_payload_gap(conn, protocol=2, payload_bytes=1, timestamp=6000)
        capped = conn.asr_audio_queue.get_nowait()
        self.assertEqual(capped.gap_ms, DTX_FRAME_MS)
        self.assertEqual(conn._audio_ingress_stats.get("dtx_ts_capped"), 1)
        self.assertEqual(conn._audio_last_timestamp, 6000)

        conn2 = _conn()
        confirm_speech(conn2)
        t0 = time.monotonic()
        await asyncio.sleep(0.12)
        note_short_payload_gap(conn2, protocol=1, payload_bytes=1)
        note_short_payload_gap(conn2, protocol=3, payload_bytes=1)
        elapsed_ms = (time.monotonic() - t0) * 1000
        self.assertGreater(elapsed_ms, 100)
        self.assertIsNone(getattr(conn2, "_audio_last_timestamp", None))
        gaps = []
        while True:
            try:
                gaps.append(conn2.asr_audio_queue.get_nowait().gap_ms)
            except queue.Empty:
                break
        self.assertEqual(gaps, [DTX_FRAME_MS, DTX_FRAME_MS])


class ListenStopDrainTests(unittest.IsolatedAsyncioTestCase):
    def _slow_asr(self):
        received = []
        commit_pending = []

        class SlowAsr:
            def __init__(self):
                self._current = SimpleNamespace(
                    pending=deque(),
                    epoch=1,
                    utterance_id=1,
                    state="RUNNING",
                    commit_sent=False,
                )

            async def receive_audio(self, _conn, audio, have_voice):
                await asyncio.sleep(0.03)
                received.append(audio)
                self._current.pending.append(audio)

            async def stop_listening(self, _conn, reason="device_stop"):
                commit_pending.append(list(self._current.pending))

        return SlowAsr(), received, commit_pending

    async def test_stop_waits_for_queued_and_pending_frames_before_commit(self):
        conn = _conn()
        conn.loop = asyncio.get_running_loop()
        asr, received, commit_pending = self._slow_asr()
        conn.asr = asr
        conn.vad = SimpleNamespace(
            is_vad=lambda _c, _a: False,
            silence_threshold_ms=200,
        )
        frames = [bytes([i, 0]) * 16 for i in range(1, 5)]
        for frame in frames:
            queue_audio(conn, frame)

        async def consume():
            while not conn.stop_event.is_set():
                try:
                    msg = conn.asr_audio_queue.get_nowait()
                except queue.Empty:
                    await asyncio.sleep(0.005)
                    continue
                conn.asr_audio_inflight = 1
                conn._audio_inflight_seq = msg.seq
                try:
                    await handleAudioMessage(conn, msg)
                finally:
                    conn.asr_audio_inflight = 0

        worker = asyncio.create_task(consume())
        handler = ListenTextMessageHandler()
        await handler.handle(conn, {"type": "listen", "state": "stop", "mode": "auto"})
        conn.stop_event.set()
        worker.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await worker
        self.assertEqual(len(commit_pending), 1)
        self.assertEqual(len(commit_pending[0]), 4)
        self.assertEqual([f[0] for f in commit_pending[0]], [1, 2, 3, 4])
        self.assertEqual(len(received), 4)

    async def test_stop_drain_with_priority_thread_does_not_deadlock(self):
        conn = _conn()
        conn.loop = asyncio.get_running_loop()
        asr, received, commit_pending = self._slow_asr()
        conn.asr = asr
        conn.vad = SimpleNamespace(
            is_vad=lambda _c, _a: False,
            silence_threshold_ms=200,
        )
        worker = threading.Thread(
            target=ASRProviderBase.asr_text_priority_thread,
            args=(_DummyPriorityAsr(), conn),
            daemon=True,
        )
        worker.start()
        try:
            for i in range(1, 5):
                queue_audio(conn, bytes([i, 0]) * 16)
            handler = ListenTextMessageHandler()
            await asyncio.wait_for(
                handler.handle(
                    conn, {"type": "listen", "state": "stop", "mode": "auto"}
                ),
                timeout=2,
            )
            self.assertEqual(len(commit_pending), 1)
            self.assertEqual([f[0] for f in commit_pending[0]], [1, 2, 3, 4])
            self.assertEqual(len(received), 4)
        finally:
            conn.stop_event.set()
            worker.join(timeout=2)
            self.assertFalse(worker.is_alive())

    async def test_drain_timeout_disconnect_and_new_epoch_do_not_commit(self):
        conn = _conn()
        conn.loop = asyncio.get_running_loop()
        queue_audio(conn, b"\x01\x00" * 8)
        barrier = 1
        ok = await drain_queued_audio(conn, barrier, timeout=0.05)
        self.assertFalse(ok)
        self.assertEqual(conn._audio_processed_seq, 0)
        self.assertEqual(
            conn._audio_ingress_stats.get("listen_stop_drain_timeout"), 1
        )

        conn.stop_event.set()
        ok = await drain_queued_audio(conn, 99, timeout=1)
        self.assertFalse(ok)
        self.assertEqual(
            conn._audio_ingress_stats.get("listen_stop_drain_disconnect"), 1
        )
        conn.stop_event.clear()

        async def bump_epoch():
            await asyncio.sleep(0)
            conn.listen_epoch += 1

        asyncio.create_task(bump_epoch())
        ok = await drain_queued_audio(conn, 99, timeout=1, epoch=conn.listen_epoch)
        self.assertFalse(ok)
        self.assertEqual(
            conn._audio_ingress_stats.get("listen_stop_drain_epoch_changed"), 1
        )

        import core.utils.audio_ingress as ingress

        old_timeout = ingress.DRAIN_TIMEOUT_SEC
        ingress.DRAIN_TIMEOUT_SEC = 0.05
        try:
            conn2 = _conn()
            conn2.loop = asyncio.get_running_loop()
            stopped = []
            aborted = []

            class Asr:
                async def stop_listening(self, _conn, reason="device_stop"):
                    stopped.append(reason)

                async def abort_listening(self, _conn, reason="abort"):
                    aborted.append(reason)

            conn2.asr = Asr()
            queue_audio(conn2, b"\x01\x00" * 8)
            handler = ListenTextMessageHandler()
            await handler.handle(
                conn2, {"type": "listen", "state": "stop", "mode": "auto"}
            )
            self.assertEqual(stopped, [])
            self.assertEqual(aborted, ["drain_timeout"])
            self.assertEqual(
                conn2._audio_ingress_stats.get("listen_stop_commit_skipped_undrained"),
                1,
            )
            self.assertFalse(conn2.device_listening)
        finally:
            ingress.DRAIN_TIMEOUT_SEC = old_timeout

    async def test_qwen3_empty_audio_commits_after_dtx_stop(self):
        loop = asyncio.get_running_loop()
        ws_hold = {}

        async def connect(url, headers):
            class WS:
                def __init__(self):
                    self.outgoing = asyncio.Queue()
                    self.incoming = asyncio.Queue()
                    self.closed = False

                async def send(self, data):
                    await self.outgoing.put(data)

                async def recv(self):
                    return await self.incoming.get()

                async def close(self):
                    self.closed = True

            ws = WS()
            ws_hold["ws"] = ws
            return ws

        provider = ASRProvider(
            {
                "api_key": "sk-test",
                "ws_url": "ws://mock",
                "_connect": connect,
                "ready_timeout": 1,
                "result_timeout": 1,
            },
            True,
        )
        conn = _conn()
        conn.loop = loop
        conn.audio_format = "pcm"
        conn.device_listening = True
        provider.handle_voice_stop = lambda *a, **k: asyncio.sleep(0)
        frame = b"\x00\x01" * 960
        await provider.receive_audio(conn, frame, True)
        for _ in range(80):
            if provider._current and provider._current.reader:
                break
            await asyncio.sleep(0.01)
        self.assertIsNotNone(provider._current)
        ws = ws_hold["ws"]
        await ws.incoming.put('{"type":"session.created"}')
        for _ in range(50):
            try:
                await asyncio.wait_for(ws.outgoing.get(), 0.05)
                break
            except asyncio.TimeoutError:
                continue
        await ws.incoming.put('{"type":"session.updated","session":{}}')
        for _ in range(50):
            if provider._current and provider._current.state == "RUNNING":
                break
            await asyncio.sleep(0.01)
        request_stop(conn, "vad_silence")
        await provider.receive_audio(conn, b"", False)
        events = []
        while True:
            try:
                events.append(await asyncio.wait_for(ws.outgoing.get(), 0.3))
            except asyncio.TimeoutError:
                break
        self.assertTrue(
            any("input_audio_buffer.commit" in e for e in events),
            events,
        )
        await provider.close()

    async def test_listen_stop_flushes_qwen3_pending_before_commit(self):
        loop = asyncio.get_running_loop()
        outgoing = asyncio.Queue()
        incoming = asyncio.Queue()

        async def connect(url, headers):
            class WS:
                closed = False

                async def send(self, data):
                    await outgoing.put(data)

                async def recv(self):
                    return await incoming.get()

                async def close(self):
                    self.closed = True

            return WS()

        provider = ASRProvider(
            {
                "api_key": "sk-test",
                "ws_url": "ws://mock",
                "_connect": connect,
                "ready_timeout": 1,
                "result_timeout": 1,
            },
            True,
        )
        conn = _conn()
        conn.loop = loop
        conn.audio_format = "pcm"
        conn.asr = provider
        conn.vad = SimpleNamespace(is_vad=lambda _c, _a: True, silence_threshold_ms=200)
        provider.handle_voice_stop = lambda *a, **k: asyncio.sleep(0)

        worker = threading.Thread(
            target=ASRProviderBase.asr_text_priority_thread,
            args=(_DummyPriorityAsr(), conn),
            daemon=True,
        )
        worker.start()
        try:
            for i in range(1, 4):
                queue_audio(conn, bytes([i, 0]) * 960)
            for _ in range(80):
                if provider._current and provider._current.reader:
                    break
                await asyncio.sleep(0.01)
            self.assertIsNotNone(provider._current)
            await incoming.put(json.dumps({"type": "session.created"}))
            await incoming.put(json.dumps({"type": "session.updated", "session": {}}))
            for _ in range(80):
                if provider._current and provider._current.state == "RUNNING":
                    break
                await asyncio.sleep(0.01)
            self.assertEqual(provider._current.state, "RUNNING")
            queue_audio(conn, bytes([4, 0]) * 960)
            handler = ListenTextMessageHandler()
            await asyncio.wait_for(
                handler.handle(
                    conn, {"type": "listen", "state": "stop", "mode": "auto"}
                ),
                timeout=2,
            )
            events = []
            while True:
                try:
                    events.append(json.loads(await asyncio.wait_for(outgoing.get(), 0.3)))
                except asyncio.TimeoutError:
                    break
            appends = [e for e in events if e.get("type") == "input_audio_buffer.append"]
            commits = [e for e in events if e.get("type") == "input_audio_buffer.commit"]
            self.assertEqual(len(commits), 1)
            self.assertGreaterEqual(len(appends), 4)
            commit_at = next(i for i, e in enumerate(events) if e.get("type") == "input_audio_buffer.commit")
            last_append_at = max(
                i
                for i, e in enumerate(events)
                if e.get("type") == "input_audio_buffer.append"
            )
            self.assertLess(
                last_append_at,
                commit_at,
                "provider cache must flush before commit",
            )
        finally:
            conn.stop_event.set()
            worker.join(timeout=2)
            self.assertFalse(worker.is_alive())
            await provider.close()


if __name__ == "__main__":
    unittest.main()
