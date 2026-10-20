"""向 manager-api 查询设备 WSS auth state（服务间 Bearer）。

建连鉴权默认不缓存 active 状态：每次握手读最新持久化结果，避免解绑后放行窗口。
失败 / 超时 / 不完整 → 调用方 fail-closed。
绝不记录 token / secret / Authorization。
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# 仅允许显式 opt-in 的极短负向/调试缓存；鉴权路径必须 use_cache=False
_CACHE_TTL_SEC = 0.0
_cache: Dict[str, Tuple[float, "DeviceWsAuthState"]] = {}


@dataclass(frozen=True)
class DeviceWsAuthState:
    device_id: str
    credential_version: int
    status: str  # active|unbound|disabled
    updated_at_epoch_sec: Optional[int] = None
    legacy_revoked_before_iat: Optional[int] = None


class AuthStateUnavailable(Exception):
    """状态查询失败 / 超时 / 不完整。"""


def invalidate_auth_state_cache(device_id: str) -> None:
    """按规范化或原始 device_id 失效缓存（不解绑其他设备）。"""
    if not device_id:
        return
    keys = {
        device_id,
        device_id.strip().lower(),
        device_id.strip().lower().replace(":", "").replace("-", ""),
    }
    for k in keys:
        _cache.pop(k, None)


def clear_auth_state_cache() -> None:
    _cache.clear()


def _normalize(device_id: str) -> str:
    return (device_id or "").strip().lower().replace(":", "").replace("-", "")


async def fetch_device_ws_auth_state(
    device_id: str,
    *,
    timeout_sec: float = 3.0,
    use_cache: bool = False,
) -> DeviceWsAuthState:
    """GET /device/ws-auth/{mac}；成功返回状态，否则抛 AuthStateUnavailable。

    默认 use_cache=False：WSS 建连不得依赖可能放行已吊销 token 的正缓存。
    """
    normalized = _normalize(device_id)
    if not normalized or len(normalized) != 12:
        raise AuthStateUnavailable("invalid_device_id")

    if use_cache and _CACHE_TTL_SEC > 0:
        hit = _cache.get(normalized)
        if hit and hit[0] > time.monotonic():
            return hit[1]

    try:
        from config.manage_api_client import ManageApiClient

        client = ManageApiClient._instance
        if client is None:
            raise AuthStateUnavailable("client_uninitialized")
    except Exception as e:
        raise AuthStateUnavailable(f"client_error:{type(e).__name__}") from e

    endpoint = f"device/ws-auth/{normalized}"
    try:
        data = await asyncio.wait_for(
            client.request("GET", endpoint),
            timeout=timeout_sec,
        )
    except asyncio.TimeoutError as e:
        raise AuthStateUnavailable("timeout") from e
    except Exception as e:
        raise AuthStateUnavailable(f"request_failed:{type(e).__name__}") from e

    state = _parse_state(data, expected_device=normalized)
    if use_cache and _CACHE_TTL_SEC > 0:
        _cache[normalized] = (time.monotonic() + _CACHE_TTL_SEC, state)
    return state


def _parse_state(data: Any, *, expected_device: str) -> DeviceWsAuthState:
    if not isinstance(data, dict):
        raise AuthStateUnavailable("incomplete")
    status = (data.get("status") or "").strip()
    raw_ver = data.get("credentialVersion")
    if raw_ver is None:
        raw_ver = data.get("credential_version")
    try:
        cred_ver = int(raw_ver)
    except (TypeError, ValueError):
        raise AuthStateUnavailable("incomplete")
    if status not in ("active", "unbound", "disabled") or cred_ver <= 0:
        raise AuthStateUnavailable("incomplete")
    did = _normalize(str(data.get("deviceId") or data.get("device_id") or expected_device))
    if did and did != expected_device:
        raise AuthStateUnavailable("device_mismatch")
    updated = data.get("updatedAtEpochSec")
    if updated is None:
        updated = data.get("updated_at_epoch_sec")
    try:
        updated_i = int(updated) if updated is not None else None
    except (TypeError, ValueError):
        updated_i = None
    legacy = data.get("legacyRevokedBeforeIat")
    if legacy is None:
        legacy = data.get("legacy_revoked_before_iat")
    try:
        legacy_i = int(legacy) if legacy is not None else None
    except (TypeError, ValueError):
        legacy_i = None
    return DeviceWsAuthState(
        device_id=expected_device,
        credential_version=cred_ver,
        status=status,
        updated_at_epoch_sec=updated_i,
        legacy_revoked_before_iat=legacy_i,
    )


def map_status_to_auth_code(status: str) -> str:
    if status == "unbound":
        return "device_unbound"
    if status == "disabled":
        return "device_disabled"
    return "credential_revoked"
