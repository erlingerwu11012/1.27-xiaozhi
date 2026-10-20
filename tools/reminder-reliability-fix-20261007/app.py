# 强制 UTF-8 编码，避免 'ascii' codec can't encode 错误导致音频/文本损坏
import sys
import io
try:
    if getattr(sys.stdout, 'buffer', None) and (sys.stdout.encoding != 'utf-8' or sys.stdout.encoding is None):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    if getattr(sys.stderr, 'buffer', None) and (sys.stderr.encoding != 'utf-8' or sys.stderr.encoding is None):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
except (AttributeError, OSError):
    pass  # 某些环境（如重定向）可能无 buffer，忽略

import uuid
import signal
import asyncio
from aioconsole import ainput
from config.settings import load_config
from config.logger import setup_logging
from core.utils.util import get_local_ip, validate_mcp_endpoint
from core.http_server import SimpleHttpServer
from core.websocket_server import WebSocketServer
from core.utils.util import check_ffmpeg_installed
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from core.utils import service_auth

TAG = __name__
logger = setup_logging()

# HTTP 设备指令接口：FastAPI，仅 /api/v1/device/send（无 /api/v1/broadcast）
broadcast_app = FastAPI(title="Xiaozhi Device API")


def _device_send_unauthorized(reason: str) -> JSONResponse:
    """401；日志仅写 reason code，不记录 Authorization / token / secret。"""
    logger.bind(tag=TAG).warning(f"[device_send] unauthorized reason={reason}")
    return JSONResponse(
        status_code=401,
        content={"ok": False, "error": "Unauthorized"},
    )


def _device_send_bad_request(reason: str, error: str) -> JSONResponse:
    logger.bind(tag=TAG).warning(f"[device_send] bad_request reason={reason}")
    return JSONResponse(
        status_code=400,
        content={"ok": False, "error": error},
    )


@broadcast_app.post("/api/v1/device/send")
async def api_device_send(request: Request):
    """
    内部服务定向下行：{ "device_id": "...", "payload": {...}, "session_id": 可选 }。
    鉴权：仅 Authorization: Bearer <manager-api.secret>；禁止 query/body 传密。
    禁止 user_id/account_id 批量下发；可选 session_id 只能是该设备 current session。
    """
    # 1) query 出现鉴权类字段 → 401，零 send（先于任何 send）
    if service_auth.query_has_forbidden_auth_keys(request.query_params):
        return _device_send_unauthorized("auth_in_query")

    # 2) 专用 secret 未配置 / 占位 → fail-closed 401
    cfg = getattr(request.app.state, "config", None) or {}
    expected, secret_reason = service_auth.get_service_secret(cfg)
    if not expected:
        return _device_send_unauthorized(secret_reason or "secret_unconfigured")

    # 3) 仅 Bearer header
    presented = service_auth.extract_bearer_token(
        request.headers.get("authorization") or request.headers.get("Authorization")
    )
    if not presented:
        return _device_send_unauthorized("missing_bearer")
    if not service_auth.verify_bearer_service_secret(presented, expected):
        return _device_send_unauthorized("secret_mismatch")

    try:
        body = await request.json()
    except Exception:
        return _device_send_bad_request("invalid_json", "Invalid JSON body")
    if not isinstance(body, dict):
        return _device_send_bad_request("invalid_json", "Invalid JSON body")

    # 4) body 鉴权类字段 → 401
    auth_body_reason = service_auth.body_auth_reject_reason(body)
    if auth_body_reason:
        return _device_send_unauthorized(auth_body_reason)

    # 5) 账号级下发字段 → 400
    if service_auth.body_has_account_dispatch_keys(body):
        return _device_send_bad_request(
            "account_dispatch_forbidden",
            "user_id/account_id batch dispatch is forbidden",
        )

    # 6) 仅允许 device_id / payload / session_id
    if service_auth.body_has_disallowed_business_keys(body):
        return _device_send_bad_request(
            "disallowed_body_keys",
            "Only device_id, payload, and optional session_id are allowed",
        )

    device_id = body.get("device_id")
    payload = body.get("payload")
    session_id = body.get("session_id")
    if device_id is not None:
        device_id = str(device_id).strip()
    if not device_id:
        return _device_send_bad_request("missing_device_id", "Missing device_id")
    if not isinstance(payload, dict):
        return _device_send_bad_request(
            "invalid_payload", "Missing or invalid payload (must be object)"
        )
    if session_id is not None:
        session_id = str(session_id).strip() or None
    ws_server = getattr(request.app.state, "ws_server", None)
    if ws_server is None:
        return JSONResponse(
            status_code=503,
            content={"ok": False, "error": "WebSocket server not ready"},
        )
    ok = await ws_server.send_json_to_device(
        device_id, payload, session_id=session_id
    )
    return JSONResponse({"ok": ok, "sent": ok})


