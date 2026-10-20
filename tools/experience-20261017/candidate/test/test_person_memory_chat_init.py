"""Exercise the deployed connection methods without loading production config."""
import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from core.utils.person_identity import PersonTurn, current_turn


def connection_methods():
    source = Path(__file__).parents[1] / "core/connection.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    original = next(n for n in tree.body if isinstance(n, ast.ClassDef)
                    and n.name == "ConnectionHandler")
    selected = {"_initialize_intent", "_initialize_function_tools", "chat"}
    methods = [n for n in original.body if isinstance(n, ast.FunctionDef)
               and n.name in selected]
    cls = ast.ClassDef(name="ConnectionMethods", bases=[], keywords=[],
                       body=methods, decorator_list=[])
    namespace = {"asyncio": asyncio, "TAG": "synthetic_chat_test",
                 "UnifiedToolHandler": MagicMock()}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[])),
                 str(source), "exec"), namespace)
    return namespace["ConnectionMethods"], namespace


class ChatInitializationTests(unittest.TestCase):
    def setUp(self):
        cls, self.namespace = connection_methods()
        self.conn = cls()
        self.conn.logger = MagicMock()
        self.conn.memory = SimpleNamespace(personal=True, record_turn=MagicMock(),record_response=MagicMock())
        self.conn.dialogue = SimpleNamespace(dialogue=[])
        self.conn.intent = None
        self.conn.func_handler = None
        self.conn.config = {}
        self.conn.loop = object()
        self.handler = MagicMock()
        self.handler._initialize = AsyncMock()
        self.namespace["UnifiedToolHandler"].return_value = self.handler

    def run_init(self):
        def schedule(coroutine, loop):
            coroutine.close()
            return MagicMock()
        with patch.object(asyncio, "run_coroutine_threadsafe", side_effect=schedule) as call:
            self.conn._initialize_intent()
            return call.call_count

    def test_bailian_initializes_tools_without_secondary_intent_model(self):
        self.assertEqual(self.run_init(), 1)
        self.assertEqual(self.conn.intent_type, "function_call")
        self.assertTrue(self.conn.load_function_plugin)
        self.assertIs(self.conn.func_handler, self.handler)
        self.namespace["UnifiedToolHandler"].assert_called_once_with(self.conn)

    def test_bailian_ignores_selected_secondary_intent(self):
        self.conn.intent = MagicMock()
        self.conn.config = {"selected_module": {"Intent": "secondary"},
                            "Intent": {"secondary": {"type": "intent_llm", "llm": "extra"}}}
        self.assertEqual(self.run_init(), 1)
        self.conn.intent.set_llm.assert_not_called()
        self.assertIs(self.conn.func_handler, self.handler)

    def test_existing_function_call_still_initializes_tools(self):
        self.conn.memory.personal = False
        self.conn.intent = MagicMock()
        self.conn.config = {"selected_module": {"Intent": "main"},
                            "Intent": {"main": {"type": "function_call"}}}
        self.assertEqual(self.run_init(), 1)
        self.assertIs(self.conn.func_handler, self.handler)

    def test_existing_no_intent_does_not_initialize_tools(self):
        self.conn.memory.personal = False
        self.conn.intent = MagicMock()
        self.conn.config = {"selected_module": {"Intent": "none"},
                            "Intent": {"none": {"type": "nointent"}}}
        self.assertEqual(self.run_init(), 0)
        self.assertIsNone(self.conn.func_handler)

    def test_complete_request_budget_call_matches_actual_dialogue_signature(self):
        from core.utils.dialogue import Dialogue
        root = Path(__file__).parents[1]
        connection=ast.parse((root/"core/connection.py").read_text(encoding="utf-8"))
        calls=[n for n in ast.walk(connection) if isinstance(n,ast.Call)
               and isinstance(n.func,ast.Attribute) and n.func.attr=="prepare_request"]
        self.assertEqual(len(calls),1)
        dialogue=Dialogue()
        conn=SimpleNamespace(dialogue=dialogue,llm=SimpleNamespace(input_limit_tokens=997952,context_limit_tokens=1000000),session_id="synthetic")
        messages=[{"role":"system","content":"rules"},{"role":"user","content":"hello"}]
        expression=ast.fix_missing_locations(ast.Expression(body=calls[0]))
        result=eval(compile(expression,"connection.py","eval"),{"self":conn,"messages":messages,"functions":None})
        self.assertEqual(result,messages);self.assertEqual(dialogue.context_window.limit,200000)

    def actor(self):
        return PersonTurn("synthetic", "", 0, 0, "unavailable", "unknown",
                          "synthetic_turn", "synthetic_device", "synthetic_agent", 2)

    def test_unexpected_chat_failure_logs_and_returns_feedback(self):
        self.conn.listen_epoch = 2
        self.conn._chat_impl = MagicMock(side_effect=RuntimeError("synthetic_failure"))
        self.conn._send_fallback_voice = MagicMock()
        with patch("core.utils.person_identity.select_dialogue"):
            self.assertFalse(self.conn.chat("synthetic", _identity=self.actor()))
        self.conn.logger.bind.return_value.exception.assert_called_once()
        self.conn._chat_impl.assert_called_once()
        self.conn._send_fallback_voice.assert_called_once()
        self.assertTrue(self.conn.llm_finish_task)
        self.assertIsNone(current_turn(self.conn))
        self.conn.memory.record_response.assert_called_once()

    def test_late_failed_turn_does_not_send_feedback_to_new_turn(self):
        self.conn.listen_epoch = 2
        def fail(*args):
            self.conn.listen_epoch = 3
            raise RuntimeError("synthetic_late_failure")
        self.conn._chat_impl = MagicMock(side_effect=fail)
        self.conn._send_fallback_voice = MagicMock()
        with patch("core.utils.person_identity.select_dialogue"):
            self.assertFalse(self.conn.chat("synthetic", _identity=self.actor()))
        self.conn._send_fallback_voice.assert_not_called()
        self.assertIsNone(current_turn(self.conn))


if __name__ == "__main__":
    unittest.main()
