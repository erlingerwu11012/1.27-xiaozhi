#!/usr/bin/env python3
"""Regression: async proactive greeting lifecycle + source contracts."""

from __future__ import annotations

import unittest
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


COOLDOWN_MS = 5 * 60 * 1000


@dataclass
class AsyncGreetingModel:
    """Models pending-greeting lifecycle aligned with ProactiveWakeCoordinator."""

    state: str = "Idle"
    active_gen: int = 0
    session: str = ""
    greetings_sent: int = 0
    last_greeting_ms: int = -1
    now_ms: int = 0
    pending: bool = False
    pending_gen: int = 0
    pending_session: str = ""
    pending_ws_req: int = 0
    manual_done: int = 0
    events: list[str] = field(default_factory=list)

    def in_cooldown(self) -> bool:
        if self.last_greeting_ms < 0:
            return False
        return (self.now_ms - self.last_greeting_ms) < COOLDOWN_MS

    def begin_greeting(self, gen: int, ws_open: bool, ws_req: int = 1) -> None:
        if self.state == "RequestingAiGreeting" and self.active_gen == gen:
            self.events.append("duplicate_suppressed")
            return
        if self.in_cooldown():
            self.events.append("rate_limited")
            self.state = "Idle"
            return
        self.active_gen = gen
        self.state = "RequestingAiGreeting"
        if ws_open:
            self._deliver(gen, self.session, ws_req)
        else:
            self.pending = True
            self.pending_gen = gen
            self.pending_session = self.session
            self.pending_ws_req = ws_req
            self.events.append(f"pending:{gen}:ws_req={ws_req}")

    def ws_open_ok(self, session: str, ws_req: int) -> None:
        self.session = session
        if not self.pending:
            return
        if ws_req != self.pending_ws_req:
            self.events.append(f"discard:ws_req:{ws_req}")
            self._clear_pending("stale_ws_request")
            return
        if self.pending_gen != self.active_gen:
            self._clear_pending("stale_generation")
            return
        self._deliver(self.pending_gen, session, ws_req)

    def ws_open_fail(self, ws_req: int, reason: str) -> None:
        if self.pending and self.pending_ws_req == ws_req:
            self._clear_pending(reason)

    def absence(self, gen: int) -> None:
        if self.pending:
            self._clear_pending("absence")
        self.state = "Idle"
        self.active_gen = 0
        self.events.append(f"absence:{gen}")

    def manual_upgrade(self, ws_req: int) -> None:
        if self.pending and self.pending_ws_req == ws_req:
            self._clear_pending("manual_priority")
        self.manual_done += 1
        self.events.append("manual_upgrade")

    def generation_change(self, new_gen: int) -> None:
        if self.pending and self.pending_gen != new_gen:
            self._clear_pending("generation_change")

    def _deliver(self, gen: int, session: str, ws_req: int) -> None:
        if self.pending:
            if self.pending_ws_req and ws_req != self.pending_ws_req:
                self._clear_pending("stale_ws_request")
                return
            if self.pending_session and session != self.pending_session:
                self._clear_pending("session_mismatch")
                return
        self.greetings_sent += 1
        self.last_greeting_ms = self.now_ms
        self._clear_pending("delivered")
        self.state = "Idle"
        self.events.append(f"sent:{gen}:session={session}")

    def _clear_pending(self, reason: str) -> None:
        self.pending = False
        self.pending_gen = 0
        self.pending_session = ""
        self.pending_ws_req = 0
        if self.state == "RequestingAiGreeting":
            self.state = "Idle"
        self.events.append(f"discard:{reason}")


