"""Unit tests for official-service JSONL trace logger. No paid upstream calls."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.utils.trace_log import (
    pcm_stats,
    reset_for_tests,
    sanitize,
    write_flags,
)


class Conn(SimpleNamespace):
    pass


def _read_jsonl(directory):
    lines = []
    if not os.path.isdir(directory):
        return lines
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".jsonl"):
            continue
        path = os.path.join(directory, name)
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    lines.append(json.loads(line))
    return lines


def _wait_written(inst, directory, minimum=1, timeout=2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        records = _read_jsonl(directory)
        if len(records) >= minimum:
            return records
        time.sleep(0.05)
    return _read_jsonl(directory)


class TraceLogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="trace-test-")
        self.flags = os.path.join(self.tmp, "flags.json")
        self.log_dir = os.path.join(self.tmp, "logs")
        os.makedirs(self.log_dir, exist_ok=True)
        self.inst = reset_for_tests(self.log_dir, self.flags)

    def tearDown(self):
        try:
            self.inst.close()
        except Exception:
            pass

    def test_disabled_writes_nothing(self):
        conn = Conn(session_id="s1", device_id="dev-a", agent_id="ag-1", listen_epoch=1)
        self.inst.emit("device.hello", conn, {"x": 1})
        time.sleep(0.2)
        self.assertEqual(_read_jsonl(self.log_dir), [])

    def test_flags_enable_and_filter(self):
        write_flags(
            self.flags,
            enabled=True,
            content_enabled=False,
            agent_ids=["ag-keep"],
            device_ids=["dev-keep"],
        )
        self.inst._load_flags(force=True)
        keep = Conn(session_id="s1", device_id="dev-keep", agent_id="other", listen_epoch=1)
        drop = Conn(session_id="s2", device_id="dev-drop", agent_id="ag-drop", listen_epoch=2)
        agent = Conn(session_id="s3", device_id="dev-x", agent_id="ag-keep", listen_epoch=3)
        self.inst.emit("device.hello", keep, {"ok": True})
        self.inst.emit("device.hello", drop, {"ok": False})
        self.inst.emit("device.hello", agent, {"ok": True})
        records = _wait_written(self.inst, self.log_dir, 2)
        devices = {r["ids"].get("device_id") for r in records if r.get("event") == "device.hello"}
        self.assertIn("dev-keep", devices)
        self.assertIn("dev-x", devices)
        self.assertNotIn("dev-drop", devices)

    def test_redact_nested_url_and_error(self):
        write_flags(self.flags, enabled=True, content_enabled=True)
        self.inst._load_flags(force=True)
        payload = {
            "Authorization": "Bearer sk-abcdefghijklmnopqrstuvwxyz",
            "nested": {
                "api_key": "secret-value-123456",
                "error": 'upstream failed cookie=abc url=https://x.example/?token=supersecret&q=1',
            },
            "stack": 'File "x.py"\nAuthorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.aaaaaaaabbbbbbbb.ccccccccdddddddd',
        }
        out = sanitize(payload, content_enabled=True)
        blob = json.dumps(out, ensure_ascii=False)
        self.assertNotIn("sk-abcdefghijklmnopqrstuvwxyz", blob)
        self.assertNotIn("secret-value-123456", blob)
        self.assertNotIn("supersecret", blob)
        self.assertIn("redacted", blob.lower())

    def test_audio_replaced_with_metadata(self):
        pcm = b"\x00\x01" * 960
        b64 = ("A" * 400)
        out = sanitize(
            {"audio": b64, "pcm": pcm, "text": "hello"},
            content_enabled=True,
        )
        self.assertTrue(out["audio"].get("omitted"))
        self.assertEqual(out["pcm"]["kind"], "bytes")
        self.assertEqual(out["text"], "hello")
        self.assertNotIn("AAAAAAAA", json.dumps(out))

    def test_content_switch_omits_prompt(self):
        hidden = sanitize(
            {"messages": [{"role": "user", "content": "private-utterance"}], "model": "qwen-plus"},
            content_enabled=False,
        )
        shown = sanitize(
            {"messages": [{"role": "user", "content": "private-utterance"}], "model": "qwen-plus"},
            content_enabled=True,
        )
        hidden_blob = json.dumps(hidden, ensure_ascii=False)
        self.assertNotIn("private-utterance", hidden_blob)
        self.assertTrue(hidden["messages"].get("content_omitted"))
        self.assertIn("private-utterance", json.dumps(shown, ensure_ascii=False))

    def test_sessions_do_not_mix_turns(self):
        write_flags(self.flags, enabled=True, content_enabled=True)
        self.inst._load_flags(force=True)
        a = Conn(session_id="sess-a", device_id="dev-a", agent_id="ag", listen_epoch=1, trace_turn_id=1)
        b = Conn(session_id="sess-b", device_id="dev-b", agent_id="ag", listen_epoch=2, trace_turn_id=2)
        self.inst.emit("asr.final", a, {"transcript": "alpha-turn"})
        self.inst.emit("asr.final", b, {"transcript": "beta-turn"})
        records = _wait_written(self.inst, self.log_dir, 2)
        finals = [r for r in records if r.get("event") == "asr.final"]
        by_session = {r["ids"]["session_id"]: r["payload"]["transcript"] for r in finals}
        self.assertEqual(by_session["sess-a"], "alpha-turn")
        self.assertEqual(by_session["sess-b"], "beta-turn")

    def test_queue_overflow_is_recorded(self):
        self.inst.close()
        self.inst.enabled = True
        self.inst.content_enabled = True
        conn = Conn(session_id="s", device_id="d", agent_id="a", listen_epoch=1)
        for i in range(80):
            self.inst.emit("noise", conn, {"i": i, "pad": "x" * 20})
        self.assertGreater(self.inst._dropped, 0)
        overflow = [item for item in self.inst._queue if item.get("event") == "trace.queue_overflow"]
        self.assertTrue(overflow)
        self.assertIn("dropped_total", overflow[0]["payload"])

    def test_emit_failure_does_not_raise(self):
        write_flags(self.flags, enabled=True)
        self.inst._load_flags(force=True)

        class Boom:
            def __getattr__(self, name):
                raise RuntimeError("boom")

        self.inst.emit("device.hello", Boom(), {"x": 1})

    def test_pcm_stats_unknown_when_odd_length(self):
        meta = pcm_stats(b"\x00", 16000, 1)
        self.assertEqual(meta["samples"], "unknown")
        even = pcm_stats(b"\x00\x00" * 160, 16000, 1)
        self.assertEqual(even["samples"], 160)
        self.assertEqual(even["duration_ms"], 10.0)


if __name__ == "__main__":
    unittest.main()
