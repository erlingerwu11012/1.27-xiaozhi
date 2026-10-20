"""设备下行统一守卫：仅 current session 可发送/入队。

产品规则：一块主板 = 一个 device_id = 一个当前 WebSocket session。
任何 superseded / 非 current 连接的下行必须 fail closed。
"""

from __future__ import annotations

import queue
import uuid
from collections import OrderedDict
from typing import Optional

from config.logger import setup_logging
from core.utils import textUtils

TAG = __name__
logger = setup_logging()


def _resolve_local_active_registry(conn):
    return getattr(conn, "local_active_registry", None)


def is_outbound_allowed(conn) -> bool:
    """预检查：是否仍允许下行（非最终安全边界）。"""
    if conn is None:
        return False
    if getattr(conn, "superseded", False):
        return False
    stop_event = getattr(conn, "stop_event", None)
    if stop_event is not None:
        is_set_fn = getattr(stop_event, "is_set", None)
        if callable(is_set_fn):
            try:
                if is_set_fn() is True:
                    return False
            except Exception:
                pass
    if getattr(conn, "outbound_mode", None) == "local_active":
        if getattr(conn, "_outbound_closed", False):
            return False
        device_id = getattr(conn, "device_id", None)
        registry = _resolve_local_active_registry(conn)
        if not device_id or registry is None:
            return False
        check = getattr(registry, "is_current_connection", None)
        if not callable(check):
            return False
        try:
            return bool(check(device_id, conn))
        except Exception:
            return False
    server = getattr(conn, "server", None)
    device_id = getattr(conn, "device_id", None)
    if server is None or not device_id:
        return False
    check = getattr(server, "is_current_connection", None)
    if not callable(check):
        return False
    try:
        return bool(check(device_id, conn))
    except Exception:
        return False


async def guarded_ws_send(
    conn,
    data,
    *,
    command: Optional[str] = None,
    msg_type: Optional[str] = None,
    task_id=None,
) -> bool:
    """唯一允许的 WebSocket 下行入口（文本或二进制）。

    local_active：经 ReminderControlManager.send_to_current（per-device 锁 + current）。
    主连接：经 WebSocketServer.send_to_current。
    禁止裸 conn.websocket.send 回退。
    """
    device_id = getattr(conn, "device_id", None)
    session_id = getattr(conn, "session_id", None)

    if getattr(conn, "outbound_mode", None) == "local_active":
        if not device_id or not str(device_id).strip():
            logger.bind(tag=TAG).info(
                f"[device_send] skip task_id={task_id} target_device_id={device_id} "
                f"connection_id={session_id} command={command} type={msg_type} "
                f"reason=missing_device_id"
            )
            return False
        registry = _resolve_local_active_registry(conn)
        send = getattr(registry, "send_to_current", None) if registry else None
        if not callable(send):
            logger.bind(tag=TAG).warning(
                f"[device_send] skip task_id={task_id} target_device_id={device_id} "
                f"connection_id={session_id} command={command} type={msg_type} "
                f"reason=no_local_active_registry"
            )
            return False
        return await send(
            device_id,
            data,
            handler=conn,
            command=command,
            msg_type=msg_type,
            task_id=task_id,
        )

    if not is_outbound_allowed(conn):
        logger.bind(tag=TAG).info(
            f"[device_send] skip task_id={task_id} target_device_id={device_id} "
            f"connection_id={session_id} command={command} type={msg_type} "
            f"reason=stale_connection"
        )
        return False

    server = getattr(conn, "server", None)
    send = getattr(server, "send_to_current", None)
    if not callable(send):
        logger.bind(tag=TAG).warning(
            f"[device_send] skip task_id={task_id} target_device_id={device_id} "
            f"connection_id={session_id} command={command} type={msg_type} "
            f"reason=no_send_to_current"
        )
        return False
    return await send(
        device_id,
        data,
        handler=conn,
        command=command,
        msg_type=msg_type,
        task_id=task_id,
    )


TTS_SENTENCE_EPOCH_LIMIT = 32


def _tts_sentence_epoch_map(conn) -> OrderedDict:
    mapping = getattr(conn, "tts_sentence_epochs", None)
    if not isinstance(mapping, OrderedDict):
        mapping = OrderedDict(mapping or {})
        conn.tts_sentence_epochs = mapping
    return mapping


def _prune_tts_sentence_epochs(conn, keep=TTS_SENTENCE_EPOCH_LIMIT, protect=None):
    mapping = _tts_sentence_epoch_map(conn)
    while len(mapping) > keep:
        oldest = next(iter(mapping))
        if oldest == protect:
            mapping.move_to_end(protect)
            if next(iter(mapping)) == protect:
                break
            continue
        mapping.popitem(last=False)


def bind_tts_sentence_epoch(conn, sentence_id, epoch=None):
    """Bind abort epoch at generation/sentence birth. First write wins."""
    if not sentence_id:
        return None
    mapping = _tts_sentence_epoch_map(conn)
    if sentence_id in mapping:
        return mapping[sentence_id]
    if epoch is None:
        epoch = int(getattr(conn, "tts_abort_epoch", 0) or 0)
    mapping[sentence_id] = int(epoch)
    _prune_tts_sentence_epochs(conn, protect=sentence_id)
    return mapping[sentence_id]


