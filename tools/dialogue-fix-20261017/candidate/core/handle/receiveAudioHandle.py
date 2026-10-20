from core.utils.audio_ingress import AudioIngress, audio_count
from core.utils.utterance_state import note_quiet_audio
import time
import json
import asyncio
from core.utils.util import audio_to_data
from core.handle.abortHandle import handleAbortMessage
from core.handle.intentHandler import handle_user_intent
from core.utils.output_counter import check_device_output_limit
from core.handle.sendAudioHandle import send_stt_message, speak_text_with_subtitle
from core.utils import trace_log as trace

TAG = __name__


def _queue_size(conn):
    try:
        return int(conn.asr_audio_queue.qsize())
    except Exception:
        return "unknown"


async def handleAudioMessage(conn, audio):
    epoch = getattr(conn, 'listen_epoch', 0)
    seq = 0
    kind = "opus"
    gap_ms = 0.0
    if isinstance(audio, AudioIngress):
        seq = int(getattr(audio, "seq", 0) or 0)
        kind = getattr(audio, "kind", "opus") or "opus"
        gap_ms = float(getattr(audio, "gap_ms", 0.0) or 0.0)
        if audio.epoch != epoch:
            audio_count(conn, 'drop_old_epoch')
            if seq:
                conn._audio_processed_seq = max(
                    int(getattr(conn, "_audio_processed_seq", 0) or 0), seq
                )
            return
        audio = audio.payload
    try:
        if kind == "dtx_gap":
            audio_count(conn, "dtx_gap_handled")
            threshold = 1000
            vad = getattr(conn, "vad", None)
            if vad is not None:
                threshold = int(getattr(vad, "silence_threshold_ms", threshold) or threshold)
            became_stop = note_quiet_audio(conn, gap_ms, threshold)
            if became_stop:
                trace.emit(
                    "vad.utterance_stop",
                    conn,
                    {
                        "stop_source": "dtx_gap",
                        "gap_ms": gap_ms,
                        "silence_threshold_ms": threshold,
                        "clock_compat": getattr(conn, "_audio_clock_compat_epoch", False),
                        "clock_policy": getattr(conn, "_audio_clock_policy", None),
                        "note": "DTX/short uplink is silence gap, not received PCM",
                    },
                )
            if getattr(conn, "client_voice_stop", False):
                await conn.asr.receive_audio(conn, b"", False)
            return
        audio_count(conn, 'dequeued_frames')
        # 当前片段是否有人说话
        have_voice = conn.vad.is_vad(conn, audio)
        audio_count(conn, 'vad_voice' if have_voice else 'vad_quiet')
        prev_have = getattr(conn, "_trace_last_have_voice", False)
        if have_voice and not prev_have:
            trace.mark(conn, "vad_start")
            trace.emit(
                "vad.start",
                conn,
                {
                    "have_voice": True,
                    "listen_mode": getattr(conn, "client_listen_mode", None),
                    "queue_size": _queue_size(conn),
                    "ingress_stats": dict(getattr(conn, "_audio_ingress_stats", {}) or {}),
                },
            )
        if getattr(conn, "client_voice_stop", False) and not getattr(conn, "_trace_vad_end_logged", False):
            conn._trace_vad_end_logged = True
            trace.mark(conn, "vad_end")
            stop_duration = None
            try:
                stop_duration = time.time() * 1000 - conn.last_activity_time
            except Exception:
                stop_duration = "unknown"
            trace.emit(
                "vad.end",
                conn,
                {
                    "have_voice": have_voice,
                    "end_reason": getattr(conn, "utterance_stop_reason", None)
                    or "silence_threshold_or_listen_stop",
                    "silence_ms": stop_duration,
                    "latency_from_vad_start_ms": trace.latency_ms(conn, "vad_start"),
                    "queue_size": _queue_size(conn),
                    "note": "duration is VAD silence wait, not connection uptime",
                },
            )
        conn._trace_last_have_voice = have_voice
        # 首次检测到有效语音时记录 ASR 开始（仅一次，不落音频内容）
        if have_voice and not getattr(conn, "_asr_start_logged", False):
            conn._asr_start_logged = True
            conn.logger.bind(tag=TAG).info(
                f"[asr_start] {conn._cid()} 检测到有效语音，开始 ASR 链路"
            )
        # 如果设备刚刚被唤醒，短暂忽略VAD检测
        if hasattr(conn, "just_woken_up") and conn.just_woken_up:
            have_voice = False
            audio_count(conn, 'drop_wakeup_window')
            # 设置一个短暂延迟后恢复VAD检测
            conn.asr_audio.clear()
            if not hasattr(conn, "vad_resume_task") or conn.vad_resume_task.done():
                conn.vad_resume_task = asyncio.create_task(resume_vad_detection(conn))
            return
        # manual 模式下不打断正在播放的内容
        if have_voice:
            if conn.client_is_speaking and conn.client_listen_mode != "manual":
                await handleAbortMessage(conn,reason='speech_activity')
        # 设备长时间空闲检测，用于say goodbye
        await no_voice_close_connect(conn, have_voice)
        # 接收音频
        if epoch != getattr(conn, 'listen_epoch', 0):
            audio_count(conn, 'drop_old_epoch')
            return
        await conn.asr.receive_audio(conn, audio, have_voice)
    finally:
        if seq:
            conn._audio_processed_seq = max(
                int(getattr(conn, "_audio_processed_seq", 0) or 0), seq
            )


