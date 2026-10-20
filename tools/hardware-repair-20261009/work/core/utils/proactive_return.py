"""[PROACTIVE_RETURN] 严格系统事件：先问候，再仅询问待办数量。"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

from config.logger import setup_logging
from core.utils.device_outbound import is_outbound_allowed
from core.utils.proactive_greeting import sanitize_verified_display_name

TAG = __name__
MARKER = "[PROACTIVE_RETURN]"
ALLOWED_KEYS = frozenset({"event", "away_seconds", "face_identity", "pending_reminder_count"})


def is_proactive_return_text(text: str) -> bool:
    if not isinstance(text, str):
        return False
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line == MARKER
    return False


def parse_proactive_return(text: str) -> Tuple[bool, Optional[Dict[str, object]], str]:
    if not is_proactive_return_text(text):
        return False, None, "not_marker"
    fields: Dict[str, str] = {}
    started = False
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if not started:
            started = True
            continue
        if "=" not in line:
            return False, None, "invalid_line"
        key, _, value = line.partition("=")
        fields[key.strip()] = value.strip()
    if set(fields) - ALLOWED_KEYS:
        return False, None, "unexpected_fields"
    if fields.get("event") != "stable_user_return":
        return False, None, "invalid_event"
    try:
        away_seconds = int(fields.get("away_seconds", ""))
        pending_count = int(fields.get("pending_reminder_count", ""))
    except (TypeError, ValueError):
        return False, None, "invalid_number"
    if away_seconds < 900 or away_seconds > 31 * 24 * 3600 or pending_count < 0 or pending_count > 10000:
        return False, None, "number_out_of_range"
    raw_face = fields.get("face_identity", "")
    display_name = None if raw_face.lower() in ("", "unknown", "none") else sanitize_verified_display_name(raw_face)
    if raw_face.lower() not in ("", "unknown", "none") and not display_name:
        return False, None, "invalid_face_identity"
    return True, {
        "away_seconds": away_seconds,
        "pending_reminder_count": pending_count,
        "display_name": display_name,
    }, "ok"


def build_return_query(payload: Dict[str, object]) -> str:
    name = str(payload.get("display_name") or "").strip()
    count = int(payload.get("pending_reminder_count") or 0)
    greeting_target = f"已确认的称呼是「{name}」。" if name else "未确认人脸身份，不要编造姓名。"
    return (
        "系统事件：用户在稳定离开至少15分钟后返回。"
        + greeting_target
        + f"未处理待办数量为 {count}。"
        + "请先用一句自然、简短的中文问候；然后仅在数量大于0时询问"
        + f"「您有 {count} 项待办，需要我播报吗？」。"
        + "不得读出任何待办详情，不得完成、取消、稍后或修改提醒，"
        + "不得提及 user_id、账号、设备或内部标识。"
    )


async def handle_proactive_return(conn, text: str) -> bool:
    if not is_proactive_return_text(text):
        return False
    ok, payload, reason = parse_proactive_return(text)
    if not ok:
        conn.logger.bind(tag=TAG).warning(f"[proactive_return] reject reason={reason}")
        return True
    if not is_outbound_allowed(conn):
        return True
    query = build_return_query(payload or {})
    try:
        # 这是内部系统上下文，不能作为 STT 字幕回显到屏幕。
        # 设备只显示 LLM 随后产生的自然问候/询问。
        if not is_outbound_allowed(conn):
            return True
        executor = getattr(conn, "executor", None)
        chat = getattr(conn, "chat", None)
        if executor is not None and callable(chat):
            executor.submit(chat, query)
        elif callable(chat):
            chat(query)
    except Exception as exc:
        conn.logger.bind(tag=TAG).warning(
            f"[proactive_return] dispatch_failed type={type(exc).__name__}"
        )
    return True
