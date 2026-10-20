"""update_spine 本地投递闸门（SQLite 持久化，仅 xiaozhi-server 侧）。

manager-api 的 ai_role_deploy_task 是业务真相源，但“设备重连即重投”由 xiaozhi-server
的 _deliver_pending_spine_role 触发。本模块在 xiaozhi-server 侧维护一份本地投递状态，
作为重投闸门，避免设备每次 WebSocket 重连立即重投同一 update_spine 造成重启循环：

    queued -> sent -> accepted/in_progress -> completed
    以及 failed / cancelled / needs_manual_review（终态）

投递时原子记录 task_id / device_id / attempt_count / last_sent_at / next_attempt_at / state，
并施加指数退避与最大尝试次数上限。
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from typing import Dict, List, Optional, Tuple

from loguru import logger

TAG = __name__

DB_FILENAME = "spine_ota.db"
_DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")

# 状态
STATE_QUEUED = "queued"
STATE_SENT = "sent"
STATE_ACCEPTED = "accepted"
STATE_IN_PROGRESS = "in_progress"
STATE_COMPLETED = "completed"
STATE_FAILED = "failed"
STATE_CANCELLED = "cancelled"
STATE_NEEDS_MANUAL_REVIEW = "needs_manual_review"

TERMINAL_STATES = frozenset(
    {STATE_COMPLETED, STATE_FAILED, STATE_CANCELLED, STATE_NEEDS_MANUAL_REVIEW}
)
# 可取消（pending 语义）：queued/sent/accepted/in_progress
CANCELABLE_STATES = frozenset(
    {STATE_QUEUED, STATE_SENT, STATE_ACCEPTED, STATE_IN_PROGRESS}
)

DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BACKOFF_BASE_S = 30.0

# 设备 phase -> 本地状态
_PHASE_TO_STATE = {
    "waiting": STATE_ACCEPTED,
    "accepted": STATE_ACCEPTED,
    "downloading": STATE_IN_PROGRESS,
    "verifying": STATE_IN_PROGRESS,
    "applying": STATE_IN_PROGRESS,
    "success": STATE_COMPLETED,
    "failed": STATE_FAILED,
}

_RETRYABLE_ERRORS = frozenset({"E_NETWORK", "E_BUSY"})

_local = threading.local()
_db_path_override: Optional[str] = None
_override_lock = threading.Lock()


class DeviceMismatchError(RuntimeError):
    """task_id 与 device_id 不匹配：拒绝跨设备推进/投递状态，防止串指令。"""


def _require_device_owner(row, device_id: str, task_id: str) -> None:
    """已存在投递记录时，必须属于同一 device_id；否则视为跨设备串任务。"""
    if row is not None and (row["device_id"] or "") != (device_id or ""):
        raise DeviceMismatchError(
            f"task {task_id} belongs to device {row['device_id']!r}, not {device_id!r}"
        )


def set_db_path(path: Optional[str]) -> None:
    """测试/运维用：切换 SQLite 文件路径，并重置当前线程连接。"""
    global _db_path_override
    with _override_lock:
        _db_path_override = path
    _local.conn = None


def get_db_path() -> str:
    if _db_path_override:
        return _db_path_override
    return os.path.join(_DB_DIR, DB_FILENAME)


def _get_conn() -> sqlite3.Connection:
    if not hasattr(_local, "conn") or _local.conn is None:
        path = get_db_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        _local.conn = sqlite3.connect(path, timeout=10)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _init_tables(_local.conn)
    return _local.conn


def _init_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS spine_ota_delivery (
            task_id         TEXT PRIMARY KEY,
            device_id       TEXT NOT NULL,
            pack_id         TEXT,
            state           TEXT NOT NULL DEFAULT 'queued',
            attempt_count   INTEGER NOT NULL DEFAULT 0,
            progress        INTEGER NOT NULL DEFAULT 0,
            last_phase      TEXT,
            last_sent_at    REAL,
            next_attempt_at REAL,
            accepted_at     REAL,
            completed_at    REAL,
            cancelled_at    REAL,
            cancel_reason   TEXT,
            error_code      TEXT,
            last_error      TEXT,
            payload_json    TEXT,
            created_at      REAL NOT NULL,
            updated_at      REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_spine_ota_device_state
            ON spine_ota_delivery(device_id, state);
        """
    )
    conn.commit()


