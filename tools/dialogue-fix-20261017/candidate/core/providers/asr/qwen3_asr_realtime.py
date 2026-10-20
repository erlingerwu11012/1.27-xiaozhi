"""Streaming Qwen3 ASR Realtime via one-api. Independent of the HTTP flash provider."""
import asyncio
import base64
import json
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Optional, Tuple, List

import opuslib_next
import websockets
from core.utils.hardware_billing import websocket_headers

from config.logger import setup_logging
from core.providers.asr.base import ASRProviderBase
from core.providers.asr.dto.dto import InterfaceType
from core.utils.audio_ingress import audio_count, log_audio_stats
from core.utils.speech_emotion import (
    inject_emotion_enabled,
    normalize_emotion,
    preview_text,
)
from core.utils import trace_log as trace
from core.utils.trace_log import pcm_stats
from core.utils.utterance_state import (
    confirm_speech,
    finish_utterance,
    should_start_asr,
    snapshot,
    stop_belongs_to,
)

TAG = __name__
logger = setup_logging()

TEXT_EVENT = "conversation.item.input_audio_transcription.text"
COMPLETED_EVENT = "conversation.item.input_audio_transcription.completed"
FAILED_EVENT = "conversation.item.input_audio_transcription.failed"
MAX_PENDING_FRAMES = 50
MAX_HANDOFF_FRAMES = 50
PREROLL_FRAMES = 10
PCM_FRAME_SAMPLES = 960
ACTIVE_STATES = ("STARTING", "RUNNING")


def _bearer(token: str) -> str:
    token = (token or "").strip()
    if token.startswith("sk-"):
        return token
    return f"sk-{token}"


def session_update_payload(sample_rate: int, language: Optional[str]) -> dict:
    transcription = {}
    if language:
        transcription["language"] = language
    session = {
        "modalities": ["text"],
        "input_audio_format": "pcm",
        "sample_rate": sample_rate,
        "turn_detection": None,
    }
    if transcription:
        session["input_audio_transcription"] = transcription
    return {"event_id": "configure", "type": "session.update", "session": session}


def append_payload(pcm: bytes) -> dict:
    return {
        "type": "input_audio_buffer.append",
        "audio": base64.b64encode(pcm).decode("ascii"),
    }


def _frame_tag(audio: bytes) -> Optional[int]:
    if not audio:
        return None
    return audio[0]


@dataclass
class Recognition:
    epoch: int
    session_id: str
    utterance_id: int = 0
    item_id: str = ""
    state: str = "STARTING"
    ws: object = None
    reader: object = None
    connect_task: object = None
    decoder: object = None
    done: asyncio.Event = field(default_factory=asyncio.Event)
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    pending: deque = field(default_factory=deque)
    audio: deque = field(default_factory=lambda: deque(maxlen=600))
    handoff: deque = field(default_factory=deque)
    handoff_has_voice: bool = False
    preview: str = ""
    transcript: str = ""
    emotion: str = "unknown"
    delivered: bool = False
    resolved: bool = False
    outcome: str = ""
    commit_sent: bool = False
    finish_sent: bool = False
    closed: bool = False
    pending_commit_reason: str = ""
    commit_reason: str = ""
    started: float = field(default_factory=time.monotonic)
    ready_at: float = 0.0
    commit_at: float = 0.0
    pcm_frames: int = 0
    pcm_bytes: int = 0
    pcm_ms: float = 0.0
    sent_seq: int = 0
    received_frames: int = 0
    dropped_handoff: int = 0


