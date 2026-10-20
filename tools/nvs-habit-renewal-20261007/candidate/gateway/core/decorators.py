# 文件路径: core/decorators.py
"""工具元信息装饰器，用于在工具函数上声明中文标题、是否隐藏等，供 /list-tools 动态读取。"""


def tool_meta(title=None, hidden=False):
    """
    装饰器：将 title（中文标题）和 hidden（是否隐藏）绑定到被装饰函数的 __tool_meta__ 属性。
    :param title: 简短中文标题，供 /list-tools 返回，前端直接展示。
    :param hidden: 是否在 /list-tools 中隐藏该工具，默认 False。
    """
    def decorator(func):
        func.__tool_meta__ = {"title": title, "hidden": bool(hidden)}
        return func
    return decorator
