# 文件路径: tools/habit_tool.py
"""
手动习惯管理工具 + 调度器。

功能：
1. habit_create  — MCP 工具，创建手动习惯，写入 sys_habits 表
2. 网页习惯由管理 API 负责账号授权
3. habit_sync_loop — 后台调度器（每 60s）：
   - 将待同步记录 ID 提交到带 Bearer 认证的私有同步入口
   - 不承担定时提醒、鼓励语、TTS 广播或 UI 弹窗
"""
import os
import re
import json
import asyncio
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any

import aiomysql
import httpx

from core.config import config
from core.db_config import DB_HOST, DB_NAME, DB_PASSWORD, DB_PORT, DB_USER
from core.decorators import tool_meta
from tools.mcp_utils import mcp_result, mcp_error

logger = logging.getLogger(__name__)

# TTS 广播接口（与 reminder_tool.py 共用同一环境变量）
REMINDER_TTS_URL = os.environ.get(
    "REMINDER_TTS_URL",
    "http://127.0.0.1:8006/api/v1/broadcast",
)
# 设备 JSON 消息推送接口
DEVICE_SEND_URL = os.environ.get(
    "DEVICE_SEND_URL",
    "http://127.0.0.1:8006/api/v1/device/send",
)

_pool: Optional[aiomysql.Pool] = None
_pool_lock = asyncio.Lock()

# 记录已触发提醒的习惯（避免同一分钟重复触发）：{habit_id: "YYYY-MM-DD HH:MM"}
_reminded_cache: Dict[int, str] = {}


# ---------------------------------------------------------------------------
# 数据库连接池
# ---------------------------------------------------------------------------

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
            logger.info("habit_tool: MySQL 连接池已创建 %s@%s", DB_USER, DB_HOST)
        return _pool


async def _sync_habit_to_device(habit: dict) -> bool:
    secret = os.environ.get("HABIT_SERVICE_SECRET", "").strip()
    if not secret:
        try:
            secret = Path(os.environ.get("HABIT_SERVICE_SECRET_FILE", "/root/prjs/xiaozhi-esp32-server/secrets/habit-service-secret")).read_text().strip()
        except OSError:
            pass
    if not secret:
        logger.error("habit_tool: service_auth_unconfigured")
        return False
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(os.environ.get("HABIT_SYNC_URL", "http://127.0.0.1:8006/api/v1/habit/sync"),
                headers={"Authorization": "Bearer " + secret}, json={"habit_id": int(habit["id"])})
            body = r.json() if r.status_code == 200 else {}
            ok = body.get("ok") is True and body.get("sync_state") == "synced" and body.get("sync_id") == str(habit["id"]) and isinstance(body.get("content_hash"), str) and len(body["content_hash"]) == 64 and type(body.get("device_rule_id")) is int
            logger.info("habit_tool: sync id=%s state=%s reason=%s", habit["id"], body.get("sync_state", "pending"), body.get("error") or ("ok" if ok else "http_"+str(r.status_code)))
            return ok
    except Exception as exc:
        logger.warning("habit_tool: sync id=%s error_type=%s", habit["id"], type(exc).__name__)
        return False


# ---------------------------------------------------------------------------
# MCP 工具：habit_create
# ---------------------------------------------------------------------------

@tool_meta(title="创建手动习惯")
async def habit_create(
    description: str = "",
    hour: int = 8,
    minute: int = 0,
    advance_minutes: int = 2,
    intent: str = "",
    device_id: str = "",
    **kwargs,
) -> str:
    """
    创建一条手动习惯提醒。
    description: 习惯中文描述，如"喝水"、"冥想"
    hour: 每天触发小时（0-23）
    minute: 每天触发分钟（0-59）
    advance_minutes: 提前提醒分钟数（默认2）
    intent: 英文意图标签（可选，自动从 description 生成）
    device_id: 目标设备ID；禁止跨账号广播
    """
    return mcp_error("该网页习惯入口需要账号授权，不能根据模型参数猜测账号。语音创建请使用当前设备的 habit.learn；网页创建请明确选择设备和接收人。")


# ---------------------------------------------------------------------------
# MCP 工具：habit_list_manual
# ---------------------------------------------------------------------------

@tool_meta(title="查询手动习惯列表")
async def habit_list_manual(
    enabled_only: bool = True,
    **kwargs,
) -> str:
    """
    查询手动创建的习惯列表。
    enabled_only: 是否只返回启用的习惯（默认 True）
    """
    return mcp_error("请使用当前设备的 habit.list，或在网页查看当前账号的习惯；不支持跨账号查询。")


# ---------------------------------------------------------------------------
# 后台调度器
# ---------------------------------------------------------------------------

async def habit_scheduler_loop() -> None:
    logger.info("habit_tool: authenticated background sync started; reminders are device-owned")
    while True:
        try:
            await _run_sync_task()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("habit_tool: cycle error_type=%s",type(exc).__name__)
        await asyncio.sleep(60)


async def _run_sync_task() -> None:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT id FROM sys_habits WHERE source='manual' AND synced=0 AND sync_state<>'needs_binding' ORDER BY id")
            rows = await cur.fetchall()
    for row in rows:
        # Only the manager's version/hash-checked receipt handler changes synced.
        await _sync_habit_to_device(row)


# ---------------------------------------------------------------------------
# 注册 MCP 工具
# ---------------------------------------------------------------------------

config.register(
    name="habit_create",
    desc=(
        "创建一条手动习惯提醒。用户可指定习惯名称（description）、"
        "每天触发时间（hour/minute）和提前提醒分钟数（advance_minutes）。"
        "此网关入口无账号授权；语音使用设备 habit.learn，网页使用账号绑定入口。"
    ),
    friendly_name="创建手动习惯",
    schema={
        "type": "object",
        "properties": {
            "description": {
                "type": "string",
                "description": "习惯中文描述，如：喝水、冥想、运动",
            },
            "hour": {
                "type": "integer",
                "description": "每天触发小时，0-23",
            },
            "minute": {
                "type": "integer",
                "description": "每天触发分钟，0-59，默认0",
            },
            "advance_minutes": {
                "type": "integer",
                "description": "提前提醒分钟数，默认2",
            },
            "intent": {
                "type": "string",
                "description": "英文意图标签（可选，如 drink_water），不填则自动生成",
            },
            "device_id": {
                "type": "string",
                "description": "目标设备ID；网页创建必须绑定当前账号所属设备",
            },
        },
        "required": ["description", "hour"],
    },
    func=habit_create,
)

config.register(
    name="habit_list_manual",
    desc="查询用户手动创建的习惯列表，返回所有启用中的手动习惯。",
    friendly_name="查询手动习惯列表",
    schema={
        "type": "object",
        "properties": {
            "enabled_only": {
                "type": "boolean",
                "description": "是否只返回启用的习惯，默认 true",
            },
        },
        "required": [],
    },
    func=habit_list_manual,
)
