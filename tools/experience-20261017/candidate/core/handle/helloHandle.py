import time
import json
import random
import asyncio
from core.utils.dialogue import Message
from core.utils.util import audio_to_data
from core.providers.tts.dto.dto import SentenceType
from core.utils.wakeup_word import WakeupWordsConfig
from core.handle.sendAudioHandle import sendAudioMessage, send_tts_message
from core.utils.util import remove_punctuation_and_length, opus_datas_to_wav_bytes
from core.providers.tools.device_mcp import (
    MCPClient,
    send_mcp_initialize_message,
    send_mcp_tools_list_request,
)
from core.utils import trace_log as trace

TAG = __name__

WAKEUP_CONFIG = {
    "refresh_time": 10,
    "responses": [
        "我一直都在呢，您请说。",
        "在的呢，请随时吩咐我。",
        "来啦来啦，请告诉我吧。",
        "您请说，我正听着。",
        "请您讲话，我准备好了。",
        "请您说出指令吧。",
        "我认真听着呢，请讲。",
        "请问您需要什么帮助？",
        "我在这里，等候您的指令。",
    ],
}

# 创建全局的唤醒词配置管理器
wakeup_words_config = WakeupWordsConfig()

# 用于防止并发调用wakeupWordsResponse的锁
_wakeup_response_lock = asyncio.Lock()


async def handleHelloMessage(conn, msg_json):
    """处理hello消息

    协议版本必须由本连接的 hello 确定：优先 hello.version，其次本连接的
    protocol-version 请求头；两者皆无或非法时显式拒绝，禁止默认降级到 v1。
    """
    conn.hello_received = True

    version = msg_json.get("version")
    source = "hello"
    if version is None and conn.headers:
        version = conn.headers.get("protocol-version") or conn.headers.get(
            "Protocol-Version"
        )
        source = "websocket-header"
    if version is None or not conn._set_protocol_version(version, source=source):
        await conn._reject_protocol(
            "hello_missing_or_invalid_version", close_code=1002
        )
        return

    audio_params = msg_json.get("audio_params")
    if audio_params:
        format = audio_params.get("format")
        conn.logger.bind(tag=TAG).debug(f"客户端音频格式: {format}")
        conn.audio_format = format
        conn.welcome_msg["audio_params"] = audio_params
        frame_duration = audio_params.get("frame_duration")
        try:
            frame_ms = float(frame_duration)
        except (TypeError, ValueError):
            frame_ms = None
        if frame_ms is not None and 10.0 <= frame_ms <= 120.0:
            conn.audio_frame_duration_ms = frame_ms
    features = msg_json.get("features")
    if features:
        conn.logger.bind(tag=TAG).debug(f"客户端特性: {features}")
        conn.features = features
        if features.get("mcp"):
            conn.logger.bind(tag=TAG).debug("客户端支持MCP")
            # 每个新会话强制创建全新 MCPClient，工具列表按
            # (device_id, firmware_version, session_id) 隔离，不复用旧会话缓存
            firmware_version = ""
            if conn.headers:
                firmware_version = (
                    conn.headers.get("client-version")
                    or conn.headers.get("firmware-version")
                    or ""
                )
            conn.mcp_client = MCPClient(
                device_id=conn.device_id or "",
                firmware_version=firmware_version,
                session_id=conn.session_id,
            )
            conn.logger.bind(tag=TAG).info(
                f"[MCP会话] 新建工具白名单缓存: {conn.mcp_client.cache_key}"
            )
            from core.utils.device_outbound import track_outbound_task

            # 发送初始化 / tools 列表（登记任务，superseded 时可取消）


    trace.mark(conn, "hello")
    audio_params = audio_params or {}
    trace.emit(
        "device.hello",
        conn,
        {
            "message": msg_json,
            "audio_format": getattr(conn, "audio_format", None),
            "sample_rate": audio_params.get("sample_rate", "unknown"),
            "channels": audio_params.get("channels", "unknown"),
            "frame_duration": audio_params.get("frame_duration", "unknown"),
            "protocol_version": getattr(conn, "protocol_version", None),
        },
    )

    # hello 回复必须在本连接已注册为 current 之后；superseded 时 fail closed
    from core.utils.device_outbound import guarded_ws_send

    hello_sent=await guarded_ws_send(
        conn,
        json.dumps(conn.welcome_msg),
        command="hello",
        msg_type="hello",
    )
    if hello_sent and features and features.get('mcp'):
        track_outbound_task(conn,asyncio.create_task(send_mcp_initialize_message(conn)))
        # The initialize builder can await credentials. Catalog discovery must
        # begin from its matching response, not race a second outbound task.


async def checkWakeupWords(conn, text):
    enable_wakeup_words_response_cache = conn.config[
        "enable_wakeup_words_response_cache"
    ]

    # 等待tts初始化，最多等待3秒
    start_time = time.time()
    while time.time() - start_time < 3:
        if conn.tts:
            break
        await asyncio.sleep(0.1)
    else:
        return False

    if not enable_wakeup_words_response_cache:
        return False

    _, filtered_text = remove_punctuation_and_length(text)
    if filtered_text not in conn.config.get("wakeup_words"):
        return False

    conn.just_woken_up = True
    # tts.start 由 sendAudioMessage 在 FIRST 时统一发送，避免重复 start

    # 获取当前音色
    voice = getattr(conn.tts, "voice", "default")
    if not voice:
        voice = "default"

    # 获取唤醒词回复配置
    response = wakeup_words_config.get_wakeup_response(voice)
    if not response or not response.get("file_path"):
        response = {
            "voice": "default",
            "file_path": "config/assets/wakeup_words_short.wav",
            "time": 0,
            "text": "我在这里哦！",
        }

    # 获取音频数据
    opus_packets = audio_to_data(response.get("file_path"))
    # 播放唤醒词回复
    conn.client_abort = False

    conn.logger.bind(tag=TAG).info(f"播放唤醒词回复: {response.get('text')}")
    await sendAudioMessage(conn, SentenceType.FIRST, opus_packets, response.get("text"))
    await sendAudioMessage(conn, SentenceType.LAST, [], None)

    # 唤醒语音仅播放，不写入对话历史，避免后续 MCP 工具调用时产生连续 assistant 消息导致 API 报错

    # 检查是否需要更新唤醒词回复
    if time.time() - response.get("time", 0) > WAKEUP_CONFIG["refresh_time"]:
        if not _wakeup_response_lock.locked():
            asyncio.create_task(wakeupWordsResponse(conn))
    return True


async def wakeupWordsResponse(conn):
    if not conn.tts:
        return

    try:
        # 尝试获取锁，如果获取不到就返回
        if not await _wakeup_response_lock.acquire():
            return

        # 从预定义回复列表中随机选择一个回复
        result = random.choice(WAKEUP_CONFIG["responses"])
        if not result or len(result) == 0:
            return

        # 生成TTS音频
        tts_result = await asyncio.to_thread(conn.tts.to_tts, result)
        if not tts_result:
            return

        # 获取当前音色
        voice = getattr(conn.tts, "voice", "default")

        wav_bytes = opus_datas_to_wav_bytes(tts_result, sample_rate=16000)
        file_path = wakeup_words_config.generate_file_path(voice)
        with open(file_path, "wb") as f:
            f.write(wav_bytes)
        # 更新配置
        wakeup_words_config.update_wakeup_response(voice, file_path, result)
    finally:
        # 确保在任何情况下都释放锁
        if _wakeup_response_lock.locked():
            _wakeup_response_lock.release()
