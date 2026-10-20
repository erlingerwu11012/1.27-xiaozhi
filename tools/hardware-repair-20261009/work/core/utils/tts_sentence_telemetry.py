"""下行 TTS 句级发送统计与上游事件时差遥测。

仅记录计数与单调时戳，不保存任何文本 / 音频 / Token / MCP payload。

线程模型：本对象所有方法必须在同一个事件循环（主循环）上调用——
- 火山监听任务 `_start_monitor_tts_response` 在主循环；
- `sendAudioMessage` / `sendAudio` 经 `run_coroutine_threadsafe` 投递回主循环；
- `handleAbortMessage` / `ConnectionHandler.close` 亦在主循环。
"""

from __future__ import annotations

import time


class TTSSentenceTelemetry:
    """单个句子（一次 FIRST..LAST 周期）的下行发送观测。

    ``sentence_id`` 变化即视为新句；同一 ``sentence_id`` 的重复 FIRST（如连续
    唤醒词应答，sentence_id 为 None）通过 ``terminated`` 标志区分，自动开启新 epoch。
    """

    def __init__(self, clock=None):
        self._clock = clock or (lambda: int(time.monotonic() * 1000))
        self._epoch_counter = 0
        self.epoch = 0
        self._reset_sentence(None)

    # ── 内部状态重置 ──────────────────────────────────────────────
    def _reset_sentence(self, sentence_id):
        self.sentence_id = sentence_id
        self.started = False
        self.terminated = False
        self.frame_count = 0
        self.total_payload_bytes = 0
        self.first_send_ms = None
        self.last_send_ms = None
        self.max_interframe_gap_ms = 0
        self.max_ws_send_ms = 0.0
        self.aborted = False
        # 上游（火山引擎）事件时戳
        self.tts_sentence_start_ms = None
        self.first_tts_response_ms = None
        self.last_tts_response_ms = None
        self.tts_sentence_end_ms = None
        self.session_finished_ms = None
        self.session_canceled_ms = None
        # 服务端 stop 消息实际下发时点
        self.stop_dispatched_ms = None

    def _new_sentence(self, sentence_id):
        self._epoch_counter += 1
        self.epoch = self._epoch_counter
        self._reset_sentence(sentence_id)

    def _now(self):
        return self._clock()

    def _ensure(self, sentence_id):
        if sentence_id is None:
            sentence_id = ""
        if sentence_id != self.sentence_id:
            self._new_sentence(sentence_id)
        return self

    def _start_boundary(self, sentence_id):
        """发送侧 FIRST 边界：sentence_id 变化或上一句已终结时开启新句。"""
        if sentence_id is None:
            sentence_id = ""
        if sentence_id != self.sentence_id or self.terminated:
            self._new_sentence(sentence_id)
        self.started = True

    # ── 上游事件记录 ──────────────────────────────────────────────
    def note_tts_sentence_start(self, sentence_id):
        self._ensure(sentence_id)
        if self.tts_sentence_start_ms is None:
            self.tts_sentence_start_ms = self._now()

    def note_tts_response(self, sentence_id):
        self._ensure(sentence_id)
        now = self._now()
        if self.first_tts_response_ms is None:
            self.first_tts_response_ms = now
        self.last_tts_response_ms = now

    def note_tts_sentence_end(self, sentence_id):
        self._ensure(sentence_id)
        self.tts_sentence_end_ms = self._now()

    def note_session_finished(self, sentence_id):
        self._ensure(sentence_id)
        self.session_finished_ms = self._now()

    def note_session_canceled(self, sentence_id):
        self._ensure(sentence_id)
        self.session_canceled_ms = self._now()

    # ── 发送侧记录（在成功 `await websocket.send(...)` 之后调用） ──
    def note_sentence_started(self, sentence_id):
        self._start_boundary(sentence_id)

    def note_audio_sent(self, sentence_id, payload_bytes, ws_send_ms=None):
        self._ensure(sentence_id)
        self.started = True
        now = self._now()
        self.frame_count += 1
        self.total_payload_bytes += int(payload_bytes or 0)
        if self.first_send_ms is None:
            self.first_send_ms = now
        if self.last_send_ms is not None:
            gap = now - self.last_send_ms
            if gap > self.max_interframe_gap_ms:
                self.max_interframe_gap_ms = gap
        self.last_send_ms = now
        if ws_send_ms is not None:
            try:
                ws_ms = float(ws_send_ms)
            except (TypeError, ValueError):
                ws_ms = 0.0
            if ws_ms > float(self.max_ws_send_ms or 0.0):
                self.max_ws_send_ms = ws_ms

    def note_stop_dispatched(self, sentence_id):
        self._ensure(sentence_id)
        self.stop_dispatched_ms = self._now()

    def mark_aborted(self, sentence_id):
        self._ensure(sentence_id)
        self.started = True
        self.aborted = True

    # ── 终态输出 ──────────────────────────────────────────────────
    @staticmethod
    def _gap_or_na(later, earlier):
        if later is None or earlier is None:
            return "n/a"
        return str(int(later - earlier))

    def build_fields(self, reason, session_label):
        if self.first_send_ms is not None and self.last_send_ms is not None:
            first_to_last_ms = str(int(self.last_send_ms - self.first_send_ms))
        else:
            first_to_last_ms = "n/a"
        return {
            "session": session_label,
            "sentence": self.epoch,
            "frames": self.frame_count,
            "bytes": self.total_payload_bytes,
            "first_to_last_ms": first_to_last_ms,
            "max_gap_ms": self.max_interframe_gap_ms,
            "max_ws_send_ms": (
                round(float(self.max_ws_send_ms), 1)
                if self.max_ws_send_ms
                else 0
            ),
            "aborted": 1 if self.aborted else 0,
            "reason": reason,
            "last_tts_response_to_last_send_ms": self._gap_or_na(
                self.last_send_ms, self.last_tts_response_ms
            ),
            "sentence_end_to_last_send_ms": self._gap_or_na(
                self.last_send_ms, self.tts_sentence_end_ms
            ),
            "session_finished_to_stop_ms": self._gap_or_na(
                self.stop_dispatched_ms, self.session_finished_ms
            ),
        }

    def finalize(self, reason, session_label):
        """输出一次终态日志字符串；已终结或未开始的句子返回 None。

        仅在以下终态调用：
        - 实际发送 LAST / tts stop（reason=normal_stop|session_finished）；
        - abort（reason=abort）；
        - 连接关闭且该句尚未终结（reason=missing_stop_observed）。
        """
        if self.terminated or not self.started:
            return None
        self.terminated = True
        f = self.build_fields(reason, session_label)
        return (
            f"[tts_sentence_done] session={f['session']} sentence={f['sentence']} "
            f"frames={f['frames']} bytes={f['bytes']} "
            f"first_to_last_ms={f['first_to_last_ms']} "
            f"max_gap_ms={f['max_gap_ms']} max_ws_send_ms={f['max_ws_send_ms']} "
            f"aborted={f['aborted']} "
            f"reason={f['reason']} "
            f"last_tts_response_to_last_send_ms={f['last_tts_response_to_last_send_ms']} "
            f"sentence_end_to_last_send_ms={f['sentence_end_to_last_send_ms']} "
            f"session_finished_to_stop_ms={f['session_finished_to_stop_ms']}"
        )
