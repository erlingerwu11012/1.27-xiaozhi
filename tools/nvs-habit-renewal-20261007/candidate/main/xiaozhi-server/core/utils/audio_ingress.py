"""Listen epochs and bounded ingress accounting; no audio contents are logged."""
import json
import time
import queue
import asyncio
from dataclasses import dataclass
from core.utils.utterance_state import on_listen_start


DTX_FRAME_MS = 60.0
DTX_GAP_CAP_MS = 200.0
DRAIN_TIMEOUT_SEC = 0.8
UINT32_MOD = 2 ** 32
# Opus frame durations accepted from hello audio_params.frame_duration.
FRAME_DURATION_MIN_MS = 10.0
FRAME_DURATION_MAX_MS = 120.0


@dataclass(frozen=True)
class AudioIngress:
    epoch: int
    payload: bytes
    seq: int = 0
    kind: str = "opus"  # opus | dtx_gap
    gap_ms: float = 0.0


def audio_count(conn, key, count=1):
    stats = getattr(conn, '_audio_ingress_stats', None)
    if not isinstance(stats, dict):
        stats = {}
        conn._audio_ingress_stats = stats
    stats[key] = stats.get(key, 0) + count


def log_audio_stats(conn, reason):
    if not conn:
        return
    data = dict(getattr(conn, '_audio_ingress_stats', {}) or {})
    data.update(reason=reason, listen_epoch=getattr(conn,'listen_epoch',0),
                device_generation=getattr(conn,'device_listen_generation',None),
                session_id=getattr(conn,'session_id',''),
                clock_compat=getattr(conn, '_audio_clock_compat_epoch', False),
                clock_policy=getattr(conn, '_audio_clock_policy', None))
    conn.logger.bind(tag='audio_ingress').info('[AUDIO_UL] ' + json.dumps(data,ensure_ascii=True))
    conn._audio_stats_at = time.monotonic()


def clock_compat_enabled_for(conn) -> bool:
    """Global: enabled for every device when the flag is on.

    白名单已移除；实际是否采用 compat 行为仍由 _observe_timestamp()
    按每设备真实时间戳自适应判定，正常递增时钟的设备保持 media 行为。
    """
    cfg = getattr(conn, "config", None) or {}
    return bool(cfg.get("audio_clock_compat_enabled"))


def dtx_frame_ms(conn) -> float:
    """Per-connection frame duration from hello; 60ms only as last-resort default."""
    candidates = []
    direct = getattr(conn, "audio_frame_duration_ms", None)
    if direct is not None:
        candidates.append(direct)
    welcome = getattr(conn, "welcome_msg", None)
    if isinstance(welcome, dict):
        params = welcome.get("audio_params")
        if isinstance(params, dict) and params.get("frame_duration") is not None:
            candidates.append(params.get("frame_duration"))
    audio_format = getattr(conn, "audio_format", None)
    if isinstance(audio_format, dict) and audio_format.get("frame_duration") is not None:
        candidates.append(audio_format.get("frame_duration"))
    for raw in candidates:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if FRAME_DURATION_MIN_MS <= value <= FRAME_DURATION_MAX_MS:
            return value
    return DTX_FRAME_MS


def _freeze_clock_for_listen(conn):
    conn._audio_clock_epoch_id = getattr(conn, "listen_epoch", 0)
    conn._audio_clock_compat_epoch = clock_compat_enabled_for(conn)
    conn._audio_clock_policy = None
    conn._audio_clock_equal_streak = 0
    audio_count(conn, "clock_compat_on" if conn._audio_clock_compat_epoch else "clock_compat_off")


def _ensure_clock_epoch(conn):
    epoch = getattr(conn, "listen_epoch", 0)
    if getattr(conn, "_audio_clock_epoch_id", object()) != epoch:
        _freeze_clock_for_listen(conn)


def begin_listen(conn, generation=None):
    log_audio_stats(conn,'before_listen_reset')
    conn.listen_epoch = getattr(conn,'listen_epoch',0) + 1
    conn.device_listen_generation = generation if isinstance(generation,int) and not isinstance(generation,bool) else None
    conn._audio_ingress_stats = {}
    conn._audio_stats_at = time.monotonic()
    conn._asr_start_logged = False
    conn._trace_last_have_voice = False
    conn._trace_vad_end_logged = False
    conn._trace_vad_pcm = {"frames": 0, "bytes": 0, "ms": 0.0, "decode_errors": 0}
    conn._pending_dtx_ms = 0.0
    conn._audio_last_timestamp = None
    on_listen_start(conn)
    _freeze_clock_for_listen(conn)
    return conn.listen_epoch


