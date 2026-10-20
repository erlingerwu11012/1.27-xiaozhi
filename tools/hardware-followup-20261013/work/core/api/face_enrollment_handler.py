"""设备人脸采集网关：Guided Burst V2（AuthManager + 稳定 JSON 契约）。

仅 /session /assess /capture /cancel；identify 与本模块权限完全分离；
上传 token 绑定 session+device+account+enrollment_upload_v2。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
from typing import Any, Dict, Optional, Tuple

import aiohttp
from aiohttp import web

from config.logger import setup_logging
from core.auth import AuthManager
from core.utils.face_enrollment_capability import (
    get_face_enrollment_upload_signing_key,
)
from core.utils.face_enrollment_limits import (
    check_create_rate,
    clear_session_limits,
    incr_metric,
)
from core.utils.face_enrollment_v2 import (
    CAPTURE_MODE_FRONT_ONLY_V1,
    CAPTURE_MODE_GUIDED_BURST_V1,
    DRAFT_READY_FIELD_MISSING,
    FRONT_ONLY_MAX_FRAMES,
    FRONT_ONLY_REQUIRED_FRAMES,
    GUIDANCE_PROFILE_USER_RELATIVE_V1,
    PROTOCOL_VERSION_V2,
    UPLOAD_TOKEN_SCOPE_V2,
    V2_CREATE_JSON_MAX_BYTES,
    V2_CREATE_TIMEOUT_SLACK_SECONDS,
    CREATE_JSON_BODY_EMPTY,
    V2_MAX_CAPTURE_MULTIPART_BYTES,
    V2_MAX_FRAME_BYTES,
    V2_MAX_FRAMES,
    V2_REQUIRED_FRAMES,
    V2_SESSION_TIMEOUT_SECONDS,
    build_v2_guidance_payload,
    clear_session_policy,
    get_session_guidance_profile,
    is_front_only_allowed,
    is_user_relative_allowed,
    map_v2_upstream_code,
    remember_session_guidance_profile,
    remember_session_policy,
    resolve_guidance_mode_fields,
    resolve_v2_session_url,
    validate_guidance_code_for_profile,
    v2_error_response,
    v2_ok_response,
    v2_public_url,
)

# opaque short id：禁止路径分隔与 query 字符，避免 cleanup URL 注入
_SAFE_V2_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{7,63}$")

TAG = __name__
logger = setup_logging()


class EnrollmentAuthError(Exception):
    """人脸采集网关鉴权错误；不得使用 AuthenticationError（其会规范化错误码）。"""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _redact(v: str) -> str:
    s = (v or "").strip()
    if len(s) < 8:
        return "***"
    return f"{s[:4]}...{s[-4:]}"


def _log(event: str, **fields: Any) -> None:
    banned = {
        "token",
        "upload_token",
        "authorization",
        "name",
        "display_name",
        "embedding",
        "image",
        "query",
    }
    safe = {k: v for k, v in fields.items() if k not in banned}
    logger.bind(tag=TAG).info(
        f"[FACE_ENROLL] {json.dumps({'event': event, **safe}, ensure_ascii=False)}"
    )


def _face_cfg(config: dict) -> dict:
    return ((config.get("server") or {}).get("face") or {})


def _account_id(config: dict) -> str:
    """配置覆盖：仅当非 default 时可用（测试/单租户遗留）。生产以设备 userId 为准。"""
    from core.utils.account_identity import normalize_manager_user_id
    from core.utils.face_jwt import is_reserved_account_id

    raw = (_face_cfg(config).get("account_id") or "").strip()
    if is_reserved_account_id(raw):
        return ""
    return normalize_manager_user_id(raw) or ""


async def _resolve_account_id_for_device(config: dict, device_id: str) -> str:
    from core.utils.account_identity import normalize_manager_user_id

    try:
        from config.manage_api_client import get_device_config

        info = await get_device_config(device_id)
        aid = normalize_manager_user_id((info or {}).get("userId") or (info or {}).get("user_id"))
        if aid:
            return aid
    except Exception:
        pass
    return _account_id(config)


class FaceEnrollmentHandler:
    def __init__(self, config: dict):
        self.config = config
        self.logger = setup_logging()
        auth_cfg = (config.get("server") or {}).get("auth") or {}
        secret = (config.get("server") or {}).get("auth_key") or ""
        expire = auth_cfg.get("expire_seconds", None)
        self.auth = AuthManager(secret_key=secret, expire_seconds=expire)
        self.auth_enable = bool(auth_cfg.get("enabled", False))

    # ── upload token ─────────────────────────────────────────────

    def _upload_token_secret(self) -> str:
        key, reason = get_face_enrollment_upload_signing_key(self.config)
        if not key:
            raise RuntimeError(reason or "upload_signing_key_missing")
        return key

    @staticmethod
    def _token_content(
        session_id: str,
        device_id: str,
        account_id: str,
        exp: int,
        *,
        scope: str = UPLOAD_TOKEN_SCOPE_V2,
    ) -> str:
        return f"{session_id}|{device_id}|{account_id}|{exp}|{scope}"

    def issue_upload_token(
        self,
        *,
        session_id: str,
        device_id: str,
        account_id: str,
        ttl: int,
        scope: str = UPLOAD_TOKEN_SCOPE_V2,
    ) -> Tuple[str, int]:
        secret = self._upload_token_secret()
        exp = int(time.time()) + int(ttl)
        content = self._token_content(
            session_id, device_id, account_id, exp, scope=scope
        )
        sig = hmac.new(
            secret.encode("utf-8"), content.encode("utf-8"), hashlib.sha256
        ).digest()
        token = base64.urlsafe_b64encode(sig).decode("utf-8").rstrip("=") + f".{exp}"
        return token, exp

    def verify_upload_token(
        self,
        token: str,
        *,
        session_id: str,
        device_id: str,
        account_id: str,
        scope: str = UPLOAD_TOKEN_SCOPE_V2,
    ) -> str:
        """返回 ok | expired | invalid。"""
        try:
            secret = self._upload_token_secret()
        except RuntimeError:
            return "invalid"
        if not secret or not token or "." not in token:
            return "invalid"
        try:
            sig_part, exp_s = token.rsplit(".", 1)
            exp = int(exp_s)
        except (ValueError, TypeError):
            return "invalid"
        if exp < int(time.time()):
            return "expired"
        content = self._token_content(
            session_id, device_id, account_id, exp, scope=scope
        )
        expect = (
            base64.urlsafe_b64encode(
                hmac.new(
                    secret.encode("utf-8"), content.encode("utf-8"), hashlib.sha256
                ).digest()
            )
            .decode("utf-8")
            .rstrip("=")
        )
        if not hmac.compare_digest(sig_part, expect):
            return "invalid"
        return "ok"

    # ── face-api 代理 ────────────────────────────────────────────

    def _face_jwt(self, device_id: str, account_id: str) -> Optional[str]:
        from core.utils.face_jwt import build_face_jwt_from_config, is_reserved_account_id

        if is_reserved_account_id(account_id):
            return None
        return build_face_jwt_from_config(
            self.config, account_id=account_id, device_id=device_id
        )

    def _face_base(self) -> str:
        url = (_face_cfg(self.config).get("identify_url") or "").strip()
        if url.endswith("/face/identify"):
            return url[: -len("/face/identify")]
        if "/face/" in url:
            return url.split("/face/", 1)[0]
        return "http://127.0.0.1:8765"

    async def _face_json(
        self,
        method: str,
        path: str,
        *,
        device_id: str,
        account_id: str,
        json_body: Optional[dict] = None,
        data=None,
        headers_extra: Optional[dict] = None,
    ) -> Tuple[int, Any]:
        token = self._face_jwt(device_id, account_id)
        if not token:
            return 503, {"detail": {"code": "enrollment_disabled", "message": "未配置"}}
        headers = {"Authorization": f"Bearer {token}"}
        if headers_extra:
            headers.update(headers_extra)
        url = self._face_base().rstrip("/") + path
        timeout = aiohttp.ClientTimeout(
            total=float(_face_cfg(self.config).get("timeout", 5.0))
        )
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.request(
                method, url, json=json_body, data=data, headers=headers
            ) as resp:
                ctype = resp.headers.get("Content-Type", "")
                if "application/json" in ctype:
                    body = await resp.json(content_type=None)
                else:
                    body = await resp.read()
                return resp.status, body


    # ── V2 Guided Burst ──────────────────────────────────────────

    async def _authenticate_device_v2_strict(
        self, request: web.Request
    ) -> Tuple[str, str, str]:
        """严格鉴权：始终校验 pairing Authorization（无设备白名单旁路）。"""
        device_id = (
            request.headers.get("Device-Id") or request.headers.get("device-id") or ""
        ).strip()
        client_id = (
            request.headers.get("Client-Id") or request.headers.get("client-id") or ""
        ).strip()
        if not device_id or not client_id:
            raise EnrollmentAuthError("auth_invalid")
        account_id = await _resolve_account_id_for_device(self.config, device_id)
        if not account_id:
            raise EnrollmentAuthError("account_mismatch")

        auth = (request.headers.get("Authorization") or "").strip()
        if not auth.lower().startswith("bearer "):
            raise EnrollmentAuthError("auth_invalid")
        token = auth[7:].strip()
        if not token or not self.auth.verify_token(
            token, client_id=client_id, username=device_id
        ):
            raise EnrollmentAuthError("auth_invalid")
        return device_id, client_id, account_id

    async def _authenticate_upload_v2(
        self, request: web.Request, session_id: str
    ) -> Tuple[str, str, str]:
        """V2：严格 pairing + 仅 X-Enrollment-Token header，禁止 query token。"""
        device_id, client_id, account_id = await self._authenticate_device_v2_strict(
            request
        )
        upload_token = (
            request.headers.get("X-Enrollment-Token")
            or request.headers.get("x-enrollment-token")
            or ""
        ).strip()
        if not upload_token:
            raise EnrollmentAuthError("upload_token_invalid")
        state = self.verify_upload_token(
            upload_token,
            session_id=session_id,
            device_id=device_id,
            account_id=account_id,
            scope=UPLOAD_TOKEN_SCOPE_V2,
        )
        if state == "expired":
            raise EnrollmentAuthError("upload_token_expired")
        if state != "ok":
            raise EnrollmentAuthError("upload_token_invalid")
        return device_id, client_id, account_id

    def _v2_upstream_error(self, status: int, body: Any) -> web.Response:
        detail = {}
        if isinstance(body, dict):
            if isinstance(body.get("detail"), dict):
                detail = body["detail"]
            else:
                detail = body
        raw = ""
        if isinstance(detail, dict):
            raw = str(detail.get("code") or "")
        elif isinstance(body, dict):
            raw = str(body.get("code") or "")
        code = map_v2_upstream_code(raw)
        if status == 410:
            code = "session_expired"
        return v2_error_response(code)

    def _v2_guidance_from_upstream(
        self, session_id: str, body: dict
    ) -> web.Response:
        """将上游 assess/capture 成功体转为网关响应；非法 count/code → internal_error。"""
        draft_arg = (
            body["draft_ready"]
            if "draft_ready" in body
            else DRAFT_READY_FIELD_MISSING
        )
        payload, err = build_v2_guidance_payload(
            session_id=session_id,
            guidance_code=body.get("guidance_code"),
            accepted_count=body.get("accepted_count"),
            draft_ready=draft_arg,
            capture_mode=body.get("capture_mode"),
            required_frames=body.get("required_frames"),
            max_frames=body.get("max_frames"),
        )
        if err or not payload:
            _log(
                "v2_guidance_rejected",
                session=_redact(session_id),
                reason=err or "invalid_guidance",
            )
            return v2_error_response("internal_error")
        return v2_ok_response(payload)

    async def _read_v2_create_json_body(
        self, request: web.Request
    ) -> Tuple[Any, Optional[web.Response]]:
        """读取 create 请求 JSON；不依赖 Content-Length 是否存在。

        返回 (parsed_or_EMPTY, error_response)。
        - 真正空体 → (CREATE_JSON_BODY_EMPTY, None)，旧协议兼容
        - JSON null/数组/非对象 → 由调用方拒绝（此处原样返回解析结果）
        - 非空非法 JSON → (None, invalid_capture_mode)
        - 超限 → (None, payload_too_large)
        """
        max_bytes = V2_CREATE_JSON_MAX_BYTES
        cl_hdr = request.headers.get("Content-Length")
        if cl_hdr is not None:
            try:
                cl = int(cl_hdr)
            except ValueError:
                return None, v2_error_response("payload_too_large")
            if cl < 0 or cl > max_bytes:
                return None, v2_error_response("payload_too_large")

        if not request.can_read_body:
            return CREATE_JSON_BODY_EMPTY, None

        # 循环读取直到 EOF；单次 read 不保证完整。每批累计实际字节，
        # 超过上限立即拒绝，内存有界。CancelledError 不被吞（不按空体降级）。
        chunks: list = []
        total = 0
        chunk_size = 8192
        try:
            while True:
                chunk = await request.content.read(chunk_size)
                if not chunk:
                    break  # EOF
                total += len(chunk)
                if total > max_bytes:
                    return None, v2_error_response("payload_too_large")
                chunks.append(chunk)
        except Exception:
            # 网络读取失败/超时：不得当作空体降级；中断不创建上游会话
            return None, v2_error_response("payload_too_large")

        raw = b"".join(chunks)
        if not raw or not raw.strip():
            return CREATE_JSON_BODY_EMPTY, None
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except Exception:
            return None, v2_error_response("invalid_capture_mode")
        return parsed, None

    async def handle_v2_create_session(self, request: web.Request) -> web.Response:
        try:
            device_id, _client_id, account_id = await self._authenticate_device_v2_strict(
                request
            )
        except EnrollmentAuthError as exc:
            code = str(exc) if str(exc) in (
                "auth_invalid",
                "account_mismatch",
            ) else "auth_invalid"
            _log("v2_auth_failed", reason=code, device=_redact(
                request.headers.get("Device-Id") or ""
            ))
            return v2_error_response(code)

        session_url, url_reason = resolve_v2_session_url(self.config)
        if not session_url:
            _log("v2_create_rejected", reason=url_reason, device=_redact(device_id))
            return v2_error_response("capability_invalid")

        _, key_reason = get_face_enrollment_upload_signing_key(self.config)
        if key_reason:
            return v2_error_response("enrollment_disabled")

        limited = check_create_rate(device_id, account_id)
        if limited:
            incr_metric("rate_limited")
            return v2_error_response("rate_limited")

        capture_mode = None
        guidance_profile = None
        raw_body, body_err = await self._read_v2_create_json_body(request)
        if body_err is not None:
            return body_err
        if raw_body is not CREATE_JSON_BODY_EMPTY:
            if not isinstance(raw_body, dict):
                return v2_error_response("invalid_capture_mode")
            if "capture_mode" in raw_body:
                cm = raw_body.get("capture_mode")
                if type(cm) is not str:
                    return v2_error_response("invalid_capture_mode")
                capture_mode = cm.strip() or None
                if capture_mode is None:
                    return v2_error_response("invalid_capture_mode")
            if "guidance_profile" in raw_body:
                gp = raw_body.get("guidance_profile")
                if type(gp) is not str:
                    return v2_error_response("invalid_guidance_profile")
                guidance_profile = gp.strip() or None
                if guidance_profile is None:
                    return v2_error_response("invalid_guidance_profile")
        if capture_mode and capture_mode not in (
            "guided_burst_v1",
            CAPTURE_MODE_FRONT_ONLY_V1,
        ):
            return v2_error_response("invalid_capture_mode")
        if capture_mode == CAPTURE_MODE_FRONT_ONLY_V1 and not is_front_only_allowed(
            self.config, account_id, device_id
        ):
            return v2_error_response("capture_mode_not_allowed")
        if guidance_profile is not None:
            if guidance_profile != GUIDANCE_PROFILE_USER_RELATIVE_V1:
                return v2_error_response("invalid_guidance_profile")
            if capture_mode != CAPTURE_MODE_FRONT_ONLY_V1:
                # user_relative_v1 仅配合 front_only_v1
                return v2_error_response("invalid_guidance_profile")
            if not is_user_relative_allowed(self.config, account_id, device_id):
                return v2_error_response("guidance_profile_not_allowed")

        requested_mode = capture_mode or "guided_burst_v1"

        json_body = {
            "device_id": device_id,
            "timeout_seconds": (
                V2_SESSION_TIMEOUT_SECONDS + V2_CREATE_TIMEOUT_SLACK_SECONDS
            ),
            "protocol_version": 2,
            "guided_burst_v1": True,
        }
        if capture_mode == CAPTURE_MODE_FRONT_ONLY_V1:
            json_body["capture_mode"] = CAPTURE_MODE_FRONT_ONLY_V1
        if guidance_profile is not None:
            json_body["guidance_profile"] = guidance_profile

        status, body = await self._face_json(
            "POST",
            "/face/enrollment/sessions",
            device_id=device_id,
            account_id=account_id,
            json_body=json_body,
        )
        if status != 200 or not isinstance(body, dict):
            _log(
                "v2_create_upstream_fail",
                http=status,
                device=_redact(device_id),
                account=_redact(account_id),
            )
            if isinstance(body, dict):
                return self._v2_upstream_error(status, body)
            return v2_error_response("internal_error")

        ok_up, up_reason = self._validate_v2_create_upstream(
            body,
            expected_mode=requested_mode,
            expected_guidance_profile=guidance_profile,
        )
        if not ok_up:
            _log(
                "v2_create_upstream_invalid",
                reason=up_reason,
                device=_redact(device_id),
            )
            # 有安全 session_id 时 best-effort 清理上游孤儿会话；失败不掩盖原错误
            await self._best_effort_cleanup_orphan_v2_session(
                body, device_id=device_id, account_id=account_id
            )
            return v2_error_response("internal_error")

        session_id = str(body["session_id"]).strip()
        expires_at = int(body["expires_at"])
        ttl = max(V2_SESSION_TIMEOUT_SECONDS, expires_at - int(time.time()))
        try:
            upload_token, token_exp = self.issue_upload_token(
                session_id=session_id,
                device_id=device_id,
                account_id=account_id,
                ttl=ttl,
                scope=UPLOAD_TOKEN_SCOPE_V2,
            )
        except RuntimeError:
            await self._best_effort_cleanup_orphan_v2_session(
                body, device_id=device_id, account_id=account_id
            )
            return v2_error_response("enrollment_disabled")

        incr_metric("created")
        _log(
            "v2_session_created",
            session=_redact(session_id),
            device=_redact(device_id),
            account=_redact(account_id),
            metric="created",
            http=200,
            capture_mode=str(body.get("capture_mode") or "guided_burst_v1"),
        )
        mode = body.get("capture_mode")
        if mode == CAPTURE_MODE_FRONT_ONLY_V1:
            req_frames = FRONT_ONLY_REQUIRED_FRAMES
            max_frames = FRONT_ONLY_MAX_FRAMES
        else:
            mode = CAPTURE_MODE_GUIDED_BURST_V1
            req_frames = V2_REQUIRED_FRAMES
            max_frames = V2_MAX_FRAMES
        remember_session_policy(session_id, mode, req_frames)
        remember_session_guidance_profile(session_id, guidance_profile)
        payload = {
            "session_id": session_id,
            "assess_url": v2_public_url(
                self.config, f"/mcp/face-enrollment/assess/{session_id}"
            ),
            "capture_url": v2_public_url(
                self.config, f"/mcp/face-enrollment/capture/{session_id}"
            ),
            "cancel_url": v2_public_url(
                self.config, f"/mcp/face-enrollment/cancel/{session_id}"
            ),
            "upload_token": upload_token,
            "expires_at": min(expires_at, token_exp),
            "required_frames": req_frames,
            "max_frames": max_frames,
        }
        if mode == CAPTURE_MODE_FRONT_ONLY_V1:
            payload["capture_mode"] = CAPTURE_MODE_FRONT_ONLY_V1
        if guidance_profile is not None:
            payload["guidance_profile"] = guidance_profile
        return v2_ok_response(payload)

    async def handle_v2_assess(self, request: web.Request) -> web.Response:
        session_id = (request.match_info.get("session_id") or "").strip()
        try:
            device_id, _client_id, account_id = await self._authenticate_upload_v2(
                request, session_id
            )
        except EnrollmentAuthError as exc:
            code = str(exc)
            if code not in (
                "auth_invalid",
                "upload_token_invalid",
                "upload_token_expired",
                "account_mismatch",
            ):
                code = "auth_invalid"
            return v2_error_response(code)

        image_data, err = await self._read_multipart_image_v2_assess(request)
        if err is not None:
            return err

        form = aiohttp.FormData()
        form.add_field(
            "image",
            image_data,
            filename="assess.jpg",
            content_type="image/jpeg",
        )
        status, body = await self._face_json(
            "POST",
            f"/face/enrollment/sessions/{session_id}/assess",
            device_id=device_id,
            account_id=account_id,
            data=form,
        )
        if not isinstance(body, dict) or status >= 400:
            return self._v2_upstream_error(status, body if isinstance(body, dict) else {})

        mode, req_frames, max_frames, mode_err = resolve_guidance_mode_fields(
            session_id, body
        )
        if mode_err or mode is None:
            _log(
                "v2_guidance_rejected",
                session=_redact(session_id),
                reason=mode_err or "mode_mismatch",
            )
            return v2_error_response("internal_error")

        profile = get_session_guidance_profile(session_id)
        if not validate_guidance_code_for_profile(
            body.get("guidance_code"), profile
        ):
            _log(
                "v2_guidance_rejected",
                session=_redact(session_id),
                reason="guidance_profile_mismatch",
            )
            return v2_error_response("internal_error")

        payload, err = build_v2_guidance_payload(
            session_id=session_id,
            guidance_code=body.get("guidance_code"),
            accepted_count=body.get("accepted_count"),
            draft_ready=(
                body["draft_ready"]
                if "draft_ready" in body
                else DRAFT_READY_FIELD_MISSING
            ),
            capture_mode=mode,
            required_frames=req_frames,
            max_frames=max_frames,
        )
        if err or not payload:
            _log(
                "v2_guidance_rejected",
                session=_redact(session_id),
                reason=err or "invalid_guidance",
            )
            return v2_error_response("internal_error")
        _log(
            "v2_assess",
            session=_redact(session_id),
            device=_redact(device_id),
            guidance=payload["guidance_code"],
            accepted=payload["accepted_count"],
        )
        return v2_ok_response(payload)

    async def handle_v2_capture(self, request: web.Request) -> web.Response:
        session_id = (request.match_info.get("session_id") or "").strip()
        try:
            device_id, _client_id, account_id = await self._authenticate_upload_v2(
                request, session_id
            )
        except EnrollmentAuthError as exc:
            code = str(exc)
            if code not in (
                "auth_invalid",
                "upload_token_invalid",
                "upload_token_expired",
                "account_mismatch",
            ):
                code = "auth_invalid"
            return v2_error_response(code)

        parsed, err = await self._read_multipart_capture_v2(request)
        if err is not None:
            return err
        assert parsed is not None
        pose, round_n, candidates = parsed

        form = aiohttp.FormData()
        form.add_field("pose", pose)
        form.add_field("round", str(round_n))
        for i, data in enumerate(candidates):
            form.add_field(
                f"candidate_{i}",
                data,
                filename=f"c{i}.jpg",
                content_type="image/jpeg",
            )
        status, body = await self._face_json(
            "POST",
            f"/face/enrollment/sessions/{session_id}/capture",
            device_id=device_id,
            account_id=account_id,
            data=form,
        )
        if not isinstance(body, dict) or status >= 400:
            return self._v2_upstream_error(status, body if isinstance(body, dict) else {})

        mode, req_frames, max_frames, mode_err = resolve_guidance_mode_fields(
            session_id, body
        )
        if mode_err or mode is None:
            _log(
                "v2_guidance_rejected",
                session=_redact(session_id),
                reason=mode_err or "mode_mismatch",
            )
            return v2_error_response("internal_error")

        profile = get_session_guidance_profile(session_id)
        if not validate_guidance_code_for_profile(
            body.get("guidance_code"), profile
        ):
            _log(
                "v2_guidance_rejected",
                session=_redact(session_id),
                reason="guidance_profile_mismatch",
            )
            return v2_error_response("internal_error")

        payload, err = build_v2_guidance_payload(
            session_id=session_id,
            guidance_code=body.get("guidance_code"),
            accepted_count=body.get("accepted_count"),
            draft_ready=(
                body["draft_ready"]
                if "draft_ready" in body
                else DRAFT_READY_FIELD_MISSING
            ),
            capture_mode=mode,
            required_frames=req_frames,
            max_frames=max_frames,
        )
        if err or not payload:
            _log(
                "v2_guidance_rejected",
                session=_redact(session_id),
                reason=err or "invalid_guidance",
            )
            return v2_error_response("internal_error")
        _log(
            "v2_capture",
            session=_redact(session_id),
            device=_redact(device_id),
            pose=pose,
            round=round_n,
            guidance=payload["guidance_code"],
            accepted=payload["accepted_count"],
        )
        return v2_ok_response(payload)

    async def handle_v2_cancel(self, request: web.Request) -> web.Response:
        session_id = (request.match_info.get("session_id") or "").strip()
        # V2：X-Enrollment-Token 必填
        try:
            device_id, _, account_id = await self._authenticate_upload_v2(
                request, session_id
            )
        except EnrollmentAuthError as exc:
            code = str(exc) if str(exc) in (
                "auth_invalid",
                "account_mismatch",
                "upload_token_invalid",
                "upload_token_expired",
            ) else "auth_invalid"
            _log("v2_cancel_auth_failed", reason=code)
            return v2_error_response(code)

        # V2 专用非幂等取消；不得调用 V1 幂等 cancel
        status, body = await self._face_json(
            "DELETE",
            f"/face/enrollment/sessions/{session_id}/guided-burst",
            device_id=device_id,
            account_id=account_id,
        )
        clear_session_limits(session_id)
        clear_session_policy(session_id)
        if status >= 400:
            _log(
                "v2_session_cancel_fail",
                session=_redact(session_id),
                device=_redact(device_id),
                http=status,
            )
            return self._v2_upstream_error(status, body)
        incr_metric("cancelled")
        _log(
            "v2_session_cancelled",
            session=_redact(session_id),
            device=_redact(device_id),
            http=status,
            metric="cancelled",
        )
        # 独立终态响应：不含 accepted_count / draft_ready，避免 count 倒退
        return v2_ok_response(
            {
                "session_id": session_id,
                "guidance_code": "CANCELLED",
            }
        )

    @staticmethod
    def _is_safe_v2_session_id(session_id: Any) -> bool:
        """安全可用的 opaque short id；不合格则不拼接 cleanup URL。"""
        if not isinstance(session_id, str):
            return False
        sid = session_id.strip()
        if sid != session_id:
            # 首尾空白视为不安全，避免隐式 strip 后误用
            return False
        return bool(_SAFE_V2_SESSION_ID_RE.fullmatch(sid))

    @staticmethod
    def _validate_v2_create_upstream(
        body: dict,
        *,
        expected_mode: Optional[str] = None,
        expected_guidance_profile: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """签发 token 前校验 face-api 成功体；字段必须完整且精确匹配 V2 契约。

        expected_mode：客户端请求的模式；与上游返回不一致时拒绝（不静默降级/升级）。
        expected_guidance_profile：客户端请求的指导 profile；上游回显须精确一致。
        """
        sid = body.get("session_id")
        if not isinstance(sid, str):
            return False, "session_id_type"
        if not FaceEnrollmentHandler._is_safe_v2_session_id(sid):
            return False, "session_id_invalid"

        if "expires_at" not in body:
            return False, "expires_at_missing"
        expires_raw = body.get("expires_at")
        if type(expires_raw) is not int:
            return False, "expires_at_type"
        expires_at = expires_raw
        now = int(time.time())
        if expires_at <= now:
            return False, "expires_at_expired"
        # 协议要求 session/upload token 均至少 240s；不接受 235 等短余量
        if expires_at - now < V2_SESSION_TIMEOUT_SECONDS:
            return False, "expires_at_too_short"

        if "protocol_version" not in body:
            return False, "protocol_version_missing"
        pv = body.get("protocol_version")
        if type(pv) is not int:
            return False, "protocol_version_type"
        if pv != PROTOCOL_VERSION_V2:
            return False, "protocol_version_mismatch"

        if "guided_burst_v1" not in body:
            return False, "guided_burst_v1_missing"
        # 必须是真正的布尔 True；拒绝 "true"/1/Truthy
        if body.get("guided_burst_v1") is not True:
            return False, "guided_burst_v1_invalid"

        mode = body.get("capture_mode")
        if mode is None:
            mode = "guided_burst_v1"
        if type(mode) is not str:
            return False, "capture_mode_invalid"
        if mode not in ("guided_burst_v1", CAPTURE_MODE_FRONT_ONLY_V1):
            return False, "capture_mode_invalid"

        want = expected_mode or "guided_burst_v1"
        if want != mode:
            return False, "capture_mode_mismatch"

        for key in ("required_frames", "max_frames"):
            if key not in body:
                return False, f"{key}_missing"
            val = body.get(key)
            if type(val) is not int or isinstance(val, bool):
                return False, f"{key}_invalid"
            if mode == CAPTURE_MODE_FRONT_ONLY_V1:
                expect = (
                    FRONT_ONLY_REQUIRED_FRAMES
                    if key == "required_frames"
                    else FRONT_ONLY_MAX_FRAMES
                )
                if val != expect:
                    return False, f"{key}_mismatch"
            elif val != V2_REQUIRED_FRAMES:
                return False, f"{key}_mismatch"

        # guidance_profile 回显必须与请求一致；未请求则上游不得下发（防止隐式开启）
        up_profile = body.get("guidance_profile")
        if expected_guidance_profile is not None:
            if up_profile != expected_guidance_profile:
                return False, "guidance_profile_mismatch"
        elif up_profile is not None:
            return False, "guidance_profile_mismatch"
        return True, "ok"

    async def _best_effort_cleanup_orphan_v2_session(
        self,
        body: Any,
        *,
        device_id: str,
        account_id: str,
    ) -> None:
        """上游契约失败但已有安全 session_id 时，best-effort 调 V2 专用取消清理。

        使用内部 face-api JWT（_face_json），不涉及设备 upload token。
        清理失败只记原因类型，不掩盖也不改写对设备的 create 失败响应。
        """
        if not isinstance(body, dict):
            return
        sid = body.get("session_id")
        if not self._is_safe_v2_session_id(sid):
            return
        assert isinstance(sid, str)
        try:
            status, _resp = await self._face_json(
                "DELETE",
                f"/face/enrollment/sessions/{sid}/guided-burst",
                device_id=device_id,
                account_id=account_id,
            )
            _log(
                "v2_create_orphan_cleanup",
                session=_redact(sid),
                device=_redact(device_id),
                http=int(status) if status is not None else 0,
                ok=bool(status is not None and int(status) < 400),
            )
        except Exception:
            _log(
                "v2_create_orphan_cleanup_fail",
                session=_redact(sid),
                device=_redact(device_id),
                reason="cleanup_exception",
            )

    async def _read_multipart_image_v2_assess(
        self, request: web.Request
    ) -> Tuple[Optional[bytes], Optional[web.Response]]:
        cl = request.headers.get("Content-Length")
        if cl is not None:
            try:
                n = int(cl)
            except ValueError:
                return None, v2_error_response("payload_too_large")
            if n > V2_MAX_FRAME_BYTES + 64 * 1024:
                return None, v2_error_response("payload_too_large")
        ctype = (request.headers.get("Content-Type") or "").lower()
        if "multipart/" not in ctype:
            return None, v2_error_response("invalid_content_type")
        try:
            reader = await request.multipart()
        except Exception:
            return None, v2_error_response("invalid_content_type")

        total = 0
        image_data: Optional[bytes] = None
        seen_image = False
        field = await reader.next()
        while field is not None:
            chunks = []
            while True:
                chunk = await field.read_chunk(size=8192)
                if not chunk:
                    break
                total += len(chunk)
                if total > V2_MAX_FRAME_BYTES + 64 * 1024:
                    return None, v2_error_response("payload_too_large")
                chunks.append(chunk)
            data = b"".join(chunks)
            name = (field.name or "").strip().lower()
            # 严格：必须且只能有一个名为 image 的字段；任意额外字段（含文本）拒绝
            if name != "image":
                return None, v2_error_response("invalid_content_type")
            if seen_image:
                return None, v2_error_response("invalid_content_type")
            seen_image = True
            image_data = data
            field = await reader.next()

        if not seen_image or not image_data:
            return None, v2_error_response("invalid_jpeg")
        if len(image_data) > V2_MAX_FRAME_BYTES:
            return None, v2_error_response("payload_too_large")
        if len(image_data) < 3 or image_data[:3] != b"\xff\xd8\xff":
            return None, v2_error_response("invalid_jpeg")
        return image_data, None

    async def _read_multipart_capture_v2(
        self, request: web.Request
    ) -> Tuple[
        Optional[Tuple[str, int, list]],
        Optional[web.Response],
    ]:
        cl = request.headers.get("Content-Length")
        if cl is not None:
            try:
                n = int(cl)
            except ValueError:
                return None, v2_error_response("payload_too_large")
            if n > V2_MAX_CAPTURE_MULTIPART_BYTES:
                return None, v2_error_response("payload_too_large")
        ctype = (request.headers.get("Content-Type") or "").lower()
        if "multipart/" not in ctype:
            return None, v2_error_response("invalid_content_type")
        try:
            reader = await request.multipart()
        except Exception:
            return None, v2_error_response("invalid_content_type")

        allowed = {"pose", "round", "candidate_0", "candidate_1", "candidate_2"}
        total = 0
        pose: Optional[str] = None
        round_n: Optional[int] = None
        candidates: Dict[int, bytes] = {}
        seen: set = set()
        field = await reader.next()
        while field is not None:
            chunks = []
            while True:
                chunk = await field.read_chunk(size=8192)
                if not chunk:
                    break
                total += len(chunk)
                if total > V2_MAX_CAPTURE_MULTIPART_BYTES:
                    return None, v2_error_response("payload_too_large")
                chunks.append(chunk)
            data = b"".join(chunks)
            name = (field.name or "").strip().lower()
            if not name:
                field = await reader.next()
                continue
            if name not in allowed:
                return None, v2_error_response("invalid_content_type")
            if name in seen:
                return None, v2_error_response("invalid_content_type")
            seen.add(name)
            if name == "pose":
                pose = data.decode("utf-8", errors="ignore").strip().lower()
            elif name == "round":
                try:
                    round_n = int(data.decode("utf-8", errors="ignore").strip())
                except ValueError:
                    return None, v2_error_response("invalid_round")
            elif name.startswith("candidate_"):
                idx = int(name.split("_", 1)[1])
                if len(data) > V2_MAX_FRAME_BYTES:
                    return None, v2_error_response("payload_too_large")
                if len(data) < 3 or data[:3] != b"\xff\xd8\xff":
                    return None, v2_error_response("invalid_jpeg")
                candidates[idx] = data
            field = await reader.next()

        if seen != allowed:
            return None, v2_error_response("invalid_content_type")
        if pose not in ("front", "left", "right"):
            return None, v2_error_response("invalid_pose")
        if round_n not in (1, 2, 3):
            return None, v2_error_response("invalid_round")
        ordered = [candidates[0], candidates[1], candidates[2]]
        return (pose, int(round_n), ordered), None
