"""Host-side regression for device face enrollment enrollment contract.

Does not require camera, network, FreeRTOS, or a real enrollment server.
Also scans firmware sources for capability / isolation / privacy contracts.
"""

from __future__ import annotations

import re
import unittest
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def starts_with_https(url: str) -> bool:
    return url.startswith("https://")


def extract_host(url: str) -> str:
    for prefix in ("https://", "http://", "wss://", "ws://"):
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
        if a in (10, 127, 0):
            return True
        if a == 192 and b == 168:
            return True
        if a == 172 and 16 <= b <= 31:
            return True
        if a == 169 and b == 254:
            return True
    return False


def accept_enrollment_capability(
    session_url: str,
    main_ws_url: str = "wss://public.example.com/xiaozhi/v1/",
    protocol_version: int = 1,
    session_timeout_seconds: int = 120,
    required_frames: int = 3,
    max_frames: int = 5,
    max_frame_bytes: int = 307200,
) -> tuple[bool, str]:
    if not session_url:
        return False, "missing_url"
    if session_url.startswith("http://") or session_url.startswith("ws://"):
        return False, "not_https"
    if session_url.startswith("wss://"):
        return False, "not_https"
    if not starts_with_https(session_url):
        return False, "not_https"
    host = normalize_host(extract_host(session_url))
    if not host:
        return False, "bad_host"
    if is_forbidden_host(host):
        return False, "forbidden_host"
    if not main_ws_url:
        return False, "main_ws_missing"
    if not main_ws_url.startswith("wss://"):
        return False, "main_ws_not_wss"
    main_host = normalize_host(extract_host(main_ws_url))
    if main_host != host:
        return False, "host_mismatch"
    if protocol_version != 1:
        return False, "unsupported_version"
    if not (30 <= session_timeout_seconds <= 600):
        return False, "bad_timeout"
    if not (1 <= required_frames <= 10):
        return False, "bad_required_frames"
    if not (required_frames <= max_frames <= 20):
        return False, "bad_max_frames"
    if not (1024 <= max_frame_bytes <= 512 * 1024):
        return False, "bad_max_frame_bytes"
    return True, "ok"


@dataclass
class FakeStore:
    values: dict[str, object] = field(default_factory=dict)

    def clear(self) -> None:
        self.values.clear()

    def has_session_url(self) -> bool:
        return bool(self.values.get("session_url"))


def validate_create_session_response(
    session_url: str,
    ok: bool,
    session_id: str,
    upload_url: str,
    cancel_url: str,
    upload_token: str,
    expires_at: int,
    required_frames: int,
    max_frames: int,
    now_unix: int,
    session_timeout_seconds: int = 120,
) -> tuple[bool, str]:
    if not ok:
        return False, "missing_ok"
    if not session_id or len(session_id) > 128:
        return False, "bad_session_id"
    if not upload_token or len(upload_token) > 512:
        return False, "bad_upload_token"
    if not starts_with_https(upload_url) or not starts_with_https(cancel_url):
        return False, "bad_url"
    expected = normalize_host(extract_host(session_url))
    if normalize_host(extract_host(upload_url)) != expected:
        return False, "host_mismatch"
    if normalize_host(extract_host(cancel_url)) != expected:
        return False, "host_mismatch"
    if expires_at <= now_unix:
        return False, "expires_at_past"
    if expires_at > now_unix + session_timeout_seconds + 120:
        return False, "expires_at_too_far"
    if not (1 <= required_frames <= 10):
        return False, "bad_required_frames"
    if not (required_frames <= max_frames <= 20):
        return False, "bad_max_frames"
    return True, "ok"


