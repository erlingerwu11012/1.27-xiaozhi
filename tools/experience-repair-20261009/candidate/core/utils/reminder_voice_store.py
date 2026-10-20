"""提醒语音资产：短期签名下载 + TTL 清理。

URL 形态：
  {public_base_url}/reminder-voice/{asset_id}?exp=...&device_id=...&sig=...

签名密钥：独立 REMINDER_VOICE_SIGNING_KEY / server.reminder_voice_signing_key，
不得复用 auth_key 或 FACE_JWT_SECRET。
签名绑定：asset_id + device_id + expiry。
"""

from __future__ import annotations

import hashlib
import hmac
import os
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Dict, Optional, Tuple
from urllib.parse import urlencode

from config.logger import setup_logging

TAG = __name__
logger = setup_logging()

MAX_ASSET_BYTES = 16 * 1024  # 16 KiB
DEFAULT_TTL_SEC = 300


@dataclass
class VoiceAsset:
    asset_id: str
    data: bytes
    sha256: str
    content_type: str
    created_at: float
    expires_at: float
    device_id: str
    account_id: str


class ReminderVoiceStore:
    """进程内短期资产仓；不长期公开保存。"""

    def __init__(self, ttl_sec: int = DEFAULT_TTL_SEC):
        self._ttl = int(ttl_sec)
        self._lock = threading.RLock()
        self._items: Dict[str, VoiceAsset] = {}

    def put(
        self,
        data: bytes,
        *,
        device_id: str,
        account_id: str,
        content_type: str = "audio/ogg",
    ) -> VoiceAsset:
        if not data or len(data) > MAX_ASSET_BYTES:
            raise ValueError("asset_size_invalid")
        digest = hashlib.sha256(data).hexdigest()
        asset_id = uuid.uuid4().hex
        now = time.time()
        item = VoiceAsset(
            asset_id=asset_id,
            data=data,
            sha256=digest,
            content_type=content_type,
            created_at=now,
            expires_at=now + self._ttl,
            device_id=device_id or "",
            account_id=account_id or "",
        )
        with self._lock:
            self._cleanup_unlocked(now)
            self._items[asset_id] = item
        return item

    def get(self, asset_id: str) -> Optional[VoiceAsset]:
        now = time.time()
        with self._lock:
            self._cleanup_unlocked(now)
            item = self._items.get(asset_id)
            if not item:
                return None
            if item.expires_at < now:
                self._items.pop(asset_id, None)
                return None
            return item

    def discard(self, asset_id: str) -> None:
        with self._lock:
            self._items.pop(asset_id, None)

    def _cleanup_unlocked(self, now: float) -> None:
        expired = [k for k, v in self._items.items() if v.expires_at < now]
        for k in expired:
            self._items.pop(k, None)
        if expired:
            logger.bind(tag=TAG).info(
                f"[reminder_voice] store_cleanup removed={len(expired)}"
            )


_STORE: Optional[ReminderVoiceStore] = None
_STORE_LOCK = threading.Lock()


def get_voice_store() -> ReminderVoiceStore:
    global _STORE
    with _STORE_LOCK:
        if _STORE is None:
            _STORE = ReminderVoiceStore()
        return _STORE


def get_reminder_voice_signing_key(config: Optional[dict] = None) -> str:
    """独立签名密钥；禁止回退到 auth_key / face jwt。"""
    env_key = (os.environ.get("REMINDER_VOICE_SIGNING_KEY") or "").strip()
    if env_key:
        # 防御：若有人误把 FACE_JWT_SECRET 同名注入，仍只认本 env 名
        return env_key
    if config:
        server = (config.get("server") or {})
        key = (server.get("reminder_voice_signing_key") or "").strip()
        if key:
            # 显式禁止把 auth_key / jwt_secret 字段当作本密钥
            auth_key = (server.get("auth_key") or "").strip()
            face_jwt = ((server.get("face") or {}).get("jwt_secret") or "").strip()
            if auth_key and key == auth_key:
                logger.bind(tag=TAG).error(
                    "[reminder_voice] signing_key_must_not_equal_auth_key"
                )
                return ""
            if face_jwt and key == face_jwt:
                logger.bind(tag=TAG).error(
                    "[reminder_voice] signing_key_must_not_equal_face_jwt"
                )
                return ""
            return key
    return ""


