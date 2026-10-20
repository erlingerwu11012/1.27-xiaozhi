"""MCP vision capabilities：HTTPS identity_url / explain_url 与短期 token。

规则：
- url 与 identity_url 必须均为 HTTPS、同一 public host；
- 禁止 localhost / 127.0.0.1 / 裸 HTTP / Docker 内网地址；
- 缺失或不合规时 fail-closed：不下发半成品 identity_url。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

from config.logger import setup_logging
from core.utils.auth import AuthToken

TAG = __name__
logger = setup_logging()

# 禁止作为 public vision host 的主机名
_BLOCKED_HOSTS = frozenset(
    {
        "localhost",
        "127.0.0.1",
        "0.0.0.0",
        "::1",
        "host.docker.internal",
    }
)

_MAX_FACE_IDENTITY_BINDINGS = 32
_MAX_IDENTITY_FIELD_LENGTH = 96


@dataclass
class VisionCapabilityResult:
    ok: bool
    vision: Optional[Dict[str, Any]] = None
    reason: str = ""


def _is_blocked_host(host: str) -> bool:
    h = (host or "").strip().lower().rstrip(".")
    if not h:
        return True
    if h in _BLOCKED_HOSTS:
        return True
    # 典型 Docker / 内网段（保守：仅拦明显内网主机名模式）
    if h.endswith(".internal") or h.endswith(".local"):
        return True
    if h.startswith("10.") or h.startswith("192.168.") or h.startswith("172."):
        # 172.16–31.x.x 私网；简化：172.* 一律视为不可作公网 vision
        return True
    return False


def validate_public_https_url(url: str, *, peer_host: Optional[str] = None) -> Tuple[bool, str]:
    """校验公网 HTTPS URL；若 peer_host 给定则要求 host 一致。"""
    raw = (url or "").strip()
    if not raw:
        return False, "empty_url"
    try:
        parsed = urlparse(raw)
    except Exception:
        return False, "bad_url"
    if parsed.scheme.lower() != "https":
        return False, "not_https"
    host = parsed.hostname or ""
    if _is_blocked_host(host):
        return False, "blocked_host"
    if peer_host and host.lower() != peer_host.lower():
        return False, "host_mismatch"
    if not parsed.path:
        return False, "missing_path"
    return True, "ok"


def resolve_vision_urls(config: dict) -> Tuple[Optional[str], Optional[str], str]:
    """返回 (explain_url, identity_url, reason)。任一不合规则两者都为 None。"""
    server = (config or {}).get("server") or {}
    public_base = (server.get("public_base_url") or "").strip().rstrip("/")

    explain = (server.get("vision_explain") or "").strip()
    identity = (server.get("vision_identity") or "").strip()

    if public_base:
        # 单一公网基址优先生成（仍须 HTTPS）
        if not explain or "你的" in explain:
            explain = f"{public_base}/mcp/vision/explain"
        if not identity:
            identity = f"{public_base}/mcp/vision/identify"

    # 禁止用本地回落拼公网能力
    if "你的" in explain or not explain:
        return None, None, "vision_explain_unconfigured"
    if not identity:
        # 明确禁止从 explain 字符串拼接；必须独立配置或 public_base_url
        return None, None, "vision_identity_unconfigured"

    ok_e, reason_e = validate_public_https_url(explain)
    if not ok_e:
        return None, None, f"explain_{reason_e}"

    explain_host = urlparse(explain).hostname or ""
    ok_i, reason_i = validate_public_https_url(identity, peer_host=explain_host)
    if not ok_i:
        return None, None, f"identity_{reason_i}"

    return explain, identity, "ok"


def build_face_identity_bindings(config: dict) -> list[Dict[str, str]]:
    """Return a bounded device-safe snapshot of explicit face/user bindings."""
    raw_bindings = (config or {}).get("face_identity_bindings")
    if not isinstance(raw_bindings, list):
        return []

    result: list[Dict[str, str]] = []
    seen_profiles: set[str] = set()
    for item in raw_bindings:
        if not isinstance(item, dict):
            continue
        face_profile_id = str(
            item.get("face_profile_id") or item.get("faceProfileId") or ""
        ).strip()
        user_id = str(item.get("user_id") or item.get("userId") or "").strip()
        display_name = str(
            item.get("display_name") or item.get("displayName") or ""
        ).strip()
        if (
            not face_profile_id
            or not user_id
            or not display_name
            or len(face_profile_id) > _MAX_IDENTITY_FIELD_LENGTH
            or len(user_id) > _MAX_IDENTITY_FIELD_LENGTH
            or len(display_name) > _MAX_IDENTITY_FIELD_LENGTH
            or face_profile_id in seen_profiles
        ):
            continue
        seen_profiles.add(face_profile_id)
        result.append(
            {
                "face_profile_id": face_profile_id,
                "user_id": user_id,
                "display_name": display_name,
            }
        )
        if len(result) >= _MAX_FACE_IDENTITY_BINDINGS:
            break
    return result


def build_vision_capabilities(
    config: dict,
    *,
    device_id: str,
    account_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> VisionCapabilityResult:
    """构造 MCP initialize 用的 capabilities.vision；失败则 ok=False。"""
    explain, identity, reason = resolve_vision_urls(config)
    if not explain or not identity:
        logger.bind(tag=TAG).warning(
            f"[vision_capability] fail_closed reason={reason} "
            f"device_id_set={bool(device_id)} account_set={bool(account_id)}"
        )
        return VisionCapabilityResult(ok=False, reason=reason)

    acct = (account_id or "").strip()
    if not acct:
        # account 必须来自可信配置/上下文，禁止静默 default
        face_acct = ((config.get("server") or {}).get("face") or {}).get("account_id")
        acct = (face_acct or "").strip()
    if not acct:
        logger.bind(tag=TAG).warning(
            "[vision_capability] fail_closed reason=account_id_missing"
        )
        return VisionCapabilityResult(ok=False, reason="account_id_missing")

    auth_key = (config.get("server") or {}).get("auth_key") or ""
    if not auth_key:
        return VisionCapabilityResult(ok=False, reason="auth_key_missing")

    device = (device_id or "").strip()
    if not device:
        return VisionCapabilityResult(ok=False, reason="device_id_missing")

    auth = AuthToken(auth_key)
    # 短期 token：绑定 device + account + scope；不在日志中打印
    token = auth.generate_token(
        device,
        account_id=acct,
        scope="vision",
        session_id=session_id or "",
    )
    # 过期时间与 AuthToken 一致（1h）；给出 unix 秒供设备参考
    expires_at = int(time.time()) + 3600

    vision = {
        "url": explain,
        "identity_url": identity,
        "token": token,
        "expires_at": expires_at,
        # Always include the list so a device clears a removed binding on its
        # next MCP initialize.
        "face_identity_bindings": build_face_identity_bindings(config),
    }
    logger.bind(tag=TAG).info(
        f"[vision_capability] issued device_set=1 account_set=1 "
        f"expires_at={expires_at} host_ok=1"
    )
    return VisionCapabilityResult(ok=True, vision=vision, reason="ok")
