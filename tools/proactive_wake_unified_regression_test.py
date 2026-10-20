#!/usr/bin/env python3
"""Regression: PresenceSensor / ProactiveWake / Reminder contracts.

State-model assertions + source contract checks (not string-search only).
"""

from __future__ import annotations

import re
import unittest
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# State models
# ---------------------------------------------------------------------------

UNKNOWN = "unknown"
KNOWN_ZERO = "known_zero"
KNOWN_ONE = "known_one_or_more"


@dataclass
class PresenceModel:
    confirmed: bool = False
    generation: int = 0
    events: list[str] = field(default_factory=list)

    def rising_edge_short(self) -> None:
        # High < 1s: no generation, no presence
        self.events.append("short_high")

    def rising_edge_dwell(self) -> None:
        if not self.confirmed:
            self.generation += 1
            self.confirmed = True
            self.events.append(f"stable_present:{self.generation}")

    def low_short(self) -> None:
        self.events.append("short_low")

    def low_absence(self) -> None:
        if not self.confirmed:
            self.events.append("absence_ignored")
            return
        self.confirmed = False
        self.events.append(f"stable_absent:{self.generation}")


@dataclass
class WakeModel:
    state: str = "Idle"
    active_gen: int = 0
    greetings: int = 0
    last_greeting_ms: int = 0
    enrollment: str = UNKNOWN
    now_ms: int = 0
    cancelled: list[str] = field(default_factory=list)

    def on_stable_presence(self, gen: int, has_reminder: bool = False) -> None:
        if self.state != "Idle" and self.active_gen == gen:
            return
        self.active_gen = gen
        if has_reminder:
            self.state = "DeliveringReminder"
            return
        self.state = "WaitingForInitialize"

    def on_initialize(self, session_ok: bool, enrollment: str) -> None:
        if self.state not in ("WaitingForInitialize", "DeliveringReminder"):
            return
        if not session_ok:
            self.cancelled.append("stale_session")
            return
        self.enrollment = enrollment
        if self.state == "DeliveringReminder":
            return
        if enrollment == KNOWN_ZERO:
            self._greet(False)
        elif enrollment == KNOWN_ONE:
            self.state = "VerifyingFace"
        else:
            self.state = "Idle"

    def on_face_verified(self, gen: int) -> None:
        if gen != self.active_gen or self.state != "VerifyingFace":
            self.cancelled.append("face_stale")
            return
        self._greet(True)

    def on_absence(self, gen: int) -> None:
        self.cancelled.append(f"absence:{gen}")
        self.state = "Idle"
        self.active_gen = 0

    def _greet(self, verified: bool) -> None:
        if self.now_ms - self.last_greeting_ms < 5 * 60 * 1000 and self.greetings:
            self.state = "Idle"
            return
        self.greetings += 1
        self.last_greeting_ms = self.now_ms
        self.state = "Idle"


@dataclass
class ReminderModel:
    repeat_count: int = 0
    next_at: int = 0
    status: str = "queued"
    paused: bool = False

    def present(self, now: int) -> None:
        if self.paused:
            return
        self.repeat_count += 1
        self.status = "presenting"
        if self.repeat_count == 1:
            self.next_at = now + 5 * 60
        else:
            self.next_at = now + 10 * 60

    def absence(self) -> None:
        self.paused = True
        self.status = "waiting_presence"
        # do not advance next_at / repeat_count

    def re_presence(self, now: int) -> None:
        self.paused = False
        self.present(now)
        # after replay, next is +10min (present already set based on count)


