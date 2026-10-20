"""Direct primary answer regression, synthetic inputs and mock upstream only."""
from __future__ import annotations

import asyncio
import copy
import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.connection import ConnectionHandler
from core.providers.tts.dto.dto import ContentType, SentenceType
from core.utils.dialogue import Dialogue, Message
from plugins_func.register import Action, ActionResponse


TOOLS = [{"type": "function", "function": {"name": "set_volume", "description": "音量", "parameters": {"type": "object", "properties": {"volume": {"type": "integer"}}, "required": ["volume"]}}}]


class PrimaryAnswerDirectTtsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.loop = asyncio.new_event_loop()
        cls.loop_thread = threading.Thread(target=cls.loop.run_forever, daemon=True)
        cls.loop_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.loop.call_soon_threadsafe(cls.loop.stop)
        cls.loop_thread.join(timeout=2)
        cls.loop.close()

    def setUp(self):
        for target, kwargs in [
            ("core.utils.trace_log.emit", {}),
            ("core.utils.person_identity.select_dialogue", {}),
            ("core.utils.turn_context.build_turn_context", {"return_value": {"current_datetime": "2026-10-03 00:00:00"}}),
        ]:
            p = patch(target, **kwargs)
            p.start()
            self.addCleanup(p.stop)

    def handler(self, *, functions=TOOLS, official=True, version="v2", finalization=None):
        h = ConnectionHandler.__new__(ConnectionHandler)
        h.config = {"voiceprint": {}, "prompt_pipeline": {"version": version}, "speech_expression": {}}
        if finalization is not None:
            h.config["speech_expression"]["finalization"] = finalization
        h.intent_type = "function_call" if functions is not None else "nointent"
        h.func_handler = SimpleNamespace(get_functions=lambda: copy.deepcopy(functions))
        h.memory = None
        h.session_id = "synthetic-direct-tts-session"
        h.device_id = "synthetic-device"
        h.agent_id = "synthetic-agent"
        h.listen_epoch = 1
        h.dialogue = Dialogue()
        h.dialogue.put(Message(role="system", content="合成测试角色"))
        h.tts = SimpleNamespace(official_enhanced=official)
        h.tts_MessageText = None
        h.sentence_id = None
        h.tts_abort_epoch = 0
        h.client_abort = False
        h.llm_finish_task = False
        h.loop = self.loop
        h.logger = MagicMock()
        h.logger.bind.return_value = h.logger
        h._consume_speech_emotion_hint = lambda: (None, None)
        h._send_fallback_voice = MagicMock()
        h.tts_events = []
        h.enqueue_tts = h.tts_events.append
        from core.utils.person_identity import PersonTurn
        h.actor = PersonTurn("synthetic-account","",0,1,"personal","unknown","synthetic-turn",h.device_id,h.agent_id,1)
        h.llm = SimpleNamespace(last_usage=None)
        return h

    def chat(self, h, text="合成问题"):
        return h.chat(text, _identity=h.actor)

    def text_events(self, h):
        return [e for e in h.tts_events if e.content_type == ContentType.TEXT]

    def assistants(self, h):
        return [m for m in h.dialogue.dialogue if m.role == "assistant" and not m.tool_calls]

    def primary_with_tools(self, h, pieces):
        h.llm.response_with_functions = MagicMock(return_value=iter([(p, None) for p in pieces]))
        h.llm.response = MagicMock(side_effect=AssertionError("unexpected second LLM call"))

    def test_primary_answer_is_spoken_and_archived_without_rewrite(self):
        h = self.handler()
        self.primary_with_tools(h, ["[excited]主模型", "原始答案。"])
        self.assertTrue(self.chat(h))
        h.llm.response_with_functions.assert_called_once()
        h.llm.response.assert_not_called()
        self.assertEqual([e.content_detail for e in self.text_events(h)], ["[excited]主模型原始答案。"])
        m, = self.assistants(h)
        self.assertEqual(m.content, "[excited]主模型原始答案。")
        self.assertEqual(m.caption_text, "主模型原始答案。")
        self.assertEqual(h.tts_MessageText, "主模型原始答案。")
        self.assertEqual([e.sentence_type for e in h.tts_events], [SentenceType.FIRST, SentenceType.MIDDLE, SentenceType.LAST])
        self.assertEqual(len({(e.sentence_id, e.abort_epoch) for e in h.tts_events}), 1)
        self.assertTrue(h.llm_finish_task)

    def test_old_finalization_config_cannot_restore_second_pass(self):
        for mode in (None, "legacy_two_pass", "integrated", "unexpected"):
            with self.subTest(mode=mode):
                h = self.handler(finalization=mode)
                self.primary_with_tools(h, ["直接回答"])
                self.assertTrue(self.chat(h))
                h.llm.response_with_functions.assert_called_once()
                h.llm.response.assert_not_called()
                self.assertEqual([e.content_detail for e in self.text_events(h)], ["直接回答"])

    def test_no_tools_streams_chunks_without_duplicate_full_answer(self):
        h = self.handler(functions=None)
        h.llm.response = MagicMock(return_value=iter(["先说", "后说"]))
        h.llm.response_with_functions = MagicMock(side_effect=AssertionError("unexpected tools"))
        self.assertTrue(self.chat(h))
        h.llm.response.assert_called_once()
        h.llm.response_with_functions.assert_not_called()
        self.assertEqual([e.content_detail for e in self.text_events(h)], ["先说", "后说"])
        self.assertEqual(self.assistants(h)[0].content, "先说后说")

    def test_empty_tools_catalog_does_not_add_rewrite(self):
        h = self.handler(functions=[])
        self.primary_with_tools(h, ["空目录回答"])
        self.assertTrue(self.chat(h))
        h.llm.response.assert_not_called()
        self.assertEqual([e.content_detail for e in self.text_events(h)], ["空目录回答"])

    def test_v1_caption_and_primary_tts_unchanged(self):
        h = self.handler(version="v1")
        self.primary_with_tools(h, ["[excited]原话"])
        self.assertTrue(self.chat(h))
        self.assertEqual(self.assistants(h)[0].content, "原话")
        self.assertEqual(self.assistants(h)[0].caption_text, "原话")
        self.assertEqual(self.text_events(h)[0].content_detail, "[excited]原话")
        h.llm.response.assert_not_called()

    def test_non_official_tts_receives_primary_text(self):
        h = self.handler(official=False)
        self.primary_with_tools(h, ["普通声音原话"])
        self.assertTrue(self.chat(h))
        self.assertEqual(self.text_events(h)[0].content_detail, "普通声音原话")
        h.llm.response.assert_not_called()

    def test_primary_history_is_kept_in_next_primary_request(self):
        h = self.handler()
        h.dialogue.put(Message(role="user", content="前一轮提问"))
        h.dialogue.put(Message(role="assistant", content="前一轮答案"))
        self.primary_with_tools(h, ["下一轮答案"])
        self.assertTrue(self.chat(h, "接着说"))
        messages = h.llm.response_with_functions.call_args.args[1]
        self.assertEqual(sum(m["role"] == "system" for m in messages), 1)
        self.assertTrue(any(m.get("content") == "前一轮答案" for m in messages))
        self.assertFalse(any("请把下面内容改写" in str(m.get("content")) for m in messages))

    def test_tool_executes_once_and_primary_continuation_spoken_once(self):
        h = self.handler()
        calls = []
        tc = SimpleNamespace(index=0, id="call-test", function=SimpleNamespace(name="set_volume", arguments='{"volume":50}'))

        def response(session_id, messages, functions=None):
            calls.append(copy.deepcopy(messages))
            if len(calls) == 1:
                yield ("正在处理", None)
                yield (None, [tc])
            else:
                yield ("[calm]音量已调到百分之五十。", None)

        async def execute(conn, tool):
            executions.append(copy.deepcopy(tool))
            return ActionResponse(action=Action.REQLLM, result='{"success":true,"volume":50}')

        executions = []
        h.llm.response_with_functions = MagicMock(side_effect=response)
        h.llm.response = MagicMock(side_effect=AssertionError("unexpected rewrite"))
        h.func_handler.handle_llm_function_call = execute
        self.assertTrue(self.chat(h, "把音量设为五十"))
        self.assertEqual(len(executions), 1)
        self.assertEqual(h.llm.response_with_functions.call_count, 2)
        h.llm.response.assert_not_called()
        self.assertEqual([e.content_detail for e in self.text_events(h)], ["[calm]音量已调到百分之五十。"])
        tools = [m for m in calls[1] if m["role"] == "tool"]
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]["tool_call_id"], "call-test")
        self.assertEqual(len(self.assistants(h)), 1)

    def test_empty_response_never_calls_rewrite_or_invents_answer(self):
        h = self.handler()
        self.primary_with_tools(h, [])
        self.assertTrue(self.chat(h))
        self.assertEqual(self.text_events(h), [])
        self.assertEqual(self.assistants(h), [])
        h.llm.response.assert_not_called()

    def test_abort_does_not_start_rewrite_or_emit_later_piece(self):
        h = self.handler()

        def pieces(*args, **kwargs):
            yield ("已生成片段", None)
            h.client_abort = True
            yield ("取消后的片段", None)

        h.llm.response_with_functions = MagicMock(side_effect=pieces)
        h.llm.response = MagicMock(side_effect=AssertionError("unexpected rewrite"))
        self.assertTrue(self.chat(h))
        self.assertEqual([e.content_detail for e in self.text_events(h)], ["已生成片段"])
        h.llm.response.assert_not_called()

    def test_rewrite_method_and_config_reader_removed(self):
        from core.utils import prompt_pipeline
        self.assertFalse(hasattr(ConnectionHandler, "_run_expressive_final"))
        self.assertFalse(hasattr(prompt_pipeline, "finalization_mode"))


if __name__ == "__main__":
    unittest.main()
