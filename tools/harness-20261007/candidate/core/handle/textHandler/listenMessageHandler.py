from core.utils.audio_ingress import (
    audio_count,
    begin_listen,
    drain_barrier_seq,
    drain_queued_audio,
    log_audio_stats,
)
import inspect
import time
from typing import Dict, Any
from core.utils.utterance_state import on_listen_stop
from core.utils.tts_listen_observe import (
    classify_listen_start,
    log_listen_during_tts,
    log_listen_start_decision,
)

from core.handle.receiveAudioHandle import handleAudioMessage, startToChat
from core.handle.reportHandle import enqueue_asr_report
from core.handle.sendAudioHandle import send_stt_message, send_tts_message
from core.handle.textMessageHandler import TextMessageHandler
from core.handle.textMessageType import TextMessageType
from core.utils.util import remove_punctuation_and_length
from core.utils import trace_log as trace

TAG = __name__


async def _call_asr_listen(fn, conn, reason: str) -> None:
    """Optional reason= for new ASR; old providers only accept conn."""
    if not callable(fn):
        return
    kwargs = {}
    try:
        params = inspect.signature(fn).parameters
        if "reason" in params:
            kwargs["reason"] = reason
    except (TypeError, ValueError):
        kwargs = {"reason": reason}
    result = fn(conn, **kwargs)
    if inspect.isawaitable(result):
        await result


