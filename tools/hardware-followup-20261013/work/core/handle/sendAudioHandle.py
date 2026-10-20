from core.utils.tts_stream import owned_send, stream_valid, stream_context
import json
import time
import uuid
import asyncio
from core.utils import textUtils
from core.utils.util import audio_to_data
from core.providers.tts.dto.dto import SentenceType, TTSMessageDTO, ContentType
from core.utils.device_outbound import guarded_ws_send, is_outbound_allowed, enqueue_tts
from core.utils import trace_log as trace
from core.utils.tts_listen_observe import (
    note_tts_audio_sent as note_tts_outbound_audio,
    note_tts_start_sent,
    note_tts_stop_sent,
)

TAG = __name__

# 帧间间隙告警阈值（毫秒）：仅观测，不注入伪音频/静音帧
_TTS_GAP_WARN_MS = 500
_TTS_WS_SEND_WARN_MS = 200


async def _device_send(conn, data, *, command="audio", msg_type="binary") -> tuple:
    """设备下行唯一入口（音频/JSON 状态）。

    Returns:
        (ok, ws_send_ms) — ws_send_ms 为实际 await send 耗时；失败时为 None。
    """
    if not stream_valid(conn, stream_context.get()):
        return False, None
    t0 = time.perf_counter()
    ok = await guarded_ws_send(conn, data, command=command, msg_type=msg_type)
    ws_ms = (time.perf_counter() - t0) * 1000.0
    return bool(ok), ws_ms


def _note_tts_sentence_started(conn):
    """发送侧 FIRST 边界：标记新句子开始（供句级遥测区分 epoch）。"""
    telemetry = getattr(conn, "tts_sentence_telemetry", None)
    if telemetry is None:
        return
    telemetry.note_sentence_started(getattr(conn, "sentence_id", None))


def _note_tts_audio_sent(conn, payload_bytes, *, ws_send_ms=None):
    """在成功完成 ``await websocket.send(...)`` 之后调用，仅计数，不打印正文。"""
    telemetry = getattr(conn, "tts_sentence_telemetry", None)
    if telemetry is not None:
        telemetry.note_audio_sent(
            getattr(conn, "sentence_id", None),
            payload_bytes,
            ws_send_ms=ws_send_ms,
        )
    note_tts_outbound_audio(conn, ws_send_ms=ws_send_ms)
    prev_max = int(getattr(conn, "_tts_gap_last_warned", 0) or 0)
    cur_gap = int(getattr(conn, "tts_max_interframe_gap_ms", 0) or 0)
    if cur_gap >= _TTS_GAP_WARN_MS and cur_gap > prev_max:
        conn._tts_gap_last_warned = cur_gap
        conn.logger.bind(tag=TAG).info(
            f"[tts_gap] {conn._cid()} max_interframe_gap_ms={cur_gap} "
            f"last_ws_send_ms={getattr(conn, 'tts_last_ws_send_ms', None)} "
            f"max_ws_send_ms={getattr(conn, 'tts_max_ws_send_ms', None)} "
            f"note=server_send_gap_not_device_play;layers=synth_or_queue_or_ws"
        )
    if ws_send_ms is not None and float(ws_send_ms) >= _TTS_WS_SEND_WARN_MS:
        conn.logger.bind(tag=TAG).info(
            f"[tts_ws_send_slow] {conn._cid()} ws_send_ms={round(float(ws_send_ms), 1)} "
            f"payload_bytes={payload_bytes}"
        )


def _finalize_tts_sentence(conn, default_reason="normal_stop"):
    """句级终态输出（仅一次）；不打印文本/音频/Token。"""
    telemetry = getattr(conn, "tts_sentence_telemetry", None)
    if telemetry is None:
        return None
    reason = (
        "session_finished"
        if telemetry.session_finished_ms is not None
        else default_reason
    )
    line = telemetry.finalize(reason, conn._mask(getattr(conn, "session_id", None)))
    if line:
        conn.logger.bind(tag=TAG).info(line)
    return line


