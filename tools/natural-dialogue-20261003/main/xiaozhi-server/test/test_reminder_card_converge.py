"""服务端 card_* 收敛：模型过滤、禁止降级、reminder_action 校验（mock MCP）。"""

from __future__ import annotations

import json
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.providers.tools.base import ToolDefinition, ToolType
from core.providers.tools.device_mcp.mcp_executor import DeviceMCPExecutor
from core.utils.card_action import (
    CardRouteResult,
    remember_reminder_card_snapshot,
    route_card_voice_action,
)
from core.utils.device_reminder import (
    is_legacy_card_tool_name,
    maybe_intercept_reminder_tool,
)
from plugins_func.register import Action


def _openai_tool(name: str) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": f"mock {name}",
            "parameters": {"type": "object", "properties": {}},
        },
    }


class TestLegacyCardName(unittest.TestCase):
    def test_legacy_names(self):
        self.assertTrue(is_legacy_card_tool_name("card_get_current"))
        self.assertTrue(is_legacy_card_tool_name("card_action"))
        self.assertTrue(is_legacy_card_tool_name("card.get_current"))
        self.assertTrue(is_legacy_card_tool_name("card.action"))
        self.assertFalse(is_legacy_card_tool_name("reminder_get_current"))
        self.assertFalse(is_legacy_card_tool_name("reminder_action"))


class TestModelToolsFilter(unittest.TestCase):
    def test_card_filtered_reminder_kept(self):
        conn = MagicMock()
        conn.mcp_client = MagicMock()
        conn.mcp_client.get_available_tools.return_value = [
            _openai_tool("card_get_current"),
            _openai_tool("card_action"),
            _openai_tool("reminder_get_current"),
            _openai_tool("reminder_action"),
            _openai_tool("reminder_list_pending"),
            _openai_tool("reminder_begin_broadcast"),
            _openai_tool("reminder_next"),
            _openai_tool("reminder_stop_broadcast"),
            _openai_tool("note_add"),
        ]
        tools = DeviceMCPExecutor(conn).get_tools()
        names = set(tools.keys())
        self.assertNotIn("card_get_current", names)
        self.assertNotIn("card_action", names)
        for n in (
            "reminder_get_current",
            "reminder_action",
            "reminder_list_pending",
            "reminder_begin_broadcast",
            "reminder_next",
            "reminder_stop_broadcast",
        ):
            self.assertIn(n, names)
        # 设备侧仍可 has_tool；过滤只影响模型工具集
        self.assertIsInstance(tools["reminder_get_current"], ToolDefinition)
        self.assertEqual(tools["reminder_get_current"].tool_type, ToolType.DEVICE_MCP)


class TestReminderActionGuard(unittest.IsolatedAsyncioTestCase):
    def _conn(self):
        conn = MagicMock()
        conn.session_id = "sess-1"
        conn.device_id = "dev-1"
        conn.mcp_client = MagicMock()
        conn.current_speaker_user = None
        conn.current_present_user = None
        return conn

    async def test_empty_instance_id_not_sent(self):
        conn = self._conn()
        with patch(
            "core.providers.tools.device_mcp.mcp_handler.call_mcp_tool",
            new=AsyncMock(side_effect=AssertionError("must not call device")),
        ):
            resp = await maybe_intercept_reminder_tool(
                conn, "reminder_action", {"action": "primary", "revision": 1}
            )
        self.assertIsNotNone(resp)
        self.assertEqual(resp.action, Action.REQLLM)
        body = json.loads(resp.result)
        self.assertEqual(body["code"], "missing_instance_id")

    async def test_revision_zero_not_sent(self):
        conn = self._conn()
        remember_reminder_card_snapshot(
            conn, instance_id="note:1:1", revision=2, recipient_id="all"
        )
        resp = await maybe_intercept_reminder_tool(
            conn,
            "reminder_action",
            {"instance_id": "note:1:1", "revision": 0, "action": "primary"},
        )
        body = json.loads(resp.result)
        self.assertEqual(body["code"], "invalid_revision")

    async def test_instance_mismatch_not_sent(self):
        conn = self._conn()
        remember_reminder_card_snapshot(
            conn, instance_id="note:1:1", revision=2, recipient_id="all"
        )
        resp = await maybe_intercept_reminder_tool(
            conn,
            "reminder_action",
            {"instance_id": "note:9:9", "revision": 2, "action": "tertiary"},
        )
        body = json.loads(resp.result)
        self.assertEqual(body["code"], "instance_mismatch")

    async def test_revision_mismatch_not_sent(self):
        conn = self._conn()
        remember_reminder_card_snapshot(
            conn, instance_id="note:1:1", revision=2, recipient_id="all"
        )
        resp = await maybe_intercept_reminder_tool(
            conn,
            "reminder_action",
            {"instance_id": "note:1:1", "revision": 9, "action": "primary"},
        )
        body = json.loads(resp.result)
        self.assertEqual(body["code"], "revision_mismatch")

    async def test_need_get_current_first(self):
        conn = self._conn()
        resp = await maybe_intercept_reminder_tool(
            conn,
            "reminder_action",
            {"instance_id": "note:1:1", "revision": 1, "action": "primary"},
        )
        body = json.loads(resp.result)
        self.assertEqual(body["code"], "need_get_current")

    async def test_valid_action_passes_through(self):
        conn = self._conn()
        remember_reminder_card_snapshot(
            conn, instance_id="note:1:1", revision=3, recipient_id="all"
        )
        resp = await maybe_intercept_reminder_tool(
            conn,
            "reminder_action",
            {"instance_id": "note:1:1", "revision": 3, "action": "primary"},
        )
        self.assertIsNone(resp)

    async def test_legacy_card_action_rejected(self):
        conn = self._conn()
        resp = await maybe_intercept_reminder_tool(
            conn, "card_action", {"action": "primary"}
        )
        body = json.loads(resp.result)
        self.assertEqual(body["code"], "use_reminder_tools")


class TestVoiceReminderOnly(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_reads_then_acts_reminder_only(self):
        """语音取消：先 reminder.get_current 再 reminder.action，不碰 card。"""
        conn = MagicMock()
        conn.session_id = "sess-1"
        conn.device_id = "dev-1"
        conn.mcp_client = MagicMock()
        conn.mcp_client.available_tools = {
            "reminder.get_current": {},
            "reminder.action": {},
            "card.get_current": {},
            "card.action": {},
        }
        conn.current_speaker_user = None
        conn.current_present_user = None
        calls = []

        async def _fake_tool(c, name, args, timeout=30.0):
            calls.append((name, dict(args or {})))
            if name == "reminder.get_current":
                return {
                    "content": [
                        {
                            "text": (
                                '{"instance_id":"note:14:100","revision":4,'
                                '"recipient_person_id":"all"}'
                            )
                        }
                    ]
                }
            if name == "reminder.action":
                return {"ok": True}
            raise AssertionError(f"unexpected {name}")

        with patch("core.utils.card_action._call_device_tool", new=_fake_tool):
            result = await route_card_voice_action(conn, "取消")
        self.assertEqual(result.result, CardRouteResult.SUCCESS)
        self.assertEqual(result.tool_family, "reminder")
        self.assertEqual(
            [c[0] for c in calls],
            ["reminder.get_current", "reminder.action"],
        )
        self.assertEqual(calls[1][1]["instance_id"], "note:14:100")
        self.assertEqual(calls[1][1]["revision"], 4)
        self.assertEqual(calls[1][1]["action"], "tertiary")


if __name__ == "__main__":
    unittest.main()
