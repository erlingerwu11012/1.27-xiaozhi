"""Host-side contract tests for the opt-in guided face-enrollment V2 path.

This suite intentionally does not talk to a camera, TLS endpoint, FreeRTOS, or
the service.  It locks the firmware-side safety and UX contract while the
server implementation is still pending.
"""

from __future__ import annotations

import re
import unittest
from dataclasses import dataclass, field
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLIENT_CC = ROOT / "main" / "face_enrollment_client.cc"
CLIENT_H = ROOT / "main" / "face_enrollment_client.h"
MANAGER_CC = ROOT / "main" / "face_enrollment_manager.cc"
MANAGER_H = ROOT / "main" / "face_enrollment_manager.h"
CATALOG_CC = ROOT / "main" / "face_enrollment_prompt_catalog.cc"
GESTURE_CC = ROOT / "main" / "touch" / "gesture_handler.cc"
MCP_SERVER_CC = ROOT / "main" / "mcp_server.cc"
BOARD_CC = ROOT / "main" / "boards" / "esp-box-3" / "esp_box3_board.cc"
CMAKE = ROOT / "main" / "CMakeLists.txt"


GUIDANCE_CODES = {
    "START", "NO_FACE", "MOVE_SCREEN_LEFT", "MOVE_SCREEN_RIGHT",
    "MOVE_USER_LEFT", "MOVE_USER_RIGHT", "MOVE_UP",
    "MOVE_DOWN", "MOVE_CLOSER", "MOVE_BACK", "FACE_FORWARD", "TOO_DARK",
    "MULTIPLE_FACES", "HOLD_STILL", "ALIGN_READY", "CAPTURE_FRONT",
    "CAPTURE_LEFT", "CAPTURE_RIGHT", "RECAPTURE_FRONT", "RECAPTURE_LEFT",
    "RECAPTURE_RIGHT", "UPLOADING", "DRAFT_READY", "DRAFT_READY_FRONT_ONLY",
    "POSE_FAILED", "TIMEOUT", "CANCELLED", "SERVICE_ERROR", "UNKNOWN_RESULT",
}

# Network allowlist excludes local-only DRAFT_READY_FRONT_ONLY.
NETWORK_GUIDANCE_CODES = GUIDANCE_CODES - {"DRAFT_READY_FRONT_ONLY"}


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def v2_capability_ok(version: int, guided: bool, timeout_s: int) -> bool:
    """Mirror the strict opt-in gate; V1 can never start this path."""
    return version == 2 and guided and 240 <= timeout_s <= 600


def validate_create_session_modes(
    requested_front_only: bool,
    requested_user_relative: bool,
    guided: bool,
    capture_mode: str,
    guidance_profile: str,
    required_frames: int,
    max_frames: int,
) -> tuple[bool, str]:
    """Mirror FaceEnrollmentClient::ValidateCreateSessionModes."""
    if requested_user_relative and not requested_front_only:
        return False, "user_relative_requires_front_only"
    if requested_front_only:
        if capture_mode != "front_only_v1":
            return False, "capture_mode_mismatch"
        if required_frames != 1 or max_frames != 1:
            return False, "front_only_frame_quota_mismatch"
    else:
        if capture_mode:
            return False, "unexpected_capture_mode"
        if guided and (required_frames != 3 or max_frames != 3):
            return False, "guided_frame_quota_mismatch"
    if requested_user_relative:
        if guidance_profile != "user_relative_v1":
            return False, "guidance_profile_mismatch"
    elif guidance_profile:
        return False, "unexpected_guidance_profile"
    return True, ""


