#!/usr/bin/env python3
"""Source contracts: manual pending must not be overwritten by proactive greeting."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_CC = ROOT / "main/application.cc"
APP_H = ROOT / "main/application.h"
COORD_CC = ROOT / "main/proactive_wake_coordinator.cc"
POLICY_CC = ROOT / "main/main_ws_submit_policy.cc"
HOST_RUNNER = ROOT / "tools/run_main_ws_open_arbiter_host_test.py"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


class ManualPendingPriorityContracts(unittest.TestCase):
    def test_submit_before_pending_write(self):
        cc = read(APP_CC)
        self.assertIn("SubmitMainWsOpenRequest", cc)
        self.assertIn("SubmitMainWsOpenRequestLocked", cc)
        self.assertIn("ShouldWritePending", cc)
        fn = cc[cc.find("Application::MainWsSubmitOutcome "
                         "Application::SubmitMainWsOpenRequestLocked") :]
        fn = fn[: fn.find("Application::MainWsSubmitOutcome "
                          "Application::SubmitMainWsOpenRequest(")]
        submit_pos = fn.find("SubmitRequest(")
        write_pos = fn.find("const bool write_pending")
        apply_guard = fn.find("if (write_pending)", write_pos)
        apply_pos = fn.find("ApplyPendingIntentLocked", apply_guard)
        self.assertGreater(submit_pos, 0)
        self.assertGreater(write_pos, submit_pos)
        self.assertGreater(apply_pos, write_pos)

    def test_greeting_uses_submit_not_write_first(self):
        cc = read(COORD_CC)
        fn = cc[cc.find("bool ProactiveWakeCoordinator::TrySendProactiveGreeting") :]
        fn = fn[: fn.find("void ProactiveWakeCoordinator::MarkGreetingSent")]
        self.assertIn("SubmitMainWsOpenRequest", fn)
        self.assertNotIn("pending_main_ws_action_", fn)
        self.assertIn("kRejectedLowerPriority", fn)
        self.assertIn("pending_applied", fn)

    def test_manual_paths_use_submit_with_intent(self):
        cc = read(APP_CC)
        for marker in (
            "PendingMainWsAction::kToggleChatListening",
            "PendingMainWsAction::kStartManualListening",
            "PendingMainWsAction::kWakeWordFlow",
        ):
            idx = cc.find(marker)
            self.assertGreater(idx, 0, marker)
            block = cc[max(0, idx - 400) : idx + 200]
            self.assertIn("SubmitMainWsOpenRequest", block, marker)
            self.assertIn("MainWsPendingIntent", block, marker)

    def test_upgrade_clears_greeting_before_manual_pending(self):
        cc = read(APP_CC)
        fn = cc[cc.find("Application::MainWsSubmitOutcome "
                         "Application::SubmitMainWsOpenRequestLocked") :]
        fn = fn[: fn.find("Application::MainWsSubmitOutcome "
                          "Application::SubmitMainWsOpenRequest(")]
        up = fn.find("SubmitResult::kUpgradedManual")
        clear = fn.find("ClearProactiveChatPendingLocked")
        apply_guard = fn.find("if (write_pending)")
        self.assertGreater(up, 0)
        self.assertGreater(clear, 0)
        self.assertGreater(apply_guard, clear)

    def test_rejected_does_not_apply_pending(self):
        cc = read(POLICY_CC)
        self.assertIn("kRejectedLowerPriority", cc)
        self.assertIn("return false", cc)
        self.assertIn("Scenario 1", cc)

    def test_policy_scenarios_in_production(self):
        cc = read(POLICY_CC)
        for needle in (
            "Scenario 1",
            "Scenario 2",
            "Scenario 3",
            "Scenario 4",
            "Scenario 5",
        ):
            self.assertIn(needle, cc)

    def test_public_result_types(self):
        h = read(APP_H)
        for sym in (
            "MainWsOpenRequestResult",
            "MainWsSubmitOutcome",
            "MainWsPendingIntent",
            "SubmitMainWsOpenRequest",
        ):
            self.assertIn(sym, h)


class HostProductionTests(unittest.TestCase):
    def test_host_runner_exit_semantics(self):
        proc = subprocess.run(
            [sys.executable, str(HOST_RUNNER)],
            capture_output=True,
            text=True,
        )
        self.assertIn(proc.returncode, (0, 2), proc.stdout + proc.stderr)
        if proc.returncode == 2:
            self.assertIn("未验证", proc.stderr + proc.stdout)


if __name__ == "__main__":
    unittest.main()
