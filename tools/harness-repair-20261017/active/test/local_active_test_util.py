"""测试辅助：local_active 绑定受控 RC 注册表 + 可选主连接代际。"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import MagicMock

from core.reminder_control import ReminderControlManager


async def wait_bounded(
    awaitable,
    *,
    timeout: float,
    test_name: str,
    point: str,
):
    try:
        return await asyncio.wait_for(awaitable, timeout=timeout)
    except asyncio.TimeoutError as exc:
        raise AssertionError(
            f"{test_name}: timeout waiting at {point} (> {timeout}s)"
        ) from exc


async def cancel_tasks(tasks):
    for t in list(tasks):
        if t and not t.done():
            t.cancel()
    for t in list(tasks):
        if t:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass


class FakeMainHost:
    """最小主连接代际表，供 RC 单测绑定 parent_main_session_id。"""

    def __init__(self):
        self._connections = {}
        self._current_sessions = {}
        self._device_send_locks = {}

    def get_current_main_session_id(self, device_id: str):
        return self._current_sessions.get(device_id)

    def is_main_session_current(self, device_id: str, main_session_id: str) -> bool:
        if self._current_sessions.get(device_id) != main_session_id:
            return False
        handler = (self._connections.get(device_id) or {}).get(main_session_id)
        return handler is not None and not getattr(handler, "superseded", False)

    def register_main(self, device_id: str, handler) -> None:
        bag = self._connections.setdefault(device_id, {})
        for old_key, old_h in list(bag.items()):
            if old_h is not handler and old_key != handler.session_id:
                old_h.superseded = True
        bag[handler.session_id] = handler
        self._current_sessions[device_id] = handler.session_id
        handler.superseded = False


def make_integrated_server():
    """WebSocketServer 骨架：主连接 + RC 共享 _device_send_locks。"""
    from core.websocket_server import WebSocketServer

    server = WebSocketServer.__new__(WebSocketServer)
    server.logger = MagicMock()
    server._connections = {}
    server._current_sessions = {}
    server._device_send_locks = {}
    server._reminder_control_manager = ReminderControlManager(
        max_per_device=2,
        device_locks=server._device_send_locks,
        main_host=server,
    )
    return server


def bind_local_active_registry(
    conn,
    manager=None,
    *,
    max_per_device: int = 2,
    main_host=None,
    device_locks=None,
    parent_main_session_id: str | None = None,
):
    conn.outbound_mode = "local_active"
    conn.superseded = False
    conn._outbound_closed = False
    device_id = getattr(conn, "device_id", None)
    if not device_id:
        raise ValueError("device_id required")
    if not getattr(conn, "session_id", None):
        conn.session_id = f"rc-{uuid.uuid4().hex[:8]}"
    if main_host is None:
        main_host = FakeMainHost()
        parent = parent_main_session_id or "main-sess-default"
        mh = MagicMock()
        mh.session_id = parent
        mh.superseded = False
        main_host.register_main(device_id, mh)
    if device_locks is None and main_host is not None:
        device_locks = getattr(main_host, "_device_send_locks", None)
    if manager is None:
        manager = ReminderControlManager(
            max_per_device=max_per_device,
            device_locks=device_locks,
            main_host=main_host,
        )
    manager._register_connection_unlocked(device_id, conn)
    return manager
