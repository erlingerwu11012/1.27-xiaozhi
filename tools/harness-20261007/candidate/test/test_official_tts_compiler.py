"""Official TTS compiler, capability matrix, and sentence-submit protocol tests."""
from __future__ import annotations

import asyncio
import json
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__file__), ".."))

import config.config_loader as config_loader


def _offline_config(config):
    local = dict(config)
    local["read_config_from_api"] = False
    return local


config_loader.get_config_from_api = _offline_config

from core.providers.tts.dto.dto import ContentType, SentenceType, TTSMessageDTO
from core.providers.tts.official.compiler import IncrementalCompiler, caption_from
from core.providers.tts.official.capabilities import catalog, freeze_snapshot, validate_snapshot
from core.providers.tts.official.params import build_continue_task, build_run_task
from core.providers.tts.qwen_audio_tts_plus import TTSProvider

# Reuse fakes from sibling test module without package import.
import importlib.util
_spec = importlib.util.spec_from_file_location(
    "qwen_tts_fakes",
    __import__("os").path.join(__import__("os").path.dirname(__file__), "test_qwen_audio_tts_plus.py"),
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
FakeConn = _mod.FakeConn
FakeWS = _mod.FakeWS


class CompilerTests(unittest.TestCase):
    def test_sentence_split_and_cross_chunk_tag(self):
        c = IncrementalCompiler()
        self.assertEqual(c.feed("你好"), [])
        units = c.feed("世界。下")
        self.assertEqual(len(units), 1)
        self.assertEqual(units[0].caption_text, "你好世界。")
        self.assertFalse("[" in units[0].synthesis_text)
        more = c.feed("[exc")
        self.assertEqual(more, [])
        units = c.feed("ited]太好了！")
        self.assertEqual(len(units), 1)
        self.assertIn("[excited]", units[0].synthesis_text)
        self.assertEqual(units[0].caption_text, "下太好了！")

    def test_unknown_tag_stripped_before_submit(self):
        c = IncrementalCompiler()
        units = c.feed("[not-a-tag]天气23度。")
        self.assertEqual(len(units), 1)
        self.assertEqual(units[0].synthesis_text, "天气23度。")
        self.assertIn("[not-a-tag]", units[0].stripped_invalid)

    def test_old_device_emotion_not_official(self):
        c = IncrementalCompiler()
        units = c.feed("[emotion:happy]你好。")
        self.assertEqual(units[0].synthesis_text, "你好。")
        self.assertNotIn("emotion", units[0].synthesis_text)

    def test_action_limit_per_unit_and_turn(self):
        c = IncrementalCompiler()
        units = c.feed("[laughing]哈。[giggles]嘿。")
        self.assertEqual(units[0].action_count, 1)
        self.assertEqual(units[1].action_count, 1)
        units = c.feed("[sighing]还要。")
        self.assertEqual(units[0].action_count, 0)

    def test_tool_json_not_tts(self):
        c = IncrementalCompiler()
        self.assertEqual(c.feed('{"name":"get_weather","arguments":{}}'), [])

    def test_long_unpunctuated_splits_at_space(self):
        c = IncrementalCompiler(soft_limit=20, hard_limit=40)
        text = "word " * 30
        units = c.feed(text)
        self.assertTrue(units)
        self.assertLessEqual(len(units[0].synthesis_text), 40)

    def test_ssml_complete_one_task_and_reject_entity(self):
        c = IncrementalCompiler()
        chunk = '<speak rate="1.2">你好<break time="200ms"/>世界</speak>'
        units = c.feed(chunk)
        self.assertEqual(len(units), 1)
        self.assertTrue(units[0].enable_ssml)
        bad = IncrementalCompiler().feed('<speak><!DOCTYPE foo [ <!ENTITY x SYSTEM "file:///etc/passwd"> ]>x</speak>')
        self.assertTrue(bad[0].rejected)

    def test_incomplete_ssml_not_submitted(self):
        c = IncrementalCompiler()
        self.assertEqual(c.feed("<speak>半句"), [])
        flushed = c.flush()
        self.assertTrue(flushed[0].rejected)

    def test_caption_strips_tags(self):
        self.assertEqual(caption_from("[excited]你好[laughing]呀"), "你好呀")


class CapabilityTests(unittest.TestCase):
    def test_catalog_excludes_seed_and_timestamps(self):
        data = catalog()
        self.assertEqual(data["model"], "qwen-audio-3.0-tts-plus")
        self.assertIn("seed", data["excluded"])
        self.assertIn("word_timestamp_enabled", data["excluded"])
        self.assertEqual(data["streaming"], "duplex")

    def test_unknown_param_rejected(self):
        snap = freeze_snapshot({"voice": "longanlingxi"})
        snap["extra_params"] = {"seed": 1}
        ok, reason = validate_snapshot(snap)
        self.assertFalse(ok)
        snap = freeze_snapshot({"voice": "not-a-voice", "voice_owner_ok": True})
        ok, reason = validate_snapshot(snap)
        self.assertFalse(ok)
        self.assertIn("voice_not_authorized", reason)
        snap = freeze_snapshot({"voice": "clonedvoice01", "allowed_voices": ["clonedvoice01"]})
        ok, reason = validate_snapshot(snap)
        self.assertTrue(ok, reason)

    def test_run_task_never_simplex_and_no_seed(self):
        snap = freeze_snapshot({"voice": "longanlingxi", "instruction": "温柔一些"})
        msg = build_run_task("tid", snap, enable_ssml=True)
        self.assertEqual(msg["header"]["streaming"], "duplex")
        self.assertNotIn("seed", msg["payload"]["parameters"])
        self.assertNotIn("word_timestamp_enabled", msg["payload"]["parameters"])
        self.assertTrue(msg["payload"]["parameters"]["enable_ssml"])
        self.assertEqual(msg["payload"]["parameters"]["instruction"], "温柔一些")
        cont = build_continue_task("tid", "[excited]你好")
        self.assertEqual(cont["header"]["streaming"], "duplex")

    def test_freeze_accepts_java_camel_case(self):
        snap = freeze_snapshot({"voice": "longanlingxi", "languageHints": "en", "hotFix": {"foo": "bar"}})
        self.assertEqual(snap["language_hints"], ["en"])
        self.assertEqual(snap["hot_fix"], {"foo": "bar"})

    def test_volume_zero_is_not_default_fifty(self):
        snap = freeze_snapshot({"voice": "longanlingxi", "volume": 0})
        self.assertEqual(snap["volume"], 0)
        ok, reason = validate_snapshot(snap)
        self.assertTrue(ok, reason)
        msg = build_run_task("tid", snap)
        self.assertEqual(msg["payload"]["parameters"]["volume"], 0)


class OfficialSubmitTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.loop = asyncio.get_running_loop()
        self.conn = FakeConn(self.loop)
        self.sockets = []

        async def connect(url, headers):
            ws = FakeWS()
            self.sockets.append(ws)
            return ws

        self.provider = TTSProvider(
            {
                "api_key": "sk-test",
                "ws_url": "ws://127.0.0.1:3011/bailian/api-ws/v1/inference",
                "model": "qwen-audio-3.0-tts-plus",
                "voice": "longanlingxi",
                "sample_rate": 16000,
                "official_enhanced": True,
                "official_model_id": "TTS_QwenAudioTTSPlus",
                "instruction": "温柔一些",
                "_connect": connect,
            },
            True,
        )
        self.provider.conn = self.conn
        self.conn.tts = self.provider
        self.provider.handle_opus = lambda data: None

    async def asyncTearDown(self):
        try:
            await self.provider.close()
        except Exception:
            pass

    async def _ack_started(self, ws):
        raw = await asyncio.wait_for(ws.outgoing.get(), 2)
        run = json.loads(raw)
        await ws.incoming.put(
            json.dumps({"header": {"event": "task-started", "task_id": run["header"]["task_id"]}})
        )
        return run

    async def test_sentence_unit_one_continue_then_finish(self):
        self.assertTrue(self.provider._official_on())
        start = asyncio.create_task(
            self.provider.start_session(self.conn.sentence_id, enable_ssml=False)
        )
        for _ in range(50):
            if self.sockets:
                break
            await asyncio.sleep(0.01)
        run = await self._ack_started(self.sockets[0])
        await start
        self.assertEqual(run["header"]["streaming"], "duplex")
        self.assertNotIn("seed", run["payload"]["parameters"])
        self.assertEqual(run["payload"]["parameters"]["instruction"], "温柔一些")
        await self.provider.text_to_speak("[excited]你好世界。", None, official=True)
        cont = json.loads(await asyncio.wait_for(self.sockets[0].outgoing.get(), 2))
        self.assertEqual(cont["header"]["action"], "continue-task")
        self.assertEqual(cont["payload"]["input"]["text"], "[excited]你好世界。")
        finish = asyncio.create_task(self.provider.finish_session(self.provider.task_id, emit_last=True))
        fin = json.loads(await asyncio.wait_for(self.sockets[0].outgoing.get(), 2))
        self.assertEqual(fin["header"]["action"], "finish-task")
        await self.sockets[0].incoming.put(
            json.dumps({"header": {"event": "task-finished", "task_id": run["header"]["task_id"]}})
        )
        await finish

    async def test_legacy_path_when_flag_off(self):
        off = TTSProvider(
            {
                "api_key": "sk-test",
                "ws_url": "ws://127.0.0.1:3011/bailian/api-ws/v1/inference",
                "model": "qwen-audio-3.0-tts-plus",
                "official_enhanced": False,
                "official_model_id": "TTS_QwenAudioTTSPlus",
                "_connect": lambda url, headers: FakeWS(),
            },
            True,
        )
        self.assertFalse(off._official_on())

    def test_token_resolve_failed_refuses_shared_key(self):
        with self.assertRaises(ValueError) as ctx:
            TTSProvider(
                {
                    "api_key": "sk-shared-production",
                    "official_billing": "token_resolve_failed",
                    "official_tts_blocked": "token_resolve_failed",
                    "official_enhanced": True,
                    "official_model_id": "TTS_QwenAudioTTSPlus",
                    "_connect": lambda url, headers: FakeWS(),
                },
                True,
            )
        self.assertIn("shared production key is not used", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
