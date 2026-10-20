"""Offline speech-text regression checks; no model, gateway, or device calls."""
import ast
import importlib.util
from pathlib import Path
import queue
import sys
import types
import unittest


tree_root, server_root = map(Path, sys.argv[1:3])
for package in ["core", "core.utils", "core.providers", "core.providers.tts", "core.providers.tts.official"]:
    module = types.ModuleType(package)
    module.__path__ = []
    sys.modules[package] = module


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


load("core.providers.tts.official.tags", server_root / "core/providers/tts/official/tags.py")
text_utils = load("core.utils.textUtils", tree_root / "core/utils/textUtils.py")
compiler_module = load("core.providers.tts.official.compiler", tree_root / "core/providers/tts/official/compiler.py")
prompt_module = load("core.providers.tts.official.prompt", tree_root / "core/providers/tts/official/prompt.py")
Compiler = compiler_module.IncrementalCompiler


class SentenceType:
    FIRST, MIDDLE, LAST = "first", "middle", "last"


class ContentType:
    TEXT, FILE = "text", "file"


# Exercise the real production queue/end handling without starting providers.
provider_tree = ast.parse((server_root / "core/providers/tts/qwen_audio_tts_plus.py").read_text())
base_tree = ast.parse((server_root / "core/providers/tts/base.py").read_text())
method_names = {"_handle_official_message", "_emit_device_last_only", "_process_before_stop_play_files"}
methods = [n for tree in (provider_tree, base_tree) for n in ast.walk(tree)
           if isinstance(n, ast.FunctionDef) and n.name in method_names]
assert len(methods) == 3
namespace = {
    "SentenceType": SentenceType,
    "ContentType": ContentType,
    "IncrementalCompiler": Compiler,
    "freeze_snapshot": lambda value: dict(value),
    "validate_snapshot": lambda value: (True, ""),
}
method_tree = ast.Module(body=methods, type_ignores=[])
exec(compile(ast.fix_missing_locations(method_tree), "production_end_methods", "exec"), namespace)
ProviderHarness = type("ProviderHarness", (), {name: namespace[name] for name in method_names})


def provider():
    obj = ProviderHarness()
    obj.conn = types.SimpleNamespace(client_abort=False, tts_abort_epoch=7, sentence_id="regression")
    obj._config_snapshot = {}
    obj._compiler = Compiler()
    obj._turn_first_sent = False
    obj._current = None
    obj.before_stop_play_files = []
    obj.tts_audio_queue = queue.Queue()
    obj.units = []
    obj._message_abort_epoch = lambda message: message.abort_epoch

    def synthesize(unit, message_epoch, current_epoch, last):
        obj.units.append(unit)
        if last:
            obj._process_before_stop_play_files()
    obj._run_official_unit = synthesize
    return obj


def message(content, kind=SentenceType.MIDDLE, epoch=7):
    return types.SimpleNamespace(sentence_type=kind, content_type=ContentType.TEXT,
                                 content_detail=content, abort_epoch=epoch)


class EmojiRegression(unittest.TestCase):
    def test_logged_wink_tail_uses_normal_last(self):
        for chunks in [("今天很棒！", "😉"), ("[empathetic]你已经很努力了！", "😉")]:
            with self.subTest(chunks=chunks):
                obj = provider()
                obj._handle_official_message(message("", SentenceType.FIRST))
                for chunk in chunks:
                    obj._handle_official_message(message(chunk))
                obj._handle_official_message(message("", SentenceType.LAST))
                self.assertEqual(len(obj.units), 1)
                self.assertNotIn("😉", obj.units[0].synthesis_text)
                self.assertEqual(obj.tts_audio_queue.get_nowait(), (SentenceType.LAST, [], None))
                self.assertTrue(obj.tts_audio_queue.empty())

    def test_inline_emoji_keeps_speech_and_tags(self):
        obj = provider()
        obj._handle_official_message(message("[empathetic]您好😉！"))
        obj._handle_official_message(message("", SentenceType.LAST))
        self.assertEqual(obj.units[0].synthesis_text, "[empathetic]您好！")
        self.assertEqual(obj.units[0].caption_text, "您好！")

    def test_unterminated_text_still_synthesizes_and_finishes(self):
        obj = provider()
        obj._handle_official_message(message("2026年价格20元，型号S3"))
        obj._handle_official_message(message("", SentenceType.LAST))
        self.assertEqual(obj.units[0].synthesis_text, "2026年价格20元，型号S3")
        self.assertEqual(obj.tts_audio_queue.get_nowait()[0], SentenceType.LAST)
        self.assertTrue(obj.tts_audio_queue.empty())

    def test_only_emoji_finishes_without_upstream_unit(self):
        obj = provider()
        obj._handle_official_message(message("😉👋🏽🇨🇳👨‍👩‍👧‍👦❤️"))
        obj._handle_official_message(message("", SentenceType.LAST))
        self.assertEqual(obj.units, [])
        self.assertEqual(obj.tts_audio_queue.get_nowait()[0], SentenceType.LAST)

    def test_keycap_split_across_chunks(self):
        compiler = Compiler()
        units = []
        for chunk in ("数字1，", "2", "\ufe0f", "\u20e3", "结束！"):
            units.extend(compiler.feed(chunk))
        units.extend(compiler.flush())
        self.assertEqual("".join(unit.synthesis_text for unit in units), "数字1，结束！")

    def test_ssml_and_newlines_retained(self):
        compiler = Compiler()
        text = "<speak><p>你好😉</p>\n<p>世界❤️</p></speak>"
        units = compiler.feed(text) + compiler.flush()
        self.assertEqual(len(units), 1)
        self.assertTrue(units[0].enable_ssml)
        self.assertFalse(units[0].rejected)
        self.assertEqual(units[0].synthesis_text, "<speak><p>你好</p>\n<p>世界</p></speak>")

    def test_caption_and_subtitle_do_not_contain_emoji(self):
        self.assertEqual(compiler_module.caption_from("[empathetic]你好！😉"), "你好！")
        self.assertEqual(text_utils.check_emoji("你好👋🏽\n2026！"), "你好2026！")

    def test_prompt_and_final_expression_explicitly_ban_emoji(self):
        self.assertIn("禁止使用 emoji", prompt_module.OFFICIAL_EXPRESSION_CONSTRAINT)
        self.assertIn("禁止使用 emoji", prompt_module.EXPRESSIVE_STAGE_NOTICE)

    def test_stale_end_does_not_stop_current_turn(self):
        obj = provider()
        obj._handle_official_message(message("", SentenceType.LAST, epoch=6))
        self.assertTrue(obj.tts_audio_queue.empty())

    def test_aborted_turn_does_not_emit_end(self):
        obj = provider()
        obj.conn.client_abort = True
        obj._handle_official_message(message("", SentenceType.LAST))
        self.assertTrue(obj.tts_audio_queue.empty())


unittest.main(argv=["emoji-regression"], verbosity=2)
