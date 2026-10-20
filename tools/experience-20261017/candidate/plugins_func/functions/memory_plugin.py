"""
长期记忆查询工具：注册为 LLM Function Calling 工具。
前台对话中，当模型需要回忆用户信息时调用。
"""
from plugins_func.register import register_function, ToolType, ActionResponse, Action
from config.logger import setup_logging

TAG = __name__
logger = setup_logging()

query_memory_function_desc = {
    "type": "function",
    "function": {
        "name": "query_memory",
        "description": (
            "查询用户的长期记忆。当用户问及个人背景、历史偏好、"
            "之前提到过的人或事时调用。返回最相关的记忆事实。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "搜索关键词，如'猫'、'工作'、'喜欢'、'名字'",
                }
            },
            "required": ["keyword"],
        },
    },
}


@register_function("query_memory", query_memory_function_desc, ToolType.SYSTEM_CTL)
def query_memory(conn, keyword: str = ""):
    """查询用户长期记忆，返回结果回灌 LLM 生成自然语言回答。"""
    device_id = getattr(conn, "device_id", None) or ""
    if not device_id:
        logger.bind(tag=TAG).warning("query_memory: 无法获取 device_id")
        return ActionResponse(Action.REQLLM, "无法识别当前设备。")

    if not keyword or not keyword.strip():
        return ActionResponse(Action.REQLLM, "没有提供搜索关键词。")

    keyword = keyword.strip()
    logger.bind(tag=TAG).info(f"查询记忆: device={device_id} keyword={keyword}")

    try:
        from core.utils.db_memory import search_memory
        results = search_memory(device_id, keyword, limit=3)
    except Exception as e:
        logger.bind(tag=TAG).error(f"查询记忆失败: {e}")
        return ActionResponse(Action.REQLLM, "记忆查询出错。")

    if not results:
        return ActionResponse(Action.REQLLM, "没有找到相关记忆。")

    text = "\n".join(f"- [{r['category']}] {r['fact']}" for r in results)
    return ActionResponse(Action.REQLLM, f"用户的相关记忆:\n{text}")
