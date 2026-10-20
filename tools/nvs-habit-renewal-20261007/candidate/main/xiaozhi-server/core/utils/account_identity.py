"""账号身份解析：智控台 userId → face account_id；禁止 default / device_id 伪装。

隔离键约定：
- account_id: 字符串化的 manager-api sys_user.id（同一账号多 device 共享）
- usr_*: face profile 人物身份（默认主人 + 可选家人）
- device_id: 设备 MAC，仅用于路由到 current session
- session_id: 单次 WebSocket 连接代际
"""

from __future__ import annotations

import re
from typing import Any, Optional

from core.utils.face_jwt import is_reserved_account_id

# 合法 face account_id（与 face-api SAFE_ACCOUNT_ID 对齐）
SAFE_ACCOUNT_ID = re.compile(r"^[a-zA-Z0-9_\-]{1,64}$")
# 禁止把 MAC / usr_* 当 account
MAC_LIKE = re.compile(r"^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$")
USR_LIKE = re.compile(r"^usr_[A-Za-z0-9]{4,64}$")


def normalize_manager_user_id(raw: Any) -> Optional[str]:
    """将 manager-api userId 规范为 face account_id 字符串。"""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or text in ("0", "None", "null"):
        return None
    if is_reserved_account_id(text):
        return None
    if MAC_LIKE.match(text) or USR_LIKE.match(text):
        return None
    if not SAFE_ACCOUNT_ID.match(text):
        return None
    return text


def resolve_face_account_id(
    *,
    conn=None,
    config: Optional[dict] = None,
    explicit: Optional[str] = None,
    allow_config_fallback: bool = False,
) -> Optional[str]:
    """解析当前请求应使用的 face account_id。

    优先级：
    1. explicit
    2. conn.face_account_id / conn.device_user_id / conn.account_id
       （必须来自设备绑定的智控台 userId，禁止 header/MAC/usr_/default）
    3. 仅当 allow_config_fallback=True 且无 conn 时，才可读 server.face.account_id
       （遗留非设备路径；MCP initialize / 私密提醒禁止走此分支）
    """
    candidates = [
        explicit,
        getattr(conn, "face_account_id", None) if conn is not None else None,
        getattr(conn, "device_user_id", None) if conn is not None else None,
        getattr(conn, "account_id", None) if conn is not None else None,
    ]
    # 有 conn 时禁止配置回退，避免全局 account_id 跨账号污染
    if allow_config_fallback and conn is None:
        cfg = config or {}
        face_cfg = ((cfg.get("server") or {}).get("face") or {})
        candidates.append(face_cfg.get("account_id"))

    for raw in candidates:
        aid = normalize_manager_user_id(raw)
        if aid:
            return aid
    return None


def bind_face_account_on_conn(conn, device_info: Optional[dict]) -> Optional[str]:
    """从 by-mac 设备信息绑定 face_account_id；失败返回 None（fail-closed）。"""
    user_id = None
    if isinstance(device_info, dict):
        user_id = device_info.get("userId") or device_info.get("user_id")
    aid = normalize_manager_user_id(user_id)
    if aid:
        conn.device_user_id = aid
        conn.face_account_id = aid
        # ReminderControl / recipient 也读 account_id
        conn.account_id = aid
    return aid