def _next_seq(conn):
    conn._audio_seq = int(getattr(conn,'_audio_seq', 0) or 0) + 1
    return conn._audio_seq


def _put_ingress(conn, ingress: AudioIngress):
    try:
        queue_size = int(conn.asr_audio_queue.qsize())
    except (AttributeError, TypeError, ValueError):
        queue_size = 0
    if queue_size >= 100:
        audio_count(conn,'drop_ingress_full')
        try:
            from core.utils import trace_log as trace
            trace.emit(
                "audio.ingress_drop",
                conn,
                {"reason": "queue_full", "queue_size": queue_size, "kind": ingress.kind},
            )
        except Exception:
            pass
        return False
    try:
        conn.asr_audio_queue.put_nowait(ingress)
        audio_count(conn,'queued_frames')
        return True
    except queue.Full:
        audio_count(conn,'drop_ingress_full')
        return False


def queue_audio(conn, payload):
    audio_count(conn,'received_payload_frames')
    audio_count(conn,'received_payload_bytes',len(payload))
    flush_pending_dtx(conn)
    seq = _next_seq(conn)
    _put_ingress(conn, AudioIngress(getattr(conn,'listen_epoch',0), payload, seq=seq, kind="opus"))
    last_stats = getattr(conn,'_audio_stats_at', None)
    if last_stats and time.monotonic()-last_stats >= 5:
        log_audio_stats(conn,'periodic')


def flush_pending_dtx(conn):
    pending = float(getattr(conn, '_pending_dtx_ms', 0.0) or 0.0)
    if pending <= 0:
        return
    conn._pending_dtx_ms = 0.0
    seq = _next_seq(conn)
    _put_ingress(
        conn,
        AudioIngress(
            getattr(conn, 'listen_epoch', 0),
            b"",
            seq=seq,
            kind="dtx_gap",
            gap_ms=pending,
        ),
    )
    audio_count(conn, 'dtx_gap_events')
    audio_count(conn, 'dtx_gap_ms', int(pending))


def _conn_closing(conn) -> bool:
    ev = getattr(conn, "stop_event", None)
    if ev is None:
        return False
    try:
        return bool(ev.is_set())
    except Exception:
        return False


def _is_meterable_dtx_payload(payload_bytes, payload=None) -> bool:
    """Only protocol-validated short DTX is meterable.

    Empty raw bytes are protocol-level DTX after a valid header. A 1-byte
    payload must be a complete Opus packet (TOC code 0). Incomplete TOC
    (code 1/2/3) is a truncated multi-frame packet and is not silence.
    """
    try:
        size = int(payload_bytes)
    except (TypeError, ValueError):
        return False
    if size < 0 or size > 1:
        return False
    if payload is None:
        return True
    if not isinstance(payload, (bytes, bytearray)):
        return size <= 1
    if size == 0:
        return len(payload) == 0
    if len(payload) == 0:
        return True
    if len(payload) != 1:
        return False
    return (payload[0] & 0x03) == 0


def _classify_timestamp(last_ts, timestamp):
    if timestamp is None:
        return "no_timestamp"
    if last_ts is None:
        return "first"
    try:
        last_f = float(last_ts)
        ts_f = float(timestamp)
    except (TypeError, ValueError):
        return "invalid"
    raw = ts_f - last_f
    if raw == 0:
        return "same"
    if raw > 0:
        if raw <= DTX_GAP_CAP_MS:
            return "increment"
        return "jump"
    wrapped = raw + UINT32_MOD
    wrap_window = max(DTX_GAP_CAP_MS * 2.0, 1000.0)
    if last_f >= (UINT32_MOD - wrap_window) and 0 < wrapped <= DTX_GAP_CAP_MS:
        return "wrap"
    return "out_of_order"


def _advance_last_timestamp(conn, timestamp, kind):
    if kind in ("out_of_order", "invalid", "no_timestamp"):
        return
    conn._audio_last_timestamp = timestamp


