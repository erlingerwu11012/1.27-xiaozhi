"""
PostToolUse 安全审计：工具执行后检查返回内容是否包含敏感信息。
借鉴 Claude Code security-guidance 插件的 PostToolUse hook 模式。
不阻断流程，仅在结果中注入系统提醒让 LLM 注意脱敏。
"""
import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# 敏感信息检测模式
_SENSITIVE_PATTERNS = [
    # API Keys
    (r"sk-[a-zA-Z0-9]{20,}", "API Key (sk-...)"),
    (r"AKIA[A-Z0-9]{16}", "AWS Access Key"),
    (r"ghp_[a-zA-Z0-9]{36}", "GitHub Personal Token"),
    (r"gho_[a-zA-Z0-9]{36}", "GitHub OAuth Token"),
    (r"glpat-[a-zA-Z0-9\-]{20,}", "GitLab Token"),
    # 私钥
    (r"-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----", "私钥文件内容"),
    (r"-----BEGIN\s+OPENSSH\s+PRIVATE\s+KEY-----", "SSH 私钥内容"),
    # 密码字段
    (r'(?i)(password|passwd|pwd)\s*[=:]\s*\S+', "密码字段"),
    (r'(?i)(secret|token|api_key|apikey)\s*[=:]\s*\S{8,}', "密钥/Token 字段"),
    # 数据库连接串
    (r'(?i)(mysql|postgres|mongodb|redis)://\S+:\S+@', "数据库连接串（含密码）"),
    # 敏感文件路径
    (r'(?i)\.ssh/(id_rsa|id_ed25519|config)', "SSH 配置/密钥路径"),
    (r'(?i)(\.env|\.netrc|\.pgpass|credentials)\b', "敏感配置文件"),
]

# 预编译正则
_COMPILED_PATTERNS = [(re.compile(p), desc) for p, desc in _SENSITIVE_PATTERNS]


def audit_tool_result(tool_name: str, result: any) -> Optional[str]:
    """
    检查工具返回结果中是否包含敏感信息。
    返回警告文本（如有），None 表示安全。
    """
    try:
        # 提取文本内容
        text = _extract_text(result)
        if not text or len(text) < 5:
            return None

        findings = []
        for pattern, desc in _COMPILED_PATTERNS:
            if pattern.search(text):
                findings.append(desc)

        if not findings:
            return None

        # 去重
        findings = list(dict.fromkeys(findings))
        warning = (
            "[安全审计提醒] 工具返回内容中检测到以下敏感信息类型：\n"
            + "\n".join(f"  - {f}" for f in findings)
            + "\n请在回复用户时务必脱敏处理，不要直接展示上述敏感内容。"
        )
        logger.warning(f"🔒 PostToolUse 审计: {tool_name} → 发现 {len(findings)} 类敏感信息")
        return warning

    except Exception as e:
        # 审计失败不阻断流程
        logger.error(f"PostToolUse 审计异常: {e}")
        return None


def _extract_text(result: any) -> str:
    """从工具返回结果中提取纯文本。"""
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        # MCP 标准格式: {"content": [{"type": "text", "text": "..."}]}
        content = result.get("content", [])
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and "text" in item:
                    parts.append(str(item["text"]))
            return "\n".join(parts)
        return str(content)
    return str(result) if result else ""


def inject_system_warning(result: any, warning: str) -> any:
    """在工具返回结果中追加安全审计警告。"""
    if isinstance(result, dict) and "content" in result:
        content = result.get("content", [])
        if isinstance(content, list):
            content.append({"type": "text", "text": f"\n\n{warning}"})
            result["content"] = content
        return result
    elif isinstance(result, str):
        return result + f"\n\n{warning}"
    return result
