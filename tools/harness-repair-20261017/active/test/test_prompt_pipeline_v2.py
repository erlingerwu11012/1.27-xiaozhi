"""LLM 请求结构 v2 契约测试。

覆盖：开关 fail-closed、轮次快照、静态 system、分层提示词、表达约束、
字幕标签剥离。仅用合成/脱敏数据，不读真实密钥、不保存用户对话。
"""
from __future__ import annotations

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.utils.dialogue import Dialogue, Message
from core.utils import prompt_pipeline
from core.utils import turn_context
from core.providers.tts.official.compiler import caption_from
from core.providers.tts.official.prompt import build_expression_constraint


def _conn(**overrides):
    base = {
        "config": {},
        "device_id": "dev-1",
        "session_id": "sess-1",
        "agent_id": "agent-1",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class SwitchTests(unittest.TestCase):
    def test_is_pipeline_v2_config_missing_fails_closed_and_v2_is_global(self):
        self.assertFalse(prompt_pipeline.is_pipeline_v2(_conn()))
        self.assertFalse(prompt_pipeline.is_pipeline_v2(_conn(config={"prompt_pipeline":{"version":"v1"}})))
        for rollout in (None,[],["dev-other"]):
            self.assertTrue(prompt_pipeline.is_pipeline_v2(_conn(config={"prompt_pipeline":{"version":"v2","rollout_device_ids":rollout}})))

    def test_is_pipeline_v2_rollout_match(self):
        self.assertTrue(
            prompt_pipeline.is_pipeline_v2(
                _conn(
                    config={
                        "prompt_pipeline": {
                            "version": "v2",
                            "rollout_device_ids": ["dev-1"],
                        }
                    }
                )
            )
        )


    def test_two_pass_finalization_switch_removed(self):
        self.assertFalse(hasattr(prompt_pipeline, 'finalization_mode'))

    def test_include_stream_usage_default_false(self):
        self.assertFalse(prompt_pipeline.include_stream_usage(_conn()))
        self.assertTrue(
            prompt_pipeline.include_stream_usage(
                _conn(config={"llm_observability": {"include_stream_usage": True}})
            )
        )

    def test_hashes_stable(self):
        msgs = [{"role": "system", "content": "固定规则"}]
        self.assertEqual(prompt_pipeline.system_hash(msgs), prompt_pipeline.system_hash(msgs))
        self.assertEqual(prompt_pipeline.system_hash([]), "")
        self.assertEqual(prompt_pipeline.tools_hash(None), "")
        self.assertTrue(prompt_pipeline.tools_hash([{"type": "function"}]))


class TurnContextTests(unittest.TestCase):
    def _fixed_time(self):
        return {
            "current_datetime": "2026-09-22 18:40:00",
            "today_date": "2026-09-22",
            "today_weekday": "星期二",
            "lunar_date": "八月初二",
            "timezone": "Asia/Shanghai",
            "unix_timestamp": "1758537600",
        }

    def test_render_excludes_unix_and_unknown_emotion(self):
        with patch(
            "core.utils.current_time.get_prompt_time_context", return_value=self._fixed_time()
        ):
            ctx = turn_context.build_turn_context(_conn(), None, None)
        text = turn_context.render_turn_context(ctx)
        self.assertIn("18:40:00", text)
        self.assertNotIn("1758537600", text)  # 不含 Unix 秒
        self.assertNotIn("情绪", text)  # unknown 不渲染

    def test_render_includes_emotion_and_speaker(self):
        with patch(
            "core.utils.current_time.get_prompt_time_context", return_value=self._fixed_time()
        ), patch("core.utils.person_identity.current_turn", return_value=SimpleNamespace(eligible=True,display_name="小明",status="matched",person_id="usr_test",payload=lambda: {})):
            ctx = turn_context.build_turn_context(
                _conn(current_speaker="小明"),
                "喜欢喝咖啡",
                {"emotion": "happy", "raw_emotion": "happy", "listen_epoch": 3, "item_id": "it-1"},
            )
        text = turn_context.render_turn_context(ctx)
        self.assertIn("情绪", text)
        self.assertIn("happy", text)
        self.assertIn("小明", text)
        self.assertIn("喜欢喝咖啡", text)
        self.assertEqual(ctx["emotion"], "happy")
        self.assertEqual(ctx["listen_epoch"], "3")
        self.assertEqual(ctx["item_id"], "it-1")

    def test_emotion_unknown_when_missing(self):
        with patch(
            "core.utils.current_time.get_prompt_time_context", return_value=self._fixed_time()
        ):
            ctx = turn_context.build_turn_context(_conn(), None, None)
        self.assertEqual(ctx["emotion"], "unknown")


class DialogueV2Tests(unittest.TestCase):
    def test_configure_compact_applies_and_validates(self):
        d = Dialogue()
        d.configure_compact(
            {
                "context_compress": {
                    "enabled": False,
                    "max_context_tokens": 999999,  # 超出上限应被钳制
                    "compact_threshold": 2.5,  # 超出上限应被钳制
                    "keep_recent_rounds": 0,  # 低于下限应被钳制
                    "max_summary_chars": 500,
                }
            }
        )
        self.assertFalse(d.compact_enabled)
        self.assertLessEqual(d.max_context_tokens, 1_000_000)
        self.assertLessEqual(d.compact_threshold, 1.0)
        self.assertGreaterEqual(d.keep_recent_rounds, 1)
        self.assertEqual(d.max_summary_chars, 500)

    def test_static_system_keeps_placeholders(self):
        d = Dialogue()
        d.put(Message(role="system", content="规则 {{current_time}}"))
        d.put(Message(role="user", content="你好"))
        msgs = d.get_llm_dialogue_with_memory(static_system=True)
        self.assertIn("{{current_time}}", msgs[0]["content"])

    def test_snapshot_prepended_to_user_content(self):
        d = Dialogue()
        d.put(Message(role="system", content="固定规则"))
        d.put(
            Message(
                role="user",
                content="今天天气怎么样",
                prompt_context={"current_datetime": "2026-09-22 18:40:00", "emotion": "unknown"},
            )
        )
        msgs = d.get_llm_dialogue_with_memory(static_system=True)
        user = [m for m in msgs if m["role"] == "user"][0]
        self.assertIn("[本轮上下文]", user["content"])
        self.assertTrue(user["content"].endswith("今天天气怎么样"))

    def test_snapshot_prepended_multimodal(self):
        d = Dialogue()
        d.put(Message(role="system", content="固定规则"))
        d.put(
            Message(
                role="user",
                content=[{"type": "image_url", "image_url": {"url": "http://x/img"}}],
                prompt_context={"current_datetime": "2026-09-22 18:40:00"},
            )
        )
        msgs = d.get_llm_dialogue_with_memory(static_system=True)
        user = [m for m in msgs if m["role"] == "user"][0]
        parts = user["content"]
        self.assertEqual(parts[0]["type"], "text")
        self.assertIn("[本轮上下文]", parts[0]["text"])
        self.assertEqual(parts[1]["type"], "image_url")  # 多模态原样保留


class ExpressionAndCaptionTests(unittest.TestCase):
    def test_expression_constraint_plain_speech_preserves_personality(self):
        text = build_expression_constraint()
        self.assertIn("禁止机械镜像", text)
        self.assertIn("正文不生成方括号情感标签", text)
        self.assertIn("不要把用户意图摘要", text)
        self.assertIn("不得覆盖用户角色设定", text)
        self.assertNotIn("声音动作白名单", text)
        self.assertNotIn("[amazed]", text)
        self.assertEqual(text, build_expression_constraint({'amazed'}, {'laughing'}))

    def test_caption_from_preserves_plain_brackets(self):
        self.assertEqual(caption_from("[选项A] 你好"), "[选项A] 你好")
        self.assertEqual(caption_from("请选 [A] 或 [B]"), "请选 [A] 或 [B]")

    def test_caption_from_strips_official_and_emotion(self):
        self.assertEqual(caption_from("[excited]太好了[laughing]呀"), "太好了呀")
        self.assertEqual(caption_from("[emotion:happy]hi"), "hi")

    def test_caption_from_removes_html(self):
        self.assertEqual(caption_from("<b>粗体</b>文本"), "粗体文本")


class PromptManagerV2Tests(unittest.TestCase):
    def test_build_enhanced_prompt_v2_layers(self):
        from core.utils.prompt_manager import PromptManager

        config = {
            "system_base_prompt": "[平台基座] 禁止泄露密钥",
            "prompt": "你是毒舌助手",
            "language": "中文",
        }
        with patch.object(PromptManager, "_load_v2_template", lambda self: None):
            pm = PromptManager(config)
            pm.base_prompt_template_v2 = "<tool_calling>\n仅调用存在的工具\n</tool_calling>"
            out = pm.build_enhanced_prompt_v2(
                "你是毒舌助手",
                "dev-1",
                client_ip=None,
                device_name="小智",
                user_nickname="用户",
                official_enhanced=False,
            )
        self.assertIn("[平台基座]", out)
        self.assertIn("<tool_calling>", out)
        self.assertIn("你是毒舌助手", out)
        self.assertIn("小智", out)
        self.assertIn("时区:", out)
        # 不含任何未渲染占位符
        self.assertNotIn("{{", out)

    def test_l3_excludes_lunar_and_weather_has_source_time(self):
        from core.utils.prompt_manager import PromptManager

        config = {"system_base_prompt": "", "prompt": "人格", "language": "中文"}
        with patch.object(PromptManager, "_load_v2_template", lambda self: None):
            pm = PromptManager(config)
            pm.base_prompt_template_v2 = "synthetic platform rules"
            # 预置天气缓存（含来源时间）
            from core.utils.cache.manager import cache_manager, CacheType

            cache_manager.set(CacheType.LOCATION, "1.2.3.4", "杭州")
            cache_manager.set(CacheType.WEATHER, "杭州", "晴，22℃")
            out = pm.build_enhanced_prompt_v2(
                "人格",
                "dev-1",
                client_ip="1.2.3.4",
                device_name="小智",
                user_nickname="用户",
                official_enhanced=False,
            )
            # 农历不在 L3（应随本轮日期在轮次快照采集）
            self.assertNotIn("农历", out)
            # 天气为连接时快照，带来源时间 + 过期刷新提示
            self.assertIn("连接时天气快照", out)
            self.assertIn("来源时间:", out)
            self.assertIn("可能过期", out)


class SwitchFreezeTests(unittest.TestCase):
    def test_is_pipeline_v2_frozen_on_first_eval(self):
        conn = _conn(config={"prompt_pipeline": {"version": "v2", "rollout_device_ids": ["dev-1"]}})
        self.assertTrue(prompt_pipeline.is_pipeline_v2(conn))
        # 连接内配置被改（模拟私有配置重下发）也不应翻转
        conn.config["prompt_pipeline"]["version"] = "v1"
        conn.config["prompt_pipeline"]["rollout_device_ids"] = []
        self.assertTrue(prompt_pipeline.is_pipeline_v2(conn))


class EmotionConsumeTests(unittest.TestCase):
    def _handler(self, *, speech_turn_result=None, utterance_id=3, listen_epoch=9):
        from core.connection import ConnectionHandler

        h = ConnectionHandler.__new__(ConnectionHandler)
        h.config = {"selected_module": {"ASR": "Qwen3ASR"}, "ASR": {"Qwen3ASR": {"inject_emotion_hint": True}}}
        h.speech_turn_result = speech_turn_result
        h.utterance_id = utterance_id
        h.listen_epoch = listen_epoch
        h.inject_emotion_hint = False
        h._trace_last_emotion_result = None
        return h

    def _result(self, emotion="happy", utterance_id=3, listen_epoch=9):
        return {
            "emotion": emotion,
            "raw_emotion": emotion,
            "item_id": "it-1",
            "utterance_id": utterance_id,
            "listen_epoch": listen_epoch,
        }

    def test_consume_returns_tuple_and_clears_slot(self):
        h = self._handler(speech_turn_result=self._result())
        result, hint = h._consume_speech_emotion_hint()
        self.assertIsInstance(result, dict)
        self.assertEqual(result["emotion"], "happy")
        self.assertEqual(result["listen_epoch"], 9)
        self.assertIn("推测", hint)
        # 一次性消费：槽位清空，避免下一轮文字输入继承上一次语音情绪
        self.assertIsNone(h.speech_turn_result)

    def test_consume_without_result_returns_none_hint(self):
        h = self._handler(speech_turn_result=None)
        result, hint = h._consume_speech_emotion_hint()
        self.assertIsNone(result)
        self.assertIsNone(hint)

    def test_reject_stale_listen_epoch(self):
        """跨监听代迟到结果：listen_epoch 不匹配 → 丢弃，不绑定、不注入。"""
        h = self._handler(speech_turn_result=self._result(listen_epoch=8))
        result, hint = h._consume_speech_emotion_hint()
        self.assertIsNone(result)
        self.assertIsNone(hint)

    def test_reject_other_utterance_same_listen(self):
        """同一监听代内的另一段识别覆盖共享槽：utterance_id 不匹配 → 丢弃。"""
        h = self._handler(speech_turn_result=self._result(utterance_id=2))
        result, hint = h._consume_speech_emotion_hint()
        self.assertIsNone(result)
        self.assertIsNone(hint)

    def test_interleaved_arrival_matches_current_turn(self):
        """交错到达：共享槽被下一段覆盖后，当前 turn 只绑定匹配自身的结果。"""
        # 当前 turn 对应 uid=5, epoch=12
        h = self._handler(
            speech_turn_result=self._result(utterance_id=5, listen_epoch=12),
            utterance_id=5,
            listen_epoch=12,
        )
        result, _ = h._consume_speech_emotion_hint()
        self.assertIsNotNone(result)
        self.assertEqual(result["utterance_id"], 5)


class EmotionMatchesTurnTests(unittest.TestCase):
    """直接测 emotion_matches_turn 纯函数，覆盖字段缺失放行语义。"""
    def _conn(self, utterance_id=3, listen_epoch=9):
        return SimpleNamespace(utterance_id=utterance_id, listen_epoch=listen_epoch)

    def test_match(self):
        from core.utils.speech_emotion import emotion_matches_turn

        self.assertTrue(emotion_matches_turn(self._conn(), {"utterance_id": 3, "listen_epoch": 9}))

    def test_listen_epoch_mismatch(self):
        from core.utils.speech_emotion import emotion_matches_turn

        self.assertFalse(emotion_matches_turn(self._conn(), {"utterance_id": 3, "listen_epoch": 8}))

    def test_utterance_mismatch(self):
        from core.utils.speech_emotion import emotion_matches_turn

        self.assertFalse(emotion_matches_turn(self._conn(), {"utterance_id": 2, "listen_epoch": 9}))

    def test_missing_fields_pass_through(self):
        """旧 ASR 结果缺 listen_epoch/utterance_id 时放行（不因此丢弃情绪）。"""
        from core.utils.speech_emotion import emotion_matches_turn

        self.assertTrue(emotion_matches_turn(self._conn(), {"emotion": "happy"}))

    def test_conn_uninitialized_passes_through(self):
        from core.utils.speech_emotion import emotion_matches_turn

        self.assertTrue(emotion_matches_turn(self._conn(utterance_id=0), {"utterance_id": 3, "listen_epoch": 9}))


class StreamUsageTests(unittest.TestCase):
    def _provider(self, include_usage):
        with patch("core.providers.llm.openai.openai.openai.OpenAI"):
            from core.providers.llm.openai.openai import LLMProvider

            p = LLMProvider(
                {
                    "model_name": "qwen-plus",
                    "api_key": "sk-test-not-real",
                    "base_url": "http://127.0.0.1:9/v1",
                }
            )
        return p

    def test_stream_options_added_when_enabled(self):
        p = self._provider(True)
        conn = _conn(config={"llm_observability": {"include_stream_usage": True}})
        params = {"stream": True}
        p._maybe_include_stream_usage(params, conn)
        self.assertEqual(params.get("stream_options"), {"include_usage": True})

    def test_stream_options_omitted_when_disabled(self):
        p = self._provider(False)
        conn = _conn(config={"llm_observability": {"include_stream_usage": False}})
        params = {"stream": True}
        p._maybe_include_stream_usage(params, conn)
        self.assertNotIn("stream_options", params)

    def test_cached_tokens_extraction(self):
        from core.providers.llm.openai.openai import LLMProvider

        self.assertIsNone(LLMProvider._cached_tokens({"prompt_tokens_details": {}}))
        self.assertEqual(LLMProvider._cached_tokens({"prompt_tokens_details": {"cached_tokens": 12}}), 12)
        self.assertIsNone(LLMProvider._cached_tokens({"usage": {}}))


class MemoryCaptionTests(unittest.TestCase):
    def test_message_caption_text_field(self):
        m = Message(role="assistant", content="[excited]你好", caption_text="你好")
        ct = getattr(m, "caption_text", None)
        self.assertEqual(m.content if ct is None else ct, "你好")

    def test_message_without_caption_falls_back_to_content(self):
        m = Message(role="user", content="原话")
        self.assertIsNone(m.caption_text)
        ct = getattr(m, "caption_text", None)
        self.assertEqual(m.content if ct is None else ct, "原话")

    def test_empty_caption_does_not_fall_back_to_tagged_content(self):
        """字幕为空字符串（纯标签输出）时必须保持空，不得回退到带标签原文。"""
        m = Message(role="assistant", content="[excited]", caption_text="")
        ct = getattr(m, "caption_text", None)
        # caption_text 是空字符串（非 None），应原样使用空串
        self.assertEqual(m.content if ct is None else ct, "")


class StreamUsageUnsupportedTests(unittest.TestCase):
    def _provider(self):
        with patch("core.providers.llm.openai.openai.openai.OpenAI"):
            from core.providers.llm.openai.openai import LLMProvider

            return LLMProvider(
                {
                    "model_name": "qwen-plus",
                    "api_key": "sk-test-not-real",
                    "base_url": "http://127.0.0.1:9/v1",
                }
            )

    def test_unsupported_error_latches_and_drops_stream_options(self):
        p = self._provider()
        conn = _conn(config={"llm_observability": {"include_stream_usage": True}})

        # 模拟 one-api 因 stream_options 返回 400
        self.assertTrue(p._detect_stream_usage_unsupported(Exception("400 stream_options not supported")))
        self.assertTrue(p._stream_usage_unsupported)

        # 后续轮次不再发送 stream_options（自动降级，不重放）
        params = {"stream": True}
        p._maybe_include_stream_usage(params, conn)
        self.assertNotIn("stream_options", params)

    def test_unrelated_error_does_not_latch(self):
        p = self._provider()
        self.assertFalse(p._detect_stream_usage_unsupported(Exception("500 internal error")))
        self.assertFalse(getattr(p, "_stream_usage_unsupported", False))


if __name__ == "__main__":
    unittest.main()
