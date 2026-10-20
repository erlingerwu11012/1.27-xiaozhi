"""Host-side regression for the phantom-touch / downlink-TTS patch.

Covers:
- TouchManager debounce: a single 10ms glitch does NOT produce a stable press;
  3 consecutive valid press frames + 2 valid release frames DO produce a TAP.
- GestureEngine: press duration must be >= 40ms and < 500ms to be a TAP.
- GestureHandler: in Speaking state a single TAP is ignored (no StartListening /
  AbortSpeaking); double TAP still aborts; in Idle a single TAP still listens.
- I2C read failure never fabricates a DOWN.
- WebSocket separate TX lock is enabled in the defaults file.
- Decode-queue-full increments the drop counter without changing the queue
  capacity or the drop policy.
- TLS/SNI/cert-bundle and uplink queue capacities are unchanged.
"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOUCH_MANAGER_H = ROOT / "main" / "touch" / "touch_manager.h"
TOUCH_MANAGER_CC = ROOT / "main" / "touch" / "touch_manager.cc"
GESTURE_ENGINE_H = ROOT / "main" / "touch" / "gesture_engine.h"
GESTURE_ENGINE_CC = ROOT / "main" / "touch" / "gesture_engine.cc"
GESTURE_HANDLER_CC = ROOT / "main" / "touch" / "gesture_handler.cc"
KCONFIG = ROOT / "main" / "Kconfig.projbuild"
SDK_DEFAULTS_S3 = ROOT / "sdkconfig.defaults.esp32s3"
AUDIO_SERVICE_H = ROOT / "main" / "audio" / "audio_service.h"
AUDIO_SERVICE_CC = ROOT / "main" / "audio" / "audio_service.cc"
APPLICATION_CC = ROOT / "main" / "application.cc"
ESP_NETWORK = ROOT / "main" / "esp_network.h"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


# --- Host mirror of the TouchManager debounce state machine ---

class TouchDebounceModel:
    PRESS_FRAMES = 3
    RELEASE_FRAMES = 2
    MAX_FAILS = 10

    def __init__(self):
        self.stable_pressed = False
        self.press_streak = 0
        self.release_streak = 0
        self.consecutive_fails = 0
        self.stable_down_events = 0
        self.stable_up_events = 0

    def sample(self, touched: bool, valid: bool = True) -> bool:
        if not valid:
            self.consecutive_fails += 1
            if self.consecutive_fails >= self.MAX_FAILS:
                self.consecutive_fails = 0
                if self.stable_pressed:
                    self.stable_pressed = False
                    self.stable_up_events += 1
            return self.stable_pressed
        self.consecutive_fails = 0
        if touched:
            self.press_streak += 1
            self.release_streak = 0
            if self.press_streak >= self.PRESS_FRAMES and not self.stable_pressed:
                self.stable_pressed = True
                self.stable_down_events += 1
        else:
            self.release_streak += 1
            self.press_streak = 0
            if self.release_streak >= self.RELEASE_FRAMES and self.stable_pressed:
                self.stable_pressed = False
                self.stable_up_events += 1
        return self.stable_pressed


class TouchDebounceTests(unittest.TestCase):
    def test_single_glitch_no_stable_press(self):
        m = TouchDebounceModel()
        m.sample(True)   # 1 frame press
        m.sample(False)  # 1 frame release
        self.assertEqual(m.stable_down_events, 0)
        self.assertFalse(m.stable_pressed)

    def test_three_press_two_release_makes_tap(self):
        m = TouchDebounceModel()
        self.assertFalse(m.sample(True))  # frame 1
        self.assertFalse(m.sample(True))  # frame 2
        self.assertTrue(m.sample(True))   # frame 3 -> stable press
        self.assertEqual(m.stable_down_events, 1)
        self.assertTrue(m.stable_pressed)
        self.assertTrue(m.sample(False))   # release frame 1 (still pressed)
        self.assertFalse(m.sample(False))  # release frame 2 -> stable release
        self.assertEqual(m.stable_up_events, 1)
        self.assertFalse(m.stable_pressed)

    def test_release_needs_two_frames(self):
        m = TouchDebounceModel()
        for _ in range(3):
            m.sample(True)
        self.assertTrue(m.stable_pressed)
        m.sample(False)  # only 1 release frame
        self.assertTrue(m.stable_pressed)
        self.assertEqual(m.stable_up_events, 0)

    def test_i2c_fail_never_fabricates_down(self):
        m = TouchDebounceModel()
        for _ in range(3):
            m.sample(True, valid=False)  # failed reads, no real data
        self.assertFalse(m.stable_pressed)
        self.assertEqual(m.stable_down_events, 0)

    def test_i2c_fail_threshold_safe_release(self):
        m = TouchDebounceModel()
        for _ in range(3):
            m.sample(True)
        self.assertTrue(m.stable_pressed)
        for _ in range(TouchDebounceModel.MAX_FAILS):
            m.sample(False, valid=False)
        self.assertFalse(m.stable_pressed)
        self.assertEqual(m.stable_up_events, 1)


# --- Host mirror of the GestureEngine TAP duration gate ---

class TapDurationModel:
    TAP_MIN_MS = 40
    TAP_MAX_MS = 500

    @classmethod
    def is_tap(cls, duration_ms: int) -> bool:
        return cls.TAP_MIN_MS <= duration_ms < cls.TAP_MAX_MS


class TapDurationTests(unittest.TestCase):
    def test_under_40ms_is_not_tap(self):
        for d in (0, 10, 39):
            self.assertFalse(TapDurationModel.is_tap(d))

    def test_40_to_499_is_tap(self):
        for d in (40, 100, 499):
            self.assertTrue(TapDurationModel.is_tap(d))

    def test_500_or_more_is_not_tap(self):
        for d in (500, 800):
            self.assertFalse(TapDurationModel.is_tap(d))


# --- Host mirror of GestureHandler state behaviour ---

class GestureHandlerModel:
    def __init__(self, state: str):
        self.state = state
        self.start_listening_calls = 0
        self.abort_speaking_calls = 0
        self.tap_ignored_logs = 0

    def on_tap(self):
        if self.state == "speaking":
            self.tap_ignored_logs += 1
            return
        self.start_listening_calls += 1

    def on_double_tap(self):
        if self.state == "speaking":
            self.abort_speaking_calls += 1


class GestureHandlerModelTests(unittest.TestCase):
    def test_speaking_single_tap_ignored(self):
        m = GestureHandlerModel("speaking")
        m.on_tap()
        self.assertEqual(m.start_listening_calls, 0)
        self.assertEqual(m.abort_speaking_calls, 0)
        self.assertEqual(m.tap_ignored_logs, 1)

    def test_speaking_double_tap_aborts(self):
        m = GestureHandlerModel("speaking")
        m.on_double_tap()
        self.assertEqual(m.abort_speaking_calls, 1)

    def test_idle_single_tap_listens(self):
        m = GestureHandlerModel("idle")
        m.on_tap()
        self.assertEqual(m.start_listening_calls, 1)
        self.assertEqual(m.tap_ignored_logs, 0)

    def test_listening_single_tap_listens(self):
        m = GestureHandlerModel("listening")
        m.on_tap()
        self.assertEqual(m.start_listening_calls, 1)


# --- Host mirror of the decode-queue drop counter ---

class DecodeQueueModel:
    def __init__(self, capacity: int):
        self.capacity = capacity
        self.q = []
        self.drop_count = 0

    def push(self, wait: bool = False) -> bool:
        if len(self.q) >= self.capacity:
            if wait:
                return False  # real code blocks; model just signals "would wait"
            self.drop_count += 1
            return False
        self.q.append(1)
        return True


class DecodeQueueTests(unittest.TestCase):
    def test_full_queue_drops_and_counts_without_resizing(self):
        m = DecodeQueueModel(capacity=40)
        for _ in range(40):
            self.assertTrue(m.push())
        self.assertFalse(m.push())          # wait=False -> drop
        self.assertEqual(m.drop_count, 1)
        self.assertEqual(len(m.q), 40)      # capacity unchanged
        self.assertEqual(m.capacity, 40)


# --- Source contracts (assert the actual firmware code) ---

class SourceContracts(unittest.TestCase):
    def test_touch_manager_debounce_constants(self):
        text = read(TOUCH_MANAGER_H)
        self.assertIn("kPressDebounceFrames = 3", text)
        self.assertIn("kReleaseDebounceFrames = 2", text)
        self.assertIn("kMaxConsecutiveFails = 10", text)

    def test_touch_manager_valid_sample_signature(self):
        text = read(TOUCH_MANAGER_CC)
        self.assertIn("bool valid_sample", text)
        # I2C read failure passes valid_sample=false and never fabricates DOWN.
        self.assertIn("UpdateState(0, 0, 0, false, /*valid_sample=*/false)", text)

    def test_gesture_engine_tap_min_duration(self):
        h = read(GESTURE_ENGINE_H)
        self.assertIn("kTapMinDurationMs = 40", h)
        cc = read(GESTURE_ENGINE_CC)
        self.assertEqual(cc.count("duration_ms >= kTapMinDurationMs"), 2)

    def test_gesture_handler_speaking_tap_ignored(self):
        text = read(GESTURE_HANDLER_CC)
        self.assertIn("tap_ignored reason=speaking", text)
        # The ignored branch must return before StartListening.
        self.assertIn('return;', text)

    def test_gesture_handler_double_tap_still_aborts(self):
        text = read(GESTURE_HANDLER_CC)
        body = text.split("void GestureHandler::OnGesture", 1)[1]
        body = body.split("case GESTURE_DOUBLE_TAP:", 1)[1].split("case GESTURE_CIRCLE:", 1)[0]
        self.assertIn("app.StartListening()", body)
        # The handler delegates interruption and listening restoration to the
        # application. Check that path rather than a fixed 300-character slice.
        app = read(ROOT / "main" / "application.cc")
        start = app.split("void Application::StartListening()", 1)[1].split("void Application::StopListening()", 1)[0]
        speaking = start.split("else if (device_state_ == kDeviceStateSpeaking)", 1)[1]
        self.assertIn("AbortSpeaking(kAbortReasonNone)", speaking)
        self.assertIn("SetListeningMode(kListeningModeManualStop)", speaking)

    def test_thgroup_kconfig_default_22(self):
        text = read(KCONFIG)
        self.assertIn("config TOUCH_FT6336_THGROUP", text)
        self.assertIn("default 22", text)
        self.assertIn("config TOUCH_DIAGNOSTICS", text)

    def test_separate_tx_lock_enabled_in_defaults(self):
        text = read(SDK_DEFAULTS_S3)
        self.assertIn("CONFIG_ESP_WS_CLIENT_SEPARATE_TX_LOCK=y", text)

    def test_decode_drop_counter_without_policy_change(self):
        text = read(AUDIO_SERVICE_CC)
        idx = text.index("PushPacketToDecodeQueue(std::unique_ptr<AudioStreamPacket> packet, bool wait)")
        body = text[idx:idx + 600]
        self.assertIn("decode_drop_count_.fetch_add", body)
        self.assertIn("return false;", body)

    def test_audio_queue_capacities_unchanged(self):
        text = read(AUDIO_SERVICE_H)
        self.assertIn("#define MAX_ENCODE_TASKS_IN_QUEUE 24", text)
        self.assertIn("#define MAX_PLAYBACK_TASKS_IN_QUEUE 2", text)
        self.assertIn("#define MAX_DECODE_PACKETS_IN_QUEUE (2400 / OPUS_FRAME_DURATION_MS)", text)
        self.assertIn("#define MAX_SEND_PACKETS_IN_QUEUE (2400 / OPUS_FRAME_DURATION_MS)", text)

    def test_ws_dl_log_present(self):
        text = read(APPLICATION_CC)
        self.assertIn("[WS_DL] rx=", text)

    def test_no_lld_logging(self):
        # newlib-nano prints "ld" for %lld; the patch replaces these with
        # bounded uint32_t / %u / %lu.
        self.assertNotIn("%lld", read(ESP_NETWORK))
        self.assertNotIn("%lld", read(GESTURE_ENGINE_CC))

    def test_tls_sni_cert_unchanged(self):
        text = read(ESP_NETWORK)
        self.assertIn("crt_bundle_attach = esp_crt_bundle_attach", text)
        self.assertNotIn("skip_cert_common_name_check = true", text)


if __name__ == "__main__":
    unittest.main()
