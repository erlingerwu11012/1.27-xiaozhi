"""Host-side regression for OTA bootstrap TLS-retry + validated WSS cache.

Covers:
- Wi-Fi settle window + temporary modem PS hold/restore
- Structured OTA_BOOT attempts with real 2/4/8s backoff (max 4)
- Validated websocket snapshot write/read rules (wss + token + valid)
- Device-auth OTA bootstrap headers and terminal credential clearing
- No empty-MQTT fallback; no TLS/URL weakening
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WIFI_BOARD = ROOT / "main" / "boards" / "common" / "wifi_board.cc"
APPLICATION = ROOT / "main" / "application.cc"
OTA_CC = ROOT / "main" / "ota.cc"
OTA_H = ROOT / "main" / "ota.h"
BOARD_H = ROOT / "main" / "boards" / "common" / "board.h"
SDKCONFIG_DEFAULTS = ROOT / "sdkconfig.defaults"
DIRECT_IP = ROOT / "main" / "realecho_dev_direct_ip.cc"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


# --- Mirror of firmware snapshot validation (host) ---

SCHEMA_VERSION = 1


def is_valid_wss_url(url: str) -> bool:
    return bool(url) and url.lower().startswith("wss://") and len(url) > 6


def snapshot_is_usable(fields: dict) -> bool:
    if not fields.get("valid"):
        return False
    if fields.get("schema") != SCHEMA_VERSION:
        return False
    url = fields.get("url") or ""
    token = fields.get("token") or ""
    return is_valid_wss_url(url) and bool(token)


def extract_ws_fields(websocket: dict) -> dict | None:
    url = websocket.get("url")
    token = websocket.get("token")
    if not isinstance(url, str) or not isinstance(token, str):
        return None
    if not is_valid_wss_url(url) or not token:
        return None
    version = websocket.get("version", 1)
    if isinstance(version, str):
        try:
            version = int(version)
        except ValueError:
            version = 1
    if not isinstance(version, int) or version <= 0:
        version = 1
    return {"url": url, "token": token, "version": version}


def is_valid_opaque_device_credential(value: str, min_length: int = 40) -> bool:
    return (
        min_length <= len(value) <= 128
        and all(ch.isascii() and (ch.isalnum() or ch in "-_") for ch in value)
    )


def ota_auth_headers(device_auth_key: str, bootstrap_code: str, wss_token: str) -> dict:
    """Mirror the firmware rule: a WSS access token never refreshes itself."""
    del wss_token
    if is_valid_opaque_device_credential(device_auth_key):
        return {"Authorization": f"Bearer {device_auth_key}"}
    if is_valid_opaque_device_credential(bootstrap_code):
        return {"X-Activation-Code": bootstrap_code}
    return {}


class ValidatedSnapshotLogic(unittest.TestCase):
    def test_accepts_wss_with_token(self):
        fields = extract_ws_fields(
            {"url": "wss://www.realecho.cn/ws", "token": "abc", "version": 2}
        )
        self.assertIsNotNone(fields)
        snap = {"schema": SCHEMA_VERSION, "valid": True, **fields}
        self.assertTrue(snapshot_is_usable(snap))

    def test_rejects_http_ws_empty_token(self):
        self.assertIsNone(extract_ws_fields({"url": "https://x/ws", "token": "t"}))
        self.assertIsNone(extract_ws_fields({"url": "ws://x/ws", "token": "t"}))
        self.assertIsNone(extract_ws_fields({"url": "wss://x/ws", "token": ""}))
        self.assertIsNone(extract_ws_fields({"url": "wss://x/ws"}))

    def test_rejects_half_written_snapshot(self):
        self.assertFalse(
            snapshot_is_usable(
                {
                    "schema": SCHEMA_VERSION,
                    "valid": False,
                    "url": "wss://www.realecho.cn/ws",
                    "token": "abc",
                }
            )
        )


class DeviceAuthBootstrapModel(unittest.TestCase):
    DEVICE_AUTH_KEY = "A" * 43
    BOOTSTRAP_CODE = "b" * 43
    WSS_TOKEN = "v2.signature.1.2.3"

    def test_device_auth_key_is_the_only_normal_refresh_authority(self):
        headers = ota_auth_headers(self.DEVICE_AUTH_KEY, self.BOOTSTRAP_CODE, self.WSS_TOKEN)
        self.assertEqual(headers, {"Authorization": f"Bearer {self.DEVICE_AUTH_KEY}"})

    def test_one_time_bootstrap_is_used_only_without_device_auth_key(self):
        headers = ota_auth_headers("", self.BOOTSTRAP_CODE, self.WSS_TOKEN)
        self.assertEqual(headers, {"X-Activation-Code": self.BOOTSTRAP_CODE})

    def test_wss_token_never_becomes_an_ota_authorization_header(self):
        headers = ota_auth_headers("", "", self.WSS_TOKEN)
        self.assertEqual(headers, {})

    def test_rejects_malformed_or_short_stored_credentials(self):
        self.assertEqual(ota_auth_headers("bad key", self.BOOTSTRAP_CODE, self.WSS_TOKEN),
                         {"X-Activation-Code": self.BOOTSTRAP_CODE})
        self.assertEqual(ota_auth_headers("", "too-short", self.WSS_TOKEN), {})
        self.assertFalse(
            snapshot_is_usable(
                {
                    "schema": SCHEMA_VERSION,
                    "valid": True,
                    "url": "wss://www.realecho.cn/ws",
                    "token": "",
                }
            )
        )
        self.assertFalse(
            snapshot_is_usable(
                {
                    "schema": 0,
                    "valid": True,
                    "url": "wss://www.realecho.cn/ws",
                    "token": "abc",
                }
            )
        )


class SourceContracts(unittest.TestCase):
    def test_always_on_wifi_no_network_hold(self):
        text = read(WIFI_BOARD)
        self.assertIn("WIFI_PS_NONE", text)
        self.assertNotIn("WIFI_PS_MIN_MODEM", text)
        self.assertNotIn("BeginOtaBootstrapHold", text)
        self.assertNotIn("EndOtaBootstrapHold", text)
        self.assertNotIn("event=network_hold", text)
        self.assertNotIn("kOtaBootstrapSettleMs", text)
        self.assertIn("OtaTlsDiag::NoteWifiGotIp", text)

    def test_board_hooks_removed(self):
        text = read(BOARD_H)
        self.assertNotIn("BeginOtaBootstrapHold", text)
        self.assertNotIn("EndOtaBootstrapHold", text)

    def test_ota_retry_structure(self):
        text = read(APPLICATION)
        self.assertIn("kMaxBootstrapAttempts = 4", text)
        self.assertIn("kBackoffAfterFailSec[] = {2, 4, 8}", text)
        self.assertIn('[OTA_BOOT] event=attempt index=%d', text)
        self.assertIn('[OTA_BOOT] event=result index=%d ok=0 reason=%s', text)
        self.assertIn('[OTA_BOOT] event=result index=%d ok=1 websocket_config=%d', text)
        self.assertIn("RestoreValidatedWebsocketSnapshot", text)
        self.assertIn("NETWORK_UNAVAILABLE_RETRYING", text)
        self.assertNotIn("EndOtaBootstrapHold", text)
        # Must not fall back to empty MQTT
        self.assertNotIn("No protocol specified in the OTA config, using MQTT", text)
        self.assertIn("refusing_empty_mqtt", text)

    def test_ota_cache_and_observability(self):
        text = read(OTA_CC)
        self.assertIn('kWsCacheNs = "ws_vcache"', text)
        self.assertIn("MirrorPersistedCredential", text)
        self.assertIn("RestoreValidatedWebsocketSnapshot", text)
        self.assertIn("tls_open_failed", text)
        self.assertIn("event=config_parsed", text)
        self.assertIn("event=config_fallback source=validated_cache", text)
        self.assertIn("IsValidWssUrl", text)
        # Never log token values in OTA_BOOT lines
        for line in text.splitlines():
            if "[OTA_BOOT]" in line and "token=" in line.lower():
                self.assertIn("token_len", line)
                self.assertNotRegex(line, r'token=%s')

    def test_device_auth_bootstrap_source_contract(self):
        text = read(OTA_CC)
        auth = read(ROOT / "main" / "auth_connection.cc")
        self.assertIn('http->SetHeader("Authorization", authorization.c_str())', text)
        self.assertIn('http->SetHeader("X-Activation-Code", choice.activation_code.c_str())', text)
        self.assertIn('http->SetHeader("X-Pairing-Secret", choice.pairing_secret.c_str())', text)
        self.assertIn('http->SetHeader("X-Auth-Confirm", "1")', text)
        self.assertIn('http->SetHeader("X-Session-Id", choice.session_id.c_str())', text)
        self.assertNotIn("else if (choice.kind == authconn::HeaderKind::kRedeemCode", text)
        self.assertIn('active.EraseKey("auth_key")', auth)
        self.assertIn('activation.EraseKey("bootstrap_code")', auth)
        self.assertIn("ApplyPersistedHttp", text)
        self.assertIn("pairing_required", auth)
        self.assertIn("recovery_required", auth)
        protocol = read(ROOT / "main" / "protocols" / "websocket_protocol.cc")
        self.assertIn('strcmp(code->valuestring, "device_unbound")', protocol)
        self.assertIn('strcmp(code->valuestring, "token_expired")', protocol)
        self.assertIn("opened_credential_epoch_", protocol)
        app = read(APPLICATION)
        self.assertIn("WaitForCredentialRelease", app)
        self.assertIn("kWaitPairing", app)
        self.assertIn("kWaitRecovery", app)
        self.assertIn("kShowDisabled", app)

    def test_ota_header_api(self):
        text = read(OTA_H)
        self.assertIn("GetLastCheckReason", text)
        self.assertIn("RestoreValidatedWebsocketSnapshot", text)
        self.assertIn("HasValidatedWebsocketSnapshot", text)

    def test_tls_and_url_not_weakened(self):
        defaults = read(SDKCONFIG_DEFAULTS)
        self.assertIn("https://api.realecho.cn/xiaozhi/ota/", defaults)
        self.assertNotIn("http://121.40.239.140", defaults)

        ota = read(OTA_CC)
        self.assertNotIn("skip_cert", ota.lower())
        self.assertNotIn("CRT_BUNDLE_ATTACH_NONE", ota)

        app = read(APPLICATION)
        self.assertNotIn("skip_cert", app.lower())

        if DIRECT_IP.exists():
            dip = read(DIRECT_IP)
            # Direct-IP must keep logical hostname for SNI (no URL rewrite helpers)
            self.assertNotIn("skip_cert_common_name_check", dip.lower())


class RetryBackoffModel(unittest.TestCase):
    """Document expected attempt timing: 4 attempts, delays 2/4/8 between them."""

    def test_backoff_schedule(self):
        max_attempts = 4
        backoff = [2, 4, 8]
        self.assertEqual(len(backoff), max_attempts - 1)
        # Attempt indices 1..4; wait only after failures before last
        waits = []
        for index in range(1, max_attempts + 1):
            if index < max_attempts:
                waits.append(backoff[index - 1])
        self.assertEqual(waits, [2, 4, 8])
        # Total bootstrap wait budget (excluding network RTT): 14s
        self.assertEqual(sum(waits), 14)


class ProductionStateMachine(unittest.TestCase):
    def test_host_binary_covers_real_vault(self):
        import subprocess
        import sys
        subprocess.run(
            [sys.executable, str(ROOT / "tools" / "run_auth_connection_host_test.py")],
            check=True,
        )


class ProtocolSelectionModel(unittest.TestCase):
    def select(self, has_mqtt: bool, has_ws: bool, cache_ok: bool) -> str:
        if has_mqtt:
            return "mqtt"
        if has_ws:
            return "websocket"
        if cache_ok:
            return "websocket_cache"
        return "retry_no_empty_mqtt"

    def test_network_ws_after_retry_success(self):
        self.assertEqual(self.select(False, True, False), "websocket")

    def test_cache_when_all_ota_fail(self):
        self.assertEqual(self.select(False, False, True), "websocket_cache")

    def test_no_cache_no_empty_mqtt(self):
        self.assertEqual(self.select(False, False, False), "retry_no_empty_mqtt")


if __name__ == "__main__":
    unittest.main()
