"""设备定时提醒：路由到 note.add，并做硬门禁。

当会话设备支持 note.add 时，一次性/相对提醒必须走设备 MCP，
不得走旧 MySQL add_reminder，不得用 alarm_set 表达相对时间。
收件人经 RecipientResolver 严格解析后下发（self 使用账号默认主人 usr_*）。
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional, Tuple

from config.logger import setup_logging
from core.utils.remind_time import (
    extract_time_expression,
    has_relative_time_intent,
    has_schedule_intent,
    parse_remind_time,
    unix_seconds,
)
from core.utils.recipient_resolver import (
    IDENTITY_UNAVAILABLE_CODE,
    RecipientResultCode,
    apply_recipient_to_device_args,
    resolve_recipient_for_conn,
)
from core.utils.unified_recipient_resolver import (
    apply_unified_recipient_to_device_args,
    resolve_unified_recipient_for_conn,
)
from plugins_func.register import Action, ActionResponse

TAG = __name__
logger = setup_logging()

TIME_PARSE_FAIL_MSG = (
    "我没能确认提醒时间，请告诉我具体时间，例如两分钟后、半小时后、明天上午九点。"
)
PAST_TIME_MSG = "提醒时间必须是将来时间，请重新说一个还没到的时间。"
RELATIVE_ALARM_BLOCK_MSG = (
    "相对时间提醒不能使用 alarm_set(hour, minute)。"
    "请改用 add_reminder，只传提醒内容和自然语言时间（如 remind_time_str='两分钟后'），"
    "不要自己计算 Unix 时间戳，也不要把“两分钟后”写成 hour=0, minute=2。"
)
SCHEDULE_ZERO_BLOCK_MSG = (
    "这是定时提醒请求，不能创建 remind_at=0 的普通便签。"
    "请改用 add_reminder，传入自然语言时间表达（如 remind_time_str='两分钟后'）；"
    "由服务端计算最终提醒时间。"
)
RECIPIENT_SELF_UNCONFIRMED_HINT = (
    "账号身份正在同步，暂时无法创建提醒。"
)
IDENTITY_UNAVAILABLE_HINT = "账号身份正在同步，暂时无法创建提醒。"

LEGACY_CARD_TOOL_NAMES = frozenset(
    {
        "card_get_current",
        "card_action",
        "card.get_current",
        "card.action",
    }
)
REMINDER_GET_CURRENT_NAMES = frozenset(
    {"reminder_get_current", "reminder.get_current"}
)
REMINDER_ACTION_NAMES = frozenset({"reminder_action", "reminder.action"})


def is_legacy_card_tool_name(name: str) -> bool:
    n = (name or "").strip()
    if not n:
        return False
    if n in LEGACY_CARD_TOOL_NAMES:
        return True
    dotted = n.replace("_", ".")
    return dotted in ("card.get_current", "card.action")


def _structured_tool_error(code: str, message: str, **extra) -> ActionResponse:
    payload = {
        "error": "reminder_action_rejected",
        "code": code,
        "message": message,
        **extra,
    }
    return ActionResponse(
        action=Action.REQLLM,
        result=json.dumps(payload, ensure_ascii=False),
    )


def _parse_revision(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def note_reminder_get_current_result(conn, result: Any) -> None:
    """从 reminder_get_current 的执行结果写入会话快照。"""
    from core.utils.card_action import (
        _extract_card_recipient_id,
        _parse_card_payload,
        remember_reminder_card_snapshot,
    )

    raw = result
    if hasattr(result, "result"):
        raw = getattr(result, "result", None)
    data = raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except Exception:
            data = {"content": [{"text": raw}]}
    if not isinstance(data, dict):
        return
    instance_id, revision, status = _parse_card_payload(data)
    if status != "ok" or not instance_id or revision is None or int(revision) <= 0:
        # 无当前卡时清快照，避免用陈旧 ID 下发
        from core.utils.card_action import clear_reminder_card_snapshot

        clear_reminder_card_snapshot(conn)
        return
    remember_reminder_card_snapshot(
        conn,
        instance_id=instance_id,
        revision=int(revision),
        recipient_id=_extract_card_recipient_id(data),
    )


def device_supports_note_add(conn) -> bool:
    mcp = getattr(conn, "mcp_client", None)
    if not mcp:
        return False
    return bool(mcp.has_tool("note_add") or mcp.has_tool("note.add"))


def _session_tag(conn) -> str:
    device_id = getattr(conn, "device_id", None) or (
        conn.headers.get("device-id", "") if getattr(conn, "headers", None) else ""
    )
    session_id = getattr(conn, "session_id", "")
    return f"device_id={device_id} session_id={session_id}"


def get_recent_user_text(conn, limit: int = 6) -> str:
    """取最近若干条用户原文，用于意图与时间表达回填。"""
    dialogue = getattr(conn, "dialogue", None)
    if dialogue is None:
        return ""
    messages = getattr(dialogue, "dialogue", None) or []
    parts = []
    for msg in reversed(messages):
        if getattr(msg, "role", None) != "user":
            continue
        content = getattr(msg, "content", None)
        if isinstance(content, str) and content.strip():
            parts.append(content.strip())
        if len(parts) >= limit:
            break
    return " ".join(reversed(parts))


def _log_reminder(
    conn,
    *,
    event: str,
    time_expr: str = "",
    local_time: str = "",
    remind_at: Any = None,
    tool_name: str = "",
    params: Optional[dict] = None,
    device_result: str = "",
    reason: str = "",
):
    # 日志中的 params 去掉可能过长的正文，只保留元数据
    safe_params = {}
    if params:
        for k, v in params.items():
            if k in ("text", "content", "label", "description"):
                safe_params[f"{k}_len"] = len(str(v or ""))
            elif k in (
                "remind_at",
                "priority",
                "attention_policy",
                "pre_alert_minutes",
                "recipient_person_id",
                "recipient_display_name",
                "hour",
                "minute",
            ):
                safe_params[k] = v
    payload = {
        "event": event,
        "session": _session_tag(conn),
        "time_expr": time_expr,
        "local_time": local_time,
        "remind_at": remind_at,
        "mcp_tool": tool_name,
        "params": safe_params,
        "device_result": (device_result or "")[:200],
        "reason": reason,
    }
    logger.bind(tag=TAG).info(f"[device_reminder] {json.dumps(payload, ensure_ascii=False)}")


def _pick_recipient_fields(arguments: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    """从工具参数提取 (selector_name, person_id)。"""
    pid = (
        arguments.get("recipient_person_id")
        or arguments.get("person_id")
        or arguments.get("user_id")
    )
    name = (
        arguments.get("recipient_name")
        or arguments.get("recipient")
        or arguments.get("person_name")
        or arguments.get("display_name")
    )
    return (
        str(name).strip() if name else None,
        str(pid).strip() if pid else None,
    )


async def _resolve_recipient_or_ask(
    conn,
    *,
    arguments: Dict[str, Any],
    user_text: str,
    tool_name: str,
):
    selector, person_id = _pick_recipient_fields(arguments)
    resolution = await resolve_unified_recipient_for_conn(
        conn,
        selector=selector,
        recipient_person_id=person_id,
        user_text=user_text,
        tool_name=tool_name,
    )
    if not resolution.ok_for_create:
        msg = resolution.message or "请说明提醒接收人。"
        if (
            resolution.error_code == IDENTITY_UNAVAILABLE_CODE
            or resolution.code.value == IDENTITY_UNAVAILABLE_CODE
            or resolution.code.name == "IDENTITY_UNAVAILABLE"
        ):
            msg = IDENTITY_UNAVAILABLE_HINT
        return None, ActionResponse(action=Action.REQLLM, result=msg)
    # 统一解析器已校验统一 user_id 或 all，不能再按旧 usr_* 规则拒绝。
    return resolution, None


async def call_device_note_add(conn, arguments: Dict[str, Any]) -> str:
    from core.providers.tools.device_mcp.mcp_handler import call_mcp_tool

    args_str = json.dumps(arguments, ensure_ascii=False)
    return await call_mcp_tool(conn, conn.mcp_client, "note_add", args_str)


async def call_device_mcp(conn, tool_name: str, arguments: Dict[str, Any]) -> str:
    from core.providers.tools.device_mcp.mcp_handler import call_mcp_tool

    args_str = json.dumps(arguments, ensure_ascii=False)
    return await call_mcp_tool(conn, conn.mcp_client, tool_name, args_str)


def _split_content_and_time(
    text: str = "", content: str = "", remind_time_str: str = ""
) -> Tuple[str, str]:
    """得到 (提醒正文, 时间表达)。"""
    time_expr = (remind_time_str or "").strip()
    body = (content or "").strip()

    if not time_expr:
        time_expr = extract_time_expression(text, content)
    if not body:
        raw = (text or "").strip()
        if "提醒" in raw:
            after = raw.split("提醒", 1)[1]
            body = after.lstrip("我一下下您你").strip(" ，,。.!！?？")
            if body.startswith("一下"):
                body = body[2:].lstrip(" ，,").strip()
        if not body:
            body = raw
            if time_expr and time_expr in body:
                body = body.replace(time_expr, "").strip()
            body = (
                body.replace("提醒我", "")
                .replace("提醒", "")
                .strip(" ，,。.!！?？")
            )
    if not body:
        body = "提醒事项"
    return body, time_expr


async def create_device_timed_note(
    conn,
    *,
    text: str = "",
    content: str = "",
    remind_time_str: str = "",
    extra_context: str = "",
    arguments: Optional[Dict[str, Any]] = None,
) -> ActionResponse:
    """解析时间与收件人，并调用设备 note.add(remind_at>now)。"""
    arguments = arguments or {}
    body, time_expr = _split_content_and_time(text, content, remind_time_str)
    if not time_expr:
        time_expr = extract_time_expression(text, content, remind_time_str, extra_context)

    if not time_expr:
        _log_reminder(
            conn,
            event="reject_no_time",
            time_expr="",
            reason="missing_time_expression",
            params={"text": text, "content": content},
        )
        return ActionResponse(action=Action.REQLLM, result=TIME_PARSE_FAIL_MSG)

    parsed = parse_remind_time(time_expr)
    if parsed is None:
        _log_reminder(
            conn,
            event="reject_parse_failed",
            time_expr=time_expr,
            reason="parse_failed",
        )
        return ActionResponse(action=Action.REQLLM, result=TIME_PARSE_FAIL_MSG)

    now_ts = unix_seconds()
    if parsed.remind_at <= now_ts:
        _log_reminder(
            conn,
            event="reject_past_time",
            time_expr=time_expr,
            local_time=parsed.local_dt.strftime("%Y-%m-%d %H:%M:%S%z"),
            remind_at=parsed.remind_at,
            reason=f"remind_at={parsed.remind_at} <= now={now_ts}",
        )
        return ActionResponse(action=Action.REQLLM, result=PAST_TIME_MSG)

    user_text = " ".join(
        x for x in [text, content, extra_context] if (x or "").strip()
    )
    resolution, ask = await _resolve_recipient_or_ask(
        conn,
        arguments=arguments,
        user_text=user_text,
        tool_name="note.add",
    )
    if ask is not None:
        _log_reminder(
            conn,
            event="reject_recipient",
            time_expr=time_expr,
            reason="recipient_unresolved",
        )
        return ask

    note_args = {
        "text": body,
        "remind_at": int(parsed.remind_at),
        "priority": str(arguments.get("priority") or "normal"),
        "attention_policy": str(arguments.get("attention_policy") or "general"),
        "pre_alert_minutes": int(arguments.get("pre_alert_minutes") or 0),
    }
    note_args = apply_unified_recipient_to_device_args(note_args, resolution)
    if not str(note_args.get("recipient_person_id") or "").strip():
        _log_reminder(
            conn,
            event="reject_recipient",
            time_expr=time_expr,
            reason=IDENTITY_UNAVAILABLE_CODE,
        )
        return ActionResponse(action=Action.REQLLM, result=IDENTITY_UNAVAILABLE_HINT)

    local_s = parsed.local_dt.strftime("%Y-%m-%d %H:%M:%S")
    _log_reminder(
        conn,
        event="call_note_add",
        time_expr=time_expr,
        local_time=local_s,
        remind_at=parsed.remind_at,
        tool_name="note.add",
        params=note_args,
    )

    try:
        device_result = await call_device_note_add(conn, note_args)
        from core.utils.operation_control import enabled
        if enabled(conn):
            from core.utils.tool_result import require_note_created
            require_note_created(device_result)
    except Exception as e:
        err = str(e)
        _log_reminder(
            conn,
            event="device_call_failed",
            time_expr=time_expr,
            local_time=local_s,
            remind_at=parsed.remind_at,
            tool_name="note.add",
            params=note_args,
            reason=err,
        )
        if resolution.code == RecipientResultCode.SELF and (
            "recipient" in err.lower()
            or "未确认" in err
            or "identity" in err.lower()
            or "person" in err.lower()
        ):
            return ActionResponse(
                action=Action.REQLLM, result=RECIPIENT_SELF_UNCONFIRMED_HINT
            )
        return ActionResponse(
            action=Action.REQLLM,
            result=f"设备提醒创建失败：{e}。请稍后重试，或让用户确认具体时间。",
        )

    _log_reminder(
        conn,
        event="device_success",
        time_expr=time_expr,
        local_time=local_s,
        remind_at=parsed.remind_at,
        tool_name="note.add",
        params=note_args,
        device_result=str(device_result),
    )
    who = (
        f"接收人：{resolution.recipient_display_name or '默认主人'}。"
        if resolution.attach_to_device
        else "接收人：账号默认主人。"
    )
    result_text = (
        f"设备定时提醒已创建成功。"
        f"内容摘要长度：{len(body)}；上海时间：{local_s}；remind_at={parsed.remind_at}。"
        f"{who}"
        f"设备返回：{device_result}。"
        f"请用自然语言告诉用户提醒已设好，不要提及工具名，不要复述隐私细节。"
    )
    response = ActionResponse(action=Action.REQLLM, result=result_text)
    response.operation_state = "completed"
    return response


async def _attach_recipient_and_call_device(
    conn,
    *,
    tool_name: str,
    arguments: Dict[str, Any],
    user_text: str,
) -> ActionResponse:
    """alarm.set / habit.learn：严格解析收件人后调设备。"""
    resolution, ask = await _resolve_recipient_or_ask(
        conn, arguments=arguments, user_text=user_text, tool_name=tool_name
    )
    if ask is not None:
        return ask
    args = apply_unified_recipient_to_device_args(dict(arguments), resolution)
    args.pop("creator_person_id", None)
    try:
        device_result = await call_device_mcp(conn, tool_name, args)
    except Exception as e:
        return ActionResponse(
            action=Action.REQLLM, result=f"设备调用失败：{e}。请稍后重试。"
        )
    return ActionResponse(
        action=Action.REQLLM,
        result=(
            f"设备工具 {tool_name} 已成功。"
            f"返回：{device_result}。"
            f"请用自然语言告知用户，不要提及工具名。"
        ),
    )


async def maybe_intercept_reminder_tool(
    conn, tool_name: str, arguments: Dict[str, Any]
) -> Optional[ActionResponse]:
    """在统一工具执行层拦截提醒相关调用。

    返回 ActionResponse 表示已处理（含拒绝）；返回 None 表示放行原执行器。
    """
    if not isinstance(arguments, dict):
        arguments = {}

    name = tool_name or ""
    recent_user = get_recent_user_text(conn)

    # ── 旧版 card_*：禁止模型/服务端业务路径使用 ──
    if is_legacy_card_tool_name(name):
        _log_reminder(
            conn,
            event="reject_legacy_card_tool",
            tool_name=name,
            reason="legacy_card_disabled",
            params={"action": arguments.get("action")},
        )
        return ActionResponse(
            action=Action.REQLLM,
            result=json.dumps(
                {
                    "error": "legacy_card_tool_disabled",
                    "code": "use_reminder_tools",
                    "message": (
                        "旧版 card_get_current / card_action 已停用。"
                        "请先调用 reminder_get_current 取得 instance_id 与 revision，"
                        "再调用 reminder_action；不要猜测 ID，也不要改用 card_*。"
                    ),
                },
                ensure_ascii=False,
            ),
        )

    # ── reminder_action：空参/版本/会话快照校验，失败不发给设备 ──
    if name in REMINDER_ACTION_NAMES:
        from core.utils.card_action import (
            _voice_action_allowed_for_recipient,
            get_reminder_card_snapshot,
        )

        instance_id = str(arguments.get("instance_id") or "").strip()
        revision = _parse_revision(arguments.get("revision"))
        if not instance_id:
            _log_reminder(
                conn,
                event="reject_reminder_action",
                tool_name=name,
                reason="empty_instance_id",
            )
            return _structured_tool_error(
                "missing_instance_id",
                "reminder_action 缺少 instance_id。"
                "请先调用 reminder_get_current，使用返回的 instance_id 与 revision，不要猜测或留空。",
            )
        if revision is None or revision <= 0:
            _log_reminder(
                conn,
                event="reject_reminder_action",
                tool_name=name,
                reason="invalid_revision",
                params={"revision": arguments.get("revision")},
            )
            return _structured_tool_error(
                "invalid_revision",
                "reminder_action 的 revision 必须为正整数。"
                "请先调用 reminder_get_current 获取当前 revision，禁止传 0 或空值。",
                revision=arguments.get("revision"),
            )

        snap = get_reminder_card_snapshot(conn)
        if not snap:
            _log_reminder(
                conn,
                event="reject_reminder_action",
                tool_name=name,
                reason="need_get_current",
            )
            return _structured_tool_error(
                "need_get_current",
                "尚未读取当前提醒。"
                "请先调用 reminder_get_current，再用返回的 instance_id 与 revision 调用 reminder_action。",
                instance_id=instance_id,
                revision=revision,
            )

        snap_sid = str(snap.get("session_id") or "")
        snap_did = str(snap.get("device_id") or "")
        cur_sid = str(getattr(conn, "session_id", "") or "")
        cur_did = str(getattr(conn, "device_id", "") or "")
        if (snap_sid and cur_sid and snap_sid != cur_sid) or (
            snap_did and cur_did and snap_did != cur_did
        ):
            _log_reminder(
                conn,
                event="reject_reminder_action",
                tool_name=name,
                reason="session_or_device_mismatch",
            )
            return _structured_tool_error(
                "session_mismatch",
                "当前提醒快照不属于本会话或本设备。请重新调用 reminder_get_current。",
            )

        if str(snap.get("instance_id") or "") != instance_id:
            _log_reminder(
                conn,
                event="reject_reminder_action",
                tool_name=name,
                reason="instance_mismatch",
            )
            return _structured_tool_error(
                "instance_mismatch",
                "instance_id 与最近一次 reminder_get_current 不一致。"
                "请重新调用 reminder_get_current，不要猜测 ID。",
                expected_instance_id=snap.get("instance_id"),
                got_instance_id=instance_id,
            )

        if int(snap.get("revision") or 0) != revision:
            _log_reminder(
                conn,
                event="reject_reminder_action",
                tool_name=name,
                reason="revision_mismatch",
            )
            return _structured_tool_error(
                "revision_mismatch",
                "revision 已变化或与最近一次读取不一致。"
                "请重新调用 reminder_get_current 后再执行 reminder_action。",
                expected_revision=snap.get("revision"),
                got_revision=revision,
            )

        recipient_id = str(snap.get("recipient_id") or "").strip()
        if not _voice_action_allowed_for_recipient(conn, recipient_id):
            _log_reminder(
                conn,
                event="reject_reminder_action",
                tool_name=name,
                reason="permission_denied",
                params={"instance_id": instance_id},
            )
            return _structured_tool_error(
                "permission_denied",
                "当前说话人无权操作该提醒卡。请由接收人本人确认，或在屏幕上操作。"
                "不要改用 card_action。",
                instance_id=instance_id,
            )
        # 校验通过：放行设备执行器
        return None

    # ── alarm_set：相对时间一律拒绝；否则附带收件人解析 ──
    if name in ("alarm_set", "alarm.set"):
        label = str(arguments.get("label") or "")
        if has_relative_time_intent(label, recent_user) or has_relative_time_intent(
            recent_user
        ):
            if device_supports_note_add(conn):
                time_expr = extract_time_expression(label, recent_user)
                if time_expr:
                    _log_reminder(
                        conn,
                        event="reroute_alarm_set_to_note_add",
                        time_expr=time_expr,
                        reason="relative_time_via_alarm_set",
                        params={
                            "hour": arguments.get("hour"),
                            "minute": arguments.get("minute"),
                        },
                    )
                    return await create_device_timed_note(
                        conn,
                        text=recent_user or label,
                        content=label or "提醒事项",
                        remind_time_str=time_expr,
                        extra_context=recent_user,
                        arguments=arguments,
                    )
            _log_reminder(
                conn,
                event="reject_alarm_set_relative",
                reason="relative_time_forbidden_for_alarm_set",
                params={
                    "hour": arguments.get("hour"),
                    "minute": arguments.get("minute"),
                    "label": label[:80],
                },
            )
            return ActionResponse(action=Action.REQLLM, result=RELATIVE_ALARM_BLOCK_MSG)
        if device_supports_note_add(conn) or (
            getattr(conn, "mcp_client", None)
            and (
                conn.mcp_client.has_tool("alarm_set")
                or conn.mcp_client.has_tool("alarm.set")
            )
        ):
            tool = "alarm.set"
            return await _attach_recipient_and_call_device(
                conn,
                tool_name=tool,
                arguments=arguments,
                user_text=recent_user or label,
            )
        return None

    # ── habit.learn：显式收件人严格解析 ──
    if name in ("habit_learn", "habit.learn"):
        mcp = getattr(conn, "mcp_client", None)
        if mcp and (mcp.has_tool("habit_learn") or mcp.has_tool("habit.learn")):
            return await _attach_recipient_and_call_device(
                conn,
                tool_name="habit.learn",
                arguments=arguments,
                user_text=recent_user
                or str(arguments.get("description") or ""),
            )
        return None

    # ── add_reminder：有设备 note.add 时强制设备路径（禁止旧 MySQL） ──
    if name == "add_reminder":
        if not device_supports_note_add(conn):
            return None
        return await create_device_timed_note(
            conn,
            text=str(arguments.get("text") or ""),
            content=str(arguments.get("content") or ""),
            remind_time_str=str(arguments.get("remind_time_str") or ""),
            extra_context=recent_user,
            arguments=arguments,
        )

    # ── note_add / note.add ──
    if name in ("note_add", "note.add"):
        if not device_supports_note_add(conn):
            return None

        text = str(arguments.get("text") or "")
        remind_time_str = str(arguments.get("remind_time_str") or "").strip()
        raw_remind_at = arguments.get("remind_at", None)
        try:
            remind_at = int(raw_remind_at) if raw_remind_at is not None else 0
        except (TypeError, ValueError):
            remind_at = 0

        inferred_time = extract_time_expression(text, recent_user)
        time_expr = remind_time_str or inferred_time
        schedule = (
            has_schedule_intent(text, remind_time_str, recent_user)
            or bool(time_expr)
        )

        if not schedule and remind_at == 0:
            _log_reminder(
                conn,
                event="allow_plain_note",
                params={"text": text, "remind_at": 0},
            )
            return None

        if schedule and remind_at <= 0:
            if remind_time_str:
                return await create_device_timed_note(
                    conn,
                    text=text or recent_user,
                    content=text,
                    remind_time_str=remind_time_str,
                    extra_context=recent_user,
                    arguments=arguments,
                )
            _log_reminder(
                conn,
                event="reject_note_add_zero",
                reason="schedule_intent_with_remind_at_0",
                time_expr=time_expr,
                params={"text": text, "remind_at": remind_at},
            )
            return ActionResponse(action=Action.REQLLM, result=SCHEDULE_ZERO_BLOCK_MSG)

        if time_expr:
            return await create_device_timed_note(
                conn,
                text=text or recent_user,
                content=text,
                remind_time_str=time_expr,
                extra_context=recent_user,
                arguments=arguments,
            )

        if schedule:
            _log_reminder(
                conn,
                event="reject_llm_epoch",
                remind_at=remind_at,
                reason="schedule_intent_without_natural_language_time",
                params={"text": text, "remind_at": remind_at},
            )
            return ActionResponse(action=Action.REQLLM, result=TIME_PARSE_FAIL_MSG)

        now_ts = unix_seconds()
        if remind_at <= now_ts:
            _log_reminder(
                conn,
                event="reject_non_future_remind_at",
                remind_at=remind_at,
                reason=f"remind_at={remind_at} <= now={now_ts}",
                params={"text": text},
            )
            return ActionResponse(action=Action.REQLLM, result=PAST_TIME_MSG)

        return None

    return None


def rewrite_reminder_tool_descriptions(descriptions: list, conn) -> list:
    """在有设备 note.add 时改写暴露给 LLM 的工具说明。"""
    if not device_supports_note_add(conn):
        return descriptions

    out = []
    for item in descriptions:
        if not isinstance(item, dict):
            out.append(item)
            continue
        fn = item.get("function") if item.get("type") == "function" else item
        if not isinstance(fn, dict):
            out.append(item)
            continue
        name = fn.get("name") or ""
        new_item = dict(item)
        if item.get("type") == "function":
            new_fn = dict(fn)
            new_item["function"] = new_fn
            fn = new_fn

        if name == "add_reminder":
            fn["description"] = (
                "创建设备定时提醒卡片（一次性/相对时间）。"
                "只传提醒内容与自然语言时间，不要自己计算 Unix 时间戳，不要自造 usr_*。"
                "接收人只能是「我」或网页已登记的明确姓名；"
                "儿子/妈妈/他/她等关系词或代词必须追问，不得猜测。"
                "参数优先：text=用户原话，或 content+remind_time_str（如「两分钟后」）；"
                "可选 recipient_name=登记姓名。"
                "服务端会解析 Asia/Shanghai 时间与收件人并调用设备 note.add。"
                "禁止用 alarm_set 表达几分钟后/几小时后。"
            )
            props = (fn.get("parameters") or {}).get("properties") or {}
            if "remind_time_str" in props and isinstance(props["remind_time_str"], dict):
                props = dict(props)
                rts = dict(props["remind_time_str"])
                rts["description"] = (
                    "自然语言时间，如：两分钟后、半小时后、明天上午9点、今晚8点。"
                    "不要传 Unix 时间戳。"
                )
                params = dict(fn.get("parameters") or {})
                params["properties"] = {**props, "remind_time_str": rts}
                fn["parameters"] = params
        elif name == "note_add":
            fn["description"] = (
                "添加设备备忘录。"
                "仅当用户明确说「记一下/记个便签」且没有任何提醒时间时使用，remind_at 填 0。"
                "若用户要「提醒我/X分钟后/明天/今晚」，必须改用 add_reminder 并传自然语言时间；"
                "禁止自行计算 remind_at，禁止在定时意图下传 remind_at=0；禁止自造 usr_*。"
            )
        elif name == "alarm_set":
            fn["description"] = (
                "设置钟点闹钟（绝对时刻 hour:minute），如每天 7:30。"
                "禁止用于「两分钟后」「半小时后」等相对时间；相对/一次性提醒请用 add_reminder。"
                "接收人只能是「我」或网页已登记姓名；关系词/代词必须追问。"
            )
        elif name in ("habit_learn", "habit.learn"):
            fn["description"] = (
                "记录规律性习惯。"
                "接收人只能是「我」或网页已登记的明确姓名；不得使用关系词/代词，不得自造 usr_*。"
            )
        out.append(new_item)
    return out
