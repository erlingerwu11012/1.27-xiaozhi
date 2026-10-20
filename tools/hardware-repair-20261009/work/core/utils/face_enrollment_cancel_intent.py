"""人脸录入取消：ASR 文本确定性路由（不进入闲聊/通用 intent LLM）。

命中句：取消录入人脸 / 取消录入 / 停止录入人脸
可处理首尾空白与常见结尾标点；不宽泛匹配单独「取消」。
兼容声纹 JSON 包装：{"speaker":"...","content":"取消录入人脸"}。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

from config.logger import setup_logging

TAG = __name__
logger = setup_logging()

CANCEL_TOOL = "camera.face.enroll.cancel"

_TRAILING_PUNCT_RE = re.compile(r"[\s\u3000]+|[。．.！!？?；;，,、…~～]+$")
_EXACT_CANCEL = frozenset(
    {
        "取消录入人脸",
        "取消录入",
        "停止录入人脸",
    }
)


class FaceEnrollCancelResult(str, Enum):
    NOT_MATCHED = "not_matched"
    NO_CAPABILITY = "no_capability"
    TIMEOUT = "timeout"
    TOOL_ERROR = "tool_error"
    SUCCESS = "success"


@dataclass
class FaceEnrollCancelResponse:
    result: FaceEnrollCancelResult
    message: str = ""


def extract_cancel_utterance(text: str) -> str:
    """从纯文本或声纹 JSON 包装中提取待匹配语句。

    仅当整段为严格 JSON object 且 content 为字符串时取 content；
    否则按原文处理。不修改 startToChat 对普通对话的 JSON 处理。
    """
    raw = text if isinstance(text, str) else ""
    s = raw.strip()
    if s.startswith("{") and s.endswith("}"):
        try:
            data = json.loads(s)
        except (json.JSONDecodeError, TypeError, ValueError):
            return raw
        if isinstance(data, dict) and "content" in data:
            content = data.get("content")
            if isinstance(content, str):
                return content
            return ""
    return raw


def normalize_cancel_utterance(text: str) -> str:
    s = extract_cancel_utterance(text).strip()
    if not s:
        return ""
    # 反复剥常见结尾标点与空白
    prev = None
    while prev != s:
        prev = s
        s = _TRAILING_PUNCT_RE.sub("", s).strip()
    return s


def match_face_enroll_cancel(text: str) -> bool:
    """严格整句匹配；不匹配单独「取消」或提醒取消语句。"""
    return normalize_cancel_utterance(text) in _EXACT_CANCEL


async def route_face_enroll_cancel(conn, text: str) -> FaceEnrollCancelResponse:
    if not match_face_enroll_cancel(text):
        return FaceEnrollCancelResponse(FaceEnrollCancelResult.NOT_MATCHED)

    mcp = getattr(conn, "mcp_client", None)
    if mcp is None:
        logger.bind(tag=TAG).warning("[FACE_ENROLL] cancel_route no_mcp_client")
        return FaceEnrollCancelResponse(
            FaceEnrollCancelResult.NO_CAPABILITY,
            "暂时无法取消人脸录入，请稍后再试。",
        )

    names = set()
    tools = getattr(mcp, "available_tools", None) or {}
    if isinstance(tools, dict):
        names = set(tools.keys())
    # 也检查 resolve / raw 能力
    has_tool = CANCEL_TOOL in names
    if not has_tool and hasattr(mcp, "has_tool"):
        try:
            has_tool = bool(mcp.has_tool(CANCEL_TOOL))
        except Exception:
            has_tool = False
    if not has_tool and hasattr(mcp, "resolve_tool_name"):
        try:
            has_tool = mcp.resolve_tool_name(CANCEL_TOOL) is not None
        except Exception:
            has_tool = False

    if not has_tool:
        logger.bind(tag=TAG).info("[FACE_ENROLL] cancel_route tool_unavailable")
        return FaceEnrollCancelResponse(
            FaceEnrollCancelResult.NO_CAPABILITY,
            "当前设备不支持取消人脸录入。",
        )

    from core.providers.tools.device_mcp.mcp_handler import call_mcp_tool

    try:
        result = await call_mcp_tool(conn, mcp, CANCEL_TOOL, "{}", timeout=15)
    except TimeoutError:
        logger.bind(tag=TAG).warning("[FACE_ENROLL] cancel_route timeout")
        return FaceEnrollCancelResponse(
            FaceEnrollCancelResult.TIMEOUT,
            "取消人脸录入超时，请稍后再试。",
        )
    except Exception as exc:
        logger.bind(tag=TAG).warning(
            f"[FACE_ENROLL] cancel_route error type={type(exc).__name__}"
        )
        return FaceEnrollCancelResponse(
            FaceEnrollCancelResult.TOOL_ERROR,
            "取消人脸录入失败，请稍后再试。",
        )

    if isinstance(result, dict) and result.get("isError"):
        logger.bind(tag=TAG).warning("[FACE_ENROLL] cancel_route tool_error")
        return FaceEnrollCancelResponse(
            FaceEnrollCancelResult.TOOL_ERROR,
            "取消人脸录入失败，请稍后再试。",
        )

    logger.bind(tag=TAG).info("[FACE_ENROLL] cancel_route success")
    return FaceEnrollCancelResponse(
        FaceEnrollCancelResult.SUCCESS,
        "好的，已取消人脸录入。",
    )
