# 文件路径: tools/mcp_utils.py
"""
MCP 协议标准返回值封装。所有工具必须使用此模块统一返回格式，避免协议解析失败导致服务器卡死。
"""
from typing import Any


def mcp_result(text: str, is_error: bool = False) -> dict:
    """
    将工具结果封装为标准 MCP 格式。
    :param text: 文本内容（确保为字符串）
    :param is_error: 是否为错误响应
    :return: {"content": [{"type": "text", "text": str}], "isError": bool}
    """
    return {
        "content": [{"type": "text", "text": str(text)}],
        "isError": is_error,
    }


def mcp_error(message: str) -> dict:
    """封装错误响应为标准 MCP 格式。"""
    return mcp_result(str(message), is_error=True)
