"""卡片语音操作路由测试。"""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.utils.card_action import (
    CardRouteResult,
    device_supports_legacy_card_action,
    device_supports_reminder_card_action,
    map_utterance_to_action,
    route_card_voice_action,
)


class TestCardActionMapping(unittest.TestCase):
    def test_map_primary(self):
        self.assertEqual(map_utterance_to_action("完成"), "primary")

    def test_map_secondary(self):
        self.assertEqual(map_utterance_to_action("稍后"), "secondary")

    def test_map_tertiary(self):
        self.assertEqual(map_utterance_to_action("不需要了"), "tertiary")

    def test_map_none(self):
        self.assertIsNone(map_utterance_to_action("今天天气怎么样"))


class TestCardActionRoute(unittest.IsolatedAsyncioTestCase):
    def _conn_with_tools(self):
        conn = MagicMock()
        conn.mcp_client = MagicMock()
        conn.mcp_client.available_tools = {
            "reminder.get_current": {},
            "reminder.action": {},
        }
        return conn

    def test_capability_missing(self):
        conn = MagicMock()
        conn.mcp_client = MagicMock()
        conn.mcp_client.available_tools = {}
        self.assertFalse(device_supports_reminder_card_action(conn))

    async def test_no_current_card(self):
        conn = self._conn_with_tools()
        with patch(
            "core.utils.card_action._call_device_tool",
            new=AsyncMock(return_value={"content": [{"text": "{}"}]}),
        ):
            result = await route_card_voice_action(conn, "完成")
        self.assertEqual(result.result, CardRouteResult.NO_CURRENT_CARD)

    async def test_success_primary(self):
        conn = self._conn_with_tools()

        async def _fake_tool(c, name, args, timeout=30.0):
            if name == "reminder.get_current":
                return {
                    "content": [
                        {
                            "text": '{"instance_id":"note:1:1","revision":2}'
                        }
                    ]
                }
            return {"isError": False}

        with patch("core.utils.card_action._call_device_tool", new=_fake_tool):
            result = await route_card_voice_action(conn, "完成")
        self.assertEqual(result.result, CardRouteResult.SUCCESS)
        self.assertIn("完成", result.message)

    async def test_version_conflict(self):
        conn = self._conn_with_tools()

        async def _fake_tool(c, name, args, timeout=30.0):
            if name == "reminder.get_current":
                return {
                    "content": [
                        {"text": '{"instance_id":"note:1:1","revision":2}'}
                    ]
                }
            return {"isError": True, "error": "version_conflict"}

        with patch("core.utils.card_action._call_device_tool", new=_fake_tool):
            result = await route_card_voice_action(conn, "稍后")
        self.assertEqual(result.result, CardRouteResult.VERSION_CONFLICT)


class TestCardActionNegative(unittest.TestCase):
    def test_not_done_yet_not_primary(self):
        self.assertIsNone(map_utterance_to_action("我还没完成"))

    def test_question_not_action(self):
        self.assertIsNone(map_utterance_to_action("这个提醒是什么意思？"))

    def test_explain_not_tertiary(self):
        self.assertIsNone(map_utterance_to_action("不需要你解释"))

    def test_compound_final_intent_complete(self):
        self.assertEqual(
            map_utterance_to_action("先别稍后，我要完成"), "primary"
        )


class TestCardActionNoCardNegative(unittest.IsolatedAsyncioTestCase):
    def _conn_with_tools(self):
        conn = MagicMock()
        conn.mcp_client = MagicMock()
        conn.mcp_client.available_tools = {
            "reminder.get_current": {},
            "reminder.action": {},
        }
        return conn

    async def test_no_card_never_calls_action(self):
        conn = self._conn_with_tools()
        calls = []

        async def _fake_tool(c, name, args, timeout=30.0):
            calls.append(name)
            return {"content": [{"text": "{}"}]}

        with patch("core.utils.card_action._call_device_tool", new=_fake_tool):
            result = await route_card_voice_action(conn, "完成")
        self.assertEqual(result.result, CardRouteResult.NO_CURRENT_CARD)
        self.assertEqual(calls, ["reminder.get_current"])


class TestCardActionDualRouting(unittest.IsolatedAsyncioTestCase):
    def _conn_both_tools(self):
        conn = MagicMock()
        conn.mcp_client = MagicMock()
        conn.mcp_client.available_tools = {
            "reminder.get_current": {},
            "reminder.action": {},
            "card.get_current": {},
            "card.action": {},
        }
        return conn

    def _conn_card_only(self):
        conn = MagicMock()
        conn.mcp_client = MagicMock()
        conn.mcp_client.available_tools = {
            "card.get_current": {},
            "card.action": {},
        }
        return conn

    async def test_reminder_capability_missing_does_not_fallback_to_card(self):
        conn = self._conn_both_tools()
        calls = []

        async def _fake_tool(c, name, args, timeout=30.0):
            calls.append(name)
            if name == "reminder.get_current":
                return {"isError": True, "error": "tool not found"}
            raise AssertionError(f"must not call legacy card tool: {name}")

        with patch("core.utils.card_action._call_device_tool", new=_fake_tool):
            result = await route_card_voice_action(conn, "完成")
        self.assertEqual(result.result, CardRouteResult.NO_CAPABILITY)
        self.assertEqual(calls, ["reminder.get_current"])
        self.assertNotIn("card.get_current", calls)
        self.assertNotIn("card.action", calls)

    async def test_version_conflict_does_not_fallback(self):
        conn = self._conn_both_tools()
        calls = []

        async def _fake_tool(c, name, args, timeout=30.0):
            calls.append(name)
            if name == "reminder.get_current":
                return {
                    "content": [
                        {"text": '{"instance_id":"note:1:1","revision":2}'}
                    ]
                }
            if name == "reminder.action":
                return {"isError": True, "error": "version_conflict"}
            raise AssertionError(f"unexpected tool call: {name}")

        with patch("core.utils.card_action._call_device_tool", new=_fake_tool):
            result = await route_card_voice_action(conn, "稍后")
        self.assertEqual(result.result, CardRouteResult.VERSION_CONFLICT)
        self.assertEqual(calls, ["reminder.get_current", "reminder.action"])

    async def test_card_only_device_no_longer_uses_card_path(self):
        conn = self._conn_card_only()
        self.assertFalse(device_supports_reminder_card_action(conn))
        self.assertTrue(device_supports_legacy_card_action(conn))
        calls = []

        async def _fake_tool(c, name, args, timeout=30.0):
            calls.append(name)
            raise AssertionError(f"must not call any device tool: {name}")

        with patch("core.utils.card_action._call_device_tool", new=_fake_tool):
            result = await route_card_voice_action(conn, "不需要了")
        self.assertEqual(result.result, CardRouteResult.NO_CAPABILITY)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
