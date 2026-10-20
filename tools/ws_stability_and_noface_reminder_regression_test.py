"""Host regression: WS fair scheduling, transient send, session/card isolation,
no-face owner delivery, and MCP recipient_identity_missing error codes.
"""

from __future__ import annotations

import unittest
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def is_usr(person_id: str) -> bool:
    return person_id.startswith("usr_") and len(person_id) > 4


# Runtime send behavior: run_ws_audio_send_host_test.py (actual C++ functions).

# --- Fair scheduling model ---


class FairLoopModel:
    def __init__(self):
        self.send_queue = 0
        self.pings = 0
        self.audio_sent = 0
        self.clock_ticks = 0
        self.max_audio_per_turn = 8

    def turn(self, bits: set[str]):
        if "schedule" in bits:
            pass
        if "send_audio" in bits:
            n = 0
            while n < self.max_audio_per_turn and self.send_queue > 0:
                self.send_queue -= 1
                self.audio_sent += 1
                n += 1
        if "clock" in bits:
            self.clock_ticks += 1
            if self.clock_ticks % 20 == 0:
                self.pings += 1


class FairScheduleTests(unittest.TestCase):
    def test_ping_survives_audio_flood(self):
        loop = FairLoopModel()
        loop.send_queue = 200
        for tick in range(1, 41):
            bits = {"clock"}
            if loop.send_queue:
                bits.add("send_audio")
            loop.turn(bits)
        self.assertEqual(loop.pings, 2)
        self.assertLess(loop.send_queue, 200)
        self.assertGreater(loop.audio_sent, 0)


# --- No-face owner delivery ---


@dataclass
class Reminder:
    instance_id: str
    recipient: str
    status: str = "queued"
    bound_session: str = ""
    no_face_bypass: bool = False
    revision: int = 1


@dataclass
class Engine:
    face_count: int = 0
    session_id: str = ""
    current: str | None = None
    reminders: dict[str, Reminder] = field(default_factory=dict)
    cards: list[str] = field(default_factory=list)
    actions: list[tuple[str, str]] = field(default_factory=list)

    def add(self, rem: Reminder):
        if not is_usr(rem.recipient):
            raise ValueError("recipient_identity_missing")
        self.reminders[rem.instance_id] = rem

    def tick_due(self, rid: str):
        rem = self.reminders[rid]
        if self.face_count == 0 and is_usr(rem.recipient):
            rem.no_face_bypass = True
            rem.status = "presenting"
            rem.bound_session = self.session_id
            rem.revision += 1
            self.current = rid
            self.cards.append(rid)
            return True
        # faces enrolled: require explicit confirm (not modeled here)
        rem.status = "waiting_recipient"
        return False

    def act(self, rid: str, actor: str) -> str:
        rem = self.reminders[rid]
        if rem.bound_session.startswith("__closed__"):
            return "session_mismatch"
        if rem.bound_session and rem.bound_session != self.session_id:
            return "session_mismatch"
        if rem.no_face_bypass and self.face_count == 0:
            self.actions.append((rid, actor or rem.recipient))
            rem.status = "completed"
            return "ok"
        if actor != rem.recipient:
            return "identity_mismatch"
        self.actions.append((rid, actor))
        rem.status = "completed"
        return "ok"

    def close_session(self):
        if self.current and self.current in self.reminders:
            rem = self.reminders[self.current]
            rem.status = "queued"
            rem.bound_session = "__closed__:" + (rem.bound_session or "none")
            rem.revision += 1
            self.current = None
        self.session_id = ""


class NoFaceDeliveryTests(unittest.TestCase):
    def test_no_face_usr_presents_and_acts(self):
        eng = Engine(face_count=0, session_id="s1")
        eng.add(Reminder("note:1", "usr_owner"))
        self.assertTrue(eng.tick_due("note:1"))
        self.assertEqual(eng.cards, ["note:1"])
        self.assertEqual(eng.act("note:1", ""), "ok")

    def test_illegal_recipient_rejected(self):
        eng = Engine(face_count=0)
        with self.assertRaises(ValueError) as ctx:
            eng.add(Reminder("note:x", "default"))
        self.assertIn("recipient_identity_missing", str(ctx.exception))

    def test_with_faces_no_bypass(self):
        eng = Engine(face_count=2, session_id="s1")
        eng.add(Reminder("note:2", "usr_owner"))
        self.assertFalse(eng.tick_due("note:2"))
        self.assertEqual(eng.cards, [])

    def test_session_close_invalidates_card_action(self):
        eng = Engine(face_count=0, session_id="s1")
        eng.add(Reminder("note:3", "usr_owner"))
        eng.tick_due("note:3")
        eng.close_session()
        eng.session_id = "s2"
        self.assertEqual(eng.act("note:3", "usr_owner"), "session_mismatch")

    def test_device_a_card_not_visible_on_b(self):
        a = Engine(face_count=0, session_id="a1")
        b = Engine(face_count=0, session_id="b1")
        a.add(Reminder("note:a", "usr_owner"))
        a.tick_due("note:a")
        self.assertEqual(a.cards, ["note:a"])
        self.assertEqual(b.cards, [])
        self.assertNotIn("note:a", b.reminders)


# --- Source contracts ---


class SourceContracts(unittest.TestCase):
    def test_ws_diag_and_error_event(self):
        text = read(ROOT / "main" / "esp_network.h")
        self.assertIn("[WS_DIAG]", text)
        self.assertIn("WEBSOCKET_EVENT_ERROR", text)
        self.assertIn("WasLastSendTransient", text)
        self.assertIn("ctrl_frame=PING", text)
        self.assertIn("NoteWifiDisconnectReason", text)

    def test_fair_audio_batch(self):
        text = read(ROOT / "main" / "application.cc")
        self.assertIn("kMaxAudioSendsPerTurn", text)
        self.assertIn("[WS_DIAG] app_ping", text)
        self.assertIn("OnAudioSessionClosed", text)

    def test_transient_send_path(self):
        text = read(ROOT / "main" / "protocols" / "websocket_protocol.cc")
        self.assertIn("WasLastSendTransient", text)
        self.assertIn("transient_send_fail", text)
        self.assertNotIn("kMaxTransientAudioFailures", text)

    def test_mcp_error_code(self):
        note = read(ROOT / "main" / "mcp_tools" / "mcp_tools_note.cc")
        hdr = read(ROOT / "main" / "mcp_server.h")
        self.assertIn("errorCode", hdr)
        self.assertIn("std::string code", hdr)
        card_action = read(ROOT / "main" / "mcp_card_action.cc")
        self.assertIn("recipient_identity_missing", card_action)

    def test_no_face_bypass_and_session(self):
        text = read(ROOT / "main" / "reminder_coordinator.cc")
        self.assertIn("AllowNoFaceOwnerBypassLocked", text)
        self.assertIn("AllowsNoFaceOwnerBypass", text)
        self.assertIn("OnSessionClosed", text)
        self.assertIn("session_mismatch", text)

    def test_face_roster_capability(self):
        text = read(ROOT / "main" / "mcp_server.cc")
        self.assertIn("ApplyInitialize", text)
        self.assertIn("default_owner_person_id", text)
        self.assertTrue((ROOT / "main" / "face_roster.cc").exists())
        hdr = read(ROOT / "main" / "face_roster.h")
        self.assertIn("kUnknown", hdr)
        self.assertIn("kKnownZero", hdr)

    def test_ui_identity_message(self):
        text = read(ROOT / "main" / "mcp_card_action.cc")
        self.assertIn("用户身份未同步", text)


if __name__ == "__main__":
    unittest.main()