def _row_to_dict(row: Optional[sqlite3.Row]) -> Optional[Dict]:
    if row is None:
        return None
    return dict(row)


def get_delivery(task_id: str) -> Optional[Dict]:
    if not task_id:
        return None
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM spine_ota_delivery WHERE task_id = ?", (task_id,)
    ).fetchone()
    return _row_to_dict(row)


def list_device(device_id: str) -> List[Dict]:
    if not device_id:
        return []
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM spine_ota_delivery WHERE device_id = ? ORDER BY updated_at DESC",
        (device_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def list_stuck(limit: int = 100) -> List[Dict]:
    """列出仍可能被重投的任务（非终态）。"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM spine_ota_delivery WHERE state NOT IN "
        "(?, ?, ?, ?) ORDER BY updated_at DESC LIMIT ?",
        (
            STATE_COMPLETED,
            STATE_FAILED,
            STATE_CANCELLED,
            STATE_NEEDS_MANUAL_REVIEW,
            int(limit),
        ),
    ).fetchall()
    return [dict(r) for r in rows]


def backoff_after(delivered_count: int, base_s: float = DEFAULT_BACKOFF_BASE_S) -> float:
    """投递第 delivered_count 次后，下次允许投递前的最短等待（指数退避）。"""
    n = max(0, int(delivered_count))
    exp = min(n - 1, 10) if n >= 1 else 0
    return float(base_s) * (2 ** exp)


def decide_delivery(
    attempt_count: int,
    next_attempt_at: Optional[float],
    now: float,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> str:
    """纯策略：返回 'deliver' | 'skip_backoff' | 'stop'。"""
    attempts = max(0, int(attempt_count))
    if attempts >= int(max_attempts):
        return "stop"
    if next_attempt_at is not None and now < float(next_attempt_at):
        return "skip_backoff"
    return "deliver"


def _upsert(
    conn: sqlite3.Connection,
    task_id: str,
    device_id: str,
    pack_id: Optional[str],
    **fields,
) -> None:
    """按 task_id upsert；fields 覆盖指定列（不含 device_id/pack_id 默认）。"""
    now = fields.pop("updated_at", time.time())
    created_at = fields.pop("created_at", now)
    set_cols = [
        "device_id",
        "pack_id",
        "state",
        "attempt_count",
        "progress",
        "last_phase",
        "last_sent_at",
        "next_attempt_at",
        "accepted_at",
        "completed_at",
        "cancelled_at",
        "cancel_reason",
        "error_code",
        "last_error",
        "payload_json",
        "updated_at",
    ]
    existing = conn.execute(
        "SELECT * FROM spine_ota_delivery WHERE task_id = ?", (task_id,)
    ).fetchone()
    values = {
        "state": STATE_QUEUED,
        "attempt_count": 0,
        "progress": 0,
        "last_phase": None,
        "last_sent_at": None,
        "next_attempt_at": None,
        "accepted_at": None,
        "completed_at": None,
        "cancelled_at": None,
        "cancel_reason": None,
        "error_code": None,
        "last_error": None,
        "payload_json": None,
        "updated_at": now,
    }
    if existing is not None:
        base = dict(existing)
        values.update(
            {k: base[k] for k in set_cols if k in base and base[k] is not None}
        )
    values.update(fields)
    if existing is None:
        conn.execute(
            "INSERT INTO spine_ota_delivery "
            "(task_id, device_id, pack_id, state, attempt_count, progress, last_phase, "
            " last_sent_at, next_attempt_at, accepted_at, completed_at, cancelled_at, "
            " cancel_reason, error_code, last_error, payload_json, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                task_id,
                device_id,
                pack_id,
                values["state"],
                values["attempt_count"],
                values["progress"],
                values["last_phase"],
                values["last_sent_at"],
                values["next_attempt_at"],
                values["accepted_at"],
                values["completed_at"],
                values["cancelled_at"],
                values["cancel_reason"],
                values["error_code"],
                values["last_error"],
                values["payload_json"],
                created_at,
                values["updated_at"],
            ),
        )
    else:
        assignments = ", ".join(f"{c} = ?" for c in set_cols)
        params = [values[c] for c in set_cols] + [task_id]
        conn.execute(
            f"UPDATE spine_ota_delivery SET {assignments} WHERE task_id = ?", params
        )


def prepare_delivery(
    task_id: str,
    device_id: str,
    pack_id: Optional[str],
    payload: Dict,
    now: Optional[float] = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    backoff_base_s: float = DEFAULT_BACKOFF_BASE_S,
) -> Tuple[str, Dict]:
    """投递前原子判定 + 记录。

    返回 (action, delivery_dict)：
      - ('deliver', ...)：已原子递增 attempt_count 并置 state=sent，可发送
      - ('skip_backoff', ...)：退避窗口内，不发送
      - ('stop_terminal', ...)：终态，不发送
      - ('stop', ...)：已达最大次数，已置 needs_manual_review，不发送
    """
    now = time.time() if now is None else float(now)
    conn = _get_conn()
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(
            "SELECT * FROM spine_ota_delivery WHERE task_id = ?", (task_id,)
        ).fetchone()
        state = STATE_QUEUED
        attempt_count = 0
        next_attempt_at = None
        if row is not None:
            _require_device_owner(row, device_id, task_id)
            state = row["state"]
            attempt_count = int(row["attempt_count"] or 0)
            next_attempt_at = row["next_attempt_at"]

        if state in TERMINAL_STATES:
            conn.commit()
            return "stop_terminal", _row_to_dict(row)

        action = decide_delivery(attempt_count, next_attempt_at, now, max_attempts)
        if action == "skip_backoff":
            conn.commit()
            return "skip_backoff", _row_to_dict(row)

        if action == "stop":
            _upsert(
                conn,
                task_id,
                device_id,
                pack_id,
                state=STATE_NEEDS_MANUAL_REVIEW,
                error_code="E_MAX_ATTEMPTS",
                last_error="max delivery attempts reached: %d" % int(max_attempts),
                updated_at=now,
            )
            conn.commit()
            return "stop", get_delivery_on_conn(conn, task_id)

        new_attempt = attempt_count + 1
        next_at = now + backoff_after(new_attempt, backoff_base_s)
        _upsert(
            conn,
            task_id,
            device_id,
            pack_id,
            state=STATE_SENT,
            attempt_count=new_attempt,
            last_sent_at=now,
            next_attempt_at=next_at,
            payload_json=json.dumps(payload, ensure_ascii=False),
            updated_at=now,
        )
        conn.commit()
        return "deliver", get_delivery_on_conn(conn, task_id)
    except Exception:
        conn.rollback()
        raise


def get_delivery_on_conn(conn: sqlite3.Connection, task_id: str) -> Dict:
    row = conn.execute(
        "SELECT * FROM spine_ota_delivery WHERE task_id = ?", (task_id,)
    ).fetchone()
    return dict(row)


def _transition_from_status(
    task_id: str,
    device_id: str,
    pack_id: Optional[str],
    now: float,
    *,
    phase: Optional[str] = None,
    progress: Optional[int] = None,
    error_code: Optional[str] = None,
    last_error: Optional[str] = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    backoff_base_s: float = DEFAULT_BACKOFF_BASE_S,
) -> Tuple[bool, str, Dict]:
    """根据 spine_ota_status 推进本地状态。

    返回 (changed, prev_state, delivery_dict)。
    success 幂等：已是 completed 时 changed=False 但仍返回 completed。
    """
    conn = _get_conn()
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(
            "SELECT * FROM spine_ota_delivery WHERE task_id = ?", (task_id,)
        ).fetchone()
        if row is not None:
            _require_device_owner(row, device_id, task_id)
        prev_state = row["state"] if row is not None else None
        attempt_count = int(row["attempt_count"] or 0) if row is not None else 0

        if prev_state == STATE_COMPLETED:
            conn.commit()
            return False, STATE_COMPLETED, dict(row)

        if phase == "success":
            _upsert(
                conn,
                task_id,
                device_id,
                pack_id,
                state=STATE_COMPLETED,
                progress=100,
                last_phase=phase,
                completed_at=now,
                next_attempt_at=None,
                error_code=None,
                last_error=None,
                updated_at=now,
            )
            conn.commit()
            return True, prev_state, get_delivery_on_conn(conn, task_id)

        if phase == "failed":
            err = error_code or "E_UNKNOWN"
            if err in _RETRYABLE_ERRORS and attempt_count < int(max_attempts):
                next_at = now + backoff_after(attempt_count + 1, backoff_base_s)
                _upsert(
                    conn,
                    task_id,
                    device_id,
                    pack_id,
                    state=STATE_QUEUED,
                    last_phase=phase,
                    error_code=err,
                    last_error=last_error or err,
                    next_attempt_at=next_at,
                    updated_at=now,
                )
                conn.commit()
                return True, prev_state, get_delivery_on_conn(conn, task_id)
            _upsert(
                conn,
                task_id,
                device_id,
                pack_id,
                state=STATE_FAILED,
                last_phase=phase,
                error_code=err,
                last_error=last_error or err,
                completed_at=now,
                next_attempt_at=None,
                updated_at=now,
            )
            conn.commit()
            return True, prev_state, get_delivery_on_conn(conn, task_id)

        target = _PHASE_TO_STATE.get(phase, STATE_IN_PROGRESS)
        _upsert(
            conn,
            task_id,
            device_id,
            pack_id,
            state=target,
            progress=progress if progress is not None else (row["progress"] if row else 0),
            last_phase=phase,
            accepted_at=now if target == STATE_ACCEPTED else (row["accepted_at"] if row else None),
            updated_at=now,
        )
        conn.commit()
        return True, prev_state, get_delivery_on_conn(conn, task_id)
    except Exception:
        conn.rollback()
        raise


def mark_completed(
    task_id: str,
    device_id: str,
    pack_id: Optional[str],
    now: Optional[float] = None,
) -> Tuple[bool, str, Dict]:
    now = time.time() if now is None else float(now)
    return _transition_from_status(
        task_id, device_id, pack_id, now, phase="success"
    )


def mark_failed(
    task_id: str,
    device_id: str,
    pack_id: Optional[str],
    error_code: Optional[str],
    last_error: Optional[str] = None,
    now: Optional[float] = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    backoff_base_s: float = DEFAULT_BACKOFF_BASE_S,
) -> Tuple[bool, str, Dict]:
    now = time.time() if now is None else float(now)
    return _transition_from_status(
        task_id,
        device_id,
        pack_id,
        now,
        phase="failed",
        error_code=error_code,
        last_error=last_error,
        max_attempts=max_attempts,
        backoff_base_s=backoff_base_s,
    )


def mark_status(
    task_id: str,
    device_id: str,
    pack_id: Optional[str],
    phase: str,
    progress: Optional[int] = None,
    now: Optional[float] = None,
) -> Tuple[bool, str, Dict]:
    now = time.time() if now is None else float(now)
    return _transition_from_status(
        task_id, device_id, pack_id, now, phase=phase, progress=progress
    )


def record_sent_mirror(
    task_id: str,
    device_id: str,
    pack_id: Optional[str] = None,
    payload: Optional[Dict] = None,
    now: Optional[float] = None,
) -> None:
    """本地审计镜像：记录 manager-api 已投递事件（best-effort，不做任何投递闸门判定）。

    投递决策完全由 manager-api 中央状态机负责；本函数仅落一条本地审计记录，
    失败或 SQLite 丢失不影响也不会改变中央投递事实，可安全忽略。
    """
    now = time.time() if now is None else float(now)
    conn = _get_conn()
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(
            "SELECT * FROM spine_ota_delivery WHERE task_id = ?", (task_id,)
        ).fetchone()
        if row is not None:
            _require_device_owner(row, device_id, task_id)
        attempt = (int(row["attempt_count"] or 0) + 1) if row is not None else 1
        _upsert(
            conn,
            task_id,
            device_id,
            pack_id,
            state=STATE_SENT,
            attempt_count=attempt,
            last_sent_at=now,
            next_attempt_at=now + backoff_after(attempt, DEFAULT_BACKOFF_BASE_S),
            payload_json=json.dumps(payload, ensure_ascii=False) if payload else None,
            updated_at=now,
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def record_abnormal_disconnect(task_id: str, device_id: str, reason: str = "abnormal_disconnect") -> None:
    """异常断开：仅落日志与 last_error，不立即重投（退避已由 next_attempt_at 保证）。"""
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM spine_ota_delivery WHERE task_id = ?", (task_id,)
    ).fetchone()
    if row is None:
        return
    if row["state"] in TERMINAL_STATES:
        return
    if (row["device_id"] or "") != (device_id or ""):
        logger.bind(tag=TAG).warning(
            f"[update_spine] abnormal_disconnect_ignored task_id={task_id} "
            f"device_id={device_id} owner_device_id={row['device_id']} reason=device_mismatch"
        )
        return
    conn.execute(
        "UPDATE spine_ota_delivery SET last_error = ?, updated_at = ? WHERE task_id = ?",
        (reason, time.time(), task_id),
    )
    conn.commit()
    logger.bind(tag=TAG).info(
        f"[update_spine] abnormal_disconnect task_id={task_id} device_id={device_id} "
        f"state={row['state']} attempt_count={row['attempt_count']} "
        f"next_attempt_at={row['next_attempt_at']} reason={reason}"
    )


def cancel_device(device_id: str, reason: str = "manual_cancel") -> List[Dict]:
    """取消指定设备处于可取消状态（queued/sent/accepted/in_progress）的 update_spine。

    仅改状态为 cancelled，不删除；不影响其他设备/命令。
    """
    if not device_id:
        return []
    conn = _get_conn()
    now = time.time()
    placeholders = ",".join("?" for _ in CANCELABLE_STATES)
    rows = conn.execute(
        f"SELECT * FROM spine_ota_delivery WHERE device_id = ? AND state IN ({placeholders})",
        [device_id] + list(CANCELABLE_STATES),
    ).fetchall()
    cancelled: List[Dict] = []
    for row in rows:
        conn.execute(
            "UPDATE spine_ota_delivery SET state = ?, cancelled_at = ?, cancel_reason = ?, "
            "last_error = ?, updated_at = ? WHERE task_id = ?",
            (
                STATE_CANCELLED,
                now,
                reason,
                "E_MANUAL_CANCEL: " + reason,
                now,
                row["task_id"],
            ),
        )
        cancelled.append(dict(row))
    conn.commit()
    for row in cancelled:
        logger.bind(tag=TAG).info(
            f"[update_spine] cancel task_id={row['task_id']} device_id={device_id} "
            f"prev_state={row['state']} new_state=cancelled reason={reason}"
        )
    return cancelled


def _fmt_ts(ts: Optional[float]) -> str:
    if ts is None:
        return ""
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(ts)))
    except Exception:
        return str(ts)


def render_delivery(d: Dict) -> Dict:
    """CLI/日志展示：epoch -> 可读时间。"""
    out = dict(d)
    for k in (
        "last_sent_at",
        "next_attempt_at",
        "accepted_at",
        "completed_at",
        "cancelled_at",
        "created_at",
        "updated_at",
    ):
        if k in out and out[k] is not None:
            out[k] = _fmt_ts(out[k])
    return out