class PresenceWakeTests(unittest.TestCase):
    def test_short_high_no_generation(self):
        p = PresenceModel()
        p.rising_edge_short()
        self.assertFalse(p.confirmed)
        self.assertEqual(p.generation, 0)

    def test_dwell_produces_generation(self):
        p = PresenceModel()
        p.rising_edge_dwell()
        self.assertTrue(p.confirmed)
        self.assertEqual(p.generation, 1)

    def test_short_low_no_absence(self):
        p = PresenceModel()
        p.rising_edge_dwell()
        p.low_short()
        self.assertTrue(p.confirmed)

    def test_absence_after_confirmed(self):
        p = PresenceModel()
        p.rising_edge_dwell()
        p.low_absence()
        self.assertFalse(p.confirmed)

    def test_brief_high_cannot_fake_absence(self):
        p = PresenceModel()
        p.low_absence()  # never confirmed
        self.assertIn("absence_ignored", p.events)

    def test_same_generation_greets_once(self):
        w = WakeModel()
        w.on_stable_presence(1)
        w.on_initialize(True, KNOWN_ZERO)
        self.assertEqual(w.greetings, 1)
        w.on_stable_presence(1)
        w.on_initialize(True, KNOWN_ZERO)
        self.assertEqual(w.greetings, 1)

    def test_rate_limit_5min(self):
        w = WakeModel(now_ms=0)
        w.on_stable_presence(1)
        w.on_initialize(True, KNOWN_ZERO)
        w.now_ms = 60_000
        w.active_gen = 0
        w.state = "Idle"
        w.on_stable_presence(2)
        w.on_initialize(True, KNOWN_ZERO)
        self.assertEqual(w.greetings, 1)

    def test_unknown_no_greeting(self):
        w = WakeModel()
        w.on_stable_presence(1)
        w.on_initialize(True, UNKNOWN)
        self.assertEqual(w.greetings, 0)
        self.assertEqual(w.state, "Idle")

    def test_noface_no_camera(self):
        w = WakeModel()
        w.on_stable_presence(1)
        w.on_initialize(True, KNOWN_ZERO)
        self.assertNotEqual(w.state, "VerifyingFace")
        self.assertEqual(w.greetings, 1)

    def test_known_one_requires_face(self):
        w = WakeModel()
        w.on_stable_presence(1)
        w.on_initialize(True, KNOWN_ONE)
        self.assertEqual(w.state, "VerifyingFace")
        self.assertEqual(w.greetings, 0)
        w.on_face_verified(1)
        self.assertEqual(w.greetings, 1)

    def test_stale_session_initialize_ignored(self):
        w = WakeModel()
        w.on_stable_presence(1)
        w.on_initialize(False, KNOWN_ZERO)
        self.assertEqual(w.greetings, 0)

    def test_absence_cancels(self):
        w = WakeModel()
        w.on_stable_presence(1)
        w.on_absence(1)
        self.assertEqual(w.state, "Idle")
        self.assertTrue(any("absence" in c for c in w.cancelled))

    def test_reminder_priority_over_greeting(self):
        w = WakeModel()
        w.on_stable_presence(1, has_reminder=True)
        self.assertEqual(w.state, "DeliveringReminder")
        w.on_initialize(True, KNOWN_ZERO)
        self.assertEqual(w.greetings, 0)


class ReminderScheduleTests(unittest.TestCase):
    def test_note_5_then_10(self):
        r = ReminderModel()
        r.present(0)
        self.assertEqual(r.repeat_count, 1)
        self.assertEqual(r.next_at, 300)
        r.present(300)
        self.assertEqual(r.repeat_count, 2)
        self.assertEqual(r.next_at, 300 + 600)
        r.present(900)
        self.assertEqual(r.next_at, 900 + 600)

    def test_absence_pauses(self):
        r = ReminderModel()
        r.present(0)
        next_before = r.next_at
        count_before = r.repeat_count
        r.absence()
        self.assertEqual(r.next_at, next_before)
        self.assertEqual(r.repeat_count, count_before)
        self.assertTrue(r.paused)

    def test_represence_replays(self):
        r = ReminderModel()
        r.present(0)
        r.absence()
        r.re_presence(100)
        self.assertEqual(r.repeat_count, 2)
        self.assertEqual(r.next_at, 100 + 600)


