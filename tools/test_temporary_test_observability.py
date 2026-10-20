#!/usr/bin/env python3
"""Static contract for compact, removable firmware test diagnostics."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8", errors="replace")


class TestObservabilityContracts(unittest.TestCase):
    def test_single_test_trace_sink_and_runtime_switch(self):
        sink = read("main/test_observability.cc")
        kconfig = read("main/Kconfig.projbuild")
        self.assertIn('constexpr const char* kTag = "TEST_TRACE"', sink)
        self.assertIn("CONFIG_TEMPORARY_TEST_OBSERVABILITY", sink)
        self.assertIn("kRepeatWindowUs", sink)
        self.assertIn("ShouldEmit", sink)
        self.assertIn("TEMPORARY_TEST_OBSERVABILITY", kconfig)

    def test_radar_reminder_and_proactive_transitions_are_instrumented(self):
        expected = {
            "main/boards/esp-box-3/presence_sensor.cc": (
                '"stable_presence"', '"stable_absence"'),
            "main/reminder_coordinator.cc": (
                '"presence_gate"', '"delivery_gate"', '"present"'),
            "main/reminder_voice_service.cc": ('"local_chime"', '"ai_voice"'),
            "main/proactive_wake_coordinator.cc": (
                '"identity_flow"', '"identity_ready"', '"greeting"'),
            "main/application.cc": ('"proactive_ws"',),
        }
        for path, needles in expected.items():
            source = read(path)
            self.assertIn("test_observability::Event", source, path)
            for needle in needles:
                self.assertIn(needle, source, f"{path}: {needle}")

    def test_trace_sink_has_no_payload_or_identity_fields(self):
        sink = read("main/test_observability.cc").lower()
        for word in ("title", "detail", "recipient", "session", "token", "url"):
            self.assertNotIn(word, sink, word)


if __name__ == "__main__":
    unittest.main()
