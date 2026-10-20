"""Independent full-chain JSONL test logger for official ASR/TTS/LLM.

Default off. Failures never interrupt dialogue. Audio bytes and secrets
are never written as plaintext.
"""
from __future__ import annotations

import json
import os
import re
import stat
import threading
import time
import traceback
from collections import deque
from datetime import datetime, timedelta
from typing import Any, Iterable, Optional
from urllib.parse import parse_qsl, urlsplit, urlunsplit, urlencode

TAG = "trace_log"

DEFAULT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "logs",
    "trace",
)
DEFAULT_FLAGS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "trace_log.flags.json",
)

MAX_QUEUE = 2000
MAX_EVENT_CHARS = 65536
MAX_STRING_CHARS = 16000
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_TOTAL_BYTES = 50 * 1024 * 1024
MAX_FILES = 5
RETENTION_DAYS = 3
FLAGS_POLL_SEC = 2.0
AUDIO_B64_MIN = 240

SENSITIVE_KEY_RE = re.compile(
    r"(authorization|api[_-]?key|access[_-]?token|refresh[_-]?token|"
    r"secret|password|passwd|passphrase|private[_-]?key|cookie|set-cookie|"
    r"credential|signature|jwt|bearer|sk$|token$|x-api-key|"
    r"connection[_-]?string|database[_-]?url|mysql|redis[_-]?url|"
    r"oneapi|dashscope|openai[_-]?key)",
    re.I,
)
SENSITIVE_QUERY = {
    "token",
    "access_token",
    "refresh_token",
    "api_key",
    "apikey",
    "key",
    "signature",
    "sign",
    "auth",
    "authorization",
    "password",
    "secret",
    "jwt",
}
AUDIO_KEYS = {
    "audio",
    "pcm",
    "opus",
    "wav",
    "image",
    "image_url",
    "audio_data",
    "binary",
    "payload_audio",
    "speech",
    "input_audio",
}
CONTENT_KEYS = {
    "text",
    "transcript",
    "stash",
    "content",
    "messages",
    "prompt",
    "input",
    "arguments",
    "delta",
    "system",
    "user",
    "assistant",
    "hint",
    "query",
    "content_detail",
    "preview",
}
SK_RE = re.compile(r"(sk-[A-Za-z0-9_\-]{8,})")
BEARER_RE = re.compile(r"(?i)(bearer\s+)([A-Za-z0-9_\-\.=]+)")
JWT_RE = re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}")
B64_RE = re.compile(r"^[A-Za-z0-9+/=\s]{240,}$")

import contextvars

_TRACE_CONN: contextvars.ContextVar = contextvars.ContextVar("trace_conn", default=None)
_LOCK = threading.RLock()
_INSTANCE: Optional["TraceLog"] = None


def bind_conn(conn):
    return _TRACE_CONN.set(conn)


def reset_conn(token):
    try:
        _TRACE_CONN.reset(token)
    except Exception:
        pass


def current_conn():
    try:
        return _TRACE_CONN.get()
    except Exception:
        return None


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="milliseconds")


def _is_mapping(value: Any) -> bool:
    return isinstance(value, dict)


def pcm_stats(pcm: bytes, sample_rate: Optional[int] = 16000, channels: Optional[int] = 1) -> dict:
    """Peak/RMS/duration from PCM16. Unknown fields stay 'unknown'."""
    meta = {
        "kind": "pcm",
        "encoding": "pcm_s16le",
        "bytes": len(pcm) if pcm is not None else 0,
        "sample_rate": sample_rate if sample_rate else "unknown",
        "channels": channels if channels else "unknown",
        "samples": "unknown",
        "duration_ms": "unknown",
        "peak": "unknown",
        "rms": "unknown",
    }
    if not pcm:
        return meta
    if len(pcm) % 2 != 0:
        meta["samples"] = "unknown"
        return meta
    samples = len(pcm) // 2
    meta["samples"] = samples
    if isinstance(sample_rate, int) and sample_rate > 0 and isinstance(channels, int) and channels > 0:
        meta["duration_ms"] = round(samples * 1000.0 / (sample_rate * channels), 3)
    try:
        import array

        arr = array.array("h")
        arr.frombytes(pcm)
        if arr:
            peak = max(abs(s) for s in arr)
            mean_sq = sum(s * s for s in arr) / len(arr)
            meta["peak"] = int(peak)
            meta["rms"] = round(mean_sq ** 0.5, 3)
    except Exception:
        pass
    return meta


