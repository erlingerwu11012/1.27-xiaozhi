# TTS 字幕时序

所有可读文本语音输出必须满足：

```
tts.start → sentence_start(text) → Opus 音频帧 → tts.stop
```

统一入口：`core/handle/sendAudioHandle.py` 的 `speak_text_with_subtitle`。

纯提示音可 `subtitle_exempt=True` 并记录 `[tts_subtitle] subtitle_exempt=1`。

## 可观测性

`send_tts_message` 对 `start` / `sentence_start` / `stop` 写入 `[tts_audit]` 事件（`tts_subtitle_event`），`sentence_start` 仅记录 `script_len`，不落完整文本。
