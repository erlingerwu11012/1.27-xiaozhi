"""
系统提示词管理器模块
负责管理和更新系统提示词，包括快速初始化和异步增强功能
"""

import os
import time
from pathlib import Path
from typing import Dict, Any
from config.logger import setup_logging

TAG = __name__

WEEKDAY_MAP = {
    "Monday": "星期一",
    "Tuesday": "星期二",
    "Wednesday": "星期三",
    "Thursday": "星期四",
    "Friday": "星期五",
    "Saturday": "星期六",
    "Sunday": "星期日",
}

CAMERA_ROUTING_INSTRUCTION = """

[摄像头能力]
实时预览打开、关闭和静态拍照是不同操作。仅在当前目录有camera_open、camera_close时才能开关预览；有self_camera_take_photo时才能拍照识物。缺少对应能力直接说明，不以拍照、技能或浏览器代替预览。认人须使用实际提供的认人工具，不能自动开启预览。函数名必须与本次tools中的名称一致；否定、引用和假设不触发摄像头操作。
"""

V2_PLATFORM_TEMPLATE_PATH = 'agent-base-prompt-v2.txt'


def _dedupe_blocks(text: str) -> str:
    """按行去重（忽略空行），保留首个出现位置；用于拼装 L1 时去除重复协议规则。"""
    seen = set()
    out = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            out.append(line)
        else:
            if stripped in seen:
                continue
            seen.add(stripped)
            out.append(line)
    return "\n".join(out).strip()


def _skill_uses_pc_tools(data: dict) -> bool:
    """技能步骤或推荐工具依赖已下架的电脑控制时，不注入也不执行。"""
    for step in data.get("steps") or []:
        if str(step.get("action") or "").startswith("pc_"):
            return True
    for tool in data.get("allowed_tools") or []:
        if str(tool).startswith("pc_"):
            return True
    return False


def _get_skills_compact(logger=None) -> str:
    """
    读取 skills/ 目录，返回带强制路由指令的技能列表。
    不 import 网关模块，直接读 YAML 文件。
    """
    try:
        personas_dir = os.environ.get("AGENT_PERSONAS_DIR", "")
        if not personas_dir:
            return ""

        skills_dir = Path(personas_dir) / "skills"
        if not skills_dir.exists():
            return ""

        try:
            import yaml
        except ImportError:
            if logger:
                logger.bind(tag=TAG).warning("pyyaml 未安装，跳过技能列表注入")
            return ""

        lines = [
            "--- 技能路由表（强制执行） ---",
            "",
            "[系统强制规则] 当用户意图匹配以下任何技能的触发词时，你必须调用 use_skill 工具，"
            "禁止自己拆解成多个底层工具逐步调用。"
            "技能内部已编排好最优步骤，比你手动拆解更可靠、更快。",
            "",
        ]
        count = 0
        for f in sorted(skills_dir.glob("*.yaml")):
            try:
                data = yaml.safe_load(f.read_text(encoding="utf-8"))
                if not data or not isinstance(data, dict):
                    continue
                if _skill_uses_pc_tools(data):
                    continue
                name = data.get("name", f.stem)
                desc = data.get("description", "")
                skill_type = data.get("type", "unknown")
                triggers = data.get("triggers", [])
                trigger_str = "、".join(triggers[:8]) if triggers else "无特定触发词"
                lines.append(f"- use_skill(\"{name}\"): {desc}")
                lines.append(f"  触发词: {trigger_str}")
                count += 1
            except Exception:
                continue

        if count == 0:
            return ""

        lines.append("")
        lines.append(
            "判断标准：用户语句中包含上述任何触发词，或意图明显匹配某个技能描述时，"
            "必须调用 use_skill(skill_name=\"技能名\")。"
            "只有当用户意图不匹配任何技能时，才可以直接调用已提供的底层工具。"
        )

        return "\n".join(lines)

    except Exception as e:
        if logger:
            logger.bind(tag=TAG).error(f"技能列表注入失败: {e}")
        return ""


