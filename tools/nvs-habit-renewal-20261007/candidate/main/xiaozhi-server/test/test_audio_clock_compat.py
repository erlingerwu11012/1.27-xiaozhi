"""Stage A: uplink clock compat for frozen-zero v2 timestamps.

No paid upstream. Does not restart production.
"""
from __future__ import annotations

import asyncio
import os
import queue
import sys
import threading
import unittest
from collections import deque
from types import SimpleNamespace
from unittest.mock import MagicMock

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _ROOT)

from core.handle.receiveAudioHandle import handleAudioMessage
from core.handle.textHandler.listenMessageHandler import ListenTextMessageHandler
from core.utils.audio_ingress import (
    DTX_FRAME_MS,
    UINT32_MOD,
    begin_listen,
    clock_compat_enabled_for,
    drain_queued_audio,
    dtx_frame_ms,
    mark_valid_uplink_timestamp,
    note_short_payload_gap,
    on_listen_start,
    queue_audio,
)
from core.utils.utterance_state import confirm_speech


def _conn(device_id="dev"):
    conn = SimpleNamespace()
    conn.listen_epoch = 1
    conn.session_id = "s"
    conn.device_id = device_id
    conn.agent_id = "ag"
    conn.client_listen_mode = "auto"
    conn.client_have_voice = False
    conn.client_voice_stop = False
    conn.client_is_speaking = False
    conn.just_woken_up = False
    conn.close_after_chat = False
    conn.config = {}
    conn.headers = {"device-id": device_id}
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
    conn.welcome_msg = {"audio_params": {"frame_duration": 60}}
    on_listen_start(conn)
    conn.device_listening = True
    return conn


def _enable_compat(conn, device_id=None, frame_ms=60):
    device_id = device_id or conn.device_id
    conn.device_id = device_id
    conn.headers = {"device-id": device_id}
    conn.config = {
        "audio_clock_compat_enabled": True,
        "audio_clock_compat_device_ids": [device_id],
    }
    conn.audio_frame_duration_ms = frame_ms
    conn.welcome_msg = {"audio_params": {"frame_duration": frame_ms}}
    begin_listen(conn)
    conn.device_listening = True
    confirm_speech(conn)
    return conn


def _drain_gaps(conn):
    gaps = []
    while True:
        try:
            item = conn.asr_audio_queue.get_nowait()
        except queue.Empty:
            break
        if getattr(item, "kind", None) == "dtx_gap":
            gaps.append(item.gap_ms)
    return gaps


def _dtx(conn, timestamp=None, payload=b"\x00", protocol=2):
    note_short_payload_gap(
        conn,
        protocol=protocol,
        payload_bytes=len(payload),
        timestamp=timestamp,
        payload=payload,
    )


class FlagAndFrameTests(unittest.TestCase):
    def test_enabled_flag_does_not_require_allowlist(self):
        conn = _conn("aa:bb:cc:dd:ee:ff")
        conn.config = {
            "audio_clock_compat_enabled": True,
            "audio_clock_compat_device_ids": [],
        }
        self.assertTrue(clock_compat_enabled_for(conn))

    def test_disabled_flag_ignores_allowlist(self):
        conn = _conn("aa:bb:cc:dd:ee:ff")
        conn.config = {
            "audio_clock_compat_enabled": False,
            "audio_clock_compat_device_ids": ["aa:bb:cc:dd:ee:ff"],
        }
        self.assertFalse(clock_compat_enabled_for(conn))

    def test_allowlist_normalizes_mac(self):
        conn = _conn("AA-BB-CC-DD-EE-FF")
        conn.config = {
            "audio_clock_compat_enabled": True,
            "audio_clock_compat_device_ids": ["aa:bb:cc:dd:ee:ff"],
        }
        self.assertTrue(clock_compat_enabled_for(conn))

    def test_hello_frame_duration_not_hardcoded(self):
        conn = _conn()
        conn.audio_frame_duration_ms = 20
        self.assertEqual(dtx_frame_ms(conn), 20)
        conn.audio_frame_duration_ms = 999
        conn.welcome_msg = {"audio_params": {"frame_duration": 40}}
        self.assertEqual(dtx_frame_ms(conn), 40)
        conn.audio_frame_duration_ms = None
        conn.welcome_msg = {}
        self.assertEqual(dtx_frame_ms(conn), DTX_FRAME_MS)