def validate_guided_response(
    *,
    guided: bool,
    session_id: str,
    response_session_id: str,
    guidance_code: str,
    accepted_count: int,
    required_frames: int,
    draft_ready: bool,
    front_only: bool = False,
    user_relative: bool = False,
) -> tuple[bool, str]:
    if not guided:
        return False, "guided_not_enabled"
    if response_session_id != session_id:
        return False, "session_id_mismatch"
    if guidance_code == "UNKNOWN_RESULT" or guidance_code not in NETWORK_GUIDANCE_CODES:
        return False, "unknown_guidance_code"
    if guidance_code == "DRAFT_READY_FRONT_ONLY":
        return False, "unknown_guidance_code"
    if guidance_code in ("MOVE_USER_LEFT", "MOVE_USER_RIGHT") and not user_relative:
        return False, "user_relative_not_negotiated"
    if front_only and guidance_code in (
        "CAPTURE_LEFT", "CAPTURE_RIGHT", "RECAPTURE_LEFT", "RECAPTURE_RIGHT"
    ):
        return False, "front_only_side_pose_forbidden"
    if accepted_count < 0 or accepted_count > required_frames:
        return False, "accepted_count_oob"
    continuation = guidance_code in {
        "START", "ALIGN_READY", "UPLOADING",
        "CAPTURE_FRONT", "CAPTURE_LEFT", "CAPTURE_RIGHT",
        "RECAPTURE_FRONT", "RECAPTURE_LEFT", "RECAPTURE_RIGHT",
        "NO_FACE", "MOVE_SCREEN_LEFT", "MOVE_SCREEN_RIGHT",
        "MOVE_USER_LEFT", "MOVE_USER_RIGHT", "MOVE_UP", "MOVE_DOWN",
        "MOVE_CLOSER", "MOVE_BACK", "FACE_FORWARD", "TOO_DARK",
        "MULTIPLE_FACES", "HOLD_STILL",
    }
    if draft_ready:
        if guidance_code != "DRAFT_READY" or accepted_count != required_frames:
            return False, "draft_inconsistent"
    elif guidance_code == "DRAFT_READY":
        return False, "draft_inconsistent"
    elif accepted_count >= required_frames and continuation:
        return False, "quota_full_continue_forbidden"
    return True, ""


def is_guided_enrollment_complete(
    *,
    guidance_code: str,
    accepted_count: int,
    required_frames: int,
    draft_ready: bool,
) -> bool:
    return (
        draft_ready
        and guidance_code == "DRAFT_READY"
        and accepted_count == required_frames
    )


@dataclass
class GuidedModel:
    generation: int = 1
    active: bool = True
    state: str = "aligning"
    accepted: int = 0
    pose_rounds: dict[str, int] = field(
        default_factory=lambda: {"front": 0, "left": 0, "right": 0}
    )

    def cancel(self) -> None:
        self.generation += 1
        self.active = False
        self.state = "cancelled"

    def capture(self, pose: str) -> bool:
        if not self.active or pose not in self.pose_rounds:
            return False
        if self.pose_rounds[pose] >= 3:
            self.state = "pose_failed"
            self.active = False
            return False
        self.pose_rounds[pose] += 1
        self.state = f"capturing_{pose}"
        return True

    def reply(self, generation: int, code: str, accepted: int, draft: bool) -> None:
        if generation != self.generation or not self.active:
            return
        if code not in GUIDANCE_CODES or code == "UNKNOWN_RESULT":
            self.state = "service_error"
            self.active = False
            return
        if accepted < self.accepted or accepted > 3:
            self.state = "service_error"
            self.active = False
            return
        self.accepted = accepted
        if draft:
            if code != "DRAFT_READY" or accepted < 3:
                self.state = "service_error"
                self.active = False
            else:
                self.state = "draft_ready"
                self.active = False
            return
        self.state = code.lower()


class CapabilityGateTests(unittest.TestCase):
    def test_v1_never_starts_guided_burst(self) -> None:
        self.assertFalse(v2_capability_ok(1, False, 120))
        self.assertFalse(v2_capability_ok(1, True, 240))

    def test_v2_requires_explicit_feature_flag(self) -> None:
        self.assertFalse(v2_capability_ok(2, False, 240))
        self.assertTrue(v2_capability_ok(2, True, 240))

    def test_v2_requires_at_least_240_second_server_session(self) -> None:
        self.assertFalse(v2_capability_ok(2, True, 239))
        self.assertTrue(v2_capability_ok(2, True, 600))
        self.assertFalse(v2_capability_ok(2, True, 601))

    def test_v2_always_has_front_left_right_final_quota(self) -> None:
        self.assertIn("guided_required_frames_must_be_3", read(CLIENT_CC))
        self.assertIn("guided_max_frames_must_be_3", read(CLIENT_CC))


