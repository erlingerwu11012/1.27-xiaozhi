"""front_only 开关：配置合并保留 + 显式 false/[] 不被环境变量覆盖。"""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config.config_loader import get_config_from_api, merge_configs
from core.utils.face_enrollment_v2 import (
    is_front_only_allowed,
    is_front_only_enabled,
    is_user_relative_allowed,
    is_user_relative_enabled,
    parse_strict_bool,
    user_relative_allowlist,
)


ACCT = "2022326478036516866"
DEV = "ac:a7:04:fd:20:2c"


def _local_cfg(**server_extra):
    server = {
        "ip": "0.0.0.0",
        "port": 8000,
        "auth_key": "local-auth-key-not-secret-xx",
        "public_base_url": "https://public.example.com",
        "websocket": "wss://public.example.com/xiaozhi/v1/",
    }
    server.update(server_extra)
    return {
        "server": server,
        "manager-api": {"url": "http://127.0.0.1:9999", "secret": "test-secret"},
        "selected_module": {"ASR": "X", "LLM": "Y", "TTS": "Z"},
        "VAD": {"min_silence_duration_ms": 111},
        "ASR": {"X": {"type": "x"}},
        "LLM": {"Y": {"type": "y"}},
        "TTS": {"Z": {"type": "z"}},
    }


class StrictBoolTests(unittest.TestCase):
    def test_parse_strict_bool(self):
        self.assertTrue(parse_strict_bool(True) is True)
        self.assertTrue(parse_strict_bool(False) is False)
        self.assertTrue(parse_strict_bool("false") is False)
        self.assertTrue(parse_strict_bool("true") is True)
        self.assertIsNone(parse_strict_bool(1))
        self.assertIsNone(parse_strict_bool(0))
        self.assertIsNone(parse_strict_bool("maybe"))
        # bool("false") 为 True；本函数不得如此
        self.assertIs(bool("false"), True)
        self.assertIs(parse_strict_bool("false"), False)


class FrontOnlyFlagSemanticsTests(unittest.TestCase):
    def setUp(self):
        self._env = {
            k: os.environ.get(k)
            for k in (
                "FACE_ENROLLMENT_FRONT_ONLY",
                "FACE_ENROLLMENT_FRONT_ONLY_ALLOWLIST",
            )
        }
        os.environ["FACE_ENROLLMENT_FRONT_ONLY"] = "1"
        os.environ["FACE_ENROLLMENT_FRONT_ONLY_ALLOWLIST"] = f"{ACCT}|{DEV}"

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_explicit_false_beats_env_true(self):
        cfg = {"server": {"face_enrollment_front_only_enabled": False}}
        self.assertFalse(is_front_only_enabled(cfg))
        self.assertFalse(is_front_only_allowed(cfg, ACCT, DEV))

    def test_explicit_empty_allowlist_beats_env(self):
        cfg = {
            "server": {
                "face_enrollment_front_only_enabled": True,
                "face_enrollment_front_only_allowlist": [],
            }
        }
        self.assertTrue(is_front_only_enabled(cfg))
        self.assertTrue(is_front_only_allowed(cfg, ACCT, DEV))

    def test_missing_fields_use_env(self):
        cfg = {"server": {}}
        self.assertTrue(is_front_only_enabled(cfg))
        self.assertTrue(is_front_only_allowed(cfg, ACCT, DEV))

    def test_enabled_front_only_is_global(self):
        cfg = {
            "server": {
                "face_enrollment_front_only_enabled": True,
                "face_enrollment_front_only_allowlist": [
                    {"account_id": ACCT, "device_id": DEV}
                ],
            }
        }
        self.assertTrue(is_front_only_allowed(cfg, "other", DEV))
        self.assertTrue(is_front_only_allowed(cfg, ACCT, "aa:bb:cc:dd:ee:ff"))
        self.assertTrue(is_front_only_allowed(cfg, ACCT, ""))
        self.assertTrue(is_front_only_allowed(cfg, ACCT, DEV))

    def test_illegal_flag_safe_reject(self):
        cfg = {"server": {"face_enrollment_front_only_enabled": "maybe"}}
        self.assertFalse(is_front_only_enabled(cfg))
        cfg2 = {"server": {"face_enrollment_front_only_enabled": 1}}
        self.assertFalse(is_front_only_enabled(cfg2))