@broadcast_app.post("/api/v1/device/revoke")
async def api_device_revoke(request: Request):
    """
    内部服务：吊销单个 device_id 的在线连接（主 WS + RC）。
    鉴权：Authorization Bearer <manager-api.secret>。
    Body：{"device_id": "...", "credential_version": 可选, "status": 可选}
    禁止 user_id/account_id；禁止影响其他设备。
    """
    if service_auth.query_has_forbidden_auth_keys(request.query_params):
        return _device_send_unauthorized("auth_in_query")

    cfg = getattr(request.app.state, "config", None) or {}
    expected, secret_reason = service_auth.get_service_secret(cfg)
    if not expected:
        return _device_send_unauthorized(secret_reason or "secret_unconfigured")

    presented = service_auth.extract_bearer_token(
        request.headers.get("authorization") or request.headers.get("Authorization")
    )
    if not presented:
        return _device_send_unauthorized("missing_bearer")
    if not service_auth.verify_bearer_service_secret(presented, expected):
        return _device_send_unauthorized("secret_mismatch")

    try:
        body = await request.json()
    except Exception:
        return _device_send_bad_request("invalid_json", "Invalid JSON body")
    if not isinstance(body, dict):
        return _device_send_bad_request("invalid_json", "Invalid JSON body")

    auth_body_reason = service_auth.body_auth_reject_reason(body)
    if auth_body_reason:
        return _device_send_unauthorized(auth_body_reason)

    if service_auth.body_has_account_dispatch_keys(body):
        return _device_send_bad_request(
            "account_dispatch_forbidden",
            "user_id/account_id batch dispatch is forbidden",
        )

    allowed = {"device_id", "credential_version", "status"}
    extra = set(body.keys()) - allowed
    if extra:
        return _device_send_bad_request(
            "disallowed_body_keys",
            "Only device_id and optional credential_version/status are allowed",
        )

    device_id = body.get("device_id")
    if device_id is not None:
        device_id = str(device_id).strip()
    if not device_id:
        return _device_send_bad_request("missing_device_id", "Missing device_id")

    cred_ver = body.get("credential_version")
    status = body.get("status")
    if status is not None:
        status = str(status).strip() or None

    ws_server = getattr(request.app.state, "ws_server", None)
    if ws_server is None:
        return JSONResponse(
            status_code=503,
            content={"ok": False, "error": "WebSocket server not ready"},
        )
    result = await ws_server.revoke_device_connections(
        device_id, credential_version=cred_ver, status=status
    )
    return JSONResponse(
        {
            "ok": bool(result.get("ok")),
            "closed_main": int(result.get("closed_main") or 0),
            "closed_rc": int(result.get("closed_rc") or 0),
        }
    )


async def wait_for_exit() -> None:
    """
    阻塞直到收到 Ctrl‑C / SIGTERM。
    - Unix: 使用 add_signal_handler
    - Windows: 依赖 KeyboardInterrupt
    """
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    if sys.platform != "win32":  # Unix / macOS
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop_event.set)
        await stop_event.wait()
    else:
        # Windows：await一个永远pending的fut，
        # 让 KeyboardInterrupt 冒泡到 asyncio.run，以此消除遗留普通线程导致进程退出阻塞的问题
        try:
            await asyncio.Future()
        except KeyboardInterrupt:  # Ctrl‑C
            pass


async def monitor_stdin():
    """监控标准输入，消费回车键"""
    while True:
        await ainput()  # 异步等待输入，消费回车