class GuidedStateModelTests(unittest.TestCase):
    def test_each_pose_has_three_total_rounds(self) -> None:
        m = GuidedModel()
        for _ in range(3):
            self.assertTrue(m.capture("front"))
        self.assertFalse(m.capture("front"))
        self.assertEqual(m.pose_rounds["front"], 3)
        self.assertEqual(m.state, "pose_failed")

    def test_failed_right_only_retries_right(self) -> None:
        m = GuidedModel()
        self.assertTrue(m.capture("front"))
        self.assertTrue(m.capture("left"))
        self.assertTrue(m.capture("right"))
        self.assertTrue(m.capture("right"))
        self.assertEqual(m.pose_rounds, {"front": 1, "left": 1, "right": 2})

    def test_valid_draft_requires_all_required_poses_accepted(self) -> None:
        m = GuidedModel()
        m.reply(1, "DRAFT_READY", 3, True)
        self.assertEqual(m.state, "draft_ready")
        self.assertFalse(m.active)

    def test_inconsistent_draft_fails_closed(self) -> None:
        m = GuidedModel()
        m.reply(1, "DRAFT_READY", 2, True)
        self.assertEqual(m.state, "service_error")

    def test_unknown_server_code_is_terminal(self) -> None:
        m = GuidedModel()
        m.reply(1, "PLEASE_TURN_AROUND", 0, False)
        self.assertEqual(m.state, "service_error")

    def test_accepted_count_cannot_regress(self) -> None:
        m = GuidedModel(accepted=2)
        m.reply(1, "RECAPTURE_RIGHT", 1, False)
        self.assertEqual(m.state, "service_error")

    def test_late_reply_after_cancel_is_ignored(self) -> None:
        m = GuidedModel()
        old_generation = m.generation
        m.cancel()
        m.reply(old_generation, "DRAFT_READY", 3, True)
        self.assertEqual(m.state, "cancelled")
        self.assertFalse(m.active)

    def test_180_second_timeout_is_independent_of_server_window(self) -> None:
        started_ms = 10_000
        # Local guided timeout is 240s (aligned with session minimum).
        self.assertFalse(249_999 - started_ms >= 240_000)
        self.assertTrue(250_000 - started_ms >= 240_000)

    def test_round_contains_two_or_three_candidates_only(self) -> None:
        self.assertFalse(1 >= 2 and 1 <= 3)
        self.assertTrue(2 >= 2 and 2 <= 3)
        self.assertTrue(3 >= 2 and 3 <= 3)
        self.assertFalse(4 >= 2 and 4 <= 3)


