"""提醒卡片交互监听生命周期（仅控制 listen/idle，不改变提醒业务状态）。"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

# 以服务端收到 interaction_opened 的时刻为基准，deadline ≤ received_at + 180s
MAX_INTERACTION_DURATION_SEC = 180.0
INTERACTION_EXPIRE_SKEW_SEC = 2.0


@dataclass
class ReminderInteractionState:
    active: bool = False
    instance_id: str = ""
    revision: int = 0
    received_at: int = 0
    expires_at: int = 0
    expires_at_clipped: bool = False

    def clear(self) -> None:
        self.active = False
        self.instance_id = ""
        self.revision = 0
        self.received_at = 0
        self.expires_at = 0
        self.expires_at_clipped = False


def get_interaction_state(conn) -> ReminderInteractionState:
    state = getattr(conn, "reminder_interaction", None)
    if not isinstance(state, ReminderInteractionState):
        state = ReminderInteractionState()
        conn.reminder_interaction = state
    return state


def _cancel_expire_task(conn) -> None:
    task = getattr(conn, "_reminder_interaction_expire_task", None)
    if task is not None and hasattr(task, "cancel"):
        task.cancel()
    conn._reminder_interaction_expire_task = None


def validate_interaction_expires_at(
    expires_at: Any, *, received_at: int | None = None
) -> tuple[bool, str, int, bool]:
    """校验 expires_at；超过 received_at+180s 时安全裁剪至上限。"""
    try:
        exp = int(expires_at)
    except (TypeError, ValueError):
        return False, "bad_expires_at", 0, False
    received_at = int(received_at if received_at is not None else time.time())
    if exp <= received_at:
        return False, "interaction_expired", 0, False
    max_exp = received_at + int(MAX_INTERACTION_DURATION_SEC)
    clipped = False
    if exp > max_exp:
        exp = max_exp
        clipped = True
    return True, "ok", exp, clipped


async def _interaction_expire_worker(conn) -> None:
    state = get_interaction_state(conn)
    expires_at = int(state.expires_at or 0)
    if not expires_at:
        return
    delay = max(0.0, expires_at - time.time() + INTERACTION_EXPIRE_SKEW_SEC)
    try:
        await asyncio.sleep(delay)
    except asyncio.CancelledError:
        return
    if not state.active:
        return
    if int(time.time()) >= expires_at:
        close_interaction(conn, reason="timeout")
        try:
            from core.utils.reminder_audit import audit_event, conn_ids

            audit_event(
                "interaction_expired",
                **conn_ids(conn),
                instance_id=state.instance_id,
                revision=state.revision,
                result_code="timeout",
                extra={"expires_at": expires_at, "received_at": state.received_at},
            )
        except Exception:
            pass


def _schedule_expire_task(conn) -> None:
    _cancel_expire_task(conn)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    task = loop.create_task(_interaction_expire_worker(conn))
    conn._reminder_interaction_expire_task = task
    from core.utils.device_outbound import track_outbound_task

    track_outbound_task(conn, task)


def is_interaction_active(conn) -> bool:
    state = get_interaction_state(conn)
    if not state.active:
        return False
    if state.expires_at and time.time() >= state.expires_at:
        close_interaction(conn, reason="timeout")
        return False
    return True


def open_interaction(
    conn,
    *,
    instance_id: str,
    revision: int,
    expires_at: int,
) -> tuple[bool, str]:
    received_at = int(time.time())
    ok, reason, exp, clipped = validate_interaction_expires_at(
        expires_at, received_at=received_at
    )
    if not ok:
        return False, reason
    state = get_interaction_state(conn)
    state.active = True
    state.instance_id = instance_id
    state.revision = int(revision)
    state.received_at = received_at
    state.expires_at = exp
    state.expires_at_clipped = clipped
    _schedule_expire_task(conn)
    return True, "expires_at_clipped" if clipped else "ok"


def close_interaction(conn, *, reason: str = "resolved") -> None:
    _cancel_expire_task(conn)
    state = get_interaction_state(conn)
    state.clear()
    _ = reason


def on_connection_invalidated(conn) -> None:
    """连接 superseded / 断开：取消 interaction 定时任务并关闭窗口。"""
    close_interaction(conn, reason="preempted")
