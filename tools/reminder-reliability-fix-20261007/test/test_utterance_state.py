"""Device-listen vs utterance-stop helpers. No upstream calls."""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.utils.utterance_state import (
    STOP_DEVICE,
    STOP_VAD,
    confirm_speech,
    finish_utterance,
    note_quiet_audio,
    note_speech_audio,
    on_listen_start,
    on_listen_stop,
    request_stop,
    should_start_asr,
    snapshot,
    stop_belongs_to,
)


class Conn:
    def __init__(self):
        self.listen_epoch = 1
        self.client_listen_mode = "auto"
        self.client_have_voice = False
        self.client_voice_stop = False
        self.client_voice_window = []
        self.client_audio_buffer = bytearray()
        self.last_is_voice = False


class UtteranceStateTests(unittest.TestCase):
    def test_listen_start_is_not_speech(self):
        conn = Conn()
        on_listen_start(conn)
        self.assertTrue(conn.device_listening)
        self.assertFalse(conn.client_have_voice)
        self.assertFalse(conn.vad_speech_confirmed)
        self.assertFalse(should_start_asr(conn, False))
        self.assertTrue(should_start_asr(conn, True))

    def test_pre_speech_silence_does_not_stop(self):
        conn = Conn()
        on_listen_start(conn)
        for _ in range(40):
            self.assertFalse(note_quiet_audio(conn, 60, 900))
        self.assertFalse(conn.client_voice_stop)
        self.assertEqual(conn.vad_audio_ms, 2400)

    def test_silence_uses_audio_time_not_wall_clock(self):
        conn = Conn()
        on_listen_start(conn)
        note_speech_audio(conn, 60)
        self.assertTrue(conn.vad_speech_confirmed)
        self.assertEqual(conn.utterance_id, 1)
        self.assertFalse(note_quiet_audio(conn, 60, 900))
        self.assertFalse(note_quiet_audio(conn, 800, 900))
        self.assertTrue(note_quiet_audio(conn, 100, 900))
        self.assertEqual(conn.utterance_stop_reason, STOP_VAD)
        self.assertTrue(stop_belongs_to(conn, 1))

    def test_new_speech_does_not_inherit_old_stop(self):
        conn = Conn()
        on_listen_start(conn)
        note_speech_audio(conn, 60)
        request_stop(conn, STOP_VAD)
        finish_utterance(conn, 1)
        self.assertFalse(conn.client_voice_stop)
        self.assertFalse(conn.vad_speech_confirmed)
        uid = confirm_speech(conn)
        self.assertEqual(uid, 2)
        self.assertFalse(conn.client_voice_stop)
        self.assertFalse(stop_belongs_to(conn, 1))

    def test_finish_does_not_clear_newer_utterance(self):
        conn = Conn()
        confirm_speech(conn)
        request_stop(conn, STOP_VAD)
        confirm_speech(conn)
        conn.utterance_id = 2
        conn.vad_speech_confirmed = True
        conn.client_have_voice = True
        conn.utterance_stop_id = 2
        conn.client_voice_stop = True
        finish_utterance(conn, 1)
        self.assertTrue(conn.client_voice_stop)
        self.assertEqual(conn.utterance_stop_id, 2)
        self.assertTrue(conn.vad_speech_confirmed)

    def test_device_stop_is_explicit_source(self):
        conn = Conn()
        on_listen_start(conn)
        confirm_speech(conn)
        change = on_listen_stop(conn)
        self.assertFalse(conn.device_listening)
        self.assertEqual(conn.utterance_stop_reason, STOP_DEVICE)
        self.assertEqual(change["reason"], STOP_DEVICE)
        snap = snapshot(conn)
        self.assertEqual(snap["utterance_stop_reason"], STOP_DEVICE)


if __name__ == "__main__":
    unittest.main()