def apply_server_time_for_settimeofday(
    timestamp_ms: float, timezone_offset_min: int | None = None
) -> int:
    """Mirror firmware: settimeofday uses epoch ms only; offset must not shift it."""
    del timezone_offset_min  # display/TZ only — never added to epoch
    return int(timestamp_ms // 1000)


def buggy_apply_server_time_with_offset(
    timestamp_ms: float, timezone_offset_min: int
) -> int:
    """Pre-fix bug: timezone_offset was added before settimeofday."""
    return int((timestamp_ms + timezone_offset_min * 60 * 1000) // 1000)


def session_expired_by_manager(
    expires_at: int,
    now_unix: int,
    uptime_ms: int,
    capture_started_at_ms: int,
    session_timeout_seconds: int = 120,
) -> bool:
    """Mirror fixed manager: Unix expires_at vs time(nullptr); local vs uptime."""
    if expires_at > 0 and now_unix >= expires_at:
        return True
    if capture_started_at_ms > 0 and (
        uptime_ms - capture_started_at_ms > session_timeout_seconds * 1000
    ):
        return True
    return False


def buggy_session_expired_uptime_vs_unix(
    expires_at: int, uptime_ms: int
) -> bool:
    """Pre-fix bug: compared esp_timer uptime seconds to Unix expires_at."""
    return expires_at > 0 and (uptime_ms // 1000) >= expires_at


def validate_upload_success(
    local_session_id: str,
    ok: bool,
    response_session_id: str,
    accepted_count: int,
    required_frames: int,
    max_frames: int,
    status: str,
    draft_ready: bool,
    previous_accepted: int,
    session_required: int,
    session_max: int,
) -> tuple[bool, str]:
    if not ok:
        return False, "missing_ok"
    if response_session_id != local_session_id:
        return False, "session_id_mismatch"
    if accepted_count < 0 or accepted_count > max_frames:
        return False, "accepted_count_oob"
    if accepted_count < previous_accepted:
        return False, "accepted_count_regress"
    if required_frames != session_required or max_frames != session_max:
        return False, "frame_quota_mismatch"
    if status not in {"collecting", "draft_ready"}:
        return False, "bad_status"
    if status == "draft_ready":
        if not draft_ready or accepted_count < required_frames:
            return False, "draft_inconsistent"
    elif draft_ready or accepted_count >= required_frames:
        return False, "draft_inconsistent"
    return True, "ok"


@dataclass
class EnrollmentEngine:
    device_state: str = "idle"
    preview_active: bool = False
    uvc_ready: bool = True
    capability_ok: bool = True
    store: FakeStore = field(default_factory=FakeStore)
    state: str = "idle"
    generation: int = 0
    accepted: int = 0
    required: int = 3
    max_frames: int = 5
    attempted: int = 0
    sessions_created: int = 0
    remote_cleanups: int = 0
    presence_capture_skipped: int = 0
    presence_changed: list[bool] = field(default_factory=list)
    camera_held: bool = False
    secrets_in_logs: list[str] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)
    persisted_tokens: list[str] = field(default_factory=list)
    identity_busy: bool = False
    events: list[str] = field(default_factory=list)
    session_id: str = ""
    upload_blocked: bool = False
    pending_upload_result: dict | None = None
    worker_alive: bool = False

    def on_presence(self, present: bool) -> None:
        self.presence_changed.append(present)
        if present and self.state in {
            "waiting_for_idle",
            "creating_session",
            "guidance",
            "capturing",
            "uploading",
        }:
            self.presence_capture_skipped += 1
            return
        # Normal path would start identify CaptureTask — not enrollment.
        if present:
            self.events.append("identify_capture")

    def apply_capability(self, capability: object | None, main_ws: str) -> str:
        if not isinstance(capability, dict):
            self.store.clear()
            self.capability_ok = False
            if self.state not in {"idle", "draft_ready"}:
                self.cancel("capability_invalid")
            self.events.append("cleared:capability_missing")
            return "cleared"
        ok, reason = accept_enrollment_capability(
            str(capability.get("session_url", "")),
            main_ws,
            int(capability.get("protocol_version", 1)),
            int(capability.get("session_timeout_seconds", 120)),
            int(capability.get("required_frames", 3)),
            int(capability.get("max_frames", 5)),
            int(capability.get("max_frame_bytes", 307200)),
        )
        if not ok:
            self.store.clear()
            self.capability_ok = False
            self.cancel(reason)
            self.events.append(f"rejected:{reason}")
            return "rejected"
        self.store.values["session_url"] = capability["session_url"]
        self.capability_ok = True
        self.required = int(capability.get("required_frames", 3))
        self.max_frames = int(capability.get("max_frames", 5))
        self.events.append("accepted")
        return "accepted"

    def start(self) -> str:
        if not self.capability_ok:
            self.hints.append("录入服务暂不可用")
            return "录入服务暂不可用"
        if self.state in {
            "waiting_for_idle",
            "creating_session",
            "guidance",
            "capturing",
            "uploading",
        }:
            return "already_active"
        self.generation += 1
        self.state = "waiting_for_idle"
        self.accepted = 0
        self.attempted = 0
        self.session_id = ""
        self.worker_alive = True
        self.remote_cleanups = 0
        self.hints.append("已准备采集，请正对摄像头")
        self.events.append("start")
        return "已准备采集，请正对摄像头"

    def pump_to_session(self, stop_before_create: bool = False,
                        stop_before_capture: bool = False) -> None:
        if self.state != "waiting_for_idle":
            return
        if self.device_state != "idle":
            return
        if self.preview_active:
            self.state = "failed"
            self.hints.append("请先关闭相机预览")
            self.camera_held = False
            self.worker_alive = False
            return
        if not self.uvc_ready:
            self.state = "failed"
            self.hints.append("录入服务暂不可用")
            self.worker_alive = False
            return
        self.state = "creating_session"
        if stop_before_create:
            return
        gen = self.generation
        self.sessions_created += 1
        self.session_id = f"sess-{self.sessions_created}"
        if gen != self.generation:
            self._cleanup_once()
            self.state = "cancelled"
            self.worker_alive = False
            return
        self.state = "guidance"
        if self.identity_busy:
            self.events.append("wait_identity")
        if stop_before_capture:
            return
        self.camera_held = True
        self.state = "capturing"

    def upload(self, error_code: str | None = None, retryable: bool = False,
               draft: bool = False, jpeg_bytes: int = 1000,
               max_frame_bytes: int = 307200) -> str:
        if self.state not in {"capturing", "guidance", "uploading"}:
            return "idle"
        gen = self.generation
        self.state = "uploading"
        self.attempted += 1
        if jpeg_bytes > max_frame_bytes:
            if gen != self.generation:
                return "stale"
            self.state = "failed"
            self.camera_held = False
            self.worker_alive = False
            self._cleanup_once()
            self.hints.append("采集失败，请重新开始")
            self.events.append("payload_too_large")
            return "payload_too_large"
        if self.upload_blocked:
            self.pending_upload_result = {
                "error_code": error_code,
                "retryable": retryable,
                "draft": draft,
            }
            return "blocked"
        return self._apply_upload(gen, error_code, retryable, draft)

    def _apply_upload(
        self,
        expected_gen: int,
        error_code: str | None,
        retryable: bool,
        draft: bool,
    ) -> str:
        # Late completion uses the generation observed when upload started.
        start_gen = expected_gen
        if start_gen != self.generation:
            self.events.append("stale_upload_discarded")
            self.worker_alive = False
            if self.state not in {"cancelled", "failed", "expired", "idle"}:
                self.state = "cancelled"
            self.camera_held = False
            return "stale"
        if error_code:
            if error_code in {
                "no_face",
                "multiple_faces",
                "duplicate_frame",
            } or (error_code == "face_quality_low" and retryable):
                self.hints.append("请正对摄像头")
                self.state = "guidance"
                return "soft_reject"
            if error_code == "payload_too_large":
                self.state = "failed"
                self.camera_held = False
                self.worker_alive = False
                self._cleanup_once()
                self.hints.append("采集失败，请重新开始")
                return "payload_too_large"
            if error_code == "face_quality_low" and not retryable:
                self.state = "failed"
                self.camera_held = False
                self.worker_alive = False
                self._cleanup_once()
                self.hints.append("采集失败，请重新开始")
                return "failed"
            if error_code in {
                "auth_invalid",
                "device_mismatch",
                "capability_invalid",
            }:
                self.state = "failed"
                self.camera_held = False
                self.worker_alive = False
                self._cleanup_once()
                self.hints.append("录入服务暂不可用")
                return "failed"
            if error_code == "session_expired":
                self.state = "expired"
                self.camera_held = False
                self.worker_alive = False
                self._cleanup_once()
                self.hints.append("采集超时，请重试")
                return "expired"
            return "failed"
        self.accepted += 1
        if draft or self.accepted >= self.required:
            self.state = "draft_ready"
            self.camera_held = False
            self.worker_alive = False
            self.hints.append("采集完成，请到网页填写姓名")
            return "draft_ready"
        self.state = "guidance"
        return "accepted"

    def _cleanup_once(self) -> None:
        if self.session_id and self.remote_cleanups == 0:
            self.remote_cleanups = 1
            self.events.append("session_cleanup")
            self.session_id = ""

    def cancel(self, reason: str = "session_cancelled") -> str:
        if self.state == "idle" and not self.session_id:
            return "当前没有进行中的人脸采集"
        # Immediate local cancel: bump generation, release camera, async cleanup.
        self.generation += 1
        self.state = "cancelled" if reason == "session_cancelled" else "failed"
        self.camera_held = False
        self.worker_alive = False
        self._cleanup_once()
        self.hints.append(
            "采集已取消" if reason == "session_cancelled" else "录入服务暂不可用"
        )
        self.events.append(f"cancel:{reason}")
        return "采集已取消"

    def late_create_session_after_cancel(self) -> None:
        # CreateSession returned after cancel invalidated generation.
        self.sessions_created += 1
        self.events.append("late_create_discarded")
        if self.remote_cleanups == 0:
            self.remote_cleanups = 1
            self.events.append("session_cleanup")
        self.session_id = ""


class FaceEnrollmentRegressionTest(unittest.TestCase):
    def test_presence_never_creates_enrollment_session(self) -> None:
        eng = EnrollmentEngine()
        eng.on_presence(True)
        self.assertEqual(eng.sessions_created, 0)
        self.assertIn("identify_capture", eng.events)
        eng.start()
        eng.pump_to_session()
        eng.on_presence(True)
        self.assertEqual(eng.presence_capture_skipped, 1)
        self.assertEqual(eng.sessions_created, 1)

    def test_only_enroll_start_creates_session(self) -> None:
        eng = EnrollmentEngine()
        eng.on_presence(True)
        eng.on_presence(False)
        self.assertEqual(eng.sessions_created, 0)
        reply = eng.start()
        self.assertTrue(reply.startswith("\u5df2\u51c6\u5907\u91c7\u96c6"))
        self.assertNotIn("\u5df2\u5f55\u5165\u6210\u529f", reply)
        eng.pump_to_session()
        self.assertEqual(eng.sessions_created, 1)

    def test_waiting_for_idle_while_speaking(self) -> None:
        eng = EnrollmentEngine(device_state="speaking")
        eng.start()
        self.assertEqual(eng.state, "waiting_for_idle")
        eng.pump_to_session()
        self.assertEqual(eng.sessions_created, 0)
        eng.device_state = "idle"
        eng.pump_to_session()
        self.assertEqual(eng.sessions_created, 1)

    def test_preview_active_does_not_grab_camera(self) -> None:
        eng = EnrollmentEngine(preview_active=True)
        eng.start()
        eng.pump_to_session()
        self.assertEqual(eng.state, "failed")
        self.assertFalse(eng.camera_held)
        self.assertIn("请先关闭相机预览", eng.hints)

    def test_capability_rejects_http_private_localhost_mismatch(self) -> None:
        main = "wss://public.example.com/xiaozhi/v1/"
        cases = [
            ("http://public.example.com/mcp/face-enrollment/sessions", "not_https"),
            ("https://localhost/mcp/face-enrollment/sessions", "forbidden_host"),
            ("https://192.168.1.8/mcp/face-enrollment/sessions", "forbidden_host"),
            ("https://other.example.com/mcp/face-enrollment/sessions", "host_mismatch"),
            ("", "missing_url"),
        ]
        for url, reason in cases:
            ok, got = accept_enrollment_capability(url, main)
            self.assertFalse(ok, url)
            self.assertEqual(got, reason, url)
        ok, _ = accept_enrollment_capability(
            "https://public.example.com/mcp/face-enrollment/sessions", main
        )
        self.assertTrue(ok)

    def test_capability_missing_clears_and_stops(self) -> None:
        eng = EnrollmentEngine()
        main = "wss://public.example.com/xiaozhi/v1/"
        eng.apply_capability(
            {
                "session_url": "https://public.example.com/mcp/face-enrollment/sessions",
                "protocol_version": 1,
                "required_frames": 3,
                "max_frames": 5,
                "max_frame_bytes": 307200,
                "session_timeout_seconds": 120,
            },
            main,
        )
        self.assertTrue(eng.store.has_session_url())
        eng.start()
        eng.pump_to_session()
        eng.apply_capability(None, main)
        self.assertFalse(eng.store.has_session_url())
        self.assertFalse(eng.camera_held)
        self.assertIn("cleared:capability_missing", eng.events)

    def test_three_accepted_frames_draft_ready(self) -> None:
        eng = EnrollmentEngine()
        eng.start()
        eng.pump_to_session()
        self.assertEqual(eng.upload(), "accepted")
        self.assertEqual(eng.upload(), "accepted")
        self.assertEqual(eng.upload(), "draft_ready")
        self.assertEqual(eng.state, "draft_ready")
        self.assertEqual(eng.accepted, 3)
        self.assertFalse(eng.camera_held)
        self.assertIn("采集完成，请到网页填写姓名", eng.hints)

    def test_soft_quality_errors_do_not_count(self) -> None:
        eng = EnrollmentEngine()
        eng.start()
        eng.pump_to_session()
        for code in ("no_face", "multiple_faces", "duplicate_frame"):
            self.assertEqual(eng.upload(error_code=code, retryable=True), "soft_reject")
        self.assertEqual(
            eng.upload(error_code="face_quality_low", retryable=True), "soft_reject"
        )
        self.assertEqual(eng.accepted, 0)
        self.assertEqual(eng.upload(), "accepted")
        self.assertEqual(eng.accepted, 1)

    def test_fatal_quality_cancel_timeout_release_camera(self) -> None:
        eng = EnrollmentEngine()
        eng.start()
        eng.pump_to_session()
        self.assertTrue(eng.camera_held)
        self.assertEqual(
            eng.upload(error_code="face_quality_low", retryable=False), "failed"
        )
        self.assertFalse(eng.camera_held)

        eng = EnrollmentEngine()
        eng.start()
        eng.pump_to_session()
        eng.cancel()
        self.assertFalse(eng.camera_held)
        self.assertIn("采集已取消", eng.hints)

        eng = EnrollmentEngine()
        eng.start()
        eng.pump_to_session()
        self.assertEqual(eng.upload(error_code="session_expired"), "expired")
        self.assertFalse(eng.camera_held)

    def test_tokens_never_persisted_or_logged(self) -> None:
        eng = EnrollmentEngine()
        eng.start()
        eng.pump_to_session()
        self.assertEqual(eng.persisted_tokens, [])
        joined = " ".join(eng.hints + eng.events)
        self.assertNotIn("upload_token", joined)
        self.assertNotIn("Bearer ", joined)

    def test_identity_verifier_wait_no_deadlock(self) -> None:
        eng = EnrollmentEngine(identity_busy=True)
        eng.start()
        eng.pump_to_session()
        self.assertIn("wait_identity", eng.events)
        self.assertTrue(eng.camera_held)
        # Reminder presence path still recorded.
        eng.on_presence(False)
        self.assertEqual(eng.presence_changed[-1], False)

    def test_start_reply_never_says_enrolled(self) -> None:
        eng = EnrollmentEngine()
        reply = eng.start()
        self.assertIn("请正对摄像头", reply)
        self.assertNotIn("已录入成功", reply)

    def test_duplicate_start_already_active(self) -> None:
        eng = EnrollmentEngine()
        eng.start()
        self.assertEqual(eng.start(), "already_active")

    def test_cancel_before_create_retry_capture_exits(self) -> None:
        eng = EnrollmentEngine()
        eng.start()
        eng.pump_to_session(stop_before_create=True)
        self.assertEqual(eng.state, "creating_session")
        eng.cancel()
        self.assertEqual(eng.state, "cancelled")
        self.assertFalse(eng.worker_alive)
        self.assertFalse(eng.camera_held)

        eng = EnrollmentEngine()
        eng.start()
        eng.pump_to_session(stop_before_capture=True)
        eng.cancel()
        self.assertEqual(eng.state, "cancelled")
        self.assertFalse(eng.camera_held)
        self.assertFalse(eng.worker_alive)

    def test_cancel_during_blocked_upload_discards_draft(self) -> None:
        eng = EnrollmentEngine()
        eng.start()
        eng.pump_to_session()
        upload_gen = eng.generation
        eng.upload_blocked = True
        self.assertEqual(eng.upload(draft=True), "blocked")
        reply = eng.cancel()
        self.assertIn("\u91c7\u96c6\u5df2\u53d6\u6d88", reply)
        # Late successful draft_ready must be discarded.
        result = eng._apply_upload(upload_gen, None, False, True)
        self.assertEqual(result, "stale")
        self.assertNotEqual(eng.state, "draft_ready")
        self.assertTrue(
            all("\u91c7\u96c6\u5b8c\u6210" not in h for h in eng.hints)
        )

    def test_capability_clear_late_create_cleans_once(self) -> None:
        eng = EnrollmentEngine()
        main = "wss://public.example.com/xiaozhi/v1/"
        eng.apply_capability(
            {
                "session_url": "https://public.example.com/mcp/face-enrollment/sessions",
                "protocol_version": 1,
                "required_frames": 3,
                "max_frames": 5,
                "max_frame_bytes": 307200,
                "session_timeout_seconds": 120,
            },
            main,
        )
        eng.start()
        eng.state = "creating_session"
        eng.apply_capability(None, main)
        eng.late_create_session_after_cancel()
        self.assertEqual(eng.remote_cleanups, 1)
        self.assertNotEqual(eng.state, "draft_ready")

    def test_failed_expired_cleanup_at_most_once(self) -> None:
        eng = EnrollmentEngine()
        eng.start()
        eng.pump_to_session()
        eng.upload(error_code="face_quality_low", retryable=False)
        self.assertEqual(eng.remote_cleanups, 1)
        eng._cleanup_once()
        self.assertEqual(eng.remote_cleanups, 1)

        eng = EnrollmentEngine()
        eng.start()
        eng.pump_to_session()
        eng.upload(error_code="session_expired")
        self.assertEqual(eng.remote_cleanups, 1)

    def test_create_session_response_validation(self) -> None:
        base = "https://public.example.com/mcp/face-enrollment/sessions"
        now = 1_700_000_000
        ok, reason = validate_create_session_response(
            base, True, "abc", base + "/u", base + "/c", "tok", now + 60, 3, 5, now
        )
        self.assertTrue(ok)
        ok, reason = validate_create_session_response(
            base, False, "abc", base + "/u", base + "/c", "tok", now + 60, 3, 5, now
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "missing_ok")
        ok, reason = validate_create_session_response(
            base, True, "abc", base + "/u", base + "/c", "tok", now - 1, 3, 5, now
        )
        self.assertEqual(reason, "expires_at_past")
        ok, reason = validate_create_session_response(
            base,
            True,
            "abc",
            "https://evil.example.com/u",
            base + "/c",
            "tok",
            now + 60,
            3,
            5,
            now,
        )
        self.assertEqual(reason, "host_mismatch")
        ok, reason = validate_create_session_response(
            base, True, "abc", base + "/u", base + "/c", "tok", now + 60, 5, 3, now
        )
        self.assertEqual(reason, "bad_max_frames")

    def test_timezone_offset_must_not_shift_epoch_for_expires_at(self) -> None:
        """timezone_offset=480 must not make expires_at=server_now+120 look past."""
        base = "https://public.example.com/mcp/face-enrollment/sessions"
        server_now = 1_700_000_000
        timestamp_ms = float(server_now * 1000)
        timezone_offset = 480  # UTC+8 minutes
        expires_at = server_now + 120

        # Fixed path: settimeofday uses raw timestamp; validation uses that clock.
        now_unix = apply_server_time_for_settimeofday(timestamp_ms, timezone_offset)
        self.assertEqual(now_unix, server_now)
        ok, reason = validate_create_session_response(
            base, True, "abc", base + "/u", base + "/c", "tok", expires_at, 3, 5,
            now_unix,
        )
        self.assertTrue(ok, reason)
        self.assertEqual(reason, "ok")

        # Buggy path: offset added to epoch => device 28800s ahead => expires_at_past.
        buggy_now = buggy_apply_server_time_with_offset(timestamp_ms, timezone_offset)
        self.assertEqual(buggy_now, server_now + 28800)
        ok, reason = validate_create_session_response(
            base, True, "abc", base + "/u", base + "/c", "tok", expires_at, 3, 5,
            buggy_now,
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "expires_at_past")

    def test_manager_expires_at_uses_unix_not_uptime(self) -> None:
        """Capture loop must not compare esp_timer uptime to Unix expires_at."""
        server_now = 1_700_000_000
        expires_at = server_now + 120
        # Fresh boot: uptime ~5s. Buggy NowMs()/1000 >= expires_at never trips
        # (false negative); fixed path uses wall-clock Unix time.
        uptime_ms = 5_000
        self.assertFalse(buggy_session_expired_uptime_vs_unix(expires_at, uptime_ms))
        self.assertFalse(
            session_expired_by_manager(
                expires_at,
                now_unix=server_now,
                uptime_ms=uptime_ms,
                capture_started_at_ms=uptime_ms,
            )
        )
        # Real expiry by Unix clock.
        self.assertTrue(
            session_expired_by_manager(
                expires_at,
                now_unix=expires_at,
                uptime_ms=uptime_ms + 1_000,
                capture_started_at_ms=uptime_ms,
            )
        )
        # Local capture timeout (after CreateSession) still works via uptime delta.
        self.assertTrue(
            session_expired_by_manager(
                expires_at,
                now_unix=server_now,
                uptime_ms=uptime_ms + 121_000,
                capture_started_at_ms=uptime_ms,
                session_timeout_seconds=120,
            )
        )
        # waiting_for_idle elapsed before CreateSession must not start capture clock.
        self.assertFalse(
            session_expired_by_manager(
                expires_at,
                now_unix=server_now,
                uptime_ms=90_000,
                capture_started_at_ms=0,
            )
        )

    def test_upload_response_validation(self) -> None:
        ok, reason = validate_upload_success(
            "s1", True, "s1", 1, 3, 5, "collecting", False, 0, 3, 5
        )
        self.assertTrue(ok)
        ok, reason = validate_upload_success(
            "s1", True, "s2", 1, 3, 5, "collecting", False, 0, 3, 5
        )
        self.assertEqual(reason, "session_id_mismatch")
        ok, reason = validate_upload_success(
            "s1", True, "s1", 0, 3, 5, "collecting", False, 1, 3, 5
        )
        self.assertEqual(reason, "accepted_count_regress")
        ok, reason = validate_upload_success(
            "s1", True, "s1", 9, 3, 5, "collecting", False, 0, 3, 5
        )
        self.assertEqual(reason, "accepted_count_oob")
        ok, reason = validate_upload_success(
            "s1", True, "s1", 1, 3, 5, "weird", False, 0, 3, 5
        )
        self.assertEqual(reason, "bad_status")
        ok, reason = validate_upload_success(
            "s1", True, "s1", 1, 3, 5, "draft_ready", True, 0, 3, 5
        )
        self.assertEqual(reason, "draft_inconsistent")

    def test_oversized_jpeg_payload_too_large(self) -> None:
        eng = EnrollmentEngine()
        eng.start()
        eng.pump_to_session()
        self.assertEqual(
            eng.upload(jpeg_bytes=400000, max_frame_bytes=307200),
            "payload_too_large",
        )
        self.assertEqual(eng.state, "failed")
        self.assertFalse(eng.camera_held)
        self.assertEqual(eng.remote_cleanups, 1)
        # No infinite repump.
        self.assertEqual(eng.attempted, 1)


class FaceEnrollmentSourceContractTest(unittest.TestCase):
    def _read(self, rel: str) -> str:
        return (ROOT / rel).read_text(encoding="utf-8")

    def test_modules_and_tools_exist(self) -> None:
        self.assertTrue((ROOT / "main/face_enrollment_client.cc").exists())
        self.assertTrue((ROOT / "main/face_enrollment_manager.cc").exists())
        tools = self._read("main/mcp_tools/mcp_tools_camera.cc")
        self.assertIn("camera.face.enroll.start", tools)
        self.assertIn("camera.face.enroll.cancel", tools)
        self.assertIn("camera.face.enroll.status", tools)
        self.assertIn("录入人脸", tools)
        self.assertIn("采集完成后提示用户到网页填写姓名", tools)

    def test_capability_parsed_in_mcp_initialize(self) -> None:
        mcp = self._read("main/mcp_server.cc")
        self.assertIn('face_enrollment', mcp)
        self.assertIn("SetCapability", mcp)
        self.assertIn("ClearCapability", mcp)
        self.assertIn("OnCapabilityCleared", mcp)

    def test_presence_skips_capture_not_reminder(self) -> None:
        board = self._read("main/boards/esp-box-3/esp_box3_board.cc")
        self.assertIn("FaceEnrollmentManager::GetInstance().IsActive()", board)
        self.assertIn("OnPresenceDetected", board)
        # Skip is only around CaptureTask path.
        self.assertIn("Presence capture skipped: face enrollment is active", board)

    def test_https_host_match_and_no_secret_logging(self) -> None:
        client = self._read("main/face_enrollment_client.cc")
        self.assertIn("host_mismatch", client)
        self.assertIn("not_https", client)
        self.assertIn("forbidden_host", client)
        self.assertIn("X-Enrollment-Token", client)
        self.assertIn("Device-Id", client)
        self.assertIn("Client-Id", client)
        self.assertNotRegex(client, r'ESP_LOG[IW].*upload_token')
        self.assertNotIn("FACE_JWT", client)
        self.assertNotIn("FACE_API", client)
        store = self._read("main/face_config_store.cc")
        self.assertIn('EraseKey("session_url")', store)
        self.assertNotIn("Settings settings(", client)
        self.assertIn("Settings settings(", store)
        # Must not persist session secrets.
        self.assertNotIn('SetString("session_id"', client)
        self.assertNotIn('SetString("upload_token"', client)
        self.assertNotIn('SetString("session_id"', store)
        self.assertNotIn('SetString("upload_token"', store)
        # Diagnostic expiry logs must not include tokens/URLs.
        self.assertIn("now_unix=", client)
        self.assertIn("expires_at=", client)
        self.assertIn("delta_s=", client)

    def test_ota_server_time_does_not_add_timezone_to_epoch(self) -> None:
        ota = self._read("main/ota.cc")
        # Must set clock from timestamp alone; offset is TZ/display only.
        self.assertIn("settimeofday(&tv, NULL)", ota)
        self.assertIn("timezone_offset", ota)
        self.assertIn("event=server_time", ota)
        self.assertIn("now_unix=", ota)
        self.assertNotRegex(
            ota,
            r"ts\s*\+=\s*\(.*timezone_offset",
        )
        self.assertIn('setenv("TZ"', ota)
        self.assertIn("tzset()", ota)

    def test_manager_states_and_privacy(self) -> None:
        mgr = self._read("main/face_enrollment_manager.cc")
        for state in (
            "waiting_for_idle",
            "creating_session",
            "guidance",
            "capturing",
            "uploading",
            "draft_ready",
            "cancelled",
            "expired",
            "failed",
        ):
            self.assertIn(state, mgr)
        self.assertIn("[FACE_ENROLL]", mgr)
        self.assertIn("请到网页填写姓名", mgr)
        self.assertIn("shrink_to_fit", mgr)
        self.assertNotIn("ReminderCoordinator", mgr)
        self.assertNotIn("RequestScripts", mgr)
        # expires_at is Unix; must use time(nullptr), not NowMs()/1000.
        self.assertIn("time(nullptr)", mgr)
        self.assertNotIn("NowMs() / 1000", mgr)
        self.assertIn("capture_started_at_ms_", mgr)
        self.assertNotIn("idle_wait_started_at_ms_", mgr)
        hdr = self._read("main/face_enrollment_manager.h")
        self.assertIn("capture_started_at_ms_", hdr)
        self.assertNotIn("idle_wait_started_at_ms_", hdr)
        self.assertNotRegex(hdr, r"(?<![a-z_])started_at_ms_")

    def test_no_finish_under_lock_and_async_cancel(self) -> None:
        mgr = self._read("main/face_enrollment_manager.cc")
        hdr = self._read("main/face_enrollment_manager.h")
        client = self._read("main/face_enrollment_client.cc")
        self.assertIn("operation_generation_", hdr)
        self.assertIn("FinishOutsideLock", mgr)
        self.assertIn("ScheduleAsyncCleanup", mgr)
        self.assertIn("face_enroll_cln", mgr)
        # Cancel must not call CancelSession synchronously.
        cancel_fn = mgr.split("FaceEnrollmentManager::Cancel()", 1)[1].split(
            "FaceEnrollmentManager::WaitUntilIdleOrCancelled", 1
        )[0]
        self.assertNotIn("CancelSession(", cancel_fn)
        self.assertIn("ScheduleAsyncCleanup", cancel_fn)
        self.assertIn("payload_too_large", client)
        self.assertIn("ValidateCreateSessionResponse", client)
        self.assertIn("ValidateUploadSuccessResponse", client)
        self.assertIn('out->error_code = "payload_too_large"', client)
        self.assertIn("ValidateCreateSessionResponse", client)
        # Upload must use SetContent(full multipart); Write-after-Open with empty
        # content_ sends Content-Length:0 and triggers server boundary errors.
        upload_fn = client.split(
            "FaceEnrollmentClient::UploadFrame(", 1
        )[1].split("FaceEnrollmentClient::CancelSession(", 1)[0]
        self.assertIn("SetContent(", upload_fn)
        self.assertIn("boundary=enrollframe", upload_fn)
        self.assertIn("--enrollframe\\r\\n", upload_fn)
        self.assertIn("body_prefix_hex=", upload_fn)
        self.assertIn("upload_rejected", upload_fn)
        self.assertNotIn("http->Write(", upload_fn)

if __name__ == "__main__":
    unittest.main()
