"""
技能管理器：扫描 skills/*.yaml，提供 compact/lazy/full 三级加载，
关键词路由匹配，以及按步骤执行 task 型技能。
"""
import os
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    import yaml
except ImportError:
    yaml = None
    logger.warning("pyyaml 未安装，技能库不可用。建议: pip install pyyaml")


class SkillManager:
    """技能管理器：管理 skills/ 目录下的 YAML 技能定义。"""

    def __init__(self, base_dir: str | Path | None = None):
        base = Path(base_dir) if base_dir else Path(
            os.environ.get("AGENT_PERSONAS_DIR", str(Path(__file__).parent))
        )
        self.skills_dir = base / "skills"
        self._skills: Dict[str, Dict[str, Any]] = {}
        self._load_skills()

    def _load_skills(self) -> None:
        """扫描 skills/*.yaml，解析为内存字典。"""
        if yaml is None:
            logger.warning("pyyaml 未安装，跳过技能加载")
            return
        if not self.skills_dir.exists():
            logger.info(f"技能目录不存在: {self.skills_dir}")
            return

        count = 0
        for f in sorted(self.skills_dir.glob("*.yaml")):
            try:
                raw = f.read_text(encoding="utf-8")
                data = yaml.safe_load(raw)
                if not data or not isinstance(data, dict):
                    continue
                name = data.get("name", f.stem)
                self._skills[name] = data
                count += 1
            except Exception as e:
                logger.warning(f"加载技能 {f.name} 失败: {e}")

        logger.info(f"已加载 {count} 个技能: {list(self._skills.keys())}")

    def reload(self) -> int:
        """重新加载所有技能，返回加载数量。"""
        self._skills.clear()
        self._load_skills()
        return len(self._skills)

    def list_skills_compact(self) -> str:
        """
        返回 compact 格式列表（名称 + 一行描述 + 触发词），
        约 30 token/技能，用于注入系统 prompt。
        """
        if not self._skills:
            return ""

        lines = ["可用技能列表（仅供参考；use_skill 工具已停用，请直接调用对应 MCP/设备工具）："]
        for name, skill in self._skills.items():
            desc = skill.get("description", "")
            triggers = skill.get("triggers", [])
            skill_type = skill.get("type", "unknown")
            trigger_str = "/".join(triggers[:5]) if triggers else ""
            lines.append(f"- {name} [{skill_type}]: {desc} (触发词: {trigger_str})")

        return "\n".join(lines)

    def get_skill_full(self, name: str) -> Optional[Dict[str, Any]]:
        """返回完整技能定义（含 steps/prompt）。"""
        return self._skills.get(name)

    def get_skill_names(self) -> List[str]:
        """返回所有技能名称。"""
        return list(self._skills.keys())

    def match_skill(self, user_text: str) -> Optional[str]:
        """
        关键词匹配，返回最佳技能 ID 或 None。
        匹配策略：统计每个技能的触发词命中数，取最高。
        """
        if not user_text or not self._skills:
            return None

        text_lower = user_text.lower()
        best_name = None
        best_score = 0

        for name, skill in self._skills.items():
            triggers = skill.get("triggers", [])
            score = sum(1 for t in triggers if t.lower() in text_lower)
            if score > best_score:
                best_score = score
                best_name = name

        return best_name if best_score > 0 else None

    def get_skill_prompt(self, name: str) -> str:
        """获取 role 型技能的 prompt 文本。"""
        skill = self._skills.get(name)
        if not skill:
            return ""
        return skill.get("prompt", "").strip()

    def get_skill_steps(self, name: str) -> List[Dict[str, Any]]:
        """获取 task 型技能的步骤列表。"""
        skill = self._skills.get(name)
        if not skill:
            return []
        return skill.get("steps", [])

    def get_skill_allowed_tools(self, name: str) -> List[str]:
        """获取技能的工具白名单。"""
        skill = self._skills.get(name)
        if not skill:
            return []
        return skill.get("allowed_tools", [])

    def get_skill_fallback(self, name: str) -> str:
        """获取 task 型技能的 fallback 说明。"""
        skill = self._skills.get(name)
        if not skill:
            return ""
        return skill.get("fallback", "")