def _observe_timestamp(conn, timestamp):
    """Freeze media/compat from consecutive observations. Never credits silence."""
    if not getattr(conn, "_audio_clock_compat_epoch", False):
        return
    if timestamp is None:
        return
    policy = getattr(conn, "_audio_clock_policy", None)
    last = getattr(conn, "_audio_last_timestamp", None)
    kind = _classify_timestamp(last, timestamp)
    if policy is None:
        if kind in ("increment", "wrap", "jump"):
            conn._audio_clock_policy = "media"
            conn._audio_clock_equal_streak = 0
            audio_count(conn, "clock_policy_media")
        elif kind == "same":
            streak = int(getattr(conn, "_audio_clock_equal_streak", 0) or 0) + 1
            conn._audio_clock_equal_streak = streak
            if streak >= 1:
                conn._audio_clock_policy = "compat"
                audio_count(conn, "clock_policy_compat")
        elif kind == "first":
            conn._audio_clock_equal_streak = 0
    _advance_last_timestamp(conn, timestamp, kind)


def _dtx_legacy_gap_ms(conn, timestamp):
    """Original media-clock delta. Same timestamp returns 0 (includes frozen-zero bug)."""
    if timestamp is None:
        return DTX_FRAME_MS, "no_timestamp_default_frame"
    last_ts = getattr(conn, "_audio_last_timestamp", None)
    if last_ts is None:
        conn._audio_last_timestamp = timestamp
        return DTX_FRAME_MS, "first_timestamp_default_frame"
    try:
        delta = float(timestamp) - float(last_ts)
    except (TypeError, ValueError):
        audio_count(conn, "dtx_ts_invalid")
        return DTX_FRAME_MS, "invalid_timestamp_default_frame"
    if delta == 0:
        audio_count(conn, "dtx_ts_duplicate")
        return 0.0, "duplicate"
    if delta < 0:
        audio_count(conn, "dtx_ts_out_of_order")
        return 0.0, "out_of_order"
    conn._audio_last_timestamp = timestamp
    if delta > DTX_GAP_CAP_MS:
        audio_count(conn, "dtx_ts_capped")
        return DTX_FRAME_MS, "delta_capped_default_frame"
    return delta, "media_delta"


def _dtx_compat_gap_ms(conn, timestamp):
    """Observe then freeze; never re-count already credited packets via media delta."""
    frame = dtx_frame_ms(conn)
    last = getattr(conn, "_audio_last_timestamp", None)
    kind = _classify_timestamp(last, timestamp)
    policy = getattr(conn, "_audio_clock_policy", None)

    if policy is None:
        _observe_timestamp(conn, timestamp)
        if kind == "out_of_order":
            audio_count(conn, "dtx_ts_out_of_order")
            return 0.0, "out_of_order"
        if kind == "invalid":
            audio_count(conn, "dtx_ts_invalid")
            return frame, "invalid_timestamp_default_frame"
        return frame, "observe_frame"

    if policy == "compat":
        _advance_last_timestamp(conn, timestamp, kind)
        if kind == "invalid":
            audio_count(conn, "dtx_ts_invalid")
            return frame, "invalid_timestamp_default_frame"
        return frame, "compat_frame"

    # media: usable clock. Same timestamp is not treated as duplicate audio.
    if kind == "first":
        conn._audio_last_timestamp = timestamp
        return frame, "first_timestamp_default_frame"
    if kind == "same":
        return frame, "media_same_ts_frame"
    if kind == "out_of_order":
        audio_count(conn, "dtx_ts_out_of_order")
        return 0.0, "out_of_order"
    if kind == "invalid":
        audio_count(conn, "dtx_ts_invalid")
        return frame, "invalid_timestamp_default_frame"
    conn._audio_last_timestamp = timestamp
    if kind == "increment":
        return float(timestamp) - float(last), "media_delta"
    if kind == "wrap":
        return float(timestamp) - float(last) + UINT32_MOD, "media_wrap"
    audio_count(conn, "dtx_ts_capped")
    return frame, "delta_capped_default_frame"


def _dtx_media_gap_ms(conn, timestamp):
    """Gap from media clock or compat frame duration. Never uses packet arrival interval."""
    _ensure_clock_epoch(conn)
    if getattr(conn, "_audio_clock_compat_epoch", False):
        return _dtx_compat_gap_ms(conn, timestamp)
    return _dtx_legacy_gap_ms(conn, timestamp)


