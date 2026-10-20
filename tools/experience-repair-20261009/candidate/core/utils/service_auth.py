"""manager-api → xiaozhi-server 服务间鉴权（/api/v1/device/send）。

唯一密钥来源：配置键 manager-api.secret
（与 Java manager-api 的 sys_params「server.secret」对齐；Python 侧写入 manager-api.secret）。

禁止回退到 server.auth_key、server.secret、设备鉴权 key、JWT key、默认值或任何第二把 key。
未配置 / 占位 / 空值：fail-closed。
"""

from __future__ import annotations

import hmac
from typing import Any, Mapping, Optional, Tuple

# 唯一允许的配置路径（勿增加第二路径）
SERVICE_SECRET_PATH = ("manager-api", "secret")

FORBIDDEN_QUERY_KEYS = frozenset({"secret", "token", "authorization"})
FORBIDDEN_AUTH_BODY_KEYS = frozenset(
    {"secret", "token", "authorization", "service_secret"}
)
FORBIDDEN_ACCOUNT_BODY_KEYS = frozenset(
    {"user_id", "userId", "account_id", "accountId"}
)
ALLOWED_BUSINESS_BODY_KEYS = frozenset({"device_id", "payload", "session_id"})


def _is_placeholder_secret(value: str) -> bool:
    """中文占位、明显模板值视为未配置。"""
    if not value:
        return True
    if "你" in value:
        return True
    lowered = value.lower()
    if lowered in {"changeme", "change-me", "placeholder", "todo", "xxx"}:
        return True
    return False


def get_service_secret(cfg: Any) -> Tuple[str, str]:
    """读取专用 service-secret。

    Returns:
        (secret, reason_code)
        - secret 非空且 reason 为空：可用
        - secret 为空且 reason 非空：fail-closed（未配置 / 占位等）
    """
    if not isinstance(cfg, Mapping):
        return "", "secret_unconfigured"
    cur: Any = cfg
    for key in SERVICE_SECRET_PATH:
        if not isinstance(cur, Mapping) or key not in cur:
            return "", "secret_unconfigured"
        cur = cur[key]
    if cur is None:
        return "", "secret_unconfigured"
    if not isinstance(cur, str):
        return "", "secret_unconfigured"
    secret = cur.strip()
    if not secret:
        return "", "secret_unconfigured"
    if _is_placeholder_secret(secret):
        return "", "secret_unconfigured"
    return secret, ""


def extract_bearer_token(authorization_header: Optional[str]) -> str:
    """仅从 Authorization 头提取 Bearer token；无则返回空串。"""
    auth = (authorization_header or "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


def verify_bearer_service_secret(presented: str, expected: str) -> bool:
    """常量时间比较；长度不等直接 False（不抛异常、不记录 secret）。"""
    if not presented or not expected:
        return False
    if len(presented) != len(expected):
        return False
    return hmac.compare_digest(presented, expected)


def query_has_forbidden_auth_keys(query_params: Mapping[str, Any]) -> bool:
    """query 出现 secret/token/authorization → 拒绝。"""
    for key in query_params.keys():
        if str(key).lower() in FORBIDDEN_QUERY_KEYS:
            return True
    return False


_AUTH_BODY_LOWER = frozenset(k.lower() for k in FORBIDDEN_AUTH_BODY_KEYS)
_ACCOUNT_BODY_EXACT = FORBIDDEN_ACCOUNT_BODY_KEYS


def body_auth_reject_reason(body: Mapping[str, Any]) -> Optional[str]:
    """body 出现鉴权类字段 → reason；否则 None。"""
    for key in body.keys():
        if str(key).lower() in _AUTH_BODY_LOWER:
            return "auth_in_body"
    return None


def body_has_account_dispatch_keys(body: Mapping[str, Any]) -> bool:
    return any(k in body for k in _ACCOUNT_BODY_EXACT)


def body_has_disallowed_business_keys(body: Mapping[str, Any]) -> bool:
    """除 device_id / payload / session_id 外的业务键一律拒绝（鉴权/账号键另判）。"""
    for key in body.keys():
        kl = str(key).lower()
        if kl in _AUTH_BODY_LOWER or key in _ACCOUNT_BODY_EXACT:
            continue
        if key not in ALLOWED_BUSINESS_BODY_KEYS:
            return True
    return False
