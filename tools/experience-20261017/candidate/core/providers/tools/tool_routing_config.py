"""工具路由配置读取与行为短指令。"""

from __future__ import annotations

from typing import Any, Dict, Optional

DEFAULT_TOOL_BEHAVIOR_PROMPT = (
    "用户明确要求执行当前工具支持的操作且参数充分时，请发起工具调用，不要只口头答应。"
    "参数不足或目标有歧义时先澄清。否定、假设、引用和介绍性提问不是执行请求。"
    "仅依据真实工具回执描述结果；未执行或失败不得声称完成。"
)


def get_tool_routing_config(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    raw = (config or {}).get("tool_routing") or {}
    if not isinstance(raw, dict):
        raw = {}
    return {
        "mode": str(raw.get("mode") or "off"),  # off | shadow | enabled
        "profile": str(raw.get("profile") or "voice_default"),
        "soft_candidate_target": int(raw.get("soft_candidate_target") or 12),
        "selector_budget_ms": float(raw.get("selector_budget_ms") or 20),
        "fallback": str(raw.get("fallback") or "eligible_all"),
        "policy_version": str(raw.get("policy_version") or "v1"),
        "policy_path": raw.get("policy_path"),
    }


def get_tool_behavior_prompt_config(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    raw = (config or {}).get("tool_behavior_prompt") or {}
    if not isinstance(raw, dict):
        raw = {}
    return {
        "enabled": bool(raw.get("enabled") or False),
        "text": str(raw.get("text") or DEFAULT_TOOL_BEHAVIOR_PROMPT),
    }


def get_native_fc_only_config(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    raw = (config or {}).get("native_fc_only") or {}
    if not isinstance(raw, dict):
        raw = {}
    return {
        "enabled": bool(raw.get("enabled") or False),
        # 新连接才建议开启；由上层按连接创建时读取
        "reject_text_tool_call": bool(raw.get("reject_text_tool_call", True)),
        "migrate_voice_direct_routes": bool(
            raw.get("migrate_voice_direct_routes") or False
        ),
    }
