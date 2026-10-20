"""
角色管理器：读取角色 Markdown 文件（含 YAML frontmatter），
拼接工具说明与动态角色列表通知。
角色仅作为任务提示参考，不再参与工具集合裁剪。
"""
import os
import re
from pathlib import Path


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """
    解析 Markdown 文件中的 YAML frontmatter。
    返回 (metadata_dict, body_text)。无 frontmatter 时 metadata 为空 dict。
    """
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not m:
        return {}, text.strip()

    meta = {}
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            key, _, val = line.partition(":")
            val = val.strip()
            # 简易解析 YAML 列表：["a", "b", "c"]
            if val.startswith("[") and val.endswith("]"):
                items = [
                    s.strip().strip('"').strip("'")
                    for s in val[1:-1].split(",")
                    if s.strip()
                ]
                meta[key.strip()] = items
            else:
                meta[key.strip()] = val.strip('"').strip("'")
    body = text[m.end():].strip()
    return meta, body


class RoleManager:
    """读取 roles/*.md 和 mcp_tools_instruction.md，拼接 prompt 后缀。
    优先从 skills/*.yaml 读取同名技能（如果存在）。"""

    def __init__(self, base_dir: str | Path | None = None):
        base = Path(base_dir) if base_dir else Path(
            os.environ.get("AGENT_PERSONAS_DIR", str(Path(__file__).parent))
        )
        self.roles_dir = base / "roles"
        self.skills_dir = base / "skills"
        self.tools_md = base / "mcp_tools_instruction.md"
        # 缓存已解析的角色元数据
        self._meta_cache: dict[str, dict] = {}

    def list_roles(self) -> list[str]:
        """扫描 roles/ 和 skills/ 目录，返回可用角色名列表（去重）。"""
        names = set()
        if self.roles_dir.exists():
            names.update(p.stem for p in self.roles_dir.glob("*.md"))
        if self.skills_dir.exists():
            try:
                import yaml as _yaml
                for f in self.skills_dir.glob("*.yaml"):
                    try:
                        data = _yaml.safe_load(f.read_text(encoding="utf-8"))
                        if data and data.get("type") == "role":
                            names.add(data.get("name", f.stem))
                    except Exception:
                        continue
            except ImportError:
                pass
        return sorted(names)

    def get_role_meta(self, role_name: str) -> dict:
        """获取角色的 frontmatter 元数据。"""
        if role_name in self._meta_cache:
            return self._meta_cache[role_name]
        meta, _ = self._load_and_parse(role_name)
        self._meta_cache[role_name] = meta
        return meta

    def get_role_suffix(self, state: dict) -> str:
        """电脑控制已下架，不再拼接角色/电脑工具说明。"""
        return ""

    def _load_and_parse(self, role_name: str) -> tuple[dict, str]:
        """加载角色文件并解析 frontmatter，返回 (meta, body)。"""
        if role_name in ("default", "", None):
            return {}, ""
        p = self.roles_dir / f"{role_name}.md"
        if not p.exists():
            return {}, ""
        raw = p.read_text(encoding="utf-8")
        return _parse_frontmatter(raw)

    def _load_tools_md(self) -> str:
        if self.tools_md.exists():
            return self.tools_md.read_text(encoding="utf-8").strip()
        return ""
