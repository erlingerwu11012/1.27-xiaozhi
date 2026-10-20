# 文件路径: tools/builtin.py
from core.config import config
from tools.mcp_utils import mcp_result


async def _mcp_response_placeholder(**kwargs):
    """硬件回传占位符，返回 MCP 标准格式。"""
    return mcp_result("OK")


# 注册硬件回传占位符
config.register("mcp_response_tool", "硬件回传", {}, _mcp_response_placeholder)