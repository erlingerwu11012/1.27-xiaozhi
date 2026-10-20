"""Streaming Qwen Audio 3.0 TTS Plus via the Bailian native gateway.

Uses an instance-level WebSocket client. It does not set global DashScope
endpoint or api_key, so it cannot bypass the gateway or race other providers.
"""
import asyncio
import json
import os
import queue
import time
import traceback
import uuid
import wave
import websockets
from core.utils.hardware_billing import websocket_headers

from config.logger import setup_logging
from core.providers.tts.base import TTSProviderBase
from core.providers.tts.dto.dto import SentenceType, ContentType, InterfaceType
from core.utils import opus_encoder_utils
from core.utils.tts import MarkdownCleaner
from core.utils import textUtils
from core.utils import trace_log as trace
from core.utils.trace_log import pcm_stats
from core.utils.tts_stream import stream_context
from core.providers.tts.official import (
    IncrementalCompiler,
    build_continue_task,
    build_finish_task,
    build_run_task,
    freeze_snapshot,
    is_official_enhanced,
    validate_snapshot,
)
from core.providers.tts.official.compiler import caption_from

TAG = __name__
logger = setup_logging()

VERIFIED_VOICES = ("longanlingxi", "longanqian")
DEVICE_SAMPLE_RATE = 16000
OPUS_FRAME_MS = 60


class QwenTtsExpired(Exception):
    """This synthesis attempt is no longer the live session (abort/replace/disconnect)."""

    def __init__(self, reason="expired"):
        self.reason = reason
        super().__init__(reason)


class QwenTtsTimeout(Exception):
    """Upstream task-started did not arrive in time."""

    def __init__(self, reason="task_started_timeout"):
        self.reason = reason
        super().__init__(reason)


class QwenTtsStartFailed(Exception):
    """Connect or protocol start failed; caller must not treat as started."""

    def __init__(self, reason="start_failed"):
        self.reason = reason
        super().__init__(reason)


def _bearer(token: str) -> str:
    """3011 only accepts one-api tokens as Bearer sk-... (same as ASR)."""
    token = (token or "").strip()
    if token.startswith("sk-"):
        return token
    return f"sk-{token}"


def to_uuid(value: str) -> str:
    raw = (value or "").replace("-", "")
    if len(raw) == 32:
        return f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:]}"
    return str(uuid.uuid4())


def resample_pcm16_mono(pcm: bytes, src_rate: int, dst_rate: int, carry: bytes = b""):
    """Stateful linear resample; keep leftover source samples in carry."""
    if not pcm and not carry:
        return b"", b""
    if src_rate == dst_rate:
        return (carry + pcm), b""
    import numpy as np

    src = np.frombuffer(carry + pcm, dtype=np.int16)
    if len(src) == 0:
        return b"", b""
    # Keep the last sample as carry so chunk boundaries stay continuous.
    keep = src[-1:]
    usable = src if len(src) == 1 else src[:-1]
    n_dst = int(round(len(usable) * dst_rate / src_rate))
    if n_dst <= 0:
        return b"", keep.tobytes()
    x_old = np.linspace(0.0, 1.0, num=len(usable), endpoint=False)
    x_new = np.linspace(0.0, 1.0, num=n_dst, endpoint=False)
    dst = np.interp(x_new, x_old, usable.astype(np.float32))
    return np.clip(dst, -32768, 32767).astype(np.int16).tobytes(), keep.tobytes()


class QwenTtsSession:
    """One synthesis attempt: own socket, reader, events, and abort epoch."""

    def __init__(self, conn, sentence_id, abort_epoch, task_id):
        self.conn = conn
        self.conn_id = id(conn) if conn is not None else None
        self.device_id = getattr(conn, "device_id", None)
        self.session_id = getattr(conn, "session_id", None)
        self.sentence_id = sentence_id
        self.abort_epoch = int(abort_epoch or 0)
        self.task_id = task_id
        self.ws = None
        self.monitor_task = None
        self.started = asyncio.Event()
        self.finished = asyncio.Event()
        self.cancel_event = asyncio.Event()
        self.cancelled = False
        self.closed = False
        self.create_t0 = time.perf_counter()
        self.ready_ms = None
        self.first_audio_ms = None
        self.audio_frames = 0
        self._text_seq = 0
        self._pcm_seq = 0
        self._opus_seq = 0
        self._pcm_ms = 0.0
        self._resample_carry = b""
        self.opus_encoder = opus_encoder_utils.OpusEncoderUtils(
            sample_rate=DEVICE_SAMPLE_RATE, channels=1, frame_size_ms=OPUS_FRAME_MS
        )
        self.emit_device_first = True
        self.emit_device_last = True
        self.caption_text = None
        self.enable_ssml = False
        self.snapshot = None

    def owner_token(self):
        return (self.session_id, self.sentence_id, self.abort_epoch)


