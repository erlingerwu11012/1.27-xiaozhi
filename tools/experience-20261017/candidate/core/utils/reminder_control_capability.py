"""MCP reminder_control 能力：公网 WSS URL 校验与下发。

不下发 face token / 长期 TTS token / HMAC 密钥；
控制连接复用设备配对 WebSocket 凭证（AuthManager）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

from config.logger import setup_logging
from core.utils.vision_capability import _is_blocked_host

TAG = __name__
logger = setup_logging()

PROTOCOL_VERSION = 1
DEFAULT_CONNECT_TIMEOUT_MS = 3000
DEFAULT_ASSET_WAIT_TIMEOUT_MS = 8000


@dataclass
class ReminderControlCapabilityResult:
    ok: bool
    capability: Optional[Dict[str, Any]] = None
    reason: str = ""


def validate_public_wss_url(url: str, *, peer_host: Optional[str] = None) -> Tuple[bool, str]:
    """校验公网 wss:// URL；禁止 ws:// / localhost / 内网。"""
    raw = (url or "").strip()
    if not raw:
        return False, "empty_url"
    try:
        parsed = urlparse(raw)
    except Exception:
        return False, "bad_url"
    if parsed.scheme.lower() != "wss":
        return False, "not_wss"
    host = parsed.hostname or ""
    if _is_blocked_host(host):
        return False, "blocked_host"
    if peer_host and host.lower() != peer_host.lower():
        return False, "host_mismatch"
    path = (parsed.path or "").rstrip("/")
    if not path:
        return False, "missing_path"
    return True, "ok"


def _https_host(public_base_url: str) -> Optional[str]:
    base = (public_base_url or "").strip()
    if not base.lower().startswith("https://"):
        return None
    try:
        host = urlparse(base).hostname
    except Exception:
        return None
    if not host or _is_blocked_host(host):
        return None
    return host


def resolve_reminder_control_url(config: dict) -> Tuple[Optional[str], str]:
    """解析 reminder-control WSS URL；失败返回 (None, reason)。"""
    server = (config or {}).get("server") or {}
    explicit = (server.get("reminder_control_url") or "").strip()
    public_base = (server.get("public_base_url") or "").strip().rstrip("/")

    if explicit:
        url = explicit
    elif public_base.lower().startswith("https://"):
        # https://host → wss://host/reminder-control（不硬编码端口）
        host_part = public_base[len("https://") :]
        url = f"wss://{host_part}/reminder-control"
    else:
        # 尝试从 websocket 配置推导（必须已是 wss）
        ws = (server.get("websocket") or "").strip()
        if ws.lower().startswith("wss://") and "你" not in ws:
            parsed = urlparse(ws)
            url = f"wss://{parsed.netloc}/reminder-control"
        else:
            return None, "reminder_control_url_unconfigured"

    peer = _https_host(public_base) if public_base else None
    # 若配置了 public_base_url，要求 WSS host 与之一致
    ok, reason = validate_public_wss_url(url, peer_host=peer)
    if not ok:
        return None, reason
    # 若有 public https host，再确认一致（validate 已做）；无 public_base 时仅校验 wss 本身
    return url, "ok"


def build_reminder_control_capability(config: dict) -> ReminderControlCapabilityResult:
    """构造 MCP capabilities.reminder_control；不合规则 ok=False（不下发）。"""
    url, reason = resolve_reminder_control_url(config)
    if not url:
        logger.bind(tag=TAG).warning(
            f"[reminder_control] fail_closed reason={reason}"
        )
        return ReminderControlCapabilityResult(ok=False, reason=reason)

    server = (config or {}).get("server") or {}
    connect_ms = int(
        server.get("reminder_control_connect_timeout_ms") or DEFAULT_CONNECT_TIMEOUT_MS
    )
    wait_ms = int(
        server.get("reminder_control_asset_wait_timeout_ms")
        or DEFAULT_ASSET_WAIT_TIMEOUT_MS
    )
    cap = {
        "url": url,
        "protocol_version": PROTOCOL_VERSION,
        "connect_timeout_ms": connect_ms,
        "asset_wait_timeout_ms": wait_ms,
    }
    logger.bind(tag=TAG).info(
        f"[reminder_control] capability_ok protocol={PROTOCOL_VERSION} "
        f"connect_ms={connect_ms} wait_ms={wait_ms}"
    )
    return ReminderControlCapabilityResult(ok=True, capability=cap, reason="ok")