class AsyncGreetingLifecycleTests(unittest.TestCase):
    def test_ws_open_immediate_single_send_and_cooldown(self):
        m = AsyncGreetingModel(session="s1")
        m.begin_greeting(1, ws_open=True)
        self.assertEqual(m.greetings_sent, 1)
        self.assertFalse(m.pending)
        m.now_ms = 60_000
        m.begin_greeting(2, ws_open=True)
        self.assertEqual(m.greetings_sent, 1)
        self.assertIn("rate_limited", m.events)

    def test_ws_closed_then_open_sends_once_then_cooldown(self):
        m = AsyncGreetingModel(session="")
        m.begin_greeting(1, ws_open=False, ws_req=7)
        self.assertTrue(m.pending)
        self.assertEqual(m.greetings_sent, 0)
        self.assertEqual(m.last_greeting_ms, -1)
        m.ws_open_ok("s1", 7)
        self.assertEqual(m.greetings_sent, 1)
        self.assertFalse(m.pending)

    def test_pending_absence_no_send_no_cooldown(self):
        m = AsyncGreetingModel()
        m.begin_greeting(1, ws_open=False, ws_req=3)
        m.absence(1)
        self.assertEqual(m.greetings_sent, 0)
        self.assertEqual(m.last_greeting_ms, -1)
        self.assertFalse(m.pending)

    def test_pending_stale_ws_req_no_send(self):
        m = AsyncGreetingModel()
        m.begin_greeting(1, ws_open=False, ws_req=2)
        m.ws_open_ok("s1", 99)
        self.assertEqual(m.greetings_sent, 0)
        self.assertEqual(m.last_greeting_ms, -1)

    def test_pending_generation_change_no_send(self):
        m = AsyncGreetingModel(active_gen=1)
        m.begin_greeting(1, ws_open=False, ws_req=4)
        m.generation_change(2)
        m.ws_open_ok("s1", 4)
        self.assertEqual(m.greetings_sent, 0)

    def test_radar_jitter_cooldown_no_repeat(self):
        m = AsyncGreetingModel(session="s1")
        m.begin_greeting(1, ws_open=True)
        m.begin_greeting(1, ws_open=True)
        self.assertEqual(m.greetings_sent, 1)
        self.assertTrue(
            "duplicate_suppressed" in m.events or "rate_limited" in m.events
        )

    def test_manual_upgrade_discards_greeting(self):
        m = AsyncGreetingModel()
        m.begin_greeting(1, ws_open=False, ws_req=5)
        m.manual_upgrade(5)
        self.assertEqual(m.greetings_sent, 0)
        self.assertEqual(m.manual_done, 1)
        self.assertFalse(m.pending)


class ProactiveGreetingSourceContracts(unittest.TestCase):
    def test_no_ws_async_pending_reset(self):
        cc = read(ROOT / "main/proactive_wake_coordinator.cc")
        self.assertNotIn('ResetToIdle("ws_async_pending")', cc)

    def test_pending_greeting_hooks(self):
        h = read(ROOT / "main/proactive_wake_coordinator.h")
        cc = read(ROOT / "main/proactive_wake_coordinator.cc")
        app = read(ROOT / "main/application.cc")
        for sym in (
            "ArmPendingGreeting",
            "OnProactiveGreetingDelivered",
            "DiscardPendingGreeting",
            "HasPendingGreeting",
            "IsIdentityOrGreetingInFlight",
            "IsProactiveGreetingPayload",
        ):
            self.assertIn(sym, h, sym)
            self.assertIn(sym, cc, sym)
        self.assertIn("CompletePendingMainWsAction(snapshot.request_id)", app)
        self.assertIn("GetMainWsOpenActiveRequestId", app)

    def test_mark_greeting_after_delivery_not_before_pending(self):
        cc = read(ROOT / "main/proactive_wake_coordinator.cc")
        fn = cc[cc.find("bool ProactiveWakeCoordinator::TrySendProactiveGreeting") :]
        fn = fn[: fn.find("void ProactiveWakeCoordinator::MarkGreetingSent")]
        pending_idx = fn.find("ArmPendingGreeting")
        mark_before_pending = fn.find("MarkGreetingSent", 0, pending_idx)
        self.assertEqual(mark_before_pending, -1)
        self.assertGreater(pending_idx, 0)

    def test_delivery_marks_cooldown(self):
        cc = read(ROOT / "main/proactive_wake_coordinator.cc")
        fn = cc[cc.find("void ProactiveWakeCoordinator::OnProactiveGreetingDelivered") :]
        fn = fn[: fn.find("void ProactiveWakeCoordinator::MarkGreetingSent")]
        self.assertIn("MarkGreetingSent()", fn)
        self.assertIn('ResetToIdle("greeting_sent")', fn)

    def test_unknown_enrollment_still_silent(self):
        cc = read(ROOT / "main/proactive_wake_coordinator.cc")
        branch = cc[cc.find("void ProactiveWakeCoordinator::BranchOnEnrollment") :]
        branch = branch[: branch.find("void ProactiveWakeCoordinator::RequestNoFaceGreeting")]
        self.assertIn("kUnknown", branch)
        self.assertIn("silent", branch)

    def test_manual_upgrade_discards_greeting(self):
        app = read(ROOT / "main/application.cc")
        self.assertIn("DiscardPendingGreeting", app)
        self.assertIn('"manual_priority"', app)


if __name__ == "__main__":
    unittest.main()
