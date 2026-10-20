"""Host-side regression for WebSocket message reassembly and reconnection.

Covers:
- Reassembly of a single WS frame split into multiple DATA events (1024+187)
- Reassembly of fragmented messages (text/binary + continuation frames)
- Bounded, self-clearing reassembly on oversized / out-of-order / stray-continuation input
- Auto-reconnect disabled at the driver so the upper layer always re-hellos
- Stale session id never reused across reconnects
- BinaryProtocol2/3 header + payload_size bounds validation before dereference
- No raw payload logging (MCP token not leaked)
"""

from __future__ import annotations

import json
import struct
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ESP_NETWORK = ROOT / "main" / "esp_network.h"
WS_PROTOCOL_CC = ROOT / "main" / "protocols" / "websocket_protocol.cc"
APPLICATION_CC = ROOT / "main" / "application.cc"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


# --- Host mirror of the EspWebSocket::HandleData reassembly state machine ---

TEXT = 0x01
BINARY = 0x02
CONT = 0x00

MAX_WS_MESSAGE_BYTES = 256 * 1024


class Reassembler:
    """Mirrors the firmware reassembly semantics, forwarding complete messages."""

    def __init__(self, max_bytes: int = MAX_WS_MESSAGE_BYTES):
        self.max_bytes = max_bytes
        self.buf = bytearray()
        self.in_progress = False       # logical message in progress
        self.is_binary = False
        self.frame_in_progress = False
        self.frame_received = 0
        self.delivered = []            # (bytes, binary) complete messages

    def _reset(self):
        self.buf = bytearray()
        self.in_progress = False
        self.is_binary = False
        self.frame_in_progress = False
        self.frame_received = 0

    def handle(self, data: bytes, op_code: int, fin: bool,
               payload_offset: int, payload_len: int) -> None:
        data_len = len(data)
        if (data_len < 0 or payload_len < 0 or payload_offset < 0
                or payload_offset > payload_len
                or data_len > payload_len - payload_offset):
            self._reset()
            return

        is_data = op_code in (TEXT, BINARY, CONT)

        if payload_offset == 0:
            if self.frame_in_progress:
                self._reset()
            if not is_data:
                return
            if op_code == CONT:
                if not self.in_progress:
                    self._reset()
                    return
            else:
                self.buf = bytearray()
                self.in_progress = True
                self.is_binary = (op_code == BINARY)
            self.frame_in_progress = True
            self.frame_received = 0
        else:
            if not self.frame_in_progress or not self.in_progress:
                self._reset()
                return
            if payload_offset != self.frame_received:
                self._reset()
                return

        if data:
            if len(self.buf) + data_len > self.max_bytes:
                self._reset()
                return
            self.buf += data
        self.frame_received += data_len

        if payload_offset + data_len < payload_len:
            return

        self.frame_in_progress = False
        self.frame_received = 0

        if not fin:
            return

        binary = self.is_binary
        msg = bytes(self.buf)
        self.buf = bytearray()
        self.in_progress = False
        if msg:
            self.delivered.append((msg, binary))


def feed_frame(r: Reassembler, op: int, fin: bool, chunks: list) -> None:
    """Feed one WS frame split into one or more DATA-event chunks."""
    total = sum(len(c) for c in chunks)
    off = 0
    for c in chunks:
        r.handle(c, op, fin, off, total)
        off += len(c)


class ReassemblyModel(unittest.TestCase):
    def test_text_single_frame(self):
        r = Reassembler()
        feed_frame(r, TEXT, True, [b'{"type":"hello"}'])
        self.assertEqual(r.delivered, [(b'{"type":"hello"}', False)])

    def test_single_frame_split_two_chunks(self):
        # A 1211-byte text frame delivered as two DATA events (1024 + 187),
        # both op=TEXT, fin=True, same payload_len. Must deliver exactly once.
        prefix = b'{"type":"mcp","data":"'
        suffix = b'"}'
        pad_len = 1211 - len(prefix) - len(suffix)
        full = prefix + (b'A' * pad_len) + suffix
        self.assertEqual(len(full), 1211)

        r = Reassembler()
        r.handle(full[:1024], TEXT, True, 0, 1211)
        r.handle(full[1024:], TEXT, True, 1024, 1211)
        self.assertEqual(len(r.delivered), 1)
        msg, binary = r.delivered[0]
        self.assertFalse(binary)
        self.assertEqual(msg, full)
        # The reassembled payload must be a complete, parseable JSON document.
        parsed = json.loads(msg.decode("utf-8"))
        self.assertEqual(parsed["type"], "mcp")
        self.assertEqual(parsed["data"], "A" * pad_len)

    def test_single_frame_three_chunks(self):
        full = b'{"n":1,"s":"' + (b'x' * 500) + b'"}'
        r = Reassembler()
        r.handle(full[:200], TEXT, True, 0, len(full))
        r.handle(full[200:450], TEXT, True, 200, len(full))
        r.handle(full[450:], TEXT, True, 450, len(full))
        self.assertEqual(r.delivered, [(full, False)])

    def test_text_fragmented(self):
        r = Reassembler()
        feed_frame(r, TEXT, False, [b'{"type":"mcp","cap'])
        feed_frame(r, CONT, True, [b'ability":1}'])
        self.assertEqual(r.delivered, [(b'{"type":"mcp","capability":1}', False)])

    def test_text_fragmented_multi_continuation(self):
        r = Reassembler()
        feed_frame(r, TEXT, False, [b'{"a":'])
        feed_frame(r, CONT, False, [b'1,'])
        feed_frame(r, CONT, True, [b'"b":2}'])
        self.assertEqual(r.delivered, [(b'{"a":1,"b":2}', False)])

    def test_fragmented_continuation_split_two_chunks(self):
        # Continuation frame itself split across two DATA events.
        r = Reassembler()
        feed_frame(r, TEXT, False, [b'{"data":"'])
        cont = b'A' * 300 + b'"}'
        feed_frame(r, CONT, True, [cont[:200], cont[200:]])
        self.assertEqual(r.delivered, [(b'{"data":"' + cont, False)])

    def test_binary_fragmented(self):
        r = Reassembler()
        feed_frame(r, BINARY, False, [bytes([0x00, 0x02, 0x00, 0x00])])
        feed_frame(r, CONT, True, [bytes([0x00, 0x00, 0x00, 0x01, 0xAA])])
        self.assertEqual(
            r.delivered,
            [(bytes([0x00, 0x02, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01, 0xAA]), True)],
        )

    def test_stray_continuation_dropped(self):
        r = Reassembler()
        feed_frame(r, CONT, True, [b'{"x":1}'])
        self.assertEqual(r.delivered, [])

    def test_new_text_interrupts_incomplete_message(self):
        r = Reassembler()
        feed_frame(r, TEXT, False, [b'{"incomplete'])
        feed_frame(r, TEXT, True, [b'{"complete":1}'])
        self.assertEqual(r.delivered, [(b'{"complete":1}', False)])

    def test_oversized_message_dropped(self):
        r = Reassembler(max_bytes=8)
        feed_frame(r, TEXT, False, [b'123456789'])
        feed_frame(r, CONT, True, [b'0'])
        self.assertEqual(r.delivered, [])

    def test_empty_final_message_not_delivered(self):
        r = Reassembler()
        feed_frame(r, TEXT, True, [b''])
        self.assertEqual(r.delivered, [])

    def test_bad_offset_dropped(self):
        r = Reassembler()
        r.handle(b'{"x":1}', TEXT, True, 5, 6)  # offset+len overruns payload_len
        self.assertEqual(r.delivered, [])

    def test_mid_frame_gap_dropped(self):
        r = Reassembler()
        r.handle(b'A' * 10, TEXT, True, 0, 100)   # first chunk, frame incomplete
        r.handle(b'B' * 10, TEXT, True, 40, 100)  # gap (expected offset 10)
        self.assertEqual(r.delivered, [])


# --- BinaryProtocol2/3 bounds mirror ---
# BinaryProtocol2 (packed): version(u16) type(u16) reserved(u32) timestamp(u32)
# payload_size(u32) = 16 bytes header. BinaryProtocol3: type(u8) reserved(u8)
# payload_size(u16) = 4 bytes header.
BP2_HEADER = 16
BP3_HEADER = 4


def parse_bp2_payload(data: bytes):
    if len(data) < BP2_HEADER:
        raise ValueError("too short")
    version = struct.unpack(">H", data[0:2])[0]
    payload_size = struct.unpack(">I", data[12:16])[0]
    if version != 2:
        raise ValueError("version mismatch")
    if payload_size > len(data) - BP2_HEADER:
        raise ValueError("payload_size exceeds remaining")
    return data[BP2_HEADER:BP2_HEADER + payload_size]


