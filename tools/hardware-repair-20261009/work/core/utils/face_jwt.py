"""face-api HS256 JWT 统一签发（与 vision / enrollment 对齐）。

载荷必须包含 ver=1、account_id、device_id、iat、exp。
绝不记录 token 明文或 jwt_secret。
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

import jwt

from config.logger import setup_logging

TAG = __name__
logger = setup_logging()

RESERVED_ACCOUNT_IDS = frozenset({"default", "DEFAULT", ""})


def is_reserved_account_id(account_id: Optional[str]) -> bool:
    raw = (account_id or "").strip()
    return (not raw) or raw.lower() == "default"


def build_face_service_jwt(
    *,
    secret: str,
    account_id: str,
    device_id: str,
    ttl_sec: int = 3600,
) -> Optional[str]:
    """签发 face-api 可验证的 JWT；缺参返回 None。"""
    secret = (secret or "").strip()
    account_id = (account_id or "").strip()
    device_id = (device_id or "").strip() or "unknown"
    if not secret or is_reserved_account_id(account_id):
        return None
    now = int(time.time())
    payload: Dict[str, Any] = {
        "ver": 1,
        "account_id": account_id,
        "device_id": device_id,
        "iat": now,
        "exp": now + int(ttl_sec),
    }
    try:
        return jwt.encode(payload, secret, algorithm="HS256")
    except Exception as exc:
        logger.bind(tag=TAG).warning(
            f"[face_jwt] encode_failed err_type={type(exc).__name__}"
        )
        return None


def build_face_jwt_from_config(
    config: dict, *, account_id: str, device_id: str
) -> Optional[str]:
    face_cfg = ((config or {}).get("server") or {}).get("face") or {}
    secret = (face_cfg.get("jwt_secret") or "").strip()
    return build_face_service_jwt(
        secret=secret, account_id=account_id, device_id=device_id
    )
