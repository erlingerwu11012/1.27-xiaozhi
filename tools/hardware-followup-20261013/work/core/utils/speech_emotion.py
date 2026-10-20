"""Official Qwen ASR realtime emotion labels. Do not invent a neutral default."""

OFFICIAL_EMOTIONS = {
    'surprised': '惊讶',
    'neutral': '平静',
    'happy': '愉快',
    'sad': '悲伤',
    'disgusted': '厌恶',
    'angry': '愤怒',
    'fearful': '恐惧',
}

UNKNOWN = '未知'
UNKNOWN_CODE = 'unknown'

LLM_HINT_PREFIX = '【本轮语音情绪参考】'


def normalize_emotion(value) -> str:
    if not isinstance(value, str):
        return UNKNOWN_CODE
    key = value.strip().lower()
    if key in OFFICIAL_EMOTIONS:
        return key
    return UNKNOWN_CODE


def emotion_label(code) -> str:
    if code in OFFICIAL_EMOTIONS:
        return OFFICIAL_EMOTIONS[code]
    return UNKNOWN


def preview_text(text, stash):
    return f"{text or ''}{stash or ''}"


def inject_emotion_enabled(config: dict) -> bool:
    if not isinstance(config, dict):
        return False
    value = config.get("inject_emotion_hint", False)
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def emotion_matches_turn(conn, result) -> bool:
    """核对 ASR 情绪结果是否属于「当前正在处理的用户输入」。

    仅凭清空共享槽不能防串轮：同一 listen_epoch 内的下一段识别结果可能
    覆盖共享槽。这里按 (listen_epoch, utterance_id) 组合核对——
    - listen_epoch 不一致：跨监听代的迟到结果，丢弃；
    - utterance_id 不一致：同一监听代内的其他语音段，丢弃。
    字段缺失（旧 ASR 提供者 / conn 侧未初始化）时视为无法核对，放行，
    不因此丢弃情绪（缺失记 unknown 由上层处理，不伪造置信度）。
    """
    if not isinstance(result, dict):
        return False

    conn_epoch = getattr(conn, "listen_epoch", None)
    res_epoch = result.get("listen_epoch")
    if conn_epoch not in (None, "", 0) and res_epoch not in (None, "", 0):
        try:
            if int(res_epoch) != int(conn_epoch):
                return False
        except (TypeError, ValueError):
            return False

    conn_uid = getattr(conn, "utterance_id", None)
    res_uid = result.get("utterance_id")
    if conn_uid not in (None, "", 0) and res_uid not in (None, "", 0):
        try:
            if int(res_uid) != int(conn_uid):
                return False
        except (TypeError, ValueError):
            return False

    return True


def build_llm_hint(result) -> str:
    if not isinstance(result, dict):
        return ''
    code = normalize_emotion(result.get("emotion"))
    label = emotion_label(code)
    return (
        f"{LLM_HINT_PREFIX}"
        f"这是语音识别模型对本轮语气的推测，不是用户原话，也不是确定事实。"
        f"推测情绪：{label}。"
        f"若与用户明确表达冲突，以用户原话为准。"
        f"不要把该标签读给用户，也不要据此更新长期用户画像。"
    )
