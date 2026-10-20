"""工具目录快照：元数据、版本号、来源映射。无网络、无执行副作用。"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


def _stable_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)


def schema_hash(description: Dict[str, Any]) -> str:
    payload = description.get("function") if isinstance(description, dict) else description
    raw = _stable_json(payload or {})
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def public_name_of(description: Dict[str, Any], fallback: str = "") -> str:
    if not isinstance(description, dict):
        return fallback
    if description.get("type") == "function" and isinstance(description.get("function"), dict):
        return description["function"].get("name") or fallback
    return description.get("name") or fallback


def tool_description_text(description: Dict[str, Any]) -> str:
    if not isinstance(description, dict):
        return ""
    fn = description.get("function") if description.get("type") == "function" else description
    if not isinstance(fn, dict):
        return ""
    parts = [fn.get("name") or "", fn.get("description") or ""]
    params = fn.get("parameters") or {}
    if isinstance(params, dict):
        props = params.get("properties") or {}
        if isinstance(props, dict):
            parts.extend(props.keys())
            for v in props.values():
                if isinstance(v, dict) and v.get("description"):
                    parts.append(str(v["description"]))
    return " ".join(str(p) for p in parts if p)


@dataclass(frozen=True)
class ToolMeta:
    stable_id: str
    public_name: str
    source: str
    original_name: str
    schema_hash: str
    domains: Tuple[str, ...] = ()
    search_text: str = ""
    utterance_examples: Tuple[str, ...] = ()
    visibility: str = "on_demand"  # always | contextual | on_demand
    related_tool_ids: Tuple[str, ...] = ()
    capability_requirements: Tuple[str, ...] = ()
    policy_reference: str = ""
    description: Dict[str, Any] = field(default_factory=dict, compare=False, hash=False)

    def copy_description(self) -> Dict[str, Any]:
        return copy.deepcopy(self.description)


@dataclass(frozen=True)
class ToolCatalog:
    version: str
    policy_version: str
    tools: Tuple[ToolMeta, ...]
    by_public_name: Dict[str, ToolMeta]
    ambiguous_names: Tuple[str, ...] = ()
    built_at: float = 0.0

    def eligible_names(self) -> List[str]:
        return [t.public_name for t in self.tools if t.public_name not in self.ambiguous_names]

    def get(self, public_name: str) -> Optional[ToolMeta]:
        return self.by_public_name.get(public_name)


_POLICY_LOCK = threading.Lock()
_POLICY_CACHE: Dict[str, Any] = {"mtime": None, "data": None, "path": None}


def default_policy_path() -> str:
    return os.path.join(os.path.dirname(__file__), "tool_routing.yaml")


def load_routing_policy(path: Optional[str] = None) -> Dict[str, Any]:
    """加载已审核的 tool_routing.yaml；失败返回空策略。"""
    policy_path = path or default_policy_path()
    if yaml is None:
        return {"policy_version": "missing_yaml", "scenes": {}, "always_include": []}
    try:
        mtime = os.path.getmtime(policy_path)
    except OSError:
        return {"policy_version": "missing", "scenes": {}, "always_include": []}

    with _POLICY_LOCK:
        if (
            _POLICY_CACHE["path"] == policy_path
            and _POLICY_CACHE["mtime"] == mtime
            and _POLICY_CACHE["data"] is not None
        ):
            return copy.deepcopy(_POLICY_CACHE["data"])
        with open(policy_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            data = {}
        _POLICY_CACHE["path"] = policy_path
        _POLICY_CACHE["mtime"] = mtime
        _POLICY_CACHE["data"] = data
        return copy.deepcopy(data)


def _source_of(tool_def: Any) -> str:
    tool_type = getattr(tool_def, "tool_type", None)
    if tool_type is None:
        return "unknown"
    return getattr(tool_type, "value", str(tool_type))


def _original_name(tool_def: Any, public_name: str) -> str:
    params = getattr(tool_def, "parameters", None) or {}
    if isinstance(params, dict):
        for key in ("original_name", "mcp_name", "raw_name"):
            if params.get(key):
                return str(params[key])
    return public_name


def build_stable_id(source: str, original_name: str, public_name: str) -> str:
    raw = f"{source}|{original_name}|{public_name}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


class ToolCatalogBuilder:
    """从当前合法工具描述构建不可变快照。"""

    def __init__(self, policy: Optional[Dict[str, Any]] = None):
        self.policy = policy if policy is not None else load_routing_policy()

    def build(
        self,
        descriptions: Sequence[Dict[str, Any]],
        tool_defs: Optional[Dict[str, Any]] = None,
        *,
        name_collisions: Optional[Sequence[str]] = None,
    ) -> ToolCatalog:
        overrides = (self.policy or {}).get("tool_metadata_overrides") or {}
        related_map = (self.policy or {}).get("related_followups") or {}
        tools: List[ToolMeta] = []
        by_name: Dict[str, ToolMeta] = {}
        seen_names: Dict[str, int] = {}

        for desc in descriptions:
            if not isinstance(desc, dict):
                continue
            name = public_name_of(desc)
            if not name:
                continue
            seen_names[name] = seen_names.get(name, 0) + 1
            tool_def = (tool_defs or {}).get(name)
            source = _source_of(tool_def) if tool_def is not None else "unknown"
            original = _original_name(tool_def, name) if tool_def is not None else name
            ov = overrides.get(name) or {}
            base_text = tool_description_text(desc)
            extra = ov.get("search_text") or ""
            examples = tuple(ov.get("utterance_examples") or ())
            search_text = normalize_search_text(" ".join([name, base_text, extra, *examples]))
            related = tuple(related_map.get(name) or ov.get("related_tool_ids") or ())
            meta = ToolMeta(
                stable_id=build_stable_id(source, original, name),
                public_name=name,
                source=source,
                original_name=original,
                schema_hash=schema_hash(desc),
                domains=tuple(ov.get("domains") or []),
                search_text=search_text,
                utterance_examples=examples,
                visibility=str(ov.get("visibility") or "on_demand"),
                related_tool_ids=related,
                capability_requirements=tuple(ov.get("capability_requirements") or []),
                policy_reference=str(ov.get("policy_reference") or ""),
                description=copy.deepcopy(desc),
            )
            tools.append(meta)
            by_name[name] = meta

        ambiguous = []
        for n, c in seen_names.items():
            if c > 1:
                ambiguous.append(n)
        if name_collisions:
            for n in name_collisions:
                if n not in ambiguous:
                    ambiguous.append(n)

        policy_version = str((self.policy or {}).get("policy_version") or "v0")
        version_src = _stable_json(
            {
                "policy": policy_version,
                "names": sorted(by_name.keys()),
                "hashes": {k: by_name[k].schema_hash for k in sorted(by_name.keys())},
            }
        )
        version = hashlib.sha256(version_src.encode("utf-8")).hexdigest()[:16]
        return ToolCatalog(
            version=version,
            policy_version=policy_version,
            tools=tuple(tools),
            by_public_name=by_name,
            ambiguous_names=tuple(sorted(ambiguous)),
            built_at=time.time(),
        )


def normalize_search_text(text: str) -> str:
    """仅用于检索副本；不改写发给模型的原文。"""
    if not text:
        return ""
    t = unicodedata.normalize("NFKC", str(text)).lower()
    out = []
    for ch in t:
        if ch.isalnum() or ("\u4e00" <= ch <= "\u9fff"):
            out.append(ch)
        elif ch.isspace():
            out.append(" ")
    return " ".join("".join(out).split())


def apply_primary_entry_filter(
    names: Sequence[str], policy: Optional[Dict[str, Any]] = None
) -> List[str]:
    """检索集合：默认去掉 secondary，保留 primary；若 primary 不在可用集则保留 secondary。"""
    policy = policy if policy is not None else load_routing_policy()
    primary_cfg = (policy or {}).get("primary_entry") or {}
    drop: set = set()
    available = set(names)
    for _group, cfg in primary_cfg.items():
        if not isinstance(cfg, dict):
            continue
        primary = cfg.get("primary")
        secondary = cfg.get("secondary") or []
        if primary and primary in available:
            for s in secondary:
                if s != primary:
                    drop.add(s)
    return [n for n in names if n not in drop]