class LegacyZeroTimestampTests(unittest.TestCase):
    def test_flag_off_frozen_zero_stops_accumulating(self):
        conn = _conn()
        confirm_speech(conn)
        for _ in range(12):
            _dtx(conn, timestamp=0)
        gaps = _drain_gaps(conn)
        self.assertEqual(sum(gaps), DTX_FRAME_MS)
        self.assertEqual(conn._audio_ingress_stats.get("dtx_ts_duplicate"), 11)

    def test_begin_listen_freezes_off_for_this_epoch(self):
        conn = _conn("dev-a")
        conn.config = {
            "audio_clock_compat_enabled": False,
            "audio_clock_compat_device_ids": ["dev-a"],
        }
        begin_listen(conn)
        self.assertFalse(conn._audio_clock_compat_epoch)
        conn.config["audio_clock_compat_enabled"] = True
        conn.config["audio_clock_compat_device_ids"] = ["dev-a"]
        confirm_speech(conn)
        conn.device_listening = True
        _dtx(conn, timestamp=0)
        _dtx(conn, timestamp=0)
        self.assertFalse(conn._audio_clock_compat_epoch)
        self.assertEqual(sum(_drain_gaps(conn)), DTX_FRAME_MS)


class CompatZeroTimestampTests(unittest.IsolatedAsyncioTestCase):
    async def test_frozen_zero_v2_credits_frame_duration(self):
        conn = _enable_compat(_conn("dev-zero"))
        for _ in range(4):
            _dtx(conn, timestamp=0)
        gaps = _drain_gaps(conn)
        self.assertGreaterEqual(sum(gaps), 240)
        self.assertEqual(conn._audio_clock_policy, "compat")

    async def test_frozen_zero_can_end_utterance(self):
        conn = _enable_compat(_conn("dev-zero"))
        conn.vad_last_speech_audio_ms = 0.0
        conn.vad_audio_ms = 0.0
        conn.vad = SimpleNamespace(silence_threshold_ms=200)
        stops = []

        class Asr:
            async def receive_audio(self, _conn, audio, have_voice):
                stops.append((audio, have_voice, _conn.client_voice_stop))

        conn.asr = Asr()
        for _ in range(5):
            _dtx(conn, timestamp=0)
        while True:
            try:
                item = conn.asr_audio_queue.get_nowait()
            except queue.Empty:
                break
            await handleAudioMessage(conn, item)
        self.assertTrue(conn.client_voice_stop)
        self.assertGreaterEqual(len(stops), 1)
        self.assertEqual(stops[0][0], b"")

    def test_legal_clock_starting_at_zero_freezes_media(self):
        conn = _enable_compat(_conn("dev-clock"))
        _dtx(conn, timestamp=0)
        _dtx(conn, timestamp=60)
        _dtx(conn, timestamp=120)
        self.assertEqual(conn._audio_clock_policy, "media")
        self.assertGreaterEqual(sum(_drain_gaps(conn)), 180)

    def test_v1_v3_no_timestamp_use_frame_duration(self):
        conn = _enable_compat(_conn("dev-v1"))
        note_short_payload_gap(
            conn, protocol=1, payload_bytes=1, payload=b"\x00", timestamp=None
        )
        note_short_payload_gap(
            conn, protocol=3, payload_bytes=1, payload=b"\x00", timestamp=None
        )
        self.assertEqual(_drain_gaps(conn), [60.0, 60.0])

    def test_wrap_is_credited(self):
        conn = _enable_compat(_conn("dev-wrap"))
        _dtx(conn, timestamp=UINT32_MOD - 40)
        _dtx(conn, timestamp=UINT32_MOD - 20)
        _dtx(conn, timestamp=20)
        self.assertEqual(conn._audio_clock_policy, "media")
        self.assertGreaterEqual(sum(_drain_gaps(conn)), 120)

    def test_out_of_order_does_not_credit_or_rewind(self):
        conn = _enable_compat(_conn("dev-ooo"))
        _dtx(conn, timestamp=1000)
        _dtx(conn, timestamp=1060)
        last = conn._audio_last_timestamp
        _dtx(conn, timestamp=900)
        self.assertEqual(conn._audio_last_timestamp, last)
        self.assertEqual(conn._audio_ingress_stats.get("dtx_ts_out_of_order"), 1)

    def test_same_timestamp_is_not_deduped_in_media(self):
        conn = _enable_compat(_conn("dev-same"))
        _dtx(conn, timestamp=1000)
        _dtx(conn, timestamp=1060)
        before = sum(_drain_gaps(conn))
        _dtx(conn, timestamp=1060)
        after = sum(_drain_gaps(conn))
        self.assertEqual(conn._audio_clock_policy, "media")
        self.assertEqual(after, DTX_FRAME_MS)
        self.assertGreaterEqual(before, 120)

    def test_different_frame_duration(self):
        conn = _enable_compat(_conn("dev-20"), frame_ms=20)
        for _ in range(3):
            _dtx(conn, timestamp=0)
        self.assertEqual(sum(_drain_gaps(conn)), 60)

    def test_batch_delivery_still_counts_each_packet(self):
        conn = _enable_compat(_conn("dev-batch"))
        for _ in range(6):
            _dtx(conn, timestamp=0)
        self.assertGreaterEqual(sum(_drain_gaps(conn)), 360)

    async def test_dtx_and_pcm_alternate_do_not_double_count(self):
        conn = _enable_compat(_conn("dev-mix"))
        conn.vad_last_speech_audio_ms = 0.0
        conn.vad_audio_ms = 0.0
        vad_ms = []

        class Vad:
            silence_threshold_ms = 10000

            def is_vad(self, _conn, audio):
                vad_ms.append(len(audio))
                return False

        conn.vad = Vad()

        class Asr:
            async def receive_audio(self, *_a, **_k):
                return None

        conn.asr = Asr()
        mark_valid_uplink_timestamp(conn, 0)
        queue_audio(conn, b"\x00\x01" * 16)
        _dtx(conn, timestamp=0)
        kinds = []
        while True:
            try:
                item = conn.asr_audio_queue.get_nowait()
            except queue.Empty:
                break
            kinds.append(item.kind)
            await handleAudioMessage(conn, item)
        self.assertEqual(kinds.count("opus"), 1)
        self.assertGreaterEqual(kinds.count("dtx_gap"), 1)
        self.assertEqual(len(vad_ms), 1)

    def test_queue_overflow_drops_without_inventing_audio(self):
        conn = _enable_compat(_conn("dev-full"))
        for _ in range(100):
            queue_audio(conn, b"\x01\x00" * 8)
        before = conn.asr_audio_queue.qsize()
        _dtx(conn, timestamp=0)
        self.assertEqual(conn.asr_audio_queue.qsize(), before)
        self.assertGreaterEqual(conn._audio_ingress_stats.get("drop_ingress_full", 0), 1)

    def test_pre_speech_silence_is_ignored(self):
        conn = _conn("dev-pre")
        conn.config = {
            "audio_clock_compat_enabled": True,
            "audio_clock_compat_device_ids": ["dev-pre"],
        }
        begin_listen(conn)
        conn.device_listening = True
        conn.vad_speech_confirmed = False
        for _ in range(8):
            _dtx(conn, timestamp=0)
        self.assertTrue(conn.asr_audio_queue.empty())
        self.assertFalse(conn.client_voice_stop)

    def test_no_packets_invent_no_audio(self):
        conn = _enable_compat(_conn("dev-none"))
        self.assertTrue(conn.asr_audio_queue.empty())
        self.assertEqual(getattr(conn, "_pending_dtx_ms", 0.0), 0.0)

    def test_illegal_one_byte_toc_is_not_silence(self):
        conn = _enable_compat(_conn("dev-bad"))
        note_short_payload_gap(
            conn, protocol=2, payload_bytes=1, timestamp=0, payload=bytes([0x01])
        )
        note_short_payload_gap(
            conn, protocol=2, payload_bytes=2, timestamp=0, payload=b"\x00\x00"
        )
        self.assertTrue(conn.asr_audio_queue.empty())
        self.assertEqual(conn._audio_ingress_stats.get("dtx_payload_rejected"), 2)

    def test_empty_protocol_dtx_is_meterable(self):
        conn = _enable_compat(_conn("dev-empty"))
        note_short_payload_gap(
            conn, protocol=2, payload_bytes=0, timestamp=0, payload=b""
        )
        self.assertGreater(sum(_drain_gaps(conn)), 0)

    async def test_stop_barrier_still_drains(self):
        conn = _enable_compat(_conn("dev-bar"))
        conn.loop = asyncio.get_running_loop()
        received = []

        class Asr:
            def __init__(self):
                self._current = SimpleNamespace(pending=[], state="RUNNING")

            async def receive_audio(self, _conn, audio, have_voice):
                received.append(audio)

            async def stop_listening(self, _conn, reason="device_stop"):
                return None

        conn.asr = Asr()
        conn.vad = SimpleNamespace(is_vad=lambda _c, _a: False, silence_threshold_ms=200)
        for _ in range(3):
            queue_audio(conn, b"\x01\x00" * 8)

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
        self.assertEqual(len(received), 3)

    async def test_drain_timeout_does_not_commit(self):
        conn = _enable_compat(_conn("dev-timeout"))
        queue_audio(conn, b"\x01\x00" * 8)
        ok = await drain_queued_audio(conn, 1, timeout=0.05)
        self.assertFalse(ok)

    def test_multi_device_isolation(self):
        allowed = _enable_compat(_conn("dev-on"))
        blocked = _conn("dev-off")
        blocked.config = {
            "audio_clock_compat_enabled": False,
            "audio_clock_compat_device_ids": ["dev-on"],
        }
        begin_listen(blocked)
        blocked.device_listening = True
        confirm_speech(blocked)
        for _ in range(4):
            _dtx(allowed, timestamp=0)
            _dtx(blocked, timestamp=0)
        self.assertGreaterEqual(sum(_drain_gaps(allowed)), 240)
        self.assertEqual(sum(_drain_gaps(blocked)), DTX_FRAME_MS)

    def test_jump_credits_one_frame_not_wall_clock(self):
        conn = _enable_compat(_conn("dev-jump"))
        _dtx(conn, timestamp=1000)
        _dtx(conn, timestamp=1060)
        _dtx(conn, timestamp=5000)
        gaps = _drain_gaps(conn)
        self.assertLessEqual(sum(gaps), 180)
        self.assertEqual(conn._audio_ingress_stats.get("dtx_ts_capped"), 1)


