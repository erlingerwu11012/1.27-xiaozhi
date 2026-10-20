import time
import threading
import numpy as np
import torch
import opuslib_next
from config.logger import setup_logging
from core.providers.vad.base import VADProviderBase
from core.utils import trace_log as trace
from core.utils.trace_log import pcm_stats
from core.utils.utterance_state import (
    note_quiet_audio,
    note_speech_audio,
    snapshot,
)

TAG = __name__
logger = setup_logging()


class VADProvider(VADProviderBase):
    def __init__(self, config):
        logger.bind(tag=TAG).info("SileroVAD", config)
        self.model, _ = torch.hub.load(
            repo_or_dir=config["model_dir"],
            source="local",
            model="silero_vad",
            force_reload=False,
        )

        self.decoder = opuslib_next.Decoder(16000, 1)

        # 处理空字符串的情况
        threshold = config.get("threshold", "0.5")
        threshold_low = config.get("threshold_low", "0.2")
        min_silence_duration_ms = config.get("min_silence_duration_ms", "1000")

        self.vad_threshold = float(threshold) if threshold else 0.5
        self.vad_threshold_low = float(threshold_low) if threshold_low else 0.2

        self.silence_threshold_ms = (
            int(min_silence_duration_ms) if min_silence_duration_ms else 1000
        )

        # 至少要多少帧才算有语音
        self.frame_window_threshold = 3
        self._infer_lock = threading.Lock()

    def _decoder_for(self, conn):
        decoder = getattr(conn, "_vad_decoder", None)
        if decoder is None:
            decoder = opuslib_next.Decoder(16000, 1)
            conn._vad_decoder = decoder
        return decoder

    def _snapshot_rnn(self):
        state = {}
        for name in ("_state", "_context"):
            val = getattr(self.model, name, None)
            if torch.is_tensor(val):
                state[name] = val.detach().clone()
        return state

    def _restore_rnn(self, conn):
        saved = getattr(conn, "_silero_rnn_state", None)
        if not saved:
            reset = getattr(self.model, "reset_states", None)
            if callable(reset):
                reset()
            conn._silero_rnn_state = self._snapshot_rnn()
            return
        for name, val in saved.items():
            if torch.is_tensor(val):
                setattr(self.model, name, val.detach().clone())

    def _save_rnn(self, conn):
        conn._silero_rnn_state = self._snapshot_rnn()

    def is_vad(self, conn, opus_packet):
        try:
            t0 = time.perf_counter()
            pcm_frame = self._decoder_for(conn).decode(opus_packet, 960)
            decode_ms = round((time.perf_counter() - t0) * 1000.0, 3)
            conn.client_audio_buffer.extend(pcm_frame)  # 将新数据加入缓冲区
            stats = getattr(conn, "_trace_vad_pcm", None)
            if not isinstance(stats, dict):
                stats = {"frames": 0, "bytes": 0, "ms": 0.0, "decode_errors": 0}
                conn._trace_vad_pcm = stats
            meta = pcm_stats(pcm_frame, 16000, 1)
            stats["frames"] += 1
            stats["bytes"] += meta["bytes"]
            if isinstance(meta.get("duration_ms"), (int, float)):
                stats["ms"] += meta["duration_ms"]
            if stats["frames"] == 1 or stats["frames"] % 20 == 0:
                trace.emit(
                    "audio.vad_pcm",
                    conn,
                    {
                        "seq": stats["frames"],
                        "opus_bytes": len(opus_packet) if opus_packet else 0,
                        "decode_ms": decode_ms,
                        "pcm": meta,
                        "cumulative_pcm_ms": stats["ms"],
                        "buffer_bytes": len(conn.client_audio_buffer),
                    },
                )

            # 处理缓冲区中的完整帧（每次处理512采样点）
            client_have_voice = False
            packet_has_voice = False
            with self._infer_lock:
                self._restore_rnn(conn)
                try:
                    while len(conn.client_audio_buffer) >= 512 * 2:
                        # 提取前512个采样点（1024字节）
                        chunk = conn.client_audio_buffer[: 512 * 2]
                        conn.client_audio_buffer = conn.client_audio_buffer[512 * 2 :]

                        # 转换为模型需要的张量格式
                        audio_int16 = np.frombuffer(chunk, dtype=np.int16)
                        audio_float32 = audio_int16.astype(np.float32) / 32768.0
                        audio_tensor = torch.from_numpy(audio_float32)

                        # 检测语音活动；RNN 隐状态按连接保存/恢复
                        with torch.no_grad():
                            speech_prob = self.model(audio_tensor, 16000).item()

                        # 双阈值判断
                        if speech_prob >= self.vad_threshold:
                            is_voice = True
                        elif speech_prob <= self.vad_threshold_low:
                            is_voice = False
                        else:
                            is_voice = conn.last_is_voice

                        conn.last_is_voice = is_voice
                        conn.client_voice_window.append(is_voice)
                        client_have_voice = (
                            conn.client_voice_window.count(True)
                            >= self.frame_window_threshold
                        )
                        if client_have_voice:
                            packet_has_voice = True
                finally:
                    self._save_rnn(conn)

            frame_ms = meta.get("duration_ms")
            if not isinstance(frame_ms, (int, float)):
                frame_ms = 60.0
            if packet_has_voice:
                note_speech_audio(conn, frame_ms)
                conn.last_activity_time = time.time() * 1000
            else:
                became_stop = note_quiet_audio(conn, frame_ms, self.silence_threshold_ms)
                if became_stop:
                    trace.emit(
                        "vad.utterance_stop",
                        conn,
                        {
                            "stop_source": "vad_silence",
                            "silence_threshold_ms": self.silence_threshold_ms,
                            "state": snapshot(conn),
                            "note": "silence uses processed audio duration, not wall-clock handshake delay",
                        },
                    )

            return client_have_voice
        except opuslib_next.OpusError as e:
            logger.bind(tag=TAG).error(
                f"Opus decode failed: {e}, "
                f"len={len(opus_packet)}, "
                f"head={opus_packet[:4].hex() if len(opus_packet) >= 4 else opus_packet.hex()}"
            )
            stats = getattr(conn, "_trace_vad_pcm", None)
            if isinstance(stats, dict):
                stats["decode_errors"] = stats.get("decode_errors", 0) + 1
            trace.emit(
                "audio.opus_decode_error",
                conn,
                {
                    "error_type": "OpusError",
                    "error": str(e),
                    "opus_bytes": len(opus_packet) if opus_packet else 0,
                },
            )
        except Exception as e:
            logger.bind(tag=TAG).error(
                f"Error processing audio packet: {e}, "
                f"len={len(opus_packet) if opus_packet else 'None'}, "
                f"head={opus_packet[:4].hex() if opus_packet and len(opus_packet) >= 4 else 'N/A'}"
            )
            trace.emit(
                "audio.vad_error",
                conn,
                {"error_type": type(e).__name__, "error": str(e)},
            )
