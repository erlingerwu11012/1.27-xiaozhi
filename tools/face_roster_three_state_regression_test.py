"""Host regression for FaceRoster three-state no-face bypass gate.

Mirrors firmware FaceEnrollmentState:
  unknown / known_zero / known_one_or_more
Bypass requires known_zero + default_owner usr_* match.
"""

from __future__ import annotations

import unittest
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def is_usr(person_id: str) -> bool:
    return bool(person_id) and person_id.startswith("usr_") and len(person_id) > 4


UNKNOWN = "unknown"
KNOWN_ZERO = "known_zero"
KNOWN_ONE = "known_one_or_more"


@dataclass
class FaceRosterModel:
    state: str = UNKNOWN
    count: int = 0
    default_owner: str = ""
    bound_session: str = ""
    current_session: str = ""
    log: list[str] = field(default_factory=list)

    def _log(self, source: str, session_match: bool = True) -> None:
        self.log.append(
            f"state={self.state} source={source} match={int(session_match)}"
        )

    def mark_unknown(self, source: str = "mark_unknown") -> None:
        self.state = UNKNOWN
        self.count = 0
        self.default_owner = ""
        self._log(source)

    def on_session_opened(self, session_id: str) -> None:
        self.current_session = session_id
        self.state = UNKNOWN
        self.count = 0
        self.default_owner = ""
        self.bound_session = session_id
        self._log("session_opened")

    def on_session_closed(self, closed: str) -> None:
        if closed and self.bound_session and closed != self.bound_session:
            self._log("session_closed_other", False)
            return
        self.state = UNKNOWN
        self.count = 0
        self.default_owner = ""
        self.bound_session = ""
        self.current_session = ""
        self._log("session_closed")

    def apply_initialize(
        self,
        session_id: str,
        count_present: bool,
        count: int,
        default_owner: str = "",
        source: str = "initialize",
    ) -> bool:
        if session_id and self.current_session and session_id != self.current_session:
            self._log("initialize_stale", False)
            return False
        if self.current_session:
            self.bound_session = self.current_session
        elif session_id:
            self.bound_session = session_id

        if not count_present or count < 0:
            self.state = UNKNOWN
            self.count = 0
            self.default_owner = ""
            self._log(source)
            return True

        if count == 0:
            self.state = KNOWN_ZERO
            self.count = 0
        else:
            self.state = KNOWN_ONE
            self.count = count

        self.default_owner = default_owner if is_usr(default_owner) else ""
        self._log(source)
        return True

    def local_enroll(self) -> None:
        self.state = KNOWN_ONE
        if self.count == 0:
            self.count = 1
        self._log("local_enroll")

    def local_delete_untrusted(self) -> None:
        self.mark_unknown("local_delete")

    def allows_bypass(self, recipient: str) -> bool:
        return (
            self.state == KNOWN_ZERO
            and is_usr(recipient)
            and is_usr(self.default_owner)
            and recipient == self.default_owner
        )


@dataclass
class Reminder:
    instance_id: str
    recipient: str
    status: str = "queued"
    bound_session: str = ""
    no_face_bypass: bool = False


@dataclass
class Engine:
    roster: FaceRosterModel = field(default_factory=FaceRosterModel)
    reminders: dict[str, Reminder] = field(default_factory=dict)
    cards: list[str] = field(default_factory=list)
    session_id: str = ""

    def add(self, rem: Reminder) -> None:
        if not is_usr(rem.recipient):
            raise ValueError("recipient_identity_missing")
        self.reminders[rem.instance_id] = rem

    def tick_due(self, rid: str) -> bool:
        rem = self.reminders[rid]
        if self.roster.allows_bypass(rem.recipient):
            rem.no_face_bypass = True
            rem.status = "presenting"
            rem.bound_session = self.session_id
            self.cards.append(rid)
            return True
        rem.status = "waiting_recipient"
        return False

    def act(self, rid: str) -> str:
        rem = self.reminders[rid]
        if rem.bound_session.startswith("__closed__"):
            return "session_mismatch"
        if rem.no_face_bypass and self.roster.allows_bypass(rem.recipient):
            rem.status = "completed"
            return "ok"
        return "identity_mismatch"


