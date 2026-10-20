"""Reminder Control 短时 WSS：仅处理提醒语音请求，不进入主对话。

鉴权：复用设备配对 AuthManager（Device-Id / Client-Id / Authorization），
不得使用 FACE_JWT_SECRET 或 vision 短期 token。
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from config.logger import setup_logging
from core.auth import AuthManager, AuthenticationError
from core.utils.modules_initialize import initialize_tts
from core.utils.reminder_audit import audit_event
from core.utils.reminder_voice import process_reminder_voice_request

TAG = __name__
logger = setup_logging()

ALLOWED_INBOUND = frozenset(
    {
        "reminder_voice_request",
        "reminder_event",
        "ping",
    }
)
MAX_TEXT_BYTES = 8 * 1024
DEFAULT_IDLE_TIMEOUT_SEC = 20
DEFAULT_MAX_CONNS_PER_DEVICE = 2
CHANNEL_KIND = "reminder_control"


class ReminderControlContext:
    """轻量连接上下文：具备 config/llm/tts，无 ASR/对话状态。"""

    def __init__(
        self,
        *,
        websocket,
        config: dict,
        device_id: str,
        client_id: str,
        account_id: str,
        llm=None,
        purpose: str = "reminder_control",
    ):
        self.websocket = websocket
        self.config = config
        self.device_id = device_id
        self.client_id = client_id
        self.account_id = account_id
        self.session_id = f"rc-{uuid.uuid4().hex[:16]}"
        self.headers = {
            "device-id": device_id,
            "client-id": client_id,
        }
        self.llm = llm
        self.tts = None
        self.purpose = purpose
        self.is_reminder_control = True
        self.logger = setup_logging()
        self.last_activity = time.time()
        # 短时通道：受控独立注册表（见 ReminderControlManager）
        self.outbound_mode = "local_active"
        self.channel_kind = CHANNEL_KIND
        self.local_active_registry = None
        self.parent_main_session_id = None
        self.correlation_id = self.session_id
        self.superseded = False
        self._outbound_closed = False
        self.server = None

    def ensure_tts(self):
        if self.tts is None:
            try:
                self.tts = initialize_tts(self.config)
            except Exception as exc:
                self.logger.bind(tag=TAG).warning(
                    f"[reminder_control] tts_init_failed err_type={type(exc).__name__}"
                )
                self.tts = None
        return self.tts

    async def send_current_guarded(
        self,
        data,
        *,
        command: str = None,
        msg_type: str = None,
        task_id=None,
    ) -> bool:
        """Reminder Control 出站：经统一守卫；superseded 时 fail closed。"""
        from core.utils.device_outbound import guarded_ws_send

        return await guarded_ws_send(
            self,
            data,
            command=command,
            msg_type=msg_type,
            task_id=task_id,
        )


class ReminderControlManager:
    """Reminder Control 受控注册表；与 WebSocketServer 共享中心 per-device lock。

    隔离键：(device_id, channel_kind, rc_session_id, parent_main_session_id)
    """

    def __init__(
        self,
        max_per_device: int = DEFAULT_MAX_CONNS_PER_DEVICE,
        *,
        device_locks: Optional[Dict[str, asyncio.Lock]] = None,
        main_host=None,
    ):
        self.max_per_device = max(1, int(max_per_device))
        self._connections: Dict[str, Dict[str, Any]] = {}
        self._current_sessions: Dict[str, str] = {}
        self._device_send_locks = device_locks if device_locks is not None else {}
        self._main_host = main_host

    def _get_device_send_lock(self, device_id: str) -> asyncio.Lock:
        lock = self._device_send_locks.get(device_id)
        if lock is None:
            lock = asyncio.Lock()
            self._device_send_locks[device_id] = lock
        return lock

    def shares_device_lock_with(self, other) -> bool:
        """测试/诊断：是否与 other 使用同一 lock 字典。"""
        if other is None:
            return False
        other_locks = getattr(other, "_device_send_locks", None)
        return other_locks is self._device_send_locks

    def _connection_key(self, ctx) -> str:
        sid = getattr(ctx, "session_id", None)
        if not sid:
            raise ValueError("ReminderControlContext 缺少 session_id")
        return sid

    def _resolve_parent_main_session_unlocked(self, device_id: str) -> Optional[str]:
        host = self._main_host
        if host is None:
            return None
        getter = getattr(host, "get_current_main_session_id", None)
        if not callable(getter):
            return None
        parent = getter(device_id)
        if not parent:
            return None
        checker = getattr(host, "is_main_session_current", None)
        if callable(checker) and not checker(device_id, parent):
            return None
        return parent

    def _main_generation_allows_rc(self, device_id: str, ctx) -> bool:
        parent = getattr(ctx, "parent_main_session_id", None)
        if not parent:
            return False
        host = self._main_host
        if host is None:
            return False
        checker = getattr(host, "is_main_session_current", None)
        if not callable(checker):
            return False
        return bool(checker(device_id, parent))

    def is_current_connection(self, device_id: str, handler) -> bool:
        if not device_id:
            return False
        if not self._main_generation_allows_rc(device_id, handler):
            return False
        try:
            key = self._connection_key(handler)
        except ValueError:
            return False
        if self._current_sessions.get(device_id) != key:
            return False
        bag = self._connections.get(device_id)
        return bool(bag) and bag.get(key) is handler

    def _mark_rc_invalid(self, ctx, *, reason: str = "superseded") -> None:
        ctx.superseded = True
        ctx._outbound_closed = True
        try:
            from core.utils.device_outbound import invalidate_connection

            invalidate_connection(ctx, reason=reason)
        except Exception:
            pass

    def _best_effort_close_rc(self, device_id: str, ctx) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        async def _close():
            ws = getattr(ctx, "websocket", None)
            if ws is None:
                return
            try:
                await ws.close()
            except Exception:
                pass

        try:
            loop.create_task(_close())
        except Exception:
            pass

    def sync_rc_to_main_generation(self, device_id: str, main_session_id: str) -> None:
        """主连接切代（调用方已持中心锁）：失效 parent != 新 main 的 RC。"""
        bag = self._connections.get(device_id) or {}
        for _rc_key, ctx in list(bag.items()):
            parent = getattr(ctx, "parent_main_session_id", None)
            if parent != main_session_id:
                self._mark_rc_invalid(ctx, reason="main_generation_changed")
                self._best_effort_close_rc(device_id, ctx)

    def invalidate_rc_with_parent(self, device_id: str, parent_main_session_id: str) -> None:
        """主连接 current 注销（调用方已持中心锁）：失效绑定该 main 的 RC。"""
        bag = self._connections.get(device_id) or {}
        for _rc_key, ctx in list(bag.items()):
            if getattr(ctx, "parent_main_session_id", None) == parent_main_session_id:
                self._mark_rc_invalid(ctx, reason="main_session_closed")
                self._best_effort_close_rc(device_id, ctx)
                rc_key = self._connection_key(ctx)
                bag.pop(rc_key, None)
                if self._current_sessions.get(device_id) == rc_key:
                    self._current_sessions.pop(device_id, None)
        if not bag:
            self._connections.pop(device_id, None)

    def _register_connection_unlocked(self, device_id: str, ctx) -> bool:
        if not device_id or not str(device_id).strip():
            return False
        parent = self._resolve_parent_main_session_unlocked(device_id)
        if not parent:
            return False
        key = self._connection_key(ctx)
        bag = self._connections.setdefault(device_id, {})
        active = [
            h
            for k, h in bag.items()
            if h is not ctx and not getattr(h, "superseded", False)
        ]
        if len(active) >= self.max_per_device:
            return False
        superseded = [(k, h) for k, h in list(bag.items()) if k != key and h is not ctx]
        bag[key] = ctx
        self._current_sessions[device_id] = key
        ctx.parent_main_session_id = parent
        ctx.correlation_id = getattr(ctx, "correlation_id", None) or ctx.session_id
        ctx.superseded = False
        ctx._outbound_closed = False
        ctx.local_active_registry = self
        ctx.channel_kind = CHANNEL_KIND
        for _old_key, old_h in superseded:
            self._mark_rc_invalid(old_h, reason="superseded_by_new_rc_session")
            self._best_effort_close_rc(device_id, old_h)
        return True

    async def register_connection(self, device_id: str, ctx) -> bool:
        if not device_id:
            return False
        async with self._get_device_send_lock(device_id):
            return self._register_connection_unlocked(device_id, ctx)

    def register_reject_reason(self, device_id: str) -> str:
        """同步诊断：注册失败原因（测试/审计）。"""
        if not self._resolve_parent_main_session_unlocked(device_id):
            return "no_main_session"
        bag = self._connections.get(device_id) or {}
        active = [h for h in bag.values() if not getattr(h, "superseded", False)]
        if len(active) >= self.max_per_device:
            return "too_many_connections"
        return "unknown"

    def _unregister_connection_unlocked(self, device_id: str, ctx) -> None:
        if not device_id:
            return
        try:
            key = self._connection_key(ctx)
        except ValueError:
            return
        bag = self._connections.get(device_id)
        if not bag:
            return
        bag.pop(key, None)
        if not bag:
            self._connections.pop(device_id, None)
            self._current_sessions.pop(device_id, None)
        elif self._current_sessions.get(device_id) == key:
            self._current_sessions.pop(device_id, None)
        ctx._outbound_closed = True

    async def unregister_connection(self, device_id: str, ctx) -> None:
        if not device_id:
            return
        async with self._get_device_send_lock(device_id):
            self._unregister_connection_unlocked(device_id, ctx)

    async def try_register(self, device_id: str, conn_obj) -> bool:
        return await self.register_connection(device_id, conn_obj)

    async def unregister(self, device_id: str, conn_obj) -> None:
        await self.unregister_connection(device_id, conn_obj)

    async def send_to_current(
        self,
        device_id: str,
        data,
        *,
        handler=None,
        command: str = None,
        msg_type: str = None,
        task_id=None,
    ) -> bool:
        """持中心 per-device 锁：主代际 + RC current 双校验后 websocket.send。"""
        if not device_id or not str(device_id).strip():
            logger.bind(tag=TAG).warning(
                f"[reminder_control] skip command={command} reason=missing_device_id"
            )
            return False
        async with self._get_device_send_lock(device_id):
            target = handler
            rc_sid = getattr(target, "session_id", None)
            parent_sid = getattr(target, "parent_main_session_id", None)
            corr = getattr(target, "correlation_id", None) or rc_sid
            if target is None or not self.is_current_connection(device_id, target):
                logger.bind(tag=TAG).info(
                    f"[device_send] task_id={task_id} target_device_id={device_id} "
                    f"rc_session_id={rc_sid} parent_main_session_id={parent_sid} "
                    f"correlation_id={corr} command={command} type={msg_type} "
                    f"result=skip reason=stale_connection"
                )
                return False
            if getattr(target, "superseded", False) or getattr(
                target, "_outbound_closed", False
            ):
                logger.bind(tag=TAG).info(
                    f"[device_send] task_id={task_id} target_device_id={device_id} "
                    f"rc_session_id={rc_sid} parent_main_session_id={parent_sid} "
                    f"correlation_id={corr} command={command} type={msg_type} "
                    f"result=skip reason=superseded"
                )
                return False
            ws = getattr(target, "websocket", None)
            if ws is None:
                return False
            try:
                if isinstance(data, (bytes, bytearray, memoryview)):
                    payload_bytes = len(data)
                else:
                    payload_bytes = len(
                        str(data).encode("utf-8", errors="replace")
                    )
                await ws.send(data)
                log_send = (
                    logger.bind(tag=TAG).debug
                    if (
                        msg_type in ("binary", "pong", "ping")
                        or command in ("audio", "pong", "ping")
                    )
                    else logger.bind(tag=TAG).info
                )
                log_send(
                    f"[device_send] task_id={task_id} target_device_id={device_id} "
                    f"rc_session_id={rc_sid} parent_main_session_id={parent_sid} "
                    f"correlation_id={corr} command={command} type={msg_type} "
                    f"result=sent payload_bytes={payload_bytes}"
                )
                return True
            except Exception as exc:
                logger.bind(tag=TAG).error(
                    f"[device_send] task_id={task_id} target_device_id={device_id} "
                    f"rc_session_id={rc_sid} parent_main_session_id={parent_sid} "
                    f"correlation_id={corr} command={command} type={msg_type} "
                    f"result=failed err_type={type(exc).__name__}"
                )
                return False

    def invalidate_device(self, device_id: str) -> None:
        """兼容：主连接切代时失效 parent 与 current main 不一致的全部 RC。"""
        host = self._main_host
        main_sid = None
        if host is not None:
            getter = getattr(host, "get_current_main_session_id", None)
            if callable(getter):
                main_sid = getter(device_id)
        if main_sid:
            self.sync_rc_to_main_generation(device_id, main_sid)
        else:
            bag = self._connections.get(device_id) or {}
            for ctx in list(bag.values()):
                self._mark_rc_invalid(ctx, reason="main_unavailable")
            self._current_sessions.pop(device_id, None)


def is_reminder_control_path(path: str) -> bool:
    raw = (path or "").split("?", 1)[0].rstrip("/")
    return raw.endswith("/reminder-control") or raw == "/reminder-control"


async def authenticate_reminder_control(
    websocket, config: dict, auth_manager: AuthManager, *, auth_enable: bool, allowed_devices: set
) -> tuple:
    """返回 (device_id, client_id, account_id)；失败抛 AuthenticationError。"""
    from core.utils.account_identity import normalize_manager_user_id
    from core.utils.face_jwt import is_reserved_account_id

    headers = dict(websocket.request.headers)
    device_id = (headers.get("device-id") or "").strip()
    client_id = (headers.get("client-id") or "").strip()
    if not device_id or not client_id:
        raise AuthenticationError("missing_device_or_client_id")

    account_id = ""
    try:
        from config.manage_api_client import get_device_config

        info = await get_device_config(device_id)
        account_id = normalize_manager_user_id(
            (info or {}).get("userId") or (info or {}).get("user_id")
        ) or ""
    except Exception:
        account_id = ""
    if not account_id:
        face_cfg = ((config.get("server") or {}).get("face") or {})
        raw = (face_cfg.get("account_id") or "").strip()
        if not is_reserved_account_id(raw):
            account_id = normalize_manager_user_id(raw) or ""
    if not account_id:
        raise AuthenticationError("account_id_missing")

    # 白名单设备：与主连接一致，可不校验 token
    if allowed_devices and device_id in allowed_devices:
        return device_id, client_id, account_id

    token = (headers.get("authorization") or "").strip()
    if not token:
        # 控制连接强制要求 Authorization（配对凭证）
        raise AuthenticationError("missing_authorization")
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    if not token:
        raise AuthenticationError("missing_authorization")

    # 始终用 AuthManager +（v2）auth-state 校验配对凭证；不接受 face/vision JWT
    from core.handle.connection_auth import verify_device_ws_token

    try:
        await verify_device_ws_token(
            auth_manager,
            token=token,
            device_id=device_id,
            client_id=client_id,
        )
    except AuthenticationError:
        raise
    except Exception:
        raise AuthenticationError("invalid_token")

    # auth_enable=False 时仍要求有效配对 token（控制面更严格）
    _ = auth_enable
    return device_id, client_id, account_id


async def _send_json(ctx: ReminderControlContext, payload: dict) -> None:
    await ctx.send_current_guarded(
        json.dumps(payload, ensure_ascii=False),
        command=str(payload.get("type") or "reminder"),
        msg_type=str(payload.get("type") or "reminder"),
    )


async def _send_error(
    ctx: ReminderControlContext,
    *,
    code: str,
    instance_id: str = "",
    message: str = "request rejected",
) -> None:
    try:
        await _send_json(
            ctx,
            {
                "type": "reminder_voice_error",
                "code": code,
                "instance_id": instance_id or "",
                "message": message,
            },
        )
    except Exception:
        pass


async def handle_reminder_control_connection(
    websocket,
    *,
    config: dict,
    auth_manager: AuthManager,
    auth_enable: bool,
    allowed_devices: set,
    manager: ReminderControlManager,
    llm=None,
    idle_timeout_sec: float = DEFAULT_IDLE_TIMEOUT_SEC,
) -> None:
    """独立短时控制连接主循环。"""
    device_id = ""
    ctx = None
    try:
        device_id, client_id, account_id = await authenticate_reminder_control(
            websocket,
            config,
            auth_manager,
            auth_enable=auth_enable,
            allowed_devices=allowed_devices,
        )
        ctx = ReminderControlContext(
            websocket=websocket,
            config=config,
            device_id=device_id,
            client_id=client_id,
            account_id=account_id,
            llm=llm,
        )
        if not await manager.try_register(device_id, ctx):
            reject = manager.register_reject_reason(device_id)
            audit_event(
                "control_conn_rejected",
                device_id=device_id,
                account_id=account_id,
                result_code=reject,
                prefix="[reminder_control]",
            )
            close_reason = (
                "no main session"
                if reject == "no_main_session"
                else "too many control connections"
            )
            close_code = 1013 if reject != "no_main_session" else 1008
            await websocket.close(code=close_code, reason=close_reason)
            return

        audit_event(
            "control_conn_open",
            device_id=device_id,
            account_id=account_id,
            session_id=ctx.session_id,
            result_code="ok",
            prefix="[reminder_control]",
        )

        while True:
            try:
                message = await asyncio.wait_for(
                    websocket.recv(), timeout=float(idle_timeout_sec)
                )
            except asyncio.TimeoutError:
                audit_event(
                    "control_conn_idle_close",
                    device_id=device_id,
                    account_id=account_id,
                    session_id=ctx.session_id,
                    result_code="idle_timeout",
                    prefix="[reminder_control]",
                )
                await websocket.close(code=1000, reason="idle timeout")
                return

            ctx.last_activity = time.time()

            # 严禁音频上行
            if isinstance(message, (bytes, bytearray)):
                await _send_error(ctx, code="binary_forbidden", message="audio not allowed")
                await websocket.close(code=1003, reason="binary not allowed")
                return

            if not isinstance(message, str):
                await websocket.close(code=1003, reason="invalid message")
                return
            if len(message.encode("utf-8", errors="ignore")) > MAX_TEXT_BYTES:
                await _send_error(ctx, code="payload_too_large")
                await websocket.close(code=1009, reason="payload too large")
                return

            try:
                msg = json.loads(message)
            except json.JSONDecodeError:
                await _send_error(ctx, code="invalid_json")
                await websocket.close(code=1003, reason="invalid json")
                return

            if not isinstance(msg, dict):
                await _send_error(ctx, code="invalid_payload")
                await websocket.close(code=1003, reason="invalid payload")
                return

            msg_type = str(msg.get("type") or "").strip()
            if msg_type not in ALLOWED_INBOUND:
                await _send_error(ctx, code="message_type_forbidden", message="not allowed")
                await websocket.close(code=1008, reason="message type forbidden")
                return

            if msg_type == "ping":
                await _send_json(ctx, {"type": "pong"})
                continue

            if msg_type == "reminder_event":
                # 预留：仅审计，不驱动业务
                from core.handle.textHandler.reminderEventMessageHandler import (
                    ReminderEventMessageHandler,
                )

                await ReminderEventMessageHandler().handle(ctx, msg)
                continue

            if msg_type == "reminder_voice_request":
                # 确保 TTS 可用
                ctx.ensure_tts()
                await process_reminder_voice_request(
                    ctx, msg, send_error_on_failure=True
                )
                continue

    except AuthenticationError as exc:
        audit_event(
            "control_auth_failed",
            device_id=device_id or "",
            result_code=str(getattr(exc, "code", exc))[:64],
            prefix="[reminder_control]",
        )
        try:
            from core.handle.connection_auth import send_auth_error_and_close

            await send_auth_error_and_close(
                websocket, getattr(exc, "code", "invalid_token")
            )
        except Exception:
            try:
                await websocket.close(code=1008, reason="invalid_token")
            except Exception:
                pass
    except Exception as exc:
        logger.bind(tag=TAG).warning(
            f"[reminder_control] conn_error err_type={type(exc).__name__}"
        )
        try:
            await websocket.close()
        except Exception:
            pass
    finally:
        if ctx is not None and device_id:
            await manager.unregister(device_id, ctx)
            audit_event(
                "control_conn_close",
                device_id=device_id,
                account_id=getattr(ctx, "account_id", ""),
                session_id=getattr(ctx, "session_id", ""),
                result_code="closed",
                prefix="[reminder_control]",
            )
