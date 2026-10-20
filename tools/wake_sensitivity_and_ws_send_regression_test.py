"""Host-side regression for wake-word sensitivity + WebSocket audio send fixes.

Covers:
- AFE WakeNet explicitly configured to DET_MODE_95 (Aggressive), not library default
- Kconfig WakeNet detection mode defaults to Aggressive
- WebSocket non-empty send: 0 / negative / short writes are all failures (no >= 0)
- Audio binary send uses a short, configurable timeout (default 500ms, not 5s)
- [WS_AUDIO] queue-pressure logging is rate-limited and prints no raw audio
- AUDIO_WAKE_DIAGNOSTICS is disabled by default and Kconfig-gated
- TLS / SNI / cert verification unchanged
"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ESP_NETWORK = ROOT / "main" / "esp_network.h"
WS_PROTOCOL_CC = ROOT / "main" / "protocols" / "websocket_protocol.cc"
APPLICATION_CC = ROOT / "main" / "application.cc"
AUDIO_SERVICE_CC = ROOT / "main" / "audio" / "audio_service.cc"
AUDIO_SERVICE_H = ROOT / "main" / "audio" / "audio_service.h"
AFE_WAKE_WORD_CC = ROOT / "main" / "audio" / "wake_words" / "afe_wake_word.cc"
KCONFIG = ROOT / "main" / "Kconfig.projbuild"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


# --- Host mirror of the firmware send-result semantics ---

def send_ok(sent: int, requested_len: int) -> bool:
    """Mirror of the firmware contract: exact write required for non-empty send."""
    return sent == requested_len


class SendResultModel(unittest.TestCase):
    def test_zero_return_is_failure(self):
        self.assertFalse(send_ok(0, 100))

    def test_negative_return_is_failure(self):
        self.assertFalse(send_ok(-1, 100))

    def test_short_write_is_failure(self):
        self.assertFalse(send_ok(50, 100))

    def test_exact_write_is_success(self):
        self.assertTrue(send_ok(100, 100))


class WakeNetModeContracts(unittest.TestCase):
    def test_afe_explicitly_sets_det_mode_95(self):
        text = read(AFE_WAKE_WORD_CC)
        self.assertIn("afe_config->wakenet_mode = DET_MODE_95", text)
        self.assertIn("afe_config->wakenet_mode = DET_MODE_90", text)
        # Must be gated by the Kconfig choice, not a hardcoded-only path.
        self.assertIn("CONFIG_WAKENET_DET_MODE_AGGRESSIVE", text)

    def test_afe_logs_config(self):
        text = read(AFE_WAKE_WORD_CC)
        self.assertIn("input_format=%s", text)
        self.assertIn("wakenet_mode=%s", text)

    def test_kconfig_defaults_aggressive(self):
        text = read(KCONFIG)
        self.assertIn("default WAKENET_DET_MODE_AGGRESSIVE", text)
        self.assertIn('bool "Aggressive (DET_MODE_95)"', text)
        self.assertIn('bool "Normal (DET_MODE_90)"', text)
        self.assertIn("depends on USE_AFE_WAKE_WORD", text)

    def test_kconfig_send_timeout_500ms(self):
        text = read(KCONFIG)
        self.assertIn("WS_AUDIO_SEND_TIMEOUT_MS", text)
        self.assertIn("default 500", text)
        self.assertIn("range 100 1000", text)

    def test_kconfig_diagnostics_default_off(self):
        text = read(KCONFIG)
        # The diagnostics switch defaults to n.
        self.assertIn("AUDIO_WAKE_DIAGNOSTICS", text)
        self.assertIn("default n", text)


class WebSocketSendContracts(unittest.TestCase):
    def test_no_nonempty_ge_zero_success(self):
        # The send path must not treat `>= 0` as success for non-empty writes.
        # EspWebSocket now centralizes that comparison in FinalizeSend so both
        # text and binary paths share the same short-write protection.  Scope
        # to WebSocket send lines only (Mqtt/Udp legitimately use >= 0).
        text = read(ESP_NETWORK)
        self.assertIn("const bool ok = FinalizeSend(sent, (int)len, send_errno);", text)
        self.assertIn("return FinalizeSend(sent, (int)text.size(), errno);", text)
        self.assertIn("if (sent == requested)", text)
        for line in text.splitlines():
            if "esp_websocket_client_send_" in line:
                self.assertNotIn(">= 0", line)

    def test_audio_send_uses_short_configurable_timeout(self):
        text = read(ESP_NETWORK)
        self.assertIn("pdMS_TO_TICKS(CONFIG_WS_AUDIO_SEND_TIMEOUT_MS)", text)
        # The old 5-second audio send timeout must be gone from the binary path.
        self.assertNotIn("pdMS_TO_TICKS(5000)", text)

    def test_control_text_keeps_longer_timeout(self):
        text = read(ESP_NETWORK)
        self.assertIn("kControlSendTimeoutMs", text)

    def test_ws_audio_log_rate_limited_and_fields(self):
        text = read(ESP_NETWORK)
        self.assertIn("[WS_AUDIO]", text)
        self.assertIn("requested_bytes", text)
        self.assertIn("returned_bytes", text)
        self.assertIn("elapsed_ms", text)
        self.assertIn("fail_class", text)
        self.assertIn("tx_lock_timeout", text)
        self.assertIn("socket_not_writable", text)
        self.assertIn("kMinWsAudioLogIntervalMs", text)
        self.assertIn("kSlowSendLogThresholdMs", text)

    def test_send_failure_triggers_error_recovery(self):
        text = read(WS_PROTOCOL_CC)
        self.assertIn("SetError(Lang::Strings::SERVER_ERROR)", text)

    def test_tls_not_weakened(self):
        text = read(ESP_NETWORK)
        self.assertIn("crt_bundle_attach = esp_crt_bundle_attach", text)
        self.assertNotIn("skip_cert_common_name_check = true", text)
        self.assertNotIn("use_global_ca_store = false", text)


class QueuePressureLogContracts(unittest.TestCase):
    def test_queue_log_rate_limited_and_fields(self):
        text = read(APPLICATION_CC)
        self.assertIn("[WS_AUDIO]", text)
        self.assertIn("encode_queue", text)
        self.assertIn("send_queue", text)
        self.assertIn("device_state", text)
        self.assertIn("pdMS_TO_TICKS(1000)", text)
        self.assertIn("GetQueueStats", text)

    def test_queue_stats_api_declared(self):
        text = read(AUDIO_SERVICE_H)
        self.assertIn("GetQueueStats", text)


class DiagnosticsContracts(unittest.TestCase):
    def test_diag_log_gated_by_kconfig(self):
        text = read(AUDIO_SERVICE_CC)
        self.assertIn("CONFIG_AUDIO_WAKE_DIAGNOSTICS", text)
        self.assertIn("[AUDIO_WAKE_DIAG]", text)

    def test_diag_log_rate_limited_1s(self):
        text = read(AUDIO_SERVICE_CC)
        self.assertIn("pdMS_TO_TICKS(1000)", text)

    def test_diag_logs_no_raw_pcm(self):
        # The [AUDIO_WAKE_DIAG] line only reports aggregated levels, never raw
        # PCM samples, Opus content, tokens, images or text.
        text = read(AUDIO_SERVICE_CC)
        diag_lines = [ln for ln in text.splitlines()
                      if "[AUDIO_WAKE_DIAG]" in ln and "ESP_LOGI" in ln]
        self.assertTrue(diag_lines, "expected at least one [AUDIO_WAKE_DIAG] line")
        for ln in diag_lines:
            self.assertIn("mic_avg", ln)
            self.assertIn("input_gain", ln)
            self.assertNotIn("data[", ln)
            self.assertNotIn("payload", ln)
            self.assertNotIn("pcm", ln.lower())


if __name__ == "__main__":
    unittest.main()
