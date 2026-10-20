import json

from core.handle.textMessageHandlerRegistry import TextMessageHandlerRegistry
from core.utils.device_outbound import guarded_ws_send

TAG = __name__


class TextMessageProcessor:
    """消息处理器主类"""

    def __init__(self, registry: TextMessageHandlerRegistry):
        self.registry = registry

    async def process_message(self, conn, message: str) -> None:
        """处理消息的主入口"""
        try:
            # 解析JSON消息
            msg_json = json.loads(message)

            # 处理JSON消息
            if isinstance(msg_json, dict):
                message_type = msg_json.get("type")

                # 记录日志（提醒语音/事件/MCP 不落完整正文，仅记摘要；不记录任何 token）
                if message_type in ("reminder_voice_request", "reminder_event"):
                    safe = {
                        "type": message_type,
                        "instance_id": msg_json.get("instance_id"),
                        "revision": msg_json.get("revision"),
                        "voice_revision": msg_json.get("voice_revision"),
                        "recipient_person_id": msg_json.get("recipient_person_id"),
                        "presence_generation": msg_json.get("presence_generation"),
                        "event": msg_json.get("event"),
                        "title_len": len(str(msg_json.get("title") or "")),
                        "detail_len": len(str(msg_json.get("detail") or "")),
                    }
                    conn.logger.bind(tag=TAG).info(
                        f"[msg] {self._cid(conn)} type={message_type} "
                        f"summary={json.dumps(safe, ensure_ascii=False)}"
                    )
                elif message_type == "mcp":
                    # MCP payload 可能含设备工具参数，仅记录长度与顶层方法，不落完整 payload
                    payload = msg_json.get("payload")
                    method = ""
                    if isinstance(payload, dict):
                        method = str(payload.get("method") or "")
                    conn.logger.bind(tag=TAG).info(
                        f"[msg] {self._cid(conn)} type=mcp "
                        f"payload_len={len(str(payload))} method={method}"
                    )
                elif message_type == "listen":
                    conn.logger.bind(tag=TAG).info(
                        f"[msg] {self._cid(conn)} type=listen "
                        f"state={msg_json.get('state')} mode={msg_json.get('mode')} "
                        f"session_id={conn._mask(msg_json.get('session_id') or '')}"
                    )
                elif message_type == "hello":
                    conn.logger.bind(tag=TAG).info(
                        f"[msg] {self._cid(conn)} type=hello "
                        f"version={msg_json.get('version')} "
                        f"session_id={conn._mask(msg_json.get('session_id') or '')}"
                    )
                elif message_type in ("ping", "pong"):
                    # 设备保活极密，INFO 会刷屏；处理逻辑不变，仅不打入站日志
                    pass
                else:
                    conn.logger.bind(tag=TAG).info(
                        f"[msg] {self._cid(conn)} type={message_type} message={message}"
                    )

                # 获取并执行处理器
                handler = self.registry.get_handler(message_type)
                if handler:
                    await handler.handle(conn, msg_json)
                else:
                    conn.logger.bind(tag=TAG).error(
                        f"收到未知类型消息：type={message_type}"
                    )
            # 处理纯数字消息
            elif isinstance(msg_json, int):
                conn.logger.bind(tag=TAG).info(f"[msg] {self._cid(conn)} type=int")
                await guarded_ws_send(
                    conn, message, command="echo", msg_type="int"
                )

        except json.JSONDecodeError:
            # 非JSON消息直接转发（不落正文）
            conn.logger.bind(tag=TAG).error(f"解析到错误的消息：len={len(message)}")
            await guarded_ws_send(
                conn, message, command="echo", msg_type="raw"
            )

    @staticmethod
    def _cid(conn) -> str:
        """诊断前缀，避免在处理器内重复拼接。"""
        return getattr(conn, "_cid", lambda: "correlation_id=? device_id=?")()