class ConfigMergePreservesFrontOnlyTests(unittest.TestCase):
    def setUp(self):
        self._env = {
            k: os.environ.get(k)
            for k in (
                "FACE_ENROLLMENT_FRONT_ONLY",
                "FACE_ENROLLMENT_FRONT_ONLY_ALLOWLIST",
            )
        }
        os.environ.pop("FACE_ENROLLMENT_FRONT_ONLY", None)
        os.environ.pop("FACE_ENROLLMENT_FRONT_ONLY_ALLOWLIST", None)

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _run_merge(self, local, api_payload):
        with patch("config.config_loader.init_service"), patch(
            "config.config_loader.get_server_config", return_value=api_payload
        ), patch("config.config_loader.apply_local_only_top_level", side_effect=lambda a, b: b):
            return get_config_from_api(local)

    def test_local_true_allowlist_survives_api_merge(self):
        local = _local_cfg(
            face_enrollment_front_only_enabled=True,
            face_enrollment_front_only_allowlist=[
                {"account_id": ACCT, "device_id": DEV}
            ],
        )
        # 模拟 manager-api 返回的 server 不含 front_only 字段
        api = {
            "server": {
                "ip": "from-api",
                "port": 9000,
                "mqtt_gateway": "mqtt.example.com:1883",
            },
            "VAD": {"min_silence_duration_ms": 999},
            "selected_module": {"ASR": "API_ASR"},
        }
        merged = self._run_merge(local, api)
        server = merged["server"]
        self.assertTrue(server.get("face_enrollment_front_only_enabled") is True)
        self.assertNotIn("face_enrollment_front_only_allowlist", server)
        self.assertTrue(is_front_only_allowed(merged, ACCT, DEV))
        # 本地 ip 仍优先；API mqtt 保留
        self.assertEqual(server["ip"], "0.0.0.0")
        self.assertEqual(server.get("mqtt_gateway"), "mqtt.example.com:1883")
        # VAD 以 API 为准（不把本地 VAD 盖上去）
        self.assertEqual(merged["VAD"]["min_silence_duration_ms"], 999)

    def test_explicit_false_survives_merge_and_blocks_env(self):
        os.environ["FACE_ENROLLMENT_FRONT_ONLY"] = "1"
        os.environ["FACE_ENROLLMENT_FRONT_ONLY_ALLOWLIST"] = f"{ACCT}|{DEV}"
        local = _local_cfg(
            face_enrollment_front_only_enabled=False,
            face_enrollment_front_only_allowlist=[
                {"account_id": ACCT, "device_id": DEV}
            ],
        )
        api = {"server": {"port": 1}, "VAD": {"min_silence_duration_ms": 50}}
        merged = self._run_merge(local, api)
        self.assertIs(merged["server"]["face_enrollment_front_only_enabled"], False)
        self.assertFalse(is_front_only_enabled(merged))
        self.assertFalse(is_front_only_allowed(merged, ACCT, DEV))

    def test_explicit_empty_list_survives_merge(self):
        os.environ["FACE_ENROLLMENT_FRONT_ONLY"] = "1"
        os.environ["FACE_ENROLLMENT_FRONT_ONLY_ALLOWLIST"] = f"{ACCT}|{DEV}"
        local = _local_cfg(
            face_enrollment_front_only_enabled=True,
            face_enrollment_front_only_allowlist=[],
        )
        api = {"server": {}, "VAD": {}}
        merged = self._run_merge(local, api)
        self.assertNotIn("face_enrollment_front_only_allowlist", merged["server"])
        self.assertTrue(is_front_only_allowed(merged, ACCT, DEV))

    def test_yaml_merge_then_api_merge(self):
        default = _local_cfg(
            face_enrollment_front_only_enabled=False,
            face_enrollment_front_only_allowlist=[],
        )
        custom = {
            "server": {
                "face_enrollment_front_only_enabled": True,
                "face_enrollment_front_only_allowlist": [
                    {"account_id": ACCT, "device_id": DEV}
                ],
            }
        }
        local = merge_configs(default, custom)
        api = {"server": {"websocket": "wss://api.example.com/v1"}, "ASR": {"x": 1}}
        merged = self._run_merge(local, api)
        self.assertTrue(is_front_only_allowed(merged, ACCT, DEV))


