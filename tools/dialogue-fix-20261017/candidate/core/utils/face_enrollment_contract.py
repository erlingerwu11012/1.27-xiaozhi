"""设备人脸采集 HTTP 契约：稳定 error_code + JSON schema。

固件必须以 error_code / ok 判断状态，不得依赖中文 message。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from aiohttp import web

# 与 capability / face-api 对齐的载荷上限（含 multipart 开销余量）
MAX_FRAME_BYTES = 307200
MAX_MULTIPART_BYTES = MAX_FRAME_BYTES + 64 * 1024  # 边界与字段开销
MIN_IMAGE_SIDE = 64
MAX_IMAGE_SIDE = 4096
MAX_IMAGE_PIXELS = 12_000_000

# 稳定机器码（固件白名单）
ERROR_CODES = frozenset(
    {
        "enrollment_disabled",
        "capability_invalid",
        "enrollment_already_active",
        "session_not_found",
        "session_expired",
        "session_cancelled",
        "session_already_consumed",
        "device_mismatch",
        "account_mismatch",
        "auth_invalid",
        "upload_token_invalid",
        "upload_token_expired",
        "upload_limit_reached",
        "account_draft_quota_exceeded",
        "invalid_content_type",
        "payload_too_large",
        "invalid_jpeg",
        "image_dimensions_invalid",
        "no_face",
        "multiple_faces",
        "face_quality_low",
        "duplicate_frame",
        "enrollment_busy",
        "internal_error",
        "rate_limited",
    }
)

# upstream face-api detail.code → 稳定码
UPSTREAM_CODE_MAP = {
    "session_exists": "enrollment_already_active",
    "not_found": "session_not_found",
    "expired": "session_expired",
    "forbidden": "device_mismatch",
    "already_consumed": "session_already_consumed",
    "quota_exceeded": "account_draft_quota_exceeded",
    "storage_quota": "account_draft_quota_exceeded",
    "too_large": "payload_too_large",
    "bad_jpeg": "invalid_jpeg",
    "no_face": "no_face",
    "multi_face": "multiple_faces",
    "blurry": "face_quality_low",
    "face_too_small": "face_quality_low",
    "quality_abort": "face_quality_low",
    "duplicate": "duplicate_frame",
    "limit": "upload_limit_reached",
    "confirm_in_progress": "enrollment_busy",
    "invalid_status": "enrollment_busy",
    "bad_image": "face_quality_low",
    "bad_device": "device_mismatch",
    "image_dimensions_invalid": "image_dimensions_invalid",
    "invalid_content_type": "invalid_content_type",
}

# 默认 retryable
RETRYABLE = {
    "enrollment_disabled": False,
    "capability_invalid": False,
    "enrollment_already_active": False,
    "session_not_found": False,
    "session_expired": False,
    "session_cancelled": False,
    "session_already_consumed": False,
    "device_mismatch": False,
    "account_mismatch": False,
    "auth_invalid": False,
    "upload_token_invalid": False,
    "upload_token_expired": False,
    "upload_limit_reached": False,
    "account_draft_quota_exceeded": True,
    "invalid_content_type": False,
    "payload_too_large": False,
    "invalid_jpeg": True,
    "image_dimensions_invalid": True,
    "no_face": True,
    "multiple_faces": True,
    "face_quality_low": True,
    "duplicate_frame": True,
    "enrollment_busy": True,
    "internal_error": True,
    "rate_limited": True,
}

# HTTP status 映射
HTTP_STATUS = {
    "auth_invalid": 401,
    "upload_token_invalid": 403,
    "upload_token_expired": 403,
    "device_mismatch": 403,
    "account_mismatch": 403,
    "session_not_found": 404,
    "session_expired": 409,
    "session_cancelled": 409,
    "session_already_consumed": 409,
    "enrollment_already_active": 409,
    "enrollment_busy": 409,
    "payload_too_large": 413,
    "invalid_jpeg": 422,
    "image_dimensions_invalid": 422,
    "no_face": 422,
    "multiple_faces": 422,
    "face_quality_low": 422,
    "duplicate_frame": 422,
    "invalid_content_type": 422,
    "upload_limit_reached": 422,
    "account_draft_quota_exceeded": 429,
    "rate_limited": 429,
    "enrollment_disabled": 503,
    "capability_invalid": 503,
    "internal_error": 500,
}

USER_MESSAGES = {
    "enrollment_disabled": "人脸采集未启用",
    "capability_invalid": "人脸采集配置无效",
    "enrollment_already_active": "已有进行中的采集，请先完成或取消",
    "session_not_found": "采集会话不存在",
    "session_expired": "采集会话已过期",
    "session_cancelled": "采集会话已取消",
    "session_already_consumed": "采集草稿已确认启用",
    "device_mismatch": "设备与会话不匹配",
    "account_mismatch": "账号不匹配",
    "auth_invalid": "设备鉴权失败",
    "upload_token_invalid": "上传凭证无效",
    "upload_token_expired": "上传凭证已过期",
    "upload_limit_reached": "已达到最大采集张数",
    "account_draft_quota_exceeded": "待确认草稿过多，请稍后再试",
    "invalid_content_type": "请上传 JPEG 图片",
    "payload_too_large": "图片过大",
    "invalid_jpeg": "图片格式无效",
    "image_dimensions_invalid": "图片尺寸不符合要求",
    "no_face": "未检测到人脸",
    "multiple_faces": "检测到多张人脸",
    "face_quality_low": "画面质量不足，请重拍或重新开始",
    "duplicate_frame": "与已采集照片过于相似",
    "enrollment_busy": "采集忙碌，请稍后重试",
    "internal_error": "服务内部错误",
    "rate_limited": "请求过于频繁，请稍后再试",
}


@dataclass
class ContractError:
    error_code: str
    http_status: int
    retryable: bool
    message: str


def resolve_error(
    error_code: str,
    *,
    retryable: Optional[bool] = None,
    message: Optional[str] = None,
    http_status: Optional[int] = None,
) -> ContractError:
    code = error_code if error_code in ERROR_CODES else "internal_error"
    return ContractError(
        error_code=code,
        http_status=http_status or HTTP_STATUS.get(code, 500),
        retryable=RETRYABLE.get(code, False) if retryable is None else bool(retryable),
        message=message or USER_MESSAGES.get(code, "错误"),
    )


def map_upstream_code(raw: str) -> str:
    if not raw:
        return "internal_error"
    if raw in ERROR_CODES:
        return raw
    return UPSTREAM_CODE_MAP.get(raw, "internal_error")


def error_body(
    error_code: str,
    *,
    retryable: Optional[bool] = None,
    message: Optional[str] = None,
) -> Dict[str, Any]:
    err = resolve_error(error_code, retryable=retryable, message=message)
    return {
        "ok": False,
        "error_code": err.error_code,
        "retryable": err.retryable,
        "message": err.message,
    }


def error_response(
    error_code: str,
    *,
    retryable: Optional[bool] = None,
    message: Optional[str] = None,
    http_status: Optional[int] = None,
) -> web.Response:
    err = resolve_error(
        error_code, retryable=retryable, message=message, http_status=http_status
    )
    return web.json_response(
        {
            "ok": False,
            "error_code": err.error_code,
            "retryable": err.retryable,
            "message": err.message,
        },
        status=err.http_status,
    )


def ok_response(payload: Dict[str, Any], *, status: int = 200) -> web.Response:
    body = {"ok": True, **payload}
    return web.json_response(body, status=status)
