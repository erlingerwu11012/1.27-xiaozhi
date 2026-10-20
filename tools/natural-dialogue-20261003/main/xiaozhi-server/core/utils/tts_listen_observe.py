"""TTS 下行发送态与 listen 交叉观测。

区分两个概念：
- 服务端发送完毕：已发出本轮 tts.stop（或 abort stop）
- 设备本地播放完毕：固件侧，本模块不推断

listen 幂等仅在协议能明确标识「同一活动听写会话」时生效；
缺少 generation 时只记日志，不做有损去重。
"""

from __future__ import annotations

import time
from typing import Any, Optional, Tuple


def _mono_ms() -> int:
    return int(time.monotonic() * 1000)


def ensure_tts_outbound_fields(conn) -> None:
    if conn is None:
        return
    if not hasattr(conn, "_tts_start_sent"):
        conn._tts_start_sent = False
    if not hasattr(conn, "tts_stop_sent"):
        conn.tts_stop_sent = True
    if not hasattr(conn, "tts_turn_start_ms"):
        conn.tts_turn_start_ms = None
    if not hasattr(conn, "tts_last_audio_sent_ms"):
        conn.tts_last_audio_sent_ms = None
    if not hasattr(conn, "tts_turn_sentence_id"):
        conn.tts_turn_sentence_id = None
    if not hasattr(conn, "tts_turn_abort_epoch"):
        conn.tts_turn_abort_epoch = None
    if not hasattr(conn, "tts_last_ws_send_ms"):
        conn.tts_last_ws_send_ms = None
    if not hasattr(conn, "tts_max_ws_send_ms"):
        conn.tts_max_ws_send_ms = 0.0
    if not hasattr(conn, "tts_max_interframe_gap_ms"):
        conn.tts_max_interframe_gap_ms = 0


def tts_send_in_progress(conn) -> bool:
    """本轮已发 tts.start 且尚未发 tts.stop（服务端发送态）。"""
    ensure_tts_outbound_fields(conn)
    return bool(getattr(conn, "_tts_start_sent", False))


def note_tts_start_sent(conn) -> None:
    ensure_tts_outbound_fields(conn)
    now = _mono_ms()
    conn._tts_start_sent = True
    conn.tts_stop_sent = False
    conn.tts_turn_start_ms = now
    conn.tts_last_audio_sent_ms = None
    conn.tts_turn_sentence_id = getattr(conn, "sentence_id", None)
    conn.tts_turn_abort_epoch = int(getattr(conn, "tts_abort_epoch", 0) or 0)
    conn.tts_last_ws_send_ms = None
    conn.tts_max_ws_send_ms = 0.0
    conn.tts_max_interframe_gap_ms = 0


def note_tts_audio_sent(conn, *, ws_send_ms: Optional[float] = None) -> None:
    ensure_tts_outbound_fields(conn)
    now = _mono_ms()
    prev = getattr(conn, "tts_last_audio_sent_ms", None)
    if prev is not None:
        gap = now - int(prev)
        if gap > int(getattr(conn, "tts_max_interframe_gap_ms", 0) or 0):
            conn.tts_max_interframe_gap_ms = gap
    conn.tts_last_audio_sent_ms = now
    if ws_send_ms is not None:
        conn.tts_last_ws_send_ms = float(ws_send_ms)
        prev_max = float(getattr(conn, "tts_max_ws_send_ms", 0.0) or 0.0)
        if float(ws_send_ms) > prev_max:
            conn.tts_max_ws_send_ms = float(ws_send_ms)


def note_tts_stop_sent(conn) -> None:
    """标记服务端已派出（或完成）本轮 stop；不表示设备播完。"""
    ensure_tts_outbound_fields(conn)
    conn.tts_stop_sent = True
    conn._tts_start_sent = False


def reset_tts_outbound(conn) -> None:
    """异常/打断后清发送态，避免污染下一轮。"""
    ensure_tts_outbound_fields(conn)
    conn._tts_start_sent = False
    conn.tts_stop_sent = True


