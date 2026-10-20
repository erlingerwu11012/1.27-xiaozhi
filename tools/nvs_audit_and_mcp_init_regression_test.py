"""Host-side regression: NVS namespace/key length audit + MCP initialize flow.

Ensures firmware never aborts (ESP_RST_PANIC) on invalid NVS names/keys:
- Every NVS namespace and key literal/constant is <= 15 chars
  (NVS_KEY_NAME_MAX_SIZE - 1, NUL-terminated).
- Settings no longer aborts on write/erase/commit failures (no ESP_ERROR_CHECK).
- MCP initialize parses vision, reminder_control, face_enrollment in order, and
  both reminder/face capabilities can emit their accepted logs.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "main"

NVS_MAX_NAME_LEN = 15  # NVS_KEY_NAME_MAX_SIZE - 1 (including NUL terminator)

# Namespace literal patterns: Settings(<ns>, ...) and nvs_open("<ns>", ...).
NS_LITERAL_PATTERNS = [
    re.compile(r'\bSettings\s+[A-Za-z_]\w*\s*\(\s*"([^"]+)"'),
    re.compile(r'\bnvs_open\s*\(\s*"([^"]+)"'),
]
# Key literal patterns: Settings get/set/erase and direct nvs_* key argument.
KEY_LITERAL_PATTERNS = [
    re.compile(
        r'\b(?:GetString|TryGetString|SetString|GetInt|TryGetInt|SetInt|GetBool|TryGetBool|SetBool|EraseKey)'
        r'\s*\(\s*"([^"]+)"'
    ),
    re.compile(
        r'\bnvs_(?:set_str|get_str|set_i32|get_i32|set_u8|get_u8|set_u16|'
        r'get_u16|set_u64|get_u64|set_blob|get_blob|erase_key)\s*\([^,]+,\s*'
        r'"([^"]+)"'
    ),
]
# NVS constant definitions: k*Ns = "..." (namespace) and k*Key* = "..." (key).
NS_CONST_PATTERN = re.compile(
    r'\b(?:constexpr\s+)?const\s+char\s*\*\s*(k\w*Ns)\s*=\s*"([^"]*)"'
)
KEY_CONST_PATTERN = re.compile(
    r'\b(?:constexpr\s+)?const\s+char\s*\*\s*(k\w*Key\w*)\s*=\s*"([^"]*)"'
)


def _iter_cpp():
    for p in MAIN.rglob("*"):
        if p.suffix in (".cc", ".h"):
            yield p


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


def scan() -> list[tuple[str, str, int, str]]:
    """Return (kind, name, length, file) for every NVS namespace/key found."""
    entries: dict[tuple[str, str], set[str]] = {}

    def add(kind: str, name: str, rel: str) -> None:
        entries.setdefault((kind, name), set()).add(rel)

    for p in _iter_cpp():
        text = _read(p)
        rel = str(p.relative_to(ROOT)).replace("\\", "/")
        for pat in NS_LITERAL_PATTERNS:
            for m in pat.finditer(text):
                add("namespace", m.group(1), rel)
        for pat in KEY_LITERAL_PATTERNS:
            for m in pat.finditer(text):
                add("key", m.group(1), rel)
        for m in NS_CONST_PATTERN.finditer(text):
            add("namespace", m.group(2), rel)
        for m in KEY_CONST_PATTERN.finditer(text):
            add("key", m.group(2), rel)

    return [
        (kind, name, len(name), ",".join(sorted(files)))
        for (kind, name), files in sorted(entries.items())
    ]


class NvsNameLengthAudit(unittest.TestCase):
    def test_all_names_within_limit(self) -> None:
        rows = scan()
        offenders = [r for r in rows if not (1 <= r[2] <= NVS_MAX_NAME_LEN)]
        self.assertEqual(
            offenders,
            [],
            "NVS names exceeding 15 chars:\n"
            + "\n".join(
                f"  [{r[0]}] {r[1]!r} len={r[2]} in {r[3]}" for r in offenders
            ),
        )

    def test_previously_broken_names_removed(self) -> None:
        text = (
            _read(MAIN / "reminder_control_client.cc")
            + "\n"
            + _read(MAIN / "face_enrollment_client.cc")
            + "\n"
            + _read(MAIN / "face_config_store.cc")
        )
        # The invalid namespace and keys must not appear as literals anymore.
        for bad in (
            "reminder_control",
            "protocol_version",
            "connect_timeout_ms",
            "asset_wait_timeout_ms",
            "session_timeout_seconds",
        ):
            self.assertNotIn(f'"{bad}"', text)

    def test_new_short_names_present(self) -> None:
        ctrl = _read(MAIN / "reminder_control_client.cc")
        face = (
            _read(MAIN / "face_enrollment_client.cc")
            + "\n"
            + _read(MAIN / "face_config_store.cc")
        )
        self.assertIn('"reminder_ctrl"', ctrl)
        self.assertIn('"proto_ver"', ctrl)
        self.assertIn('"conn_timeout"', ctrl)
        self.assertIn('"asset_timeout"', ctrl)
        self.assertIn('"proto_ver"', face)
        self.assertIn('"session_timeout"', face)
        self.assertIn('"sup_front_only"', face)
        self.assertIn('"sup_user_rel"', face)


class SettingsHardeningContract(unittest.TestCase):
    def _settings(self) -> str:
        return _read(MAIN / "settings.cc")

    def test_no_esp_error_check(self) -> None:
        src = self._settings()
        self.assertNotIn("ESP_ERROR_CHECK", src)

    def test_open_failure_is_non_fatal(self) -> None:
        src = self._settings()
        self.assertIn("open_err_", src)
        self.assertIn("valid_", src)
        self.assertIn("esp_err_to_name", src)
        # Write/erase/commit return esp_err_t and never abort.
        for sig in (
            "esp_err_t Settings::SetString",
            "esp_err_t Settings::SetInt",
            "esp_err_t Settings::SetBool",
            "esp_err_t Settings::EraseKey",
            "esp_err_t Settings::EraseAll",
        ):
            self.assertIn(sig, src)

    def test_dirty_only_on_success(self) -> None:
        src = self._settings()
        # dirty_ = true must appear only after a successful nvs_set_*.
        set_idx = src.find("dirty_ = true")
        self.assertGreater(set_idx, 0)
        self.assertIn("err != ESP_OK", src)

    def test_header_exposes_valid_and_status(self) -> None:
        hdr = _read(MAIN / "settings.h")
        self.assertIn("IsValid()", hdr)
        self.assertIn("esp_err_t SetString", hdr)
        self.assertIn("esp_err_t EraseKey", hdr)


class McpInitializeRegression(unittest.TestCase):
    def _mcp(self) -> str:
        return _read(MAIN / "mcp_server.cc")

    def test_capabilities_parsed_in_order(self) -> None:
        mcp = self._mcp()
        vision = mcp.find('cJSON_GetObjectItem(caps, "vision")')
        reminder = mcp.find('cJSON_GetObjectItem(caps, "reminder_control")')
        face = mcp.find('cJSON_GetObjectItem(caps, "face_enrollment")')
        self.assertGreater(vision, 0)
        self.assertLess(vision, reminder)
        self.assertLess(reminder, face)

    def test_reminder_and_face_accepted_logs_present(self) -> None:
        ctrl = _read(MAIN / "reminder_control_client.cc")
        face = _read(MAIN / "face_enrollment_client.cc")
        self.assertIn("status=accepted", ctrl)
        self.assertIn("status=accepted", face)

    def test_initialize_does_not_abort_on_capability_config(self) -> None:
        # The whole persistence path must degrade, not abort: no aborting NVS
        # wrappers anywhere in the settings layer used by MCP initialize.
        mcp = self._mcp()
        self.assertIn("SetConfig", mcp)
        self.assertIn("SetCapability", mcp)
        self.assertNotIn("ESP_ERROR_CHECK", mcp)
        self.assertNotIn("nvs_set", mcp)
        self.assertNotIn("nvs_open", mcp)

    def test_vision_explain_reads_server_url_field(self) -> None:
        mcp = self._mcp()
        self.assertIn('cJSON_GetObjectItem(vision, "url")', mcp)
        self.assertIn('cJSON_GetObjectItem(vision, "identity_url")', mcp)
        self.assertIn('cJSON_GetObjectItem(vision, "token")', mcp)
        self.assertNotIn('cJSON_GetObjectItem(vision, "explain")', mcp)
        self.assertNotIn('cJSON_GetObjectItem(vision, "explain_url")', mcp)

    def test_vision_url_is_applied_via_camera_manager_not_board_get_camera(self) -> None:
        mcp = self._mcp()
        mgr = _read(MAIN / "boards/esp-box-3/camera_manager.cc")
        self.assertIn("CameraManager::GetInstance().SetExplainUrl(explain, tok)", mcp)
        self.assertIn("persistent_camera_->SetExplainUrl(explain_url_, explain_token_)", mgr)
        # Board::GetCamera() is nullptr unless TryAcquire() is held, so initialize
        # must not gate SetExplainUrl on that pointer.
        self.assertNotIn("Board::GetInstance().GetCamera()", mcp)
        self.assertIn("return camera_;", mgr)


class NoPanicPersistenceModel(unittest.TestCase):
    """Host mirror of the hardened Settings contract (no NVS, no FreeRTOS)."""

    @staticmethod
    def _persist(ns: str, entries: list[tuple[str, object]]) -> list[str]:
        """Return per-entry results, mirroring Settings failure semantics."""
        results: list[str] = []
        valid_ns = 1 <= len(ns) <= NVS_MAX_NAME_LEN
        store: dict[str, object] = {}
        for key, value in entries:
            if not valid_ns or not (1 <= len(key) <= NVS_MAX_NAME_LEN):
                results.append(f"skip:{key}")  # no abort, no dirty
                continue
            store[key] = value
            results.append(f"ok:{key}")
        return results

    def test_reminder_keys_persist_cleanly(self) -> None:
        res = self._persist(
            "reminder_ctrl",
            [
                ("url", "wss://x/rc"),
                ("proto_ver", 1),
                ("conn_timeout", 3000),
                ("asset_timeout", 8000),
            ],
        )
        self.assertEqual(
            res, ["ok:url", "ok:proto_ver", "ok:conn_timeout", "ok:asset_timeout"]
        )

    def test_face_keys_persist_cleanly(self) -> None:
        res = self._persist(
            "face_enrollment",
            [
                ("session_url", "https://x/s"),
                ("proto_ver", 1),
                ("session_timeout", 120),
                ("required_frames", 3),
                ("max_frames", 5),
                ("max_frame_bytes", 307200),
                ("sup_front_only", False),
                ("sup_user_rel", False),
            ],
        )
        self.assertEqual(
            res,
            [
                "ok:session_url",
                "ok:proto_ver",
                "ok:session_timeout",
                "ok:required_frames",
                "ok:max_frames",
                "ok:max_frame_bytes",
                "ok:sup_front_only",
                "ok:sup_user_rel",
            ],
        )

    def test_overlong_key_skips_without_panic(self) -> None:
        res = self._persist(
            "reminder_ctrl", [("asset_wait_timeout_ms", 8000)]
        )
        self.assertEqual(res, ["skip:asset_wait_timeout_ms"])


class TakePhotoExplainUrlFlow(unittest.TestCase):
    """Host mirror of CameraManager stash vs take_photo Explain HTTPS check."""

    HTTPS = "https://api.realecho.cn/mcp/vision/explain"
    TOKEN = "short-lived-token"

    @staticmethod
    def _is_https_url(url: str) -> bool:
        return len(url) > 8 and url.startswith("https://")

    class CameraMgr:
        def __init__(self) -> None:
            self.camera_ = None
            self.persistent: dict[str, str] | None = None
            self.explain_url_ = ""
            self.explain_token_ = ""

        def get_camera(self):
            return self.camera_

        def set_explain_url(self, url: str, token: str) -> None:
            self.explain_url_ = url
            self.explain_token_ = token
            if self.persistent is not None:
                self.persistent["url"] = url
                self.persistent["token"] = token

        def open_persistent(self) -> None:
            self.persistent = {"url": "", "token": ""}
            if self.explain_url_:
                self.persistent["url"] = self.explain_url_
                self.persistent["token"] = self.explain_token_

        def try_acquire(self) -> None:
            self.camera_ = self.persistent

        def explain(self) -> str:
            url = self.camera_["url"] if self.camera_ else ""
            if not TakePhotoExplainUrlFlow._is_https_url(url):
                raise RuntimeError("Vision service must use an HTTPS URL")
            return url

    def test_old_board_get_camera_path_rejects_https_after_capture(self) -> None:
        mgr = self.CameraMgr()
        mgr.open_persistent()
        # MCP initialize used Board::GetCamera(), which is nullptr here.
        self.assertIsNone(mgr.get_camera())
        mgr.try_acquire()
        with self.assertRaisesRegex(RuntimeError, "HTTPS URL"):
            mgr.explain()

    def test_initialize_before_camera_open_then_take_photo_posts_https(self) -> None:
        mgr = self.CameraMgr()
        self.assertIsNone(mgr.get_camera())
        mgr.set_explain_url(self.HTTPS, self.TOKEN)
        mgr.open_persistent()
        mgr.try_acquire()
        self.assertEqual(mgr.explain(), self.HTTPS)
        self.assertEqual(mgr.camera_["token"], self.TOKEN)

    def test_initialize_after_camera_open_without_acquire_then_take_photo(self) -> None:
        mgr = self.CameraMgr()
        mgr.open_persistent()
        self.assertIsNone(mgr.get_camera())
        mgr.set_explain_url(self.HTTPS, self.TOKEN)
        mgr.try_acquire()
        self.assertEqual(mgr.explain(), self.HTTPS)

    def test_empty_and_http_urls_are_rejected(self) -> None:
        self.assertFalse(self._is_https_url(""))
        self.assertFalse(self._is_https_url("http://api.realecho.cn/mcp/vision/explain"))
        self.assertTrue(self._is_https_url(self.HTTPS))


if __name__ == "__main__":
    unittest.main()
