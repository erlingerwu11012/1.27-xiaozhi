"""Host-side regression for Reminder Control Client routing and gates.

Does not require camera, network, FreeRTOS, or a real WSS server.
Also scans firmware sources for P0 contracts (Device-Id, host match,
capability clear, TLS bundle, cancel-code atomics).
"""

from __future__ import annotations

import re
import unittest
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def starts_with_wss(url: str) -> bool:
    return url.startswith("wss://")


def extract_host(url: str) -> str:
    for prefix in ("wss://", "ws://", "https://", "http://"):
        if url.startswith(prefix):
            rest = url[len(prefix) :]
            break
    else:
        return ""
    host = rest.split("/", 1)[0].split("?", 1)[0]
    if "@" in host:
        host = host.split("@", 1)[1]
    if host.startswith("["):
        return host
    return host.split(":", 1)[0]


def normalize_host(host: str) -> str:
    return host.lower()


def is_forbidden_host(host: str) -> bool:
    h = host.lower()
    if h in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}:
        return True
    parts = h.split(".")
    if len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
        a, b = int(parts[0]), int(parts[1])
        if a == 10 or a == 127 or a == 0:
            return True
        if a == 192 and b == 168:
            return True
        if a == 172 and 16 <= b <= 31:
            return True
        if a == 169 and b == 254:
            return True
    return False


def accept_control_config(
    url: str,
    main_ws_url: str = "wss://public.example.com/xiaozhi/v1/",
    protocol_version: int = 1,
    connect_timeout_ms: int = 3000,
    asset_wait_timeout_ms: int = 8000,
) -> tuple[bool, str]:
    if not url:
        return False, "missing_url"
    if url.startswith("ws://"):
        return False, "not_wss"
    if not starts_with_wss(url):
        return False, "bad_scheme"
    host = normalize_host(extract_host(url))
    if not host:
        return False, "bad_host"
    if is_forbidden_host(host):
        return False, "forbidden_host"
    if not main_ws_url:
        return False, "main_ws_missing"
    if not starts_with_wss(main_ws_url):
        return False, "main_ws_not_wss"
    main_host = normalize_host(extract_host(main_ws_url))
    if not main_host:
        return False, "main_ws_bad_host"
    if main_host != host:
        return False, "host_mismatch"
    if protocol_version != 1:
        return False, "unsupported_version"
    if not (500 <= connect_timeout_ms <= 10000):
        return False, "bad_connect_timeout"
    if not (1000 <= asset_wait_timeout_ms <= 30000):
        return False, "bad_asset_timeout"
    return True, "ok"


@dataclass
class PersistedStore:
    values: dict[str, object] = field(default_factory=dict)

    def set_config(self, url: str, version: int = 1, connect_ms: int = 3000,
                   asset_ms: int = 8000) -> None:
        self.values = {
            "url": url,
            "protocol_version": version,
            "connect_timeout_ms": connect_ms,
            "asset_wait_timeout_ms": asset_ms,
        }

    def clear(self) -> None:
        self.values.clear()

    def has_url(self) -> bool:
        return bool(self.values.get("url"))


@dataclass
class ControlConfigState:
    store: PersistedStore = field(default_factory=PersistedStore)
    url: str = ""
    valid: bool = False
    connects: list[str] = field(default_factory=list)
    events: list[str] = field(default_factory=list)

    def apply_capability(self, capability: object | None,
                         main_ws_url: str) -> str:
        if not isinstance(capability, dict):
            self.clear("capability_missing")
            return "cleared"
        url = capability.get("url") or ""
        version = int(capability.get("protocol_version", 1))
        connect_ms = int(capability.get("connect_timeout_ms", 3000))
        asset_ms = int(capability.get("asset_wait_timeout_ms", 8000))
        ok, reason = accept_control_config(
            str(url), main_ws_url, version, connect_ms, asset_ms
        )
        if not ok:
            self.clear(reason)
            self.events.append(f"rejected:{reason}")
            return "rejected"
        self.url = str(url)
        self.valid = True
        self.store.set_config(self.url, version, connect_ms, asset_ms)
        self.events.append("accepted")
        return "accepted"

    def clear(self, reason: str) -> None:
        self.url = ""
        self.valid = False
        self.store.clear()
        self.events.append(f"cleared:{reason}")

    def try_connect(self, instance_id: str) -> bool:
        if not self.valid or not self.url:
            return False
        self.connects.append(instance_id)
        return True