def _build_binary_audio_packet(conn, opus_packet: bytes, timestamp: int, sequence: int) -> bytes:
    """
    根据 conn.audio_protocol_version 构建带头部的二进制音频包。
    - version 2 (BinaryProtocol2): 16 字节头，大端
    - version 3 (BinaryProtocol3): 4 字节头，大端
    - version 0 或 None: 不添加头部（由调用方直接发送 raw OPUS）
    """
    ver = getattr(conn, "audio_protocol_version", 0) or 0
    payload_size = len(opus_packet)

    if ver == 2:
        header = bytearray(16)
        header[0:2] = (2).to_bytes(2, "big")
        header[2:4] = (0).to_bytes(2, "big")
        header[4:8] = (0).to_bytes(4, "big")
        header[8:12] = timestamp.to_bytes(4, "big")
        header[12:16] = payload_size.to_bytes(4, "big")
        return bytes(header) + opus_packet
    elif ver == 3:
        header = bytearray(4)
        header[0] = 0
        header[1] = 0
        header[2:4] = min(payload_size, 0xFFFF).to_bytes(2, "big")
        return bytes(header) + opus_packet
    else:
        return opus_packet


@owned_send
async def sendAudioMessage(conn, sentenceType, audios, text):
    # 首句由 sendAudioMessage 统一发 tts.start（避免 hello 等旁路重复 start）
    # 顺序保证：同一 TTS 消化线程 future.result() 串行 → start → sentence_start → audio → stop
    if conn.tts.tts_audio_first_sentence:
        conn.logger.bind(tag=TAG).info(
            f"[tts_deliver] {conn._cid()} 发送第一段语音: {text}"
        )
        conn.tts.tts_audio_first_sentence = False
        if not getattr(conn, "_tts_start_sent", False):
            await send_tts_message(conn, "start", None)

    if sentenceType == SentenceType.FIRST:
        _note_tts_sentence_started(conn)
        await send_tts_message(conn, "sentence_start", text)

    # 本轮音频必须在 stop 之前发完；LAST 通常携带空包，仅作边界
    await sendAudio(conn, audios)
    if not stream_valid(conn, stream_context.get()):
        # 轮次已失效（abort/superseded）：不盲目补 stop，由 abort/invalidate 路径负责
        return
    if sentenceType is not SentenceType.MIDDLE:
        conn.logger.bind(tag=TAG).info(f"发送音频消息: {sentenceType}, {text}")

    if sentenceType == SentenceType.LAST:
        await send_tts_message(conn, "stop", None)
        conn.client_is_speaking = False
        _finalize_tts_sentence(conn)
        if conn.close_after_chat:
            if hasattr(conn, "has_pending_mcp_calls") and conn.has_pending_mcp_calls():
                conn.logger.bind(tag=TAG).info(
                    "TTS 结束但存在未完成的 MCP 工具调用，保持 WebSocket 连接"
                )
            await conn.close()


def calculate_timestamp_and_sequence(conn, start_time, packet_index, frame_duration=60):
    """计算音频数据包的时间戳和序列号。"""
    timestamp = int((start_time + packet_index * frame_duration / 1000) * 1000) % (
        2**32
    )
    if hasattr(conn, "audio_flow_control"):
        sequence = conn.audio_flow_control["sequence"]
    else:
        sequence = packet_index
    return timestamp, sequence


async def _send_to_mqtt_gateway(conn, opus_packet, timestamp, sequence) -> bool:
    """
    发送带16字节头部的opus数据包给mqtt_gateway
    """
    header = bytearray(16)
    header[0] = 1  # type
    header[2:4] = len(opus_packet).to_bytes(2, "big")  # payload length
    header[4:8] = sequence.to_bytes(4, "big")  # sequence
    header[8:12] = timestamp.to_bytes(4, "big")  # 时间戳
    header[12:16] = len(opus_packet).to_bytes(4, "big")  # opus长度

    complete_packet = bytes(header) + opus_packet
    ok, ws_ms = await _device_send(conn, complete_packet, command="audio", msg_type="binary")
    if not ok:
        return False
    conn.client_is_speaking = True
    _note_tts_audio_sent(conn, len(opus_packet), ws_send_ms=ws_ms)
    return True


