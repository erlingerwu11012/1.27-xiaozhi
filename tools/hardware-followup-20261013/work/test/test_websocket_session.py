"""WebSocket 会话状态机 / v2 音频帧 / MCP 初始化包长 端到端单测。

覆盖：
- v2/v3 音频帧包长严格校验（16/4 字节头，大端）。
- 会话状态机：未 hello 拒绝 listen/音频；旧 session 拒绝；合法 listen 放行。
- MCP initialize 消息 > 1024 字节（验证设备端大包链路）。
不依赖完整 app 依赖，仅用轻量 FakeWS + mock。
"""

from __future__ import annotations

import asyncio
import json
import struct
import sys
import os
import unittest
import websockets
import websockets.exceptions
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.connection import ConnectionHandler


class FakeWS:
    def __init__(self):
        self.sent = []
        self.closed_code = None
        self.closed_reason = None

    async def send(self, data):
        self.sent.append(data)

    async def close(self, code=1000, reason=""):
        self.closed_code = code
        self.closed_reason = reason


def _make_handler(**attrs):
    """绕过 __init__ 构造最小 ConnectionHandler，仅设置状态机所需字段。"""
    handler = ConnectionHandler.__new__(ConnectionHandler)
    handler.correlation_id = "testcid1234567890"
    handler.device_id = "aa:bb:cc:dd:ee:ff"
    handler.session_id = "session-current"
    handler.hello_received = False
    handler.protocol_version = None
    handler.audio_protocol_version = 0
    handler.vad = None
    handler.asr = None
    handler.need_bind = False
    handler.conn_from_mqtt_gateway = False
    handler.asr_audio_queue = MagicMock()
    handler.logger = MagicMock()
    handler.websocket = FakeWS()
    handler._binary_received_logged = False
    # 音频会话可观测性字段
    handler.frames_received = 0
    handler.frames_parsed_ok = 0
    handler.frames_parse_failed = 0
    handler.first_frame_monotonic_ms = None
    handler.last_frame_monotonic_ms = None
    handler.last_payload_bytes = 0
    handler.total_payload_bytes = 0
    handler.close_category = None
    # listen=start 快照字段
    handler.listen_start_seen = False
    handler.listen_start_monotonic_ms = None
    handler.frames_parsed_ok_at_listen_start = 0
    handler.total_payload_bytes_at_listen_start = 0
    handler.last_frame_monotonic_ms_at_listen_start = None
    for k, v in attrs.items():
        setattr(handler, k, v)
    return handler


def _v2_frame(version=2, msg_type=0, timestamp=0, payload=b"\x01\x02\x03"):
    header = struct.pack("!HHIII", version, msg_type, 0, timestamp, len(payload))
    return header + payload


def _v3_frame(msg_type=0, payload=b"\x01\x02\x03"):
    header = struct.pack("!BBH", msg_type, 0, len(payload))
    return header + payload


class TestBinaryAudioParsing(unittest.IsolatedAsyncioTestCase):
    async def test_v2_valid_frame(self):
        h = _make_handler()
        ok = await h._process_binary_protocol2_audio(_v2_frame(payload=b"\x01" * 32))
        self.assertTrue(ok)

    async def test_v2_wrong_version(self):
        h = _make_handler()
        ok = await h._process_binary_protocol2_audio(
            _v2_frame(version=1, payload=b"\x01" * 32)
        )
        self.assertFalse(ok)

    async def test_v2_wrong_msg_type(self):
        h = _make_handler()
        ok = await h._process_binary_protocol2_audio(
            _v2_frame(msg_type=1, payload=b"\x01" * 32)
        )
        self.assertFalse(ok)

    async def test_v2_payload_size_mismatch(self):
        h = _make_handler()
        frame = _v2_frame(payload=b"\x01" * 32)
        # 篡改 payload_size 字段（多报 1 字节）
        tampered = frame[:12] + struct.pack("!I", 33) + frame[16:]
        ok = await h._process_binary_protocol2_audio(tampered)
        self.assertFalse(ok)

    async def test_v2_too_short(self):
        h = _make_handler()
        ok = await h._process_binary_protocol2_audio(b"\x00" * 15)
        self.assertFalse(ok)

    async def test_v3_valid_frame(self):
        h = _make_handler()
        ok = await h._process_binary_protocol3_audio(_v3_frame(payload=b"\x01" * 32))
        self.assertTrue(ok)

    async def test_v3_payload_size_mismatch(self):
        h = _make_handler()
        frame = _v3_frame(payload=b"\x01" * 32)
        tampered = frame[:2] + struct.pack("!H", 33) + frame[4:]
        ok = await h._process_binary_protocol3_audio(tampered)
        self.assertFalse(ok)


