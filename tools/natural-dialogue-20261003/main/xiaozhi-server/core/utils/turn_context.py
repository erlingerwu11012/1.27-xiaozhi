"""本轮冻结上下文：把时间、情绪、说话人、检索记忆等动态信息
绑定到对应用户消息，避免每轮改写 system 破坏前缀缓存。

原则：
- depth==0 创建本轮时采集一次；depth>0 工具回调与重试复用同一份。
- 不提供 Unix 秒（提醒由服务端按实际执行时间校验）。
- 情绪缺失记 unknown，不伪造置信度。
- 检索记忆限定长度；失败/为空不当作记忆正文。
- 渲染为简短文本块，作为该轮 user content 的首个 text part。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

DEFAULT_TIMEZONE = "Asia/Shanghai"
_MEMORY_MAX_CHARS = 2000


def _str(v: Any) -> str:
    return "" if v is None else str(v)


def build_turn_context(conn, memory_str: Optional[str], emotion_result: Optional[dict]) -> Dict[str, Any]:
    ctx = {}

    try:
        from core.utils.current_time import get_prompt_time_context

        t = get_prompt_time_context()
        ctx["current_datetime"] = t.get("current_datetime", "")
        ctx["today_date"] = t.get("today_date", "")
        ctx["today_weekday"] = t.get("today_weekday", "")
        ctx["lunar_date"] = t.get("lunar_date", "")
        ctx["timezone"] = t.get("timezone", DEFAULT_TIMEZONE)
    except Exception:
        ctx.setdefault("timezone", DEFAULT_TIMEZONE)

    er = emotion_result if isinstance(emotion_result, dict) else {}
    ctx["emotion"] = er.get("emotion") or "unknown"
    ctx["emotion_raw"] = er.get("raw_emotion") or ""
    ctx["utterance_id"] = _str(er.get("utterance_id") or "")
    ctx["item_id"] = _str(er.get("item_id") or "")
    ctx["listen_epoch"] = _str(er.get("listen_epoch") or "")

    from core.utils.person_identity import current_turn
    actor=current_turn(conn)
    ctx["speaker"] = actor.display_name if actor and actor.eligible else ""
    ctx["identity"] = actor.payload() if actor else {}

    if memory_str:
        ctx["memory_text"] = _str(memory_str)[:_MEMORY_MAX_CHARS]
    else:
        ctx["memory_text"] = ""

    try:
        from core.utils.cache.manager import cache_manager, CacheType

        client_ip = getattr(conn, "client_ip", None) or ""
        local_address = cache_manager.get(CacheType.LOCATION, client_ip) if client_ip else ""
        ctx["location"] = _str(local_address or "")

        if local_address:
            weather_val, weather_ts = cache_manager.get_with_time(CacheType.WEATHER, local_address)
            ctx["weather"] = _str(weather_val or "")
            if weather_ts:
                import time

                ctx["weather_sourced_at"] = time.strftime(
                    "%Y-%m-%d %H:%M", time.localtime(weather_ts)
                )
    except Exception:
        ctx["location"] = ""

    return ctx


def render_turn_context(ctx: Optional[Dict[str, Any]]) -> str:
    if not ctx:
        return ""

    lines = []

    time_parts = []
    if ctx.get("current_datetime"):
        time_parts.append(f"时间:{ctx['current_datetime']}")
    if ctx.get("today_weekday"):
        time_parts.append(f"{ctx['today_weekday']}")
    if time_parts:
        lines.append("".join(time_parts))

    if ctx.get("lunar_date"):
        lines.append(f"农历:{ctx['lunar_date']}")
    if ctx.get("timezone"):
        lines.append(f"时区:{ctx['timezone']}")

    if ctx.get("emotion") and ctx.get("emotion") != "unknown":
        lines.append(f"语音情绪参考:{ctx['emotion']}(识别推测,非事实)")

    if ctx.get("speaker"):
        lines.append(f"当前说话人:{ctx['speaker']}")
    if not ctx.get("weather"):
        lines.append("本轮未提供天气或现场观察，不从日期时间推测天气，不编造周围景象。")

    if ctx.get("location"):
        lines.append(f"所在城市:{ctx['location']}")

    if ctx.get("weather"):
        if ctx.get("weather_sourced_at"):
            src = f"(来源时间:{ctx['weather_sourced_at']})"
        else:
            src = ""
        lines.append(f"天气参考{src}(可能过期,可调用天气工具刷新):{ctx['weather']}")

    if ctx.get("memory_text"):
        lines.append(f"相关记忆:{ctx['memory_text']}")

    if not lines:
        return ""

    return "[本轮上下文]\n" + "\n".join(lines)
