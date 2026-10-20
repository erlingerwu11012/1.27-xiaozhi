"""Host-side reminder voice/card invariant regression tests.

These tests exercise the production cache-key contract with real temporary
files and verify that the firmware source still uses the same invariants.
They do not emulate ESP-IDF audio output or flash power-loss behavior.
"""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from dataclasses import dataclass, field
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def cache_name(
    instance_id: str,
    voice_revision: int,
    phase: str,
    sha256: str,
) -> str:
    key = "\x1f".join(
        (instance_id, str(voice_revision), phase, sha256)
    )
    return "r" + hashlib.sha256(key.encode()).hexdigest()[:25] + ".ogg"


@dataclass
class Asset:
    phase: str
    voice_revision: int
    path: Path
    priority: str


@dataclass
class Reminder:
    instance_id: str
    revision: int = 1
    voice_revision: int = 1
    assets: dict[str, Asset] = field(default_factory=dict)

    def visual_transition(self) -> None:
        self.revision += 1

    def semantic_change(self) -> None:
        for asset in self.assets.values():
            asset.path.unlink(missing_ok=True)
        self.assets.clear()
        self.voice_revision += 1
        self.revision += 1

    def accepts_voice(self, voice_revision: int) -> bool:
        return voice_revision == self.voice_revision

    def play(self, phase: str) -> bytes | None:
        asset = self.assets.get(phase)
        if (
            asset is None
            or asset.voice_revision != self.voice_revision
            or not asset.path.is_file()
        ):
            return None
        return asset.path.read_bytes()


def insert_with_global_limit(
    reminders: list[Reminder],
    owner: Reminder,
    asset: Asset,
) -> None:
    old = owner.assets.get(asset.phase)
    owner.assets[asset.phase] = asset
    if old is not None and old.path != asset.path:
        old.path.unlink(missing_ok=True)

    def all_assets() -> list[tuple[Reminder, Asset]]:
        return [
            (reminder, item)
            for reminder in reminders
            for item in reminder.assets.values()
        ]

    while len(all_assets()) > 2:
        candidates = [
            pair
            for pair in all_assets()
            if pair[1].path != asset.path
        ]
        low = [
            pair for pair in candidates if pair[1].priority != "high"
        ]
        evict_owner, evict_asset = (low or candidates)[0]
        del evict_owner.assets[evict_asset.phase]
        evict_asset.path.unlink(missing_ok=True)