class ListenTextMessageHandler(TextMessageHandler):
    """Listen消息处理器"""

    @property
    def message_type(self) -> TextMessageType:
        return TextMessageType.LISTEN

    async def handle(self, conn, msg_json: Dict[str, Any]) -> None:
        if msg_json["state"] == "start":
            # TTS 期间 listen：仅观测，不因 client_is_speaking 丢弃
            log_listen_during_tts(conn, msg_json, tag=TAG)
            reason, skip_reset = classify_listen_start(conn, msg_json)
            if "mode" in msg_json and not skip_reset:
                conn.client_listen_mode = msg_json["mode"]
                conn.logger.bind(tag=TAG).debug(
                    f"客户端拾音模式：{conn.client_listen_mode}"
                )
            log_listen_start_decision(
                conn, msg_json, reason, skip=skip_reset, tag=TAG
            )
            if skip_reset:
                # 同一活动听写会话、相同 generation/mode、无语音：不 bump epoch、不清缓冲
                trace.emit(
                    "device.listen",
                    conn,
                    {
                        "message": msg_json,
                        "state": "start",
                        "idempotent": True,
                        "reason": reason,
                    },
                )
                return
            if reason == "no_generation_id" and getattr(conn, "device_listening", False):
                cid = getattr(conn, "_cid", None)
                cid_s = cid() if callable(cid) else ""
                conn.logger.bind(tag=TAG).info(
                    f"[listen_start_limit] {cid_s} reason=no_generation_id "
                    f"note=protocol_lacks_session_id_cannot_safe_dedupe"
                )
            begin_listen(conn, msg_json.get("generation"))
            from core.utils.person_identity import refresh_directory,reset_speaker
            import asyncio
            reset_speaker(conn)
            conn.identity_state={"mode":"unavailable","directory_version":0}
            # Keep the WebSocket receive loop free to route incoming audio and
            # cleanup replies while the authority request is in flight.
            conn.person_directory_refresh_task=asyncio.create_task(refresh_directory(conn))
            conn.trace_turn_id = getattr(conn, "listen_epoch", None)
            reasons = getattr(conn, "trace_id_missing_reasons", None)
            if conn.trace_turn_id not in (None, 0) and isinstance(reasons, dict):
                reasons.pop("turn_id", None)
            conn._trace_uplink_seq = 0
            conn._trace_marks = {
                k: v
                for k, v in (getattr(conn, "_trace_marks", {}) or {}).items()
                if k in ("connect", "hello")
            }
            trace.emit("device.listen", conn, {"message": msg_json, "state": "start"})
            conn.just_woken_up = False
            await _call_asr_listen(
                getattr(conn.asr, "start_listening", None), conn, "new_listen"
            )
            # listen start is not confirmed speech; VAD owns client_have_voice.
        elif msg_json["state"] == "stop":
            barrier = drain_barrier_seq(conn)
            stop_epoch = getattr(conn, "listen_epoch", 0)
            drained = await drain_queued_audio(conn, barrier, epoch=stop_epoch)
            ev = getattr(conn, "stop_event", None)
            closing = False
            try:
                closing = bool(ev is not None and ev.is_set())
            except Exception:
                closing = False
            if getattr(conn, "listen_epoch", 0) != stop_epoch:
                audio_count(conn, "listen_stop_abandoned_new_epoch")
                log_audio_stats(conn, "listen_stop_abandoned_new_epoch")
                return
            if closing:
                audio_count(conn, "listen_stop_abandoned_disconnect")
                log_audio_stats(conn, "listen_stop_abandoned_disconnect")
                return
            stop_change = on_listen_stop(conn)
            committed = False
            if drained:
                stop_listening = getattr(conn.asr, "stop_listening", None)
                if callable(stop_listening):
                    await _call_asr_listen(stop_listening, conn, "device_stop")
                    committed = True
                elif len(conn.asr_audio) > 0:
                    await handleAudioMessage(conn, b"")
                    committed = True
            else:
                audio_count(conn, "listen_stop_commit_skipped_undrained")
                abort_listening = getattr(conn.asr, "abort_listening", None)
                if callable(abort_listening):
                    await _call_asr_listen(abort_listening, conn, "drain_timeout")
            log_audio_stats(conn, "listen_stop" if committed else "listen_stop_undrained")
            current = getattr(conn.asr, "_current", None)
            pending_frames = len(getattr(current, "pending", []) or [])
            trace.emit(
                "device.listen",
                conn,
                {
                    "message": msg_json,
                    "state": "stop",
                    "stop_source": "device_listen_stop",
                    "state_change": stop_change,
                    "drain_barrier_seq": barrier,
                    "drain_ok": drained,
                    "committed": committed,
                    "pending_frames": pending_frames,
                    "ingress_stats": dict(getattr(conn, "_audio_ingress_stats", {}) or {}),
                },
            )
        elif msg_json["state"] == "detect":
            if "mode" in msg_json:
                conn.client_listen_mode = msg_json["mode"]
            begin_listen(conn, msg_json.get("generation"))
            from core.utils.person_identity import reset_speaker
            reset_speaker(conn)
            conn.trace_turn_id = getattr(conn, "listen_epoch", None)
            reasons = getattr(conn, "trace_id_missing_reasons", None)
            if conn.trace_turn_id not in (None, 0) and isinstance(reasons, dict):
                reasons.pop("turn_id", None)
            await _call_asr_listen(
                getattr(conn.asr, "stop_listening", None), conn, "wakeup_detect"
            )
            conn.client_have_voice = False
            conn.asr_audio.clear()
            trace.emit("device.listen", conn, {"message": msg_json, "state": "detect"})
            if "text" in msg_json:
                conn.last_activity_time = time.time() * 1000
                original_text = msg_json["text"]  # 保留原始文本
                filtered_len, filtered_text = remove_punctuation_and_length(
                    original_text
                )

                # 识别是否是唤醒词
                is_wakeup_words = filtered_text in conn.config.get("wakeup_words")
                # 是否开启唤醒词回复
                enable_greeting = conn.config.get("enable_greeting", True)

                if is_wakeup_words and not enable_greeting:
                    # 如果是唤醒词，且关闭了唤醒词回复，就不用回答
                    await send_stt_message(conn, original_text)
                    await send_tts_message(conn, "stop", None)
                    conn.client_is_speaking = False
                elif is_wakeup_words:
                    conn.just_woken_up = True
                    # 上报纯文字数据（复用ASR上报功能，但不提供音频数据）
                    enqueue_asr_report(conn, "嘿，你好呀", [])
                    await startToChat(conn, "嘿，你好呀")
                else:
                    # 上报纯文字数据（复用ASR上报功能，但不提供音频数据）
                    enqueue_asr_report(conn, original_text, [])
                    # 否则需要LLM对文字内容进行答复
                    await startToChat(conn, original_text)
