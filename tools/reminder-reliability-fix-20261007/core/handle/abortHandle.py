import json
import asyncio
import inspect
from core.utils.device_outbound import guarded_ws_send
from core.utils import trace_log as trace

TAG = __name__


def _cancel_session_args(tts, conn):
    """Bind cancel arguments now. Support async cancel_session(session_id) and sync cancel()."""
    extra = []
    cancel = getattr(tts, "cancel_session", None)
    if not callable(cancel):
        return extra
    try:
        required = [
            param
            for param in inspect.signature(cancel).parameters.values()
            if param.name != "self"
            and param.kind in (param.POSITIONAL_ONLY, param.POSITIONAL_OR_KEYWORD)
            and param.default is inspect.Parameter.empty
        ]
    except (TypeError, ValueError):
        return extra
    if required:
        extra.append(
            getattr(tts, "task_id", None)
            or getattr(tts, "session_id", None)
            or getattr(conn, "sentence_id", None)
        )
    return extra


def _retain_cancel_task(conn, result):
    """Schedule a cancel coroutine once and keep a reference so it is not leaked."""
    if result is None:
        return None
    if isinstance(result, asyncio.Task):
        task = result
    elif asyncio.isfuture(result):
        task = asyncio.ensure_future(result)
    elif asyncio.iscoroutine(result):
        task = asyncio.create_task(result)
    else:
        return None
    pending = getattr(conn, "_tts_cancel_tasks", None)
    if pending is None:
        pending = set()
        conn._tts_cancel_tasks = pending
    pending.add(task)
    task.add_done_callback(pending.discard)
    return task


def _finalize_aborted_sentence(conn):
    """打断终态：标记 aborted 并输出一次句级遥测（仅打印计数/时差）。"""
    telemetry = getattr(conn, "tts_sentence_telemetry", None)
    if telemetry is None:
        return None
    telemetry.mark_aborted(getattr(conn, "sentence_id", None))
    line = telemetry.finalize("abort", conn._mask(getattr(conn, "session_id", None)))
    if line:
        conn.logger.bind(tag=TAG).info(line)
    return line


async def handleAbortMessage(conn):
    conn.logger.bind(tag=TAG).info("Abort message received")
    trace.mark(conn, "abort")
    abort_listening = getattr(getattr(conn, "asr", None), "abort_listening", None)
    if callable(abort_listening):
        try:
            result = abort_listening(conn)
            if asyncio.iscoroutine(result):
                await result
        except Exception as exc:
            trace.emit(
                "asr.abort_failed",
                conn,
                {"error_type": type(exc).__name__, "error": str(exc)},
            )
    # 普通对话 abort 仅打断 LLM/TTS 播报；不触碰 ReminderVoiceStore 中已确认/已下发资产。
    conn.tts_abort_epoch = getattr(conn, 'tts_abort_epoch', 0) + 1
    conn.client_abort = True
    conn.clear_queues()
    tts = getattr(conn, "tts", None)
    # 必须在本调用栈绑定要取消的会话；不能把查找推迟到 create_task 执行时。
    cancel = getattr(tts, "cancel_session", None)
    cancel_started = False
    bound_task_id = None
    if callable(cancel):
        try:
            extra = _cancel_session_args(tts, conn)
            result = cancel(*extra)
            bound = getattr(tts, "last_cancel_session", None)
            bound_task_id = getattr(bound, "task_id", None) or (
                extra[0] if extra else None
            )
            cancel_started = True
            _retain_cancel_task(conn, result)
        except Exception as exc:
            trace.emit(
                "tts.cancel_task",
                conn,
                {"ok": False, "error_type": type(exc).__name__, "error": str(exc)},
            )
            cancel_started = False
    else:
        cancel_started = False
    # 打断客户端说话状态（abort stop：核对连接后发送；不在 finally 盲目补发）
    stop_ok = await guarded_ws_send(
        conn,
        json.dumps({"type": "tts", "state": "stop", "session_id": conn.session_id}),
        command="tts",
        msg_type="tts",
    )
    try:
        from core.utils.tts_listen_observe import note_tts_stop_sent, reset_tts_outbound

        if stop_ok:
            note_tts_stop_sent(conn)
        else:
            reset_tts_outbound(conn)
    except Exception:
        pass
    trace.emit(
        "device.abort",
        conn,
        {
            "tts_abort_epoch": getattr(conn, "tts_abort_epoch", None),
            "cancel_session_started": cancel_started,
            "cancel_task_id": bound_task_id,
            "tts_stop_sent": bool(stop_ok),
            "note": "tts stop dispatched to device; not a confirmed playback-stop time",
        },
    )
    conn.clearSpeakStatus()
    _finalize_aborted_sentence(conn)
    conn.logger.bind(tag=TAG).info("Abort message received-end")
