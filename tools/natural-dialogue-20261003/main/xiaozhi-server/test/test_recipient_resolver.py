"""RecipientResolver：精确姓名 / 关系词 / 跨 account。"""

from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.utils.recipient_resolver import (
    ProfileDirectory,
    ProfileRecord,
    RecipientResultCode,
    apply_recipient_to_device_args,
    extract_recipient_selector_from_text,
    normalize_display_name,
    resolve_recipient,
)
from core.utils.device_reminder import maybe_intercept_reminder_tool
from plugins_func.register import Action

PASS = []
FAIL = []


def check(name, cond, detail=""):
    if cond:
        PASS.append(name)
        print(f"  [PASS] {name}")
    else:
        FAIL.append(name)
        print(f"  [FAIL] {name} {detail}")


def dir_a():
    return ProfileDirectory(
        account_id="acct_a",
        profiles=[
            ProfileRecord("usr_aaa111", "小明", "active", "acct_a"),
            ProfileRecord("usr_bbb222", "小明", "active", "acct_a"),  # 重名
            ProfileRecord("usr_ccc333", "小红", "active", "acct_a"),
            ProfileRecord("usr_ddd444", "草稿人", "draft", "acct_a"),
            ProfileRecord("usr_eee555", "已删名", "inactive", "acct_a"),
        ],
    )


def dir_b():
    return ProfileDirectory(
        account_id="acct_b",
        profiles=[
            ProfileRecord("usr_zzz999", "小明", "active", "acct_b"),
        ],
    )


def test_normalize_and_self():
    print("\n== 规范化 / self ==")
    check("trim_space", normalize_display_name("  小明  ") == "小明")
    check(
        "merge_space",
        normalize_display_name("小\t\n明") == "小 明"
        or normalize_display_name("小  明") == "小 明",
    )
    r = resolve_recipient(dir_a(), selector="我")
    check("self:我", r.code == RecipientResultCode.IDENTITY_UNAVAILABLE or r.code == RecipientResultCode.RESOLVED)
    # 无默认主人时 fail-closed
    check("self:我_no_owner", r.code == RecipientResultCode.IDENTITY_UNAVAILABLE and not r.ok_for_create)
    d_owner = ProfileDirectory(
        account_id="acct_a",
        profiles=[
            ProfileRecord("usr_own001", "主人", "active", "acct_a", is_default_owner=True)
        ],
    )
    r = resolve_recipient(d_owner, selector="我")
    check(
        "self:我_with_owner",
        r.code == RecipientResultCode.RESOLVED
        and r.recipient_person_id == "usr_own001"
        and r.attach_to_device,
    )
    r = resolve_recipient(d_owner, selector=None)
    check("self:empty_default", r.code == RecipientResultCode.RESOLVED and r.ok_for_create)


def test_exact_name():
    print("\n== 精确姓名 ==")
    d = ProfileDirectory(
        account_id="acct_a",
        profiles=[ProfileRecord("usr_ccc333", "小红", "active", "acct_a")],
    )
    r = resolve_recipient(d, selector="小红")
    check(
        "exact:小红",
        r.code == RecipientResultCode.RESOLVED
        and r.recipient_person_id == "usr_ccc333"
        and r.recipient_display_name == "小红",
    )
    r = resolve_recipient(dir_a(), selector="不存在的人")
    check("exact:not_found", r.code == RecipientResultCode.NOT_FOUND)
    r = resolve_recipient(dir_a(), selector="小明")
    check("exact:ambiguous", r.code == RecipientResultCode.AMBIGUOUS)
    r = resolve_recipient(dir_a(), selector="草稿人")
    check("draft:not_resolvable", r.code == RecipientResultCode.NOT_FOUND)
    r = resolve_recipient(dir_a(), selector="已删名")
    check("inactive:not_resolvable", r.code == RecipientResultCode.NOT_FOUND)


