"""提醒交互监听生命周期测试。"""

from __future__ import annotations

import asyncio
import os
import sys
import time
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.utils.reminder_interaction import (
    MAX_INTERACTION_DURATION_SEC,
    close_interaction,
    get_interaction_state,
    is_interaction_active,
    open_interaction,
    validate_interaction_expires_at,
)


class TestReminderInteraction(unittest.IsolatedAsyncioTestCase):
    def _conn(self):
        c = MagicMock()
        c.device_id = "dev-1"
        c.session_id = "s1"
        c._outbound_tasks = set()
        return c

    def test_open_and_active(self):
        conn = self._conn()
        ok, reason = open_interaction(
            conn,
            instance_id="note:1:1",
            revision=2,
            expires_at=int(time.time()) + 60,
        )
        self.assertTrue(ok, reason)
        self.assertTrue(is_interaction_active(conn))

    def test_closed_inactive(self):
        conn = self._conn()
        open_interaction(
            conn,
            instance_id="note:1:1",
            revision=2,
            expires_at=int(time.time()) + 60,
        )
        close_interaction(conn, reason="resolved")
        self.assertFalse(is_interaction_active(conn))

    def test_expired_rejected_on_open(self):
        conn = self._conn()
        ok, reason = open_interaction(
            conn,
            instance_id="note:1:1",
            revision=2,
            expires_at=int(time.time()) - 1,
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "interaction_expired")

    def test_180_seconds_legal(self):
        received = 1_700_000_000
        ok, reason, exp, clipped = validate_interaction_expires_at(
            received + int(MAX_INTERACTION_DURATION_SEC),
            received_at=received,
        )
        self.assertTrue(ok, reason)
        self.assertFalse(clipped)
        self.assertEqual(exp, received + 180)

    def test_181_seconds_clipped_to_180(self):
        received = 1_700_000_000
        ok, reason, exp, clipped = validate_interaction_expires_at(
            received + int(MAX_INTERACTION_DURATION_SEC) + 1,
            received_at=received,
        )
        self.assertTrue(ok, reason)
        self.assertTrue(clipped)
        self.assertEqual(exp, received + 180)

    def test_open_clips_expires_at_beyond_180(self):
        conn = self._conn()
        ok, reason = open_interaction(
            conn,
            instance_id="note:1:1",
            revision=2,
            expires_at=int(time.time()) + 500,
        )
        self.assertTrue(ok, reason)
        self.assertEqual(reason, "expires_at_clipped")
        state = get_interaction_state(conn)
        self.assertTrue(state.expires_at_clipped)
        self.assertLessEqual(state.expires_at - state.received_at, 180)

    async def test_proactive_expire_without_events(self):
        conn = self._conn()
        ok, _ = open_interaction(
            conn,
            instance_id="note:1:1",
            revision=2,
            expires_at=int(time.time()) + 1,
        )
        self.assertTrue(ok)
        self.assertTrue(is_interaction_active(conn))
        await asyncio.sleep(1.3)
        self.assertFalse(is_interaction_active(conn))

    async def test_new_open_replaces_expire_task(self):
        conn = self._conn()
        open_interaction(
            conn,
            instance_id="note:1:1",
            revision=1,
            expires_at=int(time.time()) + 1,
        )
        task1 = getattr(conn, "_reminder_interaction_expire_task", None)
        open_interaction(
            conn,
            instance_id="note:1:2",
            revision=2,
            expires_at=int(time.time()) + 60,
        )
        task2 = getattr(conn, "_reminder_interaction_expire_task", None)
        self.assertIsNotNone(task2)
        self.assertNotEqual(task1, task2)
        self.assertTrue(is_interaction_active(conn))


if __name__ == "__main__":
    unittest.main()
