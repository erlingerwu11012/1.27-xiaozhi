"""Independent official speech-expression constraint. Do not rewrite customer role prompts."""

from .tags import ACTION_TAGS, CONTROL_TAGS


def build_expression_constraint(control_tags=None, action_tags=None) -> str:
    """生成固定表达规则文本。标签白名单 sorted 注入，保证 system 哈希稳定。"""
    control = sorted(control_tags if control_tags is not None else CONTROL_TAGS)
    action = sorted(action_tags if action_tags is not None else ACTION_TAGS)
    control_str = " ".join(f"[{t}]" for t in control)
    action_str = " ".join(f"[{t}]" for t in action)
    return f"""[官方语音表达]
输出适合播报的正文，不写emoji、颜文字、舞台动作或情绪分析。完全不带标签是完整且正常的输出，不强制标签。
仅在语义确实需要时在最终正文使用完整闭合的官方标签，禁止自造[smirks]、[smirking]等标签；禁止输出 [emotion:xxx]。
情感/风格白名单:{control_str}
声音动作白名单:{action_str}；每轮最多两次，同一句最多一次，不强制使用。
ASR情绪只是推测，以用户明确表达为准；unknown不等于平静，禁止机械镜像用户情绪。
标签不能写进函数名、参数、JSON或工具结果。不得覆盖用户角色设定和禁止事项，操作事实不因语气改变。
"""


# 供 v1 路径（change_system_prompt）与 v2 构建器（build_enhanced_prompt_v2）共同引用
OFFICIAL_EXPRESSION_CONSTRAINT = build_expression_constraint()

EXPRESSIVE_STAGE_NOTICE = "【最终语音表达阶段】只输出要对用户说的口语正文，可以带官方情感/动作标签。设备无法显示表情，禁止使用 emoji、颜文字或装饰性表情，包括句尾表情。禁止再调用任何工具，禁止输出工具参数或 JSON。"
