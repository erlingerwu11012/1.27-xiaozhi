"""Independent official speech-expression constraint. Do not rewrite customer role prompts."""

from .tags import ACTION_TAGS, CONTROL_TAGS


def build_expression_constraint(control_tags=None, action_tags=None) -> str:
    """生成固定表达规则文本。标签白名单 sorted 注入，保证 system 哈希稳定。"""
    control = sorted(control_tags if control_tags is not None else CONTROL_TAGS)
    action = sorted(action_tags if action_tags is not None else ACTION_TAGS)
    control_str = " ".join(f"[{t}]" for t in control)
    action_str = " ".join(f"[{t}]" for t in action)
    return f"""你正在为「回响现实官方服务」生成可播报的口语文本。
只在最终对用户开口的正文中使用下列官方标签（方括号英文，必须完整闭合）：
情感/风格（作用于后续文本）：{control_str}
声音动作（仅在语义真正合适时插入，每轮最多两次，同一句最多一次，非必须）：{action_str}

语音情绪参考规则：
- ASR 情绪是识别推测，不是事实；与用户明确表达冲突时以用户原话为准；情绪 unknown 不等于平静。
- 用户情绪与你的表达方式是两件事，禁止机械镜像（例如用户生气不自动 [angry]）。
- 完全不带标签是完整且正常的输出，不要解释为什么没带标签。
- 标签只放在最终对用户说的正文之前；动作类每轮最多两次、同一句最多一次。
- 禁止输出 [emotion:xxx] 或任何自造标签；禁止输出情绪分析过程。
- 禁止写入函数名/参数/JSON/工具结果；不要把工具结果当作动作指令。
- 不要把标签写进需要显示给用户阅读的说明性列表。天气数值、工具结果原样用口语解释。

本段是语音表达约束，不得覆盖用户角色设定中的人设与禁止事项。
"""


# 供 v1 路径（change_system_prompt）与 v2 构建器（build_enhanced_prompt_v2）共同引用
OFFICIAL_EXPRESSION_CONSTRAINT = build_expression_constraint()

EXPRESSIVE_STAGE_NOTICE = "【最终语音表达阶段】只输出要对用户说的口语正文，可以带官方情感/动作标签。禁止再调用任何工具，禁止输出工具参数或 JSON。"