class ASRProvider(ASRProviderBase):
    def __init__(self, config: dict, delete_audio_file: bool):
        super().__init__()
        self.interface_type = InterfaceType.STREAM
        self.config = config or {}
        self.delete_audio_file = delete_audio_file
        self.api_key = self.config.get("api_key")
        if not self.api_key:
            raise ValueError("Qwen3 ASR Realtime 需要配置 one-api api_key")
        self.ws_url = (
            self.config.get("ws_url")
            or "ws://127.0.0.1:3001/v1/realtime?model=qwen3-asr-flash-realtime"
        )
        self.model_name = self.config.get("model_name", "qwen3-asr-flash-realtime")
        self.sample_rate = int(self.config.get("sample_rate") or 16000)
        self.language = self.config.get("language") or None
        self.inject_emotion_hint = inject_emotion_enabled(self.config)
        self.ready_timeout = float(self.config.get("ready_timeout", 8))
        self.result_timeout = float(self.config.get("result_timeout", 8))
        self.close_timeout = float(self.config.get("close_timeout", 2))
        self._current = None
        self._start_lock = asyncio.Lock()
        self._deliveries = set()
        self._closed = False
        self._connect = self.config.get("_connect") or self._default_connect
        self._conn = None

    async def _default_connect(self, url: str, headers: dict):
        return await websockets.connect(
            url,
            additional_headers=headers,
            max_size=1024 * 1024,
            ping_interval=20,
            ping_timeout=20,
            close_timeout=2,
            open_timeout=8,
        )

    def _valid(self, conn, ctx: Recognition) -> bool:
        if conn is None or ctx is None:
            return False
        return (
            not self._closed
            and self._current is ctx
            and ctx.epoch == getattr(conn, "listen_epoch", 0)
            and not conn.stop_event.is_set()
        )

    def _ids(self, ctx: Recognition) -> dict:
        return {
            "listen_epoch": getattr(ctx, "epoch", None),
            "utterance_id": getattr(ctx, "utterance_id", None),
            "asr_session_id": getattr(ctx, "session_id", None),
            "state": getattr(ctx, "state", None),
            "item_id": getattr(ctx, "item_id", None) or None,
        }

    def _set_state(self, conn, ctx: Recognition, new_state: str, reason: str):
        old = ctx.state
        if old == new_state:
            return
        ctx.state = new_state
        trace.emit(
            "asr.state",
            conn,
            {
                **self._ids(ctx),
                "from": old,
                "to": new_state,
                "reason": reason,
                "commit_sent": ctx.commit_sent,
                "pending": len(ctx.pending),
                "handoff": len(ctx.handoff),
                "pcm_ms": ctx.pcm_ms,
            },
        )

    def _trace_ws(self, conn, ctx, direction, payload, extra=None):
        event_type = None
        if isinstance(payload, dict):
            event_type = payload.get("type")
        body = {
            "direction": direction,
            "provider": "qwen3_asr_realtime",
            "model": self.model_name,
            "ws_url": self.ws_url,
            **self._ids(ctx),
            "event_type": event_type,
            "message": payload,
        }
        if extra:
            body.update(extra)
        trace.emit("asr.ws", conn, body)

    def _redacted_endpoint(self):
        return {"provider": "qwen3_asr_realtime", "model": self.model_name, "ws_url": self.ws_url}

    def _audio_counts(self, ctx: Recognition) -> dict:
        return {
            "received_frames": ctx.received_frames,
            "pending_frames": len(ctx.pending),
            "handoff_frames": len(ctx.handoff),
            "sent_frames": ctx.sent_seq,
            "pcm_ms": ctx.pcm_ms,
            "dropped_handoff": ctx.dropped_handoff,
            "audio_cache": len(ctx.audio),
        }

    async def open_audio_channels(self, conn):
        self._conn = conn
        conn.inject_emotion_hint = self.inject_emotion_hint
        await super().open_audio_channels(conn)

    async def start_listening(self, conn, reason="new_listen"):
        await self._cleanup(conn, reason=reason)
        conn.asr_audio.clear()

    async def stop_listening(self, conn, reason="device_stop"):
        ctx = self._current
        if ctx and not ctx.commit_sent and ctx.state in ("STARTING", "RUNNING", "COMMITTING"):
            await self._commit(conn, ctx, reason)
        elif ctx:
            await self._cleanup(conn, ctx, reason=reason)

    async def abort_listening(self, conn):
        await self._cleanup(conn, reason="abort")
        conn.asr_audio.clear()

    async def receive_audio(self, conn, audio, audio_have_voice):
        if self._closed or conn.stop_event.is_set():
            return
        if not audio:
            ctx = self._current
            if ctx and stop_belongs_to(conn, ctx.utterance_id):
                await self._commit(
                    conn, ctx, getattr(conn, "utterance_stop_reason", None) or "vad_stop"
                )
            return
        epoch = getattr(conn, "listen_epoch", 0)
        ctx = self._current
        if ctx and ctx.epoch != epoch:
            await self._cleanup(conn, ctx, reason="replaced")
            ctx = None
        if audio_have_voice:
            confirm_speech(conn)
        if ctx is None:
            conn.asr_audio.append(audio)
            conn.asr_audio = conn.asr_audio[-PREROLL_FRAMES:]
            if not should_start_asr(conn, audio_have_voice):
                return
            if getattr(conn, "device_listening", True) is False:
                return
            try:
                await self._start_recognition(conn)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                audio_count(conn, "start_failed")
                logger.bind(tag=TAG).warning(
                    f"[ASR start_failed] epoch={epoch} type={type(exc).__name__}"
                )
                await self._cleanup(conn, reason="failed")
            return
        if not self._valid(conn, ctx):
            audio_count(conn, "drop_stopping")
            return
        ctx.received_frames += 1
        if ctx.state in ACTIVE_STATES:
            ctx.audio.append(audio)
            self._enqueue_bounded(
                conn, ctx.pending, audio, MAX_PENDING_FRAMES, "drop_ready_buffer_full"
            )
            if ctx.state == "RUNNING":
                await self._flush_audio(conn, ctx)
            if stop_belongs_to(conn, ctx.utterance_id):
                await self._commit(
                    conn, ctx, getattr(conn, "utterance_stop_reason", None) or "vad_stop"
                )
            return
        # COMMITTING / FAILED / CLOSED: this frame belongs to the next utterance.
        if ctx.state == "COMMITTING":
            if len(ctx.handoff) >= MAX_HANDOFF_FRAMES:
                ctx.handoff.popleft()
                ctx.dropped_handoff += 1
                audio_count(conn, "drop_handoff_full")
                trace.emit(
                    "asr.handoff_drop",
                    conn,
                    {
                        **self._ids(ctx),
                        "reason": "handoff_full",
                        "limit": MAX_HANDOFF_FRAMES,
                        "dropped": ctx.dropped_handoff,
                    },
                )
            ctx.handoff.append(audio)
            ctx.handoff_has_voice = ctx.handoff_has_voice or bool(audio_have_voice)
            audio_count(conn, "handoff_frames")
            return
        audio_count(conn, "drop_stopping")

    def _enqueue_bounded(self, conn, buf: deque, audio, limit: int, drop_key: str):
        if len(buf) >= limit:
            buf.popleft()
            audio_count(conn, drop_key)
        buf.append(audio)

    async def _start_recognition(self, conn):
        async with self._start_lock:
            if self._closed or self._current or conn.stop_event.is_set():
                return
            if getattr(conn, "device_listening", True) is False:
                return
            self._conn = conn
            uid = int(getattr(conn, "utterance_id", 0) or 0)
            if uid <= 0:
                uid = confirm_speech(conn)
            ctx = Recognition(
                epoch=getattr(conn, "listen_epoch", 0),
                utterance_id=uid,
                session_id=str(getattr(conn, "session_id", "") or uuid.uuid4()),
            )
            ctx.decoder = opuslib_next.Decoder(self.sample_rate, 1)
            preroll = list(conn.asr_audio[-PREROLL_FRAMES:])
            ctx.pending.extend(preroll)
            ctx.audio.extend(preroll)
            ctx.received_frames = len(preroll)
            conn.asr_audio.clear()
            self._current = ctx
            ctx.connect_task = asyncio.create_task(self._connect_upstream(conn, ctx))
            logger.bind(tag=TAG).info(
                f"[ASR task] epoch={ctx.epoch} utterance={ctx.utterance_id} state=STARTING"
            )
            trace.emit(
                "asr.session_start",
                conn,
                {
                    **self._redacted_endpoint(),
                    **self._ids(ctx),
                    "sample_rate": self.sample_rate,
                    "language": self.language,
                    "inject_emotion_hint": self.inject_emotion_hint,
                    "pending_frames": len(ctx.pending),
                    "vad_speech_confirmed": getattr(conn, "vad_speech_confirmed", None),
                    "stop_source": getattr(conn, "utterance_stop_reason", None),
                    "conn_state": snapshot(conn),
                },
            )

    async def _connect_upstream(self, conn, ctx: Recognition):
        headers = websocket_headers(self.ws_url,self.config,{"Authorization": f"Bearer {_bearer(self.api_key)}"})
        try:
            ctx.ws = await asyncio.wait_for(
                self._connect(self.ws_url, headers), timeout=self.ready_timeout
            )
            if not self._valid(conn, ctx):
                await self._resolve(conn, ctx, "replaced")
                await self._finalize(conn, ctx)
                return
            ctx.reader = asyncio.create_task(self._forward_results(conn, ctx))
        except asyncio.CancelledError:
            await self._finalize(conn, ctx)
            raise
        except Exception as exc:
            audio_count(conn, "start_failed")
            logger.bind(tag=TAG).warning(
                f"[ASR connect_failed] epoch={ctx.epoch} type={type(exc).__name__}"
            )
            await self._resolve(conn, ctx, "failed", error=type(exc).__name__)
            await self._finalize(conn, ctx)

    async def _flush_audio(self, conn, ctx: Recognition):
        async with ctx.send_lock:
            await self._flush_locked(conn, ctx)

    async def _flush_locked(self, conn, ctx: Recognition):
        while ctx.pending and self._valid(conn, ctx) and ctx.state == "RUNNING" and not ctx.commit_sent:
            audio = ctx.pending.popleft()
            try:
                t0 = time.perf_counter()
                pcm = (
                    audio
                    if conn.audio_format == "pcm"
                    else ctx.decoder.decode(audio, PCM_FRAME_SAMPLES)
                )
                decode_ms = round((time.perf_counter() - t0) * 1000.0, 3)
                audio_count(conn, "decode_ok")
                stats = pcm_stats(pcm, self.sample_rate, 1)
                ctx.pcm_frames += 1
                ctx.pcm_bytes += stats["bytes"]
                if isinstance(stats.get("duration_ms"), (int, float)):
                    ctx.pcm_ms += stats["duration_ms"]
                if ctx.pcm_frames == 1:
                    trace.mark(conn, "asr_first_pcm")
                if ctx.pcm_frames == 1 or ctx.pcm_frames % 10 == 0:
                    trace.emit(
                        "asr.pcm_frame",
                        conn,
                        {
                            **self._ids(ctx),
                            "seq": ctx.pcm_frames,
                            "opus_bytes": len(audio) if audio else 0,
                            "decode_ms": decode_ms,
                            "pcm": stats,
                            **self._audio_counts(ctx),
                            "cumulative_pcm_ms": ctx.pcm_ms,
                        },
                    )
            except Exception as exc:
                audio_count(conn, "decode_error")
                trace.emit(
                    "asr.decode_error",
                    conn,
                    {
                        **self._ids(ctx),
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "opus_bytes": len(audio) if audio else 0,
                    },
                )
                continue
            if not pcm:
                continue
            try:
                append_msg = append_payload(pcm)
                await asyncio.wait_for(ctx.ws.send(json.dumps(append_msg)), timeout=2)
                ctx.sent_seq += 1
                audio_count(conn, "pcm_sent_frames")
                audio_count(conn, "pcm_sent_bytes", len(pcm))
                self._trace_ws(
                    conn,
                    ctx,
                    "send",
                    append_msg,
                    extra={"sent_seq": ctx.sent_seq, "frame_tag": _frame_tag(audio)},
                )
            except Exception:
                audio_count(conn, "pcm_send_failed")
                self._set_state(conn, ctx, "FAILED", "pcm_send_failed")
                return

    async def _commit(self, conn, ctx: Recognition, reason: str):
        async with ctx.send_lock:
            if ctx.closed or ctx.commit_sent or ctx.resolved:
                trace.emit(
                    "asr.commit_skipped",
                    conn,
                    {
                        **self._ids(ctx),
                        "reason": reason,
                        "commit_sent": ctx.commit_sent,
                        "closed": ctx.closed,
                        "resolved": ctx.resolved,
                    },
                )
                return
            if ctx.state not in ("STARTING", "RUNNING", "COMMITTING"):
                return
            if ctx.state == "STARTING" or (ctx.state == "COMMITTING" and not ctx.commit_sent):
                audio_count(conn, "commit_before_ready")
                ctx.pending_commit_reason = reason
                self._set_state(conn, ctx, "COMMITTING", reason)
                logger.bind(tag=TAG).info(
                    f"[ASR commit_wait_ready] epoch={ctx.epoch} utterance={ctx.utterance_id} reason={reason}"
                )
                trace.mark(conn, "asr_user_end")
                trace.emit(
                    "asr.commit_wait_ready",
                    conn,
                    {
                        **self._ids(ctx),
                        "reason": reason,
                        "pending": len(ctx.pending),
                        "stop_source": reason,
                    },
                )
                return
            await self._flush_locked(conn, ctx)
            if ctx.state == "FAILED":
                return
            ctx.commit_sent = True
            ctx.commit_reason = reason
            ctx.commit_at = time.monotonic()
            self._set_state(conn, ctx, "COMMITTING", reason)
            commit_msg = {"type": "input_audio_buffer.commit"}
            try:
                await asyncio.wait_for(ctx.ws.send(json.dumps(commit_msg)), timeout=2)
            except Exception as exc:
                self._set_state(conn, ctx, "FAILED", "commit_failed")
                trace.emit(
                    "asr.commit_failed",
                    conn,
                    {
                        **self._ids(ctx),
                        "reason": reason,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                )
                return
            logger.bind(tag=TAG).info(
                f"[ASR commit] epoch={ctx.epoch} utterance={ctx.utterance_id} reason={reason}"
            )
            trace.mark(conn, "asr_user_end")
            self._trace_ws(
                conn,
                ctx,
                "send",
                commit_msg,
                extra={
                    "commit_reason": reason,
                    "stop_source": reason,
                    "pending_after_flush": len(ctx.pending),
                    "cumulative_pcm_ms": ctx.pcm_ms,
                    "latency_from_first_pcm_ms": trace.latency_ms(conn, "asr_first_pcm"),
                    "latency_from_vad_end_ms": trace.latency_ms(conn, "vad_end"),
                    **self._audio_counts(ctx),
                },
            )

    async def _finish(self, conn, ctx: Recognition):
        async with ctx.send_lock:
            if ctx.closed or ctx.finish_sent or ctx.ws is None:
                return
            ctx.finish_sent = True
            finish_msg = {"type": "session.finish"}
            try:
                await asyncio.wait_for(ctx.ws.send(json.dumps(finish_msg)), timeout=2)
                self._trace_ws(conn, ctx, "send", finish_msg)
            except Exception as exc:
                self._set_state(conn, ctx, "FAILED", "finish_failed")
                trace.emit(
                    "asr.finish_failed",
                    conn,
                    {
                        **self._ids(ctx),
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                )

    def _deliver(self, conn, ctx: Recognition):
        transcript = (ctx.transcript or "").strip()
        if not transcript:
            audio_count(conn, "empty_transcript")
            trace.emit(
                "asr.empty_transcript",
                conn,
                {
                    **self._ids(ctx),
                    "emotion_raw": ctx.emotion,
                    "emotion_normalized": normalize_emotion(ctx.emotion),
                    **self._audio_counts(ctx),
                },
            )
            return False
        text = transcript
        audio = list(ctx.audio)
        result = {
            "transcript": text,
            "emotion": normalize_emotion(ctx.emotion),
            "item_id": ctx.item_id,
            "utterance_id": ctx.utterance_id,
            "listen_epoch": ctx.epoch,
            "raw_emotion": ctx.emotion,
        }
        trace.mark(conn, "asr_final")
        trace.emit(
            "asr.final",
            conn,
            {
                **self._ids(ctx),
                "result": result,
                "language": getattr(ctx, "language", None),
                "usage": getattr(ctx, "usage", None),
                "usage_missing": getattr(ctx, "usage", None) is None,
                "cumulative_pcm_ms": ctx.pcm_ms,
                "latency_first_pcm_ms": trace.latency_ms(conn, "asr_first_pcm"),
                "latency_first_partial_ms": trace.latency_ms(conn, "asr_first_partial"),
                "latency_user_end_ms": trace.latency_ms(conn, "asr_user_end"),
            },
        )

        async def dispatch():
            if ctx.epoch != getattr(conn, "listen_epoch", 0) or conn.stop_event.is_set():
                trace.emit(
                    "asr.final_rejected",
                    conn,
                    {
                        **self._ids(ctx),
                        "reason": "stale_epoch_or_stopped",
                        "current_epoch": getattr(conn, "listen_epoch", 0),
                    },
                )
                return
            conn.speech_turn_result = result
            await self.handle_voice_stop(
                conn, audio, final_text=text, listen_epoch=ctx.epoch
            )

        task = asyncio.create_task(dispatch())
        self._deliveries.add(task)

        def finished(task):
            self._deliveries.discard(task)
            if not task.cancelled() and task.exception():
                logger.bind(tag=TAG).warning(
                    f"ASR delivery failed: {type(task.exception()).__name__}"
                )

        task.add_done_callback(finished)
        return True

    async def _resolve(self, conn, ctx: Recognition, outcome: str, error=None):
        if ctx.resolved:
            return
        ctx.resolved = True
        ctx.outcome = outcome
        delivered = False
        if outcome == "final":
            delivered = bool(self._deliver(conn, ctx))
            ctx.delivered = delivered
            if not delivered:
                ctx.outcome = "empty"
                outcome = "empty"
        if outcome in ("cancel", "replaced", "disconnect"):
            ctx.handoff.clear()
            ctx.handoff_has_voice = False
        change = finish_utterance(conn, ctx.utterance_id)
        trace.emit(
            "asr.turn_end",
            conn,
            {
                **self._ids(ctx),
                "outcome": outcome,
                "delivered": delivered,
                "error": error,
                "state_change": change,
                **self._audio_counts(ctx),
            },
        )

    async def _forward_results(self, conn, ctx: Recognition):
        try:
            while self._valid(conn, ctx) and ctx.state != "FAILED":
                now = time.monotonic()
                waiting_ready = ctx.state == "STARTING" or (
                    ctx.state == "COMMITTING" and not ctx.commit_sent
                )
                if waiting_ready and now - ctx.started > self.ready_timeout:
                    audio_count(conn, "ready_timeout")
                    await self._resolve(conn, ctx, "timeout")
                    break
                if ctx.state == "COMMITTING" and ctx.commit_sent:
                    started = ctx.commit_at or ctx.started
                    if now - started > self.result_timeout:
                        audio_count(conn, "result_timeout")
                        await self._resolve(conn, ctx, "timeout")
                        break
                try:
                    raw = await asyncio.wait_for(ctx.ws.recv(), timeout=0.2)
                except asyncio.TimeoutError:
                    continue
                if isinstance(raw, bytes):
                    trace.emit(
                        "asr.ws",
                        conn,
                        {
                            "direction": "recv",
                            "binary": True,
                            "bytes": len(raw),
                            "omitted": True,
                            **self._ids(ctx),
                        },
                    )
                    continue
                msg = json.loads(raw)
                event_type = msg.get("type")
                self._trace_ws(conn, ctx, "recv", msg)
                if event_type == "error":
                    logger.bind(tag=TAG).warning(
                        f"[ASR error] epoch={ctx.epoch} code={((msg.get('error') or {}).get('code'))}"
                    )
                    await self._resolve(conn, ctx, "failed")
                    break
                if event_type == "session.created":
                    update = session_update_payload(self.sample_rate, self.language)
                    await asyncio.wait_for(ctx.ws.send(json.dumps(update)), timeout=2)
                    self._trace_ws(conn, ctx, "send", update)
                    continue
                if event_type == "session.updated" and ctx.state in (
                    "STARTING",
                    "COMMITTING",
                ):
                    waiting_commit = ctx.state == "COMMITTING" or bool(ctx.pending_commit_reason)
                    ctx.ready_at = time.monotonic()
                    self._set_state(conn, ctx, "RUNNING", "session.updated")
                    await self._flush_audio(conn, ctx)
                    if waiting_commit or stop_belongs_to(conn, ctx.utterance_id):
                        await self._commit(
                            conn,
                            ctx,
                            ctx.pending_commit_reason
                            or getattr(conn, "utterance_stop_reason", None)
                            or "ready_then_commit",
                        )
                    continue
                if event_type == TEXT_EVENT:
                    if msg.get("item_id"):
                        ctx.item_id = msg["item_id"]
                    ctx.preview = preview_text(msg.get("text"), msg.get("stash"))
                    if msg.get("emotion"):
                        ctx.emotion = msg.get("emotion")
                    if not getattr(ctx, "first_partial", False):
                        ctx.first_partial = True
                        trace.mark(conn, "asr_first_partial")
                    trace.emit(
                        "asr.partial",
                        conn,
                        {
                            "message": msg,
                            "preview": ctx.preview,
                            "emotion_raw": ctx.emotion,
                            "emotion_normalized": normalize_emotion(ctx.emotion),
                            **self._ids(ctx),
                            "latency_from_first_pcm_ms": trace.latency_ms(conn, "asr_first_pcm"),
                        },
                    )
                    continue
                if event_type == COMPLETED_EVENT:
                    if ctx.resolved:
                        trace.emit(
                            "asr.duplicate_final",
                            conn,
                            {"message": msg, **self._ids(ctx), "reject_reason": "already_resolved"},
                        )
                        continue
                    if msg.get("item_id") and ctx.item_id and msg["item_id"] != ctx.item_id:
                        trace.emit(
                            "asr.late_or_mismatch_final",
                            conn,
                            {
                                "message": msg,
                                "current_item_id": ctx.item_id,
                                "incoming_item_id": msg.get("item_id"),
                                "reject_reason": "item_mismatch",
                            },
                        )
                        continue
                    if not self._valid(conn, ctx):
                        trace.emit(
                            "asr.final_rejected",
                            conn,
                            {**self._ids(ctx), "reason": "stale_context", "message": msg},
                        )
                        continue
                    ctx.item_id = msg.get("item_id") or ctx.item_id
                    ctx.transcript = msg.get("transcript") or ""
                    ctx.emotion = msg.get("emotion") or ctx.emotion
                    ctx.language = msg.get("language")
                    ctx.usage = msg.get("usage")
                    await self._resolve(conn, ctx, "final")
                    await self._finish(conn, ctx)
                    break
                if event_type == FAILED_EVENT:
                    audio_count(conn, "asr_failed")
                    await self._resolve(conn, ctx, "failed")
                    break
                if event_type == "session.finished":
                    break
        except asyncio.CancelledError:
            await self._resolve(conn, ctx, "cancel")
            raise
        except Exception as exc:
            logger.bind(tag=TAG).warning(
                f"[ASR reader] epoch={ctx.epoch} type={type(exc).__name__}"
            )
            await self._resolve(conn, ctx, "failed", error=type(exc).__name__)
        finally:
            await self._finalize(conn, ctx)

    async def _finalize(self, conn, ctx: Recognition):
        if ctx.closed:
            return
        ctx.closed = True
        self._set_state(conn, ctx, "CLOSED", ctx.outcome or "finalize")
        if not ctx.resolved:
            await self._resolve(conn, ctx, "cancel")
        handoff = list(ctx.handoff)
        handoff_has_voice = ctx.handoff_has_voice
        try:
            if ctx.ws:
                await asyncio.wait_for(ctx.ws.close(), timeout=self.close_timeout)
        except Exception:
            pass
        finally:
            ctx.pending.clear()
            ctx.audio.clear()
            ctx.handoff.clear()
            restart = False
            if self._current is ctx:
                self._current = None
                if conn and ctx.epoch == getattr(conn, "listen_epoch", 0):
                    conn.asr_audio = handoff[-PREROLL_FRAMES:]
                    log_audio_stats(conn, "asr_closed")
                    restart = (
                        handoff_has_voice
                        and not self._closed
                        and not conn.stop_event.is_set()
                        and getattr(conn, "device_listening", True) is not False
                    )
            ctx.done.set()
        if restart:
            try:
                confirm_speech(conn)
                await self._start_recognition(conn)
            except asyncio.CancelledError:
                raise
            except Exception:
                await self._cleanup(conn, reason="failed")

    async def _cleanup(self, conn=None, ctx=None, reason="cleanup"):
        ctx = ctx or self._current
        if not ctx or ctx.closed:
            return
        outcome = {
            "abort": "cancel",
            "new_listen": "replaced",
            "replaced": "replaced",
            "disconnect": "disconnect",
            "wakeup_detect": "replaced",
        }.get(reason, "cancel")
        await self._resolve(conn, ctx, outcome)
        connect_task = ctx.connect_task
        reader = ctx.reader
        try:
            for task in (connect_task, reader):
                if task and task is not asyncio.current_task() and not task.done():
                    task.cancel()
            wait = [
                t
                for t in (connect_task, reader)
                if t and t is not asyncio.current_task()
            ]
            if wait:
                await asyncio.gather(*wait, return_exceptions=True)
        finally:
            await self._finalize(conn, ctx)

    async def speech_to_text(
        self, opus_data: List[bytes], session_id: str, audio_format="opus"
    ) -> Tuple[Optional[str], Optional[str]]:
        return "", None

    async def close(self):
        self._closed = True
        await self._cleanup(self._conn, reason="disconnect")
        pending = [t for t in self._deliveries if t is not asyncio.current_task()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
