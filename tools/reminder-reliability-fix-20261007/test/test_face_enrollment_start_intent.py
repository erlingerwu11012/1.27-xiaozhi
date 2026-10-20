"""确定性启动录入人脸：不进入闲聊 / 无成功 TTS；固件本地 START 独占播报。"""

from __future__ import annotations

import os
import sys
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from plugins_func.register import Action
from core.utils.face_enrollment_start_intent import (
    ENROLL_STARTED_MARKER,
    START_TOOL,
    FaceEnrollStartResult,
    is_face_enroll_start_tool,
    match_face_enroll_start,
    normalize_start_utterance,
    route_face_enroll_start,
)
from core.utils.face_enrollment_cancel_intent import (
    CANCEL_TOOL,
    FaceEnrollCancelResult,
    match_face_enroll_cancel,
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


class MatchStartTests(unittest.TestCase):
    POSITIVES = (
        "录入人脸",
        "登记人脸",
        "添加人脸",
        "开始录入人脸",
        "帮我录入人脸",
        "我想录入人脸",
        "我要录入人脸",
        "请录入人脸",
        "请帮我登记人脸",
        "麻烦帮我添加人脸",
        "我想开始录入人脸",
        "帮我录入人脸吧",
        "可以帮我录入人脸吗",
    )

    NEGATIVES = (
        "识别人脸",
        "看看我是谁",
        "删除人脸",
        "取消录入人脸",
        "停止录入人脸",
        "不要录入人脸",
        "我不想录入人脸",
        "别录入人脸",
        "人脸录入完成了吗",
        "录入",
        "添加",
        "人脸",
        "请录入这个文件",
        # 额外回归：取消短句 / 非受控扩展
        "取消录入",
        "今天天气怎么样",
    )

    def test_required_positives(self):
        for phrase in self.POSITIVES:
            self.assertTrue(match_face_enroll_start(phrase), phrase)

    def test_required_negatives(self):
        for phrase in self.NEGATIVES:
            self.assertFalse(match_face_enroll_start(phrase), phrase)

    def test_whitespace_and_punct(self):
        self.assertTrue(match_face_enroll_start("  录入人脸。"))
        self.assertTrue(match_face_enroll_start("登记人脸！"))
        self.assertTrue(match_face_enroll_start("开始录入人脸？"))
        self.assertTrue(match_face_enroll_start("帮我录入人脸吧。"))
        self.assertEqual(normalize_start_utterance("添加人脸。。"), "添加人脸")

    def test_speaker_json_wrapper(self):
        for phrase in self.POSITIVES:
            wrapped = '{"speaker":"张三","content":"%s"}' % phrase
            self.assertTrue(match_face_enroll_start(wrapped), phrase)
        for phrase in ("取消录入人脸", "识别人脸", "请录入这个文件"):
            wrapped = '{"speaker":"李四","content":"%s"}' % phrase
            self.assertFalse(match_face_enroll_start(wrapped), phrase)

    def test_cancel_still_matches_separately(self):
        self.assertTrue(match_face_enroll_cancel("取消录入人脸"))
        self.assertFalse(match_face_enroll_start("取消录入人脸"))
        self.assertTrue(match_face_enroll_cancel("停止录入人脸"))
        self.assertFalse(match_face_enroll_start("停止录入人脸"))


class ToolNameTests(unittest.TestCase):
    def test_is_start_tool_aliases(self):
        self.assertTrue(is_face_enroll_start_tool("camera.face.enroll.start"))
        self.assertTrue(is_face_enroll_start_tool("camera_face_enroll_start"))
        self.assertTrue(is_face_enroll_start_tool("self.camera.face.enroll.start"))
        self.assertFalse(is_face_enroll_start_tool("camera.face.enroll.cancel"))
        self.assertFalse(is_face_enroll_start_tool("camera.open"))
        self.assertFalse(is_face_enroll_start_tool(""))


class RouteStartTests(unittest.IsolatedAsyncioTestCase):
    async def test_not_matched(self):
        conn = MagicMock()
        r = await route_face_enroll_start(conn, "识别人脸")
        self.assertEqual(r.result, FaceEnrollStartResult.NOT_MATCHED)

    async def test_success_silent_no_message(self):
        conn = MagicMock()
        mcp = MagicMock()
        mcp.available_tools = {START_TOOL: {}}
        mcp.has_tool = MagicMock(return_value=True)
        conn.mcp_client = mcp
        called = {}

        async def _fake_call(conn, mcp_client, tool_name, args="{}", timeout=30):
            called["tool"] = tool_name
            called["n"] = called.get("n", 0) + 1
            return "session ok"

        _install_fake_mcp_call(_fake_call)
        try:
            r = await route_face_enroll_start(conn, "录入人脸")
            self.assertEqual(r.result, FaceEnrollStartResult.SUCCESS)
            self.assertEqual(r.message, "")
            self.assertEqual(called.get("tool"), START_TOOL)
            self.assertEqual(called.get("n"), 1)
        finally:
            _uninstall_fake_mcp_call()

    async def test_tool_unavailable(self):
        conn = MagicMock()
        mcp = MagicMock()
        mcp.available_tools = {}
        mcp.has_tool = MagicMock(return_value=False)
        mcp.resolve_tool_name = MagicMock(return_value=None)
        conn.mcp_client = mcp

        async def _should_not_call(*a, **k):
            raise AssertionError("must not call MCP when tool unavailable")

        _install_fake_mcp_call(_should_not_call)
        try:
            r = await route_face_enroll_start(conn, "登记人脸")
            self.assertEqual(r.result, FaceEnrollStartResult.NO_CAPABILITY)
            self.assertTrue(r.message)
            self.assertNotIn("token", r.message.lower())
            self.assertNotIn("http", r.message.lower())
        finally:
            _uninstall_fake_mcp_call()

    async def test_no_mcp_client(self):
        conn = MagicMock()
        conn.mcp_client = None
        r = await route_face_enroll_start(conn, "添加人脸")
        self.assertEqual(r.result, FaceEnrollStartResult.NO_CAPABILITY)
        self.assertTrue(r.message)

    async def test_tool_error_not_silent_success(self):
        conn = MagicMock()
        mcp = MagicMock()
        mcp.available_tools = {START_TOOL: {}}
        conn.mcp_client = mcp

        async def _boom(*a, **k):
            raise RuntimeError("internal boom with token=secret")

        _install_fake_mcp_call(_boom)
        try:
            r = await route_face_enroll_start(conn, "开始录入人脸")
            self.assertEqual(r.result, FaceEnrollStartResult.TOOL_ERROR)
            self.assertNotEqual(r.result, FaceEnrollStartResult.SUCCESS)
            self.assertTrue(r.message)
            self.assertNotIn("secret", r.message)
            self.assertNotIn("token", r.message.lower())
        finally:
            _uninstall_fake_mcp_call()

    async def test_timeout(self):
        conn = MagicMock()
        mcp = MagicMock()
        mcp.available_tools = {START_TOOL: {}}
        conn.mcp_client = mcp

        async def _to(*a, **k):
            raise TimeoutError("timeout")

        _install_fake_mcp_call(_to)
        try:
            r = await route_face_enroll_start(conn, "录入人脸")
            self.assertEqual(r.result, FaceEnrollStartResult.TIMEOUT)
        finally:
            _uninstall_fake_mcp_call()

    async def test_short_circuits_before_intent_chat(self):
        conn = MagicMock()
        mcp = MagicMock()
        mcp.available_tools = {START_TOOL: {}}
        conn.mcp_client = mcp
        intent_called = {"n": 0}
        chat_called = {"n": 0}

        async def fake_intent(*a, **k):
            intent_called["n"] += 1
            return False

        def fake_chat(*a, **k):
            chat_called["n"] += 1

        async def _ok(*a, **k):
            return "ok"

        _install_fake_mcp_call(_ok)
        try:
            text = "录入人脸"
            start = await route_face_enroll_start(conn, text)
            self.assertEqual(start.result, FaceEnrollStartResult.SUCCESS)
            if start.result != FaceEnrollStartResult.NOT_MATCHED:
                pass
            else:
                await fake_intent(conn, text)
                fake_chat(text)
            self.assertEqual(intent_called["n"], 0)
            self.assertEqual(chat_called["n"], 0)
        finally:
            _uninstall_fake_mcp_call()


class CancelNoRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_still_speaks_on_success(self):
        conn = MagicMock()
        mcp = MagicMock()
        mcp.available_tools = {CANCEL_TOOL: {}}
        conn.mcp_client = mcp

        async def _ok(*a, **k):
            return {"ok": True}

        _install_fake_mcp_call(_ok)
        try:
            r = await route_face_enroll_cancel(conn, "取消录入人脸")
            self.assertEqual(r.result, FaceEnrollCancelResult.SUCCESS)
            self.assertEqual(r.message, "好的，已取消人脸录入。")
        finally:
            _uninstall_fake_mcp_call()


class DeviceMCPExecutorStartSilentTests(unittest.IsolatedAsyncioTestCase):
    async def test_enroll_start_success_returns_action_none(self):
        from core.providers.tools.device_mcp.mcp_executor import DeviceMCPExecutor

        conn = MagicMock()
        mcp = MagicMock()
        mcp.is_ready = AsyncMock(return_value=True)
        conn.mcp_client = mcp
        executor = DeviceMCPExecutor(conn)

        async def _ok(*a, **k):
            return "firmware started whatever text"

        with patch(
            "core.providers.tools.device_mcp.mcp_executor.call_mcp_tool",
            new=_ok,
        ):
            resp = await executor.execute(conn, START_TOOL, {})
        self.assertEqual(resp.action, Action.NONE)
        self.assertEqual(resp.result, ENROLL_STARTED_MARKER)

    async def test_enroll_start_failure_not_none(self):
        from core.providers.tools.device_mcp.mcp_executor import DeviceMCPExecutor

        conn = MagicMock()
        mcp = MagicMock()
        mcp.is_ready = AsyncMock(return_value=True)
        conn.mcp_client = mcp
        executor = DeviceMCPExecutor(conn)

        async def _boom(*a, **k):
            raise RuntimeError("device failed")

        with patch(
            "core.providers.tools.device_mcp.mcp_executor.call_mcp_tool",
            new=_boom,
        ):
            resp = await executor.execute(conn, START_TOOL, {})
        self.assertNotEqual(resp.action, Action.NONE)
        self.assertEqual(resp.action, Action.ERROR)

    async def test_other_mcp_tool_still_reqllm(self):
        from core.providers.tools.device_mcp.mcp_executor import DeviceMCPExecutor

        conn = MagicMock()
        mcp = MagicMock()
        mcp.is_ready = AsyncMock(return_value=True)
        conn.mcp_client = mcp
        executor = DeviceMCPExecutor(conn)

        async def _ok(*a, **k):
            return "camera opened"

        with patch(
            "core.providers.tools.device_mcp.mcp_executor.call_mcp_tool",
            new=_ok,
        ):
            resp = await executor.execute(conn, "camera.open", {})
        self.assertEqual(resp.action, Action.REQLLM)
        self.assertIn("camera opened", str(resp.result))


class HandleFunctionResultNoneTests(unittest.TestCase):
    def test_action_none_skips_second_chat_and_tts(self):
        """Action.NONE 不进入 need_llm_tools，故无二轮 chat / speak。"""
        from plugins_func.register import ActionResponse

        chat_called = {"n": 0}
        speak_called = {"n": 0}

        class FakeConn:
            def __init__(self):
                self.dialogue = MagicMock()
                self.logger = MagicMock()

            def chat(self, *a, **k):
                chat_called["n"] += 1

            def _handle_function_result(self, tool_results, depth, preceding_content=""):
                # 复制 connection._handle_function_result 的分支语义（精简）
                need_llm_tools = []
                for result, tool_call_data in tool_results:
                    if result.action in (
                        Action.RESPONSE,
                        Action.NOTFOUND,
                        Action.ERROR,
                    ):
                        speak_called["n"] += 1
                    elif result.action == Action.REQLLM:
                        need_llm_tools.append((result, tool_call_data))
                    else:
                        pass
                if need_llm_tools:
                    self.chat(None, depth=depth + 1)

        conn = FakeConn()
        tool_results = [
            (
                ActionResponse(action=Action.NONE, result=ENROLL_STARTED_MARKER),
                {"id": "1", "name": START_TOOL, "arguments": "{}"},
            )
        ]
        conn._handle_function_result(tool_results, depth=0)
        self.assertEqual(chat_called["n"], 0)
        self.assertEqual(speak_called["n"], 0)


class StartToChatWiringTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_success_no_speak_txt(self):
        """模拟 startToChat 片段：成功不 speak，且不进 intent/chat。"""
        conn = MagicMock()
        mcp = MagicMock()
        mcp.available_tools = {START_TOOL: {}}
        conn.mcp_client = mcp
        speak_n = {"n": 0}
        intent_n = {"n": 0}
        chat_n = {"n": 0}

        async def _ok(*a, **k):
            return "ok"

        def fake_speak(c, text):
            speak_n["n"] += 1

        _install_fake_mcp_call(_ok)
        try:
            start = await route_face_enroll_start(conn, "录入人脸")
            self.assertEqual(start.result, FaceEnrollStartResult.SUCCESS)
            if start.result != FaceEnrollStartResult.NOT_MATCHED:
                if start.message:
                    fake_speak(conn, start.message)
            else:
                intent_n["n"] += 1
                chat_n["n"] += 1
            self.assertEqual(speak_n["n"], 0)
            self.assertEqual(intent_n["n"], 0)
            self.assertEqual(chat_n["n"], 0)
        finally:
            _uninstall_fake_mcp_call()

    async def test_start_failure_does_speak_safe_message(self):
        conn = MagicMock()
        mcp = MagicMock()
        mcp.available_tools = {START_TOOL: {}}
        conn.mcp_client = mcp
        spoken = []

        async def _boom(*a, **k):
            raise RuntimeError("x")

        def fake_speak(c, text):
            spoken.append(text)

        _install_fake_mcp_call(_boom)
        try:
            start = await route_face_enroll_start(conn, "录入人脸")
            self.assertEqual(start.result, FaceEnrollStartResult.TOOL_ERROR)
            if start.message:
                fake_speak(conn, start.message)
            self.assertEqual(len(spoken), 1)
            self.assertIn("失败", spoken[0])
        finally:
            _uninstall_fake_mcp_call()

    async def test_send_stt_message_start_tts_false_skips_tts_start(self):
        from core.handle.sendAudioHandle import send_stt_message

        conn = MagicMock()
        conn.session_id = "s1"
        conn.config = {}
        conn.current_speaker = None
        with patch(
            "core.handle.sendAudioHandle._device_send", new=AsyncMock()
        ) as send, patch(
            "core.handle.sendAudioHandle.send_tts_message", new=AsyncMock()
        ) as tts:
            await send_stt_message(conn, "录入人脸", start_tts=False)
            send.assert_awaited()
            tts.assert_not_called()

    async def test_startToChat_silent_success_skips_tts_start(self):
        from core.handle.receiveAudioHandle import startToChat
        from core.utils.card_action import CardRouteResult

        conn = MagicMock()
        conn.need_bind = False
        conn.max_output_size = 0
        conn.client_is_speaking = False
        conn.client_listen_mode = "auto"
        conn.current_speaker = None
        conn.logger = MagicMock()
        conn.logger.bind.return_value = conn.logger
        mcp = MagicMock()
        mcp.available_tools = {START_TOOL: {}}
        conn.mcp_client = mcp
        stt = AsyncMock()
        card = MagicMock()
        card.result = CardRouteResult.NOT_MATCHED

        async def _ok(*a, **k):
            return "ok"

        _install_fake_mcp_call(_ok)
        try:
            with patch(
                "core.utils.proactive_return.handle_proactive_return",
                new=AsyncMock(return_value=False),
            ), patch(
                "core.utils.proactive_greeting.handle_proactive_greeting",
                new=AsyncMock(return_value=False),
            ), patch(
                "core.utils.card_action.route_card_voice_action",
                new=AsyncMock(return_value=card),
            ), patch(
                "core.handle.receiveAudioHandle.send_stt_message",
                new=stt,
            ), patch(
                "core.handle.intentHandler.speak_txt",
            ) as speak:
                await startToChat(conn, "录入人脸")
                stt.assert_awaited()
                self.assertFalse(stt.await_args.kwargs.get("start_tts", True))
                speak.assert_not_called()
        finally:
            _uninstall_fake_mcp_call()


if __name__ == "__main__":
    unittest.main()
