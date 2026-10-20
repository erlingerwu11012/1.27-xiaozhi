# 文件路径: tools/reminder_tool.py
import os
import re
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, Tuple
from zoneinfo import ZoneInfo

import dateparser
import aiomysql
import httpx

from core.config import config
from core.db_config import DB_HOST, DB_NAME, DB_PASSWORD, DB_PORT, DB_USER
from core.decorators import tool_meta
from tools.mcp_utils import mcp_result, mcp_error

logger = logging.getLogger(__name__)
SHANGHAI = ZoneInfo("Asia/Shanghai")
REMINDER_TTS_URL = os.environ.get(
    "REMINDER_TTS_URL",
    "http://127.0.0.1:8006/api/v1/broadcast",
)

_pool: Optional[aiomysql.Pool] = None
_pool_lock = asyncio.Lock()

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


def _now() -> datetime:
    return datetime.now(SHANGHAI).replace(tzinfo=None)


def _cn_num_to_int(token: str) -> Optional[int]:
    token = (token or "").strip()
    if not token:
        return None
    if token.isdigit():
        return int(token)
    if token in _CN_DIGIT:
        return _CN_DIGIT[token]
    if "十" in token:
        left, _, right = token.partition("十")
        tens = 1 if left == "" else _CN_DIGIT.get(left)
        ones = 0 if right == "" else _CN_DIGIT.get(right)
        if tens is None or ones is None:
            return None
        return tens * 10 + ones
    return None


async def _get_pool() -> aiomysql.Pool:
    """获取 MySQL 连接池，具备断线重连。"""
    global _pool
    async with _pool_lock:
        if _pool is not None:
            try:
                async with _pool.acquire() as conn:
                    await conn.ping()
            except Exception:
                _pool.close()
                await _pool.wait_closed()
                _pool = None
        if _pool is None:
            _pool = await aiomysql.create_pool(
                host=DB_HOST,
                port=DB_PORT,
                user=DB_USER,
                password=DB_PASSWORD,
                db=DB_NAME,
                charset="utf8mb4",
                autocommit=True,
                minsize=1,
                maxsize=4,
            )
            logger.info("reminder_tool: MySQL 连接池已创建 %s@%s", DB_USER, DB_HOST)
        return _pool


def _parse_relative(expr: str, now: datetime) -> Optional[datetime]:
    expr = (expr or "").strip().replace(" ", "")
    if expr in ("半小时后", "半个小时后"):
        return now + timedelta(minutes=30)
    m = re.fullmatch(
        r"([0-9]+|[零〇一二两三四五六七八九十]+)(分钟|小时|天|秒|分|时)后",
        expr,
    )
    if not m:
        return None
    num = _cn_num_to_int(m.group(1))
    if num is None:
        return None
    unit = m.group(2)
    if unit == "秒":
        return now + timedelta(seconds=num)
    if unit in ("分钟", "分"):
        return now + timedelta(minutes=num)
    if unit in ("小时", "时"):
        return now + timedelta(hours=num)
    return now + timedelta(days=num)


def _dateparser_parse(expr: str, now: datetime) -> Optional[datetime]:
    """使用 dateparser 正确 API：RELATIVE_BASE 放入 settings，禁止 relative_base= 关键字。"""
    try:
        return dateparser.parse(
            expr,
            settings={
                "TIMEZONE": "Asia/Shanghai",
                "RETURN_AS_TIMEZONE_AWARE": False,
                "RELATIVE_BASE": now,
                "PREFER_DATES_FROM": "future",
            },
        )
    except TypeError as e:
        # 防御：绝不能再把 relative_base 当 kwargs
        logger.error("reminder_tool: dateparser API 异常 %s", e)
        return None


def _parse_time_and_content(
    text: str, content: str = "", remind_time_str: str = ""
) -> Tuple[Optional[datetime], str]:
    """从用户输入解析提醒时间和内容。返回 (remind_time, content)，解析失败时 remind_time 为 None。"""
    now = _now()

    if content and remind_time_str:
        dt = _parse_relative(remind_time_str, now) or _dateparser_parse(
            remind_time_str, now
        )
        return (dt, content.strip())

    if not text or not text.strip():
        return (None, content.strip() or "提醒事项")

    raw = text.strip()
    if "提醒" in raw:
        parts = raw.split("提醒", 1)
        time_part = (parts[0] or "").strip()
        content_part = (parts[1] or "").strip().lstrip("我").strip() or "提醒事项"
    else:
        time_part = raw
        content_part = "提醒事项"

    dt = _parse_relative(time_part, now)
    if dt is not None:
        return (dt, content_part)

    dt = _dateparser_parse(time_part or raw, now)
    if dt is None and time_part != raw:
        dt = _dateparser_parse(raw, now)
    return (dt, content_part)


