# 文件路径: tools/registry.py
"""
通用工具注册表：存储 func_name、callable_func、friendly_name、desc、schema。
供 executor 做前置 TTS 播报与入口统一分发；与 core.config 协同，list_tools 仍从 config.mcp_tools 读取。
"""
from typing import Any, Callable, Dict, Optional


class ToolRegistry:
    """工具注册表：name -> {func, desc, schema, friendly_name}。"""

    def __init__(self) -> None:
        self._tools: Dict[str, Dict[str, Any]] = {}

    def register(
        self,
        name: str,
        desc: str,
        schema: dict,
        func: Callable,
        friendly_name: Optional[str] = None,
    ) -> None:
        """
        :param name: 工具名称 (如 add_reminder)
        :param desc: 工具描述 (给大模型看的)
        :param schema: 参数定义 (JSON Schema)
        :param func: 实际执行的 Python 函数 (async callable)
        :param friendly_name: 播报用中文名 (如「添加定时提醒」)，未传则用 __tool_meta__.title 或 name
        """
        meta = getattr(func, "__tool_meta__", None) if func else None
        title = (meta.get("title") if meta else None) or name
        self._tools[name] = {
            "func": func,
            "desc": desc,
            "schema": schema,
            "friendly_name": (friendly_name or title or name).strip(),
        }

    def get(self, name: str) -> Optional[Dict[str, Any]]:
        return self._tools.get(name)

    def get_all(self) -> Dict[str, Dict[str, Any]]:
        return dict(self._tools)


# 单例，供 core.config 与 core.executor 使用
registry = ToolRegistry()