# 播放音频
@owned_send
async def sendAudio(conn, audios, frame_duration=60, *, subtitle_exempt: bool = False):
    """
    发送单个opus包，支持流控
    Args:
        conn: 连接对象
        opus_packet: 单个opus数据包
        pre_buffer: 快速发送音频
        frame_duration: 帧时长（毫秒），匹配 Opus 编码
    """
    if audios is None or len(audios) == 0:
        return
    if not is_outbound_allowed(conn):
        return

    # 获取发送延迟配置
    send_delay = conn.config.get("tts_audio_send_delay", -1) / 1000.0

    if isinstance(audios, bytes):
        # 重置流控状态,第一次读取和会话发生转变时
        if not hasattr(conn, "audio_flow_control") or conn.audio_flow_control.get("sentence_id") != conn.sentence_id:
            conn.audio_flow_control = {
                "last_send_time": 0,
                "packet_count": 0,
                "start_time": time.perf_counter(),
                "sequence": 0,  # 添加序列号
                "sentence_id": conn.sentence_id,
            }

        if conn.client_abort:
            return

        conn.last_activity_time = time.time() * 1000

        # 预缓冲：前5个包直接发送，不做延迟
        pre_buffer_count = 5
        flow_control = conn.audio_flow_control
        current_time = time.perf_counter()
        pace_wait_ms = 0.0

        if flow_control["packet_count"] < pre_buffer_count:
            # 预缓冲阶段，直接发送不延迟
            pass
        elif send_delay > 0:
            # 使用固定延迟
            pace_wait_ms = send_delay * 1000.0
            await asyncio.sleep(send_delay)
        else:
            effective_packet = flow_control["packet_count"] - pre_buffer_count
            expected_time = flow_control["start_time"] + (
                effective_packet * frame_duration / 1000
            )
            delay = expected_time - current_time
            if delay > 0:
                pace_wait_ms = delay * 1000.0
                await asyncio.sleep(delay)
            else:
                # 纠正误差
                flow_control["start_time"] += abs(delay)

        if not is_outbound_allowed(conn) or conn.client_abort:
            return

        sent_ok = False
        if conn.conn_from_mqtt_gateway:
            timestamp, sequence = calculate_timestamp_and_sequence(
                conn,
                flow_control["start_time"],
                flow_control["packet_count"],
                frame_duration,
            )
            sent_ok = await _send_to_mqtt_gateway(conn, audios, timestamp, sequence)
        else:
            ver = getattr(conn, "audio_protocol_version", 0) or 0
            if ver in (2, 3):
                timestamp, sequence = calculate_timestamp_and_sequence(
                    conn, flow_control["start_time"], flow_control["packet_count"], frame_duration
                )
                packet = _build_binary_audio_packet(conn, audios, timestamp, sequence)
                ok, ws_ms = await _device_send(conn, packet)
                if ok:
                    conn.client_is_speaking = True
                    _note_tts_audio_sent(conn, len(audios), ws_send_ms=ws_ms)
                    sent_ok = True
            else:
                ok, ws_ms = await _device_send(conn, audios)
                if ok:
                    conn.client_is_speaking = True
                    _note_tts_audio_sent(conn, len(audios), ws_send_ms=ws_ms)
                    sent_ok = True
        if not sent_ok:
            return

        if pace_wait_ms >= _TTS_GAP_WARN_MS:
            conn.logger.bind(tag=TAG).info(
                f"[tts_gap] {conn._cid()} layer=pace_wait pace_wait_ms={round(pace_wait_ms, 1)} "
                f"note=intentional_frame_pacing"
            )

        seq = flow_control["packet_count"] + 1
        if seq == 1:
            trace.mark(conn, "tts_first_downlink")
        if seq == 1 or seq % 10 == 0:
            trace.emit(
                "tts.downlink_opus",
                conn,
                {
                    "seq": seq,
                    "opus_bytes": len(audios),
                    "protocol_version": getattr(conn, "audio_protocol_version", 0) or 0,
                    "frame_duration_ms": frame_duration,
                    "pace_wait_ms": round(pace_wait_ms, 1),
                    "ws_send_ms": getattr(conn, "tts_last_ws_send_ms", None),
                    "note": "server_send_success_not_device_play",
                    "latency_from_first_text_ms": trace.latency_ms(conn, "tts_first_text"),
                    "latency_from_first_upstream_pcm_ms": trace.latency_ms(
                        conn, "tts_first_upstream_pcm"
                    ),
                },
            )

        # 更新流控状态
        flow_control["packet_count"] += 1
        flow_control["sequence"] += 1
        flow_control["last_send_time"] = time.perf_counter()
    else:
        # 文件型音频走普通播放
        start_time = time.perf_counter()
        play_position = 0

        # 执行预缓冲
        pre_buffer_frames = min(5, len(audios))
        for i in range(pre_buffer_frames):
            if not is_outbound_allowed(conn):
                return
            if conn.conn_from_mqtt_gateway:
                timestamp, sequence = calculate_timestamp_and_sequence(
                    conn, start_time, i, frame_duration
                )
                if not await _send_to_mqtt_gateway(conn, audios[i], timestamp, sequence):
                    return
            else:
                ver = getattr(conn, "audio_protocol_version", 0) or 0
                if ver in (2, 3):
                    timestamp, sequence = calculate_timestamp_and_sequence(
                        conn, start_time, i, frame_duration
                    )
                    packet = _build_binary_audio_packet(conn, audios[i], timestamp, sequence)
                    ok, ws_ms = await _device_send(conn, packet)
                    if not ok:
                        return
                    conn.client_is_speaking = True
                    _note_tts_audio_sent(conn, len(audios[i]), ws_send_ms=ws_ms)
                else:
                    ok, ws_ms = await _device_send(conn, audios[i])
                    if not ok:
                        return
                    conn.client_is_speaking = True
                    _note_tts_audio_sent(conn, len(audios[i]), ws_send_ms=ws_ms)
        remaining_audios = audios[pre_buffer_frames:]

        # 播放剩余音频帧
        for i, opus_packet in enumerate(remaining_audios):
            if conn.client_abort or not is_outbound_allowed(conn):
                break

            # 重置没有声音的状态
            conn.last_activity_time = time.time() * 1000

            if send_delay > 0:
                await asyncio.sleep(send_delay)
            else:
                expected_time = start_time + (play_position / 1000)
                current_time = time.perf_counter()
                delay = expected_time - current_time
                if delay > 0:
                    await asyncio.sleep(delay)

            if not is_outbound_allowed(conn) or conn.client_abort:
                break

            if conn.conn_from_mqtt_gateway:
                packet_index = pre_buffer_frames + i
                timestamp, sequence = calculate_timestamp_and_sequence(
                    conn, start_time, packet_index, frame_duration
                )
                if not await _send_to_mqtt_gateway(conn, opus_packet, timestamp, sequence):
                    break
            else:
                ver = getattr(conn, "audio_protocol_version", 0) or 0
                if ver in (2, 3):
                    packet_index = pre_buffer_frames + i
                    timestamp, sequence = calculate_timestamp_and_sequence(
                        conn, start_time, packet_index, frame_duration
                    )
                    packet = _build_binary_audio_packet(conn, opus_packet, timestamp, sequence)
                    ok, ws_ms = await _device_send(conn, packet)
                    if not ok:
                        break
                    conn.client_is_speaking = True
                    _note_tts_audio_sent(conn, len(opus_packet), ws_send_ms=ws_ms)
                else:
                    ok, ws_ms = await _device_send(conn, opus_packet)
                    if not ok:
                        break
                    conn.client_is_speaking = True
                    _note_tts_audio_sent(conn, len(opus_packet), ws_send_ms=ws_ms)

            play_position += frame_duration


