"""主动到场问候上行：仅当首个非空行为 [PROACTIVE_GREETING] 时按系统事件处理。

安全规则：
- 标记必须是首个非空行，禁止「文本中包含」即触发；
- 字段白名单校验；no_face 不得带姓名；verified_face 才允许显示名；
- LLM/TTS 前再次确认 current session；出错只记脱敏日志，不关 WebSocket。
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple

from config.logger import setup_logging
from core.utils.device_outbound import is_outbound_allowed

TAG = __name__
logger = setup_logging()

MARKER = "[PROACTIVE_GREETING]"
ALLOWED_EVENTS = frozenset({"stable_person_present"})
ALLOWED_REASONS = frozenset({"arrival", "due_reminder", "due_habit"})
ALLOWED_IDENTITY_MODES = frozenset({"no_face", "verified_face"})
ALLOWED_KEYS = frozenset(
    {
        "event",
        "reason",
        "identity_mode",
        "identity_verified",
        "presence_generation",
        "verified_display_name",
    }
)
MAC_LIKE = re.compile(r"^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$")
USR_LIKE = re.compile(r"^usr_[A-Za-z0-9]{4,64}$")
CTRL_CHARS = re.compile(r"[\x00-\x1f\x7f]")

DEFAULT_PROMPT = (
    "系统事件：有人稳定到场。请用简短自然的中文主动问候。"
    "若提供了已验证称呼可用称呼；若无脸/未验证则不要编造姓名。"
    "不要提及设备号、账号、usr_ 或内部标识。"
)


def is_proactive_greeting_text(text: str) -> bool:
    """仅当首个非空行恰好为标记时视为系统事件。"""
    if not isinstance(text, str):
        return False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        return stripped == MARKER
    return False


def _parse_kv_lines(text: str) -> Dict[str, str]:
    fields: Dict[str, str] = {}
    started = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if not started:
            if stripped != MARKER:
                return {}
            started = True
            continue
        if "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip()
        if key:
            fields[key] = value
    return fields


def sanitize_verified_display_name(raw: Optional[str]) -> Optional[str]:
    """过滤控制字符 / usr_* / MAC / device/account 标识；最长 64。

    若原文含控制字符则直接拒绝（不只是剥离后放行）。
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if CTRL_CHARS.search(text):
        return None
    if not text or len(text) > 64:
        return None
    if USR_LIKE.match(text) or MAC_LIKE.match(text):
        return None
    lowered = text.lower()
    for banned in ("device_id", "device-id", "account_id", "account-id", "session_id"):
        if banned in lowered:
            return None
    if text.startswith("usr_"):
        return None
    return text


def parse_proactive_greeting(text: str) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    """解析并校验主动问候载荷。返回 (ok, payload, reason)。"""
    if not is_proactive_greeting_text(text):
        return False, None, "not_proactive_marker"

    fields = _parse_kv_lines(text)
    extra = set(fields.keys()) - ALLOWED_KEYS
    if extra:
        return False, None, "unexpected_fields"

    event = fields.get("event", "")
    reason = fields.get("reason", "")
    identity_mode = fields.get("identity_mode", "")
    identity_verified_raw = fields.get("identity_verified", "")
    presence_raw = fields.get("presence_generation", "")
    display_raw = fields.get("verified_display_name")

    if event not in ALLOWED_EVENTS:
        return False, None, "invalid_event"
    if reason not in ALLOWED_REASONS:
        return False, None, "invalid_reason"
    if identity_mode not in ALLOWED_IDENTITY_MODES:
        return False, None, "invalid_identity_mode"

    verified_l = identity_verified_raw.lower()
    if verified_l in ("1", "true", "yes"):
        identity_verified = True
    elif verified_l in ("0", "false", "no"):
        identity_verified = False
    else:
        return False, None, "invalid_identity_verified"

    if identity_mode == "no_face" and identity_verified:
        return False, None, "identity_mismatch"
    if identity_mode == "verified_face" and not identity_verified:
        return False, None, "identity_mismatch"

    try:
        presence_generation = int(presence_raw)
    except (TypeError, ValueError):
        return False, None, "invalid_presence_generation"
    if presence_generation <= 0 or presence_generation > 2**31 - 1:
        return False, None, "invalid_presence_generation"

    display_name = None
    if identity_mode == "no_face":
        if display_raw is not None and str(display_raw).strip():
            return False, None, "no_face_must_not_carry_name"
    else:
        display_name = sanitize_verified_display_name(display_raw)
        if display_raw is not None and str(display_raw).strip() and not display_name:
            return False, None, "invalid_display_name"

    payload = {
        "event": event,
        "reason": reason,
        "identity_mode": identity_mode,
        "identity_verified": identity_verified,
        "presence_generation": presence_generation,
        "verified_display_name": display_name,
    }
    return True, payload, "ok"