@dataclass
class VoiceRequest:
    instance_id: str
    revision: int
    voice_revision: int
    presence_generation: int
    recipient: str
    priority: str = "normal"  # high/normal

    def rank(self) -> int:
        return 0 if self.priority == "high" else 2


@dataclass
class Engine:
    main_ws_open: bool = False
    control_url_ok: bool = True
    device_state: str = "idle"
    radar: bool = True
    generation: int = 1
    confirmed: str = "usr_alice"
    presenting_id: str = "note:1"
    presenting_revision: int = 2
    presenting_voice_revision: int = 1
    presenting_status: str = "presenting"
    chimes: list[str] = field(default_factory=list)
    cards: list[str] = field(default_factory=list)
    main_ws_sends: list[str] = field(default_factory=list)
    control_connects: list[str] = field(default_factory=list)
    control_cancelled: list[str] = field(default_factory=list)
    open_audio_channel_calls: int = 0
    active: VoiceRequest | None = None
    pending: VoiceRequest | None = None
    discarded_assets: list[str] = field(default_factory=list)
    ai_plays: list[str] = field(default_factory=list)
    play_discards: list[str] = field(default_factory=list)
    played_keys: set[tuple] = field(default_factory=set)

    def send_voice_request(self, req: VoiceRequest) -> str:
        if self.main_ws_open:
            self.control_cancelled.append("main_ws_available")
            self.main_ws_sends.append(req.instance_id)
            return "main_ws"
        if not self.control_url_ok:
            return "skip_no_capability"
        if not self._gate(req):
            return "gate_reject"
        if self.active and self._same(self.active, req):
            return "dedup"
        if self.pending and self._same(self.pending, req):
            return "dedup"
        if self.active is None:
            self.active = req
            self.control_connects.append(req.instance_id)
            return "control_start"
        if self.pending is None or req.rank() < self.pending.rank():
            self.pending = req
        if self.pending and self.pending.rank() < self.active.rank():
            self.control_cancelled.append("preempted")
            self.active = self.pending
            self.pending = None
            self.control_connects.append(self.active.instance_id)
            return "control_preempt"
        return "control_pending"

    def _same(self, a: VoiceRequest, b: VoiceRequest) -> bool:
        return (
            a.instance_id == b.instance_id
            and a.revision == b.revision
            and a.voice_revision == b.voice_revision
            and a.presence_generation == b.presence_generation
        )

    def _gate(self, req: VoiceRequest) -> bool:
        if self.device_state != "idle":
            return False
        if self.main_ws_open:
            return False
        if self.presenting_status != "presenting":
            return False
        if self.presenting_id != req.instance_id:
            return False
        if self.presenting_revision != req.revision:
            return False
        if self.presenting_voice_revision != req.voice_revision:
            return False
        if not self.radar or self.generation != req.presence_generation:
            return False
        if self.confirmed != req.recipient:
            return False
        return True

    def on_asset(self, req: VoiceRequest, phase: str = "due",
                 path: str = "control") -> str:
        """Shared accept+immediate-play path for control and main WS."""
        del path  # both paths share try_play_accepted_asset_now
        if not self._gate(req):
            self.discarded_assets.append("gate")
            self.play_discards.append("gate")
            return "discard"
        key = (
            req.instance_id,
            req.revision,
            req.voice_revision,
            phase,
            req.presence_generation,
        )
        if key in self.played_keys:
            self.play_discards.append("already_played")
            return "already_played"
        self.played_keys.add(key)
        self.ai_plays.append(f"{req.instance_id}:{phase}:downloaded")
        return "play"

    def local_deliver(self, instance_id: str) -> None:
        self.chimes.append(instance_id)
        self.cards.append(instance_id)

    def deliver_then_asset(self, req: VoiceRequest,
                           path: str = "control") -> str:
        self.local_deliver(req.instance_id)
        return self.on_asset(req, path=path)


