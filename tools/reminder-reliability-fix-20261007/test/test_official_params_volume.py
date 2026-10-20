#!/usr/bin/env python3
"""Param freeze/build tests that do not import the full TTS provider stack."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.providers.tts.official.capabilities import freeze_snapshot, validate_snapshot
from core.providers.tts.official.params import build_run_task


class OfficialParamTests(unittest.TestCase):
    def test_volume_zero_is_not_default_fifty(self):
        snap = freeze_snapshot({"voice": "longanlingxi", "volume": 0})
        self.assertEqual(snap["volume"], 0)
        ok, reason = validate_snapshot(snap)
        self.assertTrue(ok, reason)
        msg = build_run_task("tid", snap)
        self.assertEqual(msg["payload"]["parameters"]["volume"], 0)

    def test_hot_fix_and_instruction_forwarded(self):
        snap = freeze_snapshot({
            "voice": "longanlingxi",
            "instruction": "温柔一些",
            "hotFix": {"foo": "bar"},
            "languageHints": "zh",
        })
        msg = build_run_task("tid", snap)
        self.assertEqual(msg["payload"]["parameters"]["instruction"], "温柔一些")
        self.assertEqual(msg["payload"]["parameters"]["hot_fix"], {"replace": [{"foo": "bar"}]})
        self.assertEqual(msg["payload"]["parameters"]["language_hints"], ["zh"])

    def test_official_hot_fix_and_pronunciation(self):
        official = {
            "replace": [{"啊": "你好世界"}],
            "pronunciation": [{"天气": "tian1 qi4"}],
        }
        snap = freeze_snapshot({"voice": "longanlingxi", "hotFix": official})
        msg = build_run_task("tid", snap)
        self.assertEqual(msg["payload"]["parameters"]["hot_fix"], official)

    def test_bit_rate_opus_kbps_only(self):
        ok, reason = validate_snapshot({"voice": "longanlingxi", "format": "opus", "bit_rate": 32})
        self.assertTrue(ok, reason)
        msg = build_run_task("tid", freeze_snapshot({"voice": "longanlingxi", "format": "opus", "bit_rate": 32}))
        self.assertEqual(msg["payload"]["parameters"]["bit_rate"], 32)
        ok, reason = validate_snapshot({"voice": "longanlingxi", "format": "mp3", "bit_rate": 32})
        self.assertFalse(ok)
        self.assertEqual(reason, "bit_rate_format")
        ok, reason = validate_snapshot({"voice": "longanlingxi", "format": "opus", "bit_rate": 128000})
        self.assertFalse(ok)
        self.assertEqual(reason, "invalid_bit_rate")
        with self.assertRaises(ValueError):
            build_run_task("tid", {"voice": "longanlingxi", "format": "wav", "bit_rate": 32})


if __name__ == "__main__":
    unittest.main()