def redact_asset_id(asset_id: str) -> str:
    aid = (asset_id or "").strip()
    if len(aid) < 8:
        return "***"
    return f"{aid[:4]}...{aid[-4:]}"


def can_issue_reminder_voice_urls(config: Optional[dict] = None) -> Tuple[bool, str]:
    """签发前置：必须有独立 signing key + https public_base。"""
    secret = get_reminder_voice_signing_key(config)
    if not secret:
        return False, "signing_key_missing"
    server = (config or {}).get("server") or {}
    base = (server.get("public_base_url") or "").strip().rstrip("/")
    if not base.lower().startswith("https://"):
        return False, "public_base_url_not_https"
    return True, "ok"


def validate_reminder_voice_signing_at_startup(config: dict) -> None:
    """启动预检：生产或已配置公网 HTTPS 时，缺独立密钥则 fail-closed 日志。

    不退出进程（避免误伤本地开发），但会标记禁用签发；
    若 XIAOZHI_ENV/FACE_ENV=production 则抛错阻止启动。
    """
    server = (config or {}).get("server") or {}
    public_base = (server.get("public_base_url") or "").strip()
    env = (
        (os.environ.get("XIAOZHI_ENV") or "")
        or (os.environ.get("FACE_ENV") or "")
        or (server.get("env") or "")
    ).strip().lower()
    is_prod = env in ("production", "prod")
    needs_key = is_prod or public_base.lower().startswith("https://")

    secret = get_reminder_voice_signing_key(config)
    if secret:
        logger.bind(tag=TAG).info(
            "[reminder_voice] signing_key_ok source=independent"
        )
        return

    if not needs_key:
        logger.bind(tag=TAG).warning(
            "[reminder_voice] signing_key_missing; url_issue_disabled"
        )
        return

    msg = (
        "[reminder_voice] fail_closed signing_key_missing; "
        "set REMINDER_VOICE_SIGNING_KEY or server.reminder_voice_signing_key "
        "(must not reuse auth_key / FACE_JWT_SECRET)"
    )
    logger.bind(tag=TAG).error(msg)
    if is_prod:
        raise RuntimeError(
            "REMINDER_VOICE_SIGNING_KEY required in production"
        )


def _sign(secret: str, asset_id: str, device_id: str, exp: int) -> str:
    msg = f"{asset_id}:{device_id}:{exp}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()


def build_signed_url(
    *,
    public_base_url: str,
    secret: str,
    asset_id: str,
    device_id: str,
    ttl_sec: int = DEFAULT_TTL_SEC,
) -> Tuple[str, int]:
    base = (public_base_url or "").rstrip("/")
    if not base.lower().startswith("https://"):
        raise ValueError("public_base_url_not_https")
    if not secret:
        raise ValueError("signing_key_missing")
    if not device_id:
        raise ValueError("device_id_missing")
    exp = int(time.time()) + int(ttl_sec)
    sig = _sign(secret, asset_id, device_id, exp)
    qs = urlencode(
        {"exp": str(exp), "device_id": device_id, "sig": sig}
    )
    return f"{base}/reminder-voice/{asset_id}?{qs}", exp


def verify_signed_request(
    *,
    secret: str,
    asset_id: str,
    device_id: str,
    exp: str,
    sig: str,
    expected_device_id: Optional[str] = None,
) -> bool:
    """校验签名；device 不符或过期均拒绝。"""
    if not secret or not asset_id or not device_id:
        return False
    if expected_device_id and device_id != expected_device_id:
        return False
    try:
        exp_i = int(exp)
    except (TypeError, ValueError):
        return False
    if exp_i < int(time.time()):
        return False
    expect = _sign(secret, asset_id, device_id, exp_i)
    return hmac.compare_digest(expect, (sig or "").strip())
