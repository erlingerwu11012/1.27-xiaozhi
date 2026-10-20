import json
import math
import asyncio
import copy
import re
import asyncio
from aiohttp import web
from config.logger import setup_logging
from core.utils.util import get_vision_url, is_valid_image_file
from core.utils.vllm import create_instance
from config.config_loader import get_private_config_from_api
from core.utils.auth import AuthToken
import aiohttp
import base64
import time
from typing import Tuple, Optional, Dict, Any
from plugins_func.register import Action
from core.utils.cache.manager import cache_manager
from core.utils.cache.config import CacheType

TAG = __name__

# 设置最大文件大小为5MB
MAX_FILE_SIZE = 5 * 1024 * 1024

# 指标说明（同一 cosine similarity）：
# - face-api 返回的 confidence = ArcFace L2 归一化向量点积
# - 历史 vision confidence_threshold=0.80 与此同指标
# - FACE_MATCH_THRESHOLD=0.45 仅为通用匹配下限，不得单独用作个人身份确认
# - 个人身份确认使用 FACE_IDENTITY_MATCH_THRESHOLD / server.face.identity_match_threshold
#   默认 0.80；在无标定数据证明可放宽前，禁止降到 0.45
DEFAULT_IDENTITY_MATCH_THRESHOLD = 0.80

# 设备 MCP / 大模型可读的非命中提示。status 是机读码；reason/message 区分空库与对不上。
IDENTIFY_CLIENT_HINTS = {
    "empty": ("no_content", "当前账号还没有录入人脸"),
    "unknown": ("no_match", "没有匹配到已录入的人脸"),
    "no_face": ("no_face", "画面中没有检测到人脸"),
    "ambiguous": ("ambiguous", "画面中有多张人脸，无法确认身份"),
    "error": ("error", "人脸识别暂时不可用"),
}


class VisionRequestError(ValueError):
    def __init__(self, status, reason, reject_code: Optional[str] = None):
        self.status, self.reason = status, reason
        # 内部精确拒绝码（仅日志）；对外 reason 仍可保持 permission_denied
        self.reject_code = reject_code or reason
        super().__init__(reason)