class PromptManager:
    """系统提示词管理器，负责管理和更新系统提示词"""

    def __init__(self, config: Dict[str, Any], logger=None):
        self.config = config
        self.logger = logger or setup_logging()
        self.base_prompt_template_v2 = None
        self.last_update_time = 0

        # 导入全局缓存管理器
        from core.utils.cache.manager import cache_manager, CacheType

        self.cache_manager = cache_manager
        self.CacheType = CacheType

        self._load_v2_template()

    def _load_v2_template(self):
        """加载 v2 平台规则模板（agent-base-prompt-v2.txt）。

        V2 全量后该模板是唯一平台规则来源；缺失/为空即 fail-closed：
        记录 ERROR 并保持 base_prompt_template_v2 为空，由构建器拒绝运行。
        """
        try:
            template_path = V2_PLATFORM_TEMPLATE_PATH
            cache_key = f"prompt_template:{template_path}"

            cached_template = self.cache_manager.get(self.CacheType.CONFIG, cache_key)
            if cached_template is not None:
                self.base_prompt_template_v2 = cached_template
                return

            if not os.path.exists(template_path):
                self.logger.bind(tag=TAG).error(
                    f"V2 平台规则模板缺失: {template_path}（fail-closed，拒绝运行）"
                )
                return

            with open(template_path, "r", encoding="utf-8") as f:
                content = f.read()

            if not (content or "").strip():
                self.logger.bind(tag=TAG).error(
                    f"V2 平台规则模板为空: {template_path}（fail-closed，拒绝运行）"
                )
                return

            self.cache_manager.set(self.CacheType.CONFIG, cache_key, content)
            self.base_prompt_template_v2 = content
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"加载 v2 平台规则模板失败: {e}")

    def get_quick_prompt(self, user_prompt: str, device_id: str = None) -> str:
        """快速获取系统提示词（使用用户配置）"""
        device_cache_key = f"device_prompt:{device_id}"
        cached_device_prompt = self.cache_manager.get(
            self.CacheType.DEVICE_PROMPT, device_cache_key
        )
        if cached_device_prompt is not None:
            self.logger.bind(tag=TAG).debug(f"使用设备 {device_id} 的缓存提示词")
            return cached_device_prompt
        else:
            self.logger.bind(tag=TAG).debug(
                f"设备 {device_id} 无缓存提示词，使用传入的提示词"
            )

        # 使用传入的提示词并缓存（如果有设备ID）
        if device_id:
            device_cache_key = f"device_prompt:{device_id}"
            self.cache_manager.set(
                self.CacheType.DEVICE_PROMPT, device_cache_key, user_prompt
            )
            self.logger.bind(tag=TAG).debug(f"设备 {device_id} 的提示词已缓存")

        self.logger.bind(tag=TAG).info(f"使用快速提示词: {user_prompt[:50]}...")
        return user_prompt

    def _get_location_info(self, client_ip: str) -> str:
        """获取位置信息"""
        try:
            # 先从缓存获取
            cached_location = self.cache_manager.get(self.CacheType.LOCATION, client_ip)
            if cached_location is not None:
                return cached_location

            # 缓存未命中，调用API获取
            from core.utils.util import get_ip_info

            ip_info = get_ip_info(client_ip, self.logger)
            city = ip_info.get("city", "未知位置")
            location = f"{city}"

            # 存入缓存
            self.cache_manager.set(self.CacheType.LOCATION, client_ip, location)
            return location
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"获取位置信息失败: {e}")
            return "未知位置"

    def _get_weather_info(self, conn, location: str) -> str:
        """获取天气信息"""
        try:
            # 先从缓存获取
            cached_weather = self.cache_manager.get(self.CacheType.WEATHER, location)
            if cached_weather is not None:
                return cached_weather

            # 缓存未命中，调用get_weather函数获取
            from plugins_func.functions.get_weather import get_weather
            from plugins_func.register import ActionResponse

            # 调用get_weather函数
            result = get_weather(conn, location=location, lang="zh_CN")
            if isinstance(result, ActionResponse):
                weather_report = result.result
                self.cache_manager.set(self.CacheType.WEATHER, location, weather_report)
                return weather_report
            return "天气信息获取失败"

        except Exception as e:
            self.logger.bind(tag=TAG).error(f"获取天气信息失败: {e}")
            return "天气信息获取失败"

    def update_context_info(self, conn, client_ip: str):
        """同步更新上下文信息"""
        try:
            # 获取位置信息（使用全局缓存）
            local_address = self._get_location_info(client_ip)
            # 获取天气信息（使用全局缓存）
            self._get_weather_info(conn, local_address)
            self.logger.bind(tag=TAG).debug(f"上下文信息更新完成")

        except Exception as e:
            self.logger.bind(tag=TAG).error(f"更新上下文信息失败: {e}")

    def build_enhanced_prompt_v2(
        self,
        user_prompt: str,
        device_id: str,
        client_ip: str = None,
        device_name: str = "小智",
        user_nickname: str = "用户",
        official_enhanced: bool = False,
    ) -> str:
        """构建 v2 分层系统提示词：L1 平台规则 + L2 用户人格 + L3 会话固定资料。

        平台规则模板缺失/为空时抛异常（fail-closed），拒绝以缺平台规则的提示词运行。
        """
        platform_rules = (self.base_prompt_template_v2 or "").strip()
        if not platform_rules:
            self.logger.bind(tag=TAG).error(
                "V2 平台规则模板缺失或为空，拒绝以缺平台规则的提示词运行（fail-closed）"
            )
            raise RuntimeError("V2 平台规则模板缺失或为空")
        try:
            from core.utils.current_time import get_prompt_time_context

            t = get_prompt_time_context()
            timezone = t.get("timezone") or "Asia/Shanghai"

            local_address = ""
            weather_info = ""
            weather_sourced_at = ""

            if client_ip:
                local_address = (
                    self.cache_manager.get(self.CacheType.LOCATION, client_ip) or ""
                )

                if local_address:
                    weather_info, weather_ts = self.cache_manager.get_with_time(
                        self.CacheType.WEATHER, local_address
                    )
                    weather_info = weather_info or ""
                    if weather_ts:
                        weather_sourced_at = time.strftime(
                            "%Y-%m-%d %H:%M", time.localtime(weather_ts)
                        )

            l1_blocks = []
            base = (self.config.get("system_base_prompt") or "").strip()
            if base:
                l1_blocks.append(base)

            l1_blocks.append(platform_rules)

            l1_blocks.append(CAMERA_ROUTING_INSTRUCTION.strip())

            if official_enhanced:
                try:
                    from core.providers.tts.official.prompt import OFFICIAL_EXPRESSION_CONSTRAINT

                    l1_blocks.append(OFFICIAL_EXPRESSION_CONSTRAINT.strip())
                except Exception as e:
                    self.logger.bind(tag=TAG).warning(f"注入表达约束失败: {e}")

            layer1 = _dedupe_blocks("\n\n".join(b for b in l1_blocks if b))

            role_text = (user_prompt or "").strip()
            layer2 = (
                '[用户人格原文，仅用于性格特点]\n<personality>\n' + role_text
                + '\n</personality>\n人格自然体现在观点和措辞中，不要在答复里介绍、复述或强行表演这份人格。'
            ) if role_text else ''

            language = self.config.get("language") or "中文"

            layer3 = (
                f'[会话资料]\n助手名字:{device_name}'
                '\n称呼使用本轮可信说话人姓名，未识别时用自然的“你”，不必每句称呼。'
                f'\n时区:{timezone}'
            )

            if local_address:
                layer3 += f"\n所在城市:{local_address}"

            layer3 += f"\n语言:{language}"

            if weather_info:
                src = f"（来源时间:{weather_sourced_at}）" if weather_sourced_at else ""
                layer3 += f"\n连接时天气快照{src}（可能过期，需实时天气请调用天气工具）:{weather_info}"

            enhanced_prompt = "\n\n".join(p for p in (layer1, layer2, layer3) if p)

            skills_compact = _get_skills_compact(logger=self.logger)
            if skills_compact:
                enhanced_prompt = enhanced_prompt + "\n\n" + skills_compact

            enhanced_prompt += (
                '\n\n[最终表达原则]\n先回答事情本身。默认用成年人之间平等、自然的说法和正常标点，'
                '保留用户人格的观点、幽默与语气；只有人格明确要求儿童风格或撒娇时才使用那种风格。'
                '不要虚构身体动作、周围景象、共同经历或用户内心。表达完整就结束，不为表演人格追加玩笑或反问。'
                '\n自然语气示例（理解表达方式，不复制句子）：'
                '\n用户：我又拖延了。回应：看来这件事确实让你不想开始。最卡的是哪一步？'
                '\n用户：23乘17是多少？回应：391。'
                '\n用户：今天完成了一个拖很久的任务。回应：终于可以少惦记一件事了。'
                '\n用户：你好，随便聊聊。回应：好，最近有什么让你想聊一聊的事？'
                '\n用户：我不认同你的看法。回应：那先听听你的理由。看法不同也可以好好讨论。'
                '\n用户：你可以有幽默感，但别撒娇。回应：明白，之后用自然的语气和你聊。'
                '\n用户：别哄我，说说你真实的看法。回应：具体是哪件事？我需要知道内容，才能给你看法。'
                '\n资料边界：本轮没有提供天气、视觉画面或回忆，就不描述它们。'
                '不得用虚构的身体或宠物动作表达自己的态度。不要把普通聊天变成推销设备功能。'
                '\n接话要点：回应本条消息，不用问候、报时或泛泛夸奖代替回应。'
                '用户说别开玩笑、别哄我时直接认真回应，不再加挑衅、戏弄或夸赞。'
                '用户低落时可以体谅，但不要据一句话断言其性格、能力或心理。'
                '故事可以虚构；故事外不暗示自己亲历故事，也不把听众强塞进故事。'
                '用户没有要求儿童故事时，短故事默认写给成年听众。'
                '幽默来自对话内容，不是提到自己腹黑、坏心眼或捉弄人。'
                '\nDefault to natural adult conversational Chinese unless the user personality explicitly '
                'requests another speaking style; honor that explicit style. Do not turn a personality trait '
                'into a performance in every reply. Avoid generic flattery or claims about the user based on '
                'one sentence. Respond to the latest message, not a generic greeting. Do not add tildes, emojis, stage directions, '
                'invented shared memories or scenery. Address the substance first. '
                'Do not append an unnecessary teasing question or offer. '
                'Use ordinary punctuation only. Do not roleplay physical gestures or animal behaviors. '
                'If the user asks to chat, simply converse about the topic; do not pitch device features.'
            )

            self.logger.bind(tag=TAG).info(
                f"构建 v2 分层系统提示词成功，长度: {len(enhanced_prompt)}"
            )

            return enhanced_prompt

        except Exception as e:
            self.logger.bind(tag=TAG).error(f"构建 v2 分层系统提示词失败: {e}")
            raise