class UserRelativeFlagSemanticsTests(unittest.TestCase):
    def setUp(self):
        self._env = {
            k: os.environ.get(k)
            for k in (
                "FACE_ENROLLMENT_USER_RELATIVE",
                "FACE_ENROLLMENT_USER_RELATIVE_ALLOWLIST",
            )
        }
        os.environ["FACE_ENROLLMENT_USER_RELATIVE"] = "1"
        os.environ["FACE_ENROLLMENT_USER_RELATIVE_ALLOWLIST"] = f"{ACCT}|{DEV}"

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_explicit_false_beats_env_true(self):
        cfg = {"server": {"face_enrollment_user_relative_enabled": False}}
        self.assertFalse(is_user_relative_enabled(cfg))
        self.assertFalse(is_user_relative_allowed(cfg, ACCT, DEV))

    def test_explicit_empty_allowlist_beats_env(self):
        cfg = {
            "server": {
                "face_enrollment_user_relative_enabled": True,
                "face_enrollment_user_relative_allowlist": [],
            }
        }
        self.assertTrue(is_user_relative_enabled(cfg))
        self.assertEqual(user_relative_allowlist(cfg), [])
        self.assertFalse(is_user_relative_allowed(cfg, ACCT, DEV))

    def test_missing_fields_use_env(self):
        cfg = {"server": {}}
        self.assertTrue(is_user_relative_enabled(cfg))
        self.assertTrue(is_user_relative_allowed(cfg, ACCT, DEV))

    def test_other_account_or_device_rejected(self):
        cfg = {
            "server": {
                "face_enrollment_user_relative_enabled": True,
                "face_enrollment_user_relative_allowlist": [
                    {"account_id": ACCT, "device_id": DEV}
                ],
            }
        }
        self.assertFalse(is_user_relative_allowed(cfg, "other", DEV))
        self.assertFalse(is_user_relative_allowed(cfg, ACCT, "aa:bb:cc:dd:ee:ff"))


class ConfigMergePreservesUserRelativeTests(unittest.TestCase):
    def setUp(self):
        self._env = {
            k: os.environ.get(k)
            for k in (
                "FACE_ENROLLMENT_USER_RELATIVE",
                "FACE_ENROLLMENT_USER_RELATIVE_ALLOWLIST",
            )
        }
        os.environ.pop("FACE_ENROLLMENT_USER_RELATIVE", None)
        os.environ.pop("FACE_ENROLLMENT_USER_RELATIVE_ALLOWLIST", None)

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _run_merge(self, local, api_payload):
        with patch("config.config_loader.init_service"), patch(
            "config.config_loader.get_server_config", return_value=api_payload
        ), patch(
            "config.config_loader.apply_local_only_top_level",
            side_effect=lambda a, b: b,
        ):
            return get_config_from_api(local)

    def test_local_true_allowlist_survives_api_merge(self):
        local = _local_cfg(
            face_enrollment_user_relative_enabled=True,
            face_enrollment_user_relative_allowlist=[
                {"account_id": ACCT, "device_id": DEV}
            ],
        )
        api = {"server": {"ip": "from-api"}, "VAD": {"min_silence_duration_ms": 50}}
        merged = self._run_merge(local, api)
        self.assertIs(
            merged["server"]["face_enrollment_user_relative_enabled"], True
        )
        self.assertEqual(
            merged["server"]["face_enrollment_user_relative_allowlist"],
            [{"account_id": ACCT, "device_id": DEV}],
        )
        self.assertTrue(is_user_relative_allowed(merged, ACCT, DEV))

    def test_explicit_false_survives_merge_and_blocks_env(self):
        os.environ["FACE_ENROLLMENT_USER_RELATIVE"] = "1"
        os.environ["FACE_ENROLLMENT_USER_RELATIVE_ALLOWLIST"] = f"{ACCT}|{DEV}"
        local = _local_cfg(
            face_enrollment_user_relative_enabled=False,
            face_enrollment_user_relative_allowlist=[
                {"account_id": ACCT, "device_id": DEV}
            ],
        )
        api = {"server": {"port": 1}, "VAD": {}}
        merged = self._run_merge(local, api)
        self.assertIs(
            merged["server"]["face_enrollment_user_relative_enabled"], False
        )
        self.assertFalse(is_user_relative_enabled(merged))
        self.assertFalse(is_user_relative_allowed(merged, ACCT, DEV))

    def test_explicit_empty_list_survives_merge(self):
        os.environ["FACE_ENROLLMENT_USER_RELATIVE"] = "1"
        os.environ["FACE_ENROLLMENT_USER_RELATIVE_ALLOWLIST"] = f"{ACCT}|{DEV}"
        local = _local_cfg(
            face_enrollment_user_relative_enabled=True,
            face_enrollment_user_relative_allowlist=[],
        )
        api = {"server": {}, "VAD": {}}
        merged = self._run_merge(local, api)
        self.assertEqual(
            merged["server"]["face_enrollment_user_relative_allowlist"], []
        )
        self.assertFalse(is_user_relative_allowed(merged, ACCT, DEV))


if __name__ == "__main__":
    unittest.main()