def _age_ms(now: int, then: Optional[int]) -> str:
    if then is None:
        return "n/a"
    return str(max(0, now - int(then)))


def log_listen_during_tts(conn, msg_json: dict, *, tag: str) -> None:
    """TTS 发送未结束时收到 listen start：仅观测，不丢弃。"""
    if not tts_send_in_progress(conn):
        return
    now = _mono_ms()
    mode = msg_json.get("mode", getattr(conn, "client_listen_mode", None))
    gen = msg_json.get("generation")
    session = getattr(conn, "session_id", None)
    mask = getattr(conn, "_mask", None)
    session_label = mask(session) if callable(mask) else session
    logger = getattr(conn, "logger", None)
    if logger is None:
        return
    logger.bind(tag=tag).info(
        f"[listen_during_tts] session={session_label} "
        f"sentence_id={getattr(conn, 'tts_turn_sentence_id', None)} "
        f"tts_abort_epoch={getattr(conn, 'tts_turn_abort_epoch', None)} "
        f"listen_mode={mode} device_generation={gen} "
        f"listen_epoch={getattr(conn, 'listen_epoch', None)} "
        f"tts_start_age_ms={_age_ms(now, getattr(conn, 'tts_turn_start_ms', None))} "
        f"last_audio_age_ms={_age_ms(now, getattr(conn, 'tts_last_audio_sent_ms', None))} "
        f"tts_stop_sent={bool(getattr(conn, 'tts_stop_sent', False))} "
        f"client_is_speaking={bool(getattr(conn, 'client_is_speaking', False))} "
        f"note=observe_only_aec_or_barge_in_may_be_valid"
    )


def _norm_generation(value: Any) -> Optional[int]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    return None


def classify_listen_start(conn, msg_json: dict) -> Tuple[str, bool]:
    """判定 listen start 是否可安全幂等跳过重置。

    Returns:
        (reason, skip_reset)
        skip_reset=True 仅当：已在听写、相同 mode、相同 generation、无有效语音。
        缺少 generation 时 skip_reset=False，并返回 no_generation_id。
    """
    if not getattr(conn, "device_listening", False):
        return "not_listening", False
    if getattr(conn, "vad_speech_confirmed", False) or getattr(
        conn, "client_have_voice", False
    ):
        return "speech_active", False
    if "mode" in msg_json:
        new_mode = msg_json.get("mode")
        cur_mode = getattr(conn, "client_listen_mode", None)
        if new_mode is not None and new_mode != cur_mode:
            return "mode_change", False
    incoming = _norm_generation(msg_json.get("generation"))
    previous = _norm_generation(getattr(conn, "device_listen_generation", None))
    if incoming is None or previous is None:
        return "no_generation_id", False
    if incoming != previous:
        return "new_generation", False
    return "same_generation_idle", True


def log_listen_start_decision(conn, msg_json: dict, reason: str, *, skip: bool, tag: str) -> None:
    logger = getattr(conn, "logger", None)
    if logger is None:
        return
    session = getattr(conn, "session_id", None)
    mask = getattr(conn, "_mask", None)
    session_label = mask(session) if callable(mask) else session
    prefix = "[listen_start_idempotent]" if skip else "[listen_start_observe]"
    logger.bind(tag=tag).info(
        f"{prefix} session={session_label} reason={reason} skip_reset={int(skip)} "
        f"listen_mode={msg_json.get('mode', getattr(conn, 'client_listen_mode', None))} "
        f"device_generation={msg_json.get('generation')} "
        f"prev_generation={getattr(conn, 'device_listen_generation', None)} "
        f"listen_epoch={getattr(conn, 'listen_epoch', None)} "
        f"device_listening={bool(getattr(conn, 'device_listening', False))} "
        f"vad_speech_confirmed={bool(getattr(conn, 'vad_speech_confirmed', False))} "
        f"client_have_voice={bool(getattr(conn, 'client_have_voice', False))}"
    )