def test_relation_and_person_id():
    print("\n== 关系词 / person_id 校验 ==")
    for w in ("儿子", "妈妈", "他", "她", "那个"):
        r = resolve_recipient(dir_a(), selector=w)
        check(f"relation:{w}", r.code == RecipientResultCode.RELATION_REFUSED)

    r = resolve_recipient(dir_a(), recipient_person_id="usr_ccc333")
    check("pid:valid_active", r.code == RecipientResultCode.RESOLVED)
    r = resolve_recipient(dir_a(), recipient_person_id="usr_zzz999")
    check("pid:other_account_id_not_in_dir", r.code == RecipientResultCode.INVALID_ID)
    r = resolve_recipient(dir_a(), recipient_person_id="usr_ddd444")
    check("pid:draft_rejected", r.code == RecipientResultCode.INVALID_ID)
    r = resolve_recipient(dir_a(), recipient_person_id="not_a_usr")
    check("pid:bad_format", r.code == RecipientResultCode.INVALID_ID)


def test_cross_account():
    print("\n== 跨 account ==")
    # account A 目录不能解析到 B 的 usr
    r = resolve_recipient(dir_a(), recipient_person_id="usr_zzz999")
    check("cross:pid", r.code == RecipientResultCode.INVALID_ID)
    # 同名在 B 不影响 A 的精确匹配（A 有重名小明 → ambiguous；无小红冲突）
    r = resolve_recipient(dir_b(), selector="小明")
    check(
        "cross:name_in_b_only",
        r.code == RecipientResultCode.RESOLVED
        and r.recipient_person_id == "usr_zzz999",
    )


def test_extract_and_apply():
    print("\n== 话术提取 / 参数附着 ==")
    check(
        "extract:我",
        extract_recipient_selector_from_text("两分钟后提醒我喝水") == "我",
    )
    check(
        "extract:小明",
        extract_recipient_selector_from_text("两分钟后提醒小明喝水") == "小明",
    )
    from core.utils.recipient_resolver import RecipientResolution

    r = RecipientResolution(
        code=RecipientResultCode.RESOLVED,
        selector_type="explicit_name",
        recipient_person_id="usr_ccc333",
        recipient_display_name="小红",
        attach_to_device=True,
    )
    args = apply_recipient_to_device_args(
        {"text": "x", "creator_person_id": "usr_should_strip"}, r
    )
    check("apply:has_recipient", args.get("recipient_person_id") == "usr_ccc333")
    check("apply:no_creator_forge", "creator_person_id" not in args)

    r2 = RecipientResolution(
        code=RecipientResultCode.SELF, selector_type="self", attach_to_device=False
    )
    args2 = apply_recipient_to_device_args(
        {"text": "x", "recipient_person_id": "usr_should_drop"}, r2
    )
    check("apply:self_no_pid", "recipient_person_id" not in args2)


