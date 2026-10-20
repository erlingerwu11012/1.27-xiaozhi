"""人脸录入启动：ASR 文本确定性路由（不进入闲聊/通用 intent LLM）。

受限语法（非整句包含匹配）：
  [礼貌/主语前缀]? [开始]? (录入|登记|添加) [一下]? 人脸 [吧|一下|吗|可以吗]?

前缀（最长优先）：可以帮我 / 请帮我 / 麻烦帮我 / 我想 / 我要 / 帮我 / 请 / 麻烦
排除词优先：取消、停止、不要、别、不想、删除、识别、看看我是谁、完成

兼容声纹 JSON 包装：{"speaker":"...","content":"录入人脸"}。
成功时不播报：由固件在 V2 session 创建成功后播放本地 START 引导音频。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

from config.logger import setup_logging

TAG = __name__
logger = setup_logging()

START_TOOL = "camera.face.enroll.start"
# 内部状态标记：不可朗读，禁止放入口语回复
ENROLL_STARTED_MARKER = "ENROLL_STARTED"

_TRAILING_PUNCT_RE = re.compile(r"[\s\u3000]+|[。．.！!？?；;，,、…~～]+$")

# 取消 / 停止 / 否定 / 删除 / 识别等：优先于启动匹配
_EXCLUDE_RE = re.compile(
    r"(取消|停止|不要|别|不想|删除|识别|看看我是谁|完成)"
)

# 受控前缀：按长度降序，避免「请」吞掉「请帮我」
_START_PREFIXES = (
    "可以帮我",
    "请帮我",
    "麻烦帮我",
    "我想",
    "我要",
    "帮我",
    "请",
    "麻烦",
)

# 核心：可选「开始」+ 动作 + 可选「一下」+ 必须「人脸」+ 可选语气后缀
_START_CORE_RE = re.compile(
    r"^(?:开始)?(?:(?:录入|登记|添加)(?:一下)?人脸|人脸(?:录入|登记))(?:吧|一下|吗|可以吗)?$"
)

_START_TOOL_ALIASES = frozenset(
    {
        "camera.face.enroll.start",
        "camera_face_enroll_start",
        "self.camera.face.enroll.start",
        "self_camera_face_enroll_start",
    }
)


class FaceEnrollStartResult(str, Enum):
    NOT_MATCHED = "not_matched"
    NO_CAPABILITY = "no_capability"
    TIMEOUT = "timeout"
    TOOL_ERROR = "tool_error"
    SUCCESS = "success"


@dataclass
class FaceEnrollStartResponse:
    result: FaceEnrollStartResult
    # 成功时为空：不得 speak_txt；失败时为安全用户可见短句
    message: str = ""


def is_face_enroll_start_tool(tool_name: str) -> bool:
    """判断工具名是否为人脸录入启动（兼容点号/下划线/self. 前缀）。"""
    name = (tool_name or "").strip()
    if not name:
        return False
    candidates = {
        name,
        name.replace(".", "_"),
        name.replace("_", "."),
    }
    if candidates & _START_TOOL_ALIASES:
        return True
    lowered = name.lower().replace("-", ".")
    # 宽松兜底：camera…face…enroll…start 顺序片段
    compact = lowered.replace("_", ".")
    return "face.enroll.start" in compact or "face_enroll_start" in lowered.replace(
        ".", "_"
    )


def extract_start_utterance(text: str) -> str:
    """从纯文本或声纹 JSON 包装中提取待匹配语句。

    仅当整段为严格 JSON object 且 content 为字符串时取 content；
    否则按原文处理。
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


def normalize_start_utterance(text: str) -> str:
    s = extract_start_utterance(text).strip()
    if not s:
        return ""
    prev = None
    while prev != s:
        prev = s
        s = _TRAILING_PUNCT_RE.sub("", s).strip()
    return s


def match_face_enroll_start(text: str) -> bool:
    """受限语法匹配启动录入意图；排除词优先；禁止孤立词命中。"""
    s = normalize_start_utterance(text)
    if not s:
        return False
    # 1) 排除词优先：取消/停止/否定/删除/识别等一律不命中
    if _EXCLUDE_RE.search(s):
        return False
    # 2) 剥离至多一个受控前缀（最长优先）
    rest = s
    for prefix in _START_PREFIXES:
        if rest.startswith(prefix):
            rest = rest[len(prefix) :]
            break
    if not rest:
        return False
    # 3) 核心必须整段贴合：动作 + 人脸（可选开始/一下/语气后缀）
    return _START_CORE_RE.fullmatch(rest) is not None


def _tool_available(mcp: Any) -> bool:
    names: set = set()
    tools = getattr(mcp, "available_tools", None) or {}
    if isinstance(tools, dict):
        names = set(tools.keys())
    has_tool = START_TOOL in names
    if not has_tool and hasattr(mcp, "has_tool"):
        try:
            has_tool = bool(mcp.has_tool(START_TOOL))
        except Exception:
            has_tool = False
    if not has_tool and hasattr(mcp, "resolve_tool_name"):
        try:
            has_tool = mcp.resolve_tool_name(START_TOOL) is not None
        except Exception:
            has_tool = False
    return bool(has_tool)


async def route_face_enroll_start(conn, text: str) -> FaceEnrollStartResponse:
    if not match_face_enroll_start(text):
        return FaceEnrollStartResponse(FaceEnrollStartResult.NOT_MATCHED)

    mcp = getattr(conn, "mcp_client", None)
    if mcp is None:
        logger.bind(tag=TAG).warning("[FACE_ENROLL] start_route no_mcp_client")
        return FaceEnrollStartResponse(
            FaceEnrollStartResult.NO_CAPABILITY,
            "暂时无法开始人脸录入，请稍后再试。",
        )

    if not _tool_available(mcp):
        logger.bind(tag=TAG).info("[FACE_ENROLL] start_route tool_unavailable")
        return FaceEnrollStartResponse(
            FaceEnrollStartResult.NO_CAPABILITY,
            "当前会话未开放人脸录入，请检查账号授权及设备工具同步。",
        )

    from core.providers.tools.device_mcp.mcp_handler import call_mcp_tool

    try:
        # 成功语义：call_mcp_tool 无异常返回（isError 会在 handler 内 raise）
        result = await call_mcp_tool(conn, mcp, START_TOOL, "{}", timeout=15)
        from core.utils.tool_result import require_enrollment_accepted
        accepted = require_enrollment_accepted(result)
        if not isinstance(getattr(conn, 'face_enrollment_operation', None), dict):
            conn.face_enrollment_operation = dict(accepted, state='accepted', session_id=getattr(conn, 'session_id', ''))
    except TimeoutError:
        logger.bind(tag=TAG).warning("[FACE_ENROLL] start_route timeout")
        return FaceEnrollStartResponse(
            FaceEnrollStartResult.TIMEOUT,
            "开始人脸录入超时，请稍后再试。",
        )
    except Exception as exc:
        logger.bind(tag=TAG).warning(
            f"[FACE_ENROLL] start_route error type={type(exc).__name__}"
        )
        return FaceEnrollStartResponse(
            FaceEnrollStartResult.TOOL_ERROR,
            getattr(exc, "user_message", "开始人脸录入失败，设备未提供明确原因。"),
        )

    logger.bind(tag=TAG).info("[FACE_ENROLL] start_route success silent")
    # message 为空：调用方不得 speak_txt；固件本地 START 独占播报
    return FaceEnrollStartResponse(FaceEnrollStartResult.SUCCESS, "")
