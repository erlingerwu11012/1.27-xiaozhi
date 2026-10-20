"""设备提醒时间解析（Asia/Shanghai，服务端确定性计算 Unix 秒）。

LLM 只提供自然语言时间表达；本模块负责算出最终 remind_at。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")

_CN_DIGIT = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


@dataclass(frozen=True)
class RemindTimeParseResult:
    """解析成功结果。"""

    remind_at: int
    local_dt: datetime
    source_expr: str


def now_shanghai(now: Optional[datetime] = None) -> datetime:
    """返回 Asia/Shanghai 的 timezone-aware datetime。"""
    if now is None:
        return datetime.now(SHANGHAI)
    if now.tzinfo is None:
        return now.replace(tzinfo=SHANGHAI)
    return now.astimezone(SHANGHAI)


def unix_seconds(dt: Optional[datetime] = None) -> int:
    """当前（或给定）上海时间对应的 Unix 秒。"""
    return int(now_shanghai(dt).timestamp())


def cn_num_to_int(token: str) -> Optional[int]:
    """将中文数字（零..十、十一..九十九、两位数组合）转为 int。"""
    if token is None:
        return None
    token = token.strip()
    if not token:
        return None
    if token.isdigit():
        return int(token)

    if token in _CN_DIGIT:
        return _CN_DIGIT[token]

    # 十、十一、二十、二十五、两位数
    if "十" in token:
        parts = token.split("十")
        if len(parts) != 2:
            return None
        left, right = parts[0], parts[1]
        tens = 1 if left == "" else _CN_DIGIT.get(left)
        ones = 0 if right == "" else _CN_DIGIT.get(right)
        if tens is None or ones is None:
            return None
        return tens * 10 + ones

    # 连续单字如「一二」不支持；仅单字已在上面处理
    return None


def _normalize_expr(expr: str) -> str:
    return (expr or "").strip().replace(" ", "").replace("　", "")


def extract_time_expression(*texts: str) -> str:
    """从若干文本中提取最可能的时间表达（优先相对时间）。"""
    candidates = []
    patterns = [
        r"(半小时后)",
        r"((?:[0-9]+|[零〇一二两三四五六七八九十]+)\s*(?:分钟|小时|天|秒|分|时)\s*后)",
        r"(明天(?:上午|下午|早上|中午|晚上)?[0-9零〇一二两三四五六七八九十]+点(?:[0-9零〇一二两三四五六七八九十]+分?)?)",
        r"(今晚[0-9零〇一二两三四五六七八九十]+点(?:[0-9零〇一二两三四五六七八九十]+分?)?)",
        r"(今天(?:上午|下午|早上|中午|晚上)?[0-9零〇一二两三四五六七八九十]+点(?:[0-9零〇一二两三四五六七八九十]+分?)?)",
        r"((?:上午|下午|早上|中午|晚上)[0-9零〇一二两三四五六七八九十]+点(?:[0-9零〇一二两三四五六七八九十]+分?)?)",
        r"([0-9零〇一二两三四五六七八九十]+点[0-9零〇一二两三四五六七八九十]+分)",
    ]
    for text in texts:
        if not text:
            continue
        raw = str(text)
        for pat in patterns:
            m = re.search(pat, raw)
            if m:
                candidates.append(m.group(1).replace(" ", ""))
    # 相对时间优先
    for c in candidates:
        if "后" in c:
            return c
    return candidates[0] if candidates else ""


def has_schedule_intent(*texts: str) -> bool:
    """是否包含定时提醒语义（非纯便签）。"""
    joined = " ".join(str(t) for t in texts if t)
    if not joined:
        return False
    keys = (
        r"提醒",
        r"闹钟",
        r"叫我",
        r"到点",
        r"分钟后",
        r"小时后",
        r"半小时",
        r"天后",
        r"明天",
        r"今晚",
        r"后天",
        r"上午\d",
        r"下午\d",
        r"点钟",
        r"\d+\s*点",
        r"[零〇一二两三四五六七八九十]+\s*点",
    )
    return any(re.search(k, joined) for k in keys)


def has_relative_time_intent(*texts: str) -> bool:
    """是否包含相对时间（几分钟后/几小时后），禁止用 alarm_set 表达。"""
    joined = " ".join(str(t) for t in texts if t)
    if not joined:
        return False
    return bool(
        re.search(
            r"(分钟后|小时后|半小时|秒后|天后|(?:[0-9]+|[零〇一二两三四五六七八九十]+)\s*(?:分钟|小时|分|时)\s*后)",
            joined,
        )
    )


def parse_remind_time(
    expr: str, now: Optional[datetime] = None
) -> Optional[RemindTimeParseResult]:
    """解析自然语言时间为未来 Unix 秒。失败返回 None。"""
    source = _normalize_expr(expr)
    if not source:
        return None

    base = now_shanghai(now)

    # 1) 半小时后
    if source in ("半小时后", "半个小时后"):
        local_dt = base + timedelta(minutes=30)
        return RemindTimeParseResult(int(local_dt.timestamp()), local_dt, source)

    # 2) N 分钟/小时/天/秒 后（阿拉伯或中文数字）
    m = re.fullmatch(
        r"([0-9]+|[零〇一二两三四五六七八九十]+)\s*(分钟|小时|天|秒|分|时)\s*后",
        source,
    )
    if m:
        num = cn_num_to_int(m.group(1))
        if num is None or num < 0:
            return None
        unit = m.group(2)
        if unit in ("秒",):
            delta = timedelta(seconds=num)
        elif unit in ("分钟", "分"):
            delta = timedelta(minutes=num)
        elif unit in ("小时", "时"):
            delta = timedelta(hours=num)
        else:
            delta = timedelta(days=num)
        local_dt = base + delta
        return RemindTimeParseResult(int(local_dt.timestamp()), local_dt, source)

    # 3) 明天/今天/今晚 + 点
    m = re.fullmatch(
        r"(今天|明天|后天|今晚)?"
        r"(上午|下午|早上|中午|晚上)?"
        r"([0-9]+|[零〇一二两三四五六七八九十]+)\s*点"
        r"(?:([0-9]+|[零〇一二两三四五六七八九十]+)\s*分?)?",
        source,
    )
    if m:
        day_word, period, hour_tok, minute_tok = m.groups()
        hour = cn_num_to_int(hour_tok)
        minute = cn_num_to_int(minute_tok) if minute_tok else 0
        if hour is None or minute is None:
            return None
        if minute < 0 or minute > 59:
            return None

        # 12 小时制修正
        if period in ("下午", "晚上") and 0 < hour < 12:
            hour += 12
        elif period == "中午" and hour < 12:
            hour = 12 if hour == 0 or hour == 12 else hour
            if hour != 12 and hour < 11:
                hour = 12
        elif period in ("上午", "早上") and hour == 12:
            hour = 0
        if day_word == "今晚" and hour < 12:
            # 「今晚8点」→ 20:00
            hour += 12
        if hour > 23:
            return None

        day_offset = 0
        if day_word == "明天":
            day_offset = 1
        elif day_word == "后天":
            day_offset = 2

        local_dt = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
        local_dt = local_dt + timedelta(days=day_offset)

        # 无明确日期且已过去：滚到次日（「今晚」已过则失败，不跨到明天冒充今晚）
        if day_word is None and local_dt <= base:
            local_dt = local_dt + timedelta(days=1)
        if day_word == "今晚" and local_dt <= base:
            return None
        if day_word == "今天" and local_dt <= base:
            return None

        return RemindTimeParseResult(int(local_dt.timestamp()), local_dt, source)

    # 4) dateparser 兜底（正确使用 RELATIVE_BASE settings，禁止 relative_base= kwargs）
    try:
        import dateparser

        dt = dateparser.parse(
            source,
            settings={
                "TIMEZONE": "Asia/Shanghai",
                "RETURN_AS_TIMEZONE_AWARE": True,
                "RELATIVE_BASE": base.replace(tzinfo=None),
                "PREFER_DATES_FROM": "future",
            },
        )
        if dt is not None:
            if dt.tzinfo is None:
                local_dt = dt.replace(tzinfo=SHANGHAI)
            else:
                local_dt = dt.astimezone(SHANGHAI)
            return RemindTimeParseResult(int(local_dt.timestamp()), local_dt, source)
    except Exception:
        pass

    return None


def ensure_future_remind_at(
    remind_at: int, now: Optional[datetime] = None
) -> bool:
    """remind_at 必须严格大于当前 Unix 秒。"""
    return isinstance(remind_at, int) and remind_at > unix_seconds(now)