async def resume_vad_detection(conn):
    epoch = getattr(conn, 'listen_epoch', 0)
    await asyncio.sleep(2)
    if epoch == getattr(conn, 'listen_epoch', 0):
        conn.just_woken_up = False


async def startToChat(conn, text):
    from core.utils.person_identity import activate, deactivate, freeze
    actor=getattr(conn,"person_turn",None)
    if actor is None:
        # Wakeup/touch text is not evidence of a voice match.
        actor=freeze(conn,{"mode":"unavailable"},status="system")
    token=activate(conn,actor)
    try:
        return await _startToChat(conn,text,actor)
    finally:
        deactivate(token)


async def _startToChat(conn,text,actor):
    # 检查输入是否是JSON格式（包含说话人信息）
    speaker_name = None
    actual_text = text

    try:
        # 尝试解析JSON格式的输入
        if text.strip().startswith("{") and text.strip().endswith("}"):
            data = json.loads(text)
            if "speaker" in data and "content" in data:
                speaker_name = data["speaker"]
                actual_text = data["content"]
                conn.logger.bind(tag=TAG).info(f"解析到说话人信息: {speaker_name}")

                # 直接使用JSON格式的文本，不解析
                actual_text = text
    except (json.JSONDecodeError, KeyError):
        # 如果解析失败，继续使用原始文本
        pass

    # 保存说话人信息到连接对象
    if speaker_name:
        conn.current_speaker = speaker_name
    else:
        conn.current_speaker = None

    # 主动到场问候：仅首行 [PROACTIVE_GREETING] 视为系统事件
    try:
        from core.utils.proactive_return import handle_proactive_return
        if await handle_proactive_return(conn, actual_text):
            return
        from core.utils.proactive_greeting import handle_proactive_greeting

        if await handle_proactive_greeting(conn, actual_text):
            return
    except Exception:
        # 解析/调度异常不得中断普通对话，也不关 WebSocket
        pass

    if conn.need_bind:
        await check_bind_device(conn)
        return

    # 如果当日的输出字数大于限定的字数
    if conn.max_output_size > 0:
        if check_device_output_limit(
            conn.headers.get("device-id"), conn.max_output_size
        ):
            await max_out_size(conn)
            return
    from core.utils.device_speech_origin import matches_device_speech
    if matches_device_speech(conn,actual_text):
        conn.logger.bind(tag=TAG).info("[speech_origin] ignored recent device-output echo; no user authorization")
        return

    # manual 模式下不打断正在播放的内容
    if conn.client_is_speaking and conn.client_listen_mode != "manual":
        await handleAbortMessage(conn,reason='speech_activity')

    # Harness owns all user operation routes, including card and face intents.
    # Do not start TTS before deciding: face enrollment uses firmware START.
    from core.utils.tool_harness import enabled as harness_enabled
    if harness_enabled(conn):
        await send_stt_message(conn, actual_text, start_tts=False)
        conn.executor.submit(conn.chat, actual_text, _identity=actor)
        return

    # 首先进行意图分析，使用实际文本内容
    try:
        from core.utils.card_action import route_card_voice_action, CardRouteResult

        card_result = await route_card_voice_action(conn, actual_text)
        if card_result.result != CardRouteResult.NOT_MATCHED:
            await send_stt_message(conn, actual_text)
            if card_result.message:
                from core.handle.intentHandler import speak_txt

                speak_txt(conn, card_result.message)
            return
    except Exception:
        pass

    # 人脸录入取消：确定性路由，不进入通用 intent / 闲聊 LLM
    try:
        from core.utils.face_enrollment_cancel_intent import (
            route_face_enroll_cancel,
            FaceEnrollCancelResult,
        )

        cancel_result = await route_face_enroll_cancel(conn, actual_text)
        if cancel_result.result != FaceEnrollCancelResult.NOT_MATCHED:
            await send_stt_message(conn, actual_text)
            if cancel_result.message:
                from core.handle.intentHandler import speak_txt

                speak_txt(conn, cancel_result.message)
            return
    except Exception:
        # 确定性路径异常也不得回退闲聊：仅记录并由上层继续时仍跳过 LLM
        try:
            from core.utils.face_enrollment_cancel_intent import match_face_enroll_cancel

            if match_face_enroll_cancel(actual_text):
                await send_stt_message(conn, actual_text)
                from core.handle.intentHandler import speak_txt

                speak_txt(conn, "取消人脸录入失败，请稍后再试。")
                return
        except Exception:
            pass

    # 人脸录入启动：确定性路由；成功静默（固件本地 START），失败才播安全短句
    try:
        from core.utils.face_enrollment_start_intent import (
            route_face_enroll_start,
            FaceEnrollStartResult,
        )

        start_result = await route_face_enroll_start(conn, actual_text)
        if start_result.result != FaceEnrollStartResult.NOT_MATCHED:
            # 成功 message 为空：不得 speak_txt，也不得 tts start。
            # 否则固件进入 speaking，录入工人一直 waiting_for_idle。
            await send_stt_message(
                conn, actual_text, start_tts=bool(start_result.message)
            )
            if start_result.message:
                from core.handle.intentHandler import speak_txt

                speak_txt(conn, start_result.message)
            return
    except Exception:
        try:
            from core.utils.face_enrollment_start_intent import match_face_enroll_start

            if match_face_enroll_start(actual_text):
                await send_stt_message(conn, actual_text)
                from core.handle.intentHandler import speak_txt

                speak_txt(conn, "开始人脸录入失败，请稍后再试。")
                return
        except Exception:
            pass

    intent_handled = await handle_user_intent(conn, actual_text)

    if intent_handled:
        # 如果意图已被处理，不再进行聊天
        return

    # 意图未被处理，继续常规聊天流程，使用实际文本内容
    await send_stt_message(conn, actual_text)
    conn.executor.submit(conn.chat, actual_text, _identity=actor)