class SourceContractTests(unittest.TestCase):
    def test_presence_sensor_contracts(self):
        h = read(ROOT / "main/boards/esp-box-3/presence_sensor.h")
        cc = read(ROOT / "main/boards/esp-box-3/presence_sensor.cc")
        self.assertIn("confirmed_present_", h)
        self.assertIn("presence_generation_", h)
        self.assertIn("RequestStableRecheck", h)
        self.assertIn("ConfirmPresentAndFire", cc)
        self.assertIn("only applies after a confirmed", cc)

    def test_board_recheck_not_direct_gpio(self):
        board = read(ROOT / "main/boards/esp-box-3/esp_box3_board.cc")
        self.assertIn("RequestStableRecheck", board)
        # Idle / UVC paths must not Schedule OnPresenceDetected from raw GPIO
        idle_block = board[board.find("Idle entered") : board.find("Idle entered") + 400]
        self.assertIn("RequestStableRecheck", idle_block)
        self.assertNotIn("OnPresenceDetected()", idle_block)

    def test_no_set_initialize_callback(self):
        h = read(ROOT / "main/face_roster.h")
        self.assertNotIn("SetInitializeCallback", h)
        self.assertNotIn("InitializeCallback", h)

    def test_wake_coordinator_exists(self):
        h = read(ROOT / "main/proactive_wake_coordinator.h")
        self.assertIn("OnStablePresence", h)
        self.assertIn("OnFaceRosterInitialized", h)
        self.assertIn("RequestingAiGreeting", h)
        self.assertIn("IsIdentityOrGreetingInFlight", h)
        cc = read(ROOT / "main/proactive_wake_coordinator.cc")
        self.assertIn("[PROACTIVE_RETURN]", cc)
        self.assertIn("face_identity=", cc)
        self.assertNotIn("identity_mode=no_face", cc)
        self.assertNotIn("usr_", cc.split("TrySendProactiveGreeting")[1][:800]
                         if "TrySendProactiveGreeting" in cc else "")

    def test_noface_bypass_radar_first(self):
        cc = read(ROOT / "main/reminder_coordinator.cc")
        # IsRadarPresent check must appear before AllowNoFaceOwnerBypass in TryBeginDelivery
        fn = cc[cc.find("TryBeginDeliveryLocked") :]
        fn = fn[: fn.find("\nbool ReminderCoordinator::", 10)]
        radar = fn.find("IsRadarPresent")
        bypass = fn.find("AllowNoFaceOwnerBypassLocked")
        self.assertGreater(radar, 0)
        self.assertGreater(bypass, 0)
        self.assertLess(radar, bypass)

    def test_reminder_no_mcp_card_for_notes(self):
        cc = read(ROOT / "main/reminder_coordinator.cc")
        idx = cc.find("void ReminderCoordinator::Present(const ReminderInstance")
        self.assertGreater(idx, 0)
        present = cc[idx : idx + 2500]
        self.assertIn("display->ShowMcpCard(card)", present)
        self.assertIn("source_type != ReminderSourceType::kInformation", present)

    def test_dialogue_bottom_y(self):
        cc = read(ROOT / "main/display/cubicat_home_player.cc")
        self.assertIn("kDialogueShownY = 284", cc)
        self.assertIn("kDialogueH = 28", cc)
        self.assertIn("kDialogueW = 296", cc)

    def test_open_audio_for_reminder(self):
        cc = read(ROOT / "main/application.cc")
        idx = cc.find("void Application::SendReminderProtocolMessage")
        self.assertGreater(idx, 0)
        send = cc[idx : idx + 3200]
        self.assertIn("EnqueueOrSendReminderProtocolMessage", send)
        self.assertIn("main_ws_open::Source::kReminder", send)

    def test_cmake_lists_coordinator(self):
        cmake = read(ROOT / "main/CMakeLists.txt")
        self.assertIn("proactive_wake_coordinator.cc", cmake)


if __name__ == "__main__":
    unittest.main()
