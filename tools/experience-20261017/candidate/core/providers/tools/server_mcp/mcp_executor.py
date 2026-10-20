"""服务端MCP工具执行器"""

import re
import traceback
from typing import Dict, Any, Optional, List, Union

from config.logger import setup_logging
from ..base import ToolType, ToolDefinition, ToolExecutor
from plugins_func.register import Action, ActionResponse
from .mcp_manager import ServerMCPManager

TAG = __name__
logger = setup_logging()

# ── display_hint 白名单：工具名关键词 → (icon FA Unicode, 标题, 状态) ──
# icon 字段必须为 Font Awesome Unicode 字面量，禁止 SVG / URL / data: URI
_DISPLAY_HINT_KEYWORD_MAP = [
    # (关键词列表,          icon,      标题)
    (["weather", "天气"],   "\uF185",  "天气预报"),
    (["stock", "股票"],     "\uF201",  "股票行情"),
    (["news", "新闻"],      "\uF1EA",  "最新资讯"),
    (["search", "搜索", "query", "find"], "\uF002", "搜索结果"),
    (["calendar", "日历", "schedule", "remind", "提醒"], "\uF073", "日程提醒"),
    (["music", "song", "音乐", "歌曲"],  "\uF001",  "音乐播放"),
    (["map", "location", "地图", "位置", "导航"], "\uF041", "位置信息"),
    (["translate", "翻译"], "\uF0AC",  "翻译结果"),
    (["timer", "countdown", "计时", "倒计时"], "\uF017", "计时器"),
    (["joke", "笑话", "story", "故事"], "\uF118",  "趣味内容"),
]

# 不附加 display_hint 的工具前缀（控制类工具）
_NO_DISPLAY_HINT_PREFIXES = [
    "restart", "reboot", "volume", "shutdown", "screenshot",
    "bind", "unbind", "exit", "quit",
]


def _is_retired_pc_tool(tool_name: str) -> bool:
    actual = tool_name[4:] if tool_name.startswith("mcp_") else tool_name
    return actual.startswith("pc_")


def _match_display_hint_meta(tool_name: str):
    """
    根据工具名匹配 display_hint 元数据（icon, title）。
    返回 (icon, title) 或 None（不需要展示）。
    """
    name_lower = tool_name.lower()

    # 控制类工具直接跳过
    for prefix in _NO_DISPLAY_HINT_PREFIXES:
        if name_lower.startswith(prefix):
            return None

    for keywords, icon, title in _DISPLAY_HINT_KEYWORD_MAP:
        for kw in keywords:
            if kw in name_lower:
                return icon, title

    return None


def _build_display_hint(tool_name: str, text: str) -> dict | None:
    """
    根据工具名和返回文本构造 display_hint payload。
    - 仅对白名单工具生成，其余返回 None。
    - items 截断为最多 4 条，title 截断为最多 16 字。
    - icon 仅使用 Font Awesome Unicode 字面量。
    """
    meta = _match_display_hint_meta(tool_name)
    if meta is None:
        return None

    icon, title = meta

    # 将文本按行拆分，过滤空行，最多取 4 条
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    items = lines[:4]  # 严格截断，不超过 4 条

    # 若解析后无有效内容，不附加 hint
    if not items:
        return None

    return {
        "icon": icon,
        "title": title[:16],          # title 最多 16 字
        "items": items,               # 已截断为 ≤4 条
        "status": "ok",
        "auto_dismiss_ms": 8000,
    }


# 匹配这些模式的工具结果视为"终态"，直接 Action.RESPONSE
# 注意：只保留真正不可能是多步任务中间步骤的模式
# "已打开""已按下组合键""已输入N字"等已移除，因为它们可能是多步任务的中间步骤
# 移除后这些结果默认走 REQLLM，LLM 会自行判断是否需要继续操作
_TERMINAL_PATTERNS = [
    re.compile(r"已将系统音量设置为"),
    re.compile(r"已写入\s"),
    re.compile(r"已尝试撤销"),
    re.compile(r"拖拽\s*\("),
    re.compile(r"已等待\s*[\d.]+\s*秒"),
]

# 匹配这些模式的工具结果需要 LLM 进一步决策
_REQLLM_PATTERNS = [
    re.compile(r"⚠️\s*多匹配需决策"),
    re.compile(r"需要视觉定位"),
    re.compile(r"找到多个匹配项"),
    re.compile(r"OCR 找到多个匹配项"),
    re.compile(r"ambiguous", re.IGNORECASE),
    re.compile(r"not_found_need_vlm", re.IGNORECASE),
    re.compile(r"VLM 分析结果"),
    re.compile(r"❌"),  # 错误结果也需要 LLM 判断下一步
    re.compile(r"执行失败"),
    re.compile(r"failed_at_step"),
]