class TTSProvider(TTSProviderBase):
    def __init__(self, config, delete_audio_file):
        super().__init__(config, delete_audio_file)
        if config.get("official_tts_blocked") or config.get("official_billing") == "token_resolve_failed":
            raise ValueError(
                "official TTS refused: customer token resolve failed; shared production key is not used"
            )
        self.interface_type = InterfaceType.DUAL_STREAM
        self.api_key = config.get("api_key")
        if not self.api_key:
            raise ValueError("api_key is required for Qwen Audio TTS Plus")
        self.ws_url = config.get("ws_url") or (
            "ws://127.0.0.1:3011/bailian/api-ws/v1/inference"
        )
        if os.environ.get("BAILIAN_ISOLATION") == "1" and not config.get("_connect"):
            iso_url = (config.get("ws_url") or "").strip()
            if not iso_url or ":3011/" in iso_url or iso_url.rstrip("/").endswith(":3011"):
                raise ValueError("isolation_ws_url_must_not_use_production_3011")
            self.ws_url = iso_url
        self.model = config.get("model", "qwen-audio-3.0-tts-plus")
        self.voice = config.get("private_voice") or config.get("voice") or "longanlingxi"
        self.format = config.get("format", "pcm")
        self.sample_rate = int(config.get("sample_rate") or DEVICE_SAMPLE_RATE)
        self.volume = int(config.get("volume") or 50)
        self.rate = float(config.get("rate") or 1.0)
        self.pitch = float(config.get("pitch") or 1.0)
        self.header = {"Authorization": f"Bearer {_bearer(self.api_key)}"}
        self.ws = None
        self._monitor_task = None
        self._started = asyncio.Event()
        self._finished = asyncio.Event()
        self.task_id = None
        self.session_epoch = 0
        self._current = None
        self.last_cancel_session = None
        self.opus_encoder = opus_encoder_utils.OpusEncoderUtils(
            sample_rate=DEVICE_SAMPLE_RATE, channels=1, frame_size_ms=OPUS_FRAME_MS
        )
        self._resample_carry = b""
        self._connect = config.get("_connect") or self._default_connect
        self.official_enhanced = bool(config.get("official_enhanced"))
        self.official_model_id = config.get("official_model_id")
        self._config_snapshot = dict(config)
        self._turn_snapshot = None
        self._compiler = None
        self._turn_first_sent = False
        self._unit_busy = False
        self._customer_token = None
        if self.official_enhanced:
            try:
                self.tts_text_queue.maxsize = 32
            except Exception:
                pass

    def set_aimi_device_context(self, context):
        """Bind per-customer one-api token when manager injects it; never log the secret."""
        token = (context or {}).get("tts_api_key") or (context or {}).get("api_key")
        if token:
            self._customer_token = token
            self.header = {"Authorization": f"Bearer {_bearer(token)}"}

    def _auth_header(self):
        token = self._customer_token or self.api_key
        return websocket_headers(self.ws_url,self._config_snapshot,{"Authorization": f"Bearer {_bearer(token)}"})

    def _official_on(self):
        return is_official_enhanced(
            {
                "official_enhanced": self.official_enhanced,
                "official_model_id": self.official_model_id,
            }
        )

    async def _default_connect(self, url: str, headers: dict):
        try:
            return await websockets.connect(
                url,
                additional_headers=headers,
                ping_interval=30,
                ping_timeout=10,
                close_timeout=10,
                max_size=10 * 1024 * 1024,
            )
        except Exception as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            logger.bind(tag=TAG).error(
                f"TTS网关握手失败 type={type(exc).__name__} status={status} host=127.0.0.1:3011"
            )
            trace.emit(
                "tts.connect_error",
                getattr(self, "conn", None),
                {
                    "error_type": type(exc).__name__,
                    "status": status,
                    "ws_url": url,
                },
            )
            raise

    def _tts_note(self, sess, event, reason=None, extra=None):
        conn = self.conn
        body = {
            "event": event,
            "reason": reason,
            "device_id": getattr(sess, "device_id", None) or getattr(conn, "device_id", None),
            "session_id": getattr(sess, "session_id", None) or getattr(conn, "session_id", None),
            "sentence_id": getattr(sess, "sentence_id", None),
            "request_epoch": getattr(sess, "abort_epoch", None),
            "current_abort_epoch": getattr(conn, "tts_abort_epoch", None) if conn else None,
            "task_id": getattr(sess, "task_id", None),
            "is_current": self._current is sess,
        }
        if extra:
            body.update(extra)
        if conn is not None and hasattr(conn, "logger"):
            try:
                conn.logger.bind(tag=TAG).info(
                    f"[tts_session] event={event} reason={reason} "
                    f"device_id={body.get('device_id')} session_id={body.get('session_id')} "
                    f"sentence_id={body.get('sentence_id')} "
                    f"request_epoch={body.get('request_epoch')} "
                    f"current_epoch={body.get('current_abort_epoch')} "
                    f"task_id={body.get('task_id')} is_current={body.get('is_current')}"
                )
            except Exception:
                pass
        trace.emit("tts.session", conn, body)

    def _can_start(self, requested_epoch) -> bool:
        conn = self.conn
        if conn is None:
            return False
        stop = getattr(conn, "stop_event", None)
        if stop is not None and callable(getattr(stop, "is_set", None)) and stop.is_set():
            return False
        return int(getattr(conn, "tts_abort_epoch", 0) or 0) == int(requested_epoch or 0)

    def _session_live(self, sess) -> bool:
        if sess is None or sess.cancelled or sess.closed:
            return False
        conn = self.conn
        if conn is None:
            return False
        if sess.conn_id is not None and id(conn) != sess.conn_id:
            return False
        stop = getattr(conn, "stop_event", None)
        if stop is not None and callable(getattr(stop, "is_set", None)) and stop.is_set():
            return False
        conn_sid = getattr(conn, "session_id", None)
        if sess.session_id and conn_sid and sess.session_id != conn_sid:
            return False
        return int(getattr(conn, "tts_abort_epoch", 0) or 0) == int(sess.abort_epoch)

    def _alive(self) -> bool:
        """Whether the current synthesis session is still the live one."""
        return self._session_live(self._current)

    def _message_abort_epoch(self, message):
        epoch = getattr(message, "abort_epoch", None)
        if epoch is not None:
            return int(epoch)
        token = getattr(message, "stream_token", None)
        if isinstance(token, tuple) and len(token) >= 3:
            try:
                return int(token[2])
            except (TypeError, ValueError):
                return None
        return None

    def _adopt(self, sess):
        self._current = sess
        self.session_epoch = sess.abort_epoch
        self.task_id = sess.task_id
        self.ws = sess.ws
        self._started = sess.started
        self._finished = sess.finished
        self._monitor_task = sess.monitor_task
        self.opus_encoder = sess.opus_encoder

    def _detach_if_current(self, sess, reason=None):
        if self._current is sess:
            self._current = None
            self.ws = None
            self.task_id = None
            self._monitor_task = None
            self._started = asyncio.Event()
            self._finished = asyncio.Event()
            return False
        self._tts_note(sess, "cleanup_skip", reason=reason or "no_longer_current")
        return True

    def _trace_ws(self, direction, payload, extra=None, sess=None):
        header = (payload or {}).get("header") if isinstance(payload, dict) else None
        active = sess or self._current
        body = {
            "direction": direction,
            "provider": "qwen_audio_tts_plus",
            "model": self.model,
            "voice": self.voice,
            "ws_url": self.ws_url,
            "format": self.format,
            "sample_rate": self.sample_rate,
            "task_id": getattr(active, "task_id", None) if active is not None else self.task_id,
            "event": (header or {}).get("event") if header else None,
            "action": (header or {}).get("action") if header else None,
            "message": payload,
        }
        if extra:
            body.update(extra)
        trace.emit("tts.ws", self.conn, body)

    def handle_opus(self, opus_data: bytes):
        sess = self._current
        if sess is not None:
            sess._opus_seq = getattr(sess, "_opus_seq", 0) + 1
            seq = sess._opus_seq
        else:
            seq = getattr(self, "_opus_seq", 0) + 1
            self._opus_seq = seq
        if seq == 1:
            trace.mark(self.conn, "tts_first_opus")
        if seq == 1 or seq % 10 == 0:
            trace.emit(
                "tts.opus_encode",
                self.conn,
                {
                    "seq": seq,
                    "opus_bytes": len(opus_data) if opus_data else 0,
                    "sample_rate": DEVICE_SAMPLE_RATE,
                    "channels": 1,
                    "frame_size_ms": OPUS_FRAME_MS,
                    "bitrate": getattr(self.opus_encoder, "bitrate", "unknown"),
                    "complexity": getattr(self.opus_encoder, "complexity", "unknown"),
                    "duration_ms": OPUS_FRAME_MS,
                },
            )
        token = None
        if sess is not None:
            token = stream_context.set(sess.owner_token())
        try:
            super().handle_opus(opus_data)
        finally:
            if token is not None:
                stream_context.reset(token)

    def tts_text_priority_thread(self):
        while not self.conn.stop_event.is_set():
            try:
                message = self.tts_text_queue.get(timeout=1)
                hook = getattr(self, "_after_dequeue_hook", None)
                if callable(hook):
                    hook(message)
                from core.utils.device_outbound import tts_message_still_valid

                if not tts_message_still_valid(self.conn, message):
                    continue
                if self._official_on():
                    self._handle_official_message(message)
                    continue
                self._handle_legacy_message(message)
            except queue.Empty:
                continue
            except Exception as exc:
                logger.bind(tag=TAG).error(
                    f"处理TTS文本失败: {type(exc).__name__}, {traceback.format_exc()}"
                )
                continue

    def _handle_legacy_message(self, message):
        msg_epoch = self._message_abort_epoch(message)
        current_epoch = int(getattr(self.conn, "tts_abort_epoch", 0) or 0)
        if message.sentence_type == SentenceType.FIRST:
            if msg_epoch is not None and msg_epoch != current_epoch:
                self._tts_note(
                    self._current or QwenTtsSession(
                        self.conn, getattr(message, "sentence_id", None), msg_epoch, None
                    ),
                    "discard",
                    reason="stale_first_epoch",
                    extra={"message_epoch": msg_epoch},
                )
                return
            if self.conn.client_abort and (
                msg_epoch is None or msg_epoch != current_epoch
            ):
                return
            self.conn.client_abort = False
            # Rearm once per device reply, not per upstream synthesis session.
            self.tts_audio_first_sentence = True
            try:
                if not getattr(self.conn, "sentence_id", None):
                    self.conn.sentence_id = uuid.uuid4().hex
                sentence_id = getattr(message, "sentence_id", None) or self.conn.sentence_id
                future = asyncio.run_coroutine_threadsafe(
                    self.start_session(
                        sentence_id,
                        abort_epoch=msg_epoch if msg_epoch is not None else current_epoch,
                    ),
                    loop=self.conn.loop,
                )
                future.result()
                self.before_stop_play_files.clear()
            except QwenTtsExpired:
                return
            except asyncio.CancelledError:
                return
            except Exception as exc:
                if type(exc).__name__ == "CancelledError":
                    return
                logger.bind(tag=TAG).error(
                    f"启动TTS会话失败: {type(exc).__name__}"
                )
                return
        elif self.conn.client_abort:
            return
        elif msg_epoch is not None and msg_epoch != current_epoch:
            return
        elif ContentType.TEXT == message.content_type:
            if message.content_detail:
                try:
                    future = asyncio.run_coroutine_threadsafe(
                        self.text_to_speak(message.content_detail, None),
                        loop=self.conn.loop,
                    )
                    future.result()
                except QwenTtsExpired:
                    return
                except asyncio.CancelledError:
                    return
                except Exception as exc:
                    if type(exc).__name__ == "CancelledError":
                        return
                    logger.bind(tag=TAG).error(
                        f"发送TTS文本失败: {type(exc).__name__}"
                    )
                    return
        elif ContentType.FILE == message.content_type:
            if message.content_file and os.path.exists(message.content_file):
                self._process_audio_file_stream(
                    message.content_file,
                    callback=lambda audio_data: self.handle_audio_file(
                        audio_data, message.content_detail
                    ),
                )
        if message.sentence_type == SentenceType.LAST:
            try:
                sess = self._current
                task_id = sess.task_id if sess is not None else self.task_id
                if msg_epoch is not None and sess is not None and msg_epoch != sess.abort_epoch:
                    return
                future = asyncio.run_coroutine_threadsafe(
                    self.finish_session(task_id),
                    loop=self.conn.loop,
                )
                future.result()
            except (QwenTtsExpired, asyncio.CancelledError):
                return
            except Exception as exc:
                if type(exc).__name__ == "CancelledError":
                    return
                logger.bind(tag=TAG).error(
                    f"结束TTS会话失败: {type(exc).__name__}"
                )

    def _handle_official_message(self, message):
        msg_epoch = self._message_abort_epoch(message)
        current_epoch = int(getattr(self.conn, "tts_abort_epoch", 0) or 0)
        if msg_epoch is not None and msg_epoch != current_epoch:
            return
        if message.sentence_type == SentenceType.FIRST:
            if self.conn.client_abort and (
                msg_epoch is None or msg_epoch != current_epoch
            ):
                return
            self.conn.client_abort = False
            self._turn_snapshot = freeze_snapshot(self._config_snapshot)
            ok, reason = validate_snapshot(self._turn_snapshot)
            if not ok:
                logger.bind(tag=TAG).error(f"官方TTS配置拒绝: {reason}")
                return
            # A previous reply consumed this flag. FIRST opens a fresh device
            # turn; subsequent sentence units must keep the same start/stop.
            self.tts_audio_first_sentence = True
            self._compiler = IncrementalCompiler()
            self._turn_first_sent = False
            self.before_stop_play_files.clear()
            if not getattr(self.conn, "sentence_id", None):
                self.conn.sentence_id = uuid.uuid4().hex
            return
        if self.conn.client_abort:
            return
        if ContentType.TEXT == message.content_type and message.content_detail:
            compiler = self._compiler or IncrementalCompiler()
            self._compiler = compiler
            units = compiler.feed(message.content_detail)
            for unit in units:
                self._run_official_unit(unit, msg_epoch, current_epoch, last=False)
        elif ContentType.FILE == message.content_type:
            if message.content_file and os.path.exists(message.content_file):
                self._process_audio_file_stream(
                    message.content_file,
                    callback=lambda audio_data: self.handle_audio_file(
                        audio_data, message.content_detail
                    ),
                )
        if message.sentence_type == SentenceType.LAST:
            compiler = self._compiler or IncrementalCompiler()
            units = compiler.flush()
            for i, unit in enumerate(units):
                self._run_official_unit(
                    unit, msg_epoch, current_epoch, last=(i == len(units) - 1)
                )
            if not units:
                self._emit_device_last_only()
            self._compiler = IncrementalCompiler()
            self._turn_first_sent = False

    def _run_official_unit(self, unit, msg_epoch, current_epoch, last):
        if unit is None:
            return
        if unit.rejected:
            logger.bind(tag=TAG).warning(
                f"官方TTS单元拒绝: {unit.reject_reason}"
            )
            if last:
                self._emit_device_last_only()
            return
        if not unit.synthesis_text:
            return
        emit_first = not self._turn_first_sent
        future = asyncio.run_coroutine_threadsafe(
            self._synthesize_official_unit(
                unit,
                abort_epoch=msg_epoch if msg_epoch is not None else current_epoch,
                emit_first=emit_first,
                emit_last=last,
            ),
            loop=self.conn.loop,
        )
        future.result()
        self._turn_first_sent = True

    def _emit_device_last_only(self):
        sess = self._current
        try:
            self._process_before_stop_play_files()
        except Exception:
            if sess is not None:
                self._put_audio(sess, (SentenceType.LAST, [], None))

    async def _synthesize_official_unit(self, unit, abort_epoch, emit_first, emit_last):
        sentence_id = getattr(self.conn, "sentence_id", None) or uuid.uuid4().hex
        snapshot = dict(self._turn_snapshot or freeze_snapshot(self._config_snapshot))
        ok, reason = validate_snapshot(snapshot)
        if not ok:
            raise QwenTtsStartFailed(reason)
        sess = await self.start_session(
            sentence_id,
            abort_epoch=abort_epoch,
            emit_first=emit_first,
            emit_last=emit_last,
            enable_ssml=unit.enable_ssml,
            snapshot=snapshot,
            caption_text=unit.caption_text,
        )
        if sess is None:
            return
        await self.text_to_speak(unit.synthesis_text, None, official=True)
        await self.finish_session(sess.task_id, emit_last=emit_last)

    async def start_session(
        self,
        session_id,
        abort_epoch=None,
        emit_first=True,
        emit_last=True,
        enable_ssml=False,
        snapshot=None,
        caption_text=None,
    ):
        requested_epoch = (
            int(abort_epoch)
            if abort_epoch is not None
            else int(getattr(self.conn, "tts_abort_epoch", 0) or 0)
        )
        if not self._can_start(requested_epoch):
            raise QwenTtsExpired("start_epoch_mismatch")

        old = self._current
        if old is not None:
            old.cancelled = True
            await self._close_session(old, reason="replaced")

        if not self._can_start(requested_epoch):
            raise QwenTtsExpired("start_epoch_mismatch_after_close")

        sentence_id = session_id or getattr(self.conn, "sentence_id", None) or uuid.uuid4().hex
        sess = QwenTtsSession(
            self.conn,
            sentence_id,
            requested_epoch,
            to_uuid(sentence_id),
        )
        sess.emit_device_first = emit_first
        sess.emit_device_last = emit_last
        sess.enable_ssml = bool(enable_ssml)
        sess.snapshot = snapshot
        sess.caption_text = caption_text
        self._adopt(sess)
        self._tts_note(sess, "create", reason="start_session")
        try:
            ws = await self._connect(self.ws_url, self._auth_header())
            if self._current is not sess or not self._session_live(sess):
                try:
                    await ws.close()
                except Exception:
                    pass
                self._tts_note(sess, "discard", reason="stale_after_connect")
                sess.closed = True
                self._detach_if_current(sess, reason="stale_after_connect")
                raise QwenTtsExpired("stale_after_connect")
            sess.ws = ws
            if self._current is sess:
                self.ws = ws
            sess.monitor_task = asyncio.create_task(self._start_monitor_tts_response(sess))
            if self._current is sess:
                self._monitor_task = sess.monitor_task
            snapshot = sess.snapshot or self._turn_snapshot or freeze_snapshot(self._config_snapshot)
            if self._official_on() or sess.enable_ssml or snapshot.get("instruction") or snapshot.get("hot_fix"):
                run_task_message = build_run_task(
                    sess.task_id, snapshot, enable_ssml=bool(sess.enable_ssml)
                )
            else:
                run_task_message = {
                    "header": {
                        "action": "run-task",
                        "task_id": sess.task_id,
                        "streaming": "duplex",
                    },
                    "payload": {
                        "task_group": "audio",
                        "task": "tts",
                        "function": "SpeechSynthesizer",
                        "model": self.model,
                        "parameters": {
                            "text_type": "PlainText",
                            "voice": self.voice,
                            "format": self.format,
                            "sample_rate": self.sample_rate,
                            "volume": self.volume,
                            "rate": self.rate,
                            "pitch": self.pitch,
                        },
                        "input": {},
                    },
                }
            await ws.send(json.dumps(run_task_message))
            sess._text_seq = 0
            sess._pcm_seq = 0
            sess._opus_seq = 0
            sess._pcm_ms = 0.0
            self._trace_ws("send", run_task_message, sess=sess)
            await self._wait_started(sess, timeout=10)
            if self._current is not sess or not self._session_live(sess):
                await self._close_session(sess, reason="stale_after_started")
                raise QwenTtsExpired("stale_after_started")
            sess.ready_ms = round((time.perf_counter() - sess.create_t0) * 1000.0, 3)
            logger.bind(tag=TAG).info("TTS会话已就绪")
            self._tts_note(
                sess,
                "ready",
                extra={"ready_ms": sess.ready_ms},
            )
            trace.emit(
                "tts.session_ready",
                self.conn,
                {
                    "provider": "qwen_audio_tts_plus",
                    "model": self.model,
                    "voice": self.voice,
                    "format": self.format,
                    "sample_rate": self.sample_rate,
                    "task_id": sess.task_id,
                    "run_task": run_task_message,
                    "abort_epoch": sess.abort_epoch,
                    "ready_ms": sess.ready_ms,
                },
            )
            return sess
        except QwenTtsExpired:
            raise
        except QwenTtsTimeout:
            await self._close_session(sess, reason="task_started_timeout")
            raise
        except asyncio.CancelledError:
            await self._close_session(sess, reason="cancelled")
            raise
        except Exception as exc:
            await self._close_session(sess, reason=f"start_failed:{type(exc).__name__}")
            raise QwenTtsStartFailed(type(exc).__name__) from exc

    async def _wait_started(self, sess, timeout=10):
        wait_started = asyncio.create_task(sess.started.wait())
        wait_cancel = asyncio.create_task(sess.cancel_event.wait())
        try:
            done, pending = await asyncio.wait(
                {wait_started, wait_cancel},
                timeout=timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            if not done:
                raise QwenTtsTimeout("task_started_timeout")
            if sess.cancelled or sess.cancel_event.is_set() or not sess.started.is_set():
                raise QwenTtsExpired("aborted_before_started")
        except asyncio.CancelledError:
            wait_started.cancel()
            wait_cancel.cancel()
            await asyncio.gather(wait_started, wait_cancel, return_exceptions=True)
            raise

    async def text_to_speak(self, text, _, official=False):
        sess = self._current
        if (
            sess is None
            or sess.ws is None
            or not self._session_live(sess)
            or not sess.started.is_set()
        ):
            return
        if official or sess.enable_ssml:
            filtered_text = textUtils.strip_all_emotion_tags(text or "")
        else:
            filtered_text = textUtils.strip_all_emotion_tags(
                MarkdownCleaner.clean_markdown(text)
            )
        if not filtered_text:
            return
        continue_task_message = build_continue_task(sess.task_id, filtered_text)
        await sess.ws.send(json.dumps(continue_task_message))
        sess._text_seq = getattr(sess, "_text_seq", 0) + 1
        if sess._text_seq == 1:
            trace.mark(self.conn, "tts_first_text")
        self._trace_ws(
            "send",
            continue_task_message,
            extra={
                "text_seq": sess._text_seq,
                "text_chars": len(filtered_text),
                "text": filtered_text,
            },
            sess=sess,
        )

    async def finish_session(self, session_id, emit_last=True, cancel=False):
        sess = self._current
        if sess is None or sess.ws is None:
            return
        if session_id and sess.task_id and session_id != sess.task_id:
            self._tts_note(
                sess,
                "discard",
                reason="finish_task_id_mismatch",
                extra={"finish_task_id": session_id},
            )
            return
        if not self._session_live(sess):
            return
        sess.emit_device_last = bool(emit_last)
        finish_message = build_finish_task(session_id or sess.task_id, cancel=cancel)
        try:
            await sess.ws.send(json.dumps(finish_message))
            self._trace_ws("send", finish_message, sess=sess)
            if sess.monitor_task and sess.monitor_task is not asyncio.current_task():
                await asyncio.wait_for(sess.monitor_task, timeout=20)
        except asyncio.CancelledError:
            await self._close_session(sess, reason="finish_cancelled")
            raise
        except Exception as exc:
            logger.bind(tag=TAG).warning(f"结束TTS会话失败: {type(exc).__name__}")
            await self._close_session(sess, reason=f"finish_failed:{type(exc).__name__}")

    def cancel_session(self):
        """Bind the live session now; native cancel then close if needed."""
        sess = self._current
        self.last_cancel_session = sess
        if sess is None:
            return None
        sess.cancelled = True
        try:
            sess.cancel_event.set()
        except Exception:
            pass
        self._compiler = IncrementalCompiler()
        self._turn_first_sent = False
        self._tts_note(sess, "cancel", reason="abort")
        trace.emit(
            "tts.cancel_task",
            self.conn,
            {
                "task_id": sess.task_id,
                "action": "finish_task_cancel_or_close_ws",
                "abort_epoch": sess.abort_epoch,
                "note": "cancel bound at call time",
            },
        )
        return self._cancel_native(sess)

    async def _cancel_native(self, sess):
        ws = sess.ws if sess is not None else None
        if ws is not None and sess.task_id:
            try:
                msg = build_finish_task(sess.task_id, cancel=True)
                await ws.send(json.dumps(msg))
                self._trace_ws("send", msg, sess=sess)
            except Exception:
                pass
        await self._close_session(sess, reason="abort")

    async def close(self):
        sess = self._current
        if sess is None:
            return
        sess.cancelled = True
        try:
            sess.cancel_event.set()
        except Exception:
            pass
        await self._close_session(sess, reason="provider_close")

    async def _close_session(self, sess, reason="close"):
        if sess is None:
            return
        sess.cancelled = True
        try:
            sess.cancel_event.set()
        except Exception:
            pass
        if sess.closed:
            self._detach_if_current(sess, reason="already_closed")
            return
        sess.closed = True
        self._tts_note(
            sess,
            "close",
            reason=reason,
            extra={
                "audio_frames": sess.audio_frames,
                "ready_ms": sess.ready_ms,
                "first_audio_ms": sess.first_audio_ms,
            },
        )
        task = sess.monitor_task
        current = None
        try:
            current = asyncio.current_task()
        except Exception:
            current = None
        if task is not None and task is not current and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        ws = sess.ws
        sess.ws = None
        if ws is not None:
            try:
                await ws.close()
            except Exception:
                pass
        skipped = self._detach_if_current(sess, reason=reason)
        if skipped and ws is None:
            return

    def _encode_pcm(self, pcm: bytes, end=False, sess=None):
        active = sess or self._current
        if active is None:
            return
        if not self._session_live(active) or self._current is not active:
            return
        encoder = active.opus_encoder
        if self.sample_rate != DEVICE_SAMPLE_RATE:
            pcm, active._resample_carry = resample_pcm16_mono(
                pcm, self.sample_rate, DEVICE_SAMPLE_RATE, active._resample_carry
            )
            if end and active._resample_carry:
                pcm += active._resample_carry
                active._resample_carry = b""
        if pcm or end:
            t0 = time.perf_counter()
            stats = pcm_stats(pcm, DEVICE_SAMPLE_RATE, 1) if pcm else {"bytes": 0, "duration_ms": 0}
            active._pcm_seq = getattr(active, "_pcm_seq", 0) + 1
            if active._pcm_seq == 1:
                trace.mark(self.conn, "tts_first_upstream_pcm")
            if isinstance(stats.get("duration_ms"), (int, float)):
                active._pcm_ms = getattr(active, "_pcm_ms", 0.0) + stats["duration_ms"]
            if active._pcm_seq == 1 or active._pcm_seq % 10 == 0 or end:
                trace.emit(
                    "tts.upstream_pcm",
                    self.conn,
                    {
                        "seq": active._pcm_seq,
                        "end": end,
                        "pcm": stats,
                        "encode_params": {
                            "sample_rate": DEVICE_SAMPLE_RATE,
                            "channels": 1,
                            "frame_size_ms": OPUS_FRAME_MS,
                            "bitrate": getattr(encoder, "bitrate", "unknown"),
                        },
                        "cumulative_pcm_ms": getattr(active, "_pcm_ms", "unknown"),
                        "encode_started": True,
                    },
                )
            token = stream_context.set(active.owner_token())
            try:
                encoder.encode_pcm_to_opus_stream(
                    pcm, end, callback=self.handle_opus
                )
            finally:
                stream_context.reset(token)
            if active._pcm_seq == 1 or end:
                trace.emit(
                    "tts.encode_done",
                    self.conn,
                    {
                        "seq": active._pcm_seq,
                        "encode_ms": round((time.perf_counter() - t0) * 1000.0, 3),
                        "end": end,
                    },
                )

    def _put_audio(self, sess, item):
        if sess is None or self._current is not sess or not self._session_live(sess):
            return
        token = stream_context.set(sess.owner_token())
        try:
            self.tts_audio_queue.put(item)
        finally:
            stream_context.reset(token)

    async def _start_monitor_tts_response(self, sess):
        session_finished = False
        try:
            while sess.ws and not self.conn.stop_event.is_set():
                if not self._session_live(sess):
                    break
                try:
                    msg = await sess.ws.recv()
                except websockets.ConnectionClosed:
                    break
                if not self._session_live(sess) or self._current is not sess:
                    break
                if isinstance(msg, (bytes, bytearray)):
                    if getattr(sess, "_pcm_seq", 0) == 0:
                        trace.mark(self.conn, "tts_first_upstream_pcm")
                    if sess.first_audio_ms is None:
                        sess.first_audio_ms = round(
                            (time.perf_counter() - sess.create_t0) * 1000.0, 3
                        )
                    sess.audio_frames += 1
                    self._encode_pcm(bytes(msg), end=False, sess=sess)
                    continue
                try:
                    data = json.loads(msg)
                    event = (data.get("header") or {}).get("event")
                    task_id = (data.get("header") or {}).get("task_id")
                    self._trace_ws("recv", data, sess=sess)
                    if task_id and sess.task_id and task_id != sess.task_id:
                        trace.emit(
                            "tts.task_id_mismatch",
                            self.conn,
                            {
                                "current_task_id": sess.task_id,
                                "incoming_task_id": task_id,
                                "event": event,
                            },
                        )
                        continue
                    if event == "task-started":
                        if self._current is sess and self._session_live(sess):
                            # FIRST is a sentence/subtitle boundary, not a new
                            # device turn. Every official unit needs its caption
                            # before PCM; sendAudioMessage gates tts.start once.
                            if sess.emit_device_first or sess.caption_text is not None:
                                self._put_audio(
                                    sess,
                                    (SentenceType.FIRST, [], sess.caption_text),
                                )
                            sess.started.set()
                    elif event == "result-generated":
                        # Official units already emitted their own caption on
                        # task-started. The legacy full-turn fallback duplicated
                        # sentence_start and leaked raw emotion tags into captions.
                        if self._current is sess and sess.caption_text is None and self.conn.tts_MessageText:
                            self._put_audio(
                                sess,
                                (SentenceType.FIRST, [], caption_from(self.conn.tts_MessageText)),
                            )
                            self.conn.tts_MessageText = None
                    elif event == "task-finished":
                        if self._current is sess and self._session_live(sess):
                            self._encode_pcm(b"", end=True, sess=sess)
                            if sess.emit_device_last:
                                self._process_before_stop_play_files()
                            session_finished = True
                            sess.finished.set()
                            trace.mark(self.conn, "tts_finished")
                        break
                    elif event == "task-failed":
                        logger.bind(tag=TAG).error(
                            "TTS任务失败: "
                            f"{(data.get('header') or {}).get('error_code', 'unknown')}"
                        )
                        break
                except json.JSONDecodeError:
                    logger.bind(tag=TAG).warning("收到无效的JSON消息")
        except asyncio.CancelledError:
            raise
        finally:
            owned_ws = sess.ws
            if not session_finished and owned_ws is not None:
                try:
                    await owned_ws.close()
                except Exception:
                    pass
                if sess.ws is owned_ws:
                    sess.ws = None
            if self._monitor_task is sess.monitor_task:
                self._monitor_task = None
            elif self._current is not sess:
                self._tts_note(sess, "cleanup_skip", reason="monitor_finally_not_current")

    async def synthesize_wav_isolated(self, text: str, output_path: str):
        """Generate a reminder asset on an owned socket, without touching live TTS.

        Uses the same customer/gateway auth and voice snapshot. Only a finished,
        nonempty PCM task becomes a WAV; cancellation/failure writes no file.
        """
        clean = textUtils.strip_all_emotion_tags(MarkdownCleaner.clean_markdown(text))
        if not clean.strip():
            raise RuntimeError("tts_empty")
        snapshot = dict(freeze_snapshot(self._config_snapshot))
        snapshot["format"] = "pcm"
        snapshot.pop("bit_rate", None)
        snapshot["sample_rate"] = self.sample_rate
        task_id = str(uuid.uuid4())
        ws = None
        audio = bytearray()
        started = False
        max_bytes = self.sample_rate * 2 * 60
        async def collect():
            nonlocal ws, started
            if True:
                ws = await self._connect(self.ws_url, self._auth_header())
                await ws.send(json.dumps(build_run_task(task_id, snapshot)))
                while True:
                    msg = await ws.recv()
                    if isinstance(msg, (bytes, bytearray)):
                        if not started:
                            raise RuntimeError("tts_protocol_invalid")
                        audio.extend(msg)
                        if len(audio) > max_bytes:
                            raise RuntimeError("tts_audio_too_large")
                        continue
                    try:
                        data = json.loads(msg)
                        header = data.get("header") or {}
                    except (ValueError, TypeError, AttributeError):
                        raise RuntimeError("tts_protocol_invalid") from None
                    if not isinstance(header, dict) or header.get("task_id") != task_id:
                        raise RuntimeError("tts_protocol_invalid")
                    event = header.get("event")
                    if event == "task-started" and not started:
                        started = True
                        await ws.send(json.dumps(build_continue_task(task_id, clean)))
                        await ws.send(json.dumps(build_finish_task(task_id)))
                    elif event == "task-failed":
                        raise RuntimeError("tts_task_failed")
                    elif event == "task-finished":
                        if not started or not audio or len(audio) % 2:
                            raise RuntimeError("tts_empty")
                        break
        try:
            # Python 3.10 compatible total deadline, including connect/send/read.
            await asyncio.wait_for(collect(), timeout=35)
        except asyncio.TimeoutError:
            raise RuntimeError("tts_timeout") from None
        finally:
            if ws is not None:
                try:
                    await asyncio.wait_for(ws.close(), timeout=3)
                except Exception:
                    pass
        with wave.open(output_path, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(snapshot["sample_rate"])
            wav.writeframes(audio)

    def to_tts(self, text: str) -> list:
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            session_id = str(uuid.uuid4())
            audio_data = []

            async def _generate_audio():
                ws = await self._connect(self.ws_url, self._auth_header())
                try:
                    await ws.send(
                        json.dumps(
                            {
                                "header": {
                                    "action": "run-task",
                                    "task_id": session_id,
                                    "streaming": "duplex",
                                },
                                "payload": {
                                    "task_group": "audio",
                                    "task": "tts",
                                    "function": "SpeechSynthesizer",
                                    "model": self.model,
                                    "parameters": {
                                        "text_type": "PlainText",
                                        "voice": self.voice,
                                        "format": self.format,
                                        "sample_rate": self.sample_rate,
                                    },
                                    "input": {},
                                },
                            }
                        )
                    )
                    started = False
                    encoder = opus_encoder_utils.OpusEncoderUtils(
                        sample_rate=DEVICE_SAMPLE_RATE,
                        channels=1,
                        frame_size_ms=OPUS_FRAME_MS,
                    )
                    while True:
                        msg = await asyncio.wait_for(ws.recv(), timeout=20)
                        if isinstance(msg, (bytes, bytearray)):
                            if started:
                                encoder.encode_pcm_to_opus_stream(
                                    bytes(msg), False, callback=audio_data.append
                                )
                            continue
                        data = json.loads(msg)
                        event = (data.get("header") or {}).get("event")
                        if event == "task-started" and not started:
                            started = True
                            await ws.send(
                                json.dumps(
                                    {
                                        "header": {
                                            "action": "continue-task",
                                            "task_id": session_id,
                                            "streaming": "duplex",
                                        },
                                        "payload": {
                                            "input": {
                                                "text": textUtils.strip_all_emotion_tags(
                                                    MarkdownCleaner.clean_markdown(text)
                                                )
                                            }
                                        },
                                    }
                                )
                            )
                            await ws.send(
                                json.dumps(
                                    {
                                        "header": {
                                            "action": "finish-task",
                                            "task_id": session_id,
                                            "streaming": "duplex",
                                        },
                                        "payload": {"input": {}},
                                    }
                                )
                            )
                        elif event == "task-finished":
                            encoder.encode_pcm_to_opus_stream(
                                b"", True, callback=audio_data.append
                            )
                            break
                        elif event == "task-failed":
                            break
                finally:
                    await ws.close()

            loop.run_until_complete(_generate_audio())
            return audio_data
        except Exception as exc:
            logger.bind(tag=TAG).error(f"生成音频失败: {type(exc).__name__}")
            return []
        finally:
            try:
                loop.close()
            except Exception:
                pass
