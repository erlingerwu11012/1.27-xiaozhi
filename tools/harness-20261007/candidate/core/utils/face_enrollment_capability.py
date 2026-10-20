"""MCP face_enrollment capability：公网 HTTPS session_url + 独立上传签名密钥。

仅 Guided Burst V2：protocol_version=2、guided_burst_v1=true、
session_url .../session（singular）。Fail-closed，不下发 V1。

静态字段：session_url / protocol / frames 限制（不依赖 account）。
动态字段（enrolled_count / default_owner_person_id）：仅在已认证 conn
成功拉取 face-api identity-snapshot 后附加；失败则缺省（固件保持 unknown）。

禁止复用 auth_key / FACE_JWT_SECRET；不下发任何密钥。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

import aiohttp

from config.logger import setup_logging
from core.utils.account_identity import resolve_face_account_id
from core.utils.device_outbound import is_outbound_allowed
from core.utils.face_jwt import build_face_jwt_from_config, is_reserved_account_id
from core.utils.vision_capability import _is_blocked_host, validate_public_https_url
from core.utils.face_enrollment_v2 import is_front_only_allowed, is_user_relative_allowed

TAG = __name__
logger = setup_logging()

# 遗留常量名保留；capability 实际以下发 V2 为准（见 face_enrollment_v2）
PROTOCOL_VERSION = 2
SESSION_TIMEOUT_SECONDS = 240
REQUIRED_FRAMES = 3
MAX_FRAMES = 3
MAX_FRAME_BYTES = 307200
MIN_UPLOAD_SIGNING_KEY_LEN = 32
USR_ID_RE = re.compile(r"^usr_[A-Za-z0-9]{4,64}$")


@dataclass
class FaceEnrollmentCapabilityResult:
    ok: bool
    capability: Optional[Dict[str, Any]] = None
    reason: str = ""


@dataclass
class IdentitySnapshotResult:
    ok: bool
    enrolled_count: Optional[int] = None
    default_owner_person_id: Optional[str] = None
    reason: str = ""


def get_face_enrollment_upload_signing_key(
    config: Optional[dict] = None,
) -> Tuple[str, str]:
    """返回 (key, reason)。reason 非空表示不可用。不回退 auth_key / FACE JWT。

    绝不在日志中输出密钥或其摘要。
    """
    env_key = (os.environ.get("FACE_ENROLLMENT_UPLOAD_SIGNING_KEY") or "").strip()
    cfg_key = ""
    auth_key = ""
    face_jwt = ""
    if config:
        server = (config.get("server") or {})
        cfg_key = (server.get("face_enrollment_upload_signing_key") or "").strip()
        auth_key = (server.get("auth_key") or "").strip()
        face_jwt = ((server.get("face") or {}).get("jwt_secret") or "").strip()

    key = env_key or cfg_key
    if not key:
        return "", "upload_signing_key_missing"
    if len(key) < MIN_UPLOAD_SIGNING_KEY_LEN:
        return "", "upload_signing_key_too_short"
    if auth_key and key == auth_key:
        logger.bind(tag=TAG).error(
            "[FACE_ENROLL] upload_signing_key_must_not_equal_auth_key"
        )
        return "", "upload_signing_key_reuses_auth_key"
    if face_jwt and key == face_jwt:
        logger.bind(tag=TAG).error(
            "[FACE_ENROLL] upload_signing_key_must_not_equal_face_jwt"
        )
        return "", "upload_signing_key_reuses_face_jwt"
    return key, ""


def resolve_enrollment_session_url(config: dict) -> Tuple[Optional[str], str]:
    """解析设备 enrollment session_url（V2 singular）。

    历史名保留；实现委托 resolve_v2_session_url（含 WSS host 一致性校验）。
    """
    from core.utils.face_enrollment_v2 import resolve_v2_session_url

    return resolve_v2_session_url(config)


def build_face_enrollment_capability(config: dict) -> FaceEnrollmentCapabilityResult:
    """静态 enrollment 能力：始终 Guided Burst V2。Fail-closed，不下发 V1。"""
    from core.utils.face_enrollment_v2 import (
        PROTOCOL_VERSION_V2,
        build_v2_capability_payload,
        resolve_v2_session_url,
    )

    url, reason = resolve_v2_session_url(config)
    if not url:
        logger.bind(tag=TAG).warning(
            f"[FACE_ENROLL] capability fail_closed reason={reason}"
        )
        return FaceEnrollmentCapabilityResult(ok=False, reason=reason)

    server = (config or {}).get("server") or {}
    if not (server.get("auth_key") or "").strip():
        return FaceEnrollmentCapabilityResult(ok=False, reason="auth_key_missing")

    _, key_reason = get_face_enrollment_upload_signing_key(config)
    if key_reason:
        logger.bind(tag=TAG).warning(
            f"[FACE_ENROLL] capability fail_closed reason={key_reason}"
        )
        return FaceEnrollmentCapabilityResult(ok=False, reason=key_reason)

    cap = build_v2_capability_payload(config, url)
    logger.bind(tag=TAG).info(
        f"[FACE_ENROLL] capability_ok protocol={PROTOCOL_VERSION_V2}"
    )
    return FaceEnrollmentCapabilityResult(ok=True, capability=cap, reason="ok")


def _identity_snapshot_url(config: dict) -> Optional[str]:
    face_cfg = ((config or {}).get("server") or {}).get("face") or {}
    identify_url = (face_cfg.get("identify_url") or "").strip()
    if not identify_url:
        return None
    base = identify_url.rstrip("/")
    if base.endswith("/face/identify"):
        return base[: -len("/face/identify")] + "/face/accounts/identity-snapshot"
    if "/face/" in base:
        root = base.split("/face/", 1)[0]
        return root + "/face/accounts/identity-snapshot"
    return base + "/face/accounts/identity-snapshot"


def _mask_usr(uid: str) -> str:
    raw = (uid or "").strip()
    if len(raw) <= 8:
        return "usr_***"
    return raw[:7] + "***"


def _validate_snapshot_payload(data: Any) -> IdentitySnapshotResult:
    if not isinstance(data, dict):
        return IdentitySnapshotResult(ok=False, reason="invalid_payload")
    if not isinstance(data.get("default_owner_person_id"), str):
        return IdentitySnapshotResult(ok=False, reason="invalid_owner")
    owner = data["default_owner_person_id"].strip()
    if owner and (not USR_ID_RE.match(owner) or is_reserved_account_id(owner)):
        return IdentitySnapshotResult(ok=False, reason="invalid_owner")
    # 字段必须显式存在（禁止缺省冒充 count=0）
    if "enrolled_count" not in data:
        return IdentitySnapshotResult(ok=False, reason="count_missing")
    try:
        count = int(data["enrolled_count"])
    except (TypeError, ValueError):
        return IdentitySnapshotResult(ok=False, reason="invalid_count")
    if count < 0:
        return IdentitySnapshotResult(ok=False, reason="invalid_count")
    return IdentitySnapshotResult(
        ok=True,
        enrolled_count=count,
        default_owner_person_id=owner,
        reason="ok",
    )


async def fetch_identity_capability_snapshot(
    conn,
    *,
    account_id: str,
    device_id: str,
    capture_session_id: str,
) -> IdentitySnapshotResult:
    """向 face-api 拉取原子身份快照。失败 fail-closed（不伪造 count=0）。"""
    if not account_id or is_reserved_account_id(account_id):
        return IdentitySnapshotResult(ok=False, reason="account_unavailable")
    config = getattr(conn, "config", None) or {}
    url = _identity_snapshot_url(config)
    if not url:
        return IdentitySnapshotResult(ok=False, reason="snapshot_url_missing")
    token = build_face_jwt_from_config(
        config, account_id=account_id, device_id=device_id or "device"
    )
    if not token:
        return IdentitySnapshotResult(ok=False, reason="jwt_unavailable")

    face_cfg = ((config.get("server") or {}).get("face") or {})
    timeout = aiohttp.ClientTimeout(total=float(face_cfg.get("timeout", 2.0)))
    headers = {"Authorization": f"Bearer {token}"}
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            # account_id 仅在 Face JWT 中；body/query/额外 header 不得携带 account_id
            async with session.post(url, headers=headers, data=b"") as resp:
                if resp.status not in (200, 201):
                    logger.bind(tag=TAG).warning(
                        f"[FACE_ENROLL] identity_snapshot_http={resp.status} "
                        f"device={_mask_device(device_id)} session_prefix="
                        f"{(capture_session_id or '')[:8]}"
                    )
                    return IdentitySnapshotResult(
                        ok=False, reason=f"http_{resp.status}"
                    )
                data = await resp.json()
    except Exception as exc:
        logger.bind(tag=TAG).warning(
            f"[FACE_ENROLL] identity_snapshot_failed err_type={type(exc).__name__}"
        )
        return IdentitySnapshotResult(ok=False, reason="network")

    # 返回后：旧连接不得再写入 capability
    if getattr(conn, "session_id", None) != capture_session_id:
        return IdentitySnapshotResult(ok=False, reason="session_changed")
    if not is_outbound_allowed(conn):
        return IdentitySnapshotResult(ok=False, reason="session_stale")

    result = _validate_snapshot_payload(data)
    owner_ok = bool(result.ok and result.default_owner_person_id)
    logger.bind(tag=TAG).info(
        f"[FACE_ENROLL] identity_snapshot account_ok=1 "
        f"enrolled_count={result.enrolled_count if result.ok else 'n/a'} "
        f"owner_usr_ok={1 if owner_ok else 0} "
        f"device={_mask_device(device_id)} session_prefix={(capture_session_id or '')[:8]} "
        f"reason={result.reason}"
    )
    return result


def _mask_device(device_id: str) -> str:
    raw = (device_id or "").strip()
    if len(raw) < 8:
        return "***"
    return raw[:2] + "..." + raw[-2:]


def merge_identity_into_face_enrollment(
    capability: Dict[str, Any], snapshot: IdentitySnapshotResult
) -> Dict[str, Any]:
    """仅在快照成功时附加动态字段；失败则保持静态字段、两字段缺失。"""
    out = dict(capability or {})
    # 确保不会残留伪造字段
    out.pop("enrolled_count", None)
    out.pop("default_owner_person_id", None)
    if not snapshot.ok:
        return out
    if snapshot.enrolled_count is None:
        return out
    if snapshot.default_owner_person_id and not USR_ID_RE.match(snapshot.default_owner_person_id):
        return out
    out["enrolled_count"] = int(snapshot.enrolled_count)
    out["default_owner_person_id"] = snapshot.default_owner_person_id
    return out


async def build_face_enrollment_capability_for_conn(
    conn,
) -> FaceEnrollmentCapabilityResult:
    """基于已认证 conn 组装 V2 capability：静态 +（可选）动态身份字段。"""
    config = getattr(conn, "config", None) or {}
    static = build_face_enrollment_capability(config)
    if not static.ok or not static.capability:
        return static

    capture_session = getattr(conn, "session_id", None) or ""
    device_id = getattr(conn, "device_id", None) or ""
    if getattr(conn, "headers", None) and not device_id:
        device_id = conn.headers.get("device-id") or ""

    account_id = resolve_face_account_id(conn=conn, config=config) or ""
    if not account_id:
        try:
            conn.face_identity_ready = False
        except Exception:
            pass
        logger.bind(tag=TAG).info(
            f"[FACE_ENROLL] identity_skip reason=account_unavailable "
            f"device={_mask_device(device_id)} session_prefix={capture_session[:8]}"
        )
        return FaceEnrollmentCapabilityResult(
            ok=True,
            capability=dict(static.capability),
            reason="ok_static_only",
        )

    snapshot = await fetch_identity_capability_snapshot(
        conn,
        account_id=account_id,
        device_id=device_id,
        capture_session_id=capture_session,
    )
    # 二次确认 session（网络与合并之间）
    if getattr(conn, "session_id", None) != capture_session or not is_outbound_allowed(
        conn
    ):
        try:
            conn.face_identity_ready = False
        except Exception:
            pass
        logger.bind(tag=TAG).info(
            f"[FACE_ENROLL] identity_skip reason=session_stale_before_merge "
            f"device={_mask_device(device_id)} session_prefix={capture_session[:8]}"
        )
        return FaceEnrollmentCapabilityResult(
            ok=True,
            capability=dict(static.capability),
            reason="ok_static_only",
        )

    merged = merge_identity_into_face_enrollment(static.capability, snapshot)
    if is_front_only_allowed(config, account_id, device_id):
        merged = dict(merged)
        merged["supported_capture_modes"] = [
            "guided_burst_v1",
            "front_only_v1",
        ]
        try:
            conn.face_enrollment_front_only = True
        except Exception:
            pass
    if is_user_relative_allowed(config, account_id, device_id):
        # user_relative_v1 指导能力：仅名单内账号/设备下发；默认关闭。
        merged = dict(merged)
        merged["supported_guidance_profiles"] = ["user_relative_v1"]
        try:
            conn.face_enrollment_user_relative = True
        except Exception:
            pass
    ready = (
        "enrolled_count" in merged and "default_owner_person_id" in merged
    )
    try:
        conn.face_identity_ready = bool(ready)
    except Exception:
        pass
    if not ready:
        logger.bind(tag=TAG).info(
            f"[FACE_ENROLL] identity_skip reason={getattr(snapshot, 'reason', 'snapshot_failed')} "
            f"device={_mask_device(device_id)} session_prefix={capture_session[:8]}"
        )

    return FaceEnrollmentCapabilityResult(
        ok=True, capability=merged, reason="ok"
    )


def validate_face_enrollment_signing_at_startup(config: dict) -> None:
    """生产或已配公网 HTTPS 时，缺独立签名密钥则 fail-closed（生产抛错）。"""
    server = (config or {}).get("server") or {}
    public_base = (server.get("public_base_url") or "").strip()
    env = (
        (os.environ.get("XIAOZHI_ENV") or "")
        or (os.environ.get("FACE_ENV") or "")
        or (server.get("env") or "")
    ).strip().lower()
    is_prod = env in ("production", "prod")
    needs_key = is_prod or public_base.lower().startswith("https://")

    key, reason = get_face_enrollment_upload_signing_key(config)
    if key:
        logger.bind(tag=TAG).info(
            "[FACE_ENROLL] upload_signing_key_ok source=independent"
        )
        return

    if not needs_key:
        logger.bind(tag=TAG).warning(
            f"[FACE_ENROLL] upload_signing_key unavailable ({reason or 'missing'}); "
            "capability/session disabled"
        )
        return

    msg = (
        "[FACE_ENROLL] fail_closed upload_signing_key; "
        "set FACE_ENROLLMENT_UPLOAD_SIGNING_KEY or "
        "server.face_enrollment_upload_signing_key "
        "(min length 32; must not reuse auth_key / FACE_JWT_SECRET)"
    )
    logger.bind(tag=TAG).error(msg)
    if is_prod:
        raise RuntimeError(
            "FACE_ENROLLMENT_UPLOAD_SIGNING_KEY required in production"
        )