class ReminderControlClientRegressionTest(unittest.TestCase):
    def test_missing_capability_skips_ai(self) -> None:
        eng = Engine(control_url_ok=False)
        req = VoiceRequest("note:1", 2, 1, 1, "usr_alice")
        eng.local_deliver("note:1")
        self.assertEqual(eng.send_voice_request(req), "skip_no_capability")
        self.assertEqual(eng.control_connects, [])
        self.assertEqual(eng.chimes, ["note:1"])
        self.assertEqual(eng.cards, ["note:1"])

    def test_ws_and_localhost_rejected(self) -> None:
        main = "wss://public.example.com/xiaozhi/v1/"
        for url, reason in (
            ("ws://public.example.com/reminder-control", "not_wss"),
            ("wss://localhost/reminder-control", "forbidden_host"),
            ("wss://127.0.0.1/reminder-control", "forbidden_host"),
            ("wss://192.168.1.8/reminder-control", "forbidden_host"),
            ("wss://10.0.0.2/reminder-control", "forbidden_host"),
            ("", "missing_url"),
        ):
            ok, got = accept_control_config(url, main)
            self.assertFalse(ok, url)
            self.assertEqual(got, reason, url)
        ok, _ = accept_control_config(
            "wss://public.example.com/reminder-control", main
        )
        self.assertTrue(ok)

    def test_host_mismatch_rejected(self) -> None:
        main = "wss://api.paired.example/ws"
        ok, reason = accept_control_config(
            "wss://other.example.com/reminder-control", main
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "host_mismatch")
        ok, reason = accept_control_config(
            "wss://API.PAIRED.EXAMPLE/reminder-control", main
        )
        self.assertTrue(ok)
        self.assertEqual(reason, "ok")
        ok, reason = accept_control_config(
            "wss://api.paired.example/reminder-control",
            "ws://api.paired.example/ws",
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "main_ws_not_wss")
        ok, reason = accept_control_config(
            "wss://api.paired.example/reminder-control", ""
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "main_ws_missing")

    def test_capability_missing_clears_persisted_url(self) -> None:
        state = ControlConfigState()
        main = "wss://public.example.com/xiaozhi/v1/"
        self.assertEqual(
            state.apply_capability(
                {"url": "wss://public.example.com/reminder-control"},
                main,
            ),
            "accepted",
        )
        self.assertTrue(state.store.has_url())
        self.assertTrue(state.try_connect("note:1"))
        self.assertEqual(state.apply_capability(None, main), "cleared")
        self.assertFalse(state.store.has_url())
        self.assertFalse(state.valid)
        self.assertFalse(state.try_connect("note:2"))
        self.assertEqual(state.connects, ["note:1"])
        self.assertIn("cleared:capability_missing", state.events)

    def test_main_ws_online_uses_main_only(self) -> None:
        eng = Engine(main_ws_open=True)
        req = VoiceRequest("note:1", 2, 1, 1, "usr_alice")
        self.assertEqual(eng.send_voice_request(req), "main_ws")
        self.assertEqual(eng.main_ws_sends, ["note:1"])
        self.assertEqual(eng.control_connects, [])
        self.assertEqual(eng.open_audio_channel_calls, 0)

    def test_main_ws_offline_starts_control(self) -> None:
        eng = Engine(main_ws_open=False)
        req = VoiceRequest("note:1", 2, 1, 1, "usr_alice")
        self.assertEqual(eng.send_voice_request(req), "control_start")
        self.assertEqual(eng.control_connects, ["note:1"])
        self.assertEqual(eng.open_audio_channel_calls, 0)

    def test_same_request_dedup(self) -> None:
        eng = Engine()
        req = VoiceRequest("note:1", 2, 1, 1, "usr_alice")
        self.assertEqual(eng.send_voice_request(req), "control_start")
        self.assertEqual(eng.send_voice_request(req), "dedup")
        self.assertEqual(eng.control_connects, ["note:1"])

    def test_high_priority_preempts_low(self) -> None:
        eng = Engine(presenting_id="note:hi", presenting_revision=3)
        low = VoiceRequest("note:low", 2, 1, 1, "usr_alice", priority="normal")
        # Force active low even if presenting id differs for queue logic.
        eng.active = low
        eng.control_connects.append("note:low")
        hi = VoiceRequest("note:hi", 3, 1, 1, "usr_alice", priority="high")
        self.assertEqual(eng.send_voice_request(hi), "control_preempt")
        self.assertIn("preempted", eng.control_cancelled)
        self.assertEqual(eng.active.instance_id, "note:hi")

    def test_listening_blocks_connect_and_play(self) -> None:
        eng = Engine(device_state="listening")
        req = VoiceRequest("note:1", 2, 1, 1, "usr_alice")
        self.assertEqual(eng.send_voice_request(req), "gate_reject")
        eng.device_state = "idle"
        eng.active = req
        eng.device_state = "speaking"
        self.assertEqual(eng.on_asset(req), "discard")

    def test_absence_identity_revision_preempt_discard_asset(self) -> None:
        base = VoiceRequest("note:1", 2, 1, 1, "usr_alice")
        eng = Engine()
        eng.radar = False
        self.assertEqual(eng.on_asset(base), "discard")
        eng = Engine(confirmed="usr_bob")
        self.assertEqual(eng.on_asset(base), "discard")
        eng = Engine(presenting_revision=9)
        self.assertEqual(eng.on_asset(base), "discard")
        eng = Engine(presenting_id="note:other")
        self.assertEqual(eng.on_asset(base), "discard")

    def test_control_failure_keeps_local_chime_card(self) -> None:
        eng = Engine(control_url_ok=False)
        eng.local_deliver("note:10")
        eng.send_voice_request(
            VoiceRequest("note:10", 2, 1, 1, "usr_alice")
        )
        self.assertEqual(eng.chimes, ["note:10"])
        self.assertEqual(eng.cards, ["note:10"])
        self.assertEqual(eng.control_connects, [])
        self.assertEqual(eng.open_audio_channel_calls, 0)

    def test_never_calls_open_audio_channel(self) -> None:
        eng = Engine(main_ws_open=False)
        eng.send_voice_request(
            VoiceRequest("note:1", 2, 1, 1, "usr_alice")
        )
        eng.main_ws_open = True
        eng.send_voice_request(
            VoiceRequest("note:2", 2, 1, 1, "usr_alice")
        )
        self.assertEqual(eng.open_audio_channel_calls, 0)

    def test_asset_accepted_plays_immediately_once(self) -> None:
        eng = Engine()
        req = VoiceRequest("note:1", 2, 1, 1, "usr_alice")
        self.assertEqual(eng.deliver_then_asset(req), "play")
        self.assertEqual(eng.chimes, ["note:1"])
        self.assertEqual(eng.cards, ["note:1"])
        self.assertEqual(eng.ai_plays, ["note:1:due:downloaded"])
        # Local chime precedes AI play in the deliver_then_asset sequence.
        self.assertEqual(eng.chimes[0], "note:1")
        self.assertEqual(eng.on_asset(req), "already_played")
        self.assertEqual(eng.ai_plays, ["note:1:due:downloaded"])
        self.assertIn("already_played", eng.play_discards)

    def test_asset_retransmit_does_not_double_play(self) -> None:
        eng = Engine()
        req = VoiceRequest("note:1", 2, 1, 1, "usr_alice")
        eng.local_deliver("note:1")
        self.assertEqual(eng.on_asset(req, path="control"), "play")
        self.assertEqual(eng.on_asset(req, path="main"), "already_played")
        self.assertEqual(eng.on_asset(req, path="control"), "already_played")
        self.assertEqual(len(eng.ai_plays), 1)

    def test_gate_failures_discard_without_ai_play(self) -> None:
        req = VoiceRequest("note:1", 2, 1, 1, "usr_alice")
        cases = [
            Engine(radar=False),
            Engine(confirmed="usr_bob"),
            Engine(presenting_revision=9),
            Engine(presenting_id="note:other"),
            Engine(presenting_status="snoozed"),
            Engine(device_state="listening"),
            Engine(device_state="speaking"),
        ]
        for eng in cases:
            eng.local_deliver("note:1")
            self.assertEqual(eng.on_asset(req), "discard")
            self.assertEqual(eng.ai_plays, [])
            self.assertEqual(eng.chimes, ["note:1"])
            self.assertEqual(eng.cards, ["note:1"])

    def test_main_and_control_share_play_entry(self) -> None:
        eng = Engine()
        req = VoiceRequest("note:1", 2, 1, 1, "usr_alice")
        eng.local_deliver("note:1")
        self.assertEqual(eng.on_asset(req, path="main"), "play")
        # Peer channel redelivery hits the same immediate-play claim.
        self.assertEqual(eng.on_asset(req, path="control"), "already_played")
        self.assertEqual(eng.ai_plays, ["note:1:due:downloaded"])

    def test_ai_failure_keeps_local_chime_and_card(self) -> None:
        eng = Engine()
        eng.local_deliver("note:1")
        eng.device_state = "listening"
        self.assertEqual(
            eng.on_asset(VoiceRequest("note:1", 2, 1, 1, "usr_alice")),
            "discard",
        )
        self.assertEqual(eng.chimes, ["note:1"])
        self.assertEqual(eng.cards, ["note:1"])
        self.assertEqual(eng.ai_plays, [])

    def test_new_presence_generation_can_play_again(self) -> None:
        eng = Engine(generation=1)
        req1 = VoiceRequest("note:1", 2, 1, 1, "usr_alice")
        eng.local_deliver("note:1")
        self.assertEqual(eng.on_asset(req1), "play")
        eng.generation = 2
        eng.presenting_revision = 3
        req2 = VoiceRequest("note:1", 3, 1, 2, "usr_alice")
        self.assertEqual(eng.on_asset(req2), "play")
        self.assertEqual(len(eng.ai_plays), 2)


