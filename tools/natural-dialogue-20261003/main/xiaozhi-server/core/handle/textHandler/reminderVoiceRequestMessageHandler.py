"""WebSocket：reminder_voice_request 入站处理。"""

from __future__ import annotations

import asyncio
from typing import Any, Dict

from core.handle.textMessageHandler import TextMessageHandler
from core.handle.textMessageType import TextMessageType
from core.utils.reminder_voice import process_reminder_voice_request

TAG = __name__


class ReminderVoiceRequestMessageHandler(TextMessageHandler):
    @property
    def message_type(self) -> TextMessageType:
        return TextMessageType.REMINDER_VOICE_REQUEST

    async def handle(self, conn, msg_json: Dict[str, Any]) -> None:
        # 不阻塞其他对话：后台任务；连接关闭时丢弃
        task = asyncio.create_task(process_reminder_voice_request(conn, msg_json))
        # 挂到连接上便于关闭时取消
        bag = getattr(conn, "_reminder_voice_tasks", None)
        if bag is None:
            bag = set()
            conn._reminder_voice_tasks = bag

        def _done(t: asyncio.Task):
            bag.discard(t)

        bag.add(task)
        task.add_done_callback(_done)