@owned_send
async def send_tts_message(conn, state, text=None):
    """发送 TTS 状态消息"""
    if text is None and state == "sentence_start":
        return
    if not is_outbound_allowed(conn):
        return
    if state in ("start", "sentence_start", "stop"):
        try:
            from core.utils.reminder_audit import audit_event, conn_ids

            extra = {"tts_state": state}
            if state == "sentence_start" and text is not None:
                extra["script_len"] = len(str(text))
            audit_event(
                "tts_subtitle_event",
                **conn_ids(conn),
                result_code=state,
                prefix="[tts_audit]",
                extra=extra,
            )
        except Exception:
            pass
    if state=="sentence_start" and text:
        from core.utils.device_speech_origin import note_device_speech
        note_device_speech(conn,text,request_id=getattr(conn,"sentence_id",None))
    message = {"type": "tts", "state": state, "session_id": conn.session_id}
    from core.utils.tts_stream import current_stream
    owner = stream_context.get() or current_stream(conn)
    if owner[1]:
        message["request_id"] = str(owner[1])
        message["abort_epoch"] = int(owner[2] or 0)
    if text is not None:
        text = textUtils.strip_all_emotion_tags(text)  # Loona 情绪标签清洗
        message["text"] = textUtils.check_emoji(text)

    # TTS播放结束：先发完可选提示音，再发 stop；stop 表示服务端发送完毕，非设备播完
    if state == "stop":
        trace.emit(
            "tts.stop_sent",
            conn,
            {
                "state": state,
                "note": "server dispatched tts stop; not confirmed device playback end",
            },
        )
        tts_notify = conn.config.get("enable_stop_tts_notify", False)
        if tts_notify:
            stop_tts_notify_voice = conn.config.get(
                "stop_tts_notify_voice", "config/assets/tts_notify.mp3"
            )
            conn.logger.bind(tag=TAG).info(
                f"[tts_subtitle] subtitle_exempt=1 reason=stop_tts_notify session_id={getattr(conn, 'session_id', '')}"
            )
            # audio_to_data 为同步解码；仅在配置开启时走此路径，避免默认阻塞事件循环
            audios = await asyncio.to_thread(
                audio_to_data, stop_tts_notify_voice, True
            )
            await sendAudio(conn, audios, subtitle_exempt=True)
        if not stream_valid(conn, stream_context.get()):
            return
        conn.clearSpeakStatus()

    # 发送消息到客户端（start/stop 在成功发送后更新观测态）
    ok, _ws_ms = await _device_send(
        conn, json.dumps(message), command="tts", msg_type="tts"
    )
    if not ok:
        if state == "stop":
            # 本地已 clearSpeakStatus；发送失败也结束本轮发送态，避免污染下一轮
            note_tts_stop_sent(conn)
        return
    if state == "start":
        note_tts_start_sent(conn)
    elif state == "stop":
        note_tts_stop_sent(conn)
        telemetry = getattr(conn, "tts_sentence_telemetry", None)
        if telemetry is not None:
            telemetry.note_stop_dispatched(getattr(conn, "sentence_id", None))



