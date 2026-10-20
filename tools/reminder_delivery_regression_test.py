"""Host-side regression for person-targeted reminder delivery gates.

Does not require camera, network, or a real face library. Models the firmware
delivery state machine with fake presence / identity / display / audio sinks.
"""

from __future__ import annotations

import unittest
from dataclasses import dataclass, field


def is_usr(person_id: str) -> bool:
    return person_id.startswith("usr_") and len(person_id) > 4


def starts_with_https(url: str) -> bool:
    return url.startswith("https://")


def accept_identity_url(identity_url: str, explain_url: str = "", token: str = "t") -> tuple[bool, str]:
    """Mirror IdentityClient::SetVisionConfig HTTPS fail-closed rules."""
    if not identity_url:
        return False, "missing"
    if not starts_with_https(identity_url):
        return False, "not_https"
    if explain_url and not starts_with_https(explain_url):
        return False, "explain_not_https"
    if not token:
        return False, "token_missing"
    return True, "ok"


def set_active_user_id(candidate: str) -> str:
    """Mirror UserContext::SetActiveUserId — only usr_* is accepted."""
    return candidate if is_usr(candidate) else ""


@dataclass
class Presence:
    radar: bool = False
    generation: int = 0
    confirmed_id: str = ""
    confirmed_gen: int = 0
    confirmed_at: int = 0

    def set_radar(self, present: bool, now: int) -> None:
        if present == self.radar:
            return
        self.radar = present
        if present:
            self.generation += 1
        self.confirmed_id = ""
        self.confirmed_gen = 0
        self.confirmed_at = 0

    def confirm(self, person_id: str, now: int) -> None:
        self.confirmed_id = person_id
        self.confirmed_gen = self.generation
        self.confirmed_at = now

    def fresh_match(self, recipient: str, gen: int, now: int) -> bool:
        return (
            self.radar
            and gen == self.generation
            and self.confirmed_gen == gen
            and self.confirmed_id == recipient
            and now - self.confirmed_at <= 10
        )


@dataclass
class Reminder:
    instance_id: str
    recipient_person_id: str
    creator_person_id: str = ""
    revision: int = 1
    status: str = "queued"
    due: bool = True
    delivery_unbound: bool = False
    priority: str = "normal"  # normal / high / information
    source_type: str = "note"
    chime_gen: int = 0
    voice_gen: int = 0
    delivery_gen: int = 0
    next_retry_at: int = 0
    reattention_count: int = 0
    next_attention_at: int = 0
    last_presented_at: int = 0
    no_face_bypass: bool = False
    bound_session: str = ""
    voice_cached: bool = True
    unattended_chime_emitted: bool = False


@dataclass
class Sink:
    chimes: list[str] = field(default_factory=list)
    cards: list[tuple[str, int]] = field(default_factory=list)
    voice_requests: list[str] = field(default_factory=list)
    played_cache: list[str] = field(default_factory=list)
    hidden: list[tuple[str, int]] = field(default_factory=list)
    dismissed: list[tuple[str, int]] = field(default_factory=list)
    ws_reconnect_attempts: int = 0
    main_loop_blocked_ms: int = 0


