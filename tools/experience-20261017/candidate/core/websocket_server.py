import asyncio
import json
import time
from typing import Optional

import websockets
from config.logger import setup_logging
from core.connection import ConnectionHandler
from config.config_loader import get_config_from_api
from core.auth import AuthManager, AuthenticationError, AUTH_ERROR_CODES
from core.handle.connection_auth import (
    send_auth_error_and_close,
    verify_device_ws_token,
)
from core.utils.modules_initialize import initialize_modules
from core.utils.util import check_vad_update, check_asr_update
from core.reminder_control import (
    ReminderControlManager,
    handle_reminder_control_connection,
    is_reminder_control_path,
)

TAG = __name__


class WebSocketServer:
    def __init__(self, config: dict):
        self.config = config
        self.logger = setup_logging()
        self.config_lock = asyncio.Lock()
        modules = initialize_modules(
            self.logger,
            self.config,
            "VAD" in self.config["selected_module"],
            "ASR" in self.config["selected_module"],
            "LLM" in self.config["selected_module"],
            False,
            "Memory" in self.config["selected_module"],
            "Intent" in self.config["selected_module"],
        )
        self._vad = modules["vad"] if "vad" in modules else None
        self._asr = modules["asr"] if "asr" in modules else None
        self._llm = modules["llm"] if "llm" in modules else None
        self._intent = modules["intent"] if "intent" in modules else None
        self._memory = modules["memory"] if "memory" in modules else None

        auth_config = self.config["server"].get("auth", {})
        self.auth_enable = auth_config.get("enabled", False)
        # 设备白名单
        self.allowed_devices = set(auth_config.get("allowed_devices", []))
        secret_key = self.config["server"]["auth_key"]
        expire_seconds = auth_config.get("expire_seconds", None)
        self.auth = AuthManager(secret_key=secret_key, expire_seconds=expire_seconds)
        # 活跃连接：device_id -> {session_id(connection generation) -> ConnectionHandler}
        # 每个连接按 session_id 独立登记，注销时按身份精确移除，
        # 避免「旧连接清理误删同一 device_id 的新连接」造成串指令/丢失路由。
        self._connections = {}
        # 每个 device_id 的当前有效连接代际（session_id）。普通设备消息只投递给该代际。
        self._current_sessions = {}
        # 每设备串行锁：current 切换与「确认 current + 提交 websocket send」互斥，消除 TOCTTOU。
        self._device_send_locks = {}
        # Reminder Control 并发限制
        max_rc = int(
            (self.config.get("server") or {}).get(
                "reminder_control_max_conns_per_device", 2
            )
        )
        self._reminder_control_manager = ReminderControlManager(
            max_per_device=max_rc,
            device_locks=self._device_send_locks,
            main_host=self,
        )

    def get_current_main_session_id(self, device_id: str) -> Optional[str]:
        """当前主连接代际 session_id（服务端生成）。"""
        if not device_id:
            return None
        return self._current_sessions.get(device_id)

    def is_main_session_current(self, device_id: str, main_session_id: str) -> bool:
        """指定主连接 session 是否仍为 device 的 current 且未 superseded。"""
        if not device_id or not main_session_id:
            return False
        if self._current_sessions.get(device_id) != main_session_id:
            return False
        conns = self._connections.get(device_id) or {}
        handler = conns.get(main_session_id)
        if handler is None:
            return False
        return not getattr(handler, "superseded", False)

    def _get_device_send_lock(self, device_id: str) -> asyncio.Lock:
        """返回（并懒创建）指定 device_id 的发送/代际切换锁。"""
        lock = self._device_send_locks.get(device_id)
        if lock is None:
            lock = asyncio.Lock()
            self._device_send_locks[device_id] = lock
        return lock

    def _connection_key(self, device_id: str, handler) -> str:
        """连接代际键：服务端生成的 session_id（每次连接唯一）。

        绝不使用 id(handler) 作为回退值——它不具备跨进程/跨生命周期语义，
        且可能在对象复用或回收时碰撞，破坏精确路由与注销。
        """
        sid = getattr(handler, "session_id", None)
        if not sid:
            raise ValueError("ConnectionHandler 缺少 session_id，无法作为连接代际键")
        return sid

    def _register_connection(self, device_id: str, handler) -> None:
        """同步登记（测试/无事件环场景）。生产路径应使用 register_connection() 持锁切换。"""
        self._register_connection_unlocked(device_id, handler)

    async def register_connection(self, device_id: str, handler) -> None:
        """持设备锁登记：与最终 send 串行，保证新旧代际切换与出站互斥。"""
        if not device_id:
            self._register_connection_unlocked(device_id, handler)
            return
        async with self._get_device_send_lock(device_id):
            self._register_connection_unlocked(device_id, handler)

    def _register_connection_unlocked(self, device_id: str, handler) -> None:
        """按 device_id + session_id 登记；新连接成为该 device_id 的唯一当前有效代际。

        调用方若在异步路径，必须已持有该 device 的 send lock。
        已有旧连接会被标记 superseded，并异步、最佳努力关闭；关闭失败不影响新连接。
        旧连接永远不得再次成为 current。
        """
        key = self._connection_key(device_id, handler)
        conns = self._connections.setdefault(device_id, {})
        superseded = [
            (old_key, old_h)
            for old_key, old_h in list(conns.items())
            if old_key != key and old_h is not handler
        ]
        conns[key] = handler
        self._current_sessions[device_id] = key
        setattr(handler, "superseded", False)
        for old_key, old_h in superseded:
            setattr(old_h, "superseded", True)
            self.logger.bind(tag=TAG).info(
                f"[conn] superseded device_id={device_id} old_session_id={old_key} "
                f"new_session_id={key}"
            )
            try:
                from core.utils.device_outbound import invalidate_connection

                invalidate_connection(old_h, reason="superseded_by_new_session")
            except Exception as e:
                self.logger.bind(tag=TAG).debug(
                    f"[conn] invalidate_failed device_id={device_id} "
                    f"session_id={old_key} reason={e}"
                )
            self._best_effort_close_superseded(device_id, old_h)
        mgr = getattr(self, "_reminder_control_manager", None)
        if mgr is not None and hasattr(mgr, "sync_rc_to_main_generation"):
            mgr.sync_rc_to_main_generation(device_id, key)

    def _best_effort_close_superseded(self, device_id: str, handler) -> None:
        """异步关闭已被取代的旧连接；任何失败都不得影响当前有效连接。"""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        async def _close():
            ws = getattr(handler, "websocket", None)
            if ws is None:
                return
            try:
                await ws.close()
            except Exception as e:
                self.logger.bind(tag=TAG).debug(
                    f"[conn] close_superseded_failed device_id={device_id} "
                    f"session_id={getattr(handler, 'session_id', None)} reason={e}"
                )

        try:
            loop.create_task(_close())
        except Exception:
            pass

    def _unregister_connection_unlocked(self, device_id: str, handler) -> None:
        """按身份精确注销（调用方须已持有该 device 的 send lock，或处于测试同步路径）。

        若注销的是当前有效代际，才清除 current 标记；
        绝不误删同 device_id 的其他代际，也绝不把旧连接回升为 current。
        """
        key = self._connection_key(device_id, handler)
        conns = self._connections.get(device_id)
        if not conns:
            return
        was_current = self._current_sessions.get(device_id) == key
        conns.pop(key, None)
        if not conns:
            self._connections.pop(device_id, None)
            self._current_sessions.pop(device_id, None)
        elif was_current:
            self._current_sessions.pop(device_id, None)
        if was_current:
            mgr = getattr(self, "_reminder_control_manager", None)
            if mgr is not None and hasattr(mgr, "invalidate_rc_with_parent"):
                mgr.invalidate_rc_with_parent(device_id, key)

    def _unregister_connection(self, device_id: str, handler) -> None:
        """同步注销（测试/无事件环）。生产 finally 应使用 unregister_connection() 持锁。"""
        self._unregister_connection_unlocked(device_id, handler)

    async def unregister_connection(self, device_id: str, handler) -> None:
        """持设备锁注销：与 register / send_to_current 串行，避免注销与 send 竞态。"""
        if not device_id:
            self._unregister_connection_unlocked(device_id, handler)
            return
        async with self._get_device_send_lock(device_id):
            self._unregister_connection_unlocked(device_id, handler)

    def _current_connection(self, device_id: str):
        """返回 device_id 当前有效连接；不存在则返回 None。"""
        key = self._current_sessions.get(device_id)
        if not key:
            return None
        conns = self._connections.get(device_id)
        if not conns:
            return None
        return conns.get(key)

    def is_current_connection(self, device_id: str, handler) -> bool:
        """该连接是否为 device_id 的当前有效代际（供异步回调/定时器在 send 前校验）。"""
        try:
            key = self._connection_key(device_id, handler)
        except ValueError:
            return False
        if self._current_sessions.get(device_id) != key:
            return False
        conns = self._connections.get(device_id)
        return bool(conns) and conns.get(key) is handler

    def _resolve_target(self, device_id: str, session_id: str = None):
        """解析投递目标。

        - session_id 为空：返回当前有效连接；
        - session_id 指定：精确路由到该代际；未命中或已非当前代际时返回 None
          （绝不退化为向所有连接发送）。
        """
        if not device_id:
            return None
        if session_id is not None:
            conns = self._connections.get(device_id)
            handler = conns.get(session_id) if conns else None
            if handler is None:
                return None
            if self._current_sessions.get(device_id) != session_id:
                return None
            return handler
        return self._current_connection(device_id)

    @staticmethod
    def _outbound_meta(payload: dict):
        """出站消息元数据（仅非敏感字段，绝不包含 payload 全文/token）。"""
        if isinstance(payload, dict):
            return {
                "task_id": payload.get("task_id") or payload.get("taskId"),
                "command": payload.get("command"),
                "msg_type": payload.get("type"),
            }
        return {"task_id": None, "command": None, "msg_type": None}

    async def send_to_current(
        self,
        device_id: str,
        data,
        *,
        handler=None,
        session_id: str = None,
        command: str = None,
        msg_type: str = None,
        task_id=None,
        _pre_send=None,
    ) -> bool:
        """统一 current-guarded 出站：持设备锁，确认仍是 current 后再 websocket.send。

        与 register_connection 共用同一把锁，消除「检查 current 与实际 send」之间的 TOCTTOU：
        要么本消息在 A2 成为 current 前完成提交，要么 A2 已成为 current 后本连接不允许 send。
        """
        if not device_id or not str(device_id).strip():
            self.logger.bind(tag=TAG).warning(
                f"[device_send] skip command={command} reason=missing_device_id"
            )
            return False
        async with self._get_device_send_lock(device_id):
            target = handler
            if target is None:
                target = self._resolve_target(device_id, session_id)
            if target is None or not self.is_current_connection(device_id, target):
                self.logger.bind(tag=TAG).warning(
                    f"[device_send] skip task_id={task_id} target_device_id={device_id} "
                    f"session_id={session_id or getattr(handler, 'session_id', None)} "
                    f"command={command} type={msg_type} reason=stale_connection"
                )
                return False
            ws = getattr(target, "websocket", None)
            if ws is None:
                return False
            if _pre_send is not None:
                await _pre_send()
            try:
                # payload_bytes 仅计长度，绝不记录正文/预览
                if isinstance(data, (bytes, bytearray, memoryview)):
                    payload_bytes = len(data)
                else:
                    payload_bytes = len(str(data).encode("utf-8", errors="replace"))
                t0 = time.perf_counter()
                configured=(getattr(self,'config',{}) or {}).get('server',{}).get('ws_send_timeout_seconds',5)
                timeout=max(.05,min(10,float(configured)))
                await asyncio.wait_for(ws.send(data),timeout=timeout)
                send_ms = (time.perf_counter() - t0) * 1000.0
                try:
                    target.last_outbound_monotonic_ms = int(time.monotonic() * 1000)
                    target.last_ws_send_block_ms = send_ms
                except Exception:
                    pass
                # binary audio / ping-pong 保活极密，INFO 会刷屏；仅 debug 保留
                log_send = (
                    self.logger.bind(tag=TAG).debug
                    if (
                        msg_type in ("binary", "pong", "ping")
                        or command in ("audio", "pong", "ping")
                    )
                    else self.logger.bind(tag=TAG).info
                )
                log_send(
                    f"[device_send] task_id={task_id} target_device_id={device_id} "
                    f"session_id={getattr(target, 'session_id', None)} "
                    f"correlation_id={getattr(target, 'correlation_id', None)} "
                    f"command={command} type={msg_type} result=sent "
                    f"payload_bytes={payload_bytes}"
                )
                return True
            except Exception as e:
                self.logger.bind(tag=TAG).error(
                    f"[device_send] task_id={task_id} target_device_id={device_id} "
                    f"session_id={getattr(target, 'session_id', None)} "
                    f"correlation_id={getattr(target, 'correlation_id', None)} "
                    f"command={command} type={msg_type} result=failed "
                    f"err_type={type(e).__name__} errno={getattr(e,'errno',None)} "
                    f"close_code={getattr(ws,'close_code',None)} elapsed_ms={round((time.perf_counter()-t0)*1000,1)}"
                )
                return False

    async def send_tts_to_device(self, text: str, device_id: str, session_id: str = None) -> bool:
        """
        将 TTS 文本推送到指定设备的当前有效连接（无全局广播语义）。

        规则：
        - device_id 必填且非空；缺失/空时 fail closed（抛 ValueError），绝不遍历全部连接。
        - 仅投递到该 device_id 的当前有效 session（持设备锁，与代际切换串行）。
        - 返回是否成功投递到 TTS 队列。
        """
        if not device_id or not str(device_id).strip():
            raise ValueError("send_tts_to_device 必须传入非空 device_id")
        from core.providers.tts.dto.dto import TTSMessageDTO, SentenceType, ContentType
        import uuid

        async with self._get_device_send_lock(device_id):
            handler = self._resolve_target(device_id, session_id)
            if handler is None or not self.is_current_connection(device_id, handler):
                self.logger.bind(tag=TAG).warning(
                    f"[device_send] skip target_device_id={device_id} session_id={session_id} "
                    f"reason=no_current_connection"
                )
                return False
            if handler.tts is None:
                self.logger.bind(tag=TAG).warning(
                    f"[device_send] skip target_device_id={device_id} "
                    f"connection_id={getattr(handler, 'session_id', None)} reason=no_tts"
                )
                return False
            try:
                from core.utils.device_outbound import enqueue_tts, begin_tts_turn

                sid = str(uuid.uuid4())
                handler.sentence_id = sid
                sid, epoch = begin_tts_turn(handler, sid)
                conn_sid = getattr(handler, "session_id", None)
                queued = True
                for dto in (
                    TTSMessageDTO(
                        sentence_id=sid,
                        sentence_type=SentenceType.FIRST,
                        content_type=ContentType.ACTION,
                        session_id=conn_sid,
                        abort_epoch=epoch,
                    ),
                    TTSMessageDTO(
                        sentence_id=sid,
                        sentence_type=SentenceType.MIDDLE,
                        content_type=ContentType.TEXT,
                        content_detail=text,
                        session_id=conn_sid,
                        abort_epoch=epoch,
                    ),
                    TTSMessageDTO(
                        sentence_id=sid,
                        sentence_type=SentenceType.LAST,
                        content_type=ContentType.ACTION,
                        session_id=conn_sid,
                        abort_epoch=epoch,
                    ),
                ):
                    queued = enqueue_tts(handler, dto) and queued
                if not queued:
                    self.logger.bind(tag=TAG).info(
                        f"[device_send] skip target_device_id={device_id} "
                        f"connection_id={conn_sid} command=tts reason=tts_enqueue_rejected"
                    )
                    return False
                self.logger.bind(tag=TAG).info(
                    f"[device_send] task_id=None target_device_id={device_id} "
                    f"connection_id={getattr(handler, 'session_id', None)} "
                    f"correlation_id={getattr(handler, 'correlation_id', None)} "
                    f"command=tts result=sent"
                )
                return True
            except Exception as e:
                self.logger.bind(tag=TAG).error(
                    f"[device_send] task_id=None target_device_id={device_id} "
                    f"connection_id={getattr(handler, 'session_id', None)} "
                    f"correlation_id={getattr(handler, 'correlation_id', None)} "
                    f"command=tts result=failed err={e}"
                )
                return False

    async def send_json_to_device(self, device_id: str, payload: dict, session_id: str = None) -> bool:
        """
        向指定设备 WebSocket 连接发送 JSON 消息（如 update_assets / update_spine）。
        严格按 device_id 路由到当前有效连接；持设备锁消除 TOCTTOU。
        """
        if not device_id:
            self.logger.bind(tag=TAG).warning("设备不在线或 device_id 为空")
            return False
        meta = self._outbound_meta(payload if isinstance(payload, dict) else {})
        return await self.send_to_current(
            device_id,
            json.dumps(payload, ensure_ascii=False),
            session_id=session_id,
            command=meta["command"],
            msg_type=meta["msg_type"],
            task_id=meta["task_id"],
        )

    async def start(self):
        server_config = self.config["server"]
        host = server_config.get("ip", "0.0.0.0")
        port = int(server_config.get("port", 8000))
        # 显式配置协议层 Ping/Pong，避免依赖库隐式默认值
        ping_interval = float(server_config.get("websocket_ping_interval", 20))
        ping_timeout = float(server_config.get("websocket_ping_timeout", 20))
        close_timeout = float(server_config.get("websocket_close_timeout", 10))
        self.logger.bind(tag=TAG).info(
            f"[ws_server] listen={host}:{port} "
            f"ping_interval={ping_interval} ping_timeout={ping_timeout} "
            f"close_timeout={close_timeout}"
        )

        async with websockets.serve(
            self._handle_connection,
            host,
            port,
            process_request=self._http_response,
            ping_interval=ping_interval,
            ping_timeout=ping_timeout,
            close_timeout=close_timeout,
        ):
            await asyncio.Future()

    async def _handle_connection(self, websocket):
        headers = dict(websocket.request.headers)
        request_path = getattr(getattr(websocket, "request", None), "path", "") or ""

        # 独立 Reminder Control 通道：不进入主对话 ConnectionHandler
        if is_reminder_control_path(request_path):
            idle_sec = float(
                (self.config.get("server") or {}).get(
                    "reminder_control_idle_timeout_sec", 20
                )
            )
            await handle_reminder_control_connection(
                websocket,
                config=self.config,
                auth_manager=self.auth,
                auth_enable=self.auth_enable,
                allowed_devices=self.allowed_devices,
                manager=self._reminder_control_manager,
                llm=self._llm,
                idle_timeout_sec=idle_sec,
            )
            return

        if headers.get("device-id", None) is None:
            # 尝试从 URL 的查询参数中获取 device-id
            from urllib.parse import parse_qs, urlparse

            # 从 WebSocket 请求中获取路径
            if not request_path:
                self.logger.bind(tag=TAG).error("无法获取请求路径")
                await websocket.close()
                return
            parsed_url = urlparse(request_path)
            query_params = parse_qs(parsed_url.query)
            if "device-id" not in query_params:
                await websocket.send("端口正常，如需测试连接，请使用test_page.html")
                await websocket.close()
                return
            else:
                websocket.request.headers["device-id"] = query_params["device-id"][0]
            if "client-id" in query_params:
                websocket.request.headers["client-id"] = query_params["client-id"][0]
            if "authorization" in query_params:
                websocket.request.headers["authorization"] = query_params[
                    "authorization"
                ][0]

        """处理新连接，每次创建独立的ConnectionHandler"""
        # 先认证，后建立连接
        try:
            await self._handle_auth(websocket)
        except AuthenticationError as auth_err:
            await send_auth_error_and_close(websocket, getattr(auth_err, "code", "invalid_token"))
            return
        # 创建ConnectionHandler时传入当前server实例
        device_id = (websocket.request.headers.get("device-id") or str(id(websocket)))
        handler = ConnectionHandler(
            self.config,
            self._vad,
            self._asr,
            self._llm,
            self._memory,
            self._intent,
            self,  # 传入server实例
        )
        srv = self.config.get("server") or {}
        handler.ws_ping_interval = float(srv.get("websocket_ping_interval", 20))
        handler.ws_ping_timeout = float(srv.get("websocket_ping_timeout", 20))
        try:
            await handler.handle_connection(websocket)
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"处理连接时出错: {e}")
        finally:
            await self.unregister_connection(device_id, handler)
            # 强制关闭连接（如果还没有关闭的话）
            try:
                # 安全地检查WebSocket状态并关闭
                if hasattr(websocket, "closed") and not websocket.closed:
                    await websocket.close()
                elif hasattr(websocket, "state") and websocket.state.name != "CLOSED":
                    await websocket.close()
                else:
                    # 如果没有closed属性，直接尝试关闭
                    await websocket.close()
            except Exception as close_error:
                self.logger.bind(tag=TAG).error(
                    f"服务器端强制关闭连接时出错: {close_error}"
                )

    async def _http_response(self, websocket, request_headers):
        # 检查是否为 WebSocket 升级请求
        if request_headers.headers.get("connection", "").lower() == "upgrade":
            # 如果是 WebSocket 请求，返回 None 允许握手继续
            return None
        else:
            # 如果是普通 HTTP 请求，返回 "server is running"
            return websocket.respond(200, "Server is running\n")

    async def update_config(self) -> bool:
        """更新服务器配置并重新初始化组件

        Returns:
            bool: 更新是否成功
        """
        try:
            async with self.config_lock:
                # 重新获取配置
                new_config = get_config_from_api(self.config)
                if new_config is None:
                    self.logger.bind(tag=TAG).error("获取新配置失败")
                    return False
                self.logger.bind(tag=TAG).info(f"获取新配置成功")
                # 检查 VAD 和 ASR 类型是否需要更新
                update_vad = check_vad_update(self.config, new_config)
                update_asr = check_asr_update(self.config, new_config)
                self.logger.bind(tag=TAG).info(
                    f"检查VAD和ASR类型是否需要更新: {update_vad} {update_asr}"
                )
                # 更新配置
                self.config = new_config
                # 重新初始化组件
                modules = initialize_modules(
                    self.logger,
                    new_config,
                    update_vad,
                    update_asr,
                    "LLM" in new_config["selected_module"],
                    False,
                    "Memory" in new_config["selected_module"],
                    "Intent" in new_config["selected_module"],
                )

                # 更新组件实例
                if "vad" in modules:
                    self._vad = modules["vad"]
                if "asr" in modules:
                    self._asr = modules["asr"]
                if "llm" in modules:
                    self._llm = modules["llm"]
                if "intent" in modules:
                    self._intent = modules["intent"]
                if "memory" in modules:
                    self._memory = modules["memory"]
                self.logger.bind(tag=TAG).info(f"更新配置任务执行完毕")
                return True
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"更新服务器配置失败: {str(e)}")
            return False

    async def revoke_device_connections(
        self, device_id: str, *, credential_version=None, status: str = None
    ) -> dict:
        """按单个 device_id 关闭主 WS + 该设备 RC；清除 auth-state 短缓存。

        绝不遍历或影响其他 device_id。返回关闭计数（不含 token/密钥）。
        """
        from core.utils.device_ws_auth_state import invalidate_auth_state_cache

        if not device_id or not str(device_id).strip():
            return {"ok": False, "reason": "missing_device_id", "closed_main": 0, "closed_rc": 0}

        did = str(device_id).strip()
        invalidate_auth_state_cache(did)
        closed_main = 0
        closed_rc = 0

        async with self._get_device_send_lock(did):
            conns = dict(self._connections.get(did) or {})
            for _sid, handler in list(conns.items()):
                try:
                    from core.utils.device_outbound import invalidate_connection

                    invalidate_connection(handler, reason="device_revoked")
                except Exception:
                    pass
                setattr(handler, "superseded", True)
                ws = getattr(handler, "websocket", None)
                if ws is not None:
                    try:
                        await ws.close(code=1008, reason="credential_revoked")
                        closed_main += 1
                    except Exception:
                        try:
                            await ws.close()
                            closed_main += 1
                        except Exception:
                            pass
            self._connections.pop(did, None)
            self._current_sessions.pop(did, None)

            mgr = getattr(self, "_reminder_control_manager", None)
            if mgr is not None:
                bag = dict(getattr(mgr, "_connections", {}).get(did) or {})
                for _rk, ctx in list(bag.items()):
                    try:
                        mgr._mark_rc_invalid(ctx, reason="device_revoked")
                    except Exception:
                        pass
                    ws = getattr(ctx, "websocket", None)
                    if ws is not None:
                        try:
                            await ws.close(code=1008, reason="credential_revoked")
                            closed_rc += 1
                        except Exception:
                            try:
                                await ws.close()
                                closed_rc += 1
                            except Exception:
                                pass
                getattr(mgr, "_connections", {}).pop(did, None)
                getattr(mgr, "_current_sessions", {}).pop(did, None)

        self.logger.bind(tag=TAG).info(
            f"[ws_revoke] device_id_set=true credential_version={credential_version} "
            f"status={status} closed_main={closed_main} closed_rc={closed_rc}"
        )
        return {
            "ok": True,
            "closed_main": closed_main,
            "closed_rc": closed_rc,
        }

    async def _handle_auth(self, websocket):
        # 先认证，后建立连接
        if not self.auth_enable:
            return
        headers = dict(websocket.request.headers)
        device_id = headers.get("device-id", None)
        client_id = headers.get("client-id", None)
        if self.allowed_devices and device_id in self.allowed_devices:
            # 如果属于白名单内的设备，不校验token，直接放行
            return
        # 否则校验 token：缺失 / 篡改 / 过期 / Device-Id 不匹配 / 吊销均拒绝
        token = (headers.get("authorization") or "").strip()
        if token.lower().startswith("bearer "):
            token = token[7:].strip()
        if not token:
            self.logger.bind(tag=TAG).error(
                "WSS 认证失败 reason=missing token_present=False "
                f"device_id_set={bool(device_id)} client_id_set={bool(client_id)}"
            )
            raise AuthenticationError("missing")
        try:
            await verify_device_ws_token(
                self.auth,
                token=token,
                device_id=device_id or "",
                client_id=client_id,
            )
        except AuthenticationError as e:
            self.logger.bind(tag=TAG).error(
                f"WSS 认证失败 reason={e.code} "
                f"token_present={bool(token)} token_len={len(token) if token else 0} "
                f"device_id_set={bool(device_id)} client_id_set={bool(client_id)}"
            )
            raise

