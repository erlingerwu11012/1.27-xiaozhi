# 文件路径: core/config.py
import os
from typing import Any, Callable, Dict, Optional

# 用于识别“配置项”的 description 标记
CONFIG_FIELD_MARKER = "config_field: true"


class GatewayConfig:
    def __init__(self):
        # 鉴权 Token
        self.auth_token = "REPLACE_WITH_GATEWAY_AUTH_TOKEN"
        # 工具注册表（与 tools.registry 同步，含 friendly_name 供 executor 播报）
        self.mcp_tools: Dict[str, Dict[str, Any]] = {}
        # 网关已配置的配置项：{ 工具名: { 参数名: 来自 env 的值 } }，用于自动隐藏与调用时补全
        self.internal_config: Dict[str, Dict[str, str]] = {}

    def register(
        self,
        name: str,
        desc: str,
        schema: dict,
        func: Callable,
        friendly_name: Optional[str] = None,
        danger_level: str = "Low",
    ) -> None:
        """
        注册工具的通用方法；同时写入 registry，供 executor 做 TTS 播报与统一分发。
        :param name: 工具名称 (如 amap_weather)
        :param desc: 工具描述 (给大模型看的)
        :param schema: 参数定义 (JSON Schema)
        :param func: 实际执行的 Python 函数
        :param friendly_name: 播报用中文名 (如「添加定时提醒」)，未传则用 __tool_meta__.title 或 name
        :param danger_level: 危险等级 (如 "High", "Low")
        """
        from tools.registry import registry
        registry.register(name, desc, schema, func, friendly_name=friendly_name)
        info = registry.get(name)
        info["danger_level"] = danger_level
        self.mcp_tools[name] = info
        print(f"✅ 正在注册工具: {name} (危险等级: {danger_level})")

    def _is_config_param(self, prop_spec: dict) -> bool:
        """根据 description 是否含 config_field: true 判断是否为配置项。"""
        if not prop_spec or not isinstance(prop_spec, dict):
            return False
        desc = (prop_spec.get("description") or "").strip().replace(" ", "")
        return CONFIG_FIELD_MARKER.replace(" ", "") in desc

    def build_internal_config(self) -> None:
        """
        启动时根据环境变量构建 internal_config。
        规则：对每个工具的 schema 中标记为 config_field: true 的参数，
        先查 TOOLNAME_PARAM（如 AMAP_WEATHER_API_KEY），再查 PARAM（如 API_KEY），
        若存在且非空则写入 internal_config[工具名][参数名]，供 /list-tools 隐藏与调用时补全。
        """
        self.internal_config.clear()
        for tool_name, info in self.mcp_tools.items():
            schema = info.get("schema") or {}
            props = schema.get("properties") or {}
            for param_name, prop_spec in props.items():
                if not self._is_config_param(prop_spec):
                    continue
                # 先工具级再全局：AMAP_WEATHER_API_KEY -> API_KEY
                env_key_specific = f"{tool_name.upper()}_{param_name.upper()}"
                env_key_global = param_name.upper()
                value = (os.environ.get(env_key_specific) or os.environ.get(env_key_global) or "").strip()
                if value:
                    self.internal_config.setdefault(tool_name, {})[param_name] = value
        if self.internal_config:
            print(f"📦 已从环境变量加载配置项: {list(self.internal_config.keys())}")


# 创建单例对象，供其他模块引用
config = GatewayConfig()