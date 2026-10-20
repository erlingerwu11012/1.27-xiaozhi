# 文件路径: core/executor.py
"""
通用工具执行器：前置 TTS 播报 + 统一分发 + 后置大数据缓存（Context Data Bus）。
"""
import json
import logging
import os
import uuid
import asyncio
from pathlib import Path
from typing import Any, Dict, Optional, Union

import httpx

from core.config import config

logger = logging.getLogger(__name__)

# TTS 广播接口（与 reminder_tool 一致，可 env 覆盖）
EXECUTOR_TTS_URL = os.environ.get(
    "REMINDER_TTS_URL",
    "http://127.0.0.1:8006/api/v1/broadcast",
)
# 超过该长度或为 List/Dict 时写入文件并返回引用
DATA_REF_THRESHOLD = int(os.environ.get("MCP_DATA_REF_THRESHOLD", "500"))
# 默认持久化目录；优先使用环境变量 MCP_CONTEXT_DIR
_DEFAULT_MCP_CONTEXT_DIR = "/root/prjs/xiaozhi_mcp_gateway/mcp_context"
MCP_CONTEXT_DIR = Path(os.environ.get("MCP_CONTEXT_DIR", _DEFAULT_MCP_CONTEXT_DIR))


class DataManager:
    """上下文数据总线：将大数据写入本地文件，返回 data_ref_id（文件绝对路径）供下游工具读取。"""

    def __init__(self, root_dir: Optional[Union[str, Path]] = None) -> None:
        self.root = Path(root_dir or MCP_CONTEXT_DIR)
        os.makedirs(self.root, exist_ok=True)

    def save(self, data: Any, suffix: str = "json") -> str:
        """
        将 data 序列化为文件，返回文件绝对路径。
        - 若 data 为 str，按 UTF-8 写入 .txt；若为 list/dict，写入 .json。
        - 写入时记录日志，便于后续手动清理旧数据。
        """
        fid = str(uuid.uuid4())[:8]
        if isinstance(data, (list, dict)):
            path = self.root / f"{fid}.json"
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        else:
            ext = "json" if isinstance(data, str) and data.strip().startswith("{") else "txt"
            path = self.root / f"{fid}.{ext}"
            with open(path, "w", encoding="utf-8") as f:
                f.write(data)
        abs_path = str(path.resolve())
        logger.info("DataManager: 已写入上下文文件 %s（持久化目录，可定期手动清理旧文件）", abs_path)
        return abs_path

    @staticmethod
    def is_large_or_structured(result: Any) -> bool:
        """是否应对结果做“输出拦截”：超长字符串或 List/Dict。"""
        if isinstance(result, dict) and "content" in result:
            return False  # MCP 标准格式，不透传大数据逻辑
        if isinstance(result, (list, dict)):
            return True
        if isinstance(result, str) and len(result) > DATA_REF_THRESHOLD:
            return True
        return False


_data_manager: Optional[DataManager] = None


def _get_data_manager() -> DataManager:
    global _data_manager
    if _data_manager is None:
        _data_manager = DataManager()
    return _data_manager


async def _fire_tts(text: str) -> None:
    """异步向 TTS 接口发送播报，不阻塞；失败仅打日志。"""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(EXECUTOR_TTS_URL, json={"text": text})
    except Exception as e:
        logger.warning("executor: TTS 播报失败（不影响工具执行）: %s", e)


def _build_ref_response(data_ref_id: str, summary: str = "数据已缓存，请将此路径传给下一个工具") -> str:
    """构造给 LLM 的轻量引用对象字符串。"""
    ref = {
        "status": "success",
        "data_ref_id": data_ref_id,
        "summary": summary,
    }
    return json.dumps(ref, ensure_ascii=False)


async def execute_tool(tool_name: str, **kwargs: Any) -> str:
    """
    通用工具执行入口：
    1. Execution：合并 internal_config 后 await tool_func(**kwargs)
    2. Post：若返回大数据或 List/Dict，写入 DataManager，仅返回 data_ref_id 引用给 LLM
    """
    if str(tool_name).startswith("pc_"):
        from tools.mcp_utils import mcp_error
        return mcp_error("电脑控制功能已下架，无法调用该工具。")

    from tools.registry import registry
    info = registry.get(tool_name) or config.mcp_tools.get(tool_name)
    if not info:
        from tools.mcp_utils import mcp_error
        return mcp_error(f"未知工具: {tool_name}")

    func = info.get("func")

    # Pre-execution TTS 已移除：工具执行快，插播「正在为您xxx，请稍等...」会延迟到达并打断 LLM 真实答案流

    # Execution
    args = _merge_internal_args(tool_name, kwargs)
    print(f"DEBUG: executor 准备调用 {tool_name}，合并后参数: {args}")
    try:
        result = await func(**args)
        print(f"DEBUG: executor {tool_name} 执行完成，结果类型: {type(result).__name__}")
    except TypeError as e:
        logger.exception("executor: 工具 %s 参数不匹配 (TypeError)", tool_name)
        from tools.mcp_utils import mcp_error
        return mcp_error(f"工具参数不匹配: {e}")
    except Exception as e:
        logger.exception("executor: 工具 %s 执行异常", tool_name)
        from tools.mcp_utils import mcp_error
        return mcp_error(str(e))

    # Post-execution: MCP 格式透传 / 大数据拦截 / 普通序列化
    if isinstance(result, dict) and "content" in result:
        return result  # 已是 MCP 标准格式，直接返回给 server 封装
    if DataManager.is_large_or_structured(result):
        dm = _get_data_manager()
        data_ref_id = dm.save(result)
        return _build_ref_response(data_ref_id)
    return result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)


# 常见参数别名：大模型或不同客户端可能使用不同 key，统一映射到 schema 定义
_PARAM_ALIASES = {
    "calculator": {"expr": "expression", "formula": "expression", "code": "expression"},
}


def _merge_internal_args(tool_name: str, arguments: dict) -> dict:
    """与 server 中逻辑一致：用户传入优先，未传的配置项从 internal_config 补全；支持参数别名。"""
    args = dict(arguments or {})
    tool_info = config.mcp_tools.get(tool_name)
    if not tool_info:
        return args
    schema = tool_info.get("schema") or {}
    props = schema.get("properties") or {}
    # 参数别名：将 expr/formula/code 等映射到 expression
    aliases = _PARAM_ALIASES.get(tool_name, {})
    for alias_key, canonical_key in aliases.items():
        if alias_key in args and canonical_key not in args:
            args[canonical_key] = args.pop(alias_key)
    internal = config.internal_config.get(tool_name) or {}
    for param_name in props:
        if param_name not in args and param_name in internal and internal[param_name]:
            args[param_name] = internal[param_name]
    return args