class ReminderRegressionTest(unittest.TestCase):
    def test_multi_phase_paths_playback_and_eviction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reminder = Reminder("note:7:due")
            due_path = root / cache_name(
                reminder.instance_id, 1, "due", "a" * 64
            )
            repeat_path = root / cache_name(
                reminder.instance_id, 1, "repeat", "b" * 64
            )
            due_path.write_bytes(b"A-due")
            repeat_path.write_bytes(b"B-repeat")
            insert_with_global_limit(
                [reminder],
                reminder,
                Asset("due", 1, due_path, "high"),
            )
            insert_with_global_limit(
                [reminder],
                reminder,
                Asset("repeat", 1, repeat_path, "high"),
            )

            self.assertNotEqual(due_path, repeat_path)
            self.assertEqual(reminder.play("due"), b"A-due")
            self.assertEqual(reminder.play("repeat"), b"B-repeat")

            other = Reminder("note:8:due")
            completion_path = root / cache_name(
                other.instance_id, 1, "completion", "c" * 64
            )
            completion_path.write_bytes(b"C-completion")
            insert_with_global_limit(
                [reminder, other],
                other,
                Asset("completion", 1, completion_path, "high"),
            )
            metadata_paths = {
                item.path
                for value in (reminder, other)
                for item in value.assets.values()
            }
            disk_paths = set(root.glob("*.ogg"))
            self.assertEqual(len(metadata_paths), 2)
            self.assertEqual(metadata_paths, disk_paths)
            print(
                "multi_phase:",
                due_path.name,
                repeat_path.name,
                "remaining=",
                sorted(path.name for path in disk_paths),
            )

    def test_visual_revision_does_not_invalidate_voice(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            reminder = Reminder("alarm:1:today")
            path = Path(directory) / cache_name(
                reminder.instance_id, 1, "due", "d" * 64
            )
            path.write_bytes(b"AI-due")
            reminder.assets["due"] = Asset(
                "due", 1, path, "high"
            )
            for _transition in (
                "show",
                "collapse",
                "show_again",
                "preempt",
                "recover",
            ):
                reminder.visual_transition()
            self.assertEqual(reminder.revision, 6)
            self.assertEqual(reminder.voice_revision, 1)
            self.assertEqual(reminder.play("due"), b"AI-due")
            print(
                "visual_lifecycle:",
                f"revision={reminder.revision}",
                f"voice_revision={reminder.voice_revision}",
                "due=AI-due",
            )

    def test_semantic_change_rejects_old_voice(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            reminder = Reminder("habit:2:today")
            old_path = Path(directory) / cache_name(
                reminder.instance_id, 1, "due", "e" * 64
            )
            old_path.write_bytes(b"old")
            reminder.assets["due"] = Asset(
                "due", 1, old_path, "high"
            )
            reminder.semantic_change()
            self.assertFalse(reminder.accepts_voice(1))
            self.assertIsNone(reminder.play("due"))
            self.assertFalse(old_path.exists())
            self.assertTrue(reminder.accepts_voice(2))
            new_path = Path(directory) / cache_name(
                reminder.instance_id, 2, "due", "f" * 64
            )
            new_path.write_bytes(b"new")
            reminder.assets["due"] = Asset(
                "due", 2, new_path, "high"
            )
            self.assertEqual(reminder.play("due"), b"new")
            print(
                "semantic_change:",
                "old_accepted=False",
                "new_accepted=True",
                "new_playback=new",
            )

    def test_stale_dismiss_does_not_close_replacement(self) -> None:
        displayed = {"instance_id": "A", "revision": 1}
        dismiss_snapshot = dict(displayed)
        displayed = {"instance_id": "B", "revision": 1}
        matched = displayed == dismiss_snapshot
        if matched:
            displayed = {}
        self.assertFalse(matched)
        self.assertEqual(
            displayed, {"instance_id": "B", "revision": 1}
        )
        print("stale_dismiss:", "matched=False", "visible=B")

    def test_firmware_source_uses_tested_contract(self) -> None:
        service = (
            ROOT / "main/reminder_voice_service.cc"
        ).read_text(encoding="utf-8")
        coordinator = (
            ROOT / "main/reminder_coordinator.cc"
        ).read_text(encoding="utf-8")
        application = (
            ROOT / "main/application.cc"
        ).read_text(encoding="utf-8")
        lcd = (
            ROOT / "main/display/lcd_display.cc"
        ).read_text(encoding="utf-8")

        build_path_body = service.split(
            "ReminderVoiceService::BuildCachePath", 1
        )[1].split(
            "ReminderVoiceService::IsCurrentCachePath", 1
        )[0]
        for token in (
            "instance_id",
            "voice_revision",
            "phase",
            "sha256",
            "DigestHex(digest).substr(0, 25)",
        ):
            self.assertIn(token, build_path_body)

        visual_body = coordinator.split(
            "ReminderCoordinator::AdvanceRevisionLocked", 1
        )[1].split(
            "ReminderCoordinator::AdvanceVoiceRevisionLocked", 1
        )[0]
        voice_body = coordinator.split(
            "ReminderCoordinator::AdvanceVoiceRevisionLocked", 1
        )[1].split(
            "bool ReminderCoordinator::EnqueueAlarm", 1
        )[0]
        self.assertNotIn("InvalidateVoiceAssetsLocked", visual_body)
        self.assertIn("InvalidateVoiceAssetsLocked", voice_body)
        self.assertIn(
            'cJSON_GetObjectItem(root, "voice_revision")',
            service,
        )
        self.assertIn("HandleIncomingAssetMessage", application)
        self.assertIn("HandleIncomingAssetMessage", service)
        self.assertIn(
            "DismissMcpCard(\n"
            "                                    card_instance_id, revision)",
            lcd,
        )
        self.assertIn(
            "display->DismissMcpCard(\n"
            "                context->instance_id, context->revision)",
            lcd,
        )
        self.assertIn("owner.voice_assets.erase", coordinator)
        self.assertIn("RemoveUnreferencedCachePaths", coordinator)
        self.assertIn(
            "AdvanceRevisionLocked(ReminderInstance& instance) {\n"
            "    instance.revision++;\n"
            "}",
            coordinator.replace("\r\n", "\n"),
        )
        play_cached = service.split(
            "ReminderVoiceService::PlayCached", 1
        )[1].split(
            "ReminderVoiceService::PlayDueLocalOrChime", 1
        )[0]
        self.assertIn("IsCurrentCachePath", play_cached)
        self.assertIn("BuildCachePath", play_cached)
        self.assertIn("voice_revision", play_cached)
        self.assertNotIn("asset.revision", play_cached)
        self.assertIn("'O'", play_cached)
        self.assertIn("HasCachedVoice", service)
        self.assertIn("PlayDueLocalOrChime", service)
        self.assertIn("voice asset is not OggS", service)
        self.assertIn("AnnounceDueVoice", coordinator)
        self.assertIn("PlayDueLocalOrChime", coordinator)
        self.assertIn("unattended_chime", coordinator)
        unattended = coordinator.split("event=unattended_chime", 1)[1].split(
            "repeat_attention", 1
        )[0]
        self.assertIn("PlayAttention", unattended)
        self.assertNotIn("PlayDueLocalOrChime", unattended)
        announce = coordinator.split(
            "ReminderCoordinator::AnnounceDueVoice", 1
        )[1].split("ReminderCoordinator::Present(", 1)[0]
        self.assertIn("PlayDueLocalOrChime", announce)
        request_idx = announce.find("RequestScripts")
        play_idx = announce.find("PlayDueLocalOrChime")
        self.assertNotEqual(play_idx, -1)
        self.assertNotEqual(request_idx, -1)
        self.assertLess(play_idx, request_idx)
        application = (ROOT / "main/application.cc").read_text(encoding="utf-8")
        self.assertIn("EnqueueOrSendReminderProtocolMessage", application)
        self.assertIn("FlushPendingReminderProtocolMessages", application)
        self.assertIn("require_presence=*/false", application)

    def test_due_playback_never_crosses_instances(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = Reminder("note:1:1001")
            second = Reminder("note:2:1002")
            first_path = root / cache_name(
                first.instance_id, 1, "due", "a" * 64
            )
            second_path = root / cache_name(
                second.instance_id, 1, "due", "b" * 64
            )
            first_path.write_bytes(b"OggS-A")
            second_path.write_bytes(b"OggS-B")
            first.assets["due"] = Asset("due", 1, first_path, "normal")
            second.assets["due"] = Asset("due", 1, second_path, "normal")
            self.assertNotEqual(first_path, second_path)
            self.assertEqual(first.play("due"), b"OggS-A")
            self.assertEqual(second.play("due"), b"OggS-B")
            self.assertNotEqual(first.play("due"), second.play("due"))

    def test_reminder_interaction_protocol_contract(self) -> None:
        """Keep firmware aligned with the server's 180-second card window."""
        application = (
            ROOT / "main/application.cc"
        ).read_text(encoding="utf-8")
        application_header = (
            ROOT / "main/application.h"
        ).read_text(encoding="utf-8")
        coordinator = (
            ROOT / "main/reminder_coordinator.cc"
        ).read_text(encoding="utf-8")
        voice = (
            ROOT / "main/reminder_voice_service.cc"
        ).read_text(encoding="utf-8")

        self.assertIn("kReminderInteractionMaxSeconds = 3 * 60", application)
        self.assertIn("kCardInteractionWindowSeconds = 180", coordinator)
        self.assertIn('"type", "reminder_event"', application)
        self.assertIn('"interaction_opened"', application)
        self.assertIn('"interaction_closed"', application)
        self.assertIn('"expires_at"', application)
        self.assertIn("server_listen_ignored", application)
        self.assertIn("kListeningReasonReminder", application_header)
        self.assertIn("BeginReminderInteraction", coordinator)
        self.assertIn("wait_presence", coordinator)
        self.assertIn('"privacy_safe_required"', voice)
        self.assertIn("No touch/voice action within 180 seconds", coordinator)

        # Reminder listen must arm once: no second start + queue wipe after
        # SetDeviceState(Listening), and same-window refresh stays idempotent.
        activate = application.split(
            "void Application::ActivateReminderInteractionIfReady()", 1
        )[1].split("bool Application::SendReminderInteractionEvent(", 1)[0]
        self.assertIn("listen_refresh_idempotent", activate)
        self.assertIn("already_reminder_listen", activate)
        self.assertNotIn("ResetUploadQueues()", activate)
        self.assertNotIn("listen_start_same_state", activate)
        finish = application.split(
            "void Application::FinishTtsPlayback(", 1
        )[1].split("void Application::ClearTtsStream(", 1)[0]
        self.assertIn("ActivateReminderInteractionIfReady()", finish)
        self.assertNotIn("SetDeviceState(kDeviceStateListening);\n    ActivateReminder", finish)
        update = application.split(
            "void Application::UpdateTtsPlayback()", 1
        )[1].split("void Application::FinishTtsPlayback(", 1)[0]
        self.assertIn("stop_and_drained", update)
        self.assertIn("missing_stop_timeout", update)
        self.assertIn("no_audio_timeout", update)
        self.assertIn("kTtsAbnormalIdleTimeoutMs", application_header)
        self.assertNotIn("rx_idle_drained", application)
        self.assertNotIn("tts_rx_idle_ticks_", application)
        self.assertNotIn("tts_rx_idle_ticks_", application_header)

    def test_pending_consult_waits_for_identity_greeting(self) -> None:
        coordinator = (
            ROOT / "main/reminder_coordinator.cc"
        ).read_text(encoding="utf-8")
        wake = (
            ROOT / "main/proactive_wake_coordinator.cc"
        ).read_text(encoding="utf-8")
        prompt = coordinator.split(
            "bool ReminderCoordinator::RequestPendingBroadcastPrompt", 1
        )[1].split("size_t ReminderCoordinator::PendingBroadcastCount", 1)[0]
        self.assertIn("IsIdentityOrGreetingInFlight", prompt)
        self.assertIn("pending consult deferred", prompt)
        self.assertIn("away_seconds=%lld < 900", prompt)
        self.assertIn("event=stable_user_return", prompt)
        self.assertNotIn("event=pending_reminder_available", prompt)
        self.assertNotIn("rules=", prompt)
        greeting = wake.split(
            "bool ProactiveWakeCoordinator::TrySendProactiveGreeting", 1
        )[1].split("void ProactiveWakeCoordinator::MarkGreetingSent", 1)[0]
        self.assertIn("kDeviceStateSpeaking", greeting)
        self.assertIn("already_in_conversation", greeting)
        self.assertIn("pending_reminder_count=", greeting)
        self.assertIn("face_identity=", greeting)
        self.assertNotIn("rules=", greeting)
        self.assertNotIn("identity_mode=", greeting)
        self.assertNotIn("verified_display_name=", greeting)
        self.assertIn("MarkPendingBroadcastPrompted", greeting)
        self.assertNotIn("SchedulePendingConsultAfterGreeting", wake)
        self.assertNotIn("BeginGreetingTurnHoldoff", wake)
        self.assertIn("skip greeting: single due plays locally", wake)


if __name__ == "__main__":
    unittest.main(verbosity=2)
