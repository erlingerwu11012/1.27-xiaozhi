"""设备定时提醒：时间解析、硬门禁、路由与 prompt 注入回归测试。

运行:
    cd main/xiaozhi-server
    python test/test_device_reminder.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.utils.remind_time import (
    SHANGHAI,
    extract_time_expression,
    has_relative_time_intent,
    has_schedule_intent,
    parse_remind_time,
)
from core.utils.device_reminder import (
    SCHEDULE_ZERO_BLOCK_MSG,
    TIME_PARSE_FAIL_MSG,
    maybe_intercept_reminder_tool,
    rewrite_reminder_tool_descriptions,
)
from core.utils.dialogue import Dialogue
from core.utils.current_time import get_prompt_time_context
from plugins_func.register import Action

PASS = []
FAIL = []

FIXED_NOW = datetime(2026, 8, 2, 21, 0, 0, tzinfo=SHANGHAI)


def check(name, cond, detail=""):
    if cond:
        PASS.append(name)
        print(f"  [PASS] {name}")
    else:
        FAIL.append(name)
        print(f"  [FAIL] {name} {detail}")


def _ts(dt: datetime) -> int:
    return int(dt.timestamp())


def test_parse_relative_times():
    print("\n== 时间解析 ==")
    cases = [
        ("两分钟后", datetime(2026, 8, 2, 21, 2, 0, tzinfo=SHANGHAI)),
        ("2分钟后", datetime(2026, 8, 2, 21, 2, 0, tzinfo=SHANGHAI)),
        ("半小时后", datetime(2026, 8, 2, 21, 30, 0, tzinfo=SHANGHAI)),
        ("一小时后", datetime(2026, 8, 2, 22, 0, 0, tzinfo=SHANGHAI)),
        ("2小时后", datetime(2026, 8, 2, 23, 0, 0, tzinfo=SHANGHAI)),
        ("明天上午9点", datetime(2026, 8, 3, 9, 0, 0, tzinfo=SHANGHAI)),
    ]
    for expr, expected in cases:
        got = parse_remind_time(expr, now=FIXED_NOW)
        ok = got is not None and got.remind_at == _ts(expected)
        check(
            f"parse:{expr}",
            ok,
            detail=f"got={got.local_dt if got else None} expect={expected}",
        )

    # 今晚8点：在 18:00 应解析为当天 20:00
    evening_now = datetime(2026, 8, 2, 18, 0, 0, tzinfo=SHANGHAI)
    got = parse_remind_time("今晚8点", now=evening_now)
    expect = datetime(2026, 8, 2, 20, 0, 0, tzinfo=SHANGHAI)
    check(
        "parse:今晚8点@18:00",
        got is not None and got.remind_at == _ts(expect),
        detail=str(got.local_dt if got else None),
    )

    # 今晚8点：在 21:00 已过去 → 解析失败（不跨日冒充）
    got_past = parse_remind_time("今晚8点", now=FIXED_NOW)
    check("parse:今晚8点@21:00_past", got_past is None)


def test_no_relative_base_kwarg():
    print("\n== dateparser API / 无 relative_base kwargs ==")
    # 走 dateparser 兜底路径也不应抛 TypeError
    try:
        parse_remind_time("in 2 minutes", now=FIXED_NOW)
        check("no_relative_base_TypeError", True)
    except TypeError as e:
        check("no_relative_base_TypeError", False, detail=str(e))


def test_intent_helpers():
    print("\n== 意图识别 ==")
    check("schedule:提醒我喝水", has_schedule_intent("提醒我喝水"))
    check("schedule:两分钟后", has_schedule_intent("两分钟后提醒我喝水"))
    check("plain:帮我记下喝水", not has_schedule_intent("帮我记下喝水"))
    check("relative:两分钟后", has_relative_time_intent("两分钟后提醒我喝水"))
    check(
        "extract:两分钟后",
        extract_time_expression("你先给我弄一个两分钟后的") == "两分钟后",
    )


class FakeMCPClient:
    def __init__(self, tools=None):
        # tools=None → 默认具备 note_add；tools=[] → 明确无设备卡片能力
        self.tools = set(["note_add"] if tools is None else tools)
        self.calls = []

    def has_tool(self, name: str) -> bool:
        return name in self.tools or name.replace(".", "_") in self.tools


class FakeMsg:
    def __init__(self, role, content):
        self.role = role
        self.content = content


class FakeDialogue:
    def __init__(self, user_texts):
        self.dialogue = [FakeMsg("user", t) for t in user_texts]


class FakeConn:
    def __init__(self, user_texts=None, tools=None, account_id="acct_a"):
        self.device_id = "b8:f8:62:7e:ca:58"
        self.session_id = "test-session-1"
        self.headers = {"device-id": self.device_id}
        self.mcp_client = FakeMCPClient(tools)
        self.dialogue = FakeDialogue(user_texts or ["两分钟后提醒我喝水"])
        self.config = {
            "server": {
                "auth_key": "test-auth-key-not-secret-in-log",
                "face": {"account_id": account_id, "identify_url": "http://127.0.0.1:8765/face/identify"},
            }
        }


def _self_resolution():
    from core.utils.recipient_resolver import RecipientResolution, RecipientResultCode

    return RecipientResolution(
        code=RecipientResultCode.RESOLVED,
        selector_type="self",
        recipient_person_id="usr_owner1",
        recipient_display_name="主人",
        attach_to_device=True,
    )


def test_intercept_gates_and_routing():
    print("\n== 拦截/路由/门禁 ==")

    async def _run():
        conn = FakeConn()

        # 1) 定时意图 + note_add(remind_at=0) → 拒绝，不调设备
        with patch(
            "core.utils.device_reminder.call_device_note_add",
            new_callable=AsyncMock,
        ) as mock_call:
            resp = await maybe_intercept_reminder_tool(
                conn, "note_add", {"text": "喝水提醒", "remind_at": 0}
            )
            check(
                "gate:note_add_remind_at_0",
                resp is not None
                and resp.action == Action.REQLLM
                and "remind_at=0" in (resp.result or ""),
                detail=str(resp.result if resp else None),
            )
            check("gate:note_add_zero_no_device_call", mock_call.await_count == 0)

        # 2) 解析失败 → 不调设备
        with patch(
            "core.utils.device_reminder.call_device_note_add",
            new_callable=AsyncMock,
        ) as mock_call:
            resp = await maybe_intercept_reminder_tool(
                conn,
                "add_reminder",
                {"text": "提醒我喝水", "remind_time_str": "蓝莓味的时间"},
            )
            check(
                "gate:parse_fail",
                resp is not None and TIME_PARSE_FAIL_MSG[:8] in (resp.result or ""),
            )
            check("gate:parse_fail_no_device_call", mock_call.await_count == 0)

        # 3) 两分钟后 → 调 note.add，remind_at=未来，不走 MySQL
        expected_at = _ts(datetime(2026, 8, 2, 21, 2, 0, tzinfo=SHANGHAI))
        with patch(
            "core.utils.device_reminder.call_device_note_add",
            new_callable=AsyncMock,
        ) as mock_call, patch(
            "core.utils.device_reminder.parse_remind_time"
        ) as mock_parse, patch(
            "core.utils.device_reminder.unix_seconds", return_value=expected_at - 120
        ), patch(
            "core.utils.device_reminder.resolve_recipient_for_conn",
            new=AsyncMock(return_value=_self_resolution()),
        ):
            from core.utils.remind_time import RemindTimeParseResult

            mock_parse.return_value = RemindTimeParseResult(
                remind_at=expected_at,
                local_dt=datetime(2026, 8, 2, 21, 2, 0, tzinfo=SHANGHAI),
                source_expr="两分钟后",
            )
            mock_call.return_value = "已设置提醒：喝水"

            resp = await maybe_intercept_reminder_tool(
                conn,
                "add_reminder",
                {
                    "text": "两分钟后提醒我喝水",
                    "remind_time_str": "两分钟后",
                },
            )
            check(
                "route:add_reminder_to_note_add",
                resp is not None
                and resp.action == Action.REQLLM
                and "设备定时提醒已创建成功" in (resp.result or ""),
                detail=str(resp.result if resp else None)[:120],
            )
            check("route:called_once", mock_call.await_count == 1)
            args = mock_call.await_args.args[1]
            check("route:remind_at_future", args.get("remind_at") == expected_at)
            check(
                "route:self_uses_default_owner_usr",
                args.get("recipient_person_id") == "usr_owner1",
            )
            check(
                "route:tool_note_add_params",
                args.get("text") in ("喝水", "提醒事项") or "喝" in args.get("text", ""),
            )

        # 4) alarm_set 相对时间 → 拒绝或改道，绝不放行 00:02
        with patch(
            "core.utils.device_reminder.call_device_note_add",
            new_callable=AsyncMock,
        ) as mock_call, patch(
            "core.utils.device_reminder.parse_remind_time"
        ) as mock_parse, patch(
            "core.utils.device_reminder.unix_seconds", return_value=expected_at - 120
        ), patch(
            "core.utils.device_reminder.resolve_recipient_for_conn",
            new=AsyncMock(return_value=_self_resolution()),
        ):
            from core.utils.remind_time import RemindTimeParseResult

            mock_parse.return_value = RemindTimeParseResult(
                remind_at=expected_at,
                local_dt=datetime(2026, 8, 2, 21, 2, 0, tzinfo=SHANGHAI),
                source_expr="两分钟后",
            )
            mock_call.return_value = "ok"
            resp = await maybe_intercept_reminder_tool(
                conn,
                "alarm_set",
                {
                    "label": "喝水时间到",
                    "hour": 0,
                    "minute": 2,
                    "repeat_days": 0,
                },
            )
            check(
                "gate:alarm_set_relative_intercepted",
                resp is not None and resp.action == Action.REQLLM,
            )
            # 应改道 note.add，而不是放行 alarm
            check(
                "gate:alarm_set_rerouted_or_blocked",
                mock_call.await_count == 1
                or (resp and "alarm_set" in (resp.result or "")),
            )
            if mock_call.await_count:
                check(
                    "gate:alarm_not_00_02_path",
                    mock_call.await_args.args[1].get("remind_at") == expected_at,
                )

        # 5) 普通便签允许 remind_at=0
        conn2 = FakeConn(user_texts=["帮我记下喝水"])
        with patch(
            "core.utils.device_reminder.call_device_note_add",
            new_callable=AsyncMock,
        ) as mock_call:
            resp = await maybe_intercept_reminder_tool(
                conn2, "note_add", {"text": "喝水", "remind_at": 0}
            )
            check("plain_note:passthrough", resp is None)
            check("plain_note:no_call_in_intercept", mock_call.await_count == 0)

        # 6) 无设备 note.add 时 add_reminder 放行（旧路径）
        conn3 = FakeConn(tools=[])
        resp = await maybe_intercept_reminder_tool(
            conn3,
            "add_reminder",
            {"text": "两分钟后提醒我喝水", "remind_time_str": "两分钟后"},
        )
        check("legacy:add_reminder_passthrough_without_note", resp is None)

    asyncio.get_event_loop().run_until_complete(_run())


def test_prompt_injection():
    print("\n== Prompt 时间注入 ==")
    d = Dialogue()
    sample = (
        "当前时间：{{current_time}} / {{current_datetime}}，"
        "日期 {{today_date}} {{today_weekday}}，Unix {{unix_timestamp}}，时区 {{timezone}}"
    )
    out = Dialogue._inject_dynamic_time_placeholders(sample)
    check("prompt:no_literal_current_time", "{{current_time}}" not in out)
    check("prompt:no_literal_unix", "{{unix_timestamp}}" not in out)
    check("prompt:has_shanghai_date_like", "-" in out and ":" in out)
    ctx = get_prompt_time_context()
    check("prompt:unix_is_digit", str(ctx["unix_timestamp"]).isdigit())
    check("prompt:timezone_shanghai", ctx["timezone"] == "Asia/Shanghai")

    # 模板文件渲染路径
    from jinja2 import Template

    tpl = Template(
        "当前时间：{{current_datetime}} Unix:{{unix_timestamp}} 星期{{today_weekday}}"
    )
    rendered = tpl.render(
        current_datetime="{{current_datetime}}",
        unix_timestamp="{{unix_timestamp}}",
        today_weekday="{{today_weekday}}",
    )
    final = Dialogue._inject_dynamic_time_placeholders(rendered)
    check("prompt:jinja_then_inject_clean", "{{" not in final)
    check("prompt:jinja_has_real_unix", any(ch.isdigit() for ch in final))


def test_tool_description_rewrite():
    print("\n== 工具描述改写 ==")
    conn = FakeConn()
    descs = [
        {
            "type": "function",
            "function": {
                "name": "add_reminder",
                "description": "旧描述",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "remind_time_str": {"type": "string", "description": "旧"}
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {"name": "note_add", "description": "旧便签", "parameters": {}},
        },
        {
            "type": "function",
            "function": {"name": "alarm_set", "description": "旧闹钟", "parameters": {}},
        },
    ]
    out = rewrite_reminder_tool_descriptions(descs, conn)
    by_name = {x["function"]["name"]: x["function"]["description"] for x in out}
    check("desc:add_reminder_mentions_nl_time", "自然语言" in by_name["add_reminder"])
    check("desc:note_add_forbids_zero", "remind_at=0" in by_name["note_add"])
    check("desc:alarm_set_forbids_relative", "两分钟后" in by_name["alarm_set"])


def test_end_to_end_parse_fixed_clock():
    print("\n== 固定时钟端到端 remind_at ==")
    two_min = parse_remind_time("两分钟后", now=FIXED_NOW)
    check(
        "e2e:two_min_unix",
        two_min is not None
        and two_min.remind_at == _ts(datetime(2026, 8, 2, 21, 2, 0, tzinfo=SHANGHAI)),
    )
    check(
        "e2e:two_min_equals_2min",
        two_min.remind_at
        == parse_remind_time("2分钟后", now=FIXED_NOW).remind_at,
    )


if __name__ == "__main__":
    test_parse_relative_times()
    test_no_relative_base_kwarg()
    test_intent_helpers()
    test_intercept_gates_and_routing()
    test_prompt_injection()
    test_tool_description_rewrite()
    test_end_to_end_parse_fixed_clock()

    print(f"\n===== 结果: {len(PASS)} passed, {len(FAIL)} failed =====")
    if FAIL:
        print("失败项:")
        for n in FAIL:
            print(" -", n)
        sys.exit(1)
    print("全部通过")
    sys.exit(0)
