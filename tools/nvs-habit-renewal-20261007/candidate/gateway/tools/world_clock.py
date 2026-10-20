# 文件路径: tools/world_clock.py
from datetime import datetime
import pytz
from core.config import config
from core.decorators import tool_meta
from tools.mcp_utils import mcp_result, mcp_error


@tool_meta(title="世界时间")
async def get_world_time(timezone: str, **kwargs):
    try:
        # 1. 获取时区对象
        # 例如: 'Asia/Shanghai', 'America/New_York', 'Europe/London'
        tz = pytz.timezone(timezone)
        
        # 2. 获取该时区当前时间
        target_time = datetime.now(tz)
        
        # 3. 格式化输出
        time_str = target_time.strftime("%Y年%m月%d日 %H:%M:%S")
        weekday = target_time.strftime("%A") # 星期几
        
        # 4. 计算时差 (与 UTC 的偏移)
        offset = target_time.utcoffset().total_seconds() / 3600
        offset_str = f"UTC{'+' if offset >=0 else ''}{int(offset)}"
        
        return mcp_result(f"🌍 {timezone} 当前时间：\n{time_str} ({weekday})\n时区：{offset_str}")

    except pytz.UnknownTimeZoneError:
        return mcp_error(f"未找到时区 '{timezone}'。请使用标准格式，如 'Asia/Tokyo', 'America/Los_Angeles'。")
    except Exception as e:
        return mcp_error(f"查询失败: {str(e)}")

# 注册工具
config.register(
    name="get_world_time",
    desc="查询世界各地城市的当前时间。请大模型根据用户提到的城市，自动转换为 IANA Timezone 格式字符串。",
    schema={
        "type": "object",
        "properties": {
            "timezone": {
                "type": "string", 
                "description": "IANA时区字符串，例如 'Asia/Shanghai', 'America/New_York', 'Europe/Paris', 'Asia/Tokyo'。"
            }
        },
        "required": ["timezone"]
    },
    func=get_world_time
)