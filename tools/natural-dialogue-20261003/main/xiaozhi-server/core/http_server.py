import asyncio
from aiohttp import web
from config.logger import setup_logging
from core.api.ota_handler import OTAHandler
from core.api.vision_handler import VisionHandler
from core.api.memory_handler import MemoryHandler
from core.api.reminder_voice_handler import ReminderVoiceHandler
from core.api.face_enrollment_handler import FaceEnrollmentHandler

TAG = __name__


class SimpleHttpServer:
    def __init__(self, config: dict):
        self.config = config
        self.logger = setup_logging()
        self.ota_handler = OTAHandler(config)
        self.vision_handler = VisionHandler(config)
        self.memory_handler = MemoryHandler(config)
        self.reminder_voice_handler = ReminderVoiceHandler(config)
        self.face_enrollment_handler = FaceEnrollmentHandler(config)

    def _get_websocket_url(self, local_ip: str, port: int) -> str:
        """获取websocket地址

        Args:
            local_ip: 本地IP地址
            port: 端口号

        Returns:
            str: websocket地址
        """
        server_config = self.config["server"]
        websocket_config = server_config.get("websocket")

        if websocket_config and "你" not in websocket_config:
            return websocket_config
        else:
            return f"ws://{local_ip}:{port}/xiaozhi/v1/"

    async def start(self):
        server_config = self.config["server"]
        read_config_from_api = self.config.get("read_config_from_api", False)
        host = server_config.get("ip", "0.0.0.0")
        port = int(server_config.get("http_port", 8003))

        if port:
            app = web.Application()

            if not read_config_from_api:
                # 如果没有开启智控台，只是单模块运行，就需要再添加简单OTA接口，用于下发websocket接口
                app.add_routes(
                    [
                        web.get("/xiaozhi/ota/", self.ota_handler.handle_get),
                        web.post("/xiaozhi/ota/", self.ota_handler.handle_post),
                        web.options("/xiaozhi/ota/", self.ota_handler.handle_options),
                    ]
                )
            # 添加路由
            app.add_routes(
                [
                    web.get("/mcp/vision/explain", self.vision_handler.handle_get),
                    web.post("/mcp/vision/explain", self.vision_handler.handle_post),
                    web.options("/mcp/vision/explain", self.vision_handler.handle_post),
                    web.get("/mcp/vision/identify", self.vision_handler.handle_get),
                    web.post(
                        "/mcp/vision/identify", self.vision_handler.handle_identify
                    ),
                    web.options(
                        "/mcp/vision/identify", self.vision_handler.handle_identify
                    ),
                    web.get("/admin/memory", self.memory_handler.handle_list),
                    web.delete("/admin/memory/{id}", self.memory_handler.handle_delete),
                    web.delete("/admin/memory/device/{device_id}", self.memory_handler.handle_delete_by_device),
                    web.options("/admin/memory", self.memory_handler.handle_options),
                    web.options("/admin/memory/{id}", self.memory_handler.handle_options),
                    web.options("/admin/memory/device/{device_id}", self.memory_handler.handle_options),
                    web.get(
                        "/reminder-voice/{asset_id}",
                        self.reminder_voice_handler.handle_get,
                    ),
                    # Guided Burst V2（唯一协议；无 V1 sessions/frames 回退）
                    web.post(
                        "/mcp/face-enrollment/session",
                        self.face_enrollment_handler.handle_v2_create_session,
                    ),
                    web.post(
                        "/mcp/face-enrollment/assess/{session_id}",
                        self.face_enrollment_handler.handle_v2_assess,
                    ),
                    web.post(
                        "/mcp/face-enrollment/capture/{session_id}",
                        self.face_enrollment_handler.handle_v2_capture,
                    ),
                    web.delete(
                        "/mcp/face-enrollment/cancel/{session_id}",
                        self.face_enrollment_handler.handle_v2_cancel,
                    ),
                ]
            )

            # 运行服务
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, host, port)
            await site.start()

            # 保持服务运行
            while True:
                await asyncio.sleep(3600)  # 每隔 1 小时检查一次
