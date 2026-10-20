#!/usr/bin/env python3
"""Offline checks that official defaults stay centralized."""
import unittest
import sys
from pathlib import Path

ROOT = Path("/root/prjs/xiaozhi-esp32-server")
sys.path.insert(0, str(ROOT / "main/xiaozhi-server"))

from core.utils.speech_emotion import (  # noqa: E402
    UNKNOWN_CODE,
    normalize_emotion,
    inject_emotion_enabled,
    build_llm_hint,
)


class OfficialDefaultsTests(unittest.TestCase):
    def test_java_constants_file(self):
        src = (ROOT / "main/manager-api/src/main/java/xiaozhi/modules/model/OfficialServiceDefaults.java").read_text()
        self.assertIn('ASR_MODEL_ID = "ASR_Qwen3ASRRealtime"', src)
        self.assertIn('TTS_MODEL_ID = "TTS_QwenAudioTTSPlus"', src)
        self.assertIn('LLM_MODEL_ID = "LLM_QwenPlusOfficial"', src)
        self.assertIn('TTS_VOICE_CODE = "longanlingxi"', src)
        self.assertIn('LLM_MODEL_NAME = "qwen-plus"', src)

    def test_frontend_defaults(self):
        src = (ROOT / "main/manager-web/src/views/TemplateQuickConfig.vue").read_text()
        self.assertIn('asrModelId: "ASR_Qwen3ASRRealtime"', src)
        self.assertIn('ttsModelId: "TTS_QwenAudioTTSPlus"', src)
        self.assertIn('llmModelId: "LLM_QwenPlusOfficial"', src)
        self.assertNotIn('llmModelId: "LLM_DeepSeekLLM"', src)

    def test_emotion_missing_is_unknown(self):
        self.assertEqual(normalize_emotion(None), UNKNOWN_CODE)
        self.assertEqual(normalize_emotion(""), UNKNOWN_CODE)
        self.assertEqual(normalize_emotion("happy"), "happy")
        self.assertFalse(inject_emotion_enabled({}))
        self.assertTrue(inject_emotion_enabled({"inject_emotion_hint": True}))
        self.assertEqual(build_llm_hint(None), "")
        hint = build_llm_hint({"emotion": "happy", "text": "ignored"})
        self.assertIn("愉快", hint)
        self.assertNotIn("ignored", hint)


if __name__ == "__main__":
    unittest.main()
