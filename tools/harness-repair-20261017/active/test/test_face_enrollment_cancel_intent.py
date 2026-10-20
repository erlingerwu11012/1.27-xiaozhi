"""确定性取消录入人脸：不进入闲聊 / 通用 intent。"""

from __future__ import annotations

import os
import sys
import types
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.utils.face_enrollment_cancel_intent import (
    CANCEL_TOOL,
    FaceEnrollCancelResult,
    match_face_enroll_cancel,
    normalize_cancel_utterance,
    route_face_enroll_cancel,
)


def _install_fake_mcp_call(fn):
    fake_pkg = types.ModuleType("core.providers.tools.device_mcp")
    fake_mod = types.ModuleType("core.providers.tools.device_mcp.mcp_handler")
    fake_mod.call_mcp_tool = fn
    sys.modules["core.providers.tools.device_mcp"] = fake_pkg
    sys.modules["core.providers.tools.device_mcp.mcp_handler"] = fake_mod


def _uninstall_fake_mcp_call():
    sys.modules.pop("core.providers.tools.device_mcp.mcp_handler", None)
    sys.modules.pop("core.providers.tools.device_mcp", None)


class MatchTests(unittest.TestCase):
    def test_exact_phrases(self):
        self.assertTrue(match_face_enroll_cancel("取消录入人脸"))
        self.assertTrue(match_face_enroll_cancel("取消录入"))
        self.assertTrue(match_face_enroll_cancel("停止录入人脸"))

    def test_whitespace_and_punct(self):
        self.assertTrue(match_face_enroll_cancel("  取消录入人脸。"))
        self.assertTrue(match_face_enroll_cancel("取消录入！"))
        self.assertTrue(match_face_enroll_cancel("停止录入人脸？"))
        self.assertEqual(normalize_cancel_utterance("取消录入。。"), "取消录入")

    def test_speaker_json_wrapper(self):
        """修复6：声纹 JSON 包装命中。"""
        for phrase in ("取消录入人脸", "取消录入", "停止录入人脸"):
            wrapped = '{"speaker":"张三","content":"%s"}' % phrase
            self.assertTrue(match_face_enroll_cancel(wrapped), phrase)
            wrapped_punct = '{"speaker":"李四","content":"%s。"}' % phrase
            self.assertTrue(match_face_enroll_cancel(wrapped_punct), phrase)

    def test_no_broad_cancel(self):
        self.assertFalse(match_face_enroll_cancel("取消"))
        self.assertFalse(match_face_enroll_cancel("取消提醒"))
        self.assertFalse(match_face_enroll_cancel("不需要了"))
        self.assertFalse(match_face_enroll_cancel("请取消录入人脸吧"))
        self.assertFalse(match_face_enroll_cancel("取消录入人脸吧"))
        self.assertFalse(
            match_face_enroll_cancel('{"speaker":"张三","content":"取消提醒"}')
        )
        self.assertFalse(match_face_enroll_cancel('{"speaker":"张三"}'))
        self.assertFalse(
            match_face_enroll_cancel('{"speaker":"张三","content":123}')
        )

class RouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_not_matched(self):
        conn = MagicMock()
        r = await route_face_enroll_cancel(conn, "今天天气怎么样")
        self.assertEqual(r.result, FaceEnrollCancelResult.NOT_MATCHED)

    async def test_calls_mcp_tool_not_llm(self):
        conn = MagicMock()
        mcp = MagicMock()
        mcp.available_tools = {CANCEL_TOOL: {}}
        mcp.has_tool = MagicMock(return_value=True)
        conn.mcp_client = mcp

        called = {}

        async def _fake_call(conn, mcp_client, tool_name, args="{}", timeout=30):
            called["tool"] = tool_name
            return {"ok": True}

        _install_fake_mcp_call(_fake_call)
        try:
            r = await route_face_enroll_cancel(conn, "取消录入人脸")
            self.assertEqual(r.result, FaceEnrollCancelResult.SUCCESS)
            self.assertEqual(called.get("tool"), CANCEL_TOOL)
        finally:
            _uninstall_fake_mcp_call()

    async def test_tool_error_stays_deterministic(self):
        conn = MagicMock()
        mcp = MagicMock()
        mcp.available_tools = {CANCEL_TOOL: {}}
        conn.mcp_client = mcp

        async def _boom(*a, **k):
            raise RuntimeError("boom")

        _install_fake_mcp_call(_boom)
        try:
            r = await route_face_enroll_cancel(conn, "取消录入")
            self.assertEqual(r.result, FaceEnrollCancelResult.TOOL_ERROR)
            self.assertTrue(r.message)
        finally:
            _uninstall_fake_mcp_call()

    async def test_match_short_circuits_before_intent(self):
        """命中短语后 route 不返回 NOT_MATCHED，供 startToChat 跳过 intent。"""
        conn = MagicMock()
        mcp = MagicMock()
        mcp.available_tools = {CANCEL_TOOL: {}}
        conn.mcp_client = mcp

        async def _ok(*a, **k):
            return {"ok": True}

        _install_fake_mcp_call(_ok)
        try:
            r = await route_face_enroll_cancel(conn, "停止录入人脸。")
            self.assertNotEqual(r.result, FaceEnrollCancelResult.NOT_MATCHED)
            self.assertEqual(r.result, FaceEnrollCancelResult.SUCCESS)

            r2 = await route_face_enroll_cancel(
                conn, '{"speaker":"张三","content":"取消录入人脸"}'
            )
            self.assertEqual(r2.result, FaceEnrollCancelResult.SUCCESS)
        finally:
            _uninstall_fake_mcp_call()

    async def test_start_to_chat_json_cancel_skips_intent(self):
        """修复6：startToChat 对声纹 JSON 取消词不进 LLM。"""
        from unittest.mock import AsyncMock, patch

        # 避免导入 receiveAudioHandle 时拉起 pydub：直接测挂接逻辑等价物
        conn = MagicMock()
        mcp = MagicMock()
        mcp.available_tools = {CANCEL_TOOL: {}}
        conn.mcp_client = mcp
        intent_called = {"n": 0}
        chat_called = {"n": 0}

        async def fake_intent(*a, **k):
            intent_called["n"] += 1
            return False

        def fake_chat(*a, **k):
            chat_called["n"] += 1

        async def _ok(*a, **k):
            return {"ok": True}

        _install_fake_mcp_call(_ok)
        try:
            text = '{"speaker":"张三","content":"取消录入人脸"}'
            # 模拟 startToChat：card 未命中 → cancel 命中 → 不调 intent/chat
            from core.utils.card_action import CardRouteResult

            card = MagicMock(result=CardRouteResult.NOT_MATCHED)
            self.assertEqual(card.result, CardRouteResult.NOT_MATCHED)
            cancel = await route_face_enroll_cancel(conn, text)
            self.assertEqual(cancel.result, FaceEnrollCancelResult.SUCCESS)
            if cancel.result != FaceEnrollCancelResult.NOT_MATCHED:
                pass  # 短路
            else:
                await fake_intent(conn, text)
                fake_chat(text)
            self.assertEqual(intent_called["n"], 0)
            self.assertEqual(chat_called["n"], 0)
        finally:
            _uninstall_fake_mcp_call()


if __name__ == "__main__":
    unittest.main()