async def _call_tts_broadcast(text: str) -> bool:
    """调用主控 TTS/广播接口。"""
    payload = {"text": text, "deviceId": "default"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(REMINDER_TTS_URL, json=payload)
            if r.status_code in (200, 201, 204):
                return True
            logger.warning("reminder_tool: TTS 接口返回 %s %s", r.status_code, r.text)
            return False
    except Exception as e:
        logger.exception("reminder_tool: 调用 TTS 接口失败 %s", e)
        return False


@tool_meta(title="定时提醒")
async def add_reminder(
    text: str = "",
    content: str = "",
    remind_time_str: str = "",
    **kwargs,
) -> str:
    """添加语音备忘录或定时提醒。可传用户原话（text），或 content + remind_time_str。时间支持自然语言。"""
    if not text and not (content and remind_time_str):
        return mcp_error("请提供提醒内容：可传用户原话（text），或提醒内容（content）与时间（remind_time_str）。")
    remind_time, content_val = _parse_time_and_content(text, content, remind_time_str)
    if remind_time is None:
        return mcp_error("未能解析出有效提醒时间，请说明具体时间，例如：十分钟后提醒我开会。")

    if remind_time <= _now():
        return mcp_error("提醒时间必须是将来时间，请重新设置。")

    pool = await _get_pool()
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO sys_reminders (content, remind_time, is_reminded, created_at) VALUES (%s, %s, 0, NOW())",
                    (content_val, remind_time),
                )
        return mcp_result(f"已为您设置提醒：{remind_time.strftime('%Y-%m-%d %H:%M')} {content_val}")
    except Exception as e:
        logger.exception("reminder_tool: 写入提醒失败 %s", e)
        return mcp_error(f"设置提醒失败：{e}")


async def scheduler_loop() -> None:
    """后台调度器：每 30 秒查询到期未提醒记录，调用 TTS 接口并更新状态。"""
    logger.info("reminder_tool: 调度器已启动，间隔 30s")
    while True:
        try:
            await asyncio.sleep(30)
            pool = await _get_pool()
            now = _now()
            async with pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cur:
                    await cur.execute(
                        "SELECT id, content FROM sys_reminders WHERE remind_time <= %s AND is_reminded = 0",
                        (now,),
                    )
                    rows = await cur.fetchall()
            for row in rows:
                rid, content = row["id"], row["content"]
                ok = await _call_tts_broadcast(content)
                if ok:
                    async with pool.acquire() as c:
                        async with c.cursor() as cur:
                            await cur.execute(
                                "UPDATE sys_reminders SET is_reminded = 1 WHERE id = %s",
                                (rid,),
                            )
                    logger.info("reminder_tool: 已播报提醒 id=%s content=%s", rid, content[:50])
        except asyncio.CancelledError:
            logger.info("reminder_tool: 调度器已停止")
            raise
        except Exception as e:
            logger.exception("reminder_tool: 调度器本轮异常 %s", e)


config.register(
    name="add_reminder",
    desc=(
        "添加定时提醒。只传提醒内容与自然语言时间（如「两分钟后」），不要自己算 Unix 时间戳。"
        "若当前语音设备支持备忘录卡片，主控会优先改走设备 note.add；本工具为无卡片设备的兼容路径。"
    ),
    friendly_name="添加定时提醒",
    schema={
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "用户原话，例如：十分钟后提醒我开会。若与 content/remind_time_str 同时提供，以后者为准。",
            },
            "content": {
                "type": "string",
                "description": "提醒内容（事项），可与 remind_time_str 一起由 LLM 提取后传入。",
            },
            "remind_time_str": {
                "type": "string",
                "description": "提醒时间，自然语言，如：两分钟后、半小时后、明天上午9点、今晚8点。不要传 Unix 时间戳。",
            },
        },
        "required": [],
    },
    func=add_reminder,
)