def audio_meta(
    value: Any,
    *,
    encoding: str = "unknown",
    sample_rate: Any = "unknown",
    channels: Any = "unknown",
    seq: Any = None,
    duration_ms: Any = "unknown",
    extra: Optional[dict] = None,
) -> dict:
    nbytes = 0
    kind = "audio"
    if isinstance(value, (bytes, bytearray, memoryview)):
        nbytes = len(value)
        kind = "bytes"
    elif isinstance(value, str):
        nbytes = len(value.encode("utf-8", errors="replace"))
        kind = "base64_or_text"
        encoding = encoding if encoding != "unknown" else "base64?"
    elif value is None:
        nbytes = 0
    else:
        nbytes = len(str(value).encode("utf-8", errors="replace"))
    meta = {
        "kind": kind,
        "encoding": encoding,
        "bytes": nbytes,
        "sample_rate": sample_rate if sample_rate is not None else "unknown",
        "channels": channels if channels is not None else "unknown",
        "seq": seq,
        "duration_ms": duration_ms,
        "omitted": True,
    }
    if extra:
        meta.update(extra)
    return meta


def redact_url(url: Any) -> Any:
    if not isinstance(url, str) or "://" not in url:
        return url
    try:
        parts = urlsplit(url)
        query = []
        for k, v in parse_qsl(parts.query, keep_blank_values=True):
            if k.lower() in SENSITIVE_QUERY or SENSITIVE_KEY_RE.search(k or ""):
                query.append((k, f"<redacted:len={len(v)}>"))
            else:
                query.append((k, redact_text(v)))
        netloc = parts.netloc
        if "@" in netloc:
            user, host = netloc.rsplit("@", 1)
            netloc = f"<redacted-user>@{host}"
        return urlunsplit(
            (parts.scheme, netloc, parts.path, urlencode(query), parts.fragment)
        )
    except Exception:
        return "<unparseable-url>"


def redact_text(text: Any) -> Any:
    if not isinstance(text, str):
        return text
    out = SK_RE.sub(lambda m: f"<redacted-sk:len={len(m.group(1))}>", text)
    out = BEARER_RE.sub(lambda m: f"{m.group(1)}<redacted:len={len(m.group(2))}>", out)
    out = JWT_RE.sub(lambda m: f"<redacted-jwt:len={len(m.group(0))}>", out)
    if "://" in out:
        # Replace credentialed URLs even when nested in free text.
        def _url_sub(match):
            return redact_url(match.group(0))

        out = re.sub(r"https?://[^\s\"']+", _url_sub, out)
        out = re.sub(r"wss?://[^\s\"']+", _url_sub, out)
    return out


def _looks_base64_audio(text: str) -> bool:
    if len(text) < AUDIO_B64_MIN:
        return False
    sample = text.strip()
    if not B64_RE.match(sample[:4000] if len(sample) > 4000 else sample):
        return False
    # High density of base64 alphabet and length typical of audio frames.
    return True


def _omit_content(value: Any) -> dict:
    if isinstance(value, str):
        return {"content_omitted": True, "chars": len(value)}
    if isinstance(value, list):
        return {"content_omitted": True, "items": len(value)}
    if isinstance(value, dict):
        return {"content_omitted": True, "keys": sorted(value.keys())[:40]}
    return {"content_omitted": True, "type": type(value).__name__}


