"""Stage 0 contract capture at SDK/network send boundaries.

Mocks only. Does not read real keys, save customer history, or call paid APIs.
Random IDs may be masked; messages/tools/arguments values are asserted.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _ROOT)

import config.config_loader as config_loader


def _offline_config(config):
    local = dict(config)
    local["read_config_from_api"] = False
    return local


config_loader.get_config_from_api = _offline_config

from core.connection import ConnectionHandler
from core.providers.llm.openai.openai import LLMProvider
from core.providers.tools.device_mcp.mcp_client import MCPClient
from core.providers.tools.device_mcp.mcp_executor import DeviceMCPExecutor
from core.providers.tts.qwen_audio_tts_plus import TTSProvider
from core.utils.dialogue import Dialogue, Message
from core.utils.face_enrollment_start_intent import ENROLL_STARTED_MARKER, START_TOOL
from plugins_func.register import Action, ActionResponse
from core.providers.tts.dto.dto import ContentType, SentenceType


NOT_SENT_BY_DEFAULT = ("tool_choice", "response_format", "stream_options")

GOLDEN_ARGUMENTS = {
    "nested": {"room": "客厅", "meta": {"id": "usr_Ab12"}},
    "flag": True,
    "missing": None,
    "empty": "",
    "tags": ["提醒", "a\"b"],
    "when": "2026-09-16T15:00:00+08:00",
    "url": "https://example.com/path?x=1",
    "long": "中文" * 80,
}


def _mask_id(value):
    if isinstance(value, str) and len(value) >= 8:
        return "<id>"
    return value


class FakeCompletions:
    def __init__(self, capture, stream_chunks=None, non_stream=None):
        self.capture = capture
        self.stream_chunks = stream_chunks or []
        self.non_stream = non_stream

    def create(self, **kwargs):
        self.capture.append(dict(kwargs))
        if kwargs.get("stream"):
            return list(self.stream_chunks)
        return self.non_stream


def _provider(capture, *, aimi=False, stream_chunks=None, non_stream=None):
    with patch("core.providers.llm.openai.openai.openai.OpenAI"):
        provider = LLMProvider(
            {
                "model_name": "qwen-plus",
                "api_key": "sk-test-not-real",
                "base_url": "http://127.0.0.1:9/v1",
                "aimi_device_gateway": aimi,
                "aimi_device_service_key": "svc-test" if aimi else "",
                "temperature": 0.7,
                "max_tokens": 500,
            }
        )
    provider.client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=FakeCompletions(capture, stream_chunks, non_stream)
        )
    )
    provider._create_with_retry = lambda **kwargs: provider.client.chat.completions.create(
        **kwargs
    )
    if aimi:
        provider.set_aimi_device_context(
            {
                "session_id": "sess-1",
                "device_id": "dev-1",
                "mac_address": "aa:bb:cc:dd:ee:ff",
                "user_id": "u-1",
            }
        )
    return provider


class LlmRequestContractTests(unittest.TestCase):
    def test_plain_chat_sends_model_messages_stream_only(self):
        capture = []
        chunk = SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content="你好"), finish_reason=None)],
            usage=None,
            id="chatcmpl-1",
        )
        provider = _provider(capture, stream_chunks=[chunk])
        messages = [
            {"role": "system", "content": "角色设定"},
            {"role": "user", "content": "今天天气怎么样"},
        ]
        out = "".join(provider.response("sess-1", messages))
        self.assertEqual(out, "你好")
        self.assertEqual(len(capture), 1)
        req = capture[0]
        self.assertEqual(req["model"], "qwen-plus")
        self.assertEqual(req["messages"], messages)
        self.assertTrue(req["stream"])
        self.assertNotIn("tools", req)
        for name in NOT_SENT_BY_DEFAULT:
            self.assertNotIn(name, req)
        self.assertEqual(req["temperature"], 0.7)
        self.assertEqual(req["max_tokens"], 500)

    def test_tools_request_keeps_schema_and_omits_new_fields(self):
        capture = []
        delta = SimpleNamespace(
            content=None,
            tool_calls=None,
        )
        chunk = SimpleNamespace(
            choices=[SimpleNamespace(delta=delta, finish_reason=None)],
            usage=None,
            id="chatcmpl-2",
        )
        provider = _provider(capture, stream_chunks=[chunk])
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "camera_open",
                    "description": "打开摄像头",
                    "parameters": {
                        "type": "object",
                        "properties": {"duration": {"type": "number"}},
                        "required": ["duration"],
                    },
                },
            }
        ]
        messages = [{"role": "user", "content": "打开摄像头"}]
        list(provider.response_with_functions("sess-1", messages, functions=tools))
        req = capture[0]
        self.assertEqual(req["model"], "qwen-plus")
        self.assertEqual(req["messages"], messages)
        self.assertTrue(req["stream"])
        self.assertEqual(req["tools"], tools)
        for name in NOT_SENT_BY_DEFAULT:
            self.assertNotIn(name, req)

    def test_aimi_non_stream_and_headers(self):
        capture = []
        message = SimpleNamespace(content="AIMI应答", tool_calls=None)
        non_stream = SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=None, id="n1")
        provider = _provider(capture, aimi=True, non_stream=non_stream)
        out = list(provider.response("sess-1", [{"role": "user", "content": "hi"}]))
        self.assertEqual(out, ["AIMI应答"])
        req = capture[0]
        self.assertFalse(req["stream"])
        headers = req["extra_headers"]
        self.assertEqual(headers["X-AIMI-Device-Service-Key"], "svc-test")
        self.assertEqual(headers["X-AIMI-Device-ID"], "dev-1")
        self.assertTrue(headers["X-Request-ID"].startswith("xiaozhi-sess-1-"))
        for name in NOT_SENT_BY_DEFAULT:
            self.assertNotIn(name, req)


class ToolMergeAndResultTests(unittest.TestCase):
    def test_fragmented_arguments_concat_then_json(self):
        handler = ConnectionHandler.__new__(ConnectionHandler)
        collected = []
        parts = [
            SimpleNamespace(
                index=0,
                id="call_abc",
                function=SimpleNamespace(name="make_reminder", arguments='{"nested":'),
            ),
            SimpleNamespace(
                index=0,
                id=None,
                function=SimpleNamespace(name=None, arguments=json.dumps(GOLDEN_ARGUMENTS)[len('{"nested":'):]),
            ),
        ]
        handler._merge_tool_calls(collected, parts[:1])
        handler._merge_tool_calls(collected, parts[1:])
        self.assertEqual(collected[0]["id"], "call_abc")
        self.assertEqual(collected[0]["name"], "make_reminder")
        parsed = json.loads(collected[0]["arguments"])
        self.assertEqual(parsed["nested"]["room"], "客厅")
        self.assertIs(parsed["flag"], True)
        self.assertIsNone(parsed["missing"])
        self.assertEqual(parsed["empty"], "")
        self.assertEqual(parsed["tags"], ["提醒", 'a"b'])
        self.assertEqual(parsed["when"], "2026-09-16T15:00:00+08:00")
        self.assertEqual(parsed["url"], "https://example.com/path?x=1")
        self.assertEqual(parsed["long"], "中文" * 80)

    def test_reqllm_keeps_tool_call_id_and_recurses(self):
        handler = ConnectionHandler.__new__(ConnectionHandler)
        handler.dialogue = Dialogue()
        handler.logger = MagicMock()
        handler.logger.bind.return_value = handler.logger
        chats = []
        handler.chat = lambda query, depth=0, **kwargs: chats.append((query, depth))
        tool_id = "call_keep"
        handler._handle_function_result(
            [
                (
                    ActionResponse(action=Action.REQLLM, result='{"ok":true}'),
                    {"id": tool_id, "name": "camera_open", "arguments": '{"duration":1}'},
                )
            ],
            depth=0,
        )
        self.assertEqual(chats, [(None, 1)])
        roles = [(m.role, m.tool_call_id) for m in handler.dialogue.dialogue]
        self.assertEqual(roles[0][0], "assistant")
        self.assertEqual(handler.dialogue.dialogue[0].tool_calls[0]["id"], tool_id)
        self.assertEqual(roles[1], ("tool", tool_id))

    def test_none_is_silent(self):
        handler = ConnectionHandler.__new__(ConnectionHandler)
        handler.dialogue = Dialogue()
        handler.logger = MagicMock()
        handler.logger.bind.return_value = handler.logger
        handler.chat = MagicMock()
        with patch("core.handle.sendAudioHandle.speak_text_with_subtitle") as speak:
            handler._handle_function_result(
                [
                    (
                        ActionResponse(action=Action.NONE, result=ENROLL_STARTED_MARKER),
                        {"id": "1", "name": START_TOOL, "arguments": "{}"},
                    )
                ],
                depth=0,
            )
        speak.assert_not_called()
        handler.chat.assert_not_called()
        self.assertEqual(handler.dialogue.dialogue, [])

    def test_response_error_notfound_speak_without_second_llm(self):
        handler = ConnectionHandler.__new__(ConnectionHandler)
        handler.dialogue = Dialogue()
        handler.logger = MagicMock()
        handler.logger.bind.return_value = handler.logger
        handler.chat = MagicMock()
        spoken = []
        with patch(
            "core.handle.sendAudioHandle.speak_text_with_subtitle",
            side_effect=lambda conn, text, **kwargs: spoken.append(text),
        ):
            for action, text in (
                (Action.RESPONSE, "直接回复"),
                (Action.ERROR, "出错了"),
                (Action.NOTFOUND, "没找到"),
            ):
                handler._handle_function_result(
                    [(ActionResponse(action=action, response=text), {"id": "x", "name": "t", "arguments": "{}"})],
                    depth=1,
                )
        self.assertEqual(spoken, ["直接回复", "出错了", "没找到"])
        handler.chat.assert_not_called()


class ChatBufferContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.loop = asyncio.new_event_loop()
        cls.loop_thread = threading.Thread(target=cls.loop.run_forever, daemon=True)
        cls.loop_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.loop.call_soon_threadsafe(cls.loop.stop)
        cls.loop_thread.join(timeout=2)

    def _handler(self, *, functions, llm_iter):
        handler = ConnectionHandler.__new__(ConnectionHandler)
        handler.intent_type = "function_call"
        handler.func_handler = SimpleNamespace(get_functions=lambda: functions)
        handler.llm = SimpleNamespace(
            response_with_functions=lambda session_id, messages, functions=None: llm_iter,
            response=lambda session_id, messages: llm_iter,
        )
        handler.dialogue = Dialogue()
        handler.dialogue.put(Message(role="system", content="角色设定"))
        handler.memory = None
        handler.config = {"voiceprint": {}, "selected_module": {}, "ASR": {}}
        handler.session_id = "sess-chat"
        handler.sentence_id = None
        handler.tts = object()
        handler.tts_MessageText = None
        handler.client_abort = False
        handler.llm_finish_task = False
        handler.logger = MagicMock()
        handler.logger.bind.return_value = handler.logger
        handler.loop = self.loop
        handler.pending_touch_prompt = None
        handler.inject_emotion_hint = False
        handler.speech_turn_result = None
        handler.tts_events = []
        handler.enqueue_tts = lambda dto: handler.tts_events.append(
            (dto.sentence_type, dto.content_type, getattr(dto, "content_detail", None))
        )
        handler._send_fallback_voice = lambda text: None
        return handler

    def test_plain_chat_without_tools_streams_tts(self):
        handler = self._handler(functions=None, llm_iter=["你", "好"])
        handler.intent_type = "nointent"
        handler.chat("今天好吗")
        texts = [e[2] for e in handler.tts_events if e[1] == ContentType.TEXT]
        self.assertEqual(texts, ["你", "好"])

    def test_tools_present_buffer_until_no_tool_call(self):
        handler = self._handler(
            functions=[{"type": "function"}],
            llm_iter=[("先缓冲", None), ("全文", None)],
        )
        handler.chat("闲聊一句")
        texts = [e[2] for e in handler.tts_events if e[1] == ContentType.TEXT]
        self.assertEqual(texts, ["先缓冲全文"])

    def test_depth_limit_disables_tools(self):
        handler = self._handler(functions=[{"type": "function"}], llm_iter=["最终回答"])
        calls = []

        def response(session_id, messages):
            calls.append(("response", [m.get("role") for m in messages]))
            yield "最终回答"

        def response_with_functions(*_a, **_k):
            calls.append("with_functions")
            yield ("x", None)

        handler.llm.response = response
        handler.llm.response_with_functions = response_with_functions
        handler.chat(None, depth=5)
        self.assertEqual(calls[0][0], "response")
        self.assertNotIn("with_functions", calls)


class McpSendContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_tools_call_payload_preserves_argument_types(self):
        captured = []

        async def fake_send(conn, payload):
            captured.append(payload)
            call_id = payload["id"]
            await conn.mcp_client.resolve_call_result(
                call_id, {"content": [{"text": '{"ok":true}'}]}
            )

        client = MCPClient(device_id="dev-mcp", session_id="sess-mcp")
        await client.add_tool(
            {
                "name": "camera.open",
                "description": "open",
                "inputSchema": {"type": "object", "properties": {}},
            }
        )
        await client.set_ready(True)
        conn = SimpleNamespace(
            mcp_client=client,
            features={"mcp": True},
            device_id="dev-mcp",
            session_id="sess-mcp",
            headers={"device-id": "dev-mcp"},
            logger=MagicMock(),
            last_activity_time=0,
        )
        conn.logger.bind.return_value = conn.logger
        with patch(
            "core.providers.tools.device_mcp.mcp_handler.send_mcp_message",
            new=fake_send,
        ):
            from core.providers.tools.device_mcp.mcp_handler import call_mcp_tool

            await call_mcp_tool(conn, client, "camera.open", json.dumps(GOLDEN_ARGUMENTS))
        self.assertEqual(len(captured), 1)
        payload = captured[0]
        self.assertEqual(payload["jsonrpc"], "2.0")
        self.assertEqual(payload["method"], "tools/call")
        self.assertEqual(payload["params"]["name"], "camera.open")
        args = payload["params"]["arguments"]
        self.assertEqual(args["nested"]["room"], "客厅")
        self.assertIs(args["flag"], True)
        self.assertIsNone(args["missing"])
        self.assertEqual(args["empty"], "")
        self.assertEqual(args["tags"][1], 'a"b')
        self.assertIsInstance(payload["id"], int)

    async def test_face_enroll_success_is_action_none(self):
        conn = MagicMock()
        conn.mcp_client.is_ready = AsyncMock(return_value=True)
        executor = DeviceMCPExecutor(conn)

        async def _ok(*_a, **_k):
            return json.dumps({"accepted": True, "state": "accepted"})

        with patch(
            "core.providers.tools.device_mcp.mcp_executor.call_mcp_tool",
            new=_ok,
        ):
            resp = await executor.execute(conn, START_TOOL, {})
        self.assertEqual(resp.action, Action.NONE)
        self.assertEqual(resp.result, ENROLL_STARTED_MARKER)


class TtsTaskContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_continue_finish_same_task_id(self):
        class FakeWS:
            def __init__(self):
                self.incoming = asyncio.Queue()
                self.outgoing = asyncio.Queue()

            async def send(self, data):
                await self.outgoing.put(data)

            async def recv(self):
                return await self.incoming.get()

            async def close(self):
                return None

        ws = FakeWS()
        conn = SimpleNamespace(
            loop=asyncio.get_running_loop(),
            session_id="sess-tts",
            sentence_id=uuid.uuid4().hex,
            stop_event=asyncio.Event(),
            client_abort=False,
            tts_abort_epoch=0,
            tts_MessageText=None,
            logger=MagicMock(),
        )
        conn.logger.bind.return_value = conn.logger
        async def _connect(url, headers):
            return ws

        provider = TTSProvider(
            {
                "api_key": "sk-test",
                "ws_url": "ws://127.0.0.1:3011/bailian/api-ws/v1/inference",
                "model": "qwen-audio-3.0-tts-plus",
                "voice": "longanlingxi",
                "sample_rate": 16000,
                "_connect": _connect,
            },
            True,
        )
        provider.conn = conn
        start = asyncio.create_task(provider.start_session(conn.sentence_id))
        run = json.loads(await asyncio.wait_for(ws.outgoing.get(), 1))
        self.assertEqual(run["header"]["action"], "run-task")
        task_id = run["header"]["task_id"]
        self.assertEqual(run["payload"]["parameters"]["voice"], "longanlingxi")
        self.assertEqual(run["payload"]["parameters"]["sample_rate"], 16000)
        await ws.incoming.put(json.dumps({"header": {"event": "task-started", "task_id": task_id}}))
        await start
        await provider.text_to_speak("你好**世界**", None)
        cont = json.loads(await asyncio.wait_for(ws.outgoing.get(), 1))
        self.assertEqual(cont["header"]["action"], "continue-task")
        self.assertEqual(cont["header"]["task_id"], task_id)
        self.assertEqual(cont["payload"]["input"]["text"], "你好世界")
        finish = asyncio.create_task(provider.finish_session(provider.task_id))
        fin = json.loads(await asyncio.wait_for(ws.outgoing.get(), 1))
        self.assertEqual(fin["header"]["action"], "finish-task")
        self.assertEqual(fin["header"]["task_id"], task_id)
        await ws.incoming.put(json.dumps({"header": {"event": "task-finished", "task_id": task_id}}))
        await finish


if __name__ == "__main__":
    unittest.main()
