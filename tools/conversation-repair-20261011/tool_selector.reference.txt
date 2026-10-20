"""本地候选工具选择器：无网络、无模型、无执行副作用。"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .tool_catalog import (
    ToolCatalog,
    apply_primary_entry_filter,
    load_routing_policy,
    normalize_search_text,
)
from .tool_selection_context import (
    CandidateScore,
    ToolSelectionContext,
    recent_tool_names,
    session_state_flags,
)


@dataclass
class SelectorConfig:
    soft_candidate_target: int = 12
    selector_budget_ms: float = 20.0
    fallback: str = "eligible_all"  # eligible_all
    min_score_for_hit: float = 1.5
    high_confidence_score: float = 3.0


def _char_ngrams(text: str, n: int) -> Set[str]:
    if not text or len(text) < n:
        return set()
    return {text[i : i + n] for i in range(len(text) - n + 1)}


def _lexical_score(query_norm: str, haystack: str) -> Tuple[float, List[str]]:
    """轻量中文词法分：子串 + 2/3-gram；分数不是概率。"""
    if not query_norm or not haystack:
        return 0.0, []
    reasons: List[str] = []
    score = 0.0
    if query_norm in haystack:
        score += 4.0
        reasons.append("substr_query")
    # 连续中文/字母块作为短语
    phrases = [p for p in query_norm.split() if len(p) >= 2]
    if not phrases and len(query_norm) >= 2:
        phrases = [query_norm]
    for p in phrases:
        if len(p) >= 2 and p in haystack:
            score += 2.5 + min(len(p), 6) * 0.15
            reasons.append(f"phrase:{p[:12]}")
    q2, h2 = _char_ngrams(query_norm.replace(" ", ""), 2), _char_ngrams(
        haystack.replace(" ", ""), 2
    )
    q3, h3 = _char_ngrams(query_norm.replace(" ", ""), 3), _char_ngrams(
        haystack.replace(" ", ""), 3
    )
    if q2 and h2:
        inter2 = len(q2 & h2)
        score += inter2 * 0.15
        if inter2:
            reasons.append(f"bigram:{inter2}")
    if q3 and h3:
        inter3 = len(q3 & h3)
        score += inter3 * 0.35
        if inter3:
            reasons.append(f"trigram:{inter3}")
    return score, reasons


class ToolSelector:
    def __init__(
        self,
        policy: Optional[Dict[str, Any]] = None,
        config: Optional[SelectorConfig] = None,
    ):
        self.policy = policy if policy is not None else load_routing_policy()
        self.config = config or SelectorConfig()

    def select(
        self,
        query: str,
        catalog: ToolCatalog,
        *,
        turn_id: str,
        abort_epoch: Any = None,
        recent_tools: Optional[Sequence[str]] = None,
        state_flags: Optional[Dict[str, bool]] = None,
        recent_user_context: Optional[Sequence[str]] = None,
        mode: str = "enabled",
    ) -> ToolSelectionContext:
        started = time.perf_counter()
        eligible = [
            n
            for n in apply_primary_entry_filter(catalog.eligible_names(), self.policy)
            if n in catalog.by_public_name
        ]
        # 未标注工具仍进可检索集合（primary 过滤后的全集）
        eligible_set = set(eligible)

        query_norm = normalize_search_text(query or "")
        ctx_parts = [normalize_search_text(x) for x in (recent_user_context or []) if x]
        ctx_norm = " ".join(ctx_parts[-2:])

        scores: Dict[str, float] = {n: 0.0 for n in eligible}
        reasons: Dict[str, List[str]] = {n: [] for n in eligible}

        # 常驻
        for name in self.policy.get("always_include") or []:
            if name in eligible_set:
                scores[name] = scores.get(name, 0.0) + 5.0
                reasons.setdefault(name, []).append("always")

        # 状态关联
        flags = state_flags or {}
        contextual = self.policy.get("contextual_include") or {}
        for flag_name, tool_list in contextual.items():
            if flags.get(flag_name):
                for name in tool_list or []:
                    if name in eligible_set:
                        scores[name] = scores.get(name, 0.0) + 4.0
                        reasons.setdefault(name, []).append(f"state:{flag_name}")

        # 场景多标签召回
        matched_scenes: List[str] = []
        scenes = self.policy.get("scenes") or {}
        for scene_id, scene in scenes.items():
            if not isinstance(scene, dict):
                continue
            aliases = scene.get("aliases") or []
            hit = False
            for alias in aliases:
                a = normalize_search_text(alias)
                if a and a in query_norm:
                    hit = True
                    break
            if not hit:
                continue
            matched_scenes.append(scene_id)
            for name in scene.get("tools") or []:
                if name not in eligible_set:
                    continue
                scores[name] = scores.get(name, 0.0) + 3.5
                reasons.setdefault(name, []).append(f"scene:{scene_id}")

        # 工具级词法
        for name in eligible:
            meta = catalog.get(name)
            if meta is None:
                continue
            hay = meta.search_text or normalize_search_text(name)
            s, r = _lexical_score(query_norm, hay)
            if s > 0:
                scores[name] = scores.get(name, 0.0) + s
                reasons.setdefault(name, []).extend(r)
            # 上下文只加权，不覆盖当前主题
            if ctx_norm:
                cs, _ = _lexical_score(ctx_norm, hay)
                if cs > 0:
                    scores[name] = scores.get(name, 0.0) + min(cs, 2.0) * 0.35
                    reasons.setdefault(name, []).append("context_boost")

        # 最近真实工具加权
        for name in recent_tools or []:
            if name in eligible_set:
                scores[name] = scores.get(name, 0.0) + 1.2
                reasons.setdefault(name, []).append("recent_tool")

        # 关联后续
        related_map = self.policy.get("related_followups") or {}
        seeded = [n for n, sc in scores.items() if sc >= self.config.min_score_for_hit]
        for name in list(seeded):
            for rel in related_map.get(name) or []:
                if rel in eligible_set:
                    scores[rel] = scores.get(rel, 0.0) + 2.0
                    reasons.setdefault(rel, []).append(f"followup_of:{name}")

        # 可见性 always 保底分
        for name in eligible:
            meta = catalog.get(name)
            if meta and meta.visibility == "always" and scores.get(name, 0) < 1.0:
                scores[name] = scores.get(name, 0.0) + 1.0
                reasons.setdefault(name, []).append("visibility_always")

        ranked = sorted(
            ((n, scores.get(n, 0.0)) for n in eligible),
            key=lambda x: (-x[1], x[0]),
        )

        always_set = set(self.policy.get("always_include") or [])
        # 常驻分不单独构成“可靠命中”，否则永远不会回退
        evidence = [
            (n, sc)
            for n, sc in ranked
            if sc >= self.config.min_score_for_hit and n not in always_set
        ]
        # 若常驻工具本身被场景/词法命中（reasons 含 scene/phrase 等），计入证据
        for n, sc in ranked:
            if n in always_set and sc >= self.config.min_score_for_hit:
                rs = reasons.get(n) or []
                if any(
                    r.startswith("scene:")
                    or r.startswith("phrase:")
                    or r.startswith("substr")
                    or r.startswith("bigram")
                    or r.startswith("trigram")
                    or r.startswith("state:")
                    for r in rs
                ):
                    if (n, sc) not in evidence:
                        evidence.append((n, sc))

        confidence = "high"
        fallback_reason = None
        selected_names: List[str]

        if not evidence:
            confidence = "fallback"
            fallback_reason = "no_reliable_hit"
            selected_names = list(eligible)
        else:
            selected_names = []
            seen: Set[str] = set()
            for n, sc in evidence:
                if n not in seen:
                    selected_names.append(n)
                    seen.add(n)
            for n in always_set:
                if n in eligible_set and n not in seen:
                    selected_names.append(n)
                    seen.add(n)

            if len(selected_names) > self.config.soft_candidate_target * 2:
                pass

            max_score = max((sc for _, sc in evidence), default=0.0)
            if max_score < self.config.high_confidence_score and len(matched_scenes) == 0:
                confidence = "low"
                expand = [
                    n for n, sc in ranked if n not in seen and sc > 0
                ][: max(0, self.config.soft_candidate_target)]
                for n in expand:
                    selected_names.append(n)
                    seen.add(n)
                if len(selected_names) < 5:
                    confidence = "fallback"
                    fallback_reason = "low_confidence_expand"
                    selected_names = list(eligible)

            high = [n for n, sc in evidence if sc >= self.config.high_confidence_score]
            if len(matched_scenes) == 0 and len(high) >= 8:
                confidence = "low"
                fallback_reason = fallback_reason or "ambiguous_broad_match"

        # 稳定排序
        selected_names = sorted(
            selected_names,
            key=lambda n: (-scores.get(n, 0.0), n),
        )

        candidate_scores = [
            CandidateScore(
                stable_id=(catalog.get(n).stable_id if catalog.get(n) else n),
                public_name=n,
                score=float(scores.get(n, 0.0)),
                reasons=tuple(reasons.get(n) or ()),
            )
            for n in selected_names
        ]

        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return ToolSelectionContext(
            turn_id=turn_id,
            abort_epoch=abort_epoch,
            original_query=query or "",
            catalog_version=catalog.version,
            policy_version=catalog.policy_version,
            candidate_public_names=selected_names,
            candidate_scores=candidate_scores,
            confidence=confidence,
            fallback_reason=fallback_reason,
            elapsed_ms=elapsed_ms,
            mode=mode,
        )

    def select_for_connection(
        self,
        conn: Any,
        query: str,
        catalog: ToolCatalog,
        *,
        turn_id: str,
        abort_epoch: Any = None,
        mode: str = "enabled",
        recent_user_context: Optional[Sequence[str]] = None,
    ) -> ToolSelectionContext:
        return self.select(
            query,
            catalog,
            turn_id=turn_id,
            abort_epoch=abort_epoch,
            recent_tools=recent_tool_names(conn),
            state_flags=session_state_flags(conn),
            recent_user_context=recent_user_context,
            mode=mode,
        )


def filter_descriptions_by_names(
    descriptions: Sequence[Dict[str, Any]],
    names: Iterable[str],
) -> List[Dict[str, Any]]:
    """按候选名过滤 OpenAI tools 描述；保持原 schema，深拷贝由调用方决定。"""
    name_set = set(names)
    out: List[Dict[str, Any]] = []
    for desc in descriptions:
        if not isinstance(desc, dict):
            continue
        fn = desc.get("function") if desc.get("type") == "function" else desc
        n = (fn or {}).get("name") if isinstance(fn, dict) else None
        if n in name_set:
            out.append(desc)
    # 稳定顺序：按 names 顺序
    order = {n: i for i, n in enumerate(names)}
    out.sort(
        key=lambda d: order.get(
            (d.get("function") or {}).get("name")
            if d.get("type") == "function"
            else d.get("name"),
            10**9,
        )
    )
    return out
