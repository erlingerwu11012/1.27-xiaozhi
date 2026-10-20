"""HTTP：短期签名的 reminder-voice 下载（真实 Device-Id 头绑定）。

校验顺序：
1. 独立 signing key 存在
2. asset_id / query 字段合法
3. HTTP Device-Id 头存在且合法
4. Device-Id 头 == 签名 query 中的 device_id
5. HMAC(asset_id, device_id, exp) 正确且未过期
6. 资产存在且归属 device（及可选 account）一致

仅成功时返回 OGG；拒绝日志不含完整 query / token / 正文。
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

from aiohttp import web

from config.logger import setup_logging
from core.utils.reminder_voice_store import (
    get_reminder_voice_signing_key,
    get_voice_store,
    redact_asset_id,
    verify_signed_request,
)

TAG = __name__
logger = setup_logging()

# 设备 ID：MAC 或常见固件标识；禁止空白与控制字符
_DEVICE_ID_RE = re.compile(r"^[A-Za-z0-9:_\-.]{4,64}$")
_ASSET_ID_RE = re.compile(r"^[a-fA-F0-9]{16,64}$")


def _log_reject(reason: str, asset_id: str = "", header_device_set: bool = False) -> None:
    logger.bind(tag=TAG).warning(
        f"[reminder_voice_download] reject reason={reason} "
        f"asset={redact_asset_id(asset_id)} device_hdr={int(header_device_set)}"
    )


def normalize_device_id(raw: Optional[str]) -> str:
    return (raw or "").strip()


def is_valid_device_id(device_id: str) -> bool:
    if not device_id:
        return False
    if not _DEVICE_ID_RE.match(device_id):
        return False
    # 拒绝明显占位
    low = device_id.lower()
    if low in ("null", "undefined", "unknown", "none"):
        return False
    return True


class ReminderVoiceHandler:
    def __init__(self, config: dict):
        self.config = config
        self.logger = setup_logging()

    def _secret(self) -> str:
        # 仅独立密钥；无 auth_key / face jwt 回退
        return get_reminder_voice_signing_key(self.config)

    def _configured_account_id(self) -> str:
        face = ((self.config.get("server") or {}).get("face") or {})
        return (face.get("account_id") or "").strip()

    async def handle_get(self, request: web.Request) -> web.Response:
        asset_id = (request.match_info.get("asset_id") or "").strip()
        exp = request.rel_url.query.get("exp", "")
        sig = request.rel_url.query.get("sig", "")
        # 签名中的 device_id（query）
        signed_device_id = normalize_device_id(
            request.rel_url.query.get("device_id")
        )
        # 真实设备绑定：HTTP 头 Device-Id（固件下载时携带）
        header_device_id = normalize_device_id(
            request.headers.get("Device-Id")
            or request.headers.get("device-id")
            or ""
        )
        header_set = bool(header_device_id)
        secret = self._secret()

        if not secret:
            _log_reject("signing_key_missing", asset_id, header_set)
            return web.Response(status=503, text="unavailable")

        if not asset_id or not _ASSET_ID_RE.match(asset_id):
            _log_reject("bad_asset_id", asset_id, header_set)
            return web.Response(status=404, text="not found")

        if not header_device_id:
            _log_reject("missing_device_id_header", asset_id, False)
            return web.Response(status=401, text="unauthorized")

        if not is_valid_device_id(header_device_id):
            _log_reject("invalid_device_id_header", asset_id, True)
            return web.Response(status=401, text="unauthorized")

        if not signed_device_id or not is_valid_device_id(signed_device_id):
            _log_reject("invalid_signed_device_id", asset_id, True)
            return web.Response(status=403, text="forbidden")

        if header_device_id != signed_device_id:
            _log_reject("device_id_mismatch", asset_id, True)
            return web.Response(status=403, text="forbidden")

        item = get_voice_store().get(asset_id)
        if not item:
            _log_reject("asset_not_found_or_expired", asset_id, True)
            return web.Response(status=404, text="not found")

        if not verify_signed_request(
            secret=secret,
            asset_id=asset_id,
            device_id=signed_device_id,
            exp=exp,
            sig=sig,
            expected_device_id=item.device_id,
        ):
            _log_reject("bad_signature_or_expired", asset_id, True)
            return web.Response(status=403, text="forbidden")

        if item.device_id != header_device_id:
            _log_reject("asset_device_mismatch", asset_id, True)
            return web.Response(status=403, text="forbidden")

        cfg_account = self._configured_account_id()
        if cfg_account and item.account_id and item.account_id != cfg_account:
            _log_reject("account_mismatch", asset_id, True)
            return web.Response(status=403, text="forbidden")

        # 成功：仅返回 OGG，不写敏感日志
        logger.bind(tag=TAG).info(
            f"[reminder_voice_download] ok asset={redact_asset_id(asset_id)} "
            f"bytes={len(item.data)}"
        )
        return web.Response(
            body=item.data,
            content_type=item.content_type or "audio/ogg",
            headers={
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )
