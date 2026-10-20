"""Source integration checks for WS cleanup and wake preroll.

Runtime send tests execute production C++ via run_ws_audio_send_host_test.py.
"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WS_PROTOCOL_CC = ROOT / "main" / "protocols" / "websocket_protocol.cc"
WS_PROTOCOL_H = ROOT / "main" / "protocols" / "websocket_protocol.h"
APPLICATION_CC = ROOT / "main" / "application.cc"
ESP_NETWORK = ROOT / "main" / "esp_network.h"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


# Runtime behavior is tested by run_ws_audio_send_host_test.py.

# --- Source contracts (assert the actual firmware code) ---

class SourceContracts(unittest.TestCase):
    def test_send_audio_has_controlled_fatal_failure(self):
        text = read(WS_PROTOCOL_CC)
        self.assertIn("HandleAudioSendFailure()", text)

    def test_handle_failure_releases_before_set_error(self):
        text = read(WS_PROTOCOL_CC)
        self.assertIn("void WebsocketProtocol::HandleAudioSendFailure()", text)
        body = text.split("void WebsocketProtocol::HandleAudioSendFailure()", 1)[1]
        self.assertIn("CloseAudioChannel()", body)
        self.assertIn("SetError(Lang::Strings::SERVER_ERROR)", body)
        # Release must precede the error publication.
        self.assertLess(body.index("CloseAudioChannel()"),
                        body.index("SetError(Lang::Strings::SERVER_ERROR)"))
        # Error callback fires exactly once per episode.
        self.assertIn("if (!error_occurred_)", body)
        # Transient path must exist and avoid immediate close.
        self.assertIn("WasLastSendTransient", text)
        self.assertIn("transient_send_fail", text)
        self.assertIn("fail_class=%s", text)
        self.assertIn("LastSendTransientClass", text)

    def test_not_started_classes_split_lock_and_writable(self):
        header = read(ROOT / "components/esp_websocket_client/include/esp_websocket_client.h")
        client = read(ROOT / "components/esp_websocket_client/esp_websocket_client.c")
        network = read(ESP_NETWORK)
        self.assertIn("#define ESP_WEBSOCKET_CLIENT_SEND_NOT_STARTED (-2)", header)
        self.assertIn("#define ESP_WEBSOCKET_CLIENT_SEND_TX_LOCK_TIMEOUT (-3)", header)
        self.assertIn("ESP_WEBSOCKET_CLIENT_SEND_TX_LOCK_TIMEOUT", client)
        self.assertIn("tx_lock_timeout", network)
        self.assertIn("socket_not_writable", network)
        self.assertIn("fail_for_ms", network)
        self.assertIn("last_tx_age_ms", network)

    def test_helper_declared_in_header(self):
        text = read(WS_PROTOCOL_H)
        self.assertIn("void HandleAudioSendFailure();", text)

    def test_wake_preroll_both_entry_points_stop_on_failure(self):
        text = read(APPLICATION_CC)
        # The two public wake entry points delegate to one common flow.  Keep
        # the send-failure guard in that shared implementation so the paths
        # cannot drift apart again.
        self.assertEqual(text.count("wake_preroll_send_failed sent_frames=%d"), 1)
        self.assertEqual(text.count("if (!protocol_->SendAudio(std::move(packet)))"), 1)
        self.assertIn("CompleteWakeWordFlow(audio_service_.GetLastWakeWord())", text)
        self.assertIn("CompleteWakeWordFlow(wake_word)", text)
        # On failure the loop must return before the detect control message.
        self.assertIn("return;", text)
        # The shared success path still sends one detect control message.
        self.assertEqual(text.count("protocol_->SendWakeWordDetected(wake_word);"), 1)

    def test_tls_and_control_timeout_unchanged(self):
        text = read(ESP_NETWORK)
        self.assertIn("crt_bundle_attach = esp_crt_bundle_attach", text)
        self.assertNotIn("skip_cert_common_name_check = true", text)
        # Control-plane send keeps its original 5s timeout.
        self.assertIn("kControlSendTimeoutMs = 5000", text)


if __name__ == "__main__":
    unittest.main()