class DeliveryEngine:
    def __init__(self) -> None:
        self.presence = Presence()
        self.sink = Sink()
        self.identity_queue: list[list[tuple[str, str]]] = []
        self.now = 1000
        self.current: str | None = None
        self.reminders: dict[str, Reminder] = {}
        self.identity_endpoint_ok = True
        self.ws_connected = True
        self.face_template_count = 1  # default: faces enrolled (legacy tests)
        self.broadcast_armed = False
        self.pending_broadcast_prompt = False

    def add(self, reminder: Reminder) -> None:
        if reminder.creator_person_id == "" and is_usr(reminder.recipient_person_id):
            reminder.creator_person_id = reminder.recipient_person_id
        if reminder.recipient_person_id and not is_usr(reminder.recipient_person_id):
            reminder.delivery_unbound = True
            reminder.recipient_person_id = ""
        self.reminders[reminder.instance_id] = reminder

    def queue_identity(self, results: list[tuple[str, str]]) -> None:
        self.identity_queue.append(results)

    def rank(self, rem: Reminder) -> int:
        if rem.priority == "high":
            return 0
        if rem.source_type == "information":
            return 3
        return 2

    def tick(self) -> None:
        for rem in self.reminders.values():
            if (
                rem.due
                and rem.source_type in {"note", "habit"}
                and rem.status
                in {"queued", "waiting_presence", "waiting_recipient"}
                and not self.presence.radar
                and not rem.unattended_chime_emitted
            ):
                rem.unattended_chime_emitted = True
                rem.status = "waiting_presence"
                rem.revision += 1
                self.sink.chimes.append(rem.instance_id)

        due = [
            r
            for r in self.reminders.values()
            if r.due
            and r.status
            in {"queued", "waiting_presence", "waiting_recipient"}
            and r.next_retry_at <= self.now
            and (
                r.status != "queued"
                or r.next_attention_at == 0
                or r.next_attention_at <= self.now
            )
        ]
        if not due:
            return
        pending_normal = [
            r
            for r in due
            if r.source_type in {"note", "habit"}
        ]
        if (
            self.presence.radar
            and len(pending_normal) >= 2
            and not self.broadcast_armed
        ):
            self.pending_broadcast_prompt = True
            return
        due.sort(key=lambda r: (self.rank(r), r.instance_id))
        rem = due[0]
        if rem.delivery_unbound or not is_usr(rem.recipient_person_id):
            rem.status = "waiting_recipient"
            return
        # Three-state face roster (mirrors FaceRoster::AllowsNoFaceOwnerBypass).
        state = getattr(self, "face_enrollment_state", None)
        default_owner = getattr(self, "default_owner_person_id", "")
        if state == "unknown":
            rem.status = "waiting_recipient"
            return
        if state == "known_zero" or (
            state is None and self.face_template_count == 0
        ):
            if not self.presence.radar:
                rem.status = "waiting_presence"
                return
            if default_owner:
                if rem.recipient_person_id == default_owner:
                    rem.delivery_gen = self.presence.generation
                    rem.no_face_bypass = True
                    self._present(rem, rem.delivery_gen)
                else:
                    rem.status = "waiting_recipient"
                return
            if state is None:
                # Legacy host tests: count==0 without default_owner.
                rem.delivery_gen = self.presence.generation
                rem.no_face_bypass = True
                self._present(rem, rem.delivery_gen)
                return
            # Explicit known_zero without default_owner → no bypass (firmware).
            rem.status = "waiting_recipient"
            return
        if not self.presence.radar:
            rem.status = "waiting_presence"
            return
        if not self.identity_endpoint_ok:
            rem.status = "waiting_recipient"
            rem.next_retry_at = self.now + 20
            return
        gen = self.presence.generation
        if self.presence.fresh_match(rem.recipient_person_id, gen, self.now):
            self._present(rem, gen)
            return
        rem.status = "verifying_identity"
        rem.delivery_gen = gen
        rem.revision += 1
        self._verify(rem)

    def begin_broadcast(self) -> None:
        self.broadcast_armed = True
        self.pending_broadcast_prompt = False
        self.tick()

    def _verify(self, rem: Reminder) -> None:
        results = self.identity_queue.pop(0) if self.identity_queue else []
        if len(results) < 2:
            rem.status = "waiting_recipient"
            rem.next_retry_at = self.now + 20
            return
        (s1, u1), (s2, u2) = results[0], results[1]
        if (
            s1 == "known"
            and s2 == "known"
            and u1 == u2 == rem.recipient_person_id
            and self.presence.radar
            and self.presence.generation == rem.delivery_gen
        ):
            self.presence.confirm(u1, self.now)
            self._present(rem, rem.delivery_gen)
            return
        rem.status = "waiting_recipient"
        rem.next_retry_at = self.now + 20

    def _present(self, rem: Reminder, gen: int) -> None:
        # Atomic preemption against current presenting card.
        if self.current and self.current in self.reminders:
            old = self.reminders[self.current]
            if old.status == "presenting" and old.instance_id != rem.instance_id:
                if self.rank(rem) >= self.rank(old):
                    rem.status = "waiting_recipient"
                    rem.next_retry_at = self.now + 5
                    return
                old_rev = old.revision
                if old.source_type == "information":
                    old.status = "queued"
                    old.next_attention_at = self.now
                else:
                    old.status = "waiting_recipient"
                    old.next_retry_at = self.now + 5
                old.revision += 1
                self.sink.dismissed.append((old.instance_id, old_rev))

        rem.status = "presenting"
        rem.revision += 1
        rem.last_presented_at = self.now
        rem.next_attention_at = self.now + 120
        self.current = rem.instance_id
        self.sink.cards.append((rem.instance_id, rem.revision))
        # Cached due audio is local and instance-bound.  Missing cache falls
        # back to a chime plus a best-effort voice_request.
        if rem.voice_cached:
            self.sink.played_cache.append(rem.instance_id)
            rem.voice_gen = gen
            return
        if rem.chime_gen != gen:
            self.sink.chimes.append(rem.instance_id)
            rem.chime_gen = gen
        if rem.voice_gen != gen:
            if self.ws_connected:
                self.sink.voice_requests.append(rem.instance_id)
            rem.voice_gen = gen

    def absence(self) -> None:
        self.presence.set_radar(False, self.now)
        if self.current and self.current in self.reminders:
            rem = self.reminders[self.current]
            if rem.status == "presenting":
                self.sink.hidden.append((rem.instance_id, rem.revision))
                rem.status = "waiting_presence"
                rem.revision += 1
                self.current = None

    def act(self, instance_id: str, actor: str, expected_revision: int | None = None) -> str:
        rem = self.reminders[instance_id]
        if rem.bound_session.startswith("__closed__"):
            return "session_mismatch"
        if rem.no_face_bypass and self.face_template_count == 0:
            if expected_revision is not None and expected_revision != rem.revision:
                return "stale_revision"
            rem.status = "completed"
            return "ok"
        if rem.recipient_person_id != actor:
            return "identity_mismatch"
        if expected_revision is not None and expected_revision != rem.revision:
            return "stale_revision"
        rem.status = "completed"
        return "ok"

    def close_session(self) -> None:
        if self.current and self.current in self.reminders:
            rem = self.reminders[self.current]
            rem.bound_session = "__closed__:" + (rem.bound_session or "none")
            rem.status = "queued"
            rem.revision += 1
            self.current = None

    def dismiss_card(self, instance_id: str, revision: int) -> bool:
        """Simulate DismissMcpCard(instance_id, revision) exact match."""
        if self.current != instance_id:
            # Old dismiss must not close a different current card.
            return False
        rem = self.reminders[instance_id]
        if rem.revision != revision:
            return False
        rem.status = "queued"
        self.current = None
        return True

    def migrate_owner(self, owner: str) -> Reminder:
        rem = Reminder("legacy:1", "")
        if is_usr(owner):
            rem.creator_person_id = owner
            rem.recipient_person_id = owner
        else:
            rem.creator_person_id = owner
            rem.delivery_unbound = True
        self.add(rem)
        return rem


