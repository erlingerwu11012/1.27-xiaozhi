import os
import io
import wave
import uuid
import json
import time
import queue
import asyncio
import traceback
import threading
import opuslib_next
from abc import ABC, abstractmethod
from config.logger import setup_logging
from typing import Any, Optional, Tuple, List
from core.handle.receiveAudioHandle import startToChat
from core.handle.reportHandle import enqueue_asr_report
from core.utils.util import remove_punctuation_and_length
from core.handle.receiveAudioHandle import handleAudioMessage

TAG = __name__
logger = setup_logging()


class ASRProviderBase(ABC):
    def __init__(self):
        pass

    # 打开音频通道
    async def open_audio_channels(self, conn):
        conn.asr_priority_thread = threading.Thread(
            target=self.asr_text_priority_thread, args=(conn,), daemon=True
        )
        conn.asr_priority_thread.start()

    # 有序处理ASR音频
    def asr_text_priority_thread(self, conn):
        while not conn.stop_event.is_set():
            try:
                message = conn.asr_audio_queue.get(timeout=1)
                seq = int(getattr(message, "seq", 0) or 0) if not isinstance(message, (bytes, bytearray)) else 0
                conn.asr_audio_inflight = int(getattr(conn, "asr_audio_inflight", 0) or 0) + 1
                conn._audio_inflight_seq = seq
                try:
                    future = asyncio.run_coroutine_threadsafe(
                        handleAudioMessage(conn, message),
                        conn.loop,
                    )
                    future.result()
                finally:
                    conn.asr_audio_inflight = max(
                        0, int(getattr(conn, "asr_audio_inflight", 1) or 1) - 1
                    )
            except queue.Empty:
                continue
            except Exception as e:
                logger.bind(tag=TAG).error(
                    f"处理ASR文本失败: {str(e)}, 类型: {type(e).__name__}, 堆栈: {traceback.format_exc()}"
                )
                continue

    # 接收音频
    async def receive_audio(self, conn, audio, audio_have_voice):
        if conn.client_listen_mode == "auto" or conn.client_listen_mode == "realtime":
            have_voice = audio_have_voice
        else:
            have_voice = conn.client_have_voice
        
        conn.asr_audio.append(audio)
        if not have_voice and not conn.client_have_voice:
            conn.asr_audio = conn.asr_audio[-10:]
            return

        if conn.client_voice_stop:
            asr_audio_task = conn.asr_audio.copy()
            conn.asr_audio.clear()
            conn.reset_vad_states()

            if len(asr_audio_task) > 15:
                await self.handle_voice_stop(conn, asr_audio_task)

    # 处理语音停止
    async def handle_voice_stop(self, conn, asr_audio_task: List[bytes], *, final_text=None, listen_epoch=None):
        """并行处理ASR和声纹识别"""
        from core.utils.person_identity import reset_speaker, freeze, refresh_directory
        import copy
        reset_speaker(conn)
        try:
            if listen_epoch is None:
                listen_epoch = getattr(conn, 'listen_epoch', 0)
            captured_session = conn.session_id
            refresh=getattr(conn,"person_directory_refresh_task",None)
            if refresh is not None:
                try:await asyncio.wait_for(asyncio.shield(refresh),timeout=2)
                except (asyncio.TimeoutError,Exception):pass
            if not hasattr(conn,"identity_state"):
                await refresh_directory(conn)
            captured_directory=copy.deepcopy(getattr(conn,"identity_state",{}) or {})
            total_start_time = time.monotonic()
            
            # 准备音频数据
            if conn.audio_format == "pcm":
                pcm_data = asr_audio_task
            else:
                pcm_data = self.decode_opus(asr_audio_task)
            
            combined_pcm_data = b"".join(pcm_data)
            
            # 预先准备WAV数据
            wav_data = None
            if conn.voiceprint_provider and combined_pcm_data:
                wav_data = self._pcm_to_wav(combined_pcm_data)
            
            # 定义ASR任务
            def run_asr():
                if final_text is not None:
                    return final_text, None
                start_time = time.monotonic()
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        result = loop.run_until_complete(
                            self.speech_to_text(asr_audio_task, conn.session_id, conn.audio_format)
                        )
                        end_time = time.monotonic()
                        logger.bind(tag=TAG).debug(f"ASR耗时: {end_time - start_time:.3f}s")
                        return result
                    finally:
                        loop.close()
                except Exception as e:
                    end_time = time.monotonic()
                    logger.bind(tag=TAG).error(f"ASR失败: {e}")
                    return ("", None)
            
            # 定义声纹识别任务
            def run_voiceprint():
                if not wav_data:
                    return None
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        # 使用连接的声纹识别提供者
                        result = loop.run_until_complete(
                            conn.voiceprint_provider.identify_speaker(wav_data, conn.session_id)
                        )
                        return result
                    finally:
                        loop.close()
                except Exception as e:
                    logger.bind(tag=TAG).error(f"声纹识别失败: {e}")
                    return None
            
            # 不得在 asyncio 事件循环线程中调用 Future.result() 阻塞等待。
            # 多设备同时结束说话时，原实现会阻塞整个事件循环。
            if conn.voiceprint_provider and wav_data:
                asr_result, voiceprint_result = await asyncio.wait_for(
                    asyncio.gather(
                        asyncio.to_thread(run_asr),
                        asyncio.to_thread(run_voiceprint),
                    ),
                    timeout=15,
                )
                results = {"asr": asr_result, "voiceprint": voiceprint_result}
            else:
                asr_result = await asyncio.wait_for(
                    asyncio.to_thread(run_asr), timeout=15
                )
                results = {"asr": asr_result, "voiceprint": None}
            
            
            if captured_session != conn.session_id or listen_epoch != getattr(conn, 'listen_epoch', 0) or conn.stop_event.is_set():
                return
            # 处理结果
            raw_text, _ = results.get("asr", ("", None))
            speaker_identity = results.get("voiceprint", None)
            speaker_display_name = ""
            if isinstance(speaker_identity, dict):
                speaker_display_name = str(
                    speaker_identity.get("display_name") or ""
                ).strip()
                speaker_user_id = str(speaker_identity.get("user_id") or "").strip()
                if speaker_user_id:
                    conn.current_speaker_user = {
                        "user_id": speaker_user_id,
                        "display_name": speaker_display_name,
                        "speaker_id": str(speaker_identity.get("speaker_id") or ""),
                    }
                else:
                    conn.current_speaker_user = None
                conn.current_speaker = speaker_display_name or None
            else:
                # 旧服务端/未绑定声纹只保留显示名兼容，不伪造统一用户。
                conn.current_speaker_user = None
                conn.current_speaker = (
                    str(speaker_identity).strip() if speaker_identity else None
                )
            archive_actor = freeze(conn,captured_directory,speaker_identity,epoch=listen_epoch)
            await self._emit_identity_context(conn)
            if captured_session != conn.session_id or listen_epoch != getattr(conn, 'listen_epoch', 0):
                return
            
            # 记录识别结果
            if raw_text:
                logger.bind(tag=TAG).info(f"识别文本: {raw_text}")
            if speaker_display_name or conn.current_speaker:
                logger.bind(tag=TAG).info(
                    f"识别说话人: {speaker_display_name or conn.current_speaker}"
                )
            
            # 性能监控
            total_time = time.monotonic() - total_start_time
            logger.bind(tag=TAG).debug(f"总处理耗时: {total_time:.3f}s")
            
            # 检查文本长度
            text_len, _ = remove_punctuation_and_length(raw_text)
            self.stop_ws_connection()
            
            if text_len > 0:
                # 构建包含说话人信息的JSON字符串
                enhanced_text = self._build_enhanced_text(raw_text, speaker_identity)
                
                # 使用自定义模块进行上报
                await startToChat(conn, enhanced_text)
                enqueue_asr_report(conn, enhanced_text, asr_audio_task, actor=archive_actor)
                
        except Exception as e:
            if listen_epoch == getattr(conn,"listen_epoch",0):
                reset_speaker(conn)
            logger.bind(tag=TAG).error(f"处理语音停止失败: {e}")
            import traceback
            logger.bind(tag=TAG).debug(f"异常详情: {traceback.format_exc()}")

    async def _emit_identity_context(self, conn) -> None:
        """向支持该消息的固件下发当前声纹用户；旧固件可安全忽略。"""
        from core.utils.device_outbound import guarded_ws_send

        current = getattr(conn, "current_speaker_user", None)
        payload = {
            "type": "identity_context",
            "current_speaker_user": "",
            "speaker_display_name": "",
        }
        actor=getattr(conn,"person_turn",None)
        if actor is not None:
            payload.update(actor.payload())
            payload["identity_protocol_version"]=2
        if isinstance(current, dict):
            payload["current_speaker_user"] = str(current.get("user_id") or "")
            payload["speaker_display_name"] = str(
                current.get("display_name") or ""
            )
        try:
            sent = await guarded_ws_send(conn, json.dumps(payload, ensure_ascii=False))
            identity_key = payload['current_speaker_user']
            if sent and getattr(conn, '_last_tool_speaker', '') != identity_key:
                conn._last_tool_speaker = identity_key
                from core.providers.tools.device_mcp.mcp_client import MCPClient
                if isinstance(getattr(conn, 'mcp_client', None), MCPClient):
                    from core.providers.tools.device_mcp.mcp_handler import send_mcp_tools_list_request
                    await send_mcp_tools_list_request(conn)
        except Exception as exc:
            # 身份上下文只是体验增强，不能阻断正常 ASR 对话。
            logger.bind(tag=TAG).warning(f"下发身份上下文失败: {exc}")

    def _build_enhanced_text(
        self, text: str, speaker_identity: Optional[Any]
    ) -> str:
        """构建包含说话人信息的文本"""
        if isinstance(speaker_identity, dict):
            speaker_name = str(
                speaker_identity.get("display_name") or ""
            ).strip()
        else:
            speaker_name = str(speaker_identity or "").strip()
        if speaker_name:
            return json.dumps({
                "speaker": speaker_name,
                "content": text
            }, ensure_ascii=False)
        return text

    def _pcm_to_wav(self, pcm_data: bytes) -> bytes:
        """将PCM数据转换为WAV格式"""
        if len(pcm_data) == 0:
            logger.bind(tag=TAG).warning("PCM数据为空，无法转换WAV")
            return b""
        
        # 确保数据长度是偶数（16位音频）
        if len(pcm_data) % 2 != 0:
            pcm_data = pcm_data[:-1]
        
        # 创建WAV文件头
        wav_buffer = io.BytesIO()
        try:
            with wave.open(wav_buffer, 'wb') as wav_file:
                wav_file.setnchannels(1)      # 单声道
                wav_file.setsampwidth(2)      # 16位
                wav_file.setframerate(16000)  # 16kHz采样率
                wav_file.writeframes(pcm_data)
            
            wav_buffer.seek(0)
            wav_data = wav_buffer.read()
            
            return wav_data
        except Exception as e:
            logger.bind(tag=TAG).error(f"WAV转换失败: {e}")
            return b""

    def stop_ws_connection(self):
        pass

    def save_audio_to_file(self, pcm_data: List[bytes], session_id: str) -> str:
        """PCM数据保存为WAV文件"""
        module_name = __name__.split(".")[-1]
        file_name = f"asr_{module_name}_{session_id}_{uuid.uuid4()}.wav"
        file_path = os.path.join(self.output_dir, file_name)

        with wave.open(file_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # 2 bytes = 16-bit
            wf.setframerate(16000)
            wf.writeframes(b"".join(pcm_data))

        return file_path

    @abstractmethod
    async def speech_to_text(
        self, opus_data: List[bytes], session_id: str, audio_format="opus"
    ) -> Tuple[Optional[str], Optional[str]]:
        """将语音数据转换为文本"""
        pass

    @staticmethod
    def decode_opus(opus_data: List[bytes]) -> List[bytes]:
        """将Opus音频数据解码为PCM数据"""
        try:
            decoder = opuslib_next.Decoder(16000, 1)
            pcm_data = []
            buffer_size = 960  # 每次处理960个采样点 (60ms at 16kHz)
            
            for i, opus_packet in enumerate(opus_data):
                try:
                    if not opus_packet or len(opus_packet) == 0:
                        continue
                    
                    pcm_frame = decoder.decode(opus_packet, buffer_size)
                    if pcm_frame and len(pcm_frame) > 0:
                        pcm_data.append(pcm_frame)
                        
                except opuslib_next.OpusError as e:
                    logger.bind(tag=TAG).warning(f"Opus解码错误，跳过数据包 {i}: {e}")
                except Exception as e:
                    logger.bind(tag=TAG).error(f"音频处理错误，数据包 {i}: {e}")
            
            return pcm_data
            
        except Exception as e:
            logger.bind(tag=TAG).error(f"音频解码过程发生错误: {e}")
            return []
