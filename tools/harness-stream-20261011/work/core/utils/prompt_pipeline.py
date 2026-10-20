"""v2 提示词管线配置读取与观测哈希。

所有开关默认关闭（v1 行为不变）。仅提供纯函数读取，不做任何 I/O，
避免在 LLM 调用链路上引入副作用。

配置来源（API 模式经 LOCAL_ONLY_TOP_LEVEL_KEYS 下发）：
- prompt_pipeline: { version }  # version=v2 即全量生效，不再按设备白名单灰度
- speech_expression: { mode }  # 旧 finalization 字段忽略，不再有二次润色
- llm_observability: { include_stream_usage }
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, List, Optional

DEFAULT_VERSION = "v1"


def _cfg(conn) -> dict:
    c = getattr(conn, "config", None)
    if isinstance(c, dict):
        return c
    return {}


def prompt_pipeline_config(conn) -> dict:
    c = _cfg(conn).get("prompt_pipeline")
    if isinstance(c, dict):
        return c
    return {}


def speech_expression_config(conn) -> dict:
    c = _cfg(conn).get("speech_expression")
    if isinstance(c, dict):
        return c
    return {}


def llm_observability_config(conn) -> dict:
    c = _cfg(conn).get("llm_observability")
    if isinstance(c, dict):
        return c
    return {}


def prompt_pipeline_version(conn) -> str:
    v = prompt_pipeline_config(conn).get("version")
    if v:
        return str(v)
    return DEFAULT_VERSION


def is_pipeline_v2(conn) -> bool:
    frozen = getattr(conn, "_pipeline_v2_frozen", None)
    if frozen is not None:
        return bool(frozen)
    # V2 全量：只要 version == "v2" 即对所有设备生效，不再按 rollout_device_ids 灰度。
    # 配置缺失时保持 fail-closed（返回 False）。
    result = prompt_pipeline_config(conn).get("version") == "v2"
    try:
        conn._pipeline_v2_frozen = bool(result)
    except Exception:
        pass
    return bool(result)




def expression_mode(conn) -> str:
    mode = speech_expression_config(conn).get("mode")
    if mode:
        return str(mode)
    return "llm_optional"


def include_stream_usage(conn) -> bool:
    return bool(llm_observability_config(conn).get("include_stream_usage", False))


def hash_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(str(value).encode("utf-8")).hexdigest()[:12]


def system_hash(messages: Optional[List[dict]]) -> str:
    if not messages:
        return ""
    first_system = None
    for m in messages:
        if isinstance(m, dict) and m.get("role") == "system":
            first_system = m
            break
    if first_system is None:
        return ""
    content = first_system.get("content")
    if isinstance(content, list):
        texts = [
            str(p.get("text") or "")
            for p in content
            if isinstance(p, dict) and p.get("type") == "text"
        ]
        content = "\n".join(texts)
    return hash_text(content)


def tools_hash(functions: Any) -> str:
    if functions is None:
        return ""
    return hash_text(functions)


def request_kind(depth: int) -> str:
    if depth == 0:
        return "first"
    return "tool_continuation"
