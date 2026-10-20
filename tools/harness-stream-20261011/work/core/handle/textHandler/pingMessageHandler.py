from typing import Dict, Any
import time

from core.handle.textMessageHandler import TextMessageHandler
from core.handle.textMessageType import TextMessageType
from core.utils.device_outbound import guarded_ws_send

TAG = __name__


class PingTextMessageHandler(TextMessageHandler):
    """Ping 心跳消息处理器"""

    @property
    def message_type(self) -> TextMessageType:
        return TextMessageType.PING

    async def handle(self, conn, msg_json: Dict[str, Any]) -> None:
        # 刷新设备的最后活动时间，防止服务器将其作为空闲连接踢掉
        conn.last_activity_time = time.time() * 1000
        # 应用层 ping（JSON type=ping），与 WebSocket 协议 ping/pong 分离
        conn.last_app_ping_monotonic_ms = int(time.monotonic() * 1000)

        # 记录 debug 日志，避免污染 info/error 日志
        conn.logger.bind(tag=TAG).debug(f"收到心跳 ping：{msg_json}")

        # 可选：回传一个极简 pong 包以保持底层链路活跃（非 current 不回）
        # 注意：这不是 WebSocket 协议级 pong，不能替代 keepalive ping timeout
        try:
            await guarded_ws_send(
                conn, '{"type":"pong"}', command="pong", msg_type="pong"
            )
        except Exception:
            pass