def _install_websocket_handshake_exception_handler(loop):
    """
    安装 WebSocket 握手异常的特殊处理：EOFError、InvalidMessage 通常来自健康检查、代理探测、
    或未发送完整 HTTP Upgrade 即断开的连接，单独记日志，不作为业务错误。
    """
    import websockets.exceptions
    _original_handler = loop.get_exception_handler() or loop.default_exception_handler

    def _handler(loop_, context):
        exc = context.get("exception")
        if exc is not None:
            if isinstance(exc, EOFError):
                logger.bind(tag=TAG).warning(
                    "WebSocket 握手中止：连接在读取 HTTP 请求前关闭（可能为健康检查、代理探测或网络断开），非业务错误"
                )
                return
            if isinstance(exc, websockets.exceptions.InvalidMessage):
                logger.bind(tag=TAG).warning(
                    "WebSocket 握手中止：未收到合法 HTTP Upgrade 请求（可能为健康检查、代理探测），非业务错误"
                )
                return
        _original_handler(context)

    loop.set_exception_handler(_handler)


async def main():
    check_ffmpeg_installed()
    _install_websocket_handshake_exception_handler(asyncio.get_running_loop())
    config = load_config()
    vad_mod = (config.get("selected_module") or {}).get("VAD")
    vad_cfg = ((config.get("VAD") or {}).get(vad_mod) or {}) if vad_mod else {}
    logger.bind(tag=TAG).info(
        "audio_clock_compat enabled={} vad_min_silence_duration_ms={}",
        config.get("audio_clock_compat_enabled"),
        vad_cfg.get("min_silence_duration_ms"),
    )
    try:
        from core.utils.trace_log import configure as configure_trace_log

        configure_trace_log(config)
        from core.utils.trace_log import emit as trace_emit

        trace_emit(
            "gateway.inventory",
            None,
            {
                "note": "xiaozhi does not write 3000/3001/3011 ledgers; existing fields only",
                "one_api_3000": {
                    "listen": "docker logs one-api",
                    "fields_seen": [
                        "RequestId",
                        "UserId",
                        "TokenName",
                        "ModelName",
                        "Quota",
                        "PromptTokens",
                        "CompletionTokens",
                        "ChannelId",
                        "ElapsedTime",
                        "IsStream",
                    ],
                    "not_logged": ["token_value", "api_key"],
                    "gap": "ModelRatio has no qwen-plus; HTTP uses default ratio (not adjusted this round)",
                },
                "realtime_3001": {
                    "listen": "journalctl -u one-api-realtime",
                    "fields_seen": ["request id", "debit rejected", "REFUND REQUIRED", "log_id"],
                    "gap": "xiaozhi ASR WS does not receive gateway bill_id/request_id unless present in session.created",
                },
                "bailian_3011": {
                    "listen": "journalctl -u one-api-bailian",
                    "fields_seen_in_binary": ["bill_id", "X-Oneapi-Request-Id", "settlement pending"],
                    "gap": "no per-event journal fields unless a request is made; do not infer ledger from TTS task_id",
                },
            },
        )
    except Exception:
        logger.bind(tag=TAG).warning("trace_log 初始化失败，对话不受影响")

    # auth_key优先级：配置文件server.auth_key > manager-api.secret > 自动生成
    # auth_key用于jwt认证，比如视觉分析接口的jwt认证、ota接口的token生成与websocket认证
    # 获取配置文件中的auth_key
    auth_key = config["server"].get("auth_key", "")
    
    # 验证auth_key，无效则尝试使用manager-api.secret
    if not auth_key or len(auth_key) == 0 or "你" in auth_key:
        auth_key = config.get("manager-api", {}).get("secret", "")
        # 验证secret，无效则生成随机密钥
        if not auth_key or len(auth_key) == 0 or "你" in auth_key:
            auth_key = str(uuid.uuid4().hex)
    
    config["server"]["auth_key"] = auth_key

    # Reminder Voice 独立签名密钥预检（禁止复用 auth_key / FACE_JWT）
    try:
        from core.utils.reminder_voice_store import (
            validate_reminder_voice_signing_at_startup,
        )

        validate_reminder_voice_signing_at_startup(config)
    except RuntimeError as exc:
        logger.bind(tag=TAG).error(str(exc))
        raise

    # 人脸采集 upload_token 独立签名密钥预检（禁止复用 auth_key / FACE_JWT）
    try:
        from core.utils.face_enrollment_capability import (
            validate_face_enrollment_signing_at_startup,
        )

        validate_face_enrollment_signing_at_startup(config)
    except RuntimeError as exc:
        logger.bind(tag=TAG).error(str(exc))
        raise

    # 添加 stdin 监控任务
    stdin_task = asyncio.create_task(monitor_stdin())

    # 启动 WebSocket 服务器
    ws_server = WebSocketServer(config)
    broadcast_app.state.ws_server = ws_server
    broadcast_app.state.config = config
    ws_task = asyncio.create_task(ws_server.start())
    # 启动 Simple http 服务器
    ota_server = SimpleHttpServer(config)
    ota_task = asyncio.create_task(ota_server.start())
    # 启动 FastAPI 设备指令接口（HTTP POST /api/v1/device/send）
    import uvicorn
    broadcast_port = int(config.get("server", {}).get("broadcast_http_port", 8006))
    broadcast_config = uvicorn.Config(
        broadcast_app, host="127.0.0.1", port=broadcast_port, log_level="info"
    )
    broadcast_server = uvicorn.Server(broadcast_config)
    broadcast_task = asyncio.create_task(broadcast_server.serve())

    read_config_from_api = config.get("read_config_from_api", False)
    port = int(config["server"].get("http_port", 8003))
    if not read_config_from_api:
        logger.bind(tag=TAG).info(
            "OTA接口是\t\thttp://{}:{}/xiaozhi/ota/",
            get_local_ip(),
            port,
        )
    logger.bind(tag=TAG).info(
        "视觉分析接口是\thttp://{}:{}/mcp/vision/explain",
        get_local_ip(),
        port,
    )
    mcp_endpoint = config.get("mcp_endpoint", None)
    if mcp_endpoint is not None and "你" not in mcp_endpoint:
        # 校验MCP接入点格式
        if validate_mcp_endpoint(mcp_endpoint):
            logger.bind(tag=TAG).info("mcp接入点是\t{}", mcp_endpoint)
            # 将mcp计入点地址转成调用点
            mcp_endpoint = mcp_endpoint.replace("/mcp/", "/call/")
            config["mcp_endpoint"] = mcp_endpoint
        else:
            logger.bind(tag=TAG).error("mcp接入点不符合规范")
            config["mcp_endpoint"] = "你的接入点 websocket地址"

    # 获取WebSocket配置，使用安全的默认值
    websocket_port = 8000
    server_config = config.get("server", {})
    if isinstance(server_config, dict):
        websocket_port = int(server_config.get("port", 8000))

    logger.bind(tag=TAG).info(
        "Websocket地址是\tws://{}:{}/xiaozhi/v1/",
        get_local_ip(),
        websocket_port,
    )
    logger.bind(tag=TAG).info(
        "设备指令接口地址是\thttp://{}:{}/api/v1/device/send",
        get_local_ip(),
        broadcast_port,
    )

    logger.bind(tag=TAG).info(
        "=======上面的地址是websocket协议地址，请勿用浏览器访问======="
    )
    logger.bind(tag=TAG).info(
        "如想测试websocket请用谷歌浏览器打开test目录下的test_page.html"
    )
    logger.bind(tag=TAG).info(
        "=============================================================\n"
    )

    try:
        await wait_for_exit()  # 阻塞直到收到退出信号
    except asyncio.CancelledError:
        print("任务被取消，清理资源中...")
    finally:
        # 取消所有任务（关键修复点）
        stdin_task.cancel()
        ws_task.cancel()
        if ota_task:
            ota_task.cancel()
        if broadcast_task:
            broadcast_task.cancel()

        # 等待任务终止（必须加超时）
        tasks = [stdin_task, ws_task]
        if ota_task:
            tasks.append(ota_task)
        if broadcast_task:
            tasks.append(broadcast_task)
        await asyncio.wait(tasks, timeout=3.0, return_when=asyncio.ALL_COMPLETED)
        print("服务器已关闭，程序退出。")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("手动中断，程序终止。")
