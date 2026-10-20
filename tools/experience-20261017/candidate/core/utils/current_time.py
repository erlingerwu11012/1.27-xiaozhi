"""
时间工具模块
提供统一的时间获取功能（默认 Asia/Shanghai）
"""

import cnlunar
from datetime import datetime
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")

WEEKDAY_MAP = {
    "Monday": "星期一",
    "Tuesday": "星期二",
    "Wednesday": "星期三",
    "Thursday": "星期四",
    "Friday": "星期五",
    "Saturday": "星期六",
    "Sunday": "星期日",
}


def _now_shanghai() -> datetime:
    return datetime.now(SHANGHAI)


def get_current_time() -> str:
    """获取当前时间字符串 (格式: HH:MM:SS，上海时区)"""
    return _now_shanghai().strftime("%H:%M:%S")


def get_current_datetime() -> str:
    """获取当前本地日期时间字符串"""
    return _now_shanghai().strftime("%Y-%m-%d %H:%M:%S")


def get_current_unix() -> int:
    """获取当前 Unix 秒级时间戳"""
    return int(_now_shanghai().timestamp())


def get_current_date() -> str:
    """获取今天日期字符串 (格式: YYYY-MM-DD)"""
    return _now_shanghai().strftime("%Y-%m-%d")


def get_current_weekday() -> str:
    """获取今天星期几"""
    now = _now_shanghai()
    return WEEKDAY_MAP[now.strftime("%A")]


def get_current_lunar_date() -> str:
    """获取农历日期字符串"""
    try:
        now = _now_shanghai()
        naive = now.replace(tzinfo=None)
        today_lunar = cnlunar.Lunar(naive, godType="8char")
        return "%s年%s%s" % (
            today_lunar.lunarYearCn,
            today_lunar.lunarMonthCn[:-1],
            today_lunar.lunarDayCn,
        )
    except Exception:
        return "农历获取失败"


def get_current_time_info() -> tuple:
    """
    获取当前时间信息
    返回: (当前时间字符串, 今天日期, 星期, 农历日期)
    """
    current_time = get_current_time()
    today_date = get_current_date()
    today_weekday = get_current_weekday()
    lunar_date = get_current_lunar_date()

    return current_time, today_date, today_weekday, lunar_date


def get_prompt_time_context() -> dict:
    """供 system prompt 动态注入的时间上下文。"""
    current_time, today_date, today_weekday, lunar_date = get_current_time_info()
    return {
        "current_time": current_time,
        "current_datetime": get_current_datetime(),
        "today_date": today_date,
        "today_weekday": today_weekday,
        "lunar_date": lunar_date,
        "timezone": "Asia/Shanghai",
        "unix_timestamp": str(get_current_unix()),
    }