def build_proactive_greeting_query(conn, payload: Dict[str, Any]) -> str:
    """从 server.proactive_greeting_prompt 构造 LLM 输入（唯一可配置项）。"""
    config = getattr(conn, "config", None) or {}
    server = (config.get("server") or {}) if isinstance(config, dict) else {}
    prompt = (server.get("proactive_greeting_prompt") or "").strip() or DEFAULT_PROMPT

    parts = [
        prompt,
        f"reason={payload.get('reason')}",
        f"identity_mode={payload.get('identity_mode')}",
    ]
    if payload.get("identity_mode") == "verified_face" and payload.get(
        "verified_display_name"
    ):
        parts.append(f"verified_display_name={payload['verified_display_name']}")
    else:
        parts.append("verified_display_name=")
    parts.append(f"presence_generation={payload.get('presence_generation')}")
    return "\n".join(parts)


def can_dispatch_private_device_reminder(conn) -> bool:
    """私密提醒下发门禁：必须有绑定 userId，且未 superseded / 身份未失败。"""
    if conn is None:
        return False
    if getattr(conn, "superseded", False):
        return False
    aid = (
        getattr(conn, "face_account_id", None)
        or getattr(conn, "device_user_id", None)
        or getattr(conn, "account_id", None)
    )
    if not aid or str(aid).strip() in ("", "default"):
        return False
    if getattr(conn, "face_identity_ready", None) is False:
        return False
    return True


async def handle_proactive_greeting(conn, text: str) -> bool:
    """处理主动问候。

    返回 True 表示已消费（合法或非法标记均吞掉），调用方勿再当普通 ASR。
    LLM/TTS 异常只记脱敏日志，绝不关闭 WebSocket。
    """
    if not is_proactive_greeting_text(text):
        return False

    ok, payload, reason = parse_proactive_greeting(text)
    if not ok:
        logger.bind(tag=TAG).warning(
            f"[proactive_greeting] reject reason={reason} "
            f"device_id={getattr(conn, 'device_id', None)} "
            f"session_id={getattr(conn, 'session_id', None)}"
        )
        return True

    if not is_outbound_allowed(conn):
        logger.bind(tag=TAG).info(
            f"[proactive_greeting] skip reason=stale_connection "
            f"device_id={getattr(conn, 'device_id', None)} "
            f"session_id={getattr(conn, 'session_id', None)}"
        )
        return True

    query = build_proactive_greeting_query(conn, payload or {})
    try:
        if not is_outbound_allowed(conn):
            logger.bind(tag=TAG).info(
                f"[proactive_greeting] skip reason=stale_before_llm "
                f"device_id={getattr(conn, 'device_id', None)} "
                f"session_id={getattr(conn, 'session_id', None)}"
            )
            return True
        # 主动问候的系统上下文不作为用户语音字幕回显。
        if not is_outbound_allowed(conn):
            return True
        executor = getattr(conn, "executor", None)
        chat_fn = getattr(conn, "chat", None)
        if executor is not None and callable(chat_fn):
            executor.submit(chat_fn, query)
        elif callable(chat_fn):
            chat_fn(query)
    except Exception as exc:
        logger.bind(tag=TAG).error(
            f"[proactive_greeting] llm_tts_failed err_type={type(exc).__name__} "
            f"device_id={getattr(conn, 'device_id', None)} "
            f"session_id={getattr(conn, 'session_id', None)}"
        )
    return True