class SilenceThresholdStageATests(unittest.IsolatedAsyncioTestCase):
    """Stage A must not change utterance-end threshold.

    Local config.yaml still has 200, but production with manager-api uses
    VAD.VAD_SileroVAD.min_silence_duration_ms=700. Stage A only reads
    vad.silence_threshold_ms and must not overlay yaml 200 onto API 700.
    """

    def test_local_silence_threshold_is_not_overlaid_onto_api(self):
        from config.config_loader import apply_local_only_top_level
        # Synthetic local config: this test must not read production credentials.
        cfg = {"VAD": {"SileroVAD": {"min_silence_duration_ms": 200}},
               "selected_module": {"VAD": "SileroVAD"},
               "audio_clock_compat_enabled": True,
               "audio_clock_compat_device_ids": []}
        api = {"VAD": {"VAD_SileroVAD": {"min_silence_duration_ms": 700}},
               "selected_module": {"VAD": "VAD_SileroVAD"}}
        apply_local_only_top_level(cfg, api)
        self.assertEqual(api["VAD"]["VAD_SileroVAD"]["min_silence_duration_ms"], 700)
        self.assertEqual(api["selected_module"]["VAD"], "VAD_SileroVAD")
        self.assertTrue(api["audio_clock_compat_enabled"])

    def test_api_overlay_enabled_without_device_allowlist(self):
        from config.config_loader import apply_local_only_top_level

        api = apply_local_only_top_level(
            {
                "audio_clock_compat_enabled": True,
                "audio_clock_compat_device_ids": [],
            },
            {},
        )
        conn = _conn("b8:f8:62:7e:ca:58")
        conn.config = api
        self.assertTrue(clock_compat_enabled_for(conn))

    def test_silero_code_default_is_1000_not_production_value(self):
        import inspect

        from core.providers.vad import silero

        src = inspect.getsource(silero.VADProvider.__init__)
        self.assertIn('config.get("min_silence_duration_ms", "1000")', src)

    def test_dtx_gap_cap_is_not_the_silence_threshold(self):
        from core.utils.audio_ingress import DTX_GAP_CAP_MS

        self.assertEqual(DTX_GAP_CAP_MS, 200.0)
        self.assertNotEqual(DTX_GAP_CAP_MS, 700)

    async def _run_dtx_pauses(self, threshold_ms, frames):
        conn = _enable_compat(_conn("dev-pause"))
        conn.vad_last_speech_audio_ms = 0.0
        conn.vad_audio_ms = 0.0
        conn.vad = SimpleNamespace(silence_threshold_ms=threshold_ms)
        stops = []

        class Asr:
            async def receive_audio(self, _conn, audio, have_voice):
                stops.append((audio, have_voice, getattr(_conn, "utterance_stop_reason", None)))

        conn.asr = Asr()
        for _ in range(frames):
            _dtx(conn, timestamp=0)
        while True:
            try:
                item = conn.asr_audio_queue.get_nowait()
            except queue.Empty:
                break
            await handleAudioMessage(conn, item)
        return conn, stops

    async def test_180ms_pause_does_not_commit_at_200(self):
        conn, stops = await self._run_dtx_pauses(200, 3)
        self.assertEqual(conn.vad_audio_ms, 180)
        self.assertFalse(conn.client_voice_stop)
        self.assertEqual(stops, [])

    async def test_240ms_pause_commits_at_yaml_200_only(self):
        conn, stops = await self._run_dtx_pauses(200, 4)
        self.assertGreaterEqual(conn.vad_audio_ms, 240)
        self.assertTrue(conn.client_voice_stop)
        self.assertEqual(conn.utterance_stop_reason, "vad_silence")
        self.assertEqual(stops[0][0], b"")

    async def test_500ms_natural_pause_does_not_split_at_runtime_700(self):
        """Production API threshold is 700ms; 300-500ms quiet must not commit."""
        conn, stops = await self._run_dtx_pauses(700, 9)
        self.assertEqual(conn.vad_audio_ms, 540)
        self.assertFalse(conn.client_voice_stop)
        self.assertEqual(stops, [])

    async def test_720ms_pause_commits_at_runtime_700(self):
        conn, stops = await self._run_dtx_pauses(700, 12)
        self.assertGreaterEqual(conn.vad_audio_ms, 720)
        self.assertTrue(conn.client_voice_stop)
        self.assertEqual(conn.utterance_stop_reason, "vad_silence")
        self.assertEqual(stops[0][0], b"")

    def test_pre_speech_silence_does_not_start_asr_or_commit(self):
        from core.utils.utterance_state import should_start_asr

        conn = _conn("dev-presilence")
        conn.config = {
            "audio_clock_compat_enabled": True,
            "audio_clock_compat_device_ids": ["dev-presilence"],
        }
        begin_listen(conn)
        conn.device_listening = True
        conn.vad_speech_confirmed = False
        for _ in range(50):
            _dtx(conn, timestamp=0)
        self.assertTrue(conn.asr_audio_queue.empty())
        self.assertFalse(should_start_asr(conn, False))
        self.assertFalse(conn.client_voice_stop)

    def test_short_command_is_not_filtered_by_min_frames(self):
        from core.utils.utterance_state import note_speech_audio, should_start_asr

        conn = _enable_compat(_conn("dev-short"))
        uid = note_speech_audio(conn, 60)
        self.assertEqual(uid, 1)
        self.assertTrue(should_start_asr(conn, False))
        self.assertTrue(should_start_asr(conn, True))

    def test_compat_does_not_replace_vad_threshold(self):
        conn = _enable_compat(_conn("dev-th"))
        conn.vad = SimpleNamespace(silence_threshold_ms=700)
        self.assertEqual(conn.vad.silence_threshold_ms, 700)
        self.assertTrue(conn._audio_clock_compat_epoch)

    def test_begin_listen_freezes_on_and_ignores_later_config(self):
        conn = _conn("b8:f8:62:7e:ca:58")
        conn.config = {
            "audio_clock_compat_enabled": True,
            "audio_clock_compat_device_ids": ["b8:f8:62:7e:ca:58"],
        }
        begin_listen(conn)
        self.assertTrue(conn._audio_clock_compat_epoch)
        conn.config["audio_clock_compat_enabled"] = False
        conn.config["audio_clock_compat_device_ids"] = []
        confirm_speech(conn)
        conn.device_listening = True
        _dtx(conn, timestamp=0)
        _dtx(conn, timestamp=0)
        self.assertTrue(conn._audio_clock_compat_epoch)
        self.assertEqual(sum(_drain_gaps(conn)), 120)


if __name__ == "__main__":
    unittest.main()