def sanitize(
    value: Any,
    *,
    content_enabled: bool = False,
    depth: int = 0,
    key_hint: str = "",
) -> Any:
    if depth > 24:
        return {"truncated": True, "reason": "max_depth"}
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, (bytes, bytearray, memoryview)):
        return audio_meta(value, encoding="bytes")
    if isinstance(value, Exception):
        return {
            "type": type(value).__name__,
            "message": redact_text(str(value))[:MAX_STRING_CHARS],
        }
    if isinstance(value, dict):
        out = {}
        for raw_k, raw_v in value.items():
            k = str(raw_k)
            kl = k.lower()
            if SENSITIVE_KEY_RE.search(kl):
                if isinstance(raw_v, str):
                    out[k] = f"<redacted:len={len(raw_v)}>"
                elif isinstance(raw_v, (bytes, bytearray)):
                    out[k] = f"<redacted:bytes={len(raw_v)}>"
                else:
                    out[k] = "<redacted>"
                continue
            if kl in AUDIO_KEYS or kl.endswith("_audio") or kl.endswith("_pcm"):
                extra = {}
                if isinstance(raw_v, str):
                    extra["chars"] = len(raw_v)
                out[k] = audio_meta(raw_v, encoding="payload", extra=extra)
                continue
            if not content_enabled and kl in CONTENT_KEYS:
                out[k] = _omit_content(raw_v)
                continue
            out[k] = sanitize(
                raw_v, content_enabled=content_enabled, depth=depth + 1, key_hint=k
            )
        return out
    if isinstance(value, (list, tuple, deque)):
        # Bound huge lists (e.g. many stream chunks already aggregated).
        items = list(value)
        limit = 200
        mapped = [
            sanitize(v, content_enabled=content_enabled, depth=depth + 1, key_hint=key_hint)
            for v in items[:limit]
        ]
        if len(items) > limit:
            mapped.append(
                {
                    "truncated": True,
                    "omitted_items": len(items) - limit,
                    "original_len": len(items),
                }
            )
        return mapped
    if isinstance(value, str):
        text = value
        stripped = text.strip()
        if key_hint.lower() in AUDIO_KEYS or _looks_base64_audio(text):
            return audio_meta(text, encoding="base64?")
        if stripped[:1] in "{[":
            try:
                parsed = json.loads(text)
                return sanitize(
                    parsed,
                    content_enabled=content_enabled,
                    depth=depth + 1,
                    key_hint=key_hint,
                )
            except Exception:
                pass
        redacted = redact_text(redact_url(text))
        if len(redacted) > MAX_STRING_CHARS:
            return {
                "truncated": True,
                "original_len": len(redacted),
                "preview": redacted[:MAX_STRING_CHARS],
            }
        return redacted
    try:
        dumped = json.loads(json.dumps(value, default=str))
        if dumped != value:
            return sanitize(
                dumped, content_enabled=content_enabled, depth=depth + 1, key_hint=key_hint
            )
    except Exception:
        pass
    return redact_text(str(value))[:MAX_STRING_CHARS]