def speak_text_with_subtitle(conn, text: str, audio_packets=None, *, subtitle_exempt: bool = False, sentence_id=None, abort_epoch=None):
    """统一 TTS 出站：保证 tts.start → sentence_start → audio → tts.stop 时序。"""
    if subtitle_exempt:
        conn.logger.bind(tag=TAG).info(
            f"[tts_subtitle] subtitle_exempt=1 reason=explicit session_id={getattr(conn, 'session_id', '')}"
        )
        if audio_packets:
            conn.tts.tts_audio_queue.put((SentenceType.LAST, audio_packets, None))
        return True
    if not text or not str(text).strip():
        return False
    text = str(text).strip()
    from core.utils.device_outbound import begin_tts_turn

    sid = sentence_id if sentence_id is not None else getattr(conn, "sentence_id", None)
    current_epoch = int(getattr(conn, "tts_abort_epoch", 0) or 0)
    mapping = getattr(conn, "tts_sentence_epochs", None) or {}
    if abort_epoch is None:
        if sid and sid in mapping and int(mapping[sid]) != current_epoch:
            sid = uuid.uuid4().hex
            conn.sentence_id = sid
        sid, abort_epoch = begin_tts_turn(conn, sid)
    else:
        sid, abort_epoch = begin_tts_turn(conn, sid, abort_epoch)
    enqueue_tts(
        conn,
        TTSMessageDTO(
            sentence_id=sid,
            sentence_type=SentenceType.FIRST,
            content_type=ContentType.ACTION,
            content_detail=text,
            session_id=getattr(conn, "session_id", None),
            abort_epoch=abort_epoch,
        ),
    )
    if audio_packets is not None:
        packets = audio_packets if isinstance(audio_packets, list) else [audio_packets]
        for pkt in packets:
            conn.tts.tts_audio_queue.put((SentenceType.MIDDLE, pkt, text))
        enqueue_tts(
            conn,
            TTSMessageDTO(
                sentence_id=sid,
                sentence_type=SentenceType.LAST,
                content_type=ContentType.ACTION,
                content_detail=text,
                session_id=getattr(conn, "session_id", None),
                abort_epoch=abort_epoch,
            ),
        )
    else:
        enqueue_tts(
            conn,
            TTSMessageDTO(
                sentence_id=sid,
                sentence_type=SentenceType.MIDDLE,
                content_type=ContentType.TEXT,
                content_detail=text,
                session_id=getattr(conn, "session_id", None),
                abort_epoch=abort_epoch,
            ),
        )
        enqueue_tts(
            conn,
            TTSMessageDTO(
                sentence_id=sid,
                sentence_type=SentenceType.LAST,
                content_type=ContentType.ACTION,
                content_detail=text,
                session_id=getattr(conn, "session_id", None),
                abort_epoch=abort_epoch,
            ),
        )
    return True