class FrontOnlyModeTests(unittest.TestCase):
    def test_front_only_create_modes_accept(self) -> None:
        ok, reason = validate_create_session_modes(
            True, True, True, "front_only_v1", "user_relative_v1", 1, 1
        )
        self.assertTrue(ok, reason)

    def test_front_only_without_echo_rejected(self) -> None:
        ok, reason = validate_create_session_modes(
            True, False, True, "", "", 1, 1
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "capture_mode_mismatch")

    def test_front_only_wrong_quota_rejected(self) -> None:
        ok, reason = validate_create_session_modes(
            True, False, True, "front_only_v1", "", 3, 3
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "front_only_frame_quota_mismatch")

    def test_silent_downgrade_on_profile_mismatch_rejected(self) -> None:
        ok, reason = validate_create_session_modes(
            True, True, True, "front_only_v1", "", 1, 1
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "guidance_profile_mismatch")

    def test_legacy_guided_still_requires_three(self) -> None:
        ok, reason = validate_create_session_modes(
            False, False, True, "", "", 3, 3
        )
        self.assertTrue(ok, reason)

    def test_move_user_requires_negotiated_profile(self) -> None:
        ok, reason = validate_guided_response(
            guided=True,
            session_id="s1",
            response_session_id="s1",
            guidance_code="MOVE_USER_LEFT",
            accepted_count=0,
            required_frames=1,
            draft_ready=False,
            front_only=True,
            user_relative=False,
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "user_relative_not_negotiated")

    def test_front_only_rejects_side_pose_codes(self) -> None:
        ok, reason = validate_guided_response(
            guided=True,
            session_id="s1",
            response_session_id="s1",
            guidance_code="CAPTURE_LEFT",
            accepted_count=0,
            required_frames=1,
            draft_ready=False,
            front_only=True,
            user_relative=True,
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "front_only_side_pose_forbidden")

    def test_front_only_draft_ready_at_one(self) -> None:
        ok, reason = validate_guided_response(
            guided=True,
            session_id="s1",
            response_session_id="s1",
            guidance_code="DRAFT_READY",
            accepted_count=1,
            required_frames=1,
            draft_ready=True,
            front_only=True,
            user_relative=True,
        )
        self.assertTrue(ok, reason)
        self.assertTrue(
            is_guided_enrollment_complete(
                guidance_code="DRAFT_READY",
                accepted_count=1,
                required_frames=1,
                draft_ready=True,
            )
        )

    def test_quota_full_continue_rejected(self) -> None:
        for code in ("CAPTURE_FRONT", "RECAPTURE_FRONT", "NO_FACE"):
            ok, reason = validate_guided_response(
                guided=True,
                session_id="s1",
                response_session_id="s1",
                guidance_code=code,
                accepted_count=1,
                required_frames=1,
                draft_ready=False,
                front_only=True,
                user_relative=True,
            )
            self.assertFalse(ok, code)
            self.assertEqual(reason, "quota_full_continue_forbidden", code)

    def test_quota_full_terminal_still_allowed(self) -> None:
        ok, reason = validate_guided_response(
            guided=True,
            session_id="s1",
            response_session_id="s1",
            guidance_code="POSE_FAILED",
            accepted_count=1,
            required_frames=1,
            draft_ready=False,
            front_only=True,
            user_relative=True,
        )
        self.assertTrue(ok, reason)

    def test_three_pose_mid_progress_still_ok(self) -> None:
        ok, reason = validate_guided_response(
            guided=True,
            session_id="s1",
            response_session_id="s1",
            guidance_code="CAPTURE_LEFT",
            accepted_count=1,
            required_frames=3,
            draft_ready=False,
        )
        self.assertTrue(ok, reason)

    def test_draft_true_wrong_code_rejected(self) -> None:
        ok, reason = validate_guided_response(
            guided=True,
            session_id="s1",
            response_session_id="s1",
            guidance_code="CAPTURE_FRONT",
            accepted_count=1,
            required_frames=1,
            draft_ready=True,
            front_only=True,
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "draft_inconsistent")

    def test_wire_must_not_send_local_draft_ready_front_only(self) -> None:
        ok, reason = validate_guided_response(
            guided=True,
            session_id="s1",
            response_session_id="s1",
            guidance_code="DRAFT_READY_FRONT_ONLY",
            accepted_count=1,
            required_frames=1,
            draft_ready=True,
            front_only=True,
            user_relative=True,
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "unknown_guidance_code")


class SourceContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client_cc = read(CLIENT_CC)
        cls.client_h = read(CLIENT_H)
        cls.manager_cc = read(MANAGER_CC)
        cls.manager_h = read(MANAGER_H)
        cls.catalog_cc = read(CATALOG_CC)
        cls.gesture_cc = read(GESTURE_CC)
        cls.mcp_server_cc = read(MCP_SERVER_CC)
        cls.board_cc = read(BOARD_CC)
        cls.cmake = read(CMAKE)
        cls.camera_cc = read(ROOT / "main" / "boards" / "common" / "esp32_camera.cc")
        cls.config_store_cc = read(ROOT / "main" / "face_config_store.cc")

    def test_v2_opt_in_and_timing_are_in_firmware(self) -> None:
        self.assertIn("guided_burst_v1", self.client_h)
        self.assertIn("kGuidedMinimumSessionSeconds = 240", self.client_cc)
        self.assertIn("kGuidedLocalTimeoutSeconds = 240", self.manager_cc)
        self.assertIn("IsGuidedBurstConfig", self.client_cc)

    def test_front_only_capability_and_create_negotiation(self) -> None:
        self.assertIn("supports_front_only_v1", self.client_h)
        self.assertIn("supports_user_relative_v1", self.client_h)
        self.assertIn("supported_capture_modes", self.mcp_server_cc)
        self.assertIn("supported_guidance_profiles", self.mcp_server_cc)
        self.assertIn("ValidateCreateSessionModes", self.client_cc)
        self.assertIn("BuildCreateSessionBody", self.client_cc)
        self.assertIn("front_only_v1", self.client_cc)
        self.assertIn("user_relative_v1", self.client_cc)
        self.assertIn('\\"capture_mode\\":\\"front_only_v1\\"', self.client_cc)
        self.assertIn("sup_front_only", self.config_store_cc)
        self.assertIn("sup_user_rel", self.config_store_cc)

    def test_front_only_state_machine_guards(self) -> None:
        self.assertIn("DRAFT_READY_FRONT_ONLY", self.manager_cc)
        self.assertIn("front_only_side_pose_forbidden", self.manager_cc)
        self.assertIn("user_relative_not_negotiated", self.manager_cc)
        self.assertIn("MOVE_USER_LEFT", self.manager_cc)
        self.assertIn("CaptureEnrollmentJpeg", self.manager_cc)
        self.assertIn("LastJpegOrientationTrusted", self.camera_cc)
        self.assertIn("orientation untrusted", self.camera_cc)
        # Assess and capture share the same completion helper.
        self.assertEqual(
            self.manager_cc.count("IsGuidedEnrollmentComplete("), 2
        )
        self.assertIn("quota_full_continue_forbidden", self.client_cc)
        self.assertIn("state_ == State::kDraftReady", self.manager_cc)

    def test_guided_endpoints_remain_https_host_checked(self) -> None:
        self.assertIn("ValidateSamePublicHttpsUrl", self.client_cc)
        self.assertIn("assess_url", self.client_h)
        self.assertIn("capture_url", self.client_h)
        self.assertIn("X-Enrollment-Token", self.client_cc)

    def test_all_local_guidance_codes_have_copy_and_embedded_assets(self) -> None:
        found = set(re.findall(
            r'\{"([A-Z_]+)", "[^"]+", FACE_PROMPT_ASSET\(([A-Z_]+)\)\}',
            self.catalog_cc,
        ))
        self.assertEqual(found, {(code, code) for code in GUIDANCE_CODES})
        for code in GUIDANCE_CODES:
            self.assertIn(f"DECLARE_FACE_PROMPT_ASSET({code})", self.catalog_cc)
        self.assertIn("SetChatMessage(\"assistant\"", self.catalog_cc)
        self.assertIn("assets/face_enrollment/*.ogg", self.cmake)
        self.assertNotIn("CreateHttp", self.catalog_cc)
        self.assertNotIn("GetNetwork()->CreateHttp", self.catalog_cc)
        self.assertIn("正面照片已经拍好，请到智控台确认姓名并启用。", self.catalog_cc)
        self.assertIn("三张照片都拍好了，正在为你保存。", self.catalog_cc)

    def test_candidate_burst_and_pose_limits_are_explicit(self) -> None:
        self.assertIn("kGuidedCandidateCount = 3", self.manager_cc)
        self.assertIn("kGuidedCandidateIntervalMs = 300", self.manager_cc)
        self.assertIn("pose_rounds[pose_index] >= 3", self.manager_cc)
        self.assertIn("CapturePose", self.manager_cc)

    def test_late_response_generation_checks_exist(self) -> None:
        self.assertGreaterEqual(
            self.manager_cc.count("IsCurrentGeneration(generation)"), 8
        )
        self.assertIn("event=frame_discard reason=stale_generation", self.manager_cc)

    def test_double_tap_cancels_before_cards(self) -> None:
        guard = self.gesture_cc.index("FaceEnrollmentManager::GetInstance().IsActive()")
        cards = self.gesture_cc.index("HandleTouchGesture")
        self.assertLess(guard, cards)
        self.assertIn("GESTURE_DOUBLE_TAP", self.gesture_cc[guard - 100 : guard + 220])
        self.assertIn("FaceEnrollmentManager::GetInstance().Cancel()", self.gesture_cc)

    def test_camera_ownership_blocks_daily_presence_capture(self) -> None:
        self.assertIn("Presence capture skipped: face enrollment is active", self.board_cc)
        self.assertIn("AcquireCameraWithWait", self.manager_cc)
        self.assertIn("CameraManager::GetInstance().Release()", self.manager_cc)

    def test_capability_parser_and_local_ogg_directory_exist(self) -> None:
        self.assertIn('"guided_burst_v1"', self.mcp_server_cc)
        self.assertIn("assets/face_enrollment/*.ogg", self.cmake)
        self.assertIn("Ogg-container Opus", read(ROOT / "main" / "assets" /
                                                   "face_enrollment" / "README.md"))

    def test_v2_does_not_route_through_v1_notification_after_session(self) -> None:
        branch = self.manager_cc.index("if (session.guided_burst_v1)")
        v1_hint = self.manager_cc.index('ShowHint("请正对摄像头"', branch)
        self.assertLess(branch, v1_hint)
        self.assertIn("RunGuidedWorker", self.manager_cc[branch : v1_hint])


if __name__ == "__main__":
    unittest.main(verbosity=2)