def begin_tts_turn(conn, sentence_id=None, epoch=None):
    """Establish TTS ownership when a generation turn starts, before any output."""
    if not sentence_id:
        sentence_id = getattr(conn, "sentence_id", None) or uuid.uuid4().hex
    if not getattr(conn, "sentence_id", None):
        conn.sentence_id = sentence_id
    bound = bind_tts_sentence_epoch(conn, sentence_id, epoch)
    return sentence_id, bound


def resolve_enqueue_abort_epoch(conn, dto):
    """Resolve epoch from the turn binding. Never guess the current abort epoch."""
    sid = getattr(dto, "sentence_id", None)
    mapping = getattr(conn, "tts_sentence_epochs", None) or {}
    if sid and sid in mapping:
        return mapping[sid]
    explicit = getattr(dto, "abort_epoch", None)
    if explicit is not None:
        return int(explicit)
    return None


def enqueue_tts(conn, dto) -> bool:
    """向本连接 TTS 文本队列入队；非 current 时 fail closed，不入队。"""
    if not is_outbound_allowed(conn):
        logger.bind(tag=TAG).info(
            f"[device_send] skip target_device_id={getattr(conn, 'device_id', None)} "
            f"connection_id={getattr(conn, 'session_id', None)} command=tts "
            f"reason=stale_connection"
        )
        return False
    tts = getattr(conn, "tts", None)
    if tts is None or getattr(tts, "tts_text_queue", None) is None:
        return False
    try:
        dto.session_id = getattr(conn, "session_id", None)
    except Exception:
        pass
    current_epoch = int(getattr(conn, "tts_abort_epoch", 0) or 0)
    bound_epoch = resolve_enqueue_abort_epoch(conn, dto)
    dto.abort_epoch = bound_epoch
    if bound_epoch is None or int(bound_epoch) != current_epoch:
        reason = (
            "unbound_generation"
            if bound_epoch is None
            else "stale_generation_epoch"
        )
        logger.bind(tag=TAG).info(
            f"[tts_enqueue] skip target_device_id={getattr(conn, 'device_id', None)} "
            f"connection_id={getattr(conn, 'session_id', None)} "
            f"sentence_id={getattr(dto, 'sentence_id', None)} "
            f"message_epoch={bound_epoch} current_epoch={current_epoch} "
            f"reason={reason}"
        )
        return False
    if isinstance(getattr(dto, "content_detail", None), str):
        dto.content_detail = textUtils.strip_all_emotion_tags(dto.content_detail)
    tts.tts_text_queue.put(dto)
    return True


def tts_message_still_valid(conn, message) -> bool:
    """TTS 消化线程：丢弃非本 session / superseded / 非 current 的队列项。"""
    if not is_outbound_allowed(conn):
        return False
    msg_sid = getattr(message, "session_id", None)
    conn_sid = getattr(conn, "session_id", None)
    if msg_sid and conn_sid and msg_sid != conn_sid:
        return False
    return True


def _drain_queue(q) -> None:
    """清空可 drain 的队列；Mock 队列应在测试中使用真实 queue.Queue。"""
    if q is None or not hasattr(q, "get_nowait"):
        return
    try:
        while True:
            q.get_nowait()
    except queue.Empty:
        pass


def bump_device_connection_generation(device_id: str) -> int:
    """设备级连接代际：新 session 注册或旧连接 invalidate 时递增。"""
    if not device_id:
        return 0
    bag = getattr(bump_device_connection_generation, "_gens", None)
    if bag is None:
        bag = {}
        bump_device_connection_generation._gens = bag
    gen = int(bag.get(device_id, 0)) + 1
    bag[device_id] = gen
    return gen


def get_device_connection_generation(device_id: str) -> int:
    bag = getattr(bump_device_connection_generation, "_gens", None) or {}
    return int(bag.get(device_id or "", 0))


def reset_device_connection_generations_for_tests() -> None:
    bump_device_connection_generation._gens = {}


def invalidate_connection(conn, *, reason: str = "superseded") -> None:
    """使旧连接下行失效：标记 superseded、打断 TTS、取消异步下行任务。"""
    if conn is None:
        return
    setattr(conn, "superseded", True)
    try:
        conn.client_abort = True
    except Exception:
        pass
    try:
        from core.utils.reminder_interaction import on_connection_invalidated

        on_connection_invalidated(conn)
    except Exception:
        pass
    device_id = getattr(conn, "device_id", None)
    if device_id:
        bump_device_connection_generation(device_id)
    tts = getattr(conn, "tts", None)
    if tts is not None:
        for qname in ("tts_text_queue", "tts_audio_queue"):
            _drain_queue(getattr(tts, qname, None))
    for bag_name in ("_reminder_voice_tasks", "_outbound_tasks"):
        bag = getattr(conn, bag_name, None)
        if not bag:
            continue
        for task in list(bag):
            try:
                if hasattr(task, "cancel"):
                    task.cancel()
            except Exception:
                pass
        try:
            bag.clear()
        except Exception:
            pass
    logger.bind(tag=TAG).info(
        f"[conn] invalidate device_id={getattr(conn, 'device_id', None)} "
        f"session_id={getattr(conn, 'session_id', None)} reason={reason}"
    )


def track_outbound_task(conn, task) -> None:
    """登记可在 superseded 时取消的异步下行任务。"""
    if conn is None or task is None:
        return
    bag = getattr(conn, "_outbound_tasks", None)
    if bag is None:
        bag = set()
        conn._outbound_tasks = bag
    bag.add(task)

    def _done(_t):
        try:
            bag.discard(_t)
        except Exception:
            pass

    try:
        task.add_done_callback(_done)
    except Exception:
        pass
