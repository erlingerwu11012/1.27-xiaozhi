"""Separate device-listen state from per-utterance speech/stop state.

listen_epoch: one device listen session (may contain many sentences).
utterance_id: one speech segment / ASR turn inside a listen session.

These helpers never log audio bytes or secrets.
"""
from __future__ import annotations

from typing import Optional


STOP_DEVICE = "device_stop"
STOP_VAD = "vad_silence"
STOP_ABORT = "abort"
STOP_NEW_LISTEN = "new_listen"
STOP_DISCONNECT = "disconnect"


def ensure_fields(conn) -> None:
    if conn is None:
        return
    if getattr(conn, "device_listening", None) is None:
        conn.device_listening = False
    if not hasattr(conn, "utterance_id"):
        conn.utterance_id = 0
    if not hasattr(conn, "vad_speech_confirmed"):
        conn.vad_speech_confirmed = False
    if not hasattr(conn, "utterance_stop_id"):
        conn.utterance_stop_id = 0
    if not hasattr(conn, "utterance_stop_reason"):
        conn.utterance_stop_reason = None
    if not hasattr(conn, "vad_audio_ms"):
        conn.vad_audio_ms = 0.0
    if not hasattr(conn, "vad_last_speech_audio_ms"):
        conn.vad_last_speech_audio_ms = 0.0


def snapshot(conn) -> dict:
    if conn is None:
        return {}
    ensure_fields(conn)
    return {
        "device_listening": bool(conn.device_listening),
        "listen_epoch": getattr(conn, "listen_epoch", 0),
        "utterance_id": int(conn.utterance_id or 0),
        "vad_speech_confirmed": bool(conn.vad_speech_confirmed),
        "client_have_voice": bool(getattr(conn, "client_have_voice", False)),
        "client_voice_stop": bool(getattr(conn, "client_voice_stop", False)),
        "utterance_stop_id": int(conn.utterance_stop_id or 0),
        "utterance_stop_reason": conn.utterance_stop_reason,
        "vad_audio_ms": conn.vad_audio_ms,
        "vad_last_speech_audio_ms": conn.vad_last_speech_audio_ms,
        "listen_mode": getattr(conn, "client_listen_mode", None),
    }


def on_listen_start(conn) -> dict:
    """New device listen: not the same as 'user already spoke'."""
    ensure_fields(conn)
    before = snapshot(conn)
    conn.device_listening = True
    conn.client_have_voice = False
    conn.vad_speech_confirmed = False
    conn.client_voice_stop = False
    conn.utterance_stop_reason = None
    conn.utterance_stop_id = 0
    conn.last_is_voice = False
    window = getattr(conn, "client_voice_window", None)
    if window is not None:
        try:
            window.clear()
        except Exception:
            pass
    conn.client_audio_buffer = bytearray()
    conn._vad_decoder = None
    conn._silero_rnn_state = None
    conn.vad_audio_ms = 0.0
    conn.vad_last_speech_audio_ms = 0.0
    conn._trace_vad_end_logged = False
    after = snapshot(conn)
    return {"before": before, "after": after, "reason": "listen_start"}


def on_listen_stop(conn) -> dict:
    """Explicit device listen stop. Does not imply a physical PTT release."""
    ensure_fields(conn)
    before = snapshot(conn)
    conn.device_listening = False
    request_stop(conn, STOP_DEVICE)
    # HTTP ASR still needs a stop edge; streaming ASR only commits a live session.
    conn.client_have_voice = True
    after = snapshot(conn)
    return {"before": before, "after": after, "reason": STOP_DEVICE}


def confirm_speech(conn) -> int:
    """Mark real VAD speech for the current utterance. Opens a new id if needed."""
    ensure_fields(conn)
    if not conn.vad_speech_confirmed:
        conn.utterance_id = int(conn.utterance_id or 0) + 1
        conn.vad_speech_confirmed = True
        if int(conn.utterance_stop_id or 0) != conn.utterance_id:
            conn.client_voice_stop = False
            conn.utterance_stop_reason = None
            conn.utterance_stop_id = 0
    conn.client_have_voice = True
    return conn.utterance_id


def add_audio_ms(conn, frame_ms: float) -> None:
    ensure_fields(conn)
    try:
        ms = float(frame_ms)
    except (TypeError, ValueError):
        ms = 0.0
    if ms > 0:
        conn.vad_audio_ms = float(conn.vad_audio_ms or 0.0) + ms


def note_speech_audio(conn, frame_ms: float) -> int:
    uid = confirm_speech(conn)
    add_audio_ms(conn, frame_ms)
    conn.vad_last_speech_audio_ms = float(conn.vad_audio_ms or 0.0)
    return uid


def note_quiet_audio(conn, frame_ms: float, silence_threshold_ms: float) -> bool:
    """Count processed quiet audio. Pre-speech silence must not end a turn."""
    ensure_fields(conn)
    add_audio_ms(conn, frame_ms)
    if not conn.vad_speech_confirmed:
        return False
    if stop_belongs_to(conn, conn.utterance_id):
        return False
    silence_ms = float(conn.vad_audio_ms or 0.0) - float(conn.vad_last_speech_audio_ms or 0.0)
    if silence_ms >= float(silence_threshold_ms):
        request_stop(conn, STOP_VAD)
        return True
    return False


def request_stop(conn, reason: str) -> None:
    ensure_fields(conn)
    conn.client_voice_stop = True
    conn.utterance_stop_reason = reason
    conn.utterance_stop_id = int(conn.utterance_id or 0)


def stop_belongs_to(conn, utterance_id: int) -> bool:
    if not getattr(conn, "client_voice_stop", False):
        return False
    stop_id = int(getattr(conn, "utterance_stop_id", 0) or 0)
    uid = int(utterance_id or 0)
    if stop_id == 0:
        current = int(getattr(conn, "utterance_id", 0) or 0)
        return uid == current or current == 0
    return stop_id == uid


def finish_utterance(conn, utterance_id: Optional[int] = None) -> dict:
    """Clear only this utterance's speech/stop flags. Newer turns stay intact."""
    if conn is None:
        return {"before": {}, "after": {}, "utterance_id": utterance_id}
    ensure_fields(conn)
    before = snapshot(conn)
    uid = int(conn.utterance_id or 0) if utterance_id is None else int(utterance_id or 0)
    if int(conn.utterance_stop_id or 0) == uid:
        conn.client_voice_stop = False
        conn.utterance_stop_reason = None
        conn.utterance_stop_id = 0
    if int(conn.utterance_id or 0) == uid:
        conn.client_have_voice = False
        conn.vad_speech_confirmed = False
        conn.last_is_voice = False
        window = getattr(conn, "client_voice_window", None)
        if window is not None:
            try:
                window.clear()
            except Exception:
                pass
        conn.client_audio_buffer = bytearray()
        conn._trace_vad_end_logged = False
    after = snapshot(conn)
    return {"before": before, "after": after, "utterance_id": uid}


def should_start_asr(conn, audio_have_voice: bool) -> bool:
    """Listen start / mode string is not enough; need confirmed speech."""
    ensure_fields(conn)
    if audio_have_voice:
        return True
    return bool(conn.vad_speech_confirmed)