# ── TTS 净化：对走 Action.RESPONSE 的结果，剥离不适合朗读的技术细节 ──
_TTS_STRIP_PATTERNS = [
    re.compile(r"\[前台窗口\].*$", re.MULTILINE),   # [前台窗口] xxx | [进程] xxx
    re.compile(r"\[进程\].*$", re.MULTILINE),        # 单独的 [进程] 行
    re.compile(r"https?://\S+"),                      # URL
    re.compile(r"✅\s*执行成功\s*\n?"),               # 冗余的"执行成功"前缀
    re.compile(r"已打开[:：]\s*https?://\S+"),        # "已打开: https://xxx" 整行
]


def _sanitize_for_tts(text: str) -> str:
    """
    对走 Action.RESPONSE 直接播报的文本做净化：
    剥离 URL、窗口信息、进程名等技术细节，只保留用户友好的摘要。
    """
    if not text:
        return text

    result = text
    for pat in _TTS_STRIP_PATTERNS:
        result = pat.sub("", result)

    # 清理多余空行和首尾空白
    lines = [line.strip() for line in result.split("\n") if line.strip()]
    result = "；".join(lines) if lines else ""

    # 如果净化后为空（比如只有 URL 和窗口信息），给一个兜底
    if not result:
        result = "操作已完成"

    return result


def _classify_tool_result(text: str) -> Action:
    """
    根据工具返回文本判断应该直接回复用户还是回灌 LLM。
    优先检查需要 LLM 决策的模式，再检查终态模式。
    默认回灌 LLM（保持向后兼容）。
    """
    if not text:
        return Action.REQLLM

    # 先检查是否需要 LLM 决策
    for pat in _REQLLM_PATTERNS:
        if pat.search(text):
            return Action.REQLLM

    # 再检查是否为终态
    for pat in _TERMINAL_PATTERNS:
        if pat.search(text):
            return Action.RESPONSE

    # 默认回灌 LLM
    return Action.REQLLM


def _mcp_content_item_type(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("type") or "")
    return str(getattr(item, "type", "") or "")


def _infer_openai_image_detail(text_blob: str) -> str:
    """根据成功文案中的分辨率推测 OpenAI image_url.detail。"""
    m = re.search(r"分辨率[：:]\s*(\d+)\s*[x×]\s*(\d+)", text_blob, re.IGNORECASE)
    if m:
        w, h = int(m.group(1)), int(m.group(2))
        if w * h > 1024 * 768:
            return "high"
    return "low"


def _extract_content_from_mcp_result(result: Any) -> Union[str, List[Dict[str, Any]]]:
    """
    从 MCP 返回结果提取内容：纯文本 str，或 OpenAI 多模态 content 数组（text + image_url）。
    支持 CallToolResult 对象及 dict 结构；兼容 type=text / type=image 的 MCP 块。
    """
    try:
        if hasattr(result, "content"):
            content = result.content if result.content is not None else []
        elif isinstance(result, dict):
            content = result.get("content", []) or []
        else:
            content = []

        text_parts: List[str] = []
        image_parts: List[Dict[str, Any]] = []

        for item in content if content else []:
            itype = _mcp_content_item_type(item)
            if itype == "text":
                t = item.get("text") if isinstance(item, dict) else getattr(item, "text", "")
                text_parts.append(str(t))
            elif itype == "image":
                b64 = item.get("data") if isinstance(item, dict) else getattr(item, "data", "")
                mime = (
                    item.get("mimeType")
                    if isinstance(item, dict)
                    else getattr(item, "mimeType", "image/jpeg")
                ) or "image/jpeg"
                if b64:
                    detail = _infer_openai_image_detail("\n".join(text_parts))
                    image_parts.append(
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime};base64,{b64}",
                                "detail": detail,
                            },
                        }
                    )
            else:
                if hasattr(item, "text"):
                    text_parts.append(str(item.text))
                elif isinstance(item, dict) and "text" in item:
                    text_parts.append(str(item["text"]))
                elif hasattr(item, "data") or (isinstance(item, dict) and item.get("data")):
                    b64 = item.get("data") if isinstance(item, dict) else getattr(item, "data", "")
                    mime = (
                        item.get("mimeType")
                        if isinstance(item, dict)
                        else getattr(item, "mimeType", "image/jpeg")
                    ) or "image/jpeg"
                    if b64:
                        detail = _infer_openai_image_detail("\n".join(text_parts))
                        image_parts.append(
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{mime};base64,{b64}",
                                    "detail": detail,
                                },
                            }
                        )

        joined = "\n".join(text_parts).strip()
        if not image_parts:
            return joined if joined else "工具返回结果为空"

        out: List[Dict[str, Any]] = []
        if joined:
            out.append({"type": "text", "text": joined})
        out.extend(image_parts)
        return out
    except Exception:
        traceback.print_exc()
        return "工具执行成功，但解析结果失败"