async def send_stt_message(conn, text, *, start_tts=True):
    """发送 STT 状态消息。

    start_tts=False：只回显识别文本，不打开 TTS 会话。
    人脸录入静默成功必须用这个，否则固件会进入 speaking，
    一直卡在 waiting_for_idle。
    """
    end_prompt_str = conn.config.get("end_prompt", {}).get("prompt")
    if end_prompt_str and end_prompt_str == text:
        if start_tts:
            await send_tts_message(conn, "start")
        return

    # 解析JSON格式，提取实际的用户说话内容
    display_text = text
    try:
        # 尝试解析JSON格式
        if text.strip().startswith("{") and text.strip().endswith("}"):
            parsed_data = json.loads(text)
            if isinstance(parsed_data, dict) and "content" in parsed_data:
                # 如果是包含说话人信息的JSON格式，只显示content部分
                display_text = parsed_data["content"]
                # 保存说话人信息到conn对象
                if "speaker" in parsed_data:
                    conn.current_speaker = parsed_data["speaker"]
    except (json.JSONDecodeError, TypeError):
        # 如果不是JSON格式，直接使用原始文本
        display_text = text
    stt_text = textUtils.get_string_no_punctuation_or_emoji(display_text)
    await _device_send(
        conn,
        json.dumps({"type": "stt", "text": stt_text, "session_id": conn.session_id}),
        command="stt",
        msg_type="stt",
    )
    if start_tts:
        await send_tts_message(conn, "start")
