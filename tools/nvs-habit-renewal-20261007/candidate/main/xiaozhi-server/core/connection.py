from core.utils.audio_ingress import (
    queue_audio,
    log_audio_stats,
    mark_valid_uplink_timestamp,
    note_short_payload_gap,
)
import os
import sys
import copy
import json
import uuid
import time
import queue
import struct
import asyncio
import threading
import traceback
import subprocess
import websockets

from core.utils.util import (
    extract_json_from_string,
    check_vad_update,
    check_asr_update,
    filter_sensitive_info,
)
from typing import Dict, Any
from collections import deque, OrderedDict
from core.utils.modules_initialize import (
    initialize_modules,
    initialize_tts,
    initialize_asr,
)
from core.handle.reportHandle import report
from core.providers.tts.default import DefaultTTS
from concurrent.futures import ThreadPoolExecutor
from core.utils.dialogue import Message, Dialogue
from core.providers.asr.dto.dto import InterfaceType
from core.handle.textHandle import handleTextMessage
from core.providers.tools.unified_tool_handler import UnifiedToolHandler
from plugins_func.loadplugins import auto_import_modules
from plugins_func.register import Action
from core.auth import AuthenticationError
from config.config_loader import get_private_config_from_api
from core.providers.tts.dto.dto import ContentType, TTSMessageDTO, SentenceType
from config.logger import setup_logging, build_module_string, create_connection_logger
from config.manage_api_client import DeviceNotFoundException, DeviceBindException
from core.utils.prompt_manager import PromptManager
from core.utils.voiceprint_provider import VoiceprintProvider
from core.utils.tts_sentence_telemetry import TTSSentenceTelemetry
from core.utils import trace_log as trace

TAG = __name__

auto_import_modules("plugins_func.functions")


class TTSException(RuntimeError):
    pass


