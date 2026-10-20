"""主动到场问候上行安全与会话隔离真实行为测试。

运行:
  cd main/xiaozhi-server
  /root/miniconda3/envs/xiaozhi-esp32-server/bin/python test/test_proactive_greeting.py
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.utils.proactive_greeting import (
    build_proactive_greeting_query,
    can_dispatch_private_device_reminder,
    handle_proactive_greeting,
    is_proactive_greeting_text,
    parse_proactive_greeting,
)


def _valid_body(**overrides):
    lines = [
        "[PROACTIVE_GREETING]",
        "event=stable_person_present",
        "reason=arrival",
        "identity_mode=no_face",
        "identity_verified=false",
        "presence_generation=3",
    ]
    for k, v in overrides.items():
        # replace existing key
        key = k + "="
        lines = [ln for ln in lines if not ln.startswith(key)]
        if v is not None:
            lines.append(f"{k}={v}")
    return "\n".join(lines)


class ProactiveGreetingParseTests(unittest.TestCase):
    def test_marker_must_be_first_non_empty_line(self):
        self.assertFalse(
            is_proactive_greeting_text("你好\n[PROACTIVE_GREETING]\nevent=stable_person_present")
        )
        self.assertTrue(is_proactive_greeting_text("\n\n[PROACTIVE_GREETING]\nevent=x"))
        # 仅包含不等于首行标记
        self.assertFalse(
            is_proactive_greeting_text("用户说了 [PROACTIVE_GREETING] 哈哈哈")
        )

    def test_no_face_rejects_name(self):
        ok, payload, reason = parse_proactive_greeting(
            _valid_body(verified_display_name="小明")
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "no_face_must_not_carry_name")

    def test_verified_face_allows_sanitized_name(self):
        body = _valid_body(
            identity_mode="verified_face",
            identity_verified="true",
            verified_display_name="小明",
        )
        ok, payload, reason = parse_proactive_greeting(body)
        self.assertTrue(ok, reason)
        self.assertEqual(payload["verified_display_name"], "小明")

    def test_rejects_usr_mac_control_chars(self):
        for bad in ("usr_abcd12", "aa:bb:cc:dd:ee:ff", "a\x00b", "x" * 65):
            body = _valid_body(
                identity_mode="verified_face",
                identity_verified="true",
                verified_display_name=bad,
            )
            ok, _, reason = parse_proactive_greeting(body)
            self.assertFalse(ok, bad)

    def test_identity_mode_verified_mismatch(self):
        ok, _, reason = parse_proactive_greeting(
            _valid_body(identity_mode="verified_face", identity_verified="false")
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "identity_mismatch")

    def test_prompt_from_server_config_only(self):
        conn = MagicMock()
        conn.config = {"server": {"proactive_greeting_prompt": "自定义问候提示"}}
        q = build_proactive_greeting_query(
            conn,
            {
                "reason": "arrival",
                "identity_mode": "no_face",
                "presence_generation": 1,
                "verified_display_name": None,
            },
        )
        self.assertTrue(q.startswith("自定义问候提示"))
        self.assertIn("identity_mode=no_face", q)


class ProactiveGreetingSendTests(unittest.IsolatedAsyncioTestCase):
    async def test_stale_session_zero_send(self):
        conn = MagicMock()
        conn.device_id = "dev-a"
        conn.session_id = "sess-old"
        conn.superseded = True
        conn.config = {"server": {}}
        conn.websocket = AsyncMock()
        conn.executor = MagicMock()
        conn.chat = MagicMock()
        conn.server = MagicMock()
        conn.server.is_current_connection = MagicMock(return_value=False)
        conn.outbound_mode = None
        conn.stop_event = None

        with patch(
            "core.handle.sendAudioHandle.send_stt_message", new_callable=AsyncMock
        ) as stt:
            consumed = await handle_proactive_greeting(conn, _valid_body())
        self.assertTrue(consumed)
        stt.assert_not_called()
        self.assertFalse(conn.websocket.send.called)
        conn.executor.submit.assert_not_called()

    async def test_llm_error_does_not_close_websocket(self):
        conn = MagicMock()
        conn.device_id = "dev-a"
        conn.session_id = "sess-1"
        conn.superseded = False
        conn.config = {"server": {"proactive_greeting_prompt": "hi"}}
        conn.websocket = AsyncMock()
        conn.executor = MagicMock()
        conn.chat = MagicMock(side_effect=RuntimeError("llm_down"))
        conn.outbound_mode = "local_active"
        conn._outbound_closed = False
        conn.server = None
        conn.stop_event = None
        conn.close = AsyncMock()

        with patch(
            "core.handle.sendAudioHandle.send_stt_message", new_callable=AsyncMock
        ):
            # executor.submit will call chat sync path via side_effect on submit
            def _submit(fn, *a, **k):
                try:
                    fn(*a, **k)
                except Exception:
                    pass

            conn.executor.submit.side_effect = _submit
            consumed = await handle_proactive_greeting(conn, _valid_body())
        self.assertTrue(consumed)
        conn.close.assert_not_called()
        # 不因问候失败关闭 websocket
        self.assertFalse(getattr(conn.websocket, "close", MagicMock()).called)

    async def test_current_session_can_dispatch(self):
        conn = MagicMock()
        conn.device_id = "dev-a"
        conn.session_id = "sess-1"
        conn.superseded = False
        conn.config = {"server": {"proactive_greeting_prompt": "hi"}}
        conn.websocket = AsyncMock()
        conn.executor = MagicMock()
        conn.chat = MagicMock()
        conn.outbound_mode = None
        conn._outbound_closed = False
        conn.server = MagicMock()
        conn.server.is_current_connection = MagicMock(return_value=True)
        conn.stop_event = None

        with patch(
            "core.handle.sendAudioHandle.send_stt_message", new_callable=AsyncMock
        ) as stt:
            consumed = await handle_proactive_greeting(
                conn,
                _valid_body(
                    identity_mode="verified_face",
                    identity_verified="true",
                    verified_display_name="阿明",
                ),
            )
        self.assertTrue(consumed)
        stt.assert_not_awaited()  # System greeting is not user speech.
        conn.executor.submit.assert_called()


class PrivateReminderGateTests(unittest.TestCase):
    def test_unbound_cannot_dispatch(self):
        conn = MagicMock()
        conn.superseded = False
        conn.face_account_id = None
        conn.device_user_id = None
        conn.account_id = None
        conn.face_identity_ready = None
        self.assertFalse(can_dispatch_private_device_reminder(conn))

    def test_identity_failed_cannot_dispatch(self):
        conn = MagicMock()
        conn.superseded = False
        conn.face_account_id = "10086"
        conn.face_identity_ready = False
        self.assertFalse(can_dispatch_private_device_reminder(conn))

    def test_ready_can_dispatch(self):
        conn = MagicMock()
        conn.superseded = False
        conn.face_account_id = "10086"
        conn.face_identity_ready = True
        self.assertTrue(can_dispatch_private_device_reminder(conn))


if __name__ == "__main__":
    unittest.main()