class TestSessionStateMachine(unittest.IsolatedAsyncioTestCase):
    async def test_listen_before_hello_rejected(self):
        h = _make_handler()
        msg = json.dumps(
            {"type": "listen", "state": "start", "session_id": "session-current"}
        )
        await h._route_message_inner(msg)
        self.assertEqual(h.websocket.closed_code, 1002)
        self.assertEqual(h.websocket.closed_reason, "hello_required_first")

    async def test_audio_before_hello_rejected(self):
        h = _make_handler()
        await h._route_message_inner(_v2_frame(payload=b"\x01" * 32))
        self.assertEqual(h.websocket.closed_code, 1002)
        self.assertEqual(h.websocket.closed_reason, "hello_required_before_audio")

    async def test_stale_session_rejected(self):
        h = _make_handler(hello_received=True, protocol_version=2)
        msg = json.dumps(
            {"type": "listen", "state": "start", "session_id": "old-session-id"}
        )
        await h._route_message_inner(msg)
        self.assertEqual(h.websocket.closed_code, 1008)
        self.assertEqual(h.websocket.closed_reason, "stale_session")

    async def test_valid_listen_after_hello_allowed(self):
        h = _make_handler(hello_received=True, protocol_version=2)
        msg = json.dumps(
            {"type": "listen", "state": "start", "session_id": "session-current"}
        )
        with patch("core.connection.handleTextMessage", new=AsyncMock()) as m:
            await h._route_message_inner(msg)
        m.assert_awaited_once()
        self.assertIsNone(h.websocket.closed_code)

    async def test_hello_message_always_allowed(self):
        h = _make_handler()
        msg = json.dumps({"type": "hello", "version": 2})
        with patch("core.connection.handleTextMessage", new=AsyncMock()) as m:
            await h._route_message_inner(msg)
        m.assert_awaited_once()
        self.assertIsNone(h.websocket.closed_code)

    async def test_invalid_v2_frame_rejected(self):
        h = _make_handler(hello_received=True, protocol_version=2)
        # 非法帧（版本错误）→ 显式协议错误关闭
        await h.handle_binary_audio(_v2_frame(version=1, payload=b"\x01" * 32))
        self.assertEqual(h.websocket.closed_code, 1002)
        self.assertEqual(h.websocket.closed_reason, "invalid_audio_frame_v2")