def tool_result_plain_text(result: Any) -> str:
    """将工具结果（str 或 OpenAI content 列表）转为纯文本，供 TTS / 摘要 / 正则匹配。"""
    if result is None:
        return ""
    if isinstance(result, str):
        return result
    if isinstance(result, list):
        lines = []
        for p in result:
            if isinstance(p, dict) and p.get("type") == "text":
                lines.append(str(p.get("text") or ""))
            elif isinstance(p, dict) and p.get("type") == "image_url":
                lines.append("[图片]")
        return "\n".join(lines).strip()
    return str(result)


def _extract_text_from_mcp_result(result: Any) -> str:
    """从 MCP CallToolResult 中提取纯文本（供绑定检测等字符串匹配场景）。"""
    extracted = _extract_content_from_mcp_result(result)
    return tool_result_plain_text(extracted)


class ServerMCPExecutor(ToolExecutor):
    """服务端MCP工具执行器"""

    def __init__(self, conn):
        self.conn = conn
        self.mcp_manager: Optional[ServerMCPManager] = None
        self._initialized = False

    async def initialize(self):
        """初始化MCP管理器"""
        if not self._initialized:
            self.mcp_manager = ServerMCPManager(self.conn)
            self._initialized = True
            await self.mcp_manager.initialize_servers()

    async def refresh_remote_tools(self) -> bool:
        """刷新所有远端 server_mcp 工具"""
        if not self._initialized or not self.mcp_manager:
            logger.bind(tag=TAG).warning("刷新 server_mcp 工具失败：MCP管理器未初始化")
            return False

        try:
            tool_count = await self.mcp_manager.refresh_all_tools()
            logger.bind(tag=TAG).info(
                f"server_mcp 远端工具刷新完成，当前可用 mcp 工具数: {tool_count}"
            )
            return True
        except Exception as e:
            logger.bind(tag=TAG).warning(f"刷新 server_mcp 远端工具失败: {e}")
            return False

    async def execute(
        self, conn, tool_name: str, arguments: Dict[str, Any]
    ) -> ActionResponse:
        """执行服务端MCP工具"""
        if not self._initialized or not self.mcp_manager:
            return ActionResponse(
                action=Action.ERROR,
                response="MCP管理器未初始化",
            )

        try:
            actual_tool_name = tool_name
            if tool_name.startswith("mcp_"):
                actual_tool_name = tool_name[4:]

            if _is_retired_pc_tool(actual_tool_name):
                return ActionResponse(
                    action=Action.ERROR,
                    response="电脑控制功能已下架，无法调用该工具。",
                )

            result = await self.mcp_manager.execute_tool(actual_tool_name, arguments)

            print(f"DEBUG: Server收到MCP响应: Type={type(result)}, Data={result}")

            # 提取多模态内容（文本 + 图片）
            extracted = _extract_content_from_mcp_result(result)

            # 提取纯文本用于字符串匹配
            final_text = tool_result_plain_text(extracted)
            is_error = result.get("isError", False) if isinstance(result, dict) else getattr(result, "isError", False)
            if is_error:
                return ActionResponse(action=Action.ERROR, result=extracted,
                    response="工具返回错误，这次没有取得有效结果。")
            print(f"DEBUG: 提取给 LLM 的最终文本: {final_text}")

            # 对工具结果做分级：终态结果直接回复，需决策的才回灌 LLM
            action = _classify_tool_result(final_text)
            logger.bind(tag=TAG).debug(
                f"工具 {actual_tool_name} 结果分级: {action.name}"
            )

            # 构造 display_hint（仅对白名单工具，控制类工具返回 None）
            display_hint = _build_display_hint(actual_tool_name, final_text)

            return ActionResponse(action=action, result=extracted, display_hint=display_hint)

        except ValueError as e:
            return ActionResponse(
                action=Action.NOTFOUND,
                response=str(e),
            )
        except Exception as e:
            return ActionResponse(
                action=Action.ERROR,
                response=str(e),
            )

    def get_tools(self) -> Dict[str, ToolDefinition]:
        """获取所有服务端MCP工具"""
        if not self._initialized or not self.mcp_manager:
            return {}

        tools = {}
        mcp_tools = self.mcp_manager.get_all_tools()

        for tool in mcp_tools:
            func_def = tool.get("function", {})
            tool_name = func_def.get("name", "")
            if tool_name == "" or _is_retired_pc_tool(tool_name):
                continue
            tools[tool_name] = ToolDefinition(
                name=tool_name, description=tool, tool_type=ToolType.SERVER_MCP
            )

        return tools

    def has_tool(self, tool_name: str) -> bool:
        """检查是否有指定的服务端MCP工具"""
        if not self._initialized or not self.mcp_manager:
            return False

        actual_tool_name = tool_name
        if tool_name.startswith("mcp_"):
            actual_tool_name = tool_name[4:]

        if _is_retired_pc_tool(actual_tool_name):
            return False

        return self.mcp_manager.is_mcp_tool(actual_tool_name)

    async def cleanup(self):
        """清理MCP连接"""
        if self.mcp_manager:
            await self.mcp_manager.cleanup_all()
