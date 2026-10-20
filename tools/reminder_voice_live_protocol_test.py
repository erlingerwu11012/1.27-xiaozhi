#!/usr/bin/env python3
"""Simulate the ESP32 reminder-voice protocol against a running RealEcho server.

Credentials (never printed in full):
  REALECHO_WSS_URL, REALECHO_DEVICE_ID, REALECHO_CLIENT_ID, REALECHO_TOKEN

Optional dotenv files (KEY=VALUE, not committed):
  tools/.realecho_live.env
  %USERPROFILE%/.realecho_live.env

The live test uses the current Realecho WSS service configured through
REALECHO_WSS_URL. Set that variable explicitly for a live run; no direct-IP
override is part of the firmware build.

Local tests always run (cache binding, no cross-instance play, N>=2 consult).
Live WSS/HTTP tests run only when credentials are present.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import ssl
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOGICAL_HOST = "www.realecho.cn"
DEFAULT_CONNECT_IP = "121.40.239.140"
DEFAULT_WSS_PATH = "/xiaozhi/v1/"
MAX_ASSET_BYTES = 16384

LIVE_RESULTS: list[dict[str, Any]] = []


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv(ROOT / "tools" / ".realecho_live.env")
_load_dotenv(Path.home() / ".realecho_live.env")


def cache_name(
    instance_id: str,
    voice_revision: int,
    phase: str,
    sha256: str,
) -> str:
    key = "\x1f".join((instance_id, str(voice_revision), phase, sha256))
    return "r" + hashlib.sha256(key.encode()).hexdigest()[:25] + ".ogg"


def redact(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "***"
    return value[:4] + "…" + value[-2:]


def redact_url(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    return f"{parsed.scheme}://{host}{parsed.path}"


def is_lower_hex_sha256(value: str) -> bool:
    return len(value) == 64 and all(ch in "0123456789abcdef" for ch in value)


def has_ogg_magic(data: bytes) -> bool:
    return data[:4] == b"OggS"


def credentials() -> dict[str, str]:
    return {
        "wss_url": os.environ.get("REALECHO_WSS_URL", "").strip(),
        "device_id": os.environ.get("REALECHO_DEVICE_ID", "").strip(),
        "client_id": os.environ.get("REALECHO_CLIENT_ID", "").strip(),
        "token": os.environ.get("REALECHO_TOKEN", "").strip(),
        "logical_host": os.environ.get(
            "REALECHO_LOGICAL_HOST", DEFAULT_LOGICAL_HOST
        ).strip()
        or DEFAULT_LOGICAL_HOST,
        "connect_ip": os.environ.get(
            "REALECHO_CONNECT_IP", DEFAULT_CONNECT_IP
        ).strip()
        or DEFAULT_CONNECT_IP,
    }


def have_live_credentials() -> bool:
    creds = credentials()
    return bool(creds["device_id"] and creds["client_id"] and creds["token"])


def resolve_wss_url(creds: dict[str, str]) -> str:
    url = creds["wss_url"]
    if url:
        return url
    return f"wss://{creds['logical_host']}{DEFAULT_WSS_PATH}"


def should_force_direct_ip(url: str, creds: dict[str, str]) -> bool:
    host = (urlparse(url).hostname or "").lower()
    if host in {creds["connect_ip"], creds["logical_host"].lower()}:
        return True
    if host in {"www.realecho.cn"}:
        return True
    return False


def record(step: str, ok: bool, **detail: Any) -> None:
    row = {"step": step, "ok": ok, **detail}
    LIVE_RESULTS.append(row)


@dataclass
class CachedVoice:
    instance_id: str
    voice_revision: int
    phase: str
    sha256: str
    path: Path

    def matches(self, instance_id: str, voice_revision: int, phase: str) -> bool:
        return (
            self.instance_id == instance_id
            and self.voice_revision == voice_revision
            and self.phase == phase
            and self.path.is_file()
            and has_ogg_magic(self.path.read_bytes())
        )


class DuePlaySelector:
    """Host stand-in for PlayDueLocalOrChime + begin_broadcast ordering."""

    def __init__(self) -> None:
        self.files: dict[str, CachedVoice] = {}
        self.played: list[str] = []
        self.voice_requests: list[str] = []
        self.consulted = False

    def bind(self, asset: CachedVoice) -> None:
        self.files[asset.instance_id] = asset

    def play_due(self, instance_id: str, voice_revision: int = 1) -> str:
        asset = self.files.get(instance_id)
        if asset and asset.matches(instance_id, voice_revision, "due"):
            self.played.append(instance_id)
            return "played_cache"
        self.voice_requests.append(instance_id)
        return "request"

    def on_due(self, instance_ids: list[str], presence: bool) -> str:
        if not presence:
            return "chime_only"
        if len(instance_ids) >= 2:
            self.consulted = True
            return "llm_consult"
        return self.play_due(instance_ids[0])

    def begin_broadcast(self, instance_ids: list[str]) -> list[str]:
        played = []
        for instance_id in instance_ids:
            if self.play_due(instance_id) == "played_cache":
                played.append(instance_id)
        return played


class CacheBindingTests(unittest.TestCase):
    def test_two_instances_bind_distinct_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            a = cache_name("note:1:1001", 1, "due", "a" * 64)
            b = cache_name("note:2:1002", 1, "due", "b" * 64)
            self.assertNotEqual(a, b)
            (root / a).write_bytes(b"OggS-A")
            (root / b).write_bytes(b"OggS-B")
            selector = DuePlaySelector()
            selector.bind(
                CachedVoice("note:1:1001", 1, "due", "a" * 64, root / a)
            )
            selector.bind(
                CachedVoice("note:2:1002", 1, "due", "b" * 64, root / b)
            )
            self.assertEqual(selector.play_due("note:1:1001"), "played_cache")
            self.assertEqual(selector.play_due("note:2:1002"), "played_cache")
            self.assertEqual(selector.played, ["note:1:1001", "note:2:1002"])

    def test_due_does_not_play_other_instance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            name = cache_name("note:a:1", 1, "due", "c" * 64)
            (root / name).write_bytes(b"OggS-A")
            selector = DuePlaySelector()
            selector.bind(
                CachedVoice("note:a:1", 1, "due", "c" * 64, root / name)
            )
            self.assertEqual(selector.play_due("note:b:1"), "request")
            self.assertEqual(selector.played, [])
            self.assertEqual(selector.voice_requests, ["note:b:1"])

    def test_non_oggs_is_not_playable_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            name = cache_name("note:x:1", 1, "due", "d" * 64)
            (root / name).write_bytes(b"XXXX-not-ogg")
            selector = DuePlaySelector()
            selector.bind(
                CachedVoice("note:x:1", 1, "due", "d" * 64, root / name)
            )
            self.assertEqual(selector.play_due("note:x:1"), "request")
            self.assertEqual(selector.played, [])

    def test_empty_room_chime_only(self) -> None:
        selector = DuePlaySelector()
        self.assertEqual(selector.on_due(["note:1:1"], presence=False), "chime_only")
        self.assertEqual(selector.played, [])

    def test_backlog_requires_begin_broadcast(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            selector = DuePlaySelector()
            for instance_id, digest in (
                ("note:a:1", "a" * 64),
                ("note:b:1", "b" * 64),
            ):
                name = cache_name(instance_id, 1, "due", digest)
                (root / name).write_bytes(b"OggS" + instance_id.encode())
                selector.bind(
                    CachedVoice(instance_id, 1, "due", digest, root / name)
                )
            self.assertEqual(
                selector.on_due(["note:a:1", "note:b:1"], presence=True),
                "llm_consult",
            )
            self.assertEqual(selector.played, [])
            order = selector.begin_broadcast(["note:a:1", "note:b:1"])
            self.assertEqual(order, ["note:a:1", "note:b:1"])

    def test_firmware_hello_and_download_contracts(self) -> None:
        hello = (
            ROOT / "main/protocols/websocket_protocol.cc"
        ).read_text(encoding="utf-8")
        voice = (ROOT / "main/reminder_voice_service.cc").read_text(
            encoding="utf-8"
        )
        self.assertIn('"type", "hello"', hello)
        self.assertIn('"mcp", true', hello)
        self.assertIn('SetHeader("Device-Id"', hello)
        self.assertIn('SetHeader("Device-Id"', voice)
        self.assertIn("voice asset is not OggS", voice)
        self.assertIn("16384", voice)


def _auth_header(token: str) -> str:
    if " " not in token:
        return "Bearer " + token
    return token


def _json_loads_maybe(message: Any) -> dict[str, Any] | None:
    if isinstance(message, bytes):
        return None
    if not isinstance(message, str):
        return None
    try:
        data = json.loads(message)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


class ForcedIp:
    def __init__(self, hostname: str, ip: str) -> None:
        self.hostname = hostname.lower()
        self.ip = ip
        self._original = socket.getaddrinfo

    def __enter__(self) -> None:
        hostname = self.hostname
        ip = self.ip
        original = self._original

        def getaddrinfo(host, port, *args, **kwargs):  # type: ignore[no-untyped-def]
            lookup = ip if str(host).lower() == hostname else host
            return original(lookup, port, *args, **kwargs)

        socket.getaddrinfo = getaddrinfo  # type: ignore[assignment]
        return None

    def __exit__(self, *exc: object) -> None:
        socket.getaddrinfo = self._original  # type: ignore[assignment]


def https_get(
    url: str,
    device_id: str | None,
    timeout: float = 20.0,
) -> tuple[int, bytes]:
    if not url.startswith("https://"):
        raise AssertionError("voice asset URL must be https")
    headers = {}
    if device_id is not None:
        headers["Device-Id"] = device_id
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return int(response.status), response.read()
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read() if exc.fp else b""


@unittest.skipUnless(
    have_live_credentials(),
    "REALECHO_DEVICE_ID / CLIENT_ID / TOKEN are required for live WSS",
)
class LiveProtocolTests(unittest.TestCase):
    def test_hello_mcp_presynthesis_download(self) -> None:
        import asyncio

        asyncio.run(self._run())

    async def _run(self) -> None:
        import asyncio
        import websockets

        creds = credentials()
        url = resolve_wss_url(creds)
        token = _auth_header(creds["token"])
        headers = {
            "Authorization": token,
            "Protocol-Version": "1",
            "Device-Id": creds["device_id"],
            "Client-Id": creds["client_id"],
        }
        record("connect_prepare", True, url=redact_url(url))
        ssl_ctx = ssl.create_default_context()
        force_ip = should_force_direct_ip(url, creds)
        hello = {
            "type": "hello",
            "version": 1,
            "transport": "websocket",
            "features": {"mcp": True},
            "audio_params": {
                "format": "opus",
                "sample_rate": 16000,
                "channels": 1,
                "frame_duration": 60,
            },
        }
        now = int(time.time())
        notes = [
            {
                "instance_id": f"note:live1:{now}",
                "title": "live protocol tea",
                "detail": "一次性提醒",
            },
            {
                "instance_id": f"note:live2:{now}",
                "title": "live protocol walk",
                "detail": "一次性提醒",
            },
        ]
        assets: dict[str, dict[str, Any]] = {}
        session_id = ""

        async def reader(ws: Any) -> None:
            nonlocal session_id
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline and len(assets) < 2:
                try:
                    message = await asyncio.wait_for(ws.recv(), timeout=8)
                except asyncio.TimeoutError:
                    continue
                data = _json_loads_maybe(message)
                if not data:
                    continue
                msg_type = data.get("type")
                if msg_type == "hello":
                    session_id = str(data.get("session_id") or "")
                    record("hello", bool(session_id), session_len=len(session_id))
                elif msg_type == "mcp":
                    payload = data.get("payload") or {}
                    method = payload.get("method")
                    req_id = payload.get("id", 0)
                    if method == "initialize":
                        reply = {
                            "session_id": session_id,
                            "type": "mcp",
                            "payload": {
                                "jsonrpc": "2.0",
                                "id": req_id,
                                "result": {
                                    "protocolVersion": "2024-11-05",
                                    "capabilities": {"tools": {}},
                                    "serverInfo": {
                                        "name": "live-sim",
                                        "version": "0",
                                    },
                                },
                            },
                        }
                        await ws.send(json.dumps(reply, ensure_ascii=False))
                        record("mcp_initialize", True)
                    elif method == "tools/list":
                        reply = {
                            "session_id": session_id,
                            "type": "mcp",
                            "payload": {
                                "jsonrpc": "2.0",
                                "id": req_id,
                                "result": {"tools": []},
                            },
                        }
                        await ws.send(json.dumps(reply, ensure_ascii=False))
                elif msg_type == "reminder_voice_asset":
                    instance_id = str(data.get("instance_id") or "")
                    assets[instance_id] = data
                    record(
                        "asset",
                        True,
                        instance=instance_id,
                        format=data.get("format"),
                        bytes=data.get("bytes"),
                    )
                elif msg_type == "reminder_voice_error":
                    record(
                        "asset_error",
                        False,
                        instance=str(data.get("instance_id") or ""),
                        code=str(data.get("code") or data.get("error") or ""),
                    )

        context = ForcedIp(creds["logical_host"], creds["connect_ip"]) if force_ip else None
        try:
            if context:
                context.__enter__()
            async with websockets.connect(
                url,
                additional_headers=headers,
                ssl=ssl_ctx,
                open_timeout=20,
                close_timeout=5,
                max_size=2 * 1024 * 1024,
            ) as ws:
                record("wss_open", True)
                reader_task = asyncio.create_task(reader(ws))
                await ws.send(json.dumps(hello, ensure_ascii=False))
                await asyncio.sleep(1.5)
                for note in notes:
                    request = {
                        "type": "reminder_voice_request",
                        "instance_id": note["instance_id"],
                        "revision": 1,
                        "voice_revision": 1,
                        "recipient_person_id": "all",
                        "presence_generation": 1,
                        "source_type": "note",
                        "title": note["title"],
                        "detail": note["detail"],
                        "pending_count": 2,
                        "announce_pending_count": True,
                        "missed_occurrence": False,
                        "privacy_safe_required": False,
                    }
                    await ws.send(json.dumps(request, ensure_ascii=False))
                    record("voice_request", True, instance=note["instance_id"])
                try:
                    await asyncio.wait_for(reader_task, timeout=45)
                except asyncio.TimeoutError:
                    reader_task.cancel()
        finally:
            if context:
                context.__exit__()

        self.assertTrue(session_id, "server hello did not assign a session")
        self.assertEqual(len(assets), 2, f"expected 2 assets, got {list(assets)}")
        paths = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for note in notes:
                asset = assets[note["instance_id"]]
                self.assertEqual(asset.get("format"), "ogg_opus")
                url_value = str(asset.get("url") or "")
                self.assertTrue(url_value.startswith("https://"), url_value[:12])
                sha256 = str(asset.get("sha256") or "")
                self.assertTrue(is_lower_hex_sha256(sha256))
                byte_count = int(asset.get("bytes") or 0)
                self.assertGreaterEqual(byte_count, 1)
                self.assertLessEqual(byte_count, MAX_ASSET_BYTES)
                status, body = https_get(url_value, creds["device_id"])
                record(
                    "https_get",
                    status == 200,
                    status=status,
                    bytes=len(body),
                    url=redact_url(url_value),
                )
                self.assertEqual(status, 200)
                self.assertEqual(len(body), byte_count)
                self.assertTrue(has_ogg_magic(body))
                digest = hashlib.sha256(body).hexdigest()
                self.assertEqual(digest, sha256)
                dest = root / cache_name(
                    note["instance_id"], 1, str(asset.get("phase") or "due"), sha256
                )
                dest.write_bytes(body)
                paths.append(dest)
                missing_status, _ = https_get(url_value, None)
                record("https_get_no_device_id", missing_status in {401, 403},
                       status=missing_status)
                wrong_status, _ = https_get(url_value, "00:00:00:00:00:00")
                record(
                    "https_get_wrong_device_id",
                    wrong_status in {401, 403},
                    status=wrong_status,
                )
            self.assertNotEqual(paths[0].name, paths[1].name)
        print("LIVE_STEPS", json.dumps(LIVE_RESULTS, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main(verbosity=2)
