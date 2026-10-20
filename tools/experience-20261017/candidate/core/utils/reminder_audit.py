"""提醒/语音链路结构化审计日志。不记录正文、Token、图片、embedding。"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, Optional

from config.logger import setup_logging

TAG = __name__
logger = setup_logging()


def audit_event(
    event: str,
    *,
    session_id: str = "",
    device_id: str = "",
    account_id: str = "",
    correlation_id: str = "",
    tool_call_id: str = "",
    instance_id: str = "",
    revision: Any = None,
    voice_revision: Any = None,
    creator_person_id: str = "",
    recipient_person_id: str = "",
    result_code: str = "",
    latency_ms: Optional[float] = None,
    extra: Optional[Dict[str, Any]] = None,
    prefix: str = "[reminder_audit]",
):
    payload: Dict[str, Any] = {
        "event": event,
        "session_id": session_id or "",
        "device_id": device_id or "",
        "account_id": account_id or "",
        "correlation_id": correlation_id or session_id or "",
        "tool_call_id": tool_call_id or "",
        "instance_id": instance_id or "",
        "revision": revision,
        "voice_revision": voice_revision,
        "creator_person_id": creator_person_id or "",
        "recipient_person_id": recipient_person_id or "",
        "result_code": result_code or "",
        "latency_ms": latency_ms,
        "ts": int(time.time()),
    }
    if extra:
        # 仅允许非敏感元数据
        for k, v in extra.items():
            if k in (
                "phase",
                "bytes",
                "format",
                "script_len",
                "reason",
                "selector_type",
                "dedup",
                "expires_at",
                "script_path",
                "received_at",
                "expires_at_clipped",
                "tool_family",
                "tool",
                "action",
                "tts_state",
            ):
                payload[k] = v
    logger.bind(tag=TAG).info(f"{prefix} {json.dumps(payload, ensure_ascii=False)}")


def _safe_str(val, fallback: str = "") -> str:
    try:
        from unittest.mock import Mock

        if isinstance(val, Mock):
            return fallback
    except ImportError:
        pass
    if val is None:
        return fallback
    return str(val)


def conn_ids(conn) -> Dict[str, str]:
    device_id = _safe_str(getattr(conn, "device_id", None))
    if not device_id and getattr(conn, "headers", None):
        device_id = _safe_str(conn.headers.get("device-id", ""))
    session_id = _safe_str(getattr(conn, "session_id", ""))
    face_cfg = ((getattr(conn, "config", None) or {}).get("server") or {}).get("face") or {}
    account_id = _safe_str(face_cfg.get("account_id") or "")
    if not account_id:
        account_id = _safe_str(getattr(conn, "account_id", None) or "")
    correlation_id = _safe_str(getattr(conn, "correlation_id", ""), session_id)
    return {
        "device_id": device_id or "",
        "session_id": session_id,
        "account_id": account_id,
        "correlation_id": correlation_id,
    }