async def no_voice_close_connect(conn, have_voice):
    from core.utils.reminder_interaction import is_interaction_active

    if is_interaction_active(conn):
        return
    if have_voice:
        conn.last_activity_time = time.time() * 1000
        return
    # 只有在已经初始化过时间戳的情况下才进行超时检查
    if conn.last_activity_time > 0.0:
        no_voice_time = time.time() * 1000 - conn.last_activity_time
        close_connection_no_voice_time = int(
            conn.config.get("close_connection_no_voice_time", 120)
        )
        if (
            not conn.close_after_chat
            and no_voice_time > 1000 * close_connection_no_voice_time
        ):
            conn.close_after_chat = True
            conn.client_abort = False
            end_prompt = conn.config.get("end_prompt", {})
            if end_prompt and end_prompt.get("enable", True) is False:
                conn.logger.bind(tag=TAG).info("结束对话，无需发送结束提示语")
                await conn.close()
                return
            prompt = end_prompt.get("prompt")
            if not prompt:
                prompt = "请你以```时间过得真快```未来头，用富有感情、依依不舍的话来结束这场对话吧。！"
            await startToChat(conn, prompt)


async def max_out_size(conn):
    conn.client_abort = False
    text = "不好意思，我现在有点事情要忙，明天这个时候我们再聊，约好了哦！明天不见不散，拜拜！"
    await send_stt_message(conn, text)
    file_path = "config/assets/max_output_size.wav"
    opus_packets = audio_to_data(file_path)
    speak_text_with_subtitle(conn, text, opus_packets)
    conn.close_after_chat = True


async def check_bind_device(conn):
    if conn.bind_code:
        # 确保bind_code是6位数字
        if len(conn.bind_code) != 6:
            conn.logger.bind(tag=TAG).error(f"无效的绑定码格式: {conn.bind_code}")
            text = "绑定码格式错误，请检查配置。"
            await send_stt_message(conn, text)
            return

        text = f"请登录控制面板，输入{conn.bind_code}，绑定设备。"
        await send_stt_message(conn, text)

        audio_packets = []
        music_path = "config/assets/bind_code.wav"
        audio_packets.extend(audio_to_data(music_path))
        for i in range(6):
            try:
                digit = conn.bind_code[i]
                num_path = f"config/assets/bind_code/{digit}.wav"
                audio_packets.extend(audio_to_data(num_path))
            except Exception as e:
                conn.logger.bind(tag=TAG).error(f"播放数字音频失败: {e}")
        speak_text_with_subtitle(conn, text, audio_packets)
    else:
        # 播放未绑定提示
        conn.client_abort = False
        text = f"没有找到该设备的版本信息，请正确配置 OTA地址，然后重新编译固件。"
        await send_stt_message(conn, text)
        music_path = "config/assets/bind_not_found.wav"
        opus_packets = audio_to_data(music_path)
        speak_text_with_subtitle(conn, text, opus_packets)