def test_device_route_with_name():
    print("\n== 设备路由集成 ==")

    class FakeMCP:
        def __init__(self):
            self.tools = {"note_add"}

        def has_tool(self, n):
            return n in self.tools or n.replace(".", "_") in self.tools

    class FakeMsg:
        def __init__(self, c):
            self.role = "user"
            self.content = c

    class FakeDialogue:
        def __init__(self, t):
            self.dialogue = [FakeMsg(t)]

    class FakeConn:
        def __init__(self):
            self.device_id = "dev"
            self.session_id = "s"
            self.headers = {"device-id": "dev"}
            self.mcp_client = FakeMCP()
            self.dialogue = FakeDialogue("两分钟后提醒小明喝水")
            self.config = {
                "server": {
                    "auth_key": "k",
                    "face": {"account_id": "acct_a"},
                }
            }

    async def _run():
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from core.utils.remind_time import RemindTimeParseResult, SHANGHAI
        from core.utils.recipient_resolver import RecipientResolution

        conn = FakeConn()
        expected_at = int(datetime(2026, 8, 2, 21, 2, 0, tzinfo=SHANGHAI).timestamp())

        # 重名 → 追问且不调设备
        with patch(
            "core.utils.device_reminder.call_device_note_add", new_callable=AsyncMock
        ) as mock_call, patch(
            "core.utils.device_reminder.parse_remind_time",
            return_value=RemindTimeParseResult(
                remind_at=expected_at,
                local_dt=datetime(2026, 8, 2, 21, 2, 0, tzinfo=SHANGHAI),
                source_expr="两分钟后",
            ),
        ), patch(
            "core.utils.device_reminder.unix_seconds", return_value=expected_at - 120
        ), patch(
            "core.utils.device_reminder.resolve_recipient_for_conn",
            new=AsyncMock(
                return_value=RecipientResolution(
                    code=RecipientResultCode.AMBIGUOUS,
                    selector_type="explicit_name",
                    message="姓名存在歧义",
                )
            ),
        ):
            resp = await maybe_intercept_reminder_tool(
                conn,
                "add_reminder",
                {"text": "两分钟后提醒小明喝水", "remind_time_str": "两分钟后"},
            )
            check(
                "route:ambiguous_ask",
                resp is not None
                and resp.action == Action.REQLLM
                and "歧义" in (resp.result or ""),
            )
            check("route:ambiguous_no_device", mock_call.await_count == 0)

        # 精确命中 → 下发 usr_*
        with patch(
            "core.utils.device_reminder.call_device_note_add", new_callable=AsyncMock
        ) as mock_call, patch(
            "core.utils.device_reminder.parse_remind_time",
            return_value=RemindTimeParseResult(
                remind_at=expected_at,
                local_dt=datetime(2026, 8, 2, 21, 2, 0, tzinfo=SHANGHAI),
                source_expr="两分钟后",
            ),
        ), patch(
            "core.utils.device_reminder.unix_seconds", return_value=expected_at - 120
        ), patch(
            "core.utils.device_reminder.resolve_recipient_for_conn",
            new=AsyncMock(
                return_value=RecipientResolution(
                    code=RecipientResultCode.RESOLVED,
                    selector_type="explicit_name",
                    recipient_person_id="usr_ccc333",
                    recipient_display_name="小红",
                    attach_to_device=True,
                )
            ),
        ):
            mock_call.return_value = "ok"
            resp = await maybe_intercept_reminder_tool(
                conn,
                "add_reminder",
                {
                    "text": "两分钟后提醒小红喝水",
                    "remind_time_str": "两分钟后",
                    "recipient_name": "小红",
                },
            )
            check(
                "route:named_success",
                resp is not None and "设备定时提醒已创建成功" in (resp.result or ""),
            )
            args = mock_call.await_args.args[1]
            check("route:named_usr", args.get("recipient_person_id") == "usr_ccc333")
            check(
                "route:named_display",
                args.get("recipient_display_name") == "小红",
            )
            check("route:future_remind_at", args.get("remind_at") == expected_at)

        # 儿子 → 追问
        with patch(
            "core.utils.device_reminder.call_device_note_add", new_callable=AsyncMock
        ) as mock_call, patch(
            "core.utils.device_reminder.parse_remind_time",
            return_value=RemindTimeParseResult(
                remind_at=expected_at,
                local_dt=datetime(2026, 8, 2, 21, 2, 0, tzinfo=SHANGHAI),
                source_expr="两分钟后",
            ),
        ), patch(
            "core.utils.device_reminder.unix_seconds", return_value=expected_at - 120
        ), patch(
            "core.utils.device_reminder.resolve_recipient_for_conn",
            new=AsyncMock(
                return_value=RecipientResolution(
                    code=RecipientResultCode.RELATION_REFUSED,
                    selector_type="relation",
                    message="无法根据关系词",
                )
            ),
        ):
            resp = await maybe_intercept_reminder_tool(
                conn,
                "add_reminder",
                {"text": "两分钟后提醒儿子喝水", "remind_time_str": "两分钟后"},
            )
            check("route:relation_ask", resp is not None and mock_call.await_count == 0)

        # 有 note.add 时 add_reminder 不放行（不写 MySQL）
        resp = await maybe_intercept_reminder_tool(
            conn, "add_reminder", {"text": "x", "remind_time_str": "坏时间"}
        )
        check("route:no_mysql_bypass", resp is not None)

    asyncio.get_event_loop().run_until_complete(_run())


def main():
    test_normalize_and_self()
    test_exact_name()
    test_relation_and_person_id()
    test_cross_account()
    test_extract_and_apply()
    test_device_route_with_name()
    print(f"\n合计 PASS={len(PASS)} FAIL={len(FAIL)}")
    if FAIL:
        sys.exit(1)


if __name__ == "__main__":
    main()
