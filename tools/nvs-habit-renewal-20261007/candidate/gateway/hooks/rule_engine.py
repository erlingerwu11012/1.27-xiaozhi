"""
PreToolUse 规则引擎：在工具执行前，根据 rules.yaml 中的规则进行拦截或警告。
借鉴 Claude Code hookify 插件的 rule_engine 模式。
"""
import os
import re
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# 规则文件路径
_RULES_FILE = Path(__file__).parent / "rules.yaml"
_rules_cache: Optional[list] = None
_rules_mtime: float = 0


@lru_cache(maxsize=128)
def _compile_regex(pattern: str) -> re.Pattern:
    """缓存编译后的正则表达式。"""
    return re.compile(pattern, re.IGNORECASE)


def _load_rules() -> list[dict]:
    """加载并缓存规则文件（文件变更时自动重新加载）。"""
    global _rules_cache, _rules_mtime

    if not _RULES_FILE.exists():
        return []

    mtime = _RULES_FILE.stat().st_mtime
    if _rules_cache is not None and mtime == _rules_mtime:
        return _rules_cache

    try:
        # 简易 YAML 解析（避免强依赖 pyyaml）
        import yaml
        raw = _RULES_FILE.read_text(encoding="utf-8")
        data = yaml.safe_load(raw) or {}
        _rules_cache = data.get("rules", [])
        _rules_mtime = mtime
        logger.info(f"📏 已加载 {len(_rules_cache)} 条安全规则")
        return _rules_cache
    except ImportError:
        logger.warning("pyyaml 未安装，规则引擎不可用。建议: pip install pyyaml")
        _rules_cache = []
        return []
    except Exception as e:
        logger.error(f"加载规则文件失败: {e}")
        _rules_cache = []
        return []


def _match_tool(tool_matcher: str, tool_name: str) -> bool:
    """检查工具名是否匹配规则的 tool_matcher（支持 | 分隔和 * 通配）。"""
    if tool_matcher == "*":
        return True
    patterns = [p.strip() for p in tool_matcher.split("|")]
    return tool_name in patterns


def _extract_field(args: dict, field: str) -> str:
    """从工具参数中提取指定字段的值。"""
    val = args.get(field, "")
    if isinstance(val, str):
        return val
    return str(val) if val is not None else ""


# 复合命令分隔符（shell 中用于串联多条命令的操作符）
_CMD_SEPARATORS = re.compile(r'\s*(?:&&|\|\||[;|])\s*')


def _split_compound_command(command: str) -> list[str]:
    """
    将复合 shell 命令拆分为独立子命令。
    例如 'echo hi && rm -rf /' → ['echo hi', 'rm -rf /']
    """
    if not command:
        return [command]
    parts = _CMD_SEPARATORS.split(command)
    return [p.strip() for p in parts if p.strip()]


def _check_condition(condition: dict, args: dict) -> bool:
    """检查单个条件是否匹配。"""
    field = condition.get("field", "")
    operator = condition.get("operator", "")
    value = condition.get("value", "")
    actual = _extract_field(args, field)

    if operator == "regex_match":
        try:
            return bool(_compile_regex(str(value)).search(actual))
        except re.error:
            return False
    elif operator == "contains":
        return str(value).lower() in actual.lower()
    elif operator == "not_contains":
        return str(value).lower() not in actual.lower()
    elif operator == "equals":
        return actual == str(value)
    elif operator == "starts_with":
        return actual.startswith(str(value))
    elif operator == "ends_with":
        return actual.endswith(str(value))
    elif operator == "length_gt":
        try:
            return len(actual) > int(value)
        except (ValueError, TypeError):
            return False
    else:
        logger.warning(f"未知的规则操作符: {operator}")
        return False


def evaluate_rules(tool_name: str, args: dict) -> dict[str, Any]:
    """
    评估所有规则，返回决策结果。
    对含 command 字段的工具，先拆分复合命令，每段分别过规则。
    返回: {"action": "allow"|"block"|"warn", "message": str, "rule_name": str}
    """
    try:
        rules = _load_rules()

        # ── 复合命令拆分：对每个子命令分别评估 ──
        command_field = args.get("command", "")
        sub_commands = _split_compound_command(command_field) if command_field else []

        for rule in rules:
            tool_matcher = rule.get("tool_matcher", "*")
            if not _match_tool(tool_matcher, tool_name):
                continue

            conditions = rule.get("conditions", [])

            # 如果规则检查的是 command 字段，且原始命令是复合命令，
            # 则对每个子命令分别构造 args 副本进行检查
            has_command_condition = any(
                c.get("field") == "command" for c in conditions
            )
            if has_command_condition and len(sub_commands) > 1:
                for sub_cmd in sub_commands:
                    sub_args = dict(args)
                    sub_args["command"] = sub_cmd
                    if all(_check_condition(c, sub_args) for c in conditions):
                        action = rule.get("action", "warn")
                        message = rule.get("message", "规则匹配，操作被拦截。")
                        rule_name = rule.get("name", "unnamed")
                        logger.warning(
                            f"🛡️ 规则命中（复合命令子句）: [{rule_name}] → {action} "
                            f"| 工具: {tool_name} | 子命令: {sub_cmd}"
                        )
                        return {"action": action, "message": message, "rule_name": rule_name}
            else:
                # 非复合命令或非 command 字段规则，正常检查
                if all(_check_condition(c, args) for c in conditions):
                    action = rule.get("action", "warn")
                    message = rule.get("message", "规则匹配，操作被拦截。")
                    rule_name = rule.get("name", "unnamed")
                    logger.warning(f"🛡️ 规则命中: [{rule_name}] → {action} | 工具: {tool_name}")
                    return {"action": action, "message": message, "rule_name": rule_name}

        return {"action": "allow", "message": "", "rule_name": ""}
    except Exception as e:
        # Hook 失败时永远放行（不因基础设施故障阻塞用户）
        logger.error(f"规则引擎异常，放行: {e}")
        return {"action": "allow", "message": "", "rule_name": ""}
