"""提醒卡片语音操作确定性路由。

唯一正式路径：reminder.get_current → reminder.action(instance_id, revision, action)

旧版 card.get_current / card.action 不再作为能力缺失降级目标。
设备 tools/list 若仍上报 card.*，由模型工具过滤与执行拦截屏蔽；本模块只调 reminder.*。

挂接点：receiveAudioHandle.startToChat（ASR 文本入口，等价于 intent 前拦截；
不重复挂 intentHandler / unified_tool_manager，工具白名单层不负责卡片口令路由）。
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional, Tuple

from config.logger import setup_logging
from core.utils.reminder_audit import audit_event, conn_ids

TAG = __name__
logger = setup_logging()

# 人脸“刚确认在场”的语音确认窗口；过期后仍可触屏，不允许靠旧人脸结果操作。
PRESENT_USER_ACTION_TTL_SECONDS = 120.0

# 会话内最近一次成功读取的当前提醒（供 reminder_action 乐观校验）
REMINDER_CARD_SNAPSHOT_ATTR = "_reminder_card_snapshot"

_CAPABILITY_MISSING_RE = re.compile(
    r"(tool not found|unknown tool|capability missing|not supported|unsupported|"
    r"does not exist|no such tool|method not found)",
    re.I,
)

# 完成 / 稍后 / 不需要了 — 须整句匹配，避免误触
_EXACT_ACTION_MAP = (
    (re.compile(r"^(完成|好了|弄完了|做完了|知道了)$"), "primary"),
    (re.compile(r"^(稍后|等会|等一下|待会|晚点|过会)$"), "secondary"),
    (re.compile(r"^(不需要了|不用了|取消|删掉|删除)$"), "tertiary"),
)
_TRAILING_ACTION_MAP = (
    (re.compile(r"^(?:我要|帮我)?(完成|好了|弄完了|做完了)$"), "primary"),
    (re.compile(r"^(?:我要|帮我)?(稍后|等会|等一下|待会|晚点|过会)$"), "secondary"),
    (re.compile(r"^(?:我要|帮我)?(不需要了|不用了|取消|删掉|删除)$"), "tertiary"),
)
_NEGATION_RE = re.compile(r"还没|不要|别弄|别完成|尚未|没完成|别稍后|不是")


class CardRouteResult(str, Enum):
    NOT_MATCHED = "not_matched"
    NO_CAPABILITY = "no_capability"
    NO_CURRENT_CARD = "no_current_card"
    PERMISSION_DENIED = "permission_denied"
    VERSION_CONFLICT = "version_conflict"
    TIMEOUT = "timeout"
    TOOL_ERROR = "tool_error"
    SUCCESS = "success"


@dataclass
class CardRouteResponse:
    result: CardRouteResult
    message: str
    action: str = ""
    tool_family: str = ""


class _TryNextFamily(Exception):
    """当前工具族能力缺失（已不再降级到 card）。"""


def remember_reminder_card_snapshot(
    conn,
    *,
    instance_id: str,
    revision: int,
    recipient_id: str = "",
) -> None:
    """记录本会话最近一次成功的 reminder.get_current 结果。"""
    if conn is None or not instance_id or revision is None:
        return
    try:
        rev = int(revision)
    except (TypeError, ValueError):
        return
    if rev <= 0:
        return
    setattr(
        conn,
        REMINDER_CARD_SNAPSHOT_ATTR,
        {
            "instance_id": str(instance_id),
            "revision": rev,
            "recipient_id": str(recipient_id or "").strip(),
            "session_id": str(getattr(conn, "session_id", "") or ""),
            "device_id": str(getattr(conn, "device_id", "") or ""),
        },
    )


def get_reminder_card_snapshot(conn) -> Optional[Dict[str, Any]]:
    snap = getattr(conn, REMINDER_CARD_SNAPSHOT_ATTR, None)
    return snap if isinstance(snap, dict) else None


def clear_reminder_card_snapshot(conn) -> None:
    if conn is not None and hasattr(conn, REMINDER_CARD_SNAPSHOT_ATTR):
        try:
            delattr(conn, REMINDER_CARD_SNAPSHOT_ATTR)
        except Exception:
            setattr(conn, REMINDER_CARD_SNAPSHOT_ATTR, None)


def _segment_negated(segment: str) -> bool:
    return bool(_NEGATION_RE.search(segment or ""))


def map_utterance_to_action(text: str) -> Optional[str]:
    s = (text or "").strip()
    if not s:
        return None
    for pattern, action in _EXACT_ACTION_MAP:
        if pattern.fullmatch(s):
            return action
    parts = [p.strip() for p in re.split(r"[，,。！!？?；;]", s) if p.strip()]
    if len(parts) > 1:
        tail = parts[-1]
        if not _segment_negated(tail):
            for pattern, action in _TRAILING_ACTION_MAP:
                if pattern.fullmatch(tail):
                    return action
    return None


def _available_tool_names(conn) -> set:
    """合并设备原始名与 sanitized 名；兼容测试里注入的 available_tools。"""
    mcp = getattr(conn, "mcp_client", None)
    if mcp is None:
        return set()
    names: set = set()
    mapping = getattr(mcp, "name_mapping", None)
    if isinstance(mapping, dict) and mapping:
        names.update(mapping.keys())
        names.update(v for v in mapping.values() if isinstance(v, str))
    for attr in ("tools", "available_tools"):
        tools = getattr(mcp, attr, None)
        if isinstance(tools, dict):
            names.update(tools.keys())
    return names


def _has_tool_pair(names: set, get_aliases: tuple, action_aliases: tuple) -> bool:
    return any(n in names for n in get_aliases) and any(
        n in names for n in action_aliases
    )


def device_supports_reminder_card_action(conn) -> bool:
    names = _available_tool_names(conn)
    return _has_tool_pair(
        names,
        ("reminder.get_current", "reminder_get_current"),
        ("reminder.action", "reminder_action"),
    )


def device_supports_legacy_card_action(conn) -> bool:
    """探测设备是否仍上报旧 card.*（仅诊断；路由不再使用）。"""
    names = _available_tool_names(conn)
    return _has_tool_pair(
        names,
        ("card.get_current", "card_get_current"),
        ("card.action", "card_action"),
    )


def device_supports_any_card_action(conn) -> bool:
    """语音/业务是否可走提醒卡操作：仅认 reminder 族。"""
    return device_supports_reminder_card_action(conn)


def is_capability_missing_error(err: Any) -> bool:
    return bool(_CAPABILITY_MISSING_RE.search(str(err or "")))


def is_capability_missing_result(result: Any) -> bool:
    if not isinstance(result, dict) or not result.get("isError"):
        return False
    return is_capability_missing_error(result.get("error"))


def _tool_families_for_conn(conn) -> list[tuple[str, str, str]]:
    """仅返回 reminder 族；不再降级到 card。"""
    if device_supports_reminder_card_action(conn):
        return [("reminder", "reminder.get_current", "reminder.action")]
    return []


async def _call_device_tool(conn, name: str, args: Dict[str, Any], *, timeout: float = 30.0):
    """调用设备 MCP；统一成 dict，便于解析 instance_id/revision。"""
    from core.providers.tools.device_mcp.mcp_handler import call_mcp_tool
    from core.utils.tool_result import DeviceToolError

    mcp = getattr(conn, "mcp_client", None)
    if mcp is None:
        raise RuntimeError("mcp_client missing")
    args_str = json.dumps(args or {}, ensure_ascii=False)
    try:
        raw = await call_mcp_tool(conn, mcp, name, args_str, timeout=timeout)
    except DeviceToolError as exc:
        code = getattr(exc, "code", None) or str(exc)
        return {"isError": True, "error": code}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return {"content": [{"text": "{}"}]}
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
        return {"content": [{"text": text}]}
    return {"content": [{"text": str(raw)}]}


def _parse_card_payload(result: Any) -> Tuple[Optional[str], Optional[int], str]:
    if result is None:
        return None, None, "empty_result"
    if isinstance(result, dict):
        if result.get("isError"):
            return None, None, str(result.get("error") or "tool_error")
        content = result.get("content")
        if isinstance(content, list) and content:
            text = content[0].get("text") if isinstance(content[0], dict) else str(content[0])
            try:
                import json

                data = json.loads(text) if isinstance(text, str) else text
                if isinstance(data, dict):
                    iid = data.get("instance_id")
                    rev = data.get("revision")
                    if iid:
                        return str(iid), int(rev) if rev is not None else None, "ok"
            except Exception:
                pass
        iid = result.get("instance_id")
        rev = result.get("revision")
        if iid:
            return str(iid), int(rev) if rev is not None else None, "ok"
    return None, None, "parse_failed"


def _extract_card_recipient_id(result: Any) -> str:
    """从新卡片载荷读取统一接收人；旧卡片没有该字段时交给兼容路径。"""
    if not isinstance(result, dict):
        return ""
    data = result
    content = result.get("content")
    if isinstance(content, list) and content:
        text = content[0].get("text") if isinstance(content[0], dict) else content[0]
        try:
            import json

            parsed = json.loads(text) if isinstance(text, str) else text
            if isinstance(parsed, dict):
                data = parsed
        except Exception:
            pass
    return str(
        data.get("recipient_user_id") or data.get("recipient_person_id") or ""
    ).strip()


def _voice_action_allowed_for_recipient(conn, recipient_id: str) -> bool:
    """语音完成/取消指定用户项时校验 speaker 或刚确认的 present user。"""
    if not recipient_id or recipient_id == "all":
        # 没有字段的旧卡片保持兼容；all 按产品规则允许任何人。
        return True
    speaker = getattr(conn, "current_speaker_user", None)
    if isinstance(speaker, dict) and str(speaker.get("user_id") or "").strip() == recipient_id:
        return True

    present = getattr(conn, "current_present_user", None)
    seen_at = float(getattr(conn, "current_present_user_seen_at", 0.0) or 0.0)
    if (
        isinstance(present, dict)
        and str(present.get("user_id") or "").strip() == recipient_id
        and seen_at > 0
        and time.monotonic() - seen_at <= PRESENT_USER_ACTION_TTL_SECONDS
    ):
        return True
    return False


def _audit_card(conn, event: str, *, result_code: str, action: str = "", extra=None):
    ids = conn_ids(conn)
    audit_event(
        event,
        **ids,
        result_code=result_code,
        prefix="[card_action]",
        extra={"action": action, **(extra or {})},
    )


def _interpret_action_result(
    action_result: Any, mapped_action: str, family: str
) -> CardRouteResponse:
    if isinstance(action_result, dict) and action_result.get("isError"):
        err_text = str(action_result.get("error") or "")
        if is_capability_missing_error(err_text):
            raise _TryNextFamily(err_text)
        if "version" in err_text.lower() or "conflict" in err_text.lower():
            return CardRouteResponse(
                CardRouteResult.VERSION_CONFLICT,
                "卡片已更新，请看一下屏幕再操作。",
                action=mapped_action,
                tool_family=family,
            )
        if "permission" in err_text.lower() or "denied" in err_text.lower():
            return CardRouteResponse(
                CardRouteResult.PERMISSION_DENIED,
                "你没有权限操作这张卡片。",
                action=mapped_action,
                tool_family=family,
            )
        return CardRouteResponse(
            CardRouteResult.TOOL_ERROR,
            "卡片操作未能完成，请看一下屏幕。",
            action=mapped_action,
            tool_family=family,
        )
    messages = {
        "primary": "好的，已经帮你标记完成了。",
        "secondary": "好的，已帮你延后处理。",
        "tertiary": "好的，已帮你关闭这条提醒。",
    }
    return CardRouteResponse(
        CardRouteResult.SUCCESS,
        messages.get(mapped_action, "好的，操作已完成。"),
        action=mapped_action,
        tool_family=family,
    )


async def _route_with_family(
    conn, *, family: str, get_tool: str, action_tool: str, mapped_action: str
) -> CardRouteResponse:
    t0 = time.time()
    _audit_card(
        conn,
        "card_action_get_current",
        result_code="start",
        action=mapped_action,
        extra={"tool_family": family, "tool": get_tool},
    )
    try:
        current = await _call_device_tool(conn, get_tool, {})
    except TimeoutError:
        _audit_card(
            conn,
            "card_action_get_current",
            result_code="timeout",
            action=mapped_action,
            extra={"tool_family": family},
        )
        return CardRouteResponse(
            CardRouteResult.TIMEOUT,
            "卡片操作超时了，请稍后再试或在屏幕上操作。",
            action=mapped_action,
            tool_family=family,
        )
    except Exception as exc:
        if is_capability_missing_error(exc):
            _audit_card(
                conn,
                "card_action_get_current",
                result_code="capability_missing",
                action=mapped_action,
                extra={"tool_family": family, "reason": type(exc).__name__},
            )
            raise _TryNextFamily(str(exc)) from exc
        _audit_card(
            conn,
            "card_action_get_current",
            result_code="error",
            action=mapped_action,
            extra={"tool_family": family, "reason": type(exc).__name__},
        )
        return CardRouteResponse(
            CardRouteResult.TOOL_ERROR,
            "暂时无法读取当前卡片，请稍后再试。",
            action=mapped_action,
            tool_family=family,
        )

    if is_capability_missing_result(current):
        _audit_card(
            conn,
            "card_action_get_current",
            result_code="capability_missing",
            action=mapped_action,
            extra={"tool_family": family},
        )
        raise _TryNextFamily(str(current.get("error")))

    instance_id, revision, _ = _parse_card_payload(current)
    if not instance_id or revision is None or int(revision) <= 0:
        _audit_card(
            conn,
            "card_action_get_current",
            result_code="no_current_card",
            action=mapped_action,
            extra={"tool_family": family},
        )
        return CardRouteResponse(
            CardRouteResult.NO_CURRENT_CARD,
            "当前没有待处理的提醒卡片。",
            action=mapped_action,
            tool_family=family,
        )

    recipient_id = _extract_card_recipient_id(current)
    if not _voice_action_allowed_for_recipient(conn, recipient_id):
        _audit_card(
            conn,
            "card_action_execute",
            result_code="permission_denied",
            action=mapped_action,
            extra={"tool_family": family, "instance_id": instance_id},
        )
        return CardRouteResponse(
            CardRouteResult.PERMISSION_DENIED,
            "这条提醒需要接收人本人确认，也可以直接在屏幕上操作。",
            action=mapped_action,
            tool_family=family,
        )

    remember_reminder_card_snapshot(
        conn,
        instance_id=instance_id,
        revision=int(revision),
        recipient_id=recipient_id,
    )

    _audit_card(
        conn,
        "card_action_get_current",
        result_code="ok",
        action=mapped_action,
        extra={
            "tool_family": family,
            "instance_id": instance_id,
            "revision": revision,
            "latency_ms": round((time.time() - t0) * 1000, 1),
        },
    )

    action_args: Dict[str, Any] = {
        "instance_id": instance_id,
        "revision": revision,
        "action": mapped_action,
    }
    t1 = time.time()
    try:
        action_result = await _call_device_tool(conn, action_tool, action_args)
    except TimeoutError:
        _audit_card(
            conn,
            "card_action_execute",
            result_code="timeout",
            action=mapped_action,
            extra={"tool_family": family, "instance_id": instance_id, "revision": revision},
        )
        return CardRouteResponse(
            CardRouteResult.TIMEOUT,
            "卡片操作超时了，请稍后再试或在屏幕上操作。",
            action=mapped_action,
            tool_family=family,
        )
    except Exception as exc:
        if is_capability_missing_error(exc):
            raise _TryNextFamily(str(exc)) from exc
        _audit_card(
            conn,
            "card_action_execute",
            result_code="error",
            action=mapped_action,
            extra={"tool_family": family, "reason": type(exc).__name__},
        )
        return CardRouteResponse(
            CardRouteResult.TOOL_ERROR,
            "卡片操作失败了，请稍后再试。",
            action=mapped_action,
            tool_family=family,
        )

    resp = _interpret_action_result(action_result, mapped_action, family)
    _audit_card(
        conn,
        "card_action_execute",
        result_code=resp.result.value,
        action=mapped_action,
        extra={
            "tool_family": family,
            "instance_id": instance_id,
            "revision": revision,
            "latency_ms": round((time.time() - t1) * 1000, 1),
        },
    )
    return resp


async def route_card_voice_action(conn, text: str) -> CardRouteResponse:
    """确定性卡片动作路由；仅 reminder.*，设备 MCP 成功结果才是权威。"""
    action = map_utterance_to_action(text)
    if not action:
        return CardRouteResponse(CardRouteResult.NOT_MATCHED, "")

    families = _tool_families_for_conn(conn)
    if not families:
        return CardRouteResponse(
            CardRouteResult.NO_CAPABILITY,
            "当前设备还不支持卡片语音操作，请直接在屏幕上操作。",
            action=action,
        )

    last_cap_missing = False
    for family, get_tool, action_tool in families:
        try:
            return await _route_with_family(
                conn,
                family=family,
                get_tool=get_tool,
                action_tool=action_tool,
                mapped_action=action,
            )
        except _TryNextFamily:
            last_cap_missing = True
            continue

    if last_cap_missing:
        return CardRouteResponse(
            CardRouteResult.NO_CAPABILITY,
            "当前设备还不支持卡片语音操作，请直接在屏幕上操作。",
            action=action,
        )
    return CardRouteResponse(
        CardRouteResult.TOOL_ERROR,
        "卡片操作失败了，请稍后再试。",
        action=action,
    )