class VisionHandler:
    def __init__(self, config: dict):
        self.config = config
        self.logger = setup_logging()
        # 初始化认证工具（与 /mcp/vision/explain 相同 AuthToken）
        self.auth = AuthToken(config["server"]["auth_key"])

    @staticmethod
    def _vision_endpoint(request) -> str:
        path = getattr(request, "path", None)
        if isinstance(path, str) and path:
            return path
        rel = getattr(request, "rel_url", None)
        rel_path = getattr(rel, "path", None) if rel is not None else None
        if isinstance(rel_path, str) and rel_path:
            return rel_path
        return "-"

    @staticmethod
    def _vision_correlation_id(request) -> str:
        headers = getattr(request, "headers", None) or {}
        for key in (
            "X-Request-Id",
            "X-Correlation-Id",
            "Correlation-Id",
            "Request-Id",
            "Client-Id",
            "client-id",
        ):
            val = headers.get(key)
            if isinstance(val, str):
                cleaned = val.strip()
                if cleaned and len(cleaned) <= 128:
                    return cleaned
        return "-"

    def _log_vision_auth_reject(
        self,
        request,
        reject_code: str,
        *,
        client_reason: str = "permission_denied",
        session_consistent: Optional[bool] = None,
        **safe_flags,
    ) -> None:
        """记录精确拒绝原因；不写 token / 密钥 / 照片 / 完整 session 明文。"""
        parts = [
            "[VISION_AUTH_REJECT]",
            f"reject={reject_code}",
            f"endpoint={self._vision_endpoint(request)}",
            f"correlation_id={self._vision_correlation_id(request)}",
            f"client_reason={client_reason}",
        ]
        if session_consistent is None:
            parts.append("session_consistent=-")
        else:
            parts.append(f"session_consistent={'1' if session_consistent else '0'}")
        for key in sorted(safe_flags):
            val = safe_flags[key]
            if val is None:
                continue
            if isinstance(val, bool):
                parts.append(f"{key}={'1' if val else '0'}")
            else:
                # 仅允许短、非密钥字段（如 device_id）
                text = str(val).strip()
                if text and len(text) <= 128 and "token" not in key.lower() and "key" not in key.lower():
                    parts.append(f"{key}={text}")
        self.logger.bind(tag=TAG).warning(" ".join(parts))

    def _face_cfg(self) -> dict:
        return self.config.get("server", {}).get("face", {}) or {}

    @staticmethod
    def _image_session_key(device_id: str, session_id: str, account_id: str = '') -> str:
        # Preserve the legacy key when account is absent; new multi-tenant paths
        # include the account so an identical device/session cannot share images.
        if not account_id:
            return f"{device_id}:{session_id}"
        return json.dumps([account_id, device_id, session_id], separators=(',', ':'))

    def _identity_threshold(self) -> float:
        face_cfg = self._face_cfg()
        raw = face_cfg.get("identity_match_threshold")
        if raw is None:
            raw = face_cfg.get("confidence_threshold")  # 兼容旧键名
        if raw is None:
            return DEFAULT_IDENTITY_MATCH_THRESHOLD
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return DEFAULT_IDENTITY_MATCH_THRESHOLD
        # 保守：不允许配置成比默认更松（除非显式 >= 默认）；禁止静默用 0.45
        if value < DEFAULT_IDENTITY_MATCH_THRESHOLD:
            self.logger.bind(tag=TAG).warning(
                f"identity_match_threshold={value} 低于保守默认 "
                f"{DEFAULT_IDENTITY_MATCH_THRESHOLD}，已钳制到默认（无标定不得放宽）"
            )
            return DEFAULT_IDENTITY_MATCH_THRESHOLD
        return value

    def _resolve_account_id(self) -> Optional[str]:
        """遗留单租户配置 account_id；禁止回退到 FACE_DEFAULT_ACCOUNT/default。"""
        from core.utils.account_identity import normalize_manager_user_id
        from core.utils.face_jwt import is_reserved_account_id

        account_id = (self._face_cfg().get("account_id") or "").strip()
        if is_reserved_account_id(account_id):
            return None
        return normalize_manager_user_id(account_id)

    def _account_from_claims(self, claims):
        from core.utils.account_identity import normalize_manager_user_id
        token_account = normalize_manager_user_id(str((claims or {}).get('account_id') or '').strip())
        cfg_account = self._resolve_account_id()
        # Preserve legacy pinned deployments. New multi-tenant mode never falls back.
        mode = self._face_cfg().get('account_mode', 'single_tenant' if cfg_account else 'multi_tenant')
        if mode == 'multi_tenant':
            return (token_account, None) if token_account else (None, 'missing')
        if mode != 'single_tenant':
            return None, 'missing'
        if token_account and cfg_account and token_account != cfg_account:
            return None, 'mismatch'
        account = token_account or cfg_account
        return (account, None) if account else (None, 'missing')

    def _build_face_jwt(
        self, device_id: str = "vision", account_id: Optional[str] = None
    ) -> Optional[str]:
        """签发 face-api HS256 JWT。缺密钥或缺 account_id 时返回 None（上层应拒绝）。"""
        from core.utils.face_jwt import build_face_jwt_from_config, is_reserved_account_id

        aid = (account_id or "").strip() or (self._resolve_account_id() or "")
        if not aid or is_reserved_account_id(aid):
            self.logger.bind(tag=TAG).error(
                "识人缺少合法 account_id：禁止使用 default"
            )
            return None
        return build_face_jwt_from_config(
            self.config, account_id=aid, device_id=device_id or "vision"
        )

    async def _call_face_identify(self, image_data, device_id='vision', account_id=None):
        cfg = self._face_cfg()
        if not cfg.get('enabled', True) or not cfg.get('identify_url'):
            return self._face_error('service_unavailable', 503)
        aid, error = self._account_from_claims({'account_id': account_id})
        if error:
            return self._face_error('service_unavailable', 503)
        token = self._build_face_jwt(device_id, aid) if cfg.get('jwt_secret') else None
        if cfg.get('jwt_secret') and not token:
            return self._face_error('service_unavailable', 503)
        headers = {'Authorization':'Bearer ' + token} if token else {}
        try:
            form = aiohttp.FormData()
            form.add_field('image', image_data, filename='face.jpg', content_type='image/jpeg')
            timeout = aiohttp.ClientTimeout(total=float(cfg.get('timeout', 2.0)))
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(cfg['identify_url'], data=form, headers=headers) as resp:
                    if resp.status != 200:
                        reason = 'upstream_auth_rejected' if resp.status in (401,403) else 'upstream_error'
                        return self._face_error(reason, 502, resp.status)
                    result = await resp.json()
        except asyncio.TimeoutError:
            return self._face_error('upstream_timeout', 504)
        except (ValueError, aiohttp.ContentTypeError):
            return self._face_error('upstream_invalid_response', 502)
        except aiohttp.ClientError:
            return self._face_error('upstream_unreachable', 502)
        if not isinstance(result, dict):
            return self._face_error('upstream_invalid_response', 502)
        status = result.get('status')
        if status not in {'known','unknown','empty','no_face','ambiguous','error'}:
            return self._face_error('upstream_invalid_response', 502)
        if status == 'error':
            return self._face_error('upstream_error', 502, 200)
        if status != 'known':
            reason = result.get('reason')
            allowed = {'no_content','no_match','no_face','multiple_faces','ambiguous'}
            return {'status':status, 'confidence':0.0, 'reason':reason if reason in allowed else IDENTIFY_CLIENT_HINTS[status][0]}
        try:
            confidence = float(result.get('confidence'))
        except (ValueError, TypeError):
            return self._face_error('upstream_invalid_response', 502)
        if not math.isfinite(confidence) or not 0 <= confidence <= 1:
            return self._face_error('upstream_invalid_response', 502)
        if confidence < self._identity_threshold():
            return {'status':'unknown', 'confidence':0.0, 'reason':'no_match'}
        user_id = result.get('user_id')
        name = result.get('name') or result.get('display_name')
        if not isinstance(user_id, str) or not user_id.strip() or not isinstance(name, str) or not name.strip():
            return self._face_error('upstream_invalid_response', 502)
        return {'status':'known', 'user_id':user_id.strip(),
                'display_name':re.sub(r'[\x00-\x1f\x7f-\x9f]', '', name).strip()[:30],
                'confidence':round(confidence,3)}

    def _public_identify_payload(self, result):
        status = result.get('status', 'error')
        if status == 'known':
            return {key:result[key] for key in ('status','user_id','display_name','confidence')}
        reason, message = IDENTIFY_CLIENT_HINTS.get(status, ('upstream_error', '人脸识别暂时不可用'))
        payload = {'status':status, 'confidence':0.0, 'reason':result.get('reason') or reason, 'message':message}
        if status == 'error':
            from core.utils.tool_result import DeviceToolError
            payload['message'] = DeviceToolError(payload['reason']).user_message
            payload['success'] = False
            payload['errorCode'] = payload['reason']
        if 'upstream_http_status' in result:
            payload['upstream_http_status'] = result['upstream_http_status']
        return payload

    @staticmethod
    def _face_error(reason, http_status, upstream_status=None):
        result = {'status':'error', 'confidence':0.0, 'reason':reason, 'http_status':http_status}
        if upstream_status is not None:
            result['upstream_http_status'] = upstream_status
        return result

    def _authorize_vision(self, request):
        ok, claims = self._verify_auth_claims(request)
        if not ok or not isinstance(claims, dict):
            self._log_vision_auth_reject(
                request,
                "authentication_failed",
                client_reason="authentication_failed",
            )
            raise VisionRequestError(401, "authentication_failed", "authentication_failed")
        device = request.headers.get("Device-Id", "")
        claims_device = claims.get("device_id") or ""
        if not device or device != claims_device:
            self._log_vision_auth_reject(
                request,
                "device_mismatch",
                header_device_present=bool(device),
                claims_device_present=bool(claims_device),
                header_device=device or "-",
                claims_device=claims_device or "-",
            )
            raise VisionRequestError(403, "permission_denied", "device_mismatch")
        scope = claims.get("scope")
        legacy = self._face_cfg().get("allow_legacy_vision_tokens", True)
        if scope != "vision" and not (scope is None and legacy):
            self._log_vision_auth_reject(
                request,
                "scope_mismatch",
                scope_present=scope is not None,
                legacy_allowed=bool(legacy),
            )
            raise VisionRequestError(403, "permission_denied", "scope_mismatch")
        account, error = self._account_from_claims(claims)
        if error:
            if error == "mismatch":
                self._log_vision_auth_reject(request, "account_mismatch")
                raise VisionRequestError(403, "permission_denied", "account_mismatch")
            self._log_vision_auth_reject(
                request,
                "account_missing",
                client_reason="service_unavailable",
            )
            raise VisionRequestError(503, "service_unavailable", "account_missing")
        self._vision_session(request, claims)
        return claims, device, account

    def _vision_session(self, request, claims, form_session=""):
        signed = claims.get("session_id") or ""
        header = request.headers.get("Session-Id", "")
        values = [v for v in (signed, header, form_session) if v]
        invalid = any(not isinstance(v, str) or len(v) > 256 for v in values)
        inconsistent = len(set(values)) > 1
        if invalid or inconsistent:
            self._log_vision_auth_reject(
                request,
                "session_mismatch",
                session_consistent=False,
                token_session_present=bool(signed),
                header_session_present=bool(header),
                form_session_present=bool(form_session),
                session_value_invalid=invalid,
            )
            raise VisionRequestError(403, "permission_denied", "session_mismatch")
        # Old tokens remain usable for one-shot images, but cannot address a shared cache.
        return signed

    async def _read_vision_part(self, field, limit=MAX_FILE_SIZE):
        data = bytearray()
        if not hasattr(field, 'read_chunk'):
            raw = await field.read()
            if len(raw) > limit:
                raise VisionRequestError(413, 'payload_too_large')
            return raw
        while True:
            chunk = await field.read_chunk(size=16384)
            if not chunk:
                break
            if len(data) + len(chunk) > limit:
                raise VisionRequestError(413, 'payload_too_large')
            data.extend(chunk)
        return bytes(data)

    def _vision_error_response(self, exc):
        result = self._face_error(exc.reason, exc.status)
        response = web.json_response(self._public_identify_payload(result), status=exc.status)
        self._add_cors_headers(response)
        return response

    async def _identify_face_for_explain(
        self,
        image_data: bytes,
        device_id: str = "vision",
        account_id: Optional[str] = None,
    ) -> Optional[Dict[str, str]]:
        """explain 路径：返回 {user_id, display_name} 或 None。保留 user_id。"""
        result = await self._call_face_identify(
            image_data, device_id, account_id=account_id
        )
        if result.get("status") != "known":
            return None
        self.logger.bind(tag=TAG).info(
            f"人脸识别命中: user_id={result.get('user_id')}, "
            f"name={result.get('display_name')}, confidence={result.get('confidence')}"
        )
        return {
            "user_id": result["user_id"],
            "display_name": result["display_name"],
        }

    def _create_error_response(self, message: str) -> dict:
        """创建统一的错误响应格式"""
        return {"success": False, "message": message}

    def _verify_auth_token(self, request) -> Tuple[bool, Optional[str]]:
        """验证认证token，返回 (ok, device_id)。"""
        ok, claims = self._verify_auth_claims(request)
        if not ok or not claims:
            return False, None
        return True, claims.get("device_id")

    def _verify_auth_claims(self, request) -> Tuple[bool, Optional[dict]]:
        """验证 token 并返回完整 claims（含 account_id/scope）。"""
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return False, None
        token = auth_header[7:]
        return self.auth.verify_token_claims(token)

    async def handle_identify(self, request):
        try:
            claims, device_id, account_id = self._authorize_vision(request)
            reader = await request.multipart()
            image_data = None
            for _ in range(12):
                part = await reader.next()
                if part is None:
                    break
                data = await self._read_vision_part(part, MAX_FILE_SIZE if part.name in ('image','file') else 4096)
                if part.name == 'session_id':
                    self._vision_session(request, claims, data.decode('utf-8'))
                elif part.name in ('image','file'):
                    if image_data is not None:
                        raise VisionRequestError(400, 'invalid_image')
                    image_data = data
            else:
                raise VisionRequestError(400, 'invalid_multipart')
            if not image_data or not is_valid_image_file(image_data):
                raise VisionRequestError(400, 'invalid_image')
            result = await self._call_face_identify(image_data, device_id, account_id=account_id)
            payload = self._public_identify_payload(result)
            response = web.json_response(payload, status=result.get('http_status', 200))
            self.logger.bind(tag=TAG).info(f'[FACE_IDENTIFY] status={payload["status"]} http={response.status} reason={payload.get("reason", "-")}')
            self._add_cors_headers(response)
            return response
        except VisionRequestError as exc:
            return self._vision_error_response(exc)
        except (ValueError, UnicodeError):
            return self._vision_error_response(VisionRequestError(400, 'invalid_multipart'))
        except Exception as exc:
            self.logger.bind(tag=TAG).error(f'Identify failed type={type(exc).__name__}')
            return self._vision_error_response(VisionRequestError(500, 'service_unavailable'))

    async def handle_post(self, request):
        """处理 MCP Vision POST 请求（视觉问答，可调用 VLM）"""
        response = None  # 初始化response变量
        image_data = None
        try:
            claims, device_id, explain_account_id = self._authorize_vision(request)
            client_id = request.headers.get('Client-Id', '')
            # 解析multipart/form-data请求
            reader = await request.multipart()

            # 读取question字段（第一个 part）
            question_field = await reader.next()
            if question_field is None:
                raise ValueError("缺少问题字段")
            question = (await self._read_vision_part(question_field, 16384)).decode('utf-8')
            self.logger.bind(tag=TAG).debug(f"Question: {question}")

            # 读取 session_id 字段（第二个 part，可选）
            session_id = self._vision_session(request, claims)
            next_field = await reader.next()
            if next_field is not None and next_field.name == "session_id":
                form_session = (await self._read_vision_part(next_field, 4096)).decode('utf-8')
                session_id = self._vision_session(request, claims, form_session)
                self.logger.bind(tag=TAG).debug(f"Session ID: {session_id}")
                # session_id 读完后，继续读下一个 part（图片）
                image_field = await reader.next()
            else:
                # 没有 session_id，next_field 就是图片字段（或 None）
                image_field = next_field

            # 处理图片：新拍照 or 追问复用缓存
            image_base64 = None
            if image_field is not None:
                # 有图片：读取并缓存
                image_data = await self._read_vision_part(image_field)
                if not image_data:
                    raise ValueError("图片数据为空")

                # 检查文件大小
                if len(image_data) > MAX_FILE_SIZE:
                    raise ValueError(
                        f"图片大小超过限制，最大允许{MAX_FILE_SIZE/1024/1024}MB"
                    )

                # 检查文件格式
                if not is_valid_image_file(image_data):
                    raise ValueError(
                        "不支持的文件格式，请上传有效的图片文件（支持JPEG、PNG、GIF、BMP、TIFF、WEBP格式）"
                    )

                image_base64 = base64.b64encode(image_data).decode("utf-8")

                # 存入 session 缓存，支持后续追问
                # 缓存 key 绑定 device_id，防止同 session_id 跨设备串图
                if session_id:
                    cache_manager.set(
                        CacheType.IMAGE_SESSION,
                        self._image_session_key(device_id, session_id, explain_account_id),
                        image_base64,
                    )
                    self.logger.bind(tag=TAG).debug(
                        f"图片已缓存，device_id={device_id} session_id={session_id}"
                    )
            else:
                # 无图片：追问场景，从缓存取原图（必须与写入同一 device_id）
                if session_id:
                    image_base64 = cache_manager.get(
                        CacheType.IMAGE_SESSION,
                        self._image_session_key(device_id, session_id, explain_account_id),
                    )
                if not image_base64:
                    raise ValueError("追问时未找到原图缓存，请重新拍照")

            # ── 人脸识别增强：有照片时先查 face-api（保留 user_id）──
            face_hit: Optional[Dict[str, str]] = None
            if image_data is not None and explain_account_id:
                face_hit = await self._identify_face_for_explain(
                    image_data, device_id, account_id=explain_account_id
                )

            if face_hit:
                face_context = (
                    "请优先信任本地人脸数据库的识别结果。本地人脸库已确认图中注册用户身份，基于相似度匹配判定为"
                    f'“{face_hit["display_name"]}”（user_id={face_hit["user_id"]}）。'
                    "回答任何与身份相关的问题时，必须以此判定为准，"
                    "不得自行猜测或假定任何他人的姓名、公众人物身份或主体角色。\n"
                    "如果本地人脸库未提供上述信息，则仅基于视觉描述回答。请勿擅自猜测或推断人的姓名。\n"
                    "用户问题："
                )
                self.logger.bind(tag=TAG).debug("已嵌入人脸识别结果")
                rebuilt_question = f"{face_context}{question}"
            else:
                rebuilt_question = question
                self.logger.bind(tag=TAG).debug("人脸识别未触发或未识别")

            # 如果开启了智控台，则从智控台获取模型配置
            current_config = copy.deepcopy(self.config)
            read_config_from_api = current_config.get("read_config_from_api", False)
            if read_config_from_api:
                current_config = get_private_config_from_api(
                    current_config,
                    device_id,
                    client_id,
                )

            select_vllm_module = current_config["selected_module"].get("VLLM")
            if not select_vllm_module:
                raise ValueError("您还未设置默认的视觉分析模块")

            vllm_type = (
                select_vllm_module
                if "type" not in current_config["VLLM"][select_vllm_module]
                else current_config["VLLM"][select_vllm_module]["type"]
            )

            if not vllm_type:
                raise ValueError(f"无法找到VLLM模块对应的供应器{vllm_type}")

            vllm = create_instance(
                vllm_type, current_config["VLLM"][select_vllm_module]
            )

            result = vllm.response(rebuilt_question, image_base64)

            return_json = {
                "success": True,
                "action": Action.RESPONSE.name,
                "response": result,
            }

            response = web.Response(
                text=json.dumps(return_json, separators=(",", ":")),
                content_type="application/json",
            )
        except VisionRequestError as exc:
            return self._vision_error_response(exc)
        except ValueError:
            return self._vision_error_response(VisionRequestError(400, 'invalid_request'))
        except Exception as exc:
            self.logger.bind(tag=TAG).error(f'Explain failed type={type(exc).__name__}')
            return self._vision_error_response(VisionRequestError(500, 'service_unavailable'))
        self._add_cors_headers(response)
        return response

    async def handle_get(self, request):
        """处理 MCP Vision GET 请求"""
        try:
            vision_explain = get_vision_url(self.config)
            if vision_explain and len(vision_explain) > 0 and "null" != vision_explain:
                message = (
                    f"MCP Vision 接口运行正常，视觉解释接口地址是：{vision_explain}"
                )
            else:
                message = "MCP Vision 接口运行不正常，请打开data目录下的.config.yaml文件，找到【server.vision_explain】，设置好地址"

            response = web.Response(text=message, content_type="text/plain")
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"MCP Vision GET请求异常: {e}")
            return_json = self._create_error_response("服务器内部错误")
            response = web.Response(
                text=json.dumps(return_json, separators=(",", ":")),
                content_type="application/json",
            )
        finally:
            self._add_cors_headers(response)
            return response

    def _add_cors_headers(self, response):
        """添加CORS头信息"""
        response.headers["Access-Control-Allow-Headers"] = (
            "client-id, content-type, device-id, authorization, session-id"
        )
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Origin"] = "*"