def note_short_payload_gap(conn, *, protocol, payload_bytes, timestamp=None, payload=None):
    """Short/DTX uplink is not PCM. After confirmed speech it may advance silence."""
    audio_count(conn, 'payload_too_small')
    if not getattr(conn, 'device_listening', False):
        return
    if not getattr(conn, 'vad_speech_confirmed', False):
        return
    if not _is_meterable_dtx_payload(payload_bytes, payload):
        audio_count(conn, "dtx_payload_rejected")
        return
    gap, reason = _dtx_media_gap_ms(conn, timestamp)
    audio_count(conn, f"dtx_gap_{reason}")
    if gap <= 0:
        return
    conn._pending_dtx_ms = float(getattr(conn, '_pending_dtx_ms', 0.0) or 0.0) + gap
    flush_at = (
        dtx_frame_ms(conn)
        if getattr(conn, "_audio_clock_compat_epoch", False)
        else DTX_FRAME_MS
    )
    if conn._pending_dtx_ms >= flush_at:
        flush_pending_dtx(conn)


def mark_valid_uplink_timestamp(conn, timestamp=None):
    """Opus path: update clock observation only. Do not credit silence here."""
    if timestamp is None:
        return
    _ensure_clock_epoch(conn)
    if getattr(conn, "_audio_clock_compat_epoch", False):
        _observe_timestamp(conn, timestamp)
        return
    conn._audio_last_timestamp = timestamp


def drain_barrier_seq(conn):
    flush_pending_dtx(conn)
    return int(getattr(conn, '_audio_seq', 0) or 0)


def _drain_snapshot(conn, barrier_seq):
    leftover_q = 0
    try:
        leftover_q = int(conn.asr_audio_queue.qsize())
    except Exception:
        leftover_q = 0
    return {
        "barrier_seq": barrier_seq,
        "processed_seq": int(getattr(conn, "_audio_processed_seq", 0) or 0),
        "inflight": int(getattr(conn, "asr_audio_inflight", 0) or 0),
        "inflight_seq": int(getattr(conn, "_audio_inflight_seq", 0) or 0),
        "queue_size": leftover_q,
        "listen_epoch": getattr(conn, "listen_epoch", 0),
        "clock_compat": getattr(conn, "_audio_clock_compat_epoch", False),
        "clock_policy": getattr(conn, "_audio_clock_policy", None),
    }


def _emit_drain(conn, ok, reason, barrier_seq, extra=None):
    body = _drain_snapshot(conn, barrier_seq)
    body.update(ok=ok, reason=reason)
    if extra:
        body.update(extra)
    try:
        from core.utils import trace_log as trace
        trace.emit("audio.listen_stop_drain", conn, body)
    except Exception:
        pass


async def drain_queued_audio(conn, barrier_seq, timeout=None, *, epoch=None):
    """Wait until processed_seq >= barrier and the barrier frame is not inflight.

    sleep(0) only yields the event loop so the receive worker can run. Success is
    never inferred from having yielded. Abort on disconnect or a newer listen epoch.
    """
    if timeout is None:
        timeout = DRAIN_TIMEOUT_SEC
    start_epoch = getattr(conn, "listen_epoch", 0) if epoch is None else epoch
    deadline = time.monotonic() + float(timeout)
    while True:
        if _conn_closing(conn):
            audio_count(conn, "listen_stop_drain_disconnect")
            _emit_drain(conn, False, "disconnect", barrier_seq)
            return False
        if getattr(conn, "listen_epoch", 0) != start_epoch:
            audio_count(conn, "listen_stop_drain_epoch_changed")
            _emit_drain(conn, False, "new_listen_epoch", barrier_seq)
            return False
        processed = int(getattr(conn, "_audio_processed_seq", 0) or 0)
        inflight = int(getattr(conn, "asr_audio_inflight", 0) or 0)
        inflight_seq = int(getattr(conn, "_audio_inflight_seq", 0) or 0)
        if processed >= barrier_seq and (
            inflight <= 0 or inflight_seq > barrier_seq
        ):
            _emit_drain(conn, True, "processed_seq", barrier_seq)
            return True
        if time.monotonic() >= deadline:
            audio_count(conn, "listen_stop_drain_timeout")
            _emit_drain(
                conn,
                False,
                "timeout",
                barrier_seq,
                extra={"timeout_sec": timeout},
            )
            return False
        await asyncio.sleep(0)