def dump_obj(obj: Any) -> Any:
    """Best-effort conversion of SDK objects to JSON-like structures."""
    if obj is None or isinstance(obj, (bool, int, float, str, bytes, bytearray)):
        return obj
    if isinstance(obj, dict):
        return {str(k): dump_obj(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [dump_obj(v) for v in obj]
    for name in ("model_dump", "to_dict", "dict"):
        fn = getattr(obj, name, None)
        if callable(fn):
            try:
                if name == "model_dump":
                    return dump_obj(fn(mode="python", exclude_unset=False))
                return dump_obj(fn())
            except TypeError:
                try:
                    return dump_obj(fn())
                except Exception:
                    pass
            except Exception:
                pass
    data = getattr(obj, "__dict__", None)
    if isinstance(data, dict) and data:
        return dump_obj({k: v for k, v in data.items() if not str(k).startswith("_")})
    return str(obj)


def ids_from_conn(conn) -> dict:
    if conn is None:
        conn = current_conn()
    if conn is None:
        return {
            "session_id": None,
            "turn_id": None,
            "agent_id": None,
            "device_id": None,
            "missing": ["session_id", "turn_id", "agent_id", "device_id"],
        }
    missing = []
    session_id = getattr(conn, "session_id", None) or None
    turn_id = getattr(conn, "trace_turn_id", None)
    if turn_id is None:
        epoch = getattr(conn, "listen_epoch", None)
        turn_id = epoch if epoch not in (None, 0) else None
    agent_id = getattr(conn, "agent_id", None) or None
    device_id = getattr(conn, "device_id", None) or None
    if not session_id:
        missing.append("session_id")
    if turn_id in (None, ""):
        missing.append("turn_id")
    if not agent_id:
        missing.append("agent_id")
    if not device_id:
        missing.append("device_id")
    extra = {}
    for name in (
        "request_id",
        "trace_request_id",
        "item_id",
        "task_id",
        "bill_id",
        "upstream_request_id",
        "correlation_id",
        "listen_epoch",
        "utterance_id",
        "sentence_id",
    ):
        val = getattr(conn, name, None)
        if val not in (None, "", 0):
            extra[name] = val
    for attr, key in (
        ("speech_turn_result", "item_id"),
        ("tts", "task_id"),
    ):
        holder = getattr(conn, attr, None)
        if holder is None:
            continue
        if isinstance(holder, dict) and holder.get(key):
            extra.setdefault(key, holder.get(key))
        else:
            nested = getattr(holder, key, None)
            if nested:
                extra.setdefault(key, nested)
    out = {
        "session_id": session_id,
        "turn_id": turn_id,
        "agent_id": agent_id,
        "device_id": device_id,
    }
    if missing:
        out["ids_missing"] = missing
        reasons = getattr(conn, "trace_id_missing_reasons", None)
        if reasons:
            out["ids_missing_reasons"] = reasons
    out.update(extra)
    return out


def mark(conn, name: str, ts: Optional[float] = None) -> Optional[float]:
    if conn is None:
        return None
    stamps = getattr(conn, "_trace_marks", None)
    if not isinstance(stamps, dict):
        stamps = {}
        conn._trace_marks = stamps
    if name not in stamps:
        stamps[name] = ts if ts is not None else time.monotonic()
    return stamps[name]


def marked(conn, name: str) -> Optional[float]:
    if conn is None:
        return None
    stamps = getattr(conn, "_trace_marks", None)
    if not isinstance(stamps, dict):
        return None
    return stamps.get(name)


def latency_ms(conn, start_name: str, end_name: Optional[str] = None) -> Any:
    start = marked(conn, start_name)
    end = marked(conn, end_name) if end_name else time.monotonic()
    if start is None or end is None:
        return "unknown"
    return round((end - start) * 1000.0, 3)


class TraceLog:
    def __init__(self):
        self.enabled = False
        self.content_enabled = False
        self.agent_ids: list = []
        self.device_ids: list = []
        self.log_dir = DEFAULT_DIR
        self.flags_path = DEFAULT_FLAGS
        self.max_queue = MAX_QUEUE
        self.max_file_bytes = MAX_FILE_BYTES
        self.max_total_bytes = MAX_TOTAL_BYTES
        self.max_files = MAX_FILES
        self.retention_days = RETENTION_DAYS
        self._queue: deque = deque()
        self._dropped = 0
        self._written = 0
        self._write_errors = 0
        self._truncated_events = 0
        self._cv = threading.Condition()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._fp = None
        self._path = None
        self._file_bytes = 0
        self._flags_mtime = None
        self._flags_checked = 0.0
        self._privacy_warned = False

    def configure(self, config: Optional[dict] = None, flags_path: Optional[str] = None):
        cfg = (config or {}).get("trace_log") or {}
        self.log_dir = cfg.get("dir") or DEFAULT_DIR
        self.flags_path = flags_path or cfg.get("flags_path") or DEFAULT_FLAGS
        self.max_queue = int(cfg.get("max_queue") or MAX_QUEUE)
        self.max_file_bytes = int(cfg.get("max_file_bytes") or MAX_FILE_BYTES)
        self.max_total_bytes = int(cfg.get("max_total_bytes") or MAX_TOTAL_BYTES)
        self.max_files = int(cfg.get("max_files") or MAX_FILES)
        self.retention_days = int(cfg.get("retention_days") or RETENTION_DAYS)
        # YAML is the schema/default; flags file wins for live toggle.
        self.enabled = bool(cfg.get("enabled", False))
        self.content_enabled = bool(cfg.get("content_enabled", False))
        self.agent_ids = list(cfg.get("agent_ids") or [])
        self.device_ids = list(cfg.get("device_ids") or [])
        self._load_flags(force=True)
        self._ensure_dir()
        self._start_writer()
        if self.enabled and self.content_enabled and not self._privacy_warned:
            self._privacy_warned = True
            self._enqueue_raw(
                {
                    "ts": _now_iso(),
                    "event": "trace.privacy_warning",
                    "payload": {
                        "content_enabled": True,
                        "warning": (
                            "content_enabled records prompts, transcripts, LLM output "
                            "and tool arguments of current sessions only. Do not export."
                        ),
                    },
                }
            )

    def _ensure_dir(self):
        try:
            os.makedirs(self.log_dir, mode=0o700, exist_ok=True)
            os.chmod(self.log_dir, 0o700)
        except Exception:
            pass

    def _load_flags(self, force: bool = False):
        path = self.flags_path
        now = time.monotonic()
        if not force and now - self._flags_checked < FLAGS_POLL_SEC:
            return
        self._flags_checked = now
        try:
            st = os.stat(path)
        except FileNotFoundError:
            return
        except Exception:
            return
        mtime = st.st_mtime
        if not force and mtime == self._flags_mtime:
            return
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            return
        if not isinstance(data, dict):
            return
        self._flags_mtime = mtime
        if "enabled" in data:
            self.enabled = bool(data.get("enabled"))
        if "content_enabled" in data:
            self.content_enabled = bool(data.get("content_enabled"))
        if "agent_ids" in data:
            self.agent_ids = [str(x) for x in (data.get("agent_ids") or []) if x]
        if "device_ids" in data:
            self.device_ids = [str(x) for x in (data.get("device_ids") or []) if x]
        if "dir" in data and data.get("dir"):
            self.log_dir = str(data["dir"])
            self._ensure_dir()

    def allowed(self, conn) -> bool:
        if not self.enabled:
            return False
        if not self.agent_ids and not self.device_ids:
            return True
        agent_id = str(getattr(conn, "agent_id", "") or "")
        device_id = str(getattr(conn, "device_id", "") or "")
        if self.device_ids and device_id and device_id in self.device_ids:
            return True
        if self.agent_ids and agent_id and agent_id in self.agent_ids:
            return True
        return False

    def emit(self, event: str, conn=None, payload: Optional[dict] = None, **extra):
        try:
            if conn is None:
                conn = current_conn()
            self._load_flags()
            if conn is not None and not self.allowed(conn):
                return
            if conn is None and (self.agent_ids or self.device_ids) and event not in (
                "trace.privacy_warning",
                "trace.writer",
                "trace.config",
            ):
                # Filtered mode: skip unscoped events except writer internals.
                if event.startswith("trace."):
                    pass
                else:
                    return
            if not self.enabled and not event.startswith("trace."):
                return
            if not self.enabled:
                return
            body = dict(payload or {})
            body.update(extra)
            record = {
                "ts": _now_iso(),
                "event": event,
                "ids": ids_from_conn(conn),
                "payload": sanitize(body, content_enabled=self.content_enabled),
            }
            line = json.dumps(record, ensure_ascii=False, default=str)
            truncated = False
            original_len = len(line)
            if original_len > MAX_EVENT_CHARS:
                truncated = True
                record["payload"] = {
                    "truncated": True,
                    "original_len": original_len,
                    "event": event,
                    "keys": sorted(body.keys())[:40],
                }
                line = json.dumps(record, ensure_ascii=False, default=str)
                self._truncated_events += 1
            if truncated:
                record["truncated"] = True
            self._enqueue_raw(json.loads(line) if truncated else record, original_len=original_len)
        except Exception:
            # Logging must never break the call path.
            return

    def _enqueue_raw(self, record: dict, original_len: Optional[int] = None):
        with self._cv:
            if len(self._queue) >= self.max_queue:
                self._dropped += 1
                # Keep a compact overflow marker, drop the new bulky event.
                if self._dropped % 20 == 1:
                    self._queue.append(
                        {
                            "ts": _now_iso(),
                            "event": "trace.queue_overflow",
                            "payload": {
                                "dropped_total": self._dropped,
                                "queue_size": len(self._queue),
                                "max_queue": self.max_queue,
                            },
                        }
                    )
                    self._cv.notify()
                return
            if original_len and original_len > MAX_EVENT_CHARS:
                record.setdefault("payload", {})["truncated"] = True
                record["payload"]["original_len"] = original_len
            self._queue.append(record)
            self._cv.notify()

    def _start_writer(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._writer_loop, name="trace-jsonl", daemon=True)
        self._thread.start()

    def _writer_loop(self):
        while not self._stop.is_set():
            with self._cv:
                if not self._queue:
                    self._cv.wait(timeout=0.5)
                batch = []
                while self._queue and len(batch) < 50:
                    batch.append(self._queue.popleft())
            if not batch:
                continue
            for record in batch:
                self._write_one(record)

    def _write_one(self, record: dict):
        try:
            self._rotate_if_needed()
            if self._fp is None:
                self._open_file()
            line = json.dumps(record, ensure_ascii=False, default=str)
            if not line.endswith("\n"):
                line += "\n"
            data = line.encode("utf-8")
            self._fp.write(data)
            self._fp.flush()
            self._file_bytes += len(data)
            self._written += 1
        except Exception:
            self._write_errors += 1

    def _open_file(self):
        self._ensure_dir()
        name = datetime.now().strftime("trace-%Y%m%d-%H%M%S.jsonl")
        path = os.path.join(self.log_dir, name)
        self._fp = open(path, "ab", buffering=0)
        try:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        except Exception:
            pass
        self._path = path
        self._file_bytes = os.path.getsize(path) if os.path.exists(path) else 0
        self._prune()

    def _rotate_if_needed(self):
        if self._fp is None:
            return
        if self._file_bytes < self.max_file_bytes:
            return
        try:
            self._fp.close()
        except Exception:
            pass
        self._fp = None
        self._open_file()

    def _prune(self):
        try:
            files = []
            for name in os.listdir(self.log_dir):
                if not name.startswith("trace-") or not name.endswith(".jsonl"):
                    continue
                path = os.path.join(self.log_dir, name)
                try:
                    st = os.stat(path)
                except OSError:
                    continue
                files.append((st.st_mtime, st.st_size, path))
            files.sort()
            cutoff = time.time() - self.retention_days * 86400
            kept = []
            for mtime, size, path in files:
                if mtime < cutoff:
                    try:
                        os.remove(path)
                    except OSError:
                        pass
                else:
                    kept.append((mtime, size, path))
            total = sum(size for _, size, _ in kept)
            while (len(kept) > self.max_files or total > self.max_total_bytes) and kept:
                mtime, size, path = kept.pop(0)
                if path == self._path:
                    kept.insert(0, (mtime, size, path))
                    break
                try:
                    os.remove(path)
                    total -= size
                except OSError:
                    break
        except Exception:
            pass

    def close(self):
        self._stop.set()
        with self._cv:
            self._cv.notify_all()
        if self._thread:
            self._thread.join(timeout=2)
        if self._fp:
            try:
                self._fp.close()
            except Exception:
                pass
            self._fp = None

    def stats(self) -> dict:
        return {
            "enabled": self.enabled,
            "content_enabled": self.content_enabled,
            "queue_size": len(self._queue),
            "dropped": self._dropped,
            "written": self._written,
            "write_errors": self._write_errors,
            "truncated_events": self._truncated_events,
            "path": self._path,
            "log_dir": self.log_dir,
        }


def get_trace() -> TraceLog:
    global _INSTANCE
    with _LOCK:
        if _INSTANCE is None:
            _INSTANCE = TraceLog()
        return _INSTANCE


def configure(config: Optional[dict] = None, **kwargs) -> TraceLog:
    inst = get_trace()
    inst.configure(config, **kwargs)
    return inst


def emit(event: str, conn=None, payload: Optional[dict] = None, **extra) -> None:
    try:
        get_trace().emit(event, conn, payload, **extra)
    except Exception:
        return


def enabled() -> bool:
    try:
        inst = get_trace()
        inst._load_flags()
        return bool(inst.enabled)
    except Exception:
        return False


def write_flags(
    path: str,
    *,
    enabled: bool,
    content_enabled: bool = False,
    agent_ids: Optional[Iterable[str]] = None,
    device_ids: Optional[Iterable[str]] = None,
):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = {
        "enabled": bool(enabled),
        "content_enabled": bool(content_enabled),
        "agent_ids": list(agent_ids or []),
        "device_ids": list(device_ids or []),
        "updated_at": _now_iso(),
    }
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass


def reset_for_tests(log_dir: str, flags_path: str) -> TraceLog:
    """Isolated instance for unit tests. Does not replace the process singleton permanently."""
    global _INSTANCE
    with _LOCK:
        if _INSTANCE is not None:
            try:
                _INSTANCE.close()
            except Exception:
                pass
        inst = TraceLog()
        inst.configure(
            {
                "trace_log": {
                    "enabled": False,
                    "content_enabled": False,
                    "dir": log_dir,
                    "flags_path": flags_path,
                    "max_queue": 32,
                    "max_file_bytes": 64 * 1024,
                    "max_total_bytes": 256 * 1024,
                    "max_files": 3,
                    "retention_days": 1,
                }
            },
            flags_path=flags_path,
        )
        _INSTANCE = inst
        return inst
