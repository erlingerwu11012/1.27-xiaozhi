"""Independent official speech-expression constraint. Do not rewrite customer role prompts."""

def build_expression_constraint(control_tags=None, action_tags=None) -> str:
    """Primary replies use plain speech. Legacy arguments remain API-compatible."""
    return """[官方语音表达]
直接输出对当前用户说的口语正文。正文不生成方括号情感标签、声音动作标签、emoji、颜文字、舞台动作或内部情绪分析。
语气自然体现在措辞和音色中，不用标签表演；不要把用户意图摘要、记忆记录或回复策略当成要播报的话。
ASR情绪只是推测，以用户明确表达为准；unknown不等于平静，禁止机械镜像用户情绪。
标签不能写进函数名、参数、JSON或工具结果。不得覆盖用户角色设定和禁止事项，操作事实不因语气改变。
"""


# 供 v1 路径（change_system_prompt）与 v2 构建器（build_enhanced_prompt_v2）共同引用
OFFICIAL_EXPRESSION_CONSTRAINT = build_expression_constraint()

EXPRESSIVE_STAGE_NOTICE = "【最终语音表达阶段】只输出要对用户说的口语正文，不生成情感或动作标签、emoji、颜文字或内部分析。禁止再调用任何工具，禁止输出工具参数或 JSON。"
