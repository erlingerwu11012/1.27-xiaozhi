"""
后台异步记忆提取器：会话结束后调用廉价 LLM 从对话中提取高价值事实。
在 daemon 线程中运行，不阻塞主对话流程。
"""
import json
import os
from typing import List, Dict, Any

from config.logger import setup_logging

TAG = __name__
logger = setup_logging()

# 后台提取 LLM 的 Prompt
MEMORY_EXTRACTION_PROMPT = """你是一个精密的记忆整理员。请从这段对话中提取"高价值、长久有效"的事实。

规则：
1. 仅提取：身份信息、个人偏好、重要关系、工作背景、长期习惯。
2. 忽略：日常寒暄、临时任务、情绪发泄、天气查询、时间查询等。
3. 每条事实必须是精简的陈述句，如"用户名叫张三"、"用户喜欢喝冰美式"。
4. 如果对话中包含对旧信息的修正（如职业变更），以最新信息为准。
5. 如果对话中没有任何值得记忆的信息，返回空数组。

输出格式（严格 JSON 数组，无则返回 []）：
[
  {"category": "personal", "fact": "用户名叫张三"},
  {"category": "preference", "fact": "用户喜欢喝冰美式"}
]

category 可选值：personal, preference, work, relationship, general"""


def _get_extract_config() -> Dict[str, Any]:
    """从服务端配置中读取记忆提取模型参数。
    sys_params 中的 memory_extract.* 会被 Java 后端按 '.' 分层嵌套为：
    {"memory_extract": {"enabled": true, "base_url": "...", "api_key": "...", "model": "..."}}
    """
    try:
        from config.manage_api_client import get_server_config
        config = get_server_config() or {}
        me = config.get("memory_extract", {})
        if isinstance(me, str):
            me = {}
        return {
            "enabled": str(me.get("enabled", "true")).lower() in ("true", "1"),
            "base_url": str(me.get("base_url", "") or "").strip(),
            "api_key": str(me.get("api_key", "") or "").strip(),
            "model": str(me.get("model", "deepseek-chat") or "deepseek-chat").strip(),
        }
    except Exception as e:
        logger.bind(tag=TAG).warning(f"读取记忆提取配置失败，使用默认值: {e}")
        return {"enabled": False, "base_url": "", "api_key": "", "model": ""}


def _dialogue_to_text(dialogue: List[Dict]) -> str:
    """将对话列表转为纯文本（只取 user 和 assistant）。"""
    lines = []
    for msg in dialogue:
        role = msg.get("role", "")
        if role not in ("user", "assistant"):
            continue
        content = msg.get("content", "")
        if isinstance(content, list):
            # 多模态消息，只取文本部分
            texts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
            content = " ".join(texts)
        if content and isinstance(content, str):
            prefix = "用户" if role == "user" else "助手"
            lines.append(f"{prefix}: {content.strip()}")
    return "\n".join(lines)


def _call_llm_sync(config: Dict, dialogue_text: str) -> str:
    """同步调用 LLM API（在后台线程中运行）。"""
    import httpx

    base_url = config["base_url"].rstrip("/")
    headers = {
        "Authorization": f"Bearer {config['api_key']}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": config["model"],
        "messages": [
            {"role": "system", "content": MEMORY_EXTRACTION_PROMPT},
            {"role": "user", "content": dialogue_text},
        ],
        "temperature": 0.1,
        "max_tokens": 500,
    }

    with httpx.Client(timeout=30) as client:
        resp = client.post(f"{base_url}/chat/completions", headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()


def _parse_facts(response_text: str) -> List[Dict]:
    """从 LLM 响应中解析 JSON 事实数组。"""
    # 尝试直接解析
    text = response_text.strip()
    # 去掉可能的 markdown 代码块
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        text = text.strip()

    try:
        facts = json.loads(text)
        if isinstance(facts, list):
            return [
                f for f in facts
                if isinstance(f, dict) and f.get("fact") and f.get("category")
            ]
    except (json.JSONDecodeError, TypeError):
        pass

    # 尝试从文本中提取 JSON 数组
    import re
    m = re.search(r'\[.*\]', text, re.DOTALL)
    if m:
        try:
            facts = json.loads(m.group())
            if isinstance(facts, list):
                return [
                    f for f in facts
                    if isinstance(f, dict) and f.get("fact") and f.get("category")
                ]
        except (json.JSONDecodeError, TypeError):
            pass

    return []


def extract_and_save_memories(device_id: str, dialogue: List[Dict]):
    """
    主入口：从对话中提取记忆并保存到 SQLite。
    在 daemon 线程中调用，不阻塞主流程。
    """
    # 1. 读取配置
    config = _get_extract_config()
    if not config["enabled"]:
        logger.bind(tag=TAG).debug("记忆提取已禁用，跳过")
        return
    if not config["api_key"]:
        logger.bind(tag=TAG).debug("记忆提取 API Key 未配置，跳过")
        return

    # 2. 对话转文本
    text = _dialogue_to_text(dialogue)
    if len(text) < 50:
        logger.bind(tag=TAG).debug("对话太短，不值得提取记忆")
        return

    # 3. 调用 LLM 提取
    logger.bind(tag=TAG).info(f"开始提取记忆 device={device_id} 对话长度={len(text)}字")
    try:
        response = _call_llm_sync(config, text)
    except Exception as e:
        logger.bind(tag=TAG).error(f"调用记忆提取 LLM 失败: {e}")
        return

    # 4. 解析事实
    facts = _parse_facts(response)
    if not facts:
        logger.bind(tag=TAG).debug("未从对话中提取到有价值的记忆")
        return

    # 5. 写入 SQLite
    from core.utils.db_memory import upsert_memory
    saved = 0
    for item in facts:
        if upsert_memory(device_id, item["category"], item["fact"]):
            saved += 1
    logger.bind(tag=TAG).info(f"记忆提取完成: 提取 {len(facts)} 条，保存 {saved} 条")
