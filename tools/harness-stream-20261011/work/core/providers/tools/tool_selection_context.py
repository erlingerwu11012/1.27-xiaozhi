"""本轮工具候选上下文：按 turn / abort epoch 隔离，禁止进程全局串用。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class CandidateScore:
    stable_id: str
    public_name: str
    score: float
    reasons: Tuple[str, ...] = ()


@dataclass
class ToolSelectionContext:
    """绑定到单次用户 turn 的候选选择结果。"""

    turn_id: str
    abort_epoch: Any
    original_query: str
    catalog_version: str
    policy_version: str
    candidate_public_names: List[str]
    candidate_scores: List[CandidateScore] = field(default_factory=list)
    confidence: str = "high"  # high | low | fallback
    fallback_reason: Optional[str] = None
    elapsed_ms: float = 0.0
    mode: str = "enabled"  # off | shadow | enabled
    exposed_public_names: Optional[List[str]] = None  # 实际发给 LLM 的集合快照

    def matches(self, turn_id: Optional[str], abort_epoch: Any) -> bool:
        if turn_id is not None and self.turn_id != turn_id:
            return False
        if abort_epoch is not None and self.abort_epoch != abort_epoch:
            return False
        return True

    def exposed_names(self) -> List[str]:
        if self.exposed_public_names is not None:
            return list(self.exposed_public_names)
        return list(self.candidate_public_names)

    def to_log_dict(self) -> Dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "abort_epoch": self.abort_epoch,
            "catalog_version": self.catalog_version,
            "policy_version": self.policy_version,
            "confidence": self.confidence,
            "fallback_reason": self.fallback_reason,
            "elapsed_ms": self.elapsed_ms,
            "mode": self.mode,
            "candidate_count": len(self.candidate_public_names),
            "candidates": self.candidate_public_names,
            "scores": [
                {
                    "name": s.public_name,
                    "score": round(s.score, 4),
                    "reasons": list(s.reasons),
                }
                for s in self.candidate_scores[:20]
            ],
        }


def session_state_flags(conn: Any) -> Dict[str, bool]:
    """从 connection 提取筛选所需的会话状态（只读，无副作用）。"""
    flags = {
        "face_enrollment_active": False,
        "card_active": False,
        "reminder_broadcast_active": False,
    }
    if conn is None:
        return flags
    try:
        if getattr(conn, "face_enrollment_session", None) or getattr(
            conn, "face_enroll_active", False
        ):
            flags["face_enrollment_active"] = True
    except Exception:
        pass
    try:
        if getattr(conn, "card_session", None) or getattr(conn, "active_card", None):
            flags["card_active"] = True
    except Exception:
        pass
    try:
        if getattr(conn, "reminder_broadcast_active", False) or getattr(
            conn, "reminder_session", None
        ):
            flags["reminder_broadcast_active"] = True
    except Exception:
        pass
    return flags


def recent_tool_names(conn: Any, limit: int = 3) -> List[str]:
    """最近真实工具名（若 connection 有记录）。"""
    names: List[str] = []
    if conn is None:
        return names
    recent = getattr(conn, "_recent_tool_names", None) or getattr(
        conn, "recent_tool_names", None
    )
    if isinstance(recent, Sequence):
        for n in recent[-limit:]:
            if isinstance(n, str) and n:
                names.append(n)
    return names
