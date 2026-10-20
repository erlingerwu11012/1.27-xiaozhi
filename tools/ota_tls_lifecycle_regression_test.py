"""Host regression for EspHttp POST lifecycle + always-on Wi-Fi + OTA gate."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ESP_NETWORK = ROOT / "main" / "esp_network.h"
OTA_CC = ROOT / "main" / "ota.cc"
OTA_DIAG = ROOT / "main" / "ota_tls_diag.cc"
WIFI_BOARD = ROOT / "main" / "boards" / "common" / "wifi_board.cc"
WIFI_BOARD_H = ROOT / "main" / "boards" / "common" / "wifi_board.h"
BOARD_H = ROOT / "main" / "boards" / "common" / "board.h"
APPLICATION = ROOT / "main" / "application.cc"
KCONFIG = ROOT / "main" / "Kconfig.projbuild"


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


class EspHttpPostLifecycle(unittest.TestCase):
    def test_no_set_post_field_with_manual_write(self):
        text = read(ESP_NETWORK)
        self.assertNotRegex(text, r"esp_http_client_set_post_field\s*\(")
        self.assertIn("Do NOT call set_post_field here", text)
        self.assertIn("esp_http_client_open(client_, write_len)", text)
        self.assertIn("esp_http_client_write(client_, content_.c_str() + written", text)
        self.assertIn("short write", text)
        self.assertIn("esp_http_client_get_and_clear_last_tls_error", text)
        self.assertIn("crt_bundle_attach", text)
        self.assertNotRegex(text, r"skip_cert_common_name_check\s*=\s*true")

    def test_event_handler_no_data_cast(self):
        text = read(ESP_NETWORK)
        self.assertIn("HTTP_EVENT_ERROR", text)
        self.assertNotIn("evt->data)", text)
        self.assertNotIn("(esp_tls_error_handle_t)evt", text)


class AlwaysOnWifiPower(unittest.TestCase):
    def test_no_ota_network_hold(self):
        for path in (WIFI_BOARD, WIFI_BOARD_H, BOARD_H, APPLICATION):
            text = read(path)
            self.assertNotIn("BeginOtaBootstrapHold", text)
            self.assertNotIn("EndOtaBootstrapHold", text)
            self.assertNotIn("ota_bootstrap_hold_active_", text)
            self.assertNotIn("network_hold", text)
            self.assertNotIn("kOtaBootstrapSettleMs", text)

    def test_wifi_ps_none_only(self):
        text = read(WIFI_BOARD)
        self.assertIn("WIFI_PS_NONE", text)
        self.assertNotIn("WIFI_PS_MIN_MODEM", text)
        self.assertIn("设备为外接电源产品，禁止启用 Wi‑Fi power save", text)
        self.assertIn("OtaTlsDiag::NoteWifiGotIp", text)
        # NoteWifiGotIp must not be followed by a settle delay API
        self.assertNotRegex(
            text,
            r"NoteWifiGotIp\(\);\s*\n\s*vTaskDelay\(pdMS_TO_TICKS\(1500\)\)",
        )

    def test_set_power_save_forced_none(self):
        text = read(WIFI_BOARD)
        self.assertRegex(
            text,
            r"void WifiBoard::SetPowerSaveMode\(bool[^\)]*\)\s*\{[^}]*WIFI_PS_NONE",
        )


class OtaAttemptGate(unittest.TestCase):
    def test_gate_and_probe_present(self):
        ota = read(OTA_CC)
        self.assertIn("OtaTlsDiag::BeginAttempt", ota)
        self.assertIn("OtaTlsDiag::EndAttempt", ota)
        self.assertIn("RunPureTlsProbe", ota)
        self.assertIn("#if CONFIG_REALECHO_OTA_TLS_PROBE", ota)
        self.assertIn("gate_timeout", ota)

        diag = read(OTA_DIAG)
        self.assertIn("overlap_rejected", diag)
        self.assertIn("esp_tls_conn_new_sync", diag)
        self.assertIn("esp_crt_bundle_attach", diag)
        self.assertIn("[OTA_TLS]", diag)

    def test_sdkconfig_probe_disabled_for_baseline(self):
        sdk = (ROOT / "sdkconfig").read_text(encoding="utf-8", errors="replace")
        self.assertIn("# CONFIG_REALECHO_OTA_TLS_PROBE is not set", sdk)
        self.assertIn('CONFIG_OTA_URL="https://api.realecho.cn/xiaozhi/ota/"', sdk)
        self.assertFalse((ROOT / "sdkconfig.defaults.realecho-direct-ip").exists())
        self.assertFalse((ROOT / "main" / "realecho_dev_direct_ip.cc").exists())

    def test_kconfig_dev_gated(self):
        text = read(KCONFIG)
        self.assertIn("REALECHO_OTA_TLS_DIAG", text)
        self.assertIn("REALECHO_OTA_TLS_PROBE", text)
        self.assertIn("default n", text)


class SecurityContracts(unittest.TestCase):
    def test_no_tls_weakening(self):
        for path in (ESP_NETWORK, OTA_CC, OTA_DIAG):
            text = read(path).lower()
            self.assertNotIn("skip_cert_common_name_check = true", text)
            self.assertNotIn("http://121.40.239.140", text)
        esp = read(ESP_NETWORK)
        self.assertIn("crt_bundle_attach = esp_crt_bundle_attach", esp)


if __name__ == "__main__":
    unittest.main()
