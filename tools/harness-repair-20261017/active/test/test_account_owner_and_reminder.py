"""账号默认主人、JWT、self 提醒、MCP isError、LLM 401 不关连。

运行:
  cd main/xiaozhi-server
  /root/miniconda3/envs/xiaozhi-esp32-server/bin/python test/test_account_owner_and_reminder.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.utils.account_identity import (
    bind_face_account_on_conn,
    normalize_manager_user_id,
    resolve_face_account_id,
)
from core.utils.device_reminder import create_device_timed_note
from core.utils.face_jwt import build_face_service_jwt, is_reserved_account_id
from core.utils.recipient_resolver import (
    IDENTITY_UNAVAILABLE_CODE,
    ProfileDirectory,
    ProfileRecord,
    RecipientResultCode,
    apply_recipient_to_device_args,
    resolve_recipient,
    resolve_recipient_for_conn,
)
from plugins_func.register import Action


class AccountIdentityTests(unittest.TestCase):
    def test_normalize_rejects_default_mac_usr(self):
        self.assertIsNone(normalize_manager_user_id("default"))
        self.assertIsNone(normalize_manager_user_id("b8:f8:62:7e:ca:58"))
        self.assertIsNone(normalize_manager_user_id("usr_abc123"))
        self.assertEqual(normalize_manager_user_id(42), "42")
        self.assertEqual(normalize_manager_user_id("10086"), "10086")

    def test_bind_face_account_on_conn(self):
        conn = types.SimpleNamespace()
        aid = bind_face_account_on_conn(conn, {"userId": 10086})
        self.assertEqual(aid, "10086")
        self.assertEqual(conn.face_account_id, "10086")
        self.assertEqual(resolve_face_account_id(conn=conn), "10086")


class JwtAndRecipientTests(unittest.IsolatedAsyncioTestCase):
    def test_jwt_requires_ver(self):
        tok = build_face_service_jwt(
            secret="x" * 32, account_id="10086", device_id="aa:bb"
        )
        self.assertIsNotNone(tok)
        import jwt

        payload = jwt.decode(tok, "x" * 32, algorithms=["HS256"])
        self.assertEqual(payload.get("ver"), 1)
        self.assertEqual(payload.get("account_id"), "10086")
        self.assertEqual(payload.get("device_id"), "aa:bb")
        self.assertIsNone(
            build_face_service_jwt(secret="x" * 32, account_id="default", device_id="d")
        )

    def test_self_uses_default_owner_usr(self):
        d = ProfileDirectory(
            account_id="10086",
            profiles=[
                ProfileRecord(
                    "usr_aabbcc", "主人", "active", "10086", is_default_owner=True
                )
            ],
        )
        r = resolve_recipient(d, selector="我")
        self.assertEqual(r.code, RecipientResultCode.RESOLVED)
        self.assertTrue(r.ok_for_create)
        self.assertEqual(r.recipient_person_id, "usr_aabbcc")
        args = apply_recipient_to_device_args({"text": "喝水"}, r)
        self.assertEqual(args["recipient_person_id"], "usr_aabbcc")

    def test_missing_owner_fail_closed(self):
        d = ProfileDirectory(account_id="10086", profiles=[])
        r = resolve_recipient(d, selector="我")
        self.assertEqual(r.code, RecipientResultCode.IDENTITY_UNAVAILABLE)
        self.assertFalse(r.ok_for_create)
        args = apply_recipient_to_device_args({"text": "x"}, r)
        self.assertNotIn("recipient_person_id", args)

    def test_fetch_error_fail_closed(self):
        d = ProfileDirectory(
            account_id="10086", profiles=[], fetch_error="http_401"
        )
        r = resolve_recipient(d, selector=None)
        self.assertEqual(r.error_code, IDENTITY_UNAVAILABLE_CODE)
        self.assertFalse(r.ok_for_create)

    async def test_profiles_401_zero_device_send(self):
        conn = MagicMock()
        conn.config = {
            "server": {
                "face": {
                    "account_id": "",
                    "jwt_secret": "y" * 40,
                    "identify_url": "http://face.test/face/identify",
                    "timeout": 1,
                }
            }
        }
        conn.device_id = "dev-a"
        conn.face_account_id = "10086"
        conn.device_user_id = "10086"
        conn.headers = {"device-id": "dev-a"}
        conn.mcp_client = MagicMock()
        conn.mcp_client.has_tool = MagicMock(return_value=True)
        sent = []

        async def fake_fetch(*a, **k):
            return ProfileDirectory(
                account_id="10086", profiles=[], fetch_error="http_401"
            )

        with patch(
            "core.utils.device_reminder.call_device_note_add",
            new_callable=AsyncMock,
        ) as call_note:
            with patch(
                "core.utils.unified_recipient_resolver._fetch_directory",
                new=fake_fetch,
            ):
                resp = await create_device_timed_note(
                    conn,
                    text="两分钟后提醒我喝水",
                    content="喝水",
                    remind_time_str="两分钟后",
                )
            # Authentication failure is a direct safe response; it must not
            # trigger a model turn or send a write to the device.
            self.assertEqual(resp.action, Action.RESPONSE)
            self.assertIn("身份正在同步", resp.result)
            call_note.assert_not_called()
            self.assertEqual(sent, [])


class MultiDeviceOwnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_account_shared_owner_different_sessions(self):
        owner = ProfileRecord(
            "usr_shared1", "主人", "active", "42", is_default_owner=True
        )
        directory = ProfileDirectory(account_id="42", profiles=[owner])

        async def resolve(device_id):
            conn = MagicMock()
            conn.config = {"server": {"face": {}}}
            conn.device_id = device_id
            conn.face_account_id = "42"
            conn.headers = {"device-id": device_id}
            return await resolve_recipient_for_conn(
                conn, selector="我", tool_name="note.add", directory=directory
            )

        ra = await resolve("aa:aa:aa:aa:aa:01")
        rb = await resolve("bb:bb:bb:bb:bb:02")
        self.assertEqual(ra.recipient_person_id, rb.recipient_person_id)
        self.assertEqual(ra.recipient_person_id, "usr_shared1")

    def test_different_accounts_different_owners(self):
        da = ProfileDirectory(
            account_id="1",
            profiles=[
                ProfileRecord("usr_aaa111", "主人", "active", "1", True)
            ],
        )
        db = ProfileDirectory(
            account_id="2",
            profiles=[
                ProfileRecord("usr_bbb222", "主人", "active", "2", True)
            ],
        )
        ra = resolve_recipient(da, selector="我")
        rb = resolve_recipient(db, selector="我")
        self.assertNotEqual(ra.recipient_person_id, rb.recipient_person_id)


class McpIsErrorPassthrough(unittest.IsolatedAsyncioTestCase):
    async def test_content_text_passthrough(self):
        from core.providers.tools.device_mcp import mcp_handler

        conn = MagicMock()
        conn.device_id = "dev1"
        conn.session_id = "sess1"
        conn.last_activity_time = 0

        class FakeClient:
            def __init__(self):
                self._id = 0
                self.call_results = {}

            def has_tool(self, name):
                return True

            async def is_ready(self):
                return True

            def resolve_tool_name(self, name):
                return "note.add"

            def get_raw_tool_names(self):
                return ["note.add"]

            async def get_next_id(self):
                self._id += 1
                return self._id

            async def register_call_result_future(self, mid, future):
                future.set_result(
                    {
                        "isError": True,
                        "content": [
                            {
                                "type": "text",
                                "text": "recipient_person_id must be a stable usr_* identity",
                            }
                        ],
                    }
                )

            async def cleanup_call_result(self, mid):
                return None

        client = FakeClient()
        with patch.object(
            mcp_handler, "send_mcp_message", new_callable=AsyncMock
        ):
            with self.assertRaises(RuntimeError) as ctx:
                await mcp_handler.call_mcp_tool(
                    conn, client, "note_add", '{"text":"x"}'
                )
        self.assertEqual(ctx.exception.code, "unclassified_tool_error")
        self.assertIn("stable usr_*", ctx.exception.device_message)
        self.assertNotIn("stable usr_*", str(ctx.exception))


class Llm401KeepsWebsocket(unittest.TestCase):
    def test_response_yields_fallback_no_close(self):
        from core.providers.llm.openai.openai import LLMProvider

        cfg = {
            "model_name": "glm-4-flash",
            "api_key": "bad",
            "base_url": "https://open.bigmodel.cn/api/paas/v4/",
            "_config_name": "LLM_ChatGLMLLM",
            "type": "openai",
            "timeout": 1,
        }
        provider = LLMProvider(cfg)
        provider.client = MagicMock()
        provider.client.chat.completions.create.side_effect = Exception(
            "Error code: 401 - {'error': {'message': '令牌已过期或验证不正确'}}"
        )
        closed = {"n": 0}

        def close_ws():
            closed["n"] += 1

        chunks = list(provider.response("sess", [{"role": "user", "content": "hi"}]))
        self.assertTrue(any("暂时无法响应" in c for c in chunks))
        self.assertEqual(closed["n"], 0)


if __name__ == "__main__":
    unittest.main()