class ReminderControlSourceContractTest(unittest.TestCase):
    def _read(self, rel: str) -> str:
        return (ROOT / rel).read_text(encoding="utf-8")

    def test_voice_download_sets_device_id(self) -> None:
        src = self._read("main/reminder_voice_service.cc")
        self.assertIn('SetHeader("Device-Id"', src)
        self.assertIn("SystemInfo::GetMacAddress()", src)
        # Must set Device-Id before Open GET.
        device_pos = src.find('SetHeader("Device-Id"')
        open_pos = src.find('Open("GET"')
        self.assertGreater(device_pos, 0)
        self.assertGreater(open_pos, device_pos)

    def test_control_host_must_match_main_websocket(self) -> None:
        src = self._read("main/reminder_control_client.cc")
        self.assertIn('Settings main_settings("websocket", false)', src)
        self.assertIn('reason = "host_mismatch"', src)
        self.assertIn("NormalizeHost", src)
        self.assertNotRegex(
            src, r'url_\s*=\s*main_url|control.*\+\s*main|"wss://"\s*\+'
        )

    def test_capability_missing_clears_config(self) -> None:
        mcp = self._read("main/mcp_server.cc")
        ctrl = self._read("main/reminder_control_client.cc")
        hdr = self._read("main/reminder_control_client.h")
        self.assertIn("ClearConfig", hdr)
        self.assertIn('ClearConfig(\n                "capability_missing")', mcp)
        self.assertIn("status=cleared", ctrl)
        self.assertIn("ErasePersistedConfigLocked", ctrl)
        self.assertIn('EraseKey(kKeyUrl)', ctrl)

    def test_wss_uses_crt_bundle_and_keeps_hostname_check(self) -> None:
        src = self._read("main/esp_network.h")
        self.assertIn("esp_crt_bundle_attach", src)
        # EspWebSocket Connect must attach the certificate bundle.
        ws_connect = src.split("class EspWebSocket", 1)[1].split(
            "class EspMqtt", 1
        )[0]
        self.assertIn(
            "config.crt_bundle_attach = esp_crt_bundle_attach", ws_connect
        )
        # Hostname / CN checks must remain enabled (field never set true).
        self.assertNotRegex(src, r"skip_cert_common_name_check\s*=\s*true")

    def test_cancel_uses_atomic_code_not_raw_string(self) -> None:
        hdr = self._read("main/reminder_control_client.h")
        src = self._read("main/reminder_control_client.cc")
        self.assertIn("std::atomic<CancelCode> cancel_code_", hdr)
        self.assertIn("RequestCancel(", src)
        self.assertNotIn("cancel_reason_", hdr)
        self.assertNotIn("cancel_reason_", src)
        self.assertNotRegex(src, r"cancel_reason_\s*=")

    def test_shared_immediate_play_entry(self) -> None:
        hdr = self._read("main/reminder_voice_service.h")
        voice = self._read("main/reminder_voice_service.cc")
        control = self._read("main/reminder_control_client.cc")
        self.assertIn("TryPlayAcceptedAssetNow", hdr)
        self.assertIn("AcceptCachedAssetAndMaybePlay", hdr)
        self.assertIn("AcceptCachedAssetAndMaybePlay", voice)
        self.assertIn("AcceptCachedAssetAndMaybePlay", control)
        self.assertIn("TryPlayAcceptedAssetNow", voice)
        self.assertIn('source=downloaded', voice)
        self.assertIn("event=play_discard", voice)
        self.assertIn("already_played", voice)
        # PlayAttention must stay local-chime only (not AI cache).
        attention = voice.split(
            "ReminderVoiceService::PlayAttention", 1
        )[1].split("ReminderVoiceService::PlayFeedback", 1)[0]
        self.assertIn("local_fallback", attention)
        self.assertNotIn("PlayCached", attention)
        self.assertIn("PlayDueLocalOrChime", hdr)
        self.assertIn("HasCachedVoice", hdr)

    def test_reminder_interaction_does_not_open_control_mic(self) -> None:
        application = self._read("main/application.cc")
        control = self._read("main/reminder_control_client.cc")
        self.assertIn("kListeningReasonReminder", application)
        self.assertIn("SendStartListening", application)
        self.assertNotIn("EnableVoiceProcessing", control)
        self.assertNotIn("SendStartListening", control)
        self.assertNotIn("kListeningReasonReminder", control)


if __name__ == "__main__":
    unittest.main()