class TestAudioFrameObservability(unittest.IsolatedAsyncioTestCase):
    def test_v2_continuous_frames_counters(self):
        async def run():
            h = _make_handler(hello_received=True, protocol_version=2)
            payload = b"\x01" * 32
            for _ in range(3):
                await h.handle_binary_audio(_v2_frame(payload=payload))
            self.assertEqual(h.frames_received, 3)
            self.assertEqual(h.frames_parsed_ok, 3)
            self.assertEqual(h.frames_parse_failed, 0)
            self.assertEqual(h.total_payload_bytes, 3 * 32)
            self.assertEqual(h.last_payload_bytes, 32)
            self.assertIsNotNone(h.first_frame_monotonic_ms)
            self.assertIsNotNone(h.last_frame_monotonic_ms)

        asyncio.run(run())

    def test_v2_malformed_frame_counts_parse_fail_and_reject(self):
        async def run():
            h = _make_handler(hello_received=True, protocol_version=2)
            await h.handle_binary_audio(_v2_frame(version=1, payload=b"\x01" * 32))
            self.assertEqual(h.frames_received, 1)
            self.assertEqual(h.frames_parsed_ok, 0)
            self.assertEqual(h.frames_parse_failed, 1)
            self.assertEqual(h.websocket.closed_code, 1002)
            self.assertEqual(h.websocket.closed_reason, "invalid_audio_frame_v2")
            self.assertEqual(h.close_category, "protocol_reject")

        asyncio.run(run())

    def test_periodic_log_only_first_and_every_100(self):
        async def run():
            h = _make_handler(hello_received=True, protocol_version=2)
            for _ in range(250):
                await h.handle_binary_audio(_v2_frame(payload=b"\x01" * 32))
            self.assertEqual(h.frames_received, 250)
            # 仅第 1、100、200 帧打印 INFO，其余帧不打印
            self.assertEqual(h.logger.bind.return_value.info.call_count, 3)

        asyncio.run(run())

    def test_classify_tcp_reset(self):
        exc = websockets.exceptions.ConnectionClosedError(None, None, None)
        exc.__cause__ = ConnectionResetError("Connection reset by peer")
        self.assertEqual(
            ConnectionHandler._classify_close_exception(exc), "connection_reset"
        )

    def test_classify_eof(self):
        exc = websockets.exceptions.ConnectionClosedError(None, None, None)
        exc.__cause__ = EOFError("connection closed")
        self.assertEqual(ConnectionHandler._classify_close_exception(exc), "eof")

    def test_classify_normal_close(self):
        exc = websockets.exceptions.ConnectionClosedOK(None, None, None)
        self.assertEqual(
            ConnectionHandler._classify_close_exception(exc), "normal_close"
        )

    def test_classify_keepalive_timeout(self):
        h = _make_handler()
        self.assertEqual(
            h._classify_close(close_code=1011, reason="keepalive ping timeout"),
            "keepalive_timeout",
        )

    def test_classify_none_is_normal_close(self):
        h = _make_handler()
        self.assertEqual(h._classify_close(), "normal_close")

    def test_classify_not_overwritten_by_cleanup(self):
        """资源清理阶段调用 _classify_close() 不得覆盖已捕获的关闭类别。"""
        for category in ("connection_reset", "eof", "protocol_reject", "keepalive_timeout"):
            h = _make_handler()
            h.close_category = category
            self.assertEqual(h._classify_close(), category)

    def test_listen_start_snapshot_and_after_stats(self):
        async def run():
            h = _make_handler(hello_received=True, protocol_version=2)
            # 唤醒词预上传：2 帧在 listen=start 之前
            await h.handle_binary_audio(_v2_frame(payload=b"\x11" * 32))
            await h.handle_binary_audio(_v2_frame(payload=b"\x11" * 32))
            # listen=start 文本消息 → 触发快照（patch 掉真实处理器）
            with patch("core.connection.handleTextMessage", new=AsyncMock()):
                await h._route_message_inner(
                    json.dumps({"type": "listen", "state": "start"})
                )
            # 实时帧：3 帧在 start 之后
            await h.handle_binary_audio(_v2_frame(payload=b"\x22" * 40))
            await h.handle_binary_audio(_v2_frame(payload=b"\x22" * 40))
            await h.handle_binary_audio(_v2_frame(payload=b"\x22" * 40))

            self.assertTrue(h.listen_start_seen)
            self.assertEqual(h.frames_parsed_ok_at_listen_start, 2)
            self.assertEqual(h.total_payload_bytes_at_listen_start, 2 * 32)
            self.assertEqual(h.frames_parsed_ok, 5)
            self.assertEqual(h.total_payload_bytes, 2 * 32 + 3 * 40)
            fields = h._listen_stats_fields()
            self.assertIn("listen_start_seen=true", fields)
            self.assertIn("frames_after_listen_start=3", fields)
            self.assertIn("payload_bytes_after_listen_start=120", fields)

        asyncio.run(run())

    def test_listen_start_with_no_audio_after(self):
        async def run():
            h = _make_handler(hello_received=True, protocol_version=2)
            await h.handle_binary_audio(_v2_frame(payload=b"\x11" * 32))
            with patch("core.connection.handleTextMessage", new=AsyncMock()):
                await h._route_message_inner(
                    json.dumps({"type": "listen", "state": "start"})
                )
            fields = h._listen_stats_fields()
            self.assertIn("listen_start_seen=true", fields)
            self.assertIn("frames_after_listen_start=0", fields)
            self.assertIn("payload_bytes_after_listen_start=0", fields)
            self.assertIn("last_frame_after_listen_start_age_ms=n/a", fields)

        asyncio.run(run())

    def test_no_listen_start_yields_na(self):
        async def run():
            h = _make_handler(hello_received=True, protocol_version=2)
            await h.handle_binary_audio(_v2_frame(payload=b"\x11" * 32))
            fields = h._listen_stats_fields()
            self.assertIn("listen_start_seen=false", fields)
            self.assertIn("frames_after_listen_start=n/a", fields)
            self.assertIn("payload_bytes_after_listen_start=n/a", fields)
            self.assertIn("last_frame_after_listen_start_age_ms=n/a", fields)

        asyncio.run(run())


class TestMcpInitializeSize(unittest.TestCase):
    def test_initialize_message_over_1024_bytes(self):
        """MCP initialize 需为大包（> 1024 字节），验证下行链路可承载。"""
        from core.providers.tools.device_mcp.mcp_handler import send_mcp_initialize_message

        conn = MagicMock()
        conn.features = {"mcp": True}
        conn.websocket = AsyncMock()
        conn.config = {
            "server": {
                "public_base_url": "https://public.example.com",
                "auth_key": "test-auth-key-0123456789abcdef",
                "face": {"account_id": "acct-1234567890"},
                "face_enrollment_upload_signing_key": "independent-signing-key-0123456789abcdef",
            }
        }
        conn.headers = {"device-id": "aa:bb:cc:dd:ee:ff"}
        conn.device_id = "aa:bb:cc:dd:ee:ff"
        conn.session_id = "session-1"
        conn.outbound_mode = None
        conn.superseded = False
        conn._outbound_closed = False
        conn.server = MagicMock()

        async def _send_to_current(device_id, data, handler=None, **kwargs):
            await conn.websocket.send(data)
            return True

        conn.server.send_to_current = AsyncMock(side_effect=_send_to_current)
        conn.server.is_current_connection = MagicMock(return_value=True)
        conn.stop_event = None

        async def run():
            await send_mcp_initialize_message(conn)
            # 校验最终落到受控 websocket.send，且为合法 JSON-RPC initialize，且 > 1024 字节
            self.assertTrue(conn.websocket.send.called)
            raw = conn.websocket.send.call_args[0][0]
            obj = json.loads(raw)
            self.assertEqual(obj["type"], "mcp")
            self.assertEqual(obj["payload"]["method"], "initialize")
            self.assertGreater(
                len(raw), 1024, f"MCP initialize 包长应 > 1024，实际 {len(raw)}"
            )

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
