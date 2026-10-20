#!/usr/bin/env python3
"""Shared update_spine URL/canonical helpers (must match firmware)."""

from __future__ import annotations

from urllib.parse import urlparse


def parse_https_url(url: str) -> tuple[str, str, str]:
    """Return (host_lower, path_no_query, signed_origin_path). Raises ValueError."""
    p = urlparse(url)
    if p.scheme != "https":
        raise ValueError("url must be https")
    if p.fragment:
        raise ValueError("fragment not allowed")
    if p.username or p.password:
        raise ValueError("userinfo not allowed")
    if p.port is not None:
        raise ValueError("explicit port not allowed (including :443)")
    host = (p.hostname or "").lower()
    if not host:
        raise ValueError("empty host")
    # IPv4 / IPv6 literals
    if all(c.isdigit() or c == "." for c in host) or ":" in host or host.startswith("["):
        raise ValueError("IP literal not allowed")
    path = p.path or "/"
    signed = f"https://{host}{path}"
    return host, path, signed


def build_canonical(task: dict) -> str:
    _, _, signed = parse_https_url(task["url"])
    return (
        f'{task["task_id"]}\n'
        f'{task["pack_id"]}\n'
        f'{task["role_id"]}\n'
        f'{task["version"]}\n'
        f'{task["size"]}\n'
        f'{task["sha256"]}\n'
        f'{task["min_fw"]}\n'
        f"{signed}\n"
    )


def role_id_allowed(role_id: str, allow_list: str) -> bool:
    import re

    if not role_id or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", role_id):
        return False
    if allow_list is None or allow_list == "":
        return False
    for item in allow_list.split(","):
        item = item.strip()
        if item == "*" or item == role_id:
            return True
    return False


class AcquireLock:
    """Mirrors SpineOta::TryAcquire / Release for host concurrency tests."""

    def __init__(self) -> None:
        self.running = False
        self.callback = None

    def try_acquire(self, cb) -> bool:
        if self.running:
            return False
        self.running = True
        self.callback = cb
        return True

    def release(self) -> None:
        self.running = False
        self.callback = None

    def report(self, *args) -> None:
        # Must not require holding a lock when invoking callback.
        cb = self.callback
        if cb:
            cb(*args)


def commit_active_slot(store: dict, *, fail_at: str | None = None) -> bool:
    """Simulate the single dynamic Spine partition's NVS commit."""
    if fail_at == "nvs_open":
        return False
    staging = dict(store)
    steps = [
        ("active_role_id", "set_role_id"),
        ("active_version", "set_version"),
        ("last_task_id", "set_task_id"),
        ("last_sha256", "set_sha256"),
        ("active_source", "set_source"),
    ]
    for key, tag in steps:
        if fail_at == tag:
            return False
        # values supplied by caller via store["_pending"]
        pending = store.get("_pending", {})
        staging[key] = pending[key]
    if fail_at == "nvs_commit":
        return False
    store.clear()
    store.update(staging)
    store.pop("_pending", None)
    return True