class FaceRosterThreeStateTests(unittest.TestCase):
    def test_boot_default_unknown_no_bypass(self):
        r = FaceRosterModel()
        self.assertEqual(r.state, UNKNOWN)
        self.assertFalse(r.allows_bypass("usr_owner"))

    def test_missing_initialize_count_stays_unknown(self):
        r = FaceRosterModel()
        r.on_session_opened("s1")
        r.apply_initialize("s1", count_present=False, count=-1)
        self.assertEqual(r.state, UNKNOWN)
        self.assertFalse(r.allows_bypass("usr_owner"))

    def test_face_enrollment_missing_unknown(self):
        r = FaceRosterModel()
        r.on_session_opened("s1")
        r.apply_initialize("s1", False, -1, source="initialize_face_enrollment_missing")
        self.assertEqual(r.state, UNKNOWN)

    def test_illegal_count_unknown(self):
        r = FaceRosterModel()
        r.on_session_opened("s1")
        r.apply_initialize("s1", True, -3)
        self.assertEqual(r.state, UNKNOWN)

    def test_known_zero_with_default_owner_bypass(self):
        eng = Engine()
        eng.session_id = "s1"
        eng.roster.on_session_opened("s1")
        eng.roster.apply_initialize(
            "s1", True, 0, default_owner="usr_owner"
        )
        self.assertEqual(eng.roster.state, KNOWN_ZERO)
        eng.add(Reminder("note:1", "usr_owner"))
        self.assertTrue(eng.tick_due("note:1"))
        self.assertEqual(eng.cards, ["note:1"])
        self.assertEqual(eng.act("note:1"), "ok")

    def test_known_zero_without_default_owner_no_bypass(self):
        r = FaceRosterModel()
        r.on_session_opened("s1")
        r.apply_initialize("s1", True, 0, default_owner="")
        self.assertEqual(r.state, KNOWN_ZERO)
        self.assertFalse(r.allows_bypass("usr_owner"))

    def test_known_zero_wrong_recipient_no_bypass(self):
        r = FaceRosterModel()
        r.on_session_opened("s1")
        r.apply_initialize("s1", True, 0, default_owner="usr_owner")
        self.assertFalse(r.allows_bypass("usr_guest"))

    def test_known_one_or_more_no_bypass(self):
        r = FaceRosterModel()
        r.on_session_opened("s1")
        r.apply_initialize("s1", True, 2, default_owner="usr_owner")
        self.assertEqual(r.state, KNOWN_ONE)
        self.assertFalse(r.allows_bypass("usr_owner"))

    def test_stale_session_initialize_rejected(self):
        r = FaceRosterModel()
        r.on_session_opened("A2")
        r.apply_initialize("A2", True, 2, default_owner="usr_owner")
        self.assertEqual(r.state, KNOWN_ONE)
        ok = r.apply_initialize("A1", True, 0, default_owner="usr_owner")
        self.assertFalse(ok)
        self.assertEqual(r.state, KNOWN_ONE)

    def test_session_open_resets_prior_zero(self):
        r = FaceRosterModel()
        r.on_session_opened("s1")
        r.apply_initialize("s1", True, 0, default_owner="usr_owner")
        r.on_session_opened("s2")
        self.assertEqual(r.state, UNKNOWN)
        self.assertFalse(r.allows_bypass("usr_owner"))

    def test_local_enroll_and_delete(self):
        r = FaceRosterModel()
        r.on_session_opened("s1")
        r.apply_initialize("s1", True, 0, default_owner="usr_owner")
        r.local_enroll()
        self.assertEqual(r.state, KNOWN_ONE)
        r.local_delete_untrusted()
        self.assertEqual(r.state, UNKNOWN)

    def test_device_isolation(self):
        a = Engine()
        b = Engine()
        a.session_id = "a1"
        a.roster.on_session_opened("a1")
        a.roster.apply_initialize("a1", True, 0, "usr_owner")
        a.add(Reminder("note:a", "usr_owner"))
        a.tick_due("note:a")
        self.assertEqual(a.cards, ["note:a"])
        self.assertEqual(b.cards, [])
        self.assertNotIn("note:a", b.reminders)


class FirmwareSourceContracts(unittest.TestCase):
    def test_face_roster_has_three_states(self):
        hdr = read(ROOT / "main" / "face_roster.h")
        self.assertIn("kUnknown", hdr)
        self.assertIn("kKnownZero", hdr)
        self.assertIn("kKnownOneOrMore", hdr)
        self.assertIn("AllowsNoFaceOwnerBypass", hdr)
        self.assertIn("ApplyInitialize", hdr)
        cc = read(ROOT / "main" / "face_roster.cc")
        self.assertIn("reject_stale_initialize", cc)
        self.assertIn("session_closed", cc)
        self.assertIn("enrollment_state=", cc)

    def test_bypass_uses_allows_api(self):
        text = read(ROOT / "main" / "reminder_coordinator.cc")
        self.assertIn("AllowsNoFaceOwnerBypass", text)
        self.assertNotIn(
            "if (FaceRoster::GetInstance().HasAnyFaceTemplate()) return false;",
            text,
        )

    def test_mcp_initialize_wires_apply(self):
        text = read(ROOT / "main" / "mcp_server.cc")
        self.assertIn("ApplyInitialize", text)
        self.assertIn("default_owner_person_id", text)
        self.assertIn("initialize_face_enrollment_missing", text)


if __name__ == "__main__":
    unittest.main()
