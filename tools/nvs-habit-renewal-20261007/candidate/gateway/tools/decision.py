# 文件路径: tools/decision.py
import random
from core.config import config
from core.decorators import tool_meta
from tools.mcp_utils import mcp_result, mcp_error


@tool_meta(title="随机决策")
async def make_decision(mode: str, options: str = "", min_val: int = 1, max_val: int = 100, **kwargs):
    try:
        # 1. 抛硬币
        if mode == "coin":
            result = random.choice(["正面", "反面"])
            return mcp_result(f"🪙 抛硬币结果：{result}")

        # 2. 掷骰子
        elif mode == "dice":
            result = random.randint(1, 6)
            return mcp_result(f"🎲 掷骰子结果：{result} 点")

        # 3. 随机数
        elif mode == "number":
            result = random.randint(min_val, max_val)
            return mcp_result(f"🔢 随机数 ({min_val}-{max_val})：{result}")

        # 4. 帮我选 (从列表里选)
        elif mode == "pick":
            if not options:
                return mcp_error("请提供选项列表。")
            choices = options.replace("，", ",").split(",")
            choices = [c.strip() for c in choices if c.strip()]
            if not choices:
                return mcp_error("选项无效。")
            choice = random.choice(choices)
            return mcp_result(f"🤔 经过深思熟虑，我帮你选：{choice}")

        else:
            return mcp_error(f"未知的模式：{mode}")

    except Exception as e:
        return mcp_error(f"决策失败: {str(e)}")

config.register(
    name="random_decision",
    desc="随机决策助手。支持抛硬币、掷骰子、生成随机数、从多个选项中随机选择。",
    schema={
        "type": "object",
        "properties": {
            "mode": {
                "type": "string", 
                "enum": ["coin", "dice", "number", "pick"],
                "description": "模式：'coin'(抛硬币), 'dice'(掷骰子), 'number'(随机数), 'pick'(做选择)"
            },
            "options": {
                "type": "string", 
                "description": "当模式为 'pick' 时必填。选项列表，用逗号分隔。例如：'肯德基, 麦当劳, 沙县小吃'"
            },
            "min_val": {
                "type": "integer",
                "description": "当模式为 'number' 时可选。最小值，默认1。"
            },
            "max_val": {
                "type": "integer",
                "description": "当模式为 'number' 时可选。最大值，默认100。"
            }
        },
        "required": ["mode"]
    },
    func=make_decision
)