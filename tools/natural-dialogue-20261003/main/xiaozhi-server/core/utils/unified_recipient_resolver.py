"""统一用户提醒接收人：显式用户 > 当前声纹用户 > all。

查询 manager-api 时使用 2 秒超时和 15 秒成功缓存，避免提醒链路阻塞设备会话。
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional, Tuple

import aiohttp

from core.utils.account_identity import resolve_face_account_id
from core.utils.recipient_resolver import (
    ProfileDirectory,
    ProfileRecord,
    RecipientResolution,
    RecipientResultCode,
    extract_recipient_selector_from_text,
    log_recipient_resolution,
    normalize_display_name,
)

_DIRECTORY_CACHE: Dict[Tuple[str, str], Tuple[float, ProfileDirectory]] = {}
_CACHE_TTL_SECONDS = 15.0
_TIMEOUT_SECONDS = 2.0


def _all_resolution() -> RecipientResolution:
    return RecipientResolution(
        code=RecipientResultCode.ALL,
        selector_type="all",
        recipient_person_id="all",
        recipient_display_name="所有人",
        attach_to_device=True,
    )


async def _fetch_directory(config: dict, account_id: str) -> ProfileDirectory:
    manager = (config or {}).get("manager-api") or {}
    base = str(manager.get("url") or "").rstrip("/")
    secret = str(manager.get("secret") or "").strip()
    if not base or not secret or not account_id:
        return ProfileDirectory(account_id=account_id, fetch_error="config_missing")

    cache_key = (base, account_id)
    cached = _DIRECTORY_CACHE.get(cache_key)
    now = time.monotonic()
    if cached and now - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1]

    url = f"{base}/user-identities/device-directory/{account_id}"
    timeout = aiohttp.ClientTimeout(total=_TIMEOUT_SECONDS)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers={"Authorization": f"Bearer {secret}"}) as response:
                if response.status != 200:
                    return ProfileDirectory(account_id=account_id, fetch_error=f"http_{response.status}")
                body = await response.json()
    except Exception:
        return ProfileDirectory(account_id=account_id, fetch_error="network")

    items = body.get("data") if isinstance(body, dict) else None
    if not isinstance(items, list):
        return ProfileDirectory(account_id=account_id, fetch_error="invalid_payload")
    profiles = []
    for item in items:
        if not isinstance(item, dict):
            continue
        user_id = str(item.get("user_id") or item.get("userId") or "").strip()
        display_name = normalize_display_name(item.get("display_name") or item.get("displayName") or "")
        if not user_id or not display_name or str(item.get("status") or "active") != "active":
            continue
        profiles.append(ProfileRecord(
            user_id=user_id,
            display_name=display_name,
            status="active",
            account_id=account_id,
        ))
    directory = ProfileDirectory(account_id=account_id, profiles=profiles)
    _DIRECTORY_CACHE[cache_key] = (now, directory)
    return directory


def _resolve_explicit(directory: ProfileDirectory, selector: str,
                      recipient_user_id: Optional[str]) -> RecipientResolution:
    requested_id = str(recipient_user_id or "").strip()
    if requested_id:
        if requested_id == "all":
            return _all_resolution()
        hit = directory.find_by_user_id(requested_id)
        if hit:
            return RecipientResolution(
                code=RecipientResultCode.RESOLVED,
                selector_type="user_id",
                recipient_person_id=hit.user_id,
                recipient_display_name=hit.display_name,
                attach_to_device=True,
            )
        return RecipientResolution(
            code=RecipientResultCode.NOT_FOUND,
            selector_type="user_id",
            message="未找到该统一用户，请在用户管理页面检查 user_id。",
        )

    target = normalize_display_name(selector)
    matches = directory.find_by_exact_name(target)
    if len(matches) == 1:
        hit = matches[0]
        return RecipientResolution(
            code=RecipientResultCode.RESOLVED,
            selector_type="explicit_name",
            recipient_person_id=hit.user_id,
            recipient_display_name=hit.display_name,
            attach_to_device=True,
        )
    if len(matches) > 1:
        return RecipientResolution(
            code=RecipientResultCode.AMBIGUOUS,
            selector_type="explicit_name",
            message="这个显示名对应多个用户，请使用唯一的显示名或 user_id。",
        )
    return RecipientResolution(
        code=RecipientResultCode.NOT_FOUND,
        selector_type="explicit_name",
        message="未找到该用户，请先在用户管理中创建并绑定身份。",
    )


async def resolve_unified_recipient_for_conn(
    conn,
    *,
    selector: Optional[str] = None,
    recipient_person_id: Optional[str] = None,
    user_text: str = "",
    tool_name: str = "",
) -> RecipientResolution:
    config = getattr(conn, "config", None) or {}
    account_id = str(
        getattr(conn, "account_id", None)
        or resolve_face_account_id(conn=conn, config=config)
        or ""
    ).strip()
    device_id = str(getattr(conn, "device_id", None) or "")
    directory = await _fetch_directory(config, account_id)
    # A failed authenticated lookup must never change a personal request to all.
    if directory.fetch_error and directory.fetch_error != "config_missing":
        resolution = RecipientResolution(
            code=RecipientResultCode.IDENTITY_UNAVAILABLE,
            selector_type="directory_unavailable",
            message="账号身份正在同步，暂时无法创建提醒。",
            error_code="recipient_identity_unavailable",
        )
        log_recipient_resolution(device_id=device_id, account_id=account_id,
                                 resolution=resolution, tool_name=tool_name)
        return resolution
    selected = selector if str(selector or "").strip() else extract_recipient_selector_from_text(user_text)

    # 明确指定（名字或 user_id）优先，名字「爸爸」也按显示名精确匹配，不按关系词猜测。
    if str(recipient_person_id or "").strip():
        resolution = _resolve_explicit(directory, "", recipient_person_id)
    elif selected and normalize_display_name(selected) not in {"我", "自己", "本人", "俺", "咱", "咱们"}:
        resolution = _resolve_explicit(directory, selected, None)
    else:
        current = getattr(conn, "current_speaker_user", None)
        current_user_id = str(current.get("user_id") or "").strip() if isinstance(current, dict) else ""
        if current_user_id:
            # 配置下发只会把 active user_id 写入声纹上下文；目录不可达时仍允许本轮短期上下文。
            display_name = str(current.get("display_name") or "").strip()
            resolution = RecipientResolution(
                code=RecipientResultCode.RESOLVED,
                selector_type="current_speaker_user",
                recipient_person_id=current_user_id,
                recipient_display_name=display_name,
                attach_to_device=True,
            )
        else:
            resolution = _all_resolution()

    log_recipient_resolution(
        device_id=device_id,
        account_id=account_id,
        resolution=resolution,
        tool_name=tool_name,
    )
    return resolution


def apply_unified_recipient_to_device_args(
    arguments: Dict[str, Any], resolution: RecipientResolution
) -> Dict[str, Any]:
    """写入设备 MCP 收件人参数。

    仅下发当前固件 schema 已接受的历史字段 recipient_person_id /
    recipient_display_name；不下发 recipient_user_id（旧固件会
    Unknown argument 拒绝整次 note.add / alarm.set）。
    设备→服务端入站仍可在 reminder_voice / card 路径兼容 recipient_user_id。
    """
    out = dict(arguments or {})
    out.pop("creator_person_id", None)
    out.pop("recipient", None)
    out.pop("recipient_name", None)
    # 禁止向设备双写新字段名（当前固件 schema 不认）
    out.pop("recipient_user_id", None)
    if not resolution.ok_for_create:
        out.pop("recipient_person_id", None)
        out.pop("recipient_display_name", None)
        return out
    recipient_id = str(resolution.recipient_person_id or "").strip()
    out["recipient_person_id"] = recipient_id
    out["recipient_display_name"] = resolution.recipient_display_name or (
        "所有人" if recipient_id == "all" else ""
    )
    return out