def parse_bp3_payload(data: bytes):
    if len(data) < BP3_HEADER:
        raise ValueError("too short")
    payload_size = struct.unpack(">H", data[2:4])[0]
    if payload_size > len(data) - BP3_HEADER:
        raise ValueError("payload_size exceeds remaining")
    return data[BP3_HEADER:BP3_HEADER + payload_size]


class BinaryBoundsModel(unittest.TestCase):
    def test_bp2_valid(self):
        payload = b"\x01\x02\x03"
        pkt = struct.pack(">HHIII", 2, 0, 0, 0, len(payload)) + payload
        self.assertEqual(parse_bp2_payload(pkt), payload)

    def test_bp2_too_short(self):
        with self.assertRaises(ValueError):
            parse_bp2_payload(b"\x00\x02")

    def test_bp2_version_mismatch(self):
        pkt = struct.pack(">HHIII", 3, 0, 0, 0, 0)
        with self.assertRaises(ValueError):
            parse_bp2_payload(pkt)

    def test_bp2_payload_size_exceeds(self):
        pkt = struct.pack(">HHIII", 2, 0, 0, 0, 100) + b"\x01"
        with self.assertRaises(ValueError):
            parse_bp2_payload(pkt)

    def test_bp3_valid_and_bounds(self):
        pkt = struct.pack(">BBH", 0, 0, 3) + b"\x01\x02\x03"
        self.assertEqual(parse_bp3_payload(pkt), b"\x01\x02\x03")
        with self.assertRaises(ValueError):
            parse_bp3_payload(struct.pack(">BBH", 0, 0, 100) + b"\x01")


# --- Source contracts ---

class SourceContracts(unittest.TestCase):
    def test_auto_reconnect_disabled(self):
        text = read(ESP_NETWORK)
        self.assertIn("disable_auto_reconnect = true", text)
        # The old non-disabling knob must not remain as the sole mechanism.
        self.assertNotIn("reconnect_timeout_ms = 0", text)

    def test_reassembly_present(self):
        text = read(ESP_NETWORK)
        self.assertIn("HandleData", text)
        self.assertIn("kMaxWsMessageBytes", text)
        self.assertIn("ResetReceiveState", text)
        self.assertIn("WS_TRANSPORT_OPCODES_CONT", text)
        self.assertIn("WS_TRANSPORT_OPCODES_TEXT", text)
        self.assertIn("WS_TRANSPORT_OPCODES_BINARY", text)
        # New: frame-level reassembly driven by payload_offset / payload_len.
        self.assertIn("payload_offset == 0", text)
        self.assertIn("payload_offset + data_len < payload_len", text)
        self.assertIn("frame_in_progress_", text)
        self.assertIn("frame_received_", text)

    def test_tls_not_weakened(self):
        text = read(ESP_NETWORK)
        self.assertIn("crt_bundle_attach = esp_crt_bundle_attach", text)
        self.assertNotIn("skip_cert_common_name_check = true", text)

    def test_session_not_reused(self):
        text = read(WS_PROTOCOL_CC)
        # Cleared at channel open and on disconnect.
        self.assertGreaterEqual(text.count("session_id_.clear()"), 2)

    def test_no_raw_payload_logging(self):
        text = read(WS_PROTOCOL_CC)
        self.assertNotIn("data: %s", text)
        # The JSON parse error path must log length + error offset only.
        self.assertIn("err_offset=%u", text)

    def test_binary_bounds_validation(self):
        text = read(WS_PROTOCOL_CC)
        self.assertIn("BinaryProtocol2 too short", text)
        self.assertIn("BinaryProtocol2 version mismatch", text)
        self.assertIn("BinaryProtocol2 payload_size=%u exceeds", text)
        self.assertIn("BinaryProtocol3 too short", text)
        self.assertIn("BinaryProtocol3 payload_size=%u exceeds", text)

    def test_upload_queue_cleared_on_disconnect(self):
        text = read(APPLICATION_CC)
        # ResetUploadQueues is invoked on audio-channel-closed before going idle.
        self.assertIn("ResetUploadQueues()", text)


if __name__ == "__main__":
    unittest.main()
