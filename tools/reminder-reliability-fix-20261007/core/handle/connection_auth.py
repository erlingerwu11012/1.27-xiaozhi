"""WSS / Reminder-Control 共用：设备 token 校验 + 鉴权失败 JSON 协议。"""

from __future__ import annotations

import json
from typing import Optional

from core.auth import AUTH_ERROR_CODES, AuthenticationError, AuthManager, TokenClaims
from core.utils.device_ws_auth_state import (
    AuthStateUnavailable,
    fetch_device_ws_auth_state,
    map_status_to_auth_code,
)

WS_AUTH_CLOSE_CODE = 1008


async def verify_device_ws_token(
    auth_manager: AuthManager,
    *,
    token: str,
    device_id: str,
    client_id: Optional[str] = None,
) -> TokenClaims:
    """本地验签 + 持久化 auth-state（v1/v2 均查）；失败抛 AuthenticationError(code)。

    每次握手强制拉取最新状态（不缓存），避免解绑后正缓存放行窗口。
    """
    claims, status = auth_manager.parse_and_verify(token, username=device_id)
    if status != "ok" or claims is None:
        raise AuthenticationError(status)

    try:
        state = await fetch_device_ws_auth_state(
            device_id, timeout_sec=3.0, use_cache=False
        )
    except AuthStateUnavailable:
        raise AuthenticationError("auth_state_unavailable") from None

    if state.status != "active":
        raise AuthenticationError(map_status_to_auth_code(state.status))

    if claims.version == "v1":
        # 迁移窗口：HMAC/exp/device_id 已通过；须未触碰 legacy 吊销边界
        boundary = state.legacy_revoked_before_iat
        if boundary is not None and int(claims.iat) <= int(boundary):
            raise AuthenticationError("credential_revoked")
        _ = client_id
        return claims

    # v2：credential_version 必须与持久化一致
    if claims.credential_version is None or int(claims.credential_version) != int(
        state.credential_version
    ):
        raise AuthenticationError("credential_revoked")

    _ = client_id
    return claims


async def send_auth_error_and_close(websocket, code: str) -> None:
    """先发合法 JSON error，再 close(1008, reason=短枚举)。不发送明文。"""
    err = code if code in AUTH_ERROR_CODES else "invalid_token"
    payload = json.dumps(
        {"type": "error", "code": err},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    try:
        await websocket.send(payload)
    except Exception:
        pass
    try:
        await websocket.close(code=WS_AUTH_CLOSE_CODE, reason=err)
    except Exception:
        try:
            await websocket.close()
        except Exception:
            pass