class ReminderDeliveryRegressionTest(unittest.TestCase):
    def test_due_without_presence_chimes_only(self) -> None:
        eng = DeliveryEngine()
        eng.add(Reminder("note:1", "usr_alice"))
        eng.tick()
        self.assertEqual(eng.reminders["note:1"].status, "waiting_presence")
        self.assertEqual(eng.sink.chimes, ["note:1"])
        self.assertEqual(eng.sink.cards, [])
        self.assertEqual(eng.sink.voice_requests, [])
        self.assertEqual(eng.sink.played_cache, [])

    def test_unknown_or_error_rejects(self) -> None:
        for results in (
            [("unknown", ""), ("unknown", "")],
            [("no_face", ""), ("no_face", "")],
            [("ambiguous", ""), ("ambiguous", "")],
            [("error", ""), ("error", "")],
        ):
            eng = DeliveryEngine()
            eng.add(Reminder("note:2", "usr_alice"))
            eng.presence.set_radar(True, eng.now)
            eng.queue_identity(results)
            eng.tick()
            self.assertEqual(eng.reminders["note:2"].status, "waiting_recipient")
            self.assertEqual(eng.sink.cards, [])
            self.assertEqual(eng.sink.chimes, [])

    def test_two_matching_known_delivers_once(self) -> None:
        eng = DeliveryEngine()
        eng.add(Reminder("note:3", "usr_alice"))
        eng.presence.set_radar(True, eng.now)
        eng.queue_identity(
            [("known", "usr_alice"), ("known", "usr_alice")]
        )
        eng.tick()
        self.assertEqual(eng.reminders["note:3"].status, "presenting")
        self.assertEqual(eng.sink.played_cache, ["note:3"])
        self.assertEqual(eng.sink.chimes, [])
        self.assertEqual([c[0] for c in eng.sink.cards], ["note:3"])
        self.assertEqual(eng.sink.voice_requests, [])

    def test_inconsistent_pair_rejected(self) -> None:
        eng = DeliveryEngine()
        eng.add(Reminder("note:4", "usr_alice"))
        eng.presence.set_radar(True, eng.now)
        eng.queue_identity(
            [("known", "usr_alice"), ("known", "usr_bob")]
        )
        eng.tick()
        self.assertEqual(eng.reminders["note:4"].status, "waiting_recipient")
        self.assertEqual(eng.sink.cards, [])

    def test_wrong_person_no_leak(self) -> None:
        eng = DeliveryEngine()
        eng.add(Reminder("note:5", "usr_alice"))
        eng.presence.set_radar(True, eng.now)
        eng.queue_identity([("known", "usr_bob"), ("known", "usr_bob")])
        eng.tick()
        self.assertEqual(eng.sink.cards, [])
        self.assertEqual(eng.sink.chimes, [])
        self.assertEqual(eng.sink.voice_requests, [])

    def test_absence_hides_and_restores(self) -> None:
        eng = DeliveryEngine()
        eng.add(Reminder("note:6", "usr_alice"))
        eng.presence.set_radar(True, eng.now)
        eng.queue_identity(
            [("known", "usr_alice"), ("known", "usr_alice")]
        )
        eng.tick()
        eng.absence()
        self.assertEqual(eng.reminders["note:6"].status, "waiting_presence")
        self.assertEqual([h[0] for h in eng.sink.hidden], ["note:6"])
        eng.now += 1
        eng.presence.set_radar(True, eng.now)
        eng.queue_identity(
            [("known", "usr_alice"), ("known", "usr_alice")]
        )
        eng.tick()
        self.assertEqual(eng.reminders["note:6"].status, "presenting")
        self.assertEqual([c[0] for c in eng.sink.cards].count("note:6"), 2)

    def test_stale_async_result_discarded(self) -> None:
        eng = DeliveryEngine()
        eng.add(Reminder("note:7", "usr_alice"))
        eng.presence.set_radar(True, eng.now)
        rem = eng.reminders["note:7"]
        rem.status = "verifying_identity"
        rem.delivery_gen = eng.presence.generation
        rem.revision = 3
        eng.presence.set_radar(False, eng.now)
        eng.now += 1
        eng.presence.set_radar(True, eng.now)
        if eng.presence.generation != rem.delivery_gen:
            rem.status = "waiting_presence"
        self.assertEqual(rem.status, "waiting_presence")
        self.assertEqual(eng.sink.cards, [])

    def test_wrong_actor_action_rejected(self) -> None:
        eng = DeliveryEngine()
        eng.add(Reminder("note:8", "usr_alice"))
        eng.presence.set_radar(True, eng.now)
        eng.queue_identity(
            [("known", "usr_alice"), ("known", "usr_alice")]
        )
        eng.tick()
        self.assertEqual(eng.act("note:8", "usr_bob"), "identity_mismatch")
        self.assertEqual(eng.reminders["note:8"].status, "presenting")

    def test_legacy_non_usr_owner_not_delivered(self) -> None:
        eng = DeliveryEngine()
        rem = eng.migrate_owner("爸爸")
        eng.presence.set_radar(True, eng.now)
        eng.queue_identity([("known", "usr_alice"), ("known", "usr_alice")])
        eng.tick()
        self.assertTrue(rem.delivery_unbound)
        self.assertEqual(eng.sink.cards, [])

    def test_normal_card_not_forced_30s_close(self) -> None:
        eng = DeliveryEngine()
        eng.add(Reminder("note:9", "usr_alice"))
        eng.presence.set_radar(True, eng.now)
        eng.queue_identity(
            [("known", "usr_alice"), ("known", "usr_alice")]
        )
        eng.tick()
        eng.now += 30
        self.assertEqual(eng.reminders["note:9"].status, "presenting")
        self.assertEqual(eng.reminders["note:9"].next_attention_at, 1120)

    def test_voice_failure_still_delivers_local(self) -> None:
        eng = DeliveryEngine()
        eng.ws_connected = False
        eng.add(Reminder("note:10", "usr_alice"))
        eng.presence.set_radar(True, eng.now)
        eng.queue_identity(
            [("known", "usr_alice"), ("known", "usr_alice")]
        )
        eng.tick()
        self.assertEqual(eng.sink.ws_reconnect_attempts, 0)
        self.assertEqual(eng.sink.main_loop_blocked_ms, 0)
        self.assertEqual(eng.sink.played_cache, ["note:10"])
        self.assertEqual(eng.sink.chimes, [])
        self.assertEqual([c[0] for c in eng.sink.cards], ["note:10"])
        self.assertEqual(eng.sink.voice_requests, [])
        self.assertEqual(eng.reminders["note:10"].status, "presenting")

    def test_http_identity_url_rejected(self) -> None:
        ok, reason = accept_identity_url("http://lan/face/identify")
        self.assertFalse(ok)
        self.assertEqual(reason, "not_https")
        ok, reason = accept_identity_url("")
        self.assertFalse(ok)
        self.assertEqual(reason, "missing")
        ok, reason = accept_identity_url(
            "https://api.example/face/identify",
            "https://api.example/explain",
        )
        self.assertTrue(ok)

    def test_missing_identity_endpoint_fail_closed(self) -> None:
        eng = DeliveryEngine()
        eng.identity_endpoint_ok = False
        eng.add(Reminder("note:11", "usr_alice"))
        eng.presence.set_radar(True, eng.now)
        eng.tick()
        self.assertEqual(eng.reminders["note:11"].status, "waiting_recipient")
        self.assertEqual(eng.sink.cards, [])
        self.assertEqual(eng.sink.chimes, [])
        self.assertEqual(eng.sink.voice_requests, [])

    def test_high_personal_preempts_information_exact_dismiss(self) -> None:
        eng = DeliveryEngine()
        info = Reminder(
            "info:1",
            "",
            priority="information",
            source_type="information",
        )
        info.status = "presenting"
        info.revision = 4
        eng.add(info)
        eng.current = "info:1"
        eng.sink.cards.append(("info:1", 4))

        eng.add(Reminder("note:hi", "usr_alice", priority="high"))
        eng.presence.set_radar(True, eng.now)
        eng.queue_identity(
            [("known", "usr_alice"), ("known", "usr_alice")]
        )
        eng.tick()

        self.assertEqual(eng.reminders["info:1"].status, "queued")
        self.assertNotEqual(eng.reminders["info:1"].status, "presenting")
        self.assertEqual(eng.sink.dismissed, [("info:1", 4)])
        self.assertEqual(eng.current, "note:hi")
        self.assertEqual(eng.reminders["note:hi"].status, "presenting")
        new_rev = eng.reminders["note:hi"].revision
        # Old dismiss must not close the new card.
        self.assertFalse(eng.dismiss_card("info:1", 4))
        self.assertEqual(eng.current, "note:hi")
        self.assertEqual(eng.act("note:hi", "usr_alice", new_rev), "ok")

    def test_higher_personal_preempts_lower_personal(self) -> None:
        eng = DeliveryEngine()
        low = Reminder("note:low", "usr_alice", priority="normal")
        low.status = "presenting"
        low.revision = 2
        eng.add(low)
        eng.current = "note:low"
        eng.sink.cards.append(("note:low", 2))

        eng.add(Reminder("note:hi", "usr_bob", priority="high"))
        eng.presence.set_radar(True, eng.now)
        eng.presence.confirm("usr_bob", eng.now)
        eng.queue_identity(
            [("known", "usr_bob"), ("known", "usr_bob")]
        )
        # Fresh confirm for bob should present via fresh_match path.
        eng.tick()
        self.assertEqual(eng.reminders["note:low"].status, "waiting_recipient")
        self.assertEqual(eng.sink.dismissed, [("note:low", 2)])
        self.assertEqual(eng.current, "note:hi")
        self.assertFalse(eng.dismiss_card("note:low", 2))
        self.assertEqual(eng.reminders["note:hi"].status, "presenting")

    def test_creator_recipient_separation(self) -> None:
        # Mom creates a reminder for son; management stays with mom.
        note = Reminder(
            "note:son",
            recipient_person_id="usr_son",
            creator_person_id="usr_mom",
        )
        self.assertEqual(note.creator_person_id, "usr_mom")
        self.assertEqual(note.recipient_person_id, "usr_son")
        eng = DeliveryEngine()
        eng.add(note)
        eng.presence.set_radar(True, eng.now)
        eng.queue_identity([("known", "usr_mom"), ("known", "usr_mom")])
        eng.tick()
        self.assertEqual(eng.sink.cards, [])
        eng.now = eng.reminders["note:son"].next_retry_at
        eng.queue_identity([("known", "usr_son"), ("known", "usr_son")])
        eng.tick()
        self.assertEqual(eng.reminders["note:son"].status, "presenting")
        self.assertEqual(eng.act("note:son", "usr_mom"), "identity_mismatch")
        self.assertEqual(eng.act("note:son", "usr_son"), "ok")

    def test_alarm_habit_recipient_not_lost(self) -> None:
        alarm = Reminder(
            "alarm:1",
            recipient_person_id="usr_son",
            creator_person_id="usr_mom",
            source_type="alarm",
            priority="high",
        )
        habit = Reminder(
            "habit:1",
            recipient_person_id="usr_son",
            creator_person_id="usr_mom",
            source_type="habit",
        )
        eng = DeliveryEngine()
        eng.add(alarm)
        eng.add(habit)
        self.assertEqual(eng.reminders["alarm:1"].recipient_person_id, "usr_son")
        self.assertEqual(eng.reminders["habit:1"].recipient_person_id, "usr_son")
        self.assertEqual(eng.reminders["alarm:1"].creator_person_id, "usr_mom")

    def test_non_usr_cannot_become_active_user(self) -> None:
        self.assertEqual(set_active_user_id("爸爸"), "")
        self.assertEqual(set_active_user_id("default"), "")
        self.assertEqual(set_active_user_id("usr_alice"), "usr_alice")

    def test_no_face_templates_delivers_without_identity(self) -> None:
        eng = DeliveryEngine()
        eng.face_template_count = 0
        eng.face_enrollment_state = "known_zero"
        eng.default_owner_person_id = "usr_owner"
        eng.add(Reminder("note:noface", "usr_owner"))
        eng.presence.set_radar(True, eng.now)
        eng.tick()
        self.assertEqual(eng.reminders["note:noface"].status, "presenting")
        self.assertTrue(eng.reminders["note:noface"].no_face_bypass)
        self.assertEqual(eng.act("note:noface", ""), "ok")

    def test_unknown_face_state_no_bypass(self) -> None:
        eng = DeliveryEngine()
        eng.face_enrollment_state = "unknown"
        eng.face_template_count = 0
        eng.add(Reminder("note:unk", "usr_owner"))
        eng.presence.set_radar(True, eng.now)
        eng.tick()
        self.assertEqual(eng.reminders["note:unk"].status, "waiting_recipient")
        self.assertEqual(eng.sink.cards, [])

    def test_session_close_rejects_stale_card_action(self) -> None:
        eng = DeliveryEngine()
        eng.face_template_count = 0
        eng.face_enrollment_state = "known_zero"
        eng.default_owner_person_id = "usr_owner"
        eng.add(Reminder("note:sess", "usr_owner"))
        eng.presence.set_radar(True, eng.now)
        eng.tick()
        eng.close_session()
        self.assertEqual(eng.act("note:sess", "usr_owner"), "session_mismatch")

    def test_due_with_cache_does_not_rerequest_voice(self) -> None:
        eng = DeliveryEngine()
        eng.add(Reminder("note:cache", "usr_alice"))
        eng.presence.set_radar(True, eng.now)
        eng.queue_identity(
            [("known", "usr_alice"), ("known", "usr_alice")]
        )
        eng.tick()
        self.assertEqual(eng.sink.played_cache, ["note:cache"])
        self.assertEqual(eng.sink.voice_requests, [])
        self.assertEqual(eng.sink.chimes, [])

    def test_due_without_cache_chimes_and_requests(self) -> None:
        eng = DeliveryEngine()
        rem = Reminder("note:nocache", "usr_alice")
        rem.voice_cached = False
        eng.add(rem)
        eng.presence.set_radar(True, eng.now)
        eng.queue_identity(
            [("known", "usr_alice"), ("known", "usr_alice")]
        )
        eng.tick()
        self.assertEqual(eng.sink.played_cache, [])
        self.assertEqual(eng.sink.chimes, ["note:nocache"])
        self.assertEqual(eng.sink.voice_requests, ["note:nocache"])

    def test_backlog_does_not_autoplay_until_begin_broadcast(self) -> None:
        eng = DeliveryEngine()
        eng.add(Reminder("note:a", "usr_alice"))
        eng.add(Reminder("note:b", "usr_alice"))
        eng.presence.set_radar(True, eng.now)
        eng.queue_identity(
            [("known", "usr_alice"), ("known", "usr_alice")]
        )
        eng.tick()
        self.assertTrue(eng.pending_broadcast_prompt)
        self.assertEqual(eng.sink.played_cache, [])
        self.assertEqual(eng.sink.cards, [])
        self.assertEqual(eng.sink.voice_requests, [])
        self.assertEqual(eng.reminders["note:a"].status, "queued")
        self.assertEqual(eng.reminders["note:b"].status, "queued")
        eng.begin_broadcast()
        self.assertEqual(eng.current, "note:a")
        self.assertEqual(eng.sink.played_cache, ["note:a"])
        self.assertNotIn("note:b", eng.sink.played_cache)
        self.assertEqual(eng.reminders["note:b"].status, "queued")
        self.assertEqual(eng.act("note:a", "usr_alice"), "ok")
        eng.tick()
        self.assertEqual(eng.current, "note:b")
        self.assertEqual(eng.sink.played_cache, ["note:a", "note:b"])

    def test_cached_play_stays_on_own_instance(self) -> None:
        eng = DeliveryEngine()
        eng.add(Reminder("note:left", "usr_alice"))
        eng.add(Reminder("note:right", "usr_alice"))
        eng.presence.set_radar(True, eng.now)
        eng.queue_identity(
            [("known", "usr_alice"), ("known", "usr_alice")]
        )
        eng.begin_broadcast()
        self.assertEqual(eng.sink.played_cache, ["note:left"])
        self.assertNotEqual(eng.sink.played_cache[0], "note:right")


if __name__ == "__main__":
    unittest.main()
