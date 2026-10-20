"""Guided Burst V2：URL 防护、guidance allowlist、无 message 错误体。

V2 为唯一协议；feature-flag/allowlist 桩函数始终放行。
失败响应不得含中文 message / TTS / 图片内容。
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Set, Tuple
from urllib.parse import urlparse
import os

from aiohttp import web

from core.utils.reminder_control_capability import validate_public_wss_url
from core.utils.vision_capability import _is_blocked_host, validate_public_https_url

PROTOCOL_VERSION_V2 = 2
V2_SESSION_TIMEOUT_SECONDS = 240
# 仅用于网关→face-api 创建时的传输/时钟余量；不写入 capability
V2_CREATE_TIMEOUT_SLACK_SECONDS = 5
V2_REQUIRED_FRAMES = 3
V2_MAX_FRAMES = 3
V2_MAX_FRAME_BYTES = 307200
# 三张候选 + multipart 开销（不得误用 V1 单图上限）
V2_MAX_CAPTURE_MULTIPART_BYTES = V2_MAX_FRAME_BYTES * 3 + 128 * 1024
# create JSON 体上限（chunked/普通共用）；远大于合法 create 体，防放大
V2_CREATE_JSON_MAX_BYTES = 16 * 1024
UPLOAD_TOKEN_SCOPE_V2 = "enrollment_upload_v2"
CAPTURE_MODE_GUIDED_BURST_V1 = "guided_burst_v1"
CAPTURE_MODE_FRONT_ONLY_V1 = "front_only_v1"
FRONT_ONLY_REQUIRED_FRAMES = 1
FRONT_ONLY_MAX_FRAMES = 1
# 指导能力协商：user_relative_v1 仅配合 front_only_v1；未协商则沿用旧 MOVE_SCREEN_* 语义。
GUIDANCE_PROFILE_USER_RELATIVE_V1 = "user_relative_v1"
# 仅 user_relative_v1 会话可用的方向状态码；旧会话收到即契约错误。
USER_RELATIVE_ONLY_GUIDANCE = frozenset({"MOVE_USER_LEFT", "MOVE_USER_RIGHT"})

# draft_ready 字段缺失（非显式 false/null）；仅用于旧协议缺省兼容
DRAFT_READY_FIELD_MISSING = object()
# create 请求真正空体（无字节/仅空白）；与 JSON null 区分
CREATE_JSON_BODY_EMPTY = object()

# create 时钉住的会话完成条件；assess/capture 不得用矛盾字段改写
_SESSION_POLICY: Dict[str, Tuple[str, int]] = {}
# create 时钉住的指导 profile（user_relative_v1 或 None）；assess/capture 不得改写
_SESSION_GUIDANCE_PROFILE: Dict[str, str] = {}


def remember_session_policy(
    session_id: str, capture_mode: str, required_frames: int
) -> None:
    sid = (session_id or "").strip()
    if not sid:
        return
    _SESSION_POLICY[sid] = (capture_mode, int(required_frames))


def get_session_policy(session_id: str) -> Optional[Tuple[str, int]]:
    return _SESSION_POLICY.get((session_id or "").strip())


def remember_session_guidance_profile(
    session_id: str, guidance_profile: Optional[str]
) -> None:
    sid = (session_id or "").strip()
    if not sid:
        return
    if guidance_profile is None:
        _SESSION_GUIDANCE_PROFILE.pop(sid, None)
    else:
        _SESSION_GUIDANCE_PROFILE[sid] = guidance_profile


def get_session_guidance_profile(session_id: str) -> Optional[str]:
    return _SESSION_GUIDANCE_PROFILE.get((session_id or "").strip())


def clear_session_policy(session_id: str) -> None:
    _SESSION_POLICY.pop((session_id or "").strip(), None)
    _SESSION_GUIDANCE_PROFILE.pop((session_id or "").strip(), None)


def reset_session_policies_for_tests() -> None:
    _SESSION_POLICY.clear()
    _SESSION_GUIDANCE_PROFILE.clear()


def validate_guidance_code_for_profile(
    guidance_code: Any, guidance_profile: Optional[str]
) -> bool:
    """user_relative 专属状态码只能在已协商 user_relative_v1 的会话出现。

    旧会话收到 MOVE_USER_LEFT/RIGHT 视为契约错误（返回 False，调用方转 internal_error）。
    """
    c = str(guidance_code or "").strip().upper()
    if c in USER_RELATIVE_ONLY_GUIDANCE:
        return guidance_profile == GUIDANCE_PROFILE_USER_RELATIVE_V1
    return True


def resolve_guidance_mode_fields(
    session_id: str,
    body: Dict[str, Any],
) -> Tuple[Optional[str], Optional[int], Optional[int], Optional[str]]:
    """以 create 钉住的模式为准校验 assess/capture 上游体。

    返回 (capture_mode, required_frames, max_frames, error)。
    上游不得用矛盾字段改写会话完成条件。
    """
    stored = get_session_policy(session_id)
    up_mode = body.get("capture_mode")
    if up_mode is None or up_mode is False:
        up_mode_norm = CAPTURE_MODE_GUIDED_BURST_V1
    elif type(up_mode) is not str:
        return None, None, None, "capture_mode_invalid"
    else:
        up_mode_norm = up_mode.strip() or CAPTURE_MODE_GUIDED_BURST_V1

    if stored is not None:
        mode, req = stored
        if up_mode_norm != mode:
            return None, None, None, "capture_mode_mismatch"
        up_req = body.get("required_frames")
        if up_req is not None:
            if type(up_req) is not int or isinstance(up_req, bool) or up_req != req:
                return None, None, None, "required_frames_mismatch"
        up_max = body.get("max_frames")
        if up_max is not None:
            if type(up_max) is not int or isinstance(up_max, bool) or up_max != req:
                return None, None, None, "max_frames_mismatch"
        return mode, req, req, None

    # 进程重启等未钉住：仍严格解析上游，不得静默改写
    mode, req, err = resolve_session_frame_limits(
        capture_mode=body.get("capture_mode"),
        required_frames=body.get("required_frames"),
        max_frames=body.get("max_frames"),
    )
    if err or mode is None or req is None:
        return None, None, None, err or "invalid_capture_mode"
    return mode, req, req, None


GUIDANCE_CODES: frozenset = frozenset(
    {
        "START",
        "NO_FACE",
        "MOVE_SCREEN_LEFT",
        "MOVE_SCREEN_RIGHT",
        "MOVE_USER_LEFT",
        "MOVE_USER_RIGHT",
        "MOVE_UP",
        "MOVE_DOWN",
        "MOVE_CLOSER",
        "MOVE_BACK",
        "FACE_FORWARD",
        "TOO_DARK",
        "MULTIPLE_FACES",
        "HOLD_STILL",
        "ALIGN_READY",
        "CAPTURE_FRONT",
        "CAPTURE_LEFT",
        "CAPTURE_RIGHT",
        "RECAPTURE_FRONT",
        "RECAPTURE_LEFT",
        "RECAPTURE_RIGHT",
        "UPLOADING",
        "DRAFT_READY",
        "POSE_FAILED",
        "TIMEOUT",
        "CANCELLED",
        "SERVICE_ERROR",
    }
)

V2_ERROR_CODES = frozenset(
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
        "invalid_pose",
        "invalid_round",
        "enrollment_busy",
        "internal_error",
        "rate_limited",
        "v2_not_allowed",
        "invalid_capture_mode",
        "capture_mode_not_allowed",
        "invalid_guidance_profile",
        "guidance_profile_not_allowed",
    }
)

V2_RETRYABLE = {
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
    "invalid_pose": False,
    "invalid_round": False,
    "enrollment_busy": True,
    "internal_error": True,
    "rate_limited": True,
    "v2_not_allowed": False,
    "invalid_capture_mode": False,
    "capture_mode_not_allowed": False,
    "invalid_guidance_profile": False,
    "guidance_profile_not_allowed": False,
}

V2_HTTP_STATUS = {
    "auth_invalid": 401,
    "upload_token_invalid": 403,
    "upload_token_expired": 403,
    "device_mismatch": 403,
    "account_mismatch": 403,
    "v2_not_allowed": 403,
    "session_not_found": 404,
    "session_expired": 409,
    "session_cancelled": 409,
    "session_already_consumed": 409,
    "enrollment_already_active": 409,
    "enrollment_busy": 409,
    "payload_too_large": 413,
    "invalid_jpeg": 422,
    "image_dimensions_invalid": 422,
    "invalid_content_type": 422,
    "invalid_pose": 422,
    "invalid_round": 422,
    "upload_limit_reached": 422,
    "account_draft_quota_exceeded": 429,
    "rate_limited": 429,
    "enrollment_disabled": 503,
    "capability_invalid": 503,
    "internal_error": 500,
    "invalid_capture_mode": 400,
    "capture_mode_not_allowed": 403,
    "invalid_guidance_profile": 400,
    "guidance_profile_not_allowed": 403,
}

V2_UPSTREAM_CODE_MAP = {
    "session_exists": "enrollment_already_active",
    "not_found": "session_not_found",
    "expired": "session_expired",
    "cancelled": "session_cancelled",
    "forbidden": "device_mismatch",
    "already_consumed": "session_already_consumed",
    "quota_exceeded": "account_draft_quota_exceeded",
    "storage_quota": "account_draft_quota_exceeded",
    "too_large": "payload_too_large",
    "bad_jpeg": "invalid_jpeg",
    "image_dimensions_invalid": "image_dimensions_invalid",
    "invalid_content_type": "invalid_content_type",
    "invalid_pose": "invalid_pose",
    "invalid_round": "invalid_round",
    "confirm_in_progress": "enrollment_busy",
    "invalid_status": "enrollment_busy",
    "bad_device": "device_mismatch",
    "not_guided_burst": "enrollment_busy",
    "pose_failed": "session_cancelled",
    "invalid_capture_mode": "invalid_capture_mode",
    "capture_mode_not_allowed": "capture_mode_not_allowed",
    "invalid_guidance_profile": "invalid_guidance_profile",
    "guidance_profile_not_allowed": "guidance_profile_not_allowed",
}


def is_allowed_guidance_code(code: Any) -> bool:
    """仅当 code 精确属于 allowlist 时为 True；未知字符串不得伪装。"""
    c = str(code or "").strip().upper()
    return c in GUIDANCE_CODES


def sanitize_guidance_code(code: Any) -> Optional[str]:
    """已知 code 原样返回；未知返回 None（调用方应转 internal_error）。"""
    c = str(code or "").strip().upper()
    if c in GUIDANCE_CODES:
        return c
    return None


def parse_accepted_count(
    raw: Any, *, max_count: int = V2_REQUIRED_FRAMES
) -> Optional[int]:
    """严格解析 accepted_count：仅真正的 int，范围 0..max_count。

    拒绝 bool（bool 是 int 子类）、float、数字字符串、null、容器。
    不使用 int() 截断/转换，不 clamp。
    """
    if type(raw) is not int:
        return None
    # 防御：若未来改用 isinstance，bool 仍须拒绝
    if isinstance(raw, bool):
        return None
    if raw < 0 or raw > int(max_count):
        return None
    return raw


def parse_draft_ready(raw: Any) -> Tuple[Optional[bool], Optional[str]]:
    """解析 draft_ready。返回 (value_or_None_if_missing, error)。

    - DRAFT_READY_FIELD_MISSING → (None, None) 表示缺省，由调用方按契约补全。
    - 真正的 bool True/False → (True/False, None)。
    - 其它类型（含 null、字符串、0/1）→ (None, error)。
    """
    if raw is DRAFT_READY_FIELD_MISSING:
        return None, None
    if raw is True:
        return True, None
    if raw is False:
        return False, None
    return None, "draft_ready_invalid"


def resolve_session_frame_limits(
    *,
    capture_mode: Any = None,
    required_frames: Any = None,
    max_frames: Any = None,
) -> Tuple[Optional[str], Optional[int], Optional[str]]:
    """解析会话帧数契约。返回 (mode, required_frames, error)。

    - 缺省/空 capture_mode → 旧三姿态 guided_burst_v1，required=3。
    - front_only_v1：required_frames 若提供则必须是真正的 int 1；错误值拒绝，不静默改成 1。
    - 未知模式拒绝。
    """
    if capture_mode is None or capture_mode is False:
        mode = CAPTURE_MODE_GUIDED_BURST_V1
    elif type(capture_mode) is not str:
        return None, None, "invalid_capture_mode"
    else:
        mode = capture_mode.strip()
        if not mode:
            mode = CAPTURE_MODE_GUIDED_BURST_V1

    if mode == CAPTURE_MODE_FRONT_ONLY_V1:
        if required_frames is not None:
            if type(required_frames) is not int or isinstance(required_frames, bool):
                return None, None, "required_frames_invalid"
            if required_frames != FRONT_ONLY_REQUIRED_FRAMES:
                return None, None, "required_frames_mismatch"
        if max_frames is not None:
            if type(max_frames) is not int or isinstance(max_frames, bool):
                return None, None, "max_frames_invalid"
            if max_frames != FRONT_ONLY_MAX_FRAMES:
                return None, None, "max_frames_mismatch"
        return mode, FRONT_ONLY_REQUIRED_FRAMES, None

    if mode == CAPTURE_MODE_GUIDED_BURST_V1:
        if required_frames is not None:
            if type(required_frames) is not int or isinstance(required_frames, bool):
                return None, None, "required_frames_invalid"
            if required_frames != V2_REQUIRED_FRAMES:
                return None, None, "required_frames_mismatch"
        if max_frames is not None:
            if type(max_frames) is not int or isinstance(max_frames, bool):
                return None, None, "max_frames_invalid"
            if max_frames != V2_MAX_FRAMES:
                return None, None, "max_frames_mismatch"
        return mode, V2_REQUIRED_FRAMES, None

    return None, None, "invalid_capture_mode"


def build_v2_guidance_payload(
    *,
    session_id: str,
    guidance_code: Any,
    accepted_count: Any,
    draft_ready: Any = DRAFT_READY_FIELD_MISSING,
    capture_mode: Any = None,
    required_frames: Any = None,
    max_frames: Any = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """构造 V2 成功 guidance 体。

    返回 (payload, error_code)。error_code 非空表示不得返回 ok:true。
    - 未知 guidance → internal_error（不伪装成 SERVICE_ERROR 成功体）
    - accepted_count 必须是真正 int；拒绝 float/字符串/bool；不截断不 clamp
    - draft_ready 若存在必须是真正 bool；拒绝字符串/0/1/null
    - 缺省 draft_ready（字段缺失）：DRAFT_READY 且 count==req 时可推断完成；
      显式 False/null/非法类型不得推断
    - DRAFT_READY + 显式 False → 拒绝（不得改写成成功）
    - draft_ready=True + 非 DRAFT_READY → 拒绝
    - front_only 矛盾 required_frames → internal_error（不静默改成 1）
    """
    raw_code = str(guidance_code or "").strip().upper()
    if not is_allowed_guidance_code(raw_code):
        return None, "internal_error"
    mode, req, lim_err = resolve_session_frame_limits(
        capture_mode=capture_mode,
        required_frames=required_frames,
        max_frames=max_frames,
    )
    if lim_err or mode is None or req is None:
        return None, "internal_error"
    count = parse_accepted_count(accepted_count, max_count=req)
    if count is None:
        return None, "internal_error"

    ready_parsed, ready_err = parse_draft_ready(draft_ready)
    if ready_err:
        return None, "internal_error"

    if ready_parsed is None:
        # 字段缺失：仅 DRAFT_READY + 达标 count 推断完成；否则未完成
        if raw_code == "DRAFT_READY":
            if count != req:
                return None, "internal_error"
            ready = True
        else:
            ready = False
    else:
        ready = ready_parsed
        if ready:
            if raw_code != "DRAFT_READY" or count != req:
                return None, "internal_error"
        elif raw_code == "DRAFT_READY":
            # 显式矛盾：不得改写为成功
            return None, "internal_error"

    return (
        {
            "session_id": session_id,
            "guidance_code": raw_code,
            "accepted_count": count,
            "draft_ready": ready,
        },
        None,
    )


def is_v2_feature_enabled(config: Optional[dict]) -> bool:
    """V2 恒开启（遗留桩；忽略配置 flag）。"""
    return True


def v2_allowlist(config: Optional[dict]) -> Set[str]:
    """遗留桩：返回空集（调用方应以 is_device_allowed_for_v2 为准）。"""
    return set()


def is_device_allowed_for_v2(config: Optional[dict], device_id: str) -> bool:
    """V2 恒允许任意非空 device_id（遗留桩；不再读 allowlist）。"""
    return bool((device_id or "").strip())


def resolve_device_wss_host(config: Optional[dict]) -> Tuple[Optional[str], str]:
    """解析设备主 WSS host；缺失/非 wss/内网 → fail-closed。"""
    server = (config or {}).get("server") or {}
    ws = (server.get("websocket") or "").strip()
    if not ws or "你" in ws:
        return None, "wss_missing"
    ok, reason = validate_public_wss_url(ws)
    if not ok:
        return None, f"wss_{reason}"
    try:
        host = urlparse(ws).hostname
    except Exception:
        return None, "wss_bad_url"
    if not host or _is_blocked_host(host):
        return None, "wss_blocked_host"
    return host.lower(), "ok"


def resolve_v2_session_url(config: Optional[dict]) -> Tuple[Optional[str], str]:
    """V2 session_url：仅由 public_base_url 推导；host 必须与 WSS host 一致。

    不允许另配外部 V2 host。
    """
    server = (config or {}).get("server") or {}
    public_base = (server.get("public_base_url") or "").strip().rstrip("/")
    if not public_base:
        return None, "enrollment_url_unconfigured"
    if not public_base.lower().startswith("https://"):
        return None, "not_https"

    try:
        https_host = urlparse(public_base).hostname
    except Exception:
        return None, "bad_url"
    if not https_host or _is_blocked_host(https_host):
        return None, "blocked_host"

    wss_host, wss_reason = resolve_device_wss_host(config)
    if not wss_host:
        return None, wss_reason
    if https_host.lower() != wss_host:
        return None, "host_mismatch"

    url = f"{public_base}/mcp/face-enrollment/session"
    ok, reason = validate_public_https_url(url, peer_host=wss_host)
    if not ok:
        return None, reason
    return url, "ok"


def build_v2_capability_payload(config: dict, session_url: str) -> Dict[str, Any]:
    return {
        "protocol_version": PROTOCOL_VERSION_V2,
        "guided_burst_v1": True,
        "session_url": session_url,
        "session_timeout_seconds": V2_SESSION_TIMEOUT_SECONDS,
        "required_frames": V2_REQUIRED_FRAMES,
        "max_frames": V2_MAX_FRAMES,
        "max_frame_bytes": V2_MAX_FRAME_BYTES,
    }


def _norm_device(device_id: str) -> str:
    return (device_id or "").strip().lower()


def parse_strict_bool(value: Any) -> Optional[bool]:
    """严格布尔：仅 True/False 或明确真假字符串；非法值返回 None（调用方安全拒绝）。

    不使用 bool(value)：bool(\"false\") 为 True，会误开开关。
    """
    if value is None:
        return None
    if value is True:
        return True
    if value is False:
        return False
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        # 拒绝 1/0 宽松数字，避免 YAML/JSON 混用掩盖配置错误
        return None
    if isinstance(value, str):
        s = value.strip().lower()
        if s in ("1", "true", "yes", "on"):
            return True
        if s in ("0", "false", "no", "off"):
            return False
        return None
    return None


def _parse_allowlist_items(raw: Any) -> Optional[list]:
    """解析名单。返回 list[(account, device)]；raw 类型非法时返回 None。"""
    if raw is None:
        return None
    if isinstance(raw, str):
        items = []
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            if "|" not in part:
                continue
            acc, dev = part.split("|", 1)
            acc, dev = acc.strip(), _norm_device(dev)
            if acc and dev:
                items.append((acc, dev))
        return items
    if not isinstance(raw, list):
        return None
    out = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        acc = str(item.get("account_id") or "").strip()
        dev = _norm_device(str(item.get("device_id") or ""))
        if acc and dev:
            out.append((acc, dev))
    return out


def is_front_only_enabled(config: Optional[dict]) -> bool:
    """正面单模板开关。

    - 字段存在且严格为 false → 关闭（环境变量不能打开）。
    - 字段存在且严格为 true → 打开。
    - 字段存在但非法 → 安全关闭。
    - 字段不存在 → 才读 FACE_ENROLLMENT_FRONT_ONLY。
    """
    server = (config or {}).get("server") or {}
    if "face_enrollment_front_only_enabled" in server:
        parsed = parse_strict_bool(server.get("face_enrollment_front_only_enabled"))
        return parsed is True
    env = (os.environ.get("FACE_ENROLLMENT_FRONT_ONLY") or "").strip().lower()
    return env in ("1", "true", "yes", "on")


def is_front_only_allowed(
    config: Optional[dict], account_id: str, device_id: str
) -> bool:
    """全局可用：开关开启即对所有账号/设备放行，不再按名单匹配。

    身份认证、限流、用户绑定仍在调用方（face_enrollment_handler /
    face_enrollment_capability）执行，不受此处影响。
    """
    return is_front_only_enabled(config)


def user_relative_allowlist(config: Optional[dict]) -> list:
    """返回获准 user_relative_v1 的 (account_id, device_id) 列表。

    优先级与 front_only 相同：字段存在（含显式 []）→ 只用配置；否则读环境变量。
    """
    server = (config or {}).get("server") or {}
    if "face_enrollment_user_relative_allowlist" in server:
        parsed = _parse_allowlist_items(
            server.get("face_enrollment_user_relative_allowlist")
        )
        return parsed if parsed is not None else []
    env_raw = (os.environ.get("FACE_ENROLLMENT_USER_RELATIVE_ALLOWLIST") or "").strip()
    if not env_raw:
        return []
    parsed = _parse_allowlist_items(env_raw)
    return parsed if parsed is not None else []


def is_user_relative_enabled(config: Optional[dict]) -> bool:
    """用户本人左右方向指导开关（默认关闭）。

    - 字段存在且严格 false → 关闭（环境变量不能打开）。
    - 字段存在且严格 true → 打开。
    - 字段存在但非法 → 安全关闭。
    - 字段不存在 → 读 FACE_ENROLLMENT_USER_RELATIVE。
    """
    server = (config or {}).get("server") or {}
    if "face_enrollment_user_relative_enabled" in server:
        parsed = parse_strict_bool(
            server.get("face_enrollment_user_relative_enabled")
        )
        return parsed is True
    env = (os.environ.get("FACE_ENROLLMENT_USER_RELATIVE") or "").strip().lower()
    return env in ("1", "true", "yes", "on")


def is_user_relative_allowed(
    config: Optional[dict], account_id: str, device_id: str
) -> bool:
    """user_relative_v1 须开关开启且账号/设备同时匹配名单；缺一不可。"""
    if not is_user_relative_enabled(config):
        return False
    acc = (account_id or "").strip()
    dev = _norm_device(device_id)
    if not acc or not dev:
        return False
    return any(acc == a and dev == d for a, d in user_relative_allowlist(config))


def v2_error_body(
    error_code: str, *, retryable: Optional[bool] = None
) -> Dict[str, Any]:
    code = error_code if error_code in V2_ERROR_CODES else "internal_error"
    return {
        "ok": False,
        "error_code": code,
        "retryable": (
            V2_RETRYABLE.get(code, False) if retryable is None else bool(retryable)
        ),
    }


def v2_error_response(
    error_code: str,
    *,
    retryable: Optional[bool] = None,
    http_status: Optional[int] = None,
) -> web.Response:
    body = v2_error_body(error_code, retryable=retryable)
    code = body["error_code"]
    status = http_status or V2_HTTP_STATUS.get(code, 500)
    return web.json_response(body, status=status)


def v2_ok_response(payload: Dict[str, Any], *, status: int = 200) -> web.Response:
    body = {"ok": True, **payload}
    return web.json_response(body, status=status)


def v2_guidance_ok(
    *,
    session_id: str,
    guidance_code: str,
    accepted_count: int,
    draft_ready: bool = False,
    capture_mode: Any = None,
    required_frames: Any = None,
    max_frames: Any = None,
) -> Dict[str, Any]:
    """仅用于已知合法本地构造；非法值抛 ValueError。"""
    payload, err = build_v2_guidance_payload(
        session_id=session_id,
        guidance_code=guidance_code,
        accepted_count=accepted_count,
        draft_ready=draft_ready,
        capture_mode=capture_mode,
        required_frames=required_frames,
        max_frames=max_frames,
    )
    if err or not payload:
        raise ValueError(err or "invalid_guidance_payload")
    return payload


def map_v2_upstream_code(raw: str) -> str:
    if not raw:
        return "internal_error"
    if raw in V2_ERROR_CODES:
        return raw
    return V2_UPSTREAM_CODE_MAP.get(raw, "internal_error")


def v2_public_url(config: dict, path: str) -> str:
    base = ((config.get("server") or {}).get("public_base_url") or "").strip().rstrip("/")
    path = path if path.startswith("/") else f"/{path}"
    return f"{base}{path}"