class ConnectionHandler:
    def __init__(
        self,
        config: Dict[str, Any],
        _vad,
        _asr,
        _llm,
        _memory,
        _intent,
        server=None,
    ):
        self.common_config = config
        self.config = copy.deepcopy(config)
        self.session_id = str(uuid.uuid4())
        self.correlation_id = str(uuid.uuid4().hex)  # 每次连接唯一，用于可追溯诊断
        self.logger = setup_logging()
        self.server = server  # 保存server实例的引用

        self.need_bind = False  # 是否需要绑定设备
        self.bind_code = None  # 绑定设备的验证码
        self.last_bind_prompt_time = 0  # 上次播放绑定提示的时间戳(秒)
        self.bind_prompt_interval = 30  # 绑定提示播放间隔(秒)

        self.read_config_from_api = self.config.get("read_config_from_api", False)

        self.websocket = None
        self.headers = None
        self.device_id = None
        self.device_user_id = None
        self.agent_id = None
        self.trace_turn_id = None
        self.trace_id_missing_reasons = {
            "agent_id": "not_bound_yet",
            "turn_id": "listen_not_started",
        }
        self._trace_uplink_seq = 0
        self.client_ip = None
        self.prompt = None
        self.welcome_msg = None
        self.max_output_size = 0
        self.chat_history_conf = 0
        self.audio_format = "opus"
        # 1=裸 OPUS, 2=BinaryProtocol2(16字节头), 3=BinaryProtocol3(4字节头)
        # 协议版本必须由本连接的 hello 确定，未确定前为 None，禁止默认降级 v1
        self.protocol_version = None
        self.audio_protocol_version = 0
        # 会话状态机：未完成 hello 前拒绝处理 listen/音频帧
        self.hello_received = False
        # 本连接是否已下发 update_spine（异常断开时上报，避免无限重投）
        self.spine_update_sent_task_id = None
        self.spine_update_sent_at_ms = None
        self.wallpaper_update_sent_task_id = None
        self.wallpaper_update_sent_at_ms = None

        self.device_custom_name = "小智"  # 默认名字
        self.user_nickname = "主人"     # 默认称呼
        # 智控台用户 → face account_id（禁止 default / device_id / usr_* 伪装）
        self.face_account_id = None
        self.account_id = None
        self.connection_started_monotonic_ms = int(time.monotonic() * 1000)
        self.last_outbound_monotonic_ms = None
        self.last_ws_ping_sent_ms = None
        self.last_ws_pong_recv_ms = None
        self.ws_ping_interval = None
        self.ws_ping_timeout = None

        # 客户端状态相关
        self.client_abort = False
        self.client_is_speaking = False
        self.client_listen_mode = "auto"

        # 线程任务相关
        self.loop = asyncio.get_event_loop()
        self.stop_event = threading.Event()
        self.executor = ThreadPoolExecutor(max_workers=5)

        # 添加上报线程池
        self.report_queue = queue.Queue()
        self.report_thread = None
        # 未来可以通过修改此处，调节asr的上报和tts的上报，目前默认都开启
        self.report_asr_enable = self.read_config_from_api
        self.report_tts_enable = self.read_config_from_api

        # 依赖的组件
        self.vad = None
        self.asr = None
        self.tts = None
        self._asr = _asr
        self._vad = _vad
        self.llm = _llm
        # 记忆实例必须在每个连接内独立创建，绝不复用服务级共享单例，
        # 否则不同设备会互相覆盖 role_id / short_memory 导致串记忆。
        self.memory = None
        self.intent = _intent

        # 为每个连接单独管理声纹识别
        self.voiceprint_provider = None
        # 在场用户（人脸）与当前说话用户（声纹）必须独立，均只存本连接短期上下文。
        self.current_present_user = None
        self.current_present_user_seen_at = 0.0
        self.current_speaker_user = None
        self.current_speaker = None

        # vad相关变量
        self.client_audio_buffer = bytearray()
        self.client_have_voice = False
        self.client_voice_window = deque(maxlen=5)
        self.first_activity_time = 0.0  # 记录首次活动的时间（毫秒）
        self.last_activity_time = 0.0  # 统一的活动时间戳（毫秒）
        self.client_voice_stop = False
        self.last_is_voice = False
        # Device listen vs per-utterance speech. listen_epoch is the listen
        # generation; utterance_id is one sentence inside that listen.
        self.device_listening = False
        self.utterance_id = 0
        self.vad_speech_confirmed = False
        self.utterance_stop_id = 0
        self.utterance_stop_reason = None
        self.vad_audio_ms = 0.0
        self.vad_last_speech_audio_ms = 0.0
        self._vad_decoder = None

        # asr相关变量
        # 因为实际部署时可能会用到公共的本地ASR，不能把变量暴露给公共ASR
        # 所以涉及到ASR的变量，需要在这里定义，属于connection的私有变量
        self.asr_audio = []
        self.asr_audio_queue = queue.Queue()

        # llm相关变量
        self.llm_finish_task = True
        self.dialogue = Dialogue()
        # 接通 context_compress 配置（原为死配置：config.yaml 写了但从未读取）
        self.dialogue.configure_compact(self.config)

        # tts相关变量
        self.sentence_id = None
        self.tts_abort_epoch = 0
        self.tts_sentence_epochs = OrderedDict()
        # 处理TTS响应没有文本返回
        self.tts_MessageText = ""
        # 下行 TTS 句级发送可观测性（仅计数与时戳，不保存文本/音频）
        self.tts_sentence_telemetry = TTSSentenceTelemetry(clock=self._monotonic_ms)
        # 上行 VAD/ASR 未就绪丢弃的音频帧计数（限频告警，close 汇总输出）
        self.preinit_audio_dropped = 0
        self.preinit_audio_last_warn_ms = 0

        # iot相关变量
        self.iot_descriptors = {}
        self.func_handler = None

        self.cmd_exit = self.config["exit_commands"]

        # 是否在聊天结束后关闭连接
        self.close_after_chat = False
        self.load_function_plugin = False
        self.intent_type = "nointent"

        self.timeout_seconds = (
            int(self.config.get("close_connection_no_voice_time", 120)) + 60
        )  # 在原来第一道关闭的基础上加60秒，进行二道关闭
        self.timeout_task = None

        # {"mcp":true} 表示启用MCP功能
        self.features = None

        # 标记连接是否来自MQTT
        self.conn_from_mqtt_gateway = False

        # ── WebSocket 音频会话可观测性（仅计数，不逐帧打印）──
        self.frames_received = 0
        self.frames_parsed_ok = 0
        self.frames_parse_failed = 0
        self.first_frame_monotonic_ms = None
        self.last_frame_monotonic_ms = None
        self.last_payload_bytes = 0
        self.total_payload_bytes = 0
        # 关闭类别（协议拒绝/keepalive 超时等由具体路径在关闭前显式标记）
        self.close_category = None

        # ── listen=start 快照（唤醒词预上传音频与实时音频的分界）──
        self.listen_start_seen = False
        self.listen_start_monotonic_ms = None
        self.frames_parsed_ok_at_listen_start = 0
        self.total_payload_bytes_at_listen_start = 0
        self.last_frame_monotonic_ms_at_listen_start = None

    async def handle_connection(self, ws):
        try:
            # 获取并验证headers
            self.headers = dict(ws.request.headers)
            real_ip = self.headers.get("x-real-ip") or self.headers.get(
                "x-forwarded-for"
            )
            if real_ip:
                self.client_ip = real_ip.split(",")[0].strip()
            else:
                self.client_ip = ws.remote_address[0]
            # 连接日志禁止输出明文 token/Authorization，只保留存在性与长度
            redacted_headers = {
                k: (f"<redacted:len={len(v)}>" if k.lower() == "authorization" else v)
                for k, v in self.headers.items()
            }
            self.logger.bind(tag=TAG).info(
                f"[conn] {self._cid()} client_ip={self.client_ip} "
                f"headers={redacted_headers}"
            )

            self.device_id = self.headers.get("device-id", None)
            trace.mark(self, "connect")
            trace.emit(
                "device.connect",
                self,
                {
                    "client_ip": self.client_ip,
                    "headers": self.headers,
                    "path": getattr(getattr(ws, "request", None), "path", None),
                },
            )

            # 认证通过,继续处理
            self.websocket = ws
            # 注册到 server：持设备锁切换 current，与出站 send 串行
            if self.server:
                await self.server.register_connection(
                    self.device_id or str(id(ws)), self
                )
                # 视觉 OTA：重连后串行查询并投递（Spine 优先，同一时刻仅一类）
                if self.device_id:
                    from core.utils.visual_ota_delivery import deliver_pending_visual_ota

                    asyncio.create_task(deliver_pending_visual_ota(self))

            # 检查是否来自MQTT连接
            request_path = ws.request.path
            self.conn_from_mqtt_gateway = request_path.endswith("?from=mqtt_gateway")
            if self.conn_from_mqtt_gateway:
                self.logger.bind(tag=TAG).info("连接来自:MQTT网关")

            # 初始化活动时间戳
            self.first_activity_time = time.time() * 1000
            self.last_activity_time = time.time() * 1000

            # 启动超时检查任务
            self.timeout_task = asyncio.create_task(self._check_timeout())

            self.welcome_msg = self.config["xiaozhi"]
            self.welcome_msg["session_id"] = self.session_id

            # 人物归属只来自本次连接查询到的设备绑定，不能沿用公共配置。
            self.config.pop("sys_user_id", None)
            self.config.pop("agent_id", None)
            # 获取设备特定的私有配置，如归属用户ID（用于按用户路由 one-api token）
            try:
                from config.manage_api_client import get_device_config
                from core.utils.account_identity import bind_face_account_on_conn

                device_info = await get_device_config(self.device_id)
                if device_info:
                    agent_id = device_info.get("agentId") or device_info.get("agent_id")
                    if agent_id:
                        self.agent_id = str(agent_id)
                        self.trace_id_missing_reasons.pop("agent_id", None)
                    user_id = device_info.get("userId") or device_info.get("user_id")
                    if user_id not in (None, ""):
                        self.device_user_id = str(user_id)
                    if agent_id and user_id not in (None, "") and str(user_id).isdecimal() and int(user_id) > 0:
                        # MCP 能力上报、目录同步、每轮人物冻结和存档均读取此连接的配置。
                        # 两个值必须同时取自同一条受服务密钥保护的设备绑定记录。
                        self.config["sys_user_id"] = str(user_id)
                        self.config["agent_id"] = str(agent_id)
                    device_row_id = device_info.get("id")
                    trace.emit(
                        "device.bound",
                        self,
                        {
                            "user_id": str(user_id) if user_id not in (None, "") else None,
                            "device_row_id": device_row_id,
                            "agent_id_source": "manager_api_device_by_mac",
                        },
                    )
                    face_aid = bind_face_account_on_conn(self, device_info)
                    if face_aid:
                        self.logger.bind(tag=TAG).info(
                            f"设备 face_account_id 已绑定，长度={len(face_aid)}"
                        )
                    else:
                        self.logger.bind(tag=TAG).warning(
                            "设备归属用户ID为空或非法，face 身份与提醒将 fail-closed"
                        )
                else:
                    self.logger.bind(tag=TAG).warning("未获取到设备配置，aimi 设备网关将无法按用户路由计费 token")
            except DeviceNotFoundException as e:
                self.logger.bind(tag=TAG).info(f"设备未找到，准备进入绑定流程: {e}")
            except DeviceBindException as e:
                self.logger.bind(tag=TAG).info(f"设备未绑定，准备进入绑定流程: {e}")
            except Exception as e:
                # fallback 保留（连接可继续），但明确记录失败类别与后果，避免静默掩盖正式配置问题
                self.logger.bind(tag=TAG).warning(
                    f"[device_config_fallback] {self._cid()} 获取设备配置失败，"
                    f"已降级为无 user_id 路由（aimi 网关计费 token 将不可用），原因: {e}"
                )

            # 获取差异化配置
            self._initialize_private_config()
            
            # 初始化提示词管理器并注入上下文
            self.prompt_manager = PromptManager(self.config, self.logger)

            # 异步初始化
            self.executor.submit(self._initialize_components)

            try:
                async for message in self.websocket:
                    await self._route_message(message)
            except websockets.exceptions.ConnectionClosed as e:
                # 记录 close code / reason / 发起端，便于排查连接被谁关闭
                rcvd = getattr(e, "rcvd", None)
                sent = getattr(e, "sent", None)
                rcvd_then_sent = getattr(e, "rcvd_then_sent", None)
                if rcvd_then_sent is True or (rcvd and not sent):
                    initiator = "client"
                elif rcvd_then_sent is False or (sent and not rcvd):
                    initiator = "server"
                else:
                    initiator = "unknown(abnormal)"
                close_frame = rcvd or sent
                close_code = getattr(close_frame, "code", None)
                close_reason = getattr(close_frame, "reason", "")
                category = self._classify_close(
                    exc=e, close_code=close_code, reason=close_reason
                )
                cause_info = self._format_close_cause(e)
                age_ms = max(
                    0,
                    self._monotonic_ms()
                    - int(getattr(self, "connection_started_monotonic_ms", self._monotonic_ms()) or 0),
                )
                last_out = getattr(self, "last_outbound_monotonic_ms", None)
                last_out_age = (
                    max(0, self._monotonic_ms() - last_out) if last_out else -1
                )
                self.logger.bind(tag=TAG).info(
                    f"[WebSocket close] {self._cid()} "
                    f"session_id={self._mask(self.session_id)} "
                    f"close_code={close_code} initiator={initiator} reason={close_reason!r} "
                    f"category={category} cause={cause_info} "
                    f"connection_age_ms={age_ms} "
                    f"last_outbound_age_ms={last_out_age} "
                    f"ws_ping_interval={getattr(self, 'ws_ping_interval', None)} "
                    f"ws_ping_timeout={getattr(self, 'ws_ping_timeout', None)} "
                    f"{self._frame_stats_fields()} "
                    f"last_frame_age_ms={self._last_frame_age_ms()} "
                    f"{self._listen_stats_fields()} "
                    f"{self._preinit_drop_field()}"
                )
                # 仅在本连接刚下发过 update_spine 且为异常断开时上报，避免误伤普通会话
                if initiator == "unknown(abnormal)":
                    await self._report_spine_delivery_aborted_if_needed(
                        initiator=initiator, category=category
                    )
                    await self._report_wallpaper_delivery_aborted_if_needed(
                        initiator=initiator, category=category
                    )

        except AuthenticationError as e:
            self.logger.bind(tag=TAG).error(f"Authentication failed: {str(e)}")
            return
        except Exception as e:
            stack_trace = traceback.format_exc()
            self.logger.bind(tag=TAG).error(
                f"[conn_error] {self._cid()} {str(e)}\n{stack_trace}"
            )
            return
        finally:
            try:
                await self._save_and_close(ws)
            except Exception as final_error:
                self.logger.bind(tag=TAG).error(f"最终清理时出错: {final_error}")
                # 确保即使保存记忆失败，也要关闭连接
                try:
                    await self.close(ws)
                except Exception as close_error:
                    self.logger.bind(tag=TAG).error(
                        f"强制关闭连接时出错: {close_error}"
                    )

    def _spine_ota_policy(self):
        """读取重投策略（优先环境变量，其次配置，最后默认）。"""
        from core.utils import spine_ota_store

        max_attempts = spine_ota_store.DEFAULT_MAX_ATTEMPTS
        backoff_base_s = spine_ota_store.DEFAULT_BACKOFF_BASE_S
        cfg = self.config.get("role_pack") or {}
        try:
            max_attempts = int(
                os.environ.get("SPINE_OTA_MAX_ATTEMPTS", cfg.get("max_attempts", max_attempts))
            )
        except (TypeError, ValueError):
            max_attempts = spine_ota_store.DEFAULT_MAX_ATTEMPTS
        try:
            backoff_base_s = float(
                os.environ.get("SPINE_OTA_BACKOFF_BASE_S", cfg.get("backoff_base_s", backoff_base_s))
            )
        except (TypeError, ValueError):
            backoff_base_s = spine_ota_store.DEFAULT_BACKOFF_BASE_S
        return max_attempts, backoff_base_s

    async def send_current_guarded(
        self,
        data,
        *,
        command: str = None,
        msg_type: str = None,
        task_id=None,
    ) -> bool:
        """本连接出站：统一经 guarded_ws_send；无 server / 非 current 一律 fail closed。

        禁止以「缺少方法」为由回退到裸 websocket.send。
        """
        from core.utils.device_outbound import guarded_ws_send

        return await guarded_ws_send(
            self,
            data,
            command=command,
            msg_type=msg_type,
            task_id=task_id,
        )

    def _is_stale_connection(self) -> bool:
        """当前连接是否已不再允许下行（superseded / 非 current / 无 server）。"""
        from core.utils.device_outbound import is_outbound_allowed

        return not is_outbound_allowed(self)

    def enqueue_tts(self, dto) -> bool:
        """TTS 文本入队（带 session 校验）；非 current 不入队。"""
        from core.utils.device_outbound import enqueue_tts

        return enqueue_tts(self, dto)

    async def _release_claimed_delivery(
        self, task_id: str, delivery_lease_id, claimed_session_id=None
    ) -> None:
        """领取后、发送前发现连接已 stale：向 manager-api 按 lease 精确释放。

        仅当中央任务仍持有本次不可复用 delivery_lease_id 时才回滚；
        旧 release 重放绝不能影响新 session 的 claim。best-effort。
        """
        if not delivery_lease_id:
            self.logger.bind(tag=TAG).warning(
                f"[update_spine] release_skip task_id={task_id} device_id={self.device_id} "
                f"reason=missing_lease"
            )
            return
        try:
            from config.manage_api_client import ManageApiClient

            client = ManageApiClient._instance
            if client is None:
                return False
            params = {
                "taskId": task_id,
                "deliveryLeaseId": delivery_lease_id,
            }
            if claimed_session_id:
                params["claimedSessionId"] = claimed_session_id
            await client.request(
                "POST",
                "role-packs/device/release-pending",
                headers={"X-Device-Id": self.device_id},
                params=params,
            )
            self.logger.bind(tag=TAG).info(
                f"[update_spine] release task_id={task_id} device_id={self.device_id} "
                f"session_id={self.session_id} lease_id={delivery_lease_id} "
                f"reason=stale_before_send"
            )
        except Exception as e:
            self.logger.bind(tag=TAG).warning(
                f"[update_spine] release_failed task_id={task_id} device_id={self.device_id} "
                f"lease_id={delivery_lease_id} reason={e}"
            )

    async def _deliver_pending_visual_ota(self):
        """设备重连后串行投递视觉 OTA（委托 visual_ota_delivery 模块）。"""
        from core.utils.visual_ota_delivery import deliver_pending_visual_ota

        await deliver_pending_visual_ota(self)

    async def _deliver_pending_spine_role(self, *, _skip_initial_sleep: bool = False):
        """设备重连后向 manager-api 查询待重投任务并推送 update_spine。

        Returns:
            bool: 是否已向设备成功下发 update_spine。
        """
        try:
            if not _skip_initial_sleep:
                await asyncio.sleep(1.0)
            if self._is_stale_connection():
                self.logger.bind(tag=TAG).info(
                    f"[update_spine] skip device_id={self.device_id} "
                    f"session_id={self.session_id} reason=stale_before_claim"
                )
                return False
            from config.manage_api_client import ManageApiClient

            client = ManageApiClient._instance
            if client is None:
                return False
            data = await client.request(
                "GET",
                "role-packs/device/pending",
                headers={
                    "X-Device-Id": self.device_id,
                    "X-Session-Id": self.session_id or "",
                },
                params={
                    "deviceId": self.device_id,
                    "sessionId": self.session_id,
                },
            )
            if not data or not data.get("hasPending"):
                self.logger.bind(tag=TAG).info(
                    f"[update_spine] skip device_id={self.device_id} reason=no_pending"
                )
                return False
            payload = data.get("payload")
            if not isinstance(payload, dict):
                return False
            task_id = payload.get("task_id") or data.get("taskId")
            pack_id = payload.get("pack_id") or payload.get("packId")
            delivery_lease_id = data.get("deliveryLeaseId")
            claimed_session_id = data.get("claimedSessionId") or self.session_id
            if not task_id:
                self.logger.bind(tag=TAG).warning(
                    f"[update_spine] skip device_id={self.device_id} reason=no_task_id"
                )
                return False

            if self.websocket is None:
                return False
            raw = json.dumps(payload, ensure_ascii=False)
            sent = await self.send_current_guarded(
                raw,
                command="update_spine",
                msg_type="system",
                task_id=task_id,
            )
            if not sent:
                await self._release_claimed_delivery(
                    task_id, delivery_lease_id, claimed_session_id
                )
                return False

            self.spine_update_sent_task_id = task_id
            self.spine_update_sent_at_ms = self._monotonic_ms()

            try:
                from core.utils import spine_ota_store

                spine_ota_store.record_sent_mirror(
                    task_id=task_id,
                    device_id=self.device_id,
                    pack_id=pack_id,
                    payload=payload,
                )
            except Exception as mirror_err:
                self.logger.bind(tag=TAG).debug(
                    f"[update_spine] local_mirror_failed task_id={task_id} "
                    f"device_id={self.device_id} reason={mirror_err}"
                )

            self.logger.bind(tag=TAG).info(
                f"[update_spine] deliver task_id={task_id} device_id={self.device_id} "
                f"lease_id={delivery_lease_id} reason=reconnect_pending"
            )
            return True
        except Exception as e:
            self.logger.bind(tag=TAG).warning(
                f"[update_spine] deliver_failed device_id={self.device_id} reason={e}"
            )
            return False

    async def _report_spine_delivery_aborted_if_needed(self, initiator: str, category: str):
        """update_spine 下发后异常断开：上报中央停止自动重投 + 本地审计镜像。"""
        task_id = getattr(self, "spine_update_sent_task_id", None)
        if not task_id or not self.device_id:
            return
        # 正常客户端关闭不视为投递崩溃
        if initiator == "client" and category == "normal_close":
            return
        try:
            from config.manage_api_client import ManageApiClient

            client = ManageApiClient._instance
            if client is not None:
                await client.request(
                    "POST",
                    "role-packs/device/delivery-aborted",
                    headers={"X-Device-Id": self.device_id},
                    params={"taskId": task_id},
                )
            # 本地审计镜像（best-effort）
            from core.utils import spine_ota_store

            spine_ota_store.record_abnormal_disconnect(task_id, self.device_id)
            self.spine_update_sent_task_id = None
        except Exception as e:
            self.logger.bind(tag=TAG).warning(
                f"[update_spine] abnormal_disconnect_failed task_id={task_id} "
                f"device_id={self.device_id} reason={e}"
            )

    async def _deliver_pending_wallpaper(self, *, _skip_initial_sleep: bool = False):
        """设备重连后向 manager-api 查询待重投壁纸任务并推送 update_wallpaper。

        Returns:
            bool: 是否已向设备成功下发 update_wallpaper。
        """
        try:
            if not _skip_initial_sleep:
                await asyncio.sleep(1.0)
            if self._is_stale_connection():
                self.logger.bind(tag=TAG).info(
                    f"[update_wallpaper] skip device_id={self.device_id} "
                    f"session_id={self.session_id} reason=stale_before_claim"
                )
                return False
            from config.manage_api_client import ManageApiClient

            client = ManageApiClient._instance
            if client is None:
                return False
            data = await client.request(
                "GET",
                "wallpaper-packs/device/pending",
                headers={
                    "X-Device-Id": self.device_id,
                    "X-Session-Id": self.session_id or "",
                },
                params={
                    "deviceId": self.device_id,
                    "sessionId": self.session_id,
                },
            )
            if not data or not data.get("hasPending"):
                self.logger.bind(tag=TAG).info(
                    f"[update_wallpaper] skip device_id={self.device_id} reason=no_pending"
                )
                return False
            payload = data.get("payload")
            if not isinstance(payload, dict):
                return False
            task_id = payload.get("task_id") or data.get("taskId")
            pack_id = payload.get("pack_id") or payload.get("packId")
            delivery_lease_id = data.get("deliveryLeaseId")
            claimed_session_id = data.get("claimedSessionId") or self.session_id
            if not task_id:
                self.logger.bind(tag=TAG).warning(
                    f"[update_wallpaper] skip device_id={self.device_id} reason=no_task_id"
                )
                return False

            if self.websocket is None:
                return False
            raw = json.dumps(payload, ensure_ascii=False)
            sent = await self.send_current_guarded(
                raw,
                command="update_wallpaper",
                msg_type="system",
                task_id=task_id,
            )
            if not sent:
                await self._release_claimed_wallpaper_delivery(
                    task_id, delivery_lease_id, claimed_session_id
                )
                return False

            self.wallpaper_update_sent_task_id = task_id
            self.wallpaper_update_sent_at_ms = self._monotonic_ms()

            try:
                from core.utils import wallpaper_ota_store

                wallpaper_ota_store.record_sent_mirror(
                    task_id=task_id,
                    device_id=self.device_id,
                    pack_id=pack_id,
                    payload=payload,
                )
            except Exception as mirror_err:
                self.logger.bind(tag=TAG).debug(
                    f"[update_wallpaper] local_mirror_failed task_id={task_id} "
                    f"device_id={self.device_id} reason={mirror_err}"
                )

            self.logger.bind(tag=TAG).info(
                f"[update_wallpaper] deliver task_id={task_id} device_id={self.device_id} "
                f"lease_id={delivery_lease_id} reason=reconnect_pending"
            )
            return True
        except Exception as e:
            self.logger.bind(tag=TAG).warning(
                f"[update_wallpaper] deliver_failed device_id={self.device_id} reason={e}"
            )
            return False

    async def _release_claimed_wallpaper_delivery(
        self, task_id, delivery_lease_id, claimed_session_id
    ):
        if not self.device_id or not task_id or not delivery_lease_id:
            return
        try:
            from config.manage_api_client import ManageApiClient

            client = ManageApiClient._instance
            if client is None:
                return
            await client.request(
                "POST",
                "wallpaper-packs/device/release-pending",
                headers={"X-Device-Id": self.device_id},
                params={
                    "taskId": task_id,
                    "deliveryLeaseId": delivery_lease_id,
                    "claimedSessionId": claimed_session_id or "",
                },
            )
            self.logger.bind(tag=TAG).info(
                f"[update_wallpaper] release task_id={task_id} device_id={self.device_id} "
                f"session_id={self.session_id} lease_id={delivery_lease_id} "
                f"reason=stale_before_send"
            )
        except Exception as e:
            self.logger.bind(tag=TAG).warning(
                f"[update_wallpaper] release_failed task_id={task_id} device_id={self.device_id} "
                f"lease_id={delivery_lease_id} reason={e}"
            )

    async def _report_wallpaper_delivery_aborted_if_needed(self, initiator: str, category: str):
        """update_wallpaper 下发后异常断开：上报中央停止自动重投 + 本地审计镜像。"""
        task_id = getattr(self, "wallpaper_update_sent_task_id", None)
        if not task_id or not self.device_id:
            return
        if initiator == "client" and category == "normal_close":
            return
        try:
            from config.manage_api_client import ManageApiClient

            client = ManageApiClient._instance
            if client is not None:
                await client.request(
                    "POST",
                    "wallpaper-packs/device/delivery-aborted",
                    headers={"X-Device-Id": self.device_id},
                    params={"taskId": task_id},
                )
            from core.utils import wallpaper_ota_store

            wallpaper_ota_store.record_abnormal_disconnect(task_id, self.device_id)
            self.wallpaper_update_sent_task_id = None
        except Exception as e:
            self.logger.bind(tag=TAG).warning(
                f"[update_wallpaper] abnormal_disconnect_failed task_id={task_id} "
                f"device_id={self.device_id} reason={e}"
            )

    async def _save_and_close(self, ws):
        """保存记忆并关闭连接"""
        try:
            if self.memory and (getattr(self.memory,"personal",False) or getattr(self.memory,"person_context",False)):
                from core.utils.person_short_memory import persist_compact
                for key,dialogue in getattr(self,"_person_dialogues",{}).items():
                    actor=getattr(self,"_person_dialogue_actors",{}).get(key)
                    if actor and actor.eligible:persist_compact(actor,dialogue)
            for dialogue in getattr(self,"_person_dialogues",{}).values():
                if dialogue.context_window:dialogue.context_window.invalidate()
            if self.memory and not getattr(self.memory,"person_context",False) and not hasattr(self,"_person_dialogues"):
                # 使用线程池异步保存记忆
                def save_memory_task():
                    try:
                        # 创建新事件循环（避免与主循环冲突）
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        loop.run_until_complete(
                            self.memory.save_memory(self.dialogue.dialogue)
                        )
                    except Exception as e:
                        self.logger.bind(tag=TAG).error(f"保存记忆失败: {e}")
                    finally:
                        try:
                            loop.close()
                        except Exception:
                            pass

                # 启动线程保存记忆，不等待完成
                threading.Thread(target=save_memory_task, daemon=True).start()
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"保存记忆失败: {e}")
        finally:
            # 立即关闭连接，不等待记忆保存完成
            try:
                await self.close(ws)
            except Exception as close_error:
                self.logger.bind(tag=TAG).error(
                    f"保存记忆后关闭连接失败: {close_error}"
                )

    async def _route_message(self, message):
        """消息路由

        单条消息处理异常不得导致整条 WebSocket 断开：
        此前任何 handler 抛异常都会冒泡到 handle_connection 的 except，
        进而走 finally -> close(ws)，设备侧表现为服务端 close 1000。
        ConnectionClosed 除外（连接确实已断，需要正常退出接收循环）。
        """
        try:
            await self._route_message_inner(message)
        except websockets.exceptions.ConnectionClosed:
            raise
        except Exception as e:
            self.logger.bind(tag=TAG).error(
                f"[recv_error] {self._cid()} {e}\n{traceback.format_exc()}"
            )

    def _cid(self) -> str:
        """诊断前缀：correlation_id + device_id，不含任何 token/密钥/会话原文。"""
        return f"correlation_id={self.correlation_id} device_id={self.device_id}"

    @staticmethod
    def _mask(value: str) -> str:
        """会话/标识脱敏：仅保留前缀，避免完整 UUID/标识落日志。"""
        if not value:
            return value
        if len(value) <= 8:
            return value[:2] + "***"
        return value[:8] + "..."

    @staticmethod
    def _monotonic_ms() -> int:
        """单调时钟毫秒，用于计算帧到达间隔与「最后一帧距关闭」时长。"""
        return int(time.monotonic() * 1000)

    def _audio_payload_len(self, message: bytes) -> int:
        """按协议版本剥离头部，返回 opus 负载字节数（无头时退化为整帧长度）。"""
        version = self.protocol_version
        if version == 2 and len(message) >= 16:
            return len(message) - 16
        if version == 3 and len(message) >= 4:
            return len(message) - 4
        return len(message)

    def _note_audio_frame(self, message: bytes) -> None:
        """记录一帧音频到达：仅计数，按阈值（第一帧/每 100 帧）打印紧凑日志。

        字节口径：``bytes`` 为剥离协议头后的 Opus payload 字节；
        protocol_version 未就绪时标 ``n/a``，不得用整帧长度回退误导。
        """
        now = self._monotonic_ms()
        self.frames_received += 1
        if self.first_frame_monotonic_ms is None:
            self.first_frame_monotonic_ms = now
        self.last_frame_monotonic_ms = now
        version = self.protocol_version
        if version is None:
            payload_len = None
        else:
            payload_len = self._audio_payload_len(message)
        self.last_payload_bytes = payload_len if payload_len is not None else 0
        if payload_len is not None:
            self.total_payload_bytes += payload_len
        if self.frames_received == 1 or self.frames_received % 100 == 0:
            bytes_label = "n/a" if payload_len is None else str(payload_len)
            self.logger.bind(tag=TAG).info(
                f"[audio_frame] {self._cid()} frame=#{self.frames_received} "
                f"bytes={bytes_label} total_bytes={self.total_payload_bytes}"
            )

    def _record_audio_frame_result(self, ok: bool) -> None:
        """记录解析结果：仅解析失败时打印紧凑告警，避免逐帧 INFO。"""
        if ok:
            self.frames_parsed_ok += 1
        else:
            self.frames_parse_failed += 1
            self.logger.bind(tag=TAG).warning(
                f"[audio_frame_parse_fail] {self._cid()} "
                f"frame=#{self.frames_received} bytes={self.last_payload_bytes} "
                f"parse_failed={self.frames_parse_failed}"
            )

    def _last_frame_age_ms(self) -> int:
        """最后一帧到达时刻到当前时刻的毫秒数；从未收到音频返回 -1。"""
        if self.last_frame_monotonic_ms is None:
            return -1
        return max(0, self._monotonic_ms() - self.last_frame_monotonic_ms)

    def _frame_stats_fields(self) -> str:
        """紧凑帧统计字段（仅计数与字节数，不含音频/文本/Token）。"""
        return (
            f"frames_received={self.frames_received} "
            f"frames_parsed_ok={self.frames_parsed_ok} "
            f"frames_parse_failed={self.frames_parse_failed} "
            f"total_payload_bytes={self.total_payload_bytes} "
            f"last_payload_bytes={self.last_payload_bytes}"
        )

    def _preinit_drop_field(self) -> str:
        """上行 VAD/ASR 未就绪丢弃帧计数（close 汇总输出）。"""
        return f"preinit_audio_dropped={getattr(self, 'preinit_audio_dropped', 0)}"

    def _finalize_tts_sentence(self, reason: str):
        """句级终态兜底输出；未开始的句子返回 None（不打印）。"""
        telemetry = getattr(self, "tts_sentence_telemetry", None)
        if telemetry is None:
            return None
        line = telemetry.finalize(reason, self._mask(self.session_id))
        if line:
            self.logger.bind(tag=TAG).info(line)
        return line

    @staticmethod
    def _format_close_cause(exc) -> str:
        """提取 ConnectionClosed 因果链类型与 errno（不包含敏感内容）。"""
        parts = []
        seen = set()
        cur = exc
        depth = 0
        while cur is not None and id(cur) not in seen and depth < 6:
            seen.add(id(cur))
            depth += 1
            errno = getattr(cur, "errno", None)
            winerror = getattr(cur, "winerror", None)
            parts.append(
                f"{type(cur).__name__}"
                + (f"(errno={errno})" if errno is not None else "")
                + (f"(winerror={winerror})" if winerror is not None else "")
            )
            cur = cur.__cause__ or cur.__context__
        return " > ".join(parts) if parts else "none"

    @staticmethod
    def _classify_close_exception(exc) -> str:
        """对底层异常分类，仅描述服务端观察到的传输层异常类别。

        注意：connection_reset / eof 仅表示「服务端侧读到的传输层异常」，
        不能据此断言是客户端还是网络主动发起（无 TCP 抓包证据时不下结论）。
        """
        if exc is None:
            return "normal_close"
        seen = set()
        cur = exc
        while cur is not None and id(cur) not in seen:
            seen.add(id(cur))
            if isinstance(cur, (ConnectionResetError, ConnectionAbortedError)):
                return "connection_reset"
            if isinstance(cur, EOFError):
                return "eof"
            if isinstance(cur, websockets.exceptions.ConnectionClosedOK):
                return "normal_close"
            if isinstance(cur, websockets.exceptions.ConnectionClosedError):
                # 进入 __cause__（底层传输异常），继续向上归类
                cur = cur.__cause__ or cur.__context__
                continue
            if isinstance(cur, asyncio.TimeoutError):
                return "timeout"
            cur = cur.__cause__ or cur.__context__
        return "other"

    def _classify_close(self, exc=None, close_code=None, reason="") -> str:
        """关闭归类：优先已标记类别，其次 keepalive 超时，再次底层异常。"""
        if self.close_category:
            return self.close_category
        if close_code == 1011 or "keepalive" in (reason or "").lower():
            self.close_category = "keepalive_timeout"
            return self.close_category
        self.close_category = self._classify_close_exception(exc)
        return self.close_category

    @staticmethod
    def _peek_message(message: str):
        """轻量解析文本消息的 type 与 session_id（供状态机校验，失败返回 (None, None)）。"""
        try:
            obj = json.loads(message)
        except Exception:
            return None, None
        if not isinstance(obj, dict):
            return None, None
        return obj.get("type"), obj.get("session_id")

    @staticmethod
    def _is_listen_start(message: str) -> bool:
        """判断文本消息是否为 type=listen 且 state=start（失败/缺失视为否）。"""
        try:
            obj = json.loads(message)
        except Exception:
            return False
        if not isinstance(obj, dict):
            return False
        return obj.get("type") == "listen" and obj.get("state") == "start"

    def _snapshot_listen_start(self) -> None:
        """记录 listen=start 时点的帧/字节快照，用于后续 after 增量统计。

        唤醒词预上传音频发生在 listen=start 之前，因此不计入 after 字段。
        """
        self.listen_start_seen = True
        self.listen_start_monotonic_ms = self._monotonic_ms()
        self.frames_parsed_ok_at_listen_start = self.frames_parsed_ok
        self.total_payload_bytes_at_listen_start = self.total_payload_bytes
        self.last_frame_monotonic_ms_at_listen_start = self.last_frame_monotonic_ms

    def _listen_stats_fields(self) -> str:
        """listen=start 之后的增量统计；未收到 listen=start 时 after 字段为 n/a。"""
        if not self.listen_start_seen:
            return (
                "listen_start_seen=false "
                "frames_after_listen_start=n/a "
                "payload_bytes_after_listen_start=n/a "
                "last_frame_after_listen_start_age_ms=n/a"
            )
        frames_after = self.frames_parsed_ok - self.frames_parsed_ok_at_listen_start
        bytes_after = self.total_payload_bytes - self.total_payload_bytes_at_listen_start
        if frames_after > 0 and self.last_frame_monotonic_ms is not None:
            last_age_after = max(
                0, self._monotonic_ms() - self.last_frame_monotonic_ms
            )
        else:
            last_age_after = "n/a"
        return (
            f"listen_start_seen=true "
            f"frames_after_listen_start={frames_after} "
            f"payload_bytes_after_listen_start={bytes_after} "
            f"last_frame_after_listen_start_age_ms={last_age_after}"
        )

    async def _reject_protocol(self, reason: str, close_code: int = 1002):
        """协议违规：返回协议错误并显式关闭，便于客户端与日志定位失败类别。"""
        self.close_category = "protocol_reject"
        self.logger.bind(tag=TAG).error(
            f"[protocol_reject] {self._cid()} reason={reason} close_code={close_code}"
        )
        try:
            await self.send_current_guarded(
                json.dumps(
                    {"type": "error", "code": "protocol_error", "message": reason},
                    ensure_ascii=False,
                ),
                command="error",
                msg_type="error",
            )
        except Exception:
            pass
        try:
            await self.websocket.close(code=close_code, reason=reason)
        except Exception:
            pass

    async def _route_message_inner(self, message):
        if isinstance(message, str):
            msg_type, session_id = self._peek_message(message)
            # 会话状态机：对可识别的非 hello 消息强制 hello 先行；协议版本/会话由本连接 hello 确定
            if msg_type is not None and msg_type != "hello":
                if not self.hello_received:
                    await self._reject_protocol("hello_required_first", close_code=1002)
                    return
                # 旧 session：携带的 session_id 与本连接不一致，显式拒绝
                if session_id and session_id != self.session_id:
                    await self._reject_protocol("stale_session", close_code=1008)
                    return
            # listen=start 快照：仅记录时点，不改变处理流程（唤醒词帧均在此之后到达）
            if msg_type == "listen" and self._is_listen_start(message):
                self._snapshot_listen_start()
            await handleTextMessage(self, message)
        elif isinstance(message, bytes):
            # 未完成 hello 直接拒绝音频帧
            if not self.hello_received:
                await self._reject_protocol("hello_required_before_audio", close_code=1002)
                return

            # 首次收到 binary 时打 INFO（在任意 early-return 之前），便于排查链路
            if not getattr(self, "_binary_received_logged", False):
                self._binary_received_logged = True
                self.logger.bind(tag=TAG).info(
                    f"[audio_first_frame] {self._cid()} raw_bytes={len(message)} "
                    f"session_id={self._mask(getattr(self, 'session_id', '?'))} "
                    f"protocol_version={getattr(self, 'protocol_version', None)}"
                )

            if self.vad is None or self.asr is None:
                # 上行预初始化丢弃：累计计数，首次 WARNING，之后每 5 秒最多一条限频
                self.preinit_audio_dropped = getattr(self, "preinit_audio_dropped", 0) + 1
                now_ms = self._monotonic_ms()
                last_warn_ms = getattr(self, "preinit_audio_last_warn_ms", 0)
                if self.preinit_audio_dropped == 1 or now_ms - last_warn_ms >= 5000:
                    self.preinit_audio_last_warn_ms = now_ms
                    self.logger.bind(tag=TAG).warning(
                        f"[preinit_audio_drop] {self._cid()} 收到 binary 但 VAD/ASR 未就绪，"
                        f"丢弃；vad={self.vad is not None} asr={self.asr is not None} "
                        f"dropped={self.preinit_audio_dropped}"
                    )
                return

            # 未绑定设备直接丢弃所有音频，不进行ASR处理
            if self.need_bind:
                current_time = time.time()
                # 检查是否需要播放绑定提示
                if (
                    current_time - self.last_bind_prompt_time
                    >= self.bind_prompt_interval
                ):
                    self.last_bind_prompt_time = current_time
                    # 复用现有的绑定提示逻辑
                    from core.handle.receiveAudioHandle import check_bind_device

                    asyncio.create_task(check_bind_device(self))
                # 直接丢弃音频，不进行ASR处理
                return

            await self.handle_binary_audio(message)

    def _set_protocol_version(self, version, source="unknown"):
        """设置连接音频协议版本，并同步下行 TTS 使用的 audio_protocol_version。

        协议版本必须由本连接的 hello 确定；无效/未知版本返回 False（调用方据此拒绝），
        不再静默降级到 v1。
        """
        try:
            version = int(version)
        except (TypeError, ValueError):
            self.logger.bind(tag=TAG).warning(
                f"无效协议版本值 {version!r} (来源: {source})"
            )
            return False

        if version not in (1, 2, 3):
            self.logger.bind(tag=TAG).warning(
                f"未知协议版本 {version} (来源: {source})"
            )
            return False

        self.protocol_version = version
        self.audio_protocol_version = version
        self.logger.bind(tag=TAG).info(
            f"[hello] {self._cid()} protocol_version={version} (来源: {source})"
        )
        trace.emit(
            "device.protocol",
            self,
            {"protocol_version": version, "source": source, "audio_format": getattr(self, "audio_format", None)},
        )
        return True

    async def handle_binary_audio(self, message: bytes):
        """按 protocol_version 分流处理 WebSocket 上行音频。"""
        self._note_audio_frame(message)
        version = self.protocol_version
        if version is None:
            await self._reject_protocol("protocol_version_unknown", close_code=1002)
            return

        if version == 1:
            if len(message) <= 1:
                self.logger.bind(tag=TAG).debug(
                    f"丢弃过小裸 Opus 包 len={len(message)} protocol_version=1"
                )
                note_short_payload_gap(
                    self,
                    protocol=1,
                    payload_bytes=len(message),
                    payload=message,
                )
                return
            self.logger.bind(tag=TAG).debug(
                f"上行音频走 raw opus len={len(message)} protocol_version=1"
            )
            self._trace_uplink_frame(
                protocol=1,
                raw_bytes=len(message),
                header_bytes=0,
                payload_bytes=len(message),
            )
            queue_audio(self, message)
            self.frames_parsed_ok += 1
            return

        if version == 2:
            handled = await self._process_binary_protocol2_audio(message)
            self._record_audio_frame_result(handled)
            if not handled:
                await self._reject_protocol("invalid_audio_frame_v2", close_code=1002)
                return
            return

        if version == 3:
            handled = await self._process_binary_protocol3_audio(message)
            self._record_audio_frame_result(handled)
            if not handled:
                await self._reject_protocol("invalid_audio_frame_v3", close_code=1002)
                return
            return

        self.logger.bind(tag=TAG).warning(
            f"未知协议版本 {version}，丢弃上行音频 len={len(message)}"
        )

    async def _process_binary_protocol2_audio(self, message: bytes) -> bool:
        """严格解析 BinaryProtocol2（16 字节头，大端）。"""
        if len(message) < 16:
            return False

        version, msg_type, reserved, timestamp, payload_size = struct.unpack(
            "!HHIII", message[:16]
        )

        if version != 2:
            return False
        if msg_type != 0:
            return False
        if payload_size != len(message) - 16:
            return False

        payload = message[16:]
        if len(payload) <= 1:
            self.logger.bind(tag=TAG).debug(
                f"BinaryProtocol2 忽略过小 payload len={len(payload)}"
            )
            trace.emit(
                "audio.uplink_drop",
                self,
                {"reason": "payload_too_small", "protocol": 2, "payload_bytes": len(payload)},
            )
            note_short_payload_gap(
                self,
                protocol=2,
                payload_bytes=len(payload),
                timestamp=timestamp,
                payload=payload,
            )
            return True

        self.logger.bind(tag=TAG).debug(
            f"上行音频走 BinaryProtocol2 payload_len={len(payload)} timestamp={timestamp}"
        )
        self._trace_uplink_frame(
            protocol=2,
            raw_bytes=len(message),
            header_bytes=16,
            payload_bytes=len(payload),
            timestamp=timestamp,
            reserved=reserved,
            msg_type=msg_type,
        )
        mark_valid_uplink_timestamp(self, timestamp)
        if self.conn_from_mqtt_gateway:
            self._process_websocket_audio(payload, timestamp)
        else:
            queue_audio(self, payload)
        return True

    async def _process_binary_protocol3_audio(self, message: bytes) -> bool:
        """严格解析 BinaryProtocol3（4 字节头，大端）。"""
        if len(message) < 4:
            return False

        msg_type, reserved, payload_size = struct.unpack("!BBH", message[:4])

        if msg_type != 0:
            return False
        if payload_size != len(message) - 4:
            return False

        payload = message[4:]
        if len(payload) <= 1:
            self.logger.bind(tag=TAG).debug(
                f"BinaryProtocol3 忽略过小 payload len={len(payload)}"
            )
            trace.emit(
                "audio.uplink_drop",
                self,
                {"reason": "payload_too_small", "protocol": 3, "payload_bytes": len(payload)},
            )
            note_short_payload_gap(
                self, protocol=3, payload_bytes=len(payload), payload=payload
            )
            return True

        self.logger.bind(tag=TAG).debug(
            f"上行音频走 BinaryProtocol3 payload_len={len(payload)}"
        )
        self._trace_uplink_frame(
            protocol=3,
            raw_bytes=len(message),
            header_bytes=4,
            payload_bytes=len(payload),
            msg_type=msg_type,
        )
        queue_audio(self, payload)
        return True

    def _trace_uplink_frame(self, *, protocol, raw_bytes, header_bytes, payload_bytes, **fields):
        self._trace_uplink_seq = getattr(self, "_trace_uplink_seq", 0) + 1
        seq = self._trace_uplink_seq
        stats = getattr(self, "_audio_ingress_stats", None) or {}
        first = trace.mark(self, "first_uplink")
        # 首帧、每 10 帧、以及入队积压时记录，避免每包刷盘
        queue_size = "unknown"
        try:
            queue_size = int(self.asr_audio_queue.qsize())
        except Exception:
            pass
        if seq != 1 and seq % 10 != 0 and not (isinstance(queue_size, int) and queue_size >= 50):
            return
        trace.emit(
            "audio.uplink_frame",
            self,
            {
                "seq": seq,
                "protocol_version": protocol,
                "raw_bytes": raw_bytes,
                "header_bytes": header_bytes,
                "payload_bytes": payload_bytes,
                "payload_encoding": getattr(self, "audio_format", None) or "opus",
                "sample_rate": "unknown",
                "channels": "unknown",
                "duration_ms": "unknown",
                "queue_size": queue_size,
                "ingress_stats": dict(stats),
                "first_uplink": first is not None,
                **fields,
            },
        )

    def _process_websocket_audio(self, audio_data, timestamp):
        """处理WebSocket格式的音频包"""
        # 初始化时间戳序列管理
        if not hasattr(self, "audio_timestamp_buffer"):
            self.audio_timestamp_buffer = {}
            self.last_processed_timestamp = 0
            self.max_timestamp_buffer_size = 20

        # 如果时间戳是递增的，直接处理
        if timestamp >= self.last_processed_timestamp:
            queue_audio(self, audio_data)
            self.last_processed_timestamp = timestamp

            # 处理缓冲区中的后续包
            processed_any = True
            while processed_any:
                processed_any = False
                for ts in sorted(self.audio_timestamp_buffer.keys()):
                    if ts > self.last_processed_timestamp:
                        buffered_audio = self.audio_timestamp_buffer.pop(ts)
                        queue_audio(self, buffered_audio)
                        self.last_processed_timestamp = ts
                        processed_any = True
                        break
        else:
            # 乱序包，暂存
            if len(self.audio_timestamp_buffer) < self.max_timestamp_buffer_size:
                self.audio_timestamp_buffer[timestamp] = audio_data
            else:
                queue_audio(self, audio_data)

    async def handle_restart(self, message):
        """处理服务器重启请求"""
        try:

            self.logger.bind(tag=TAG).info("收到服务器重启指令，准备执行...")

            # 发送确认响应
            await self.send_current_guarded(
                json.dumps(
                    {
                        "type": "server",
                        "status": "success",
                        "message": "服务器重启中...",
                        "content": {"action": "restart"},
                    }
                ),
                command="server",
                msg_type="server",
            )

            # 异步执行重启操作
            def restart_server():
                """实际执行重启的方法"""
                time.sleep(1)
                self.logger.bind(tag=TAG).info("执行服务器重启...")
                subprocess.Popen(
                    [sys.executable, "app.py"],
                    stdin=sys.stdin,
                    stdout=sys.stdout,
                    stderr=sys.stderr,
                    start_new_session=True,
                )
                os._exit(0)

            # 使用线程执行重启避免阻塞事件循环
            threading.Thread(target=restart_server, daemon=True).start()

        except Exception as e:
            self.logger.bind(tag=TAG).error(f"重启失败: {str(e)}")
            await self.send_current_guarded(
                json.dumps(
                    {
                        "type": "server",
                        "status": "error",
                        "message": f"Restart failed: {str(e)}",
                        "content": {"action": "restart"},
                    }
                ),
                command="server",
                msg_type="server",
            )

    def _initialize_components(self):
        try:
            self.selected_module_str = build_module_string(
                self.config.get("selected_module", {})
            )
            self.logger = create_connection_logger(self.selected_module_str)

            """初始化组件"""
            if self.config.get("prompt") is not None:
                user_prompt = self.config["prompt"]
                # 使用快速提示词进行初始化
                prompt = self.prompt_manager.get_quick_prompt(user_prompt)
                self.change_system_prompt(prompt)
                self.logger.bind(tag=TAG).info(
                    f"快速初始化组件: prompt成功 {prompt[:50]}..."
                )

            """初始化本地组件"""
            if self.vad is None:
                self.vad = self._vad
            if self.asr is None:
                self.asr = self._initialize_asr()

            # 初始化声纹识别
            self._initialize_voiceprint()

            # 打开语音识别通道
            asyncio.run_coroutine_threadsafe(
                self.asr.open_audio_channels(self), self.loop
            )
            if self.tts is None:
                self.tts = self._initialize_tts()
            # 打开语音合成通道
            asyncio.run_coroutine_threadsafe(
                self.tts.open_audio_channels(self), self.loop
            )

            """初始化LLM模块 - 独立出来以防被遗漏"""
            self._init_llm_module()
            self._bind_aimi_device_context()

            """加载记忆"""
            self._initialize_memory()
            """加载意图识别"""
            self._initialize_intent()
            """初始化上报线程"""
            self._init_report_threads()
            """更新系统提示词"""
            self._init_prompt_enhancement()

        except Exception as e:
            self.logger.bind(tag=TAG).error(f"实例化组件失败: {e}")

    def _init_llm_module(self):
        """初始化主要的 LLM 模型模块"""
        if self.llm is None and not self.need_bind:
            try:
                from core.utils import llm as llm_utils
                llm_config = self.config["LLM"]
                llm_name = self.config["selected_module"]["LLM"]
                
                if llm_name and llm_name in llm_config:
                    current_llm_config = llm_config[llm_name]
                    llm_type = current_llm_config.get("type", llm_name)
                    self.llm = llm_utils.create_instance(llm_type, current_llm_config)
                    self.logger.bind(tag=TAG).info(f"成功初始化大模型: {llm_name}, 类型: {llm_type}")
                else:
                    self.logger.bind(tag=TAG).warning(f"无法找到配置的大模型: {llm_name}")
            except Exception as e:
                self.logger.bind(tag=TAG).error(f"初始化 LLM 模块失败: {e}")

    def _bind_aimi_device_context(self):
        """Pass server-only ESP32 context to providers configured for the internal AIMI gateway."""
        context = {
            "device_id": self.device_id or "unknown-device",
            "mac_address": self.headers.get("mac-address", self.device_id or "") if self.headers else "",
            "user_id": self.device_user_id or "",
            "session_id": self.session_id,
        }
        if not context["user_id"]:
            self.logger.bind(tag=TAG).warning(
                "aimi 设备网关上下文缺少 user_id，将无法按用户路由 one-api 计费 token"
            )
        for provider in (self.llm, self.asr, self.tts):
            bind_context = getattr(provider, "set_aimi_device_context", None)
            if callable(bind_context):
                bind_context(context)

    def _init_prompt_enhancement(self):
        # 更新上下文信息
        self.prompt_manager.update_context_info(self, self.client_ip)

        # v2：构建固定三层 system（L1 平台规则 / L2 人格 / L3 会话固定资料）
        tts = getattr(self, "tts", None)
        official_enhanced = bool(tts is not None and getattr(tts, "official_enhanced", False))
        enhanced_prompt = self.prompt_manager.build_enhanced_prompt_v2(
            self.config["prompt"],
            self.device_id,
            self.client_ip,
            device_name=getattr(self, "device_custom_name", "小智"),
            user_nickname=getattr(self, "user_nickname", "用户"),
            official_enhanced=official_enhanced,
        )
        if enhanced_prompt:
            self.change_system_prompt(enhanced_prompt)
            self.logger.bind(tag=TAG).debug("系统提示词已增强更新")

    def _init_report_threads(self):
        """初始化ASR和TTS上报线程"""
        if not self.read_config_from_api or self.need_bind:
            return
        if self.chat_history_conf == 0:
            return
        if self.report_thread is None or not self.report_thread.is_alive():
            self.report_thread = threading.Thread(
                target=self._report_worker, daemon=True
            )
            self.report_thread.start()
            self.logger.bind(tag=TAG).info("TTS上报线程已启动")

    def _initialize_tts(self):
        """初始化TTS"""
        tts = None
        if not self.need_bind:
            tts = initialize_tts(self.config)

        if tts is None:
            tts = DefaultTTS(self.config, delete_audio_file=True)

        return tts

    def _initialize_asr(self):
        """初始化ASR"""
        if self._asr.interface_type == InterfaceType.LOCAL:
            # 如果公共ASR是本地服务，则直接返回
            # 因为本地一个实例ASR，可以被多个连接共享
            asr = self._asr
        else:
            # 如果公共ASR是远程服务，则初始化一个新实例
            # 因为远程ASR，涉及到websocket连接和接收线程，需要每个连接一个实例
            asr = initialize_asr(self.config)

        return asr

    def _initialize_voiceprint(self):
        """为当前连接初始化声纹识别"""
        try:
            voiceprint_config = self.config.get("voiceprint", {})
            if voiceprint_config:
                voiceprint_provider = VoiceprintProvider(voiceprint_config)
                if voiceprint_provider is not None and voiceprint_provider.enabled:
                    self.voiceprint_provider = voiceprint_provider
                    self.logger.bind(tag=TAG).info("声纹识别功能已在连接时动态启用")
                else:
                    self.logger.bind(tag=TAG).warning("声纹识别功能启用但配置不完整")
            else:
                self.logger.bind(tag=TAG).info("声纹识别功能未启用")
        except Exception as e:
            self.logger.bind(tag=TAG).warning(f"声纹识别初始化失败: {str(e)}")

    def _initialize_private_config(self):
        """如果是从配置文件获取，则进行二次实例化"""
        if not self.read_config_from_api:
            return
        """从接口获取差异化的配置进行二次实例化，非全量重新实例化"""
        try:
            begin_time = time.time()  
            # 1. 正常请求 API 获取配置
            private_config = get_private_config_from_api(
                self.config,
                self.headers.get("device-id"),
                self.headers.get("client-id", self.headers.get("device-id")),
            )

            # 2. =========== 【Genesis 修改：动态读取】 ===========
            # 从 API 返回的配置里寻找这些字段，如果找不到则使用 __init__ 里的默认值
            # 假设你在智控台存入的字段名叫 device_name 和 user_nickname
            if "device_name" in private_config:
                self.device_custom_name = private_config["device_name"]
            
            if "user_nickname" in private_config:
                self.user_nickname = private_config["user_nickname"]

            self.logger.bind(tag=TAG).info(f"【Genesis 阶段二】从云端加载身份：我是{self.device_custom_name}，主人是{self.user_nickname}")
            # 2. =========== 【修改结束】 ===========
            private_config["delete_audio"] = bool(self.config.get("delete_audio", True))
            self.logger.bind(tag=TAG).info(
                f"{time.time() - begin_time} 秒，获取差异化配置成功: {json.dumps(filter_sensitive_info(private_config), ensure_ascii=False)}"
            )
        except DeviceNotFoundException as e:
            self.need_bind = True
            private_config = {}
        except DeviceBindException as e:
            self.need_bind = True
            self.bind_code = e.bind_code
            private_config = {}
        except Exception as e:
            # 网络或鉴权等未知错误不应中断连接，而是进入默认的"访客模式"
            self.logger.bind(tag=TAG).error(f"获取差异化配置失败，将使用默认配置作为访客模式: {e}")
            private_config = {}

        init_llm, init_tts, init_memory, init_intent = (
            False,
            False,
            False,
            False,
        )

        init_vad = check_vad_update(self.common_config, private_config)
        init_asr = check_asr_update(self.common_config, private_config)

        if init_vad:
            self.config["VAD"] = private_config["VAD"]
            self.config["selected_module"]["VAD"] = private_config["selected_module"][
                "VAD"
            ]
        if init_asr:
            self.config["ASR"] = private_config["ASR"]
            self.config["selected_module"]["ASR"] = private_config["selected_module"][
                "ASR"
            ]
        if private_config.get("TTS", None) is not None:
            init_tts = True
            self.config["TTS"] = private_config["TTS"]
            self.config["selected_module"]["TTS"] = private_config["selected_module"][
                "TTS"
            ]
        if private_config.get("LLM", None) is not None:
            init_llm = True
            self.config["LLM"] = private_config["LLM"]
            self.config["selected_module"]["LLM"] = private_config["selected_module"][
                "LLM"
            ]
        if private_config.get("VLLM", None) is not None:
            self.config["VLLM"] = private_config["VLLM"]
            self.config["selected_module"]["VLLM"] = private_config["selected_module"][
                "VLLM"
            ]
        if private_config.get("Memory", None) is not None:
            init_memory = True
            self.config["Memory"] = private_config["Memory"]
            self.config["selected_module"]["Memory"] = private_config[
                "selected_module"
            ]["Memory"]
        if private_config.get("Intent", None) is not None:
            init_intent = True
            self.config["Intent"] = private_config["Intent"]
            model_intent = private_config.get("selected_module", {}).get("Intent", {})
            self.config["selected_module"]["Intent"] = model_intent
            # 加载插件配置
            if model_intent != "Intent_nointent":
                plugin_from_server = private_config.get("plugins", {})
                for plugin, config_str in plugin_from_server.items():
                    plugin_from_server[plugin] = json.loads(config_str)
                self.config["plugins"] = plugin_from_server
                self.config["Intent"][self.config["selected_module"]["Intent"]][
                    "functions"
                ] = plugin_from_server.keys()
        if private_config.get("prompt", None) is not None:
            self.config["prompt"] = private_config["prompt"]
        # 获取声纹信息
        if private_config.get("voiceprint", None) is not None:
            self.config["voiceprint"] = private_config["voiceprint"]
        if private_config.get("summaryMemory", None) is not None:
            self.config["summaryMemory"] = private_config["summaryMemory"]
        if private_config.get("device_max_output_size", None) is not None:
            self.max_output_size = int(private_config["device_max_output_size"])
        if private_config.get("chat_history_conf", None) is not None:
            self.chat_history_conf = int(private_config["chat_history_conf"])
        if private_config.get("mcp_endpoint", None) is not None:
            self.config["mcp_endpoint"] = private_config["mcp_endpoint"]
        try:
            modules = initialize_modules(
                self.logger,
                private_config,
                init_vad,
                init_asr,
                init_llm,
                init_tts,
                init_memory,
                init_intent,
            )
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"初始化组件失败: {e}")
            modules = {}
        if modules.get("tts", None) is not None:
            self.tts = modules["tts"]
        if modules.get("vad", None) is not None:
            self.vad = modules["vad"]
        if modules.get("asr", None) is not None:
            self.asr = modules["asr"]
        if modules.get("llm", None) is not None:
            self.llm = modules["llm"]
        if modules.get("intent", None) is not None:
            self.intent = modules["intent"]
        if modules.get("memory", None) is not None:
            self.memory = modules["memory"]

    def _instantiate_memory(self):
        """按当前配置创建独立的 Memory 实例（绝不复用共享单例）。"""
        from core.utils import memory as memory_utils

        selected = (self.config.get("selected_module") or {}).get("Memory")
        memory_cfg = self.config.get("Memory") or {}
        if not selected or selected not in memory_cfg:
            # 角色私有配置缺 Memory 时使用 nomem，仍为每连接独立实例。
            return memory_utils.create_instance(
                "nomem", {}, self.config.get("summaryMemory", None)
            )
        memory_type = (
            selected
            if "type" not in memory_cfg[selected]
            else memory_cfg[selected]["type"]
        )
        return memory_utils.create_instance(
            memory_type,
            memory_cfg[selected],
            self.config.get("summaryMemory", None),
        )

    def _initialize_memory(self):
        if self.memory is None:
            try:
                self.memory = self._instantiate_memory()
            except Exception as e:
                self.memory_init_error = str(e)
                self.logger.bind(tag=TAG).error(
                    f"实例化记忆模块失败: {e}\n{traceback.format_exc()}"
                )
                return
        """初始化记忆模块"""
        self.memory.init_memory(
            role_id=self.device_id,
            llm=self.llm,
            summary_memory=self.config.get("summaryMemory", None),
            save_to_file=not self.read_config_from_api,
        )

        # 获取记忆总结配置。缺 Memory 时约定为 nomem，不再访问缺失节。
        memory_config = self.config.get("Memory") or {}
        selected = (self.config.get("selected_module") or {}).get("Memory")
        if not selected or selected not in memory_config:
            return
        selected_cfg = memory_config[selected] or {}
        memory_type = selected_cfg.get("type", selected)
        # 如果使用 nomen，直接返回
        if memory_type == "nomem":
            return
        # 使用 mem_local_short 模式
        elif memory_type == "mem_local_short":
            memory_llm_name = selected_cfg.get("llm")
            if memory_llm_name and memory_llm_name in (self.config.get("LLM") or {}):
                # 如果配置了专用LLM，则创建独立的LLM实例
                from core.utils import llm as llm_utils

                memory_llm_config = dict(self.config["LLM"][memory_llm_name])
                memory_llm_config["_config_name"] = memory_llm_name
                memory_llm_type = memory_llm_config.get("type", memory_llm_name)
                memory_llm = llm_utils.create_instance(
                    memory_llm_type, memory_llm_config
                )
                self.logger.bind(tag=TAG).info(
                    f"为记忆总结创建了专用LLM: {memory_llm_name}, 类型: {memory_llm_type}"
                )
                self.memory.set_llm(memory_llm)
            else:
                # 否则使用主LLM
                self.memory.set_llm(self.llm)
                self.logger.bind(tag=TAG).info("使用主LLM作为意图识别模型")

    def _initialize_intent(self):
        if getattr(self.memory,"personal",False):
            # The selected main provider owns tool calling. A separate intent
            # model must not cause a paid Search before the main model asks.
            self.intent_type="function_call"
            self.load_function_plugin=True
            self._initialize_function_tools()
            return
        if self.intent is None:
            return
        self.intent_type = self.config["Intent"][
            self.config["selected_module"]["Intent"]
        ]["type"]
        if self.intent_type == "function_call" or self.intent_type == "intent_llm":
            self.load_function_plugin = True
        """初始化意图识别模块"""
        # 获取意图识别配置
        intent_config = self.config["Intent"]
        intent_type = self.config["Intent"][self.config["selected_module"]["Intent"]][
            "type"
        ]

        # 如果使用 nointent，直接返回
        if intent_type == "nointent":
            return
        # 使用 intent_llm 模式
        elif intent_type == "intent_llm":
            intent_llm_name = intent_config[self.config["selected_module"]["Intent"]][
                "llm"
            ]

            if intent_llm_name and intent_llm_name in self.config["LLM"]:
                # 如果配置了专用LLM，则创建独立的LLM实例
                from core.utils import llm as llm_utils

                intent_llm_config = self.config["LLM"][intent_llm_name]
                intent_llm_type = intent_llm_config.get("type", intent_llm_name)
                intent_llm = llm_utils.create_instance(
                    intent_llm_type, intent_llm_config
                )
                self.logger.bind(tag=TAG).info(
                    f"为意图识别创建了专用LLM: {intent_llm_name}, 类型: {intent_llm_type}"
                )
                self.intent.set_llm(intent_llm)
            else:
                # 否则使用主LLM
                self.intent.set_llm(self.llm)
                self.logger.bind(tag=TAG).info("使用主LLM作为意图识别模型")

        self._initialize_function_tools()

    def _initialize_function_tools(self):
        """Create tools for both normal intent routing and personal memory."""
        self.func_handler = UnifiedToolHandler(self)

        # 异步初始化工具处理器
        if hasattr(self, "loop") and self.loop:
            asyncio.run_coroutine_threadsafe(self.func_handler._initialize(), self.loop)

    def change_system_prompt(self, prompt):
        # v2：prompt 已是固定三层静态内容（含身份/摄像头/表达约束），直接落库，不再拼接动态内容
        self.prompt = prompt
        self.dialogue.update_system_message(self.prompt)

    def _consume_speech_emotion_hint(self):
        """One-turn ASR emotion reference. Not persisted into user text or memory.

        返回 (result, hint)：
        - result：原始情绪结果 dict（v2 用于轮次快照，与 TTS 能力解耦）。
        - hint：v1 的 system 注入文本（仅当 inject 开关开启时生成）。

        一次性消费并核对轮次：结果必须匹配当前正在处理的 (listen_epoch,
        utterance_id)，否则丢弃（跨监听代迟到 / 同监听代内其他语音段）。
        """
        from core.utils.speech_emotion import (
            build_llm_hint,
            inject_emotion_enabled,
            emotion_matches_turn,
        )

        selected = (self.config.get("selected_module") or {}).get("ASR")
        asr_cfg = ((self.config.get("ASR") or {}).get(selected) or {})
        result = getattr(self, "speech_turn_result", None)
        self.speech_turn_result = None
        self._trace_last_emotion_result = result if isinstance(result, dict) else None

        # 核对轮次：不匹配则丢弃情绪结果（不绑定、不注入），但不中断对话
        if isinstance(result, dict) and not emotion_matches_turn(self, result):
            trace.emit(
                "asr.emotion_rejected",
                self,
                {
                    "reason": "turn_mismatch",
                    "result_utterance_id": result.get("utterance_id"),
                    "result_listen_epoch": result.get("listen_epoch"),
                    "conn_utterance_id": getattr(self, "utterance_id", None),
                    "conn_listen_epoch": getattr(self, "listen_epoch", None),
                },
            )
            result = None
            self._trace_last_emotion_result = None

        if not inject_emotion_enabled(asr_cfg) and not getattr(
            self, "inject_emotion_hint", False
        ):
            return result, None
        hint = build_llm_hint(result)
        return result, hint or None

    def chat(self, query, depth=0, _tts_turn=None, _identity=None):
        from core.utils.person_identity import activate, deactivate, current_turn, freeze, select_dialogue
        import threading
        if not hasattr(self,"_person_chat_lock"):
            self._person_chat_lock=threading.RLock()
        with self._person_chat_lock:
            actor=_identity or (current_turn(self) if depth else None)
            if actor is None:
                actor=freeze(self,{"mode":"unavailable"},status="system")
            token=activate(self,actor)
            material_started=False
            try:
                if depth==0:
                    if actor.listen_epoch != int(getattr(self,"listen_epoch",0)):
                        return
                    select_dialogue(self,actor)
                    if not hasattr(self,"_person_inputs"):self._person_inputs={}
                    self._person_inputs[actor.turn_id]=query or ""
                    if len(self._person_inputs)>128:self._person_inputs.pop(next(iter(self._person_inputs)))
                    if getattr(getattr(self,"memory",None),"personal",False):
                        self.memory.record_turn(self,actor,query or "")
                        material_started=True
                result=self._chat_impl(query,depth,_tts_turn)
                if depth==0 and actor.eligible:
                    from core.utils.person_short_memory import persist_compact
                    persist_compact(actor,self.dialogue)
                return result
            except Exception:
                self.logger.bind(tag=TAG).exception(
                    "Chat task failed before completing its response"
                )
                if depth == 0:
                    self.llm_finish_task = True
                    if (actor.listen_epoch == int(getattr(self, "listen_epoch", 0))
                            and not getattr(self, "client_abort", False)):
                        try:
                            self._send_fallback_voice(
                                "抱歉，处理这次请求时出错了，请稍后再试。",
                                _tts_turn=_tts_turn,
                            )
                        except Exception:
                            self.logger.bind(tag=TAG).exception(
                                "Chat failure feedback could not be queued"
                            )
                return False
            finally:
                if depth==0 and material_started:
                    try:
                        self.memory.record_response(self,actor,self.dialogue.dialogue)
                    except Exception:
                        self.logger.bind(tag=TAG).exception("Turn material finalization failed")
                deactivate(token)

    def _chat_impl(self, query, depth=0, _tts_turn=None):
        from core.utils.person_identity import current_turn
        from core.utils.operation_control import enabled as operation_enabled, get_control, actor_scope
        # 1. 处理可能挂载的物理触摸事件
        pending_prompt = getattr(self, "pending_touch_prompt", None)
        if pending_prompt:
            # 消费掉该事件，避免重复触发
            self.pending_touch_prompt = None

            junk_phrases = ["你好啊", "你好呀", "我的朋友", "你好朋友", "。"]
            query_str = str(query).strip() if query else ""

            is_junk = False
            if not query_str or len(query_str) <= 1:
                is_junk = True
            elif any(junk in query_str for junk in junk_phrases):
                is_junk = True
            elif len(query_str) < 10 and "你好" in query_str:
                is_junk = True

            if is_junk:
                self.logger.bind(tag=TAG).info(f"过滤掉物理敲击产生的杂音 ASR: '{query}'")
                query = f"{pending_prompt}"
            else:
                self.logger.bind(tag=TAG).info(f"合并触摸事件与真实语音: '{query}'")
                query = f"{pending_prompt} 然后用户刚刚对你说：{query}"

        # 兜底：如果没触摸，但由于某些原因传来了极短的空白，防止报错
        if depth == 0 and (not query or str(query).strip() == ""):
            self.logger.bind(tag=TAG).warning("收到空查询，直接忽略")
            return

        if query is not None:
            self.logger.bind(tag=TAG).info(f"大模型收到用户消息: {query}")
        if depth > 0:
            print(f"DEBUG: 进入 LLM 第二轮迭代 (depth={depth})")

        if self.llm is None:
            self.logger.bind(tag=TAG).error("大模型未正确初始化，无法处理请求。")
            if hasattr(self, "tts") and self.tts:
                # 需新建 sentence_id 才能成功推入队列发声
                if getattr(self, "sentence_id", None) is None:
                    self.sentence_id = str(uuid.uuid4().hex)
                try:
                    from core.utils.device_outbound import begin_tts_turn

                    turn_sid, turn_epoch = begin_tts_turn(self, self.sentence_id)
                    self.enqueue_tts(
                        TTSMessageDTO(
                            sentence_id=turn_sid,
                            sentence_type=SentenceType.FIRST,
                            content_type=ContentType.ACTION,
                            abort_epoch=turn_epoch,
                        )
                    )
                    self.enqueue_tts(
                        TTSMessageDTO(
                            sentence_id=turn_sid,
                            sentence_type=SentenceType.MIDDLE,
                            content_type=ContentType.TEXT,
                            content_detail="抱歉，我的大脑还没准备好，请稍后再试",
                            abort_epoch=turn_epoch,
                        )
                    )
                    self.enqueue_tts(
                        TTSMessageDTO(
                            sentence_id=turn_sid,
                            sentence_type=SentenceType.LAST,
                            content_type=ContentType.ACTION,
                            abort_epoch=turn_epoch,
                        )
                    )
                except Exception as e:
                    self.logger.bind(tag=TAG).error(f"TTS队列推送失败: {e}")
            return None

        # 为最顶层时新建会话ID，初始化 TTS 管道（不插入伪造的 assistant 消息，避免与 MCP 工具调用产生连续 assistant 导致 API 报错）
        if depth == 0:
            self.llm_finish_task = False
            self.sentence_id = str(uuid.uuid4().hex)
            from core.utils.device_outbound import begin_tts_turn

            turn_sid, turn_epoch = begin_tts_turn(self, self.sentence_id)
            _tts_turn = (turn_sid, turn_epoch)
            from core.utils.person_identity import current_turn
            if not hasattr(self, "_report_actors"):
                self._report_actors = {}
            self._report_actors[(self.session_id, turn_sid, turn_epoch)] = current_turn(self)
            while len(self._report_actors) > 128:
                self._report_actors.pop(next(iter(self._report_actors)))
            user_message=Message(role="user", content=query)
            user_message.material_turn_id=current_turn(self).turn_id
            self.dialogue.put(user_message)
            if self.tts:
                self.enqueue_tts(
                    TTSMessageDTO(
                        sentence_id=turn_sid,
                        sentence_type=SentenceType.FIRST,
                        content_type=ContentType.ACTION,
                        abort_epoch=turn_epoch,
                    )
                )

        if _tts_turn is None:
            _tts_turn = (getattr(self, "sentence_id", None), None)
        turn_sid, turn_epoch = _tts_turn

        # 设置最大递归深度，避免无限循环，可根据实际需求调整
        MAX_DEPTH = 5
        force_final_answer = bool(depth > 0 and operation_enabled(self) and get_control(self).force_answer)

        if depth >= MAX_DEPTH:
            self.logger.bind(tag=TAG).debug(
                f"已达到最大工具调用深度 {MAX_DEPTH}，将强制基于现有信息回答"
            )
            force_final_answer = True
            # 添加系统指令，要求 LLM 基于现有信息回答
            self.dialogue.put(
                Message(
                    role="user",
                    content="[系统提示] 已达到最大工具调用次数限制，请你基于目前已经获取的所有信息，直接给出最终答案。不要再尝试调用任何工具。",
                )
            )

        # Define intent functions
        operation_plan = None
        if depth == 0 and operation_enabled(self):
            from core.utils.operation_control import conversation_only, content_text
            prior_users = [m for m in self.dialogue.dialogue if m.role == 'user'][:-1]
            has_recent_topic = any(not conversation_only(content_text(m.content)) for m in prior_users[-4:])
            operation_plan = get_control(self).begin(query, actor_scope(self),has_recent_topic=has_recent_topic)
        functions = None
        if depth == 0 and getattr(self,"mcp_client",None) and not self.mcp_client.ready:
            # This runs in the chat executor, so WebSocket replies can continue
            # routing while the initial catalog is being populated.
            try:
                asyncio.run_coroutine_threadsafe(self.mcp_client.wait_ready(timeout=1),self.loop).result(timeout=1.2)
            except Exception:
                pass
        # 达到最大深度时，禁用工具调用，强制 LLM 直接回答
        if (
            self.intent_type == "function_call"
            and not force_final_answer
        ):
            if getattr(self, "func_handler", None) is None:
                raise RuntimeError("function_tool_handler_not_initialized")
            functions = self.func_handler.get_functions()

        # Dispatch positively understood requests through the SAME handler as native
        # calls. Do this before model generation: no prose fallback can fake success.
        if operation_plan and (operation_plan.reply or operation_plan.requests):
            from core.utils.operation_control import execute_plan
            replies, tool_results = [], []
            if operation_plan.reply:
                replies.append(operation_plan.reply)
            elif getattr(self, "func_handler", None):
                future = asyncio.run_coroutine_threadsafe(execute_plan(self, operation_plan), self.loop)
                replies, tool_results = future.result()
            else:
                replies.append("设备操作能力尚未准备好，这次没有执行。")
            if replies:
                text = "".join(replies)
                self.dialogue.put(Message(role="assistant", content=text, caption_text=text))
                self.enqueue_tts(TTSMessageDTO(sentence_id=turn_sid, sentence_type=SentenceType.MIDDLE,
                    content_type=ContentType.TEXT, content_detail=text, abort_epoch=turn_epoch))
            if tool_results:
                self._handle_function_result(tool_results, depth=depth, _tts_turn=_tts_turn)
            self.enqueue_tts(TTSMessageDTO(sentence_id=turn_sid, sentence_type=SentenceType.LAST,
                content_type=ContentType.ACTION, abort_epoch=turn_epoch))
            self.llm_finish_task = True
            return True

        # 本地工具候选筛选（shadow 模式）：depth==0 时计算并记录候选与耗时，
        # 但实际发送给 LLM 的 functions 仍为全集，不影响工具可达性。
        if depth == 0 and functions is not None:
            try:
                if hasattr(self.func_handler, "select_candidate_functions"):
                    self.func_handler.select_candidate_functions(
                        query,
                        turn_id=getattr(self, "utterance_id", None),
                        abort_epoch=getattr(self, "listen_epoch", None),
                        mode="shadow",
                    )
            except Exception as e:
                self.logger.bind(tag=TAG).warning(f"本地工具筛选(shadow)失败: {e}")

        response_message = []

        try:
            # 使用带记忆的对话
            memory_str = None
            if self.memory is not None and not getattr(self.memory,"personal",False) and current_turn(self).eligible:
                future = asyncio.run_coroutine_threadsafe(
                    self.memory.query_memory(query), self.loop
                )
                memory_str = future.result(timeout=3)
            elif getattr(self.memory,"personal",False) and depth==0:
                future=asyncio.run_coroutine_threadsafe(self.memory.background(self),self.loop)
                try:memory_str=future.result(timeout=1)
                except Exception:memory_str=""

            from core.utils.prompt_pipeline import (
                is_pipeline_v2,
                prompt_pipeline_version,
                system_hash,
                tools_hash,
                request_kind,
            )

            is_v2 = is_pipeline_v2(self)

            # 消费本轮 ASR 情绪（一次性）：v2 进冻结快照，v1 做 system 注入
            emotion_result = None
            emotion_hint = None
            if depth == 0:
                emotion_result, emotion_hint = self._consume_speech_emotion_hint()

            # v2：冻结本轮上下文，绑定到刚 put 的 user 消息（depth>0 复用同一份）
            if is_v2 and depth == 0:
                from core.utils.turn_context import build_turn_context

                ctx = build_turn_context(self, memory_str, emotion_result)
                for m in reversed(self.dialogue.dialogue):
                    if m.role == "user" and getattr(m, "prompt_context", None) is None:
                        m.prompt_context = ctx
                        m.utterance_id = ctx.get("utterance_id") or None
                        m.listen_epoch = ctx.get("listen_epoch") or None
                        break
                trace.emit(
                    "asr.emotion_inject",
                    self,
                    {
                        "injected": True,
                        "via": "turn_context",
                        "emotion": ctx.get("emotion"),
                        "raw_emotion": ctx.get("emotion_raw"),
                        "utterance_id": ctx.get("utterance_id"),
                        "item_id": ctx.get("item_id"),
                        "listen_epoch": ctx.get("listen_epoch"),
                    },
                )

            # 构建并校验 messages（v2 的 system 为静态，不再每轮改写）
            messages = self.dialogue.get_llm_dialogue_with_memory(
                memory_str, self.config.get("voiceprint", {}), static_system=is_v2
            )
            messages = self._ensure_tool_calls_before_tool_messages(messages)
            if depth == 0 and not is_v2:
                if emotion_hint and not self._official_tts_enabled():
                    messages = list(messages)
                    insert_at = (
                        1 if messages and messages[0].get("role") == "system" else 0
                    )
                    messages.insert(insert_at, {"role": "system", "content": emotion_hint})
                    result = getattr(self, "_trace_last_emotion_result", None)
                    trace.emit(
                        "asr.emotion_inject",
                        self,
                        {
                            "injected": True,
                            "message_index": insert_at,
                            "role": "system",
                            "hint": emotion_hint,
                            "raw_emotion": (result or {}).get("raw_emotion")
                            if isinstance(result, dict)
                            else None,
                            "normalized_emotion": (result or {}).get("emotion")
                            if isinstance(result, dict)
                            else None,
                        },
                    )
                else:
                    trace.emit(
                        "asr.emotion_inject",
                        self,
                        {"injected": False, "reason": "no_hint_or_disabled"},
                    )

            if functions:
                functions = sorted(functions, key=lambda f: f.get("function", {}).get("name", ""))
            messages = self.dialogue.prepare_request(messages, functions, self.llm, self.session_id)
            trace.emit("llm.context_budget", self, {
                "estimated_tokens": self.dialogue.context_window.last_estimate,
                "input_limit_tokens": self.dialogue.context_window.limit,
                "state": self.dialogue.context_window.last_status,
                "summary_version": self.dialogue.context_window.version,
            })

            # 观测：提示词结构元信息（不写数据库、不把内部 ID 写进提示词）
            trace.emit(
                "llm.prompt_meta",
                self,
                {
                    "system_hash": system_hash(messages),
                    "tools_hash": tools_hash(functions),
                    "prompt_version": prompt_pipeline_version(self),
                    "request_kind": request_kind(depth),
                },
            )

            if depth > 0:
                # 避免无节制打印完整 system prompt（含角色/隐私上下文）
                roles = [m.get("role") for m in messages if isinstance(m, dict)]
                print(
                    f"DEBUG: 第二轮请求 messages 条数={len(messages)} roles={roles}"
                )

            token = trace.bind_conn(self)
            try:
                from core.utils.context_window import bounded_responses
                response_options = {}
                if operation_enabled(self) and get_control(self).chat_only:
                    response_options['tool_choice'] = 'none'
                llm_responses = bounded_responses(self.llm, self.session_id, messages,
                    functions if self.intent_type == "function_call" else None, self.dialogue.context_window,
                    **response_options)
            except Exception as e:
                trace.reset_conn(token)
                self.logger.bind(tag=TAG).error(f"LLM 处理出错 {query}: {e}")
                print(f"CRITICAL ERROR: LLM 第二轮请求失败: {e}")
                traceback.print_exc()
                if depth > 0:
                    self._send_fallback_voice(
                        "抱歉，我整理答案时出错了", _tts_turn=_tts_turn
                    )
                return None
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"LLM 处理出错 {query}: {e}")
            print(f"CRITICAL ERROR: LLM 第二轮请求失败: {e}")
            traceback.print_exc()
            if depth > 0:
                self._send_fallback_voice(
                    "抱歉，我整理答案时出错了", _tts_turn=_tts_turn
                )
            return None

        # 处理流式响应
        tool_call_flag = False
        # 支持多个并行工具调用 - 使用列表存储
        tool_calls_list = []  # 格式: [{"id": "", "name": "", "arguments": ""}]
        content_arguments = ""
        speech_buffer = None
        if functions is None and operation_enabled(self):
            from core.utils.operation_control import SpeechBuffer
            speech_buffer = SpeechBuffer(self)
        self.client_abort = False
        try:
            chunk_count = 0
            for response in llm_responses:
                chunk_count += 1
                if depth > 0 and chunk_count == 1:
                    print(f"DEBUG: 流式模式 - 二轮推理已收到首个 chunk，持续流式输出中...")
                if self.client_abort:
                    break
                if self.intent_type == "function_call" and functions is not None:
                    content, tools_call = response
                    if "content" in response:
                        content = response["content"]
                        tools_call = None
                    if content is not None and len(content) > 0:
                        content_arguments += content

                    if not tool_call_flag and content_arguments.startswith("<tool_call>"):
                        # print("content_arguments", content_arguments)
                        tool_call_flag = True

                    if tools_call is not None and len(tools_call) > 0:
                        tool_call_flag = True
                        self._merge_tool_calls(tool_calls_list, tools_call)
                else:
                    content = response

                if content is not None and len(content) > 0:
                    if not tool_call_flag:
                        response_message.append(content)
                        # 【关键】存在 functions 时，第一轮不推送任何内容到 TTS：若后续出现 tool_call，
                        # 补位语音会延迟发送并打断 LLM 真实答案流；仅在确认无 tool_call 后再推送
                        if functions is None and not operation_enabled(self):
                            self.enqueue_tts(
                                TTSMessageDTO(
                                    sentence_id=turn_sid,
                                    sentence_type=SentenceType.MIDDLE,
                                    content_type=ContentType.TEXT,
                                    content_detail=content,
                                    abort_epoch=turn_epoch,
                                )
                            )
                        elif speech_buffer is not None:
                            for checked_sentence in speech_buffer.feed(content):
                                self.enqueue_tts(TTSMessageDTO(sentence_id=turn_sid, sentence_type=SentenceType.MIDDLE,
                                    content_type=ContentType.TEXT, content_detail=checked_sentence, abort_epoch=turn_epoch))
        except Exception as e:
            trace.reset_conn(token)
            self.logger.bind(tag=TAG).error(f"LLM 流式响应迭代出错: {e}")
            print(f"CRITICAL ERROR: LLM 第二轮请求失败: {e}")
            traceback.print_exc()
            if depth > 0:
                self._send_fallback_voice(
                    "抱歉，我整理答案时出错了", _tts_turn=_tts_turn
                )
            return None

        # 处理function call
        if tool_call_flag:
            bHasError = False
            # 处理基于文本的工具调用格式
            if len(tool_calls_list) == 0 and content_arguments:
                # 原生 FC 严格模式：禁止正文 JSON / <tool_call> 提取执行
                try:
                    from core.providers.tools.native_fc_guard import (
                        should_reject_text_tool_call,
                    )

                    reject_text_fc = should_reject_text_tool_call(self)
                except Exception:
                    reject_text_fc = False
                if reject_text_fc:
                    bHasError = True
                    self.logger.bind(tag=TAG).warning(
                        "native_fc_only: 忽略正文假 tool_call，不执行、不自动补问"
                    )
                    response_message.clear()
                    response_message.append("这次没有发出有效的工具调用，操作没有执行。")
                    tool_call_flag = False
                else:
                    a = extract_json_from_string(content_arguments)
                    if a is not None:
                        try:
                            content_arguments_json = json.loads(a)
                            tool_calls_list.append(
                                {
                                    "id": str(uuid.uuid4().hex),
                                    "name": content_arguments_json["name"],
                                    "arguments": json.dumps(
                                        content_arguments_json["arguments"],
                                        ensure_ascii=False,
                                    ),
                                }
                            )
                        except Exception as e:
                            bHasError = True
                            response_message.append(a)
                    else:
                        bHasError = True
                        response_message.append(content_arguments)
                if bHasError:
                    self.logger.bind(tag=TAG).error(
                        f"function call error: {content_arguments}"
                    )

            if not bHasError and len(tool_calls_list) > 0:
                # 保存补位文本，与 tool_calls 合并为单条 assistant 消息（符合 OpenAI 格式）
                preceding_content = (
                    "".join(response_message) if response_message else ""
                )
                # 显式清空 tts_MessageText，防止 xunfei/alibl/aliyun 等据此发 SentenceType.FIRST
                # 导致“正在为您...”插播语音打断 LLM 真实答案流
                self.tts_MessageText = ""
                response_message.clear()

                self.logger.bind(tag=TAG).debug(
                    f"检测到 {len(tool_calls_list)} 个工具调用"
                )

                # 收集所有工具调用的 Future
                futures_with_data = []
                for tool_call_data in tool_calls_list:
                    self.logger.bind(tag=TAG).debug(
                        f"function_name={tool_call_data['name']}, function_id={tool_call_data['id']}, function_arguments={tool_call_data['arguments']}"
                    )

                    future = asyncio.run_coroutine_threadsafe(
                        self.func_handler.handle_llm_function_call(
                            self, tool_call_data
                        ),
                        self.loop,
                    )
                    futures_with_data.append((future, tool_call_data))

                # 等待协程结束（实际等待时长为最慢的那个）
                tool_results = []
                for future, tool_call_data in futures_with_data:
                    result = future.result()
                    tool_results.append((result, tool_call_data))

                # 统一处理所有工具调用结果
                if tool_results:
                    self._handle_function_result(
                        tool_results,
                        depth=depth,
                        preceding_content=preceding_content,
                        _tts_turn=_tts_turn,
                    )

        # 存储对话内容
        if len(response_message) > 0:
            if speech_buffer is not None:
                for checked_sentence in speech_buffer.feed('',final=True):
                    self.enqueue_tts(TTSMessageDTO(sentence_id=turn_sid, sentence_type=SentenceType.MIDDLE,
                        content_type=ContentType.TEXT, content_detail=checked_sentence, abort_epoch=turn_epoch))
                response_message = speech_buffer.delivered
            text_buff = "".join(response_message)
            from core.utils.operation_control import guard_reply
            text_buff = guard_reply(self, text_buff)
            from core.utils.prompt_pipeline import is_pipeline_v2

            is_v2 = is_pipeline_v2(self)
            if self._official_tts_enabled():
                from core.providers.tts.official.compiler import caption_from

                caption = caption_from(text_buff)
            else:
                caption = text_buff

            # D1 三种文本分离：
            #   content（模型视图）：v2 为带标签原始输出，冻结不改；v1 保持字幕文本
            #   caption_text（字幕/上报/长期记忆来源）：caption_from 结果
            #   TTS 文本：由编译器校验后的合成文本，这里不落库
            if is_v2 and self._official_tts_enabled():
                history_text = text_buff
            else:
                history_text = caption
            self.tts_MessageText = caption

            # 主模型定稿直接进入 TTS，不再调用第二次模型改写。
            self.dialogue.put(
                Message(role="assistant", content=history_text, caption_text=caption)
            )
            if speech_buffer is None and (functions is not None or operation_enabled(self)) and not tool_call_flag:
                self.enqueue_tts(
                    TTSMessageDTO(
                        sentence_id=turn_sid,
                        sentence_type=SentenceType.MIDDLE,
                        content_type=ContentType.TEXT,
                        content_detail=text_buff,
                        abort_epoch=turn_epoch,
                    )
                )
        if depth == 0:
            self.enqueue_tts(
                TTSMessageDTO(
                    sentence_id=turn_sid,
                    sentence_type=SentenceType.LAST,
                    content_type=ContentType.ACTION,
                    abort_epoch=turn_epoch,
                )
            )
            self.llm_finish_task = True
            # 使用lambda延迟计算，只有在DEBUG级别时才执行get_llm_dialogue()
            self.logger.bind(tag=TAG).debug(
                lambda: json.dumps(
                    self.dialogue.get_llm_dialogue(), indent=4, ensure_ascii=False
                )
            )

        trace.reset_conn(token)
        return True

    def _handle_function_result(self, tool_results, depth, preceding_content="", _tts_turn=None):
        need_llm_tools = []

        for result, tool_call_data in tool_results:
            from core.utils.tool_fact_reply import verified_tool_reply
            from core.utils.operation_control import enabled as operation_enabled, get_control
            fact_reply = (verified_tool_reply(result, tool_call_data)
                          if operation_enabled(self) and not get_control(self).force_answer else None)
            if fact_reply is not None:
                # Keep the actual receipt paired with its call for later context.
                # The spoken answer uses the receipt directly, without another LLM.
                call_id = tool_call_data.get("id") or str(uuid.uuid4())
                tool_call_data["id"] = call_id
                arguments = tool_call_data.get("arguments") or "{}"
                if not isinstance(arguments, str):
                    arguments = json.dumps(arguments, ensure_ascii=False)
                self.dialogue.put(Message(role="assistant", content=None, tool_calls=[{
                    "id": call_id, "type": "function", "function": {
                        "name": tool_call_data["name"], "arguments": arguments}}]))
                raw_result = result.result
                if not isinstance(raw_result, (str, list)):
                    raw_result = json.dumps(raw_result, ensure_ascii=False)
                self.dialogue.put(Message(role="tool", tool_call_id=call_id, content=raw_result))
                if _tts_turn:
                    self.enqueue_tts(TTSMessageDTO(sentence_id=_tts_turn[0], sentence_type=SentenceType.MIDDLE,
                        content_type=ContentType.TEXT, content_detail=fact_reply, abort_epoch=_tts_turn[1]))
                else:
                    from core.handle.sendAudioHandle import speak_text_with_subtitle
                    speak_text_with_subtitle(self, fact_reply)
                self.dialogue.put(Message(role="assistant", content=fact_reply, caption_text=fact_reply))
                continue
            if result.action in [
                Action.RESPONSE,
                Action.NOTFOUND,
                Action.ERROR,
            ]:  # 直接回复前端
                text = result.response if result.response else result.result
                from core.handle.sendAudioHandle import speak_text_with_subtitle

                from core.utils.operation_control import enabled as operation_enabled
                if operation_enabled(self) and _tts_turn:
                    self.enqueue_tts(TTSMessageDTO(sentence_id=_tts_turn[0], sentence_type=SentenceType.MIDDLE,
                        content_type=ContentType.TEXT, content_detail=text, abort_epoch=_tts_turn[1]))
                else:
                    speak_text_with_subtitle(
                        self, text,
                        sentence_id=_tts_turn[0] if _tts_turn else None,
                        abort_epoch=_tts_turn[1] if _tts_turn else None,
                    )
                self.dialogue.put(Message(role="assistant", content=text))
            elif result.action == Action.REQLLM:
                # 收集需要 LLM 处理的工具
                need_llm_tools.append((result, tool_call_data))
            else:
                pass

        if need_llm_tools:
            # 确保 tool_call_id 有效，空值时生成并回填以便 tool 消息能正确匹配
            for _, tc in need_llm_tools:
                if not tc.get("id"):
                    tc["id"] = str(uuid.uuid4())
            all_tool_calls = [
                {
                    "id": tool_call_data["id"],
                    "function": {
                        "arguments": (
                            "{}"
                            if tool_call_data["arguments"] == ""
                            else tool_call_data["arguments"]
                        ),
                        "name": tool_call_data["name"],
                    },
                    "type": "function",
                    "index": idx,
                }
                for idx, (_, tool_call_data) in enumerate(need_llm_tools)
            ]
            # 合并补位文本与 tool_calls 为单条 assistant 消息（符合 OpenAI 格式）
            self.dialogue.put(
                Message(
                    role="assistant",
                    content=preceding_content if preceding_content else None,
                    tool_calls=all_tool_calls,
                )
            )

            for result, tool_call_data in need_llm_tools:
                text = result.result
                if text is not None and len(text) > 0:
                    self.dialogue.put(
                        Message(
                            role="tool",
                            tool_call_id=tool_call_data["id"],
                            content=text,
                        )
                    )

            print(f"DEBUG: 正在将工具结果喂回给LLM进行最终回答...")
            print(f"DEBUG: 流式模式 - 工具执行完毕，正在通过 Stream 发起二轮推理...")
            self.chat(None, depth=depth + 1, _tts_turn=_tts_turn)

    def _report_worker(self):
        """聊天记录上报工作线程"""
        while not self.stop_event.is_set():
            try:
                # 从队列获取数据，设置超时以便定期检查停止事件
                item = self.report_queue.get(timeout=1)
                if item is None:  # 检测毒丸对象
                    break
                try:
                    # 检查线程池状态
                    if self.executor is None:
                        continue
                    # 提交任务到线程池
                    self.executor.submit(self._process_report, *item)
                except Exception as e:
                    self.logger.bind(tag=TAG).error(f"聊天记录上报线程异常: {e}")
            except queue.Empty:
                continue
            except Exception as e:
                self.logger.bind(tag=TAG).error(f"聊天记录上报工作线程异常: {e}")

        self.logger.bind(tag=TAG).info("聊天记录上报线程已退出")

    def _process_report(self, type, text, audio_data, report_time, metadata=None):
        """处理上报任务"""
        try:
            # 执行上报（传入二进制数据）
            report(self, type, text, audio_data, report_time, metadata)
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"上报处理异常: {e}")
        finally:
            # 标记任务完成
            self.report_queue.task_done()

    def clearSpeakStatus(self):
        self.client_is_speaking = False
        self.logger.bind(tag=TAG).debug(f"清除服务端讲话状态")

    def has_pending_mcp_calls(self) -> bool:
        """是否有尚未返回 result 的设备端 MCP 工具调用"""
        mcp_client = getattr(self, "mcp_client", None)
        return bool(mcp_client and getattr(mcp_client, "call_results", None))

    async def close(self, ws=None):
        """资源清理方法"""
        try:
            # 连接结束后必须清除短期身份，重连不能继承任何人脸或声纹结果。
            self.current_present_user = None
            self.current_present_user_seen_at = 0.0
            self.current_speaker_user = None
            self.current_speaker = None
            # MCP 工具调用执行窗口内不得释放连接：等待 result 返回（最长10秒）
            if self.has_pending_mcp_calls():
                self.logger.bind(tag=TAG).warning(
                    f"[WebSocket close延迟] device_id={self.device_id} session_id={self.session_id} "
                    f"存在未完成的MCP工具调用，延迟关闭连接等待result"
                )
                for _ in range(20):
                    await asyncio.sleep(0.5)
                    if not self.has_pending_mcp_calls():
                        break

            # End async workers before tearing down the websocket and executor.
            if getattr(self, 'mcp_client', None):
                await self.mcp_client.close()
            if getattr(self, 'asr', None) and callable(getattr(self.asr, 'close', None)):
                try:
                    await self.asr.close()
                except Exception as exc:
                    self.logger.bind(tag=TAG).warning(f'ASR close failed: {type(exc).__name__}')
            for task_name in ('vad_resume_task', '_face_enrollment_monitor'):
                task = getattr(self, task_name, None)
                if task and task is not asyncio.current_task() and not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
            log_audio_stats(self, 'connection_close')
            trace.emit(
                "device.disconnect",
                self,
                {
                    "reason": "server_close",
                    "listen_epoch": getattr(self, "listen_epoch", None),
                    "ingress_stats": dict(getattr(self, "_audio_ingress_stats", {}) or {}),
                    "connection_duration_ms": round(
                        (time.monotonic() - (getattr(self, "_trace_marks", {}) or {}).get("connect", time.monotonic()))
                        * 1000,
                        3,
                    )
                    if getattr(self, "_trace_marks", None)
                    else "unknown",
                    "audio_duration_note": "connection_duration_is_not_audio_duration",
                },
            )

            # 句级终态兜底：若句子已开始但尚未终结（未收到 stop），输出 missing_stop_observed
            self._finalize_tts_sentence("missing_stop_observed")

            self.logger.bind(tag=TAG).info(
                f"[WebSocket close] device_id={self.device_id} session_id={self.session_id} "
                f"initiator=server reason=服务端主动清理连接 "
                f"category={self._classify_close()} "
                f"{self._frame_stats_fields()} "
                f"last_frame_age_ms={self._last_frame_age_ms()} "
                f"{self._listen_stats_fields()} "
                f"{self._preinit_drop_field()}"
            )

            # 清理音频缓冲区
            if hasattr(self, "audio_buffer"):
                self.audio_buffer.clear()

            # 取消超时任务
            if self.timeout_task and self.timeout_task is not asyncio.current_task() and not self.timeout_task.done():
                self.timeout_task.cancel()
                try:
                    await self.timeout_task
                except asyncio.CancelledError:
                    pass
                self.timeout_task = None

            # 清理工具处理器资源
            if hasattr(self, "func_handler") and self.func_handler:
                try:
                    await self.func_handler.cleanup()
                except Exception as cleanup_error:
                    self.logger.bind(tag=TAG).error(
                        f"清理工具处理器时出错: {cleanup_error}"
                    )

            # 触发停止事件
            if self.stop_event:
                self.stop_event.set()

            # 清空任务队列
            self.clear_queues()

            # 关闭WebSocket连接
            try:
                if ws:
                    # 安全地检查WebSocket状态并关闭
                    try:
                        if hasattr(ws, "closed") and not ws.closed:
                            await ws.close()
                        elif hasattr(ws, "state") and ws.state.name != "CLOSED":
                            await ws.close()
                        else:
                            # 如果没有closed属性，直接尝试关闭
                            await ws.close()
                    except Exception:
                        # 如果关闭失败，忽略错误
                        pass
                elif self.websocket:
                    try:
                        if (
                            hasattr(self.websocket, "closed")
                            and not self.websocket.closed
                        ):
                            await self.websocket.close()
                        elif (
                            hasattr(self.websocket, "state")
                            and self.websocket.state.name != "CLOSED"
                        ):
                            await self.websocket.close()
                        else:
                            # 如果没有closed属性，直接尝试关闭
                            await self.websocket.close()
                    except Exception:
                        # 如果关闭失败，忽略错误
                        pass
            except Exception as ws_error:
                self.logger.bind(tag=TAG).error(f"关闭WebSocket连接时出错: {ws_error}")

            if self.tts:
                await self.tts.close()

            # 最后关闭线程池（避免阻塞）
            if self.executor:
                try:
                    self.executor.shutdown(wait=False)
                except Exception as executor_error:
                    self.logger.bind(tag=TAG).error(
                        f"关闭线程池时出错: {executor_error}"
                    )
                self.executor = None

            self.logger.bind(tag=TAG).info("连接资源已释放")
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"关闭连接时出错: {e}")
        finally:
            # 确保停止事件被设置
            if self.stop_event:
                self.stop_event.set()

    def clear_queues(self):
        """清空所有任务队列"""
        dropped = {"tts_text": 0, "tts_audio": 0, "report": 0}
        if self.tts:
            self.logger.bind(tag=TAG).debug(
                f"开始清理: TTS队列大小={self.tts.tts_text_queue.qsize()}, 音频队列大小={self.tts.tts_audio_queue.qsize()}"
            )

            # 使用非阻塞方式清空队列
            queues = [
                ("tts_text", self.tts.tts_text_queue),
                ("tts_audio", self.tts.tts_audio_queue),
                ("report", self.report_queue),
            ]
            for name, q in queues:
                if not q:
                    continue
                while True:
                    try:
                        q.get_nowait()
                        dropped[name] = dropped.get(name, 0) + 1
                    except queue.Empty:
                        break

            self.logger.bind(tag=TAG).debug(
                f"清理结束: TTS队列大小={self.tts.tts_text_queue.qsize()}, 音频队列大小={self.tts.tts_audio_queue.qsize()}"
            )
        trace.emit(
            "tts.discard_old_audio",
            self,
            {
                "dropped": dropped,
                "dropped_total": sum(dropped.values()),
                "note": "counts queued items discarded; not device playback confirmation",
            },
        )

    def reset_vad_states(self, utterance_id=None):
        from core.utils.utterance_state import finish_utterance

        finish_utterance(self, utterance_id)
        self.logger.bind(tag=TAG).debug("VAD states reset.")

    def chat_and_close(self, text):
        """Chat with the user and then close the connection"""
        try:
            # Use the existing chat method
            self.chat(text)

            # After chat is complete, close the connection
            self.close_after_chat = True
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"Chat and close error: {str(e)}")

    async def _check_timeout(self):
        """检查连接超时"""
        try:
            while not self.stop_event.is_set():
                last_activity_time = self.last_activity_time
                if self.need_bind:
                    last_activity_time = self.first_activity_time

                # 检查是否超时（只有在时间戳已初始化的情况下）
                if last_activity_time > 0.0:
                    current_time = time.time() * 1000
                    if current_time - last_activity_time > self.timeout_seconds * 1000:
                        if not self.stop_event.is_set():
                            self.logger.bind(tag=TAG).info("连接超时，准备关闭")
                            # 设置停止事件，防止重复处理
                            self.stop_event.set()
                            # 使用 try-except 包装关闭操作，确保不会因为异常而阻塞
                            try:
                                await self.close(self.websocket)
                            except Exception as close_error:
                                self.logger.bind(tag=TAG).error(
                                    f"超时关闭连接时出错: {close_error}"
                                )
                        break
                # 每10秒检查一次，避免过于频繁
                await asyncio.sleep(10)
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"超时检查任务出错: {e}")
        finally:
            self.logger.bind(tag=TAG).info("超时检查任务已退出")

    def _ensure_tool_calls_before_tool_messages(self, messages: list) -> list:
        """
        确保每条 tool 消息的上一条必须是 assistant 且包含 tool_calls（或是另一条 tool）。
        若缺失则补全虚拟 AssistantMessage，避免 LLM 厂商报 400。
        """
        result = []
        for i, msg in enumerate(messages):
            if isinstance(msg, dict) and msg.get("role") == "tool":
                prev = result[-1] if result else None
                prev_is_assistant_with_tools = (
                    prev
                    and prev.get("role") == "assistant"
                    and prev.get("tool_calls")
                )
                prev_is_tool = prev and prev.get("role") == "tool"
                if not (prev_is_assistant_with_tools or prev_is_tool):
                    self.logger.bind(tag=TAG).warning(
                        "发现 tool 消息前缺失 assistant+tool_calls，补全虚拟消息"
                    )
                    tid = msg.get("tool_call_id", str(uuid.uuid4()))
                    result.append(
                        {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": tid,
                                    "type": "function",
                                    "function": {"name": "unknown", "arguments": "{}"},
                                }
                            ],
                        }
                    )
            result.append(msg)
        return result

    def _official_tts_enabled(self):
        tts = getattr(self, "tts", None)
        checker = getattr(tts, "_official_on", None)
        if callable(checker):
            return bool(checker())
        return bool(getattr(tts, "official_enhanced", False))


    def _send_fallback_voice(self, text: str, _tts_turn=None):
        """发送兜底语音，确保对话有结束反馈"""
        turn_sid = _tts_turn[0] if _tts_turn else getattr(self, "sentence_id", None)
        turn_epoch = _tts_turn[1] if _tts_turn else None
        if self.tts:
            self.enqueue_tts(
                TTSMessageDTO(
                    sentence_id=turn_sid,
                    sentence_type=SentenceType.FIRST,
                    content_type=ContentType.ACTION,
                    abort_epoch=turn_epoch,
                )
            )
            self.enqueue_tts(
                TTSMessageDTO(
                    sentence_id=turn_sid,
                    sentence_type=SentenceType.MIDDLE,
                    content_type=ContentType.TEXT,
                    content_detail=text,
                    abort_epoch=turn_epoch,
                )
            )
            self.enqueue_tts(
                TTSMessageDTO(
                    sentence_id=turn_sid,
                    sentence_type=SentenceType.LAST,
                    content_type=ContentType.ACTION,
                    abort_epoch=turn_epoch,
                )
            )
        self.dialogue.put(Message(role="assistant", content=text))

    def _merge_tool_calls(self, tool_calls_list, tools_call):
        """合并工具调用列表

        Args:
            tool_calls_list: 已收集的工具调用列表
            tools_call: 新的工具调用
        """
        for tool_call in tools_call:
            tool_index = getattr(tool_call, "index", None)
            if tool_index is None:
                if tool_call.function.name:
                    # 有 function_name，说明是新的工具调用
                    tool_index = len(tool_calls_list)
                else:
                    tool_index = len(tool_calls_list) - 1 if tool_calls_list else 0

            # 确保列表有足够的位置
            if tool_index >= len(tool_calls_list):
                tool_calls_list.append({"id": "", "name": "", "arguments": ""})

            # 更新工具调用信息
            if tool_call.id:
                tool_calls_list[tool_index]["id"] = tool_call.id
            if tool_call.function.name:
                tool_calls_list[tool_index]["name"] = tool_call.function.name
            if tool_call.function.arguments:
                tool_calls_list[tool_index]["arguments"] += tool_call.function.arguments
