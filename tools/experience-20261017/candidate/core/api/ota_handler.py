import json
import time
import base64
import hashlib
import hmac
from aiohttp import web

from core.auth import AuthManager
from core.utils.util import get_local_ip
from core.api.base_handler import BaseHandler

TAG = __name__


class OTAHandler(BaseHandler):
    def __init__(self, config: dict):
        super().__init__(config)
        auth_config = config["server"].get("auth", {})
        self.auth_enable = auth_config.get("enabled", False)
        # 设备白名单
        self.allowed_devices = set(auth_config.get("allowed_devices", []))
        secret_key = config["server"]["auth_key"]
        expire_seconds = auth_config.get("expire_seconds")
        self.auth = AuthManager(secret_key=secret_key, expire_seconds=expire_seconds)

    def generate_password_signature(self, content: str, secret_key: str) -> str:
        """生成MQTT密码签名

        Args:
            content: 签名内容 (clientId + '|' + username)
            secret_key: 密钥

        Returns:
            str: Base64编码的HMAC-SHA256签名
        """
        try:
            hmac_obj = hmac.new(
                secret_key.encode("utf-8"), content.encode("utf-8"), hashlib.sha256
            )
            signature = hmac_obj.digest()
            return base64.b64encode(signature).decode("utf-8")
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"生成MQTT密码签名失败: {e}")
            return ""

    def _get_websocket_url(self, local_ip: str, port: int) -> str:
        """获取websocket地址

        Args:
            local_ip: 本地IP地址
            port: 端口号

        Returns:
            str: websocket地址
        """
        server_config = self.config["server"]
        websocket_config = server_config.get("websocket", "")

        if "你的" not in websocket_config:
            return websocket_config
        else:
            return f"ws://{local_ip}:{port}/xiaozhi/v1/"

    def _build_ota_config_response(self, data_json=None, device_id="", client_id=""):
        """构建标准 OTA 配置 JSON（mqtt + firmware），不抛出 ValueError/Exception"""
        server_config = self.config.get("server", {})
        mqtt_gateway = server_config.get("mqtt_gateway") or ""
        ota_base = server_config.get("ota_url", "http://localhost:8002/xiaozhi/ota/")
        version = "2.0.5"
        if data_json and isinstance(data_json, dict):
            app = data_json.get("application") or {}
            if isinstance(app, dict):
                version = str(app.get("version", version))
        firmware_url = ota_base.rstrip("/").replace("/ota/", "/otaMag/download/") + "placeholder"
        if "/otaMag/download/" not in firmware_url:
            firmware_url = "http://localhost:8002/xiaozhi/otaMag/download/placeholder"
        mqtt_host, mqtt_port = "localhost", 1883
        if mqtt_gateway and str(mqtt_gateway) != "null":
            s = str(mqtt_gateway).strip()
            if "://" in s:
                s = s.split("://", 1)[1]
            if ":" in s:
                parts = s.split(":", 1)
                mqtt_host = parts[0]
                try:
                    mqtt_port = int(parts[1].split("/")[0])
                except (ValueError, IndexError):
                    pass
            else:
                mqtt_host = s
        mqtt_obj = {
            "broker": mqtt_host,
            "host": mqtt_host,
            "port": mqtt_port,
            "username": "",
            "password": "",
        }
        if device_id and mqtt_gateway and str(mqtt_gateway) != "null":
            try:
                device_model = "default"
                if data_json and isinstance(data_json, dict):
                    dev = data_json.get("device")
                    if isinstance(dev, dict):
                        device_model = dev.get("model", "default") or "default"
                    else:
                        device_model = str(data_json.get("model", "default"))
                group_id = f"GID_{device_model}".replace(":", "_").replace(" ", "_")
                mac_safe = device_id.replace(":", "_")
                mqtt_client_id = f"{group_id}@@@{mac_safe}@@@{mac_safe}"
                user_data = {"ip": "unknown"}
                username = base64.b64encode(
                    json.dumps(user_data).encode("utf-8")
                ).decode("utf-8")
                sk = server_config.get("mqtt_signature_key", "")
                if sk:
                    mqtt_obj["password"] = self.generate_password_signature(
                        mqtt_client_id + "|" + username, sk
                    )
                mqtt_obj["username"] = username
                mqtt_obj["endpoint"] = str(mqtt_gateway)
                mqtt_obj["client_id"] = mqtt_client_id
                mqtt_obj["publish_topic"] = "device-server"
                mqtt_obj["subscribe_topic"] = f"devices/p2p/{mac_safe}"
            except Exception as e:
                self.logger.bind(tag=TAG).warning(f"构建设备级 MQTT 配置失败: {e}")
        return {
            "message": "OTA success",
            "mqtt": mqtt_obj,
            "firmware": {"version": version, "url": firmware_url},
        }

    async def handle_post(self, request):
        """处理 OTA POST 请求，安全解析 JSON，不抛 ValueError，始终返回 mqtt + firmware"""
        data_json = None
        try:
            data = await request.text() or "{}"
            self.logger.bind(tag=TAG).debug(f"OTA POST 请求头: {request.headers}")
            data_json = json.loads(data) if data.strip() else {}
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            self.logger.bind(tag=TAG).debug(f"OTA POST 请求体非 JSON，使用空对象: {e}")
            data_json = {}
        device_id = (request.headers.get("device-id") or request.headers.get("Device-Id") or "").strip()
        client_id = (request.headers.get("client-id") or request.headers.get("Client-Id") or "").strip()
        if device_id:
            self.logger.bind(tag=TAG).info(f"OTA POST 设备ID: {device_id}")
        try:
            return_json = self._build_ota_config_response(data_json, device_id, client_id)
            response = web.Response(
                text=json.dumps(return_json, separators=(",", ":")),
                content_type="application/json",
            )
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"OTA POST 构建响应异常: {e}")
            return_json = {
                "message": "OTA接口异常",
                "mqtt": {"broker": "localhost", "host": "localhost", "port": 1883, "username": "", "password": ""},
                "firmware": {"version": "2.0.5", "url": "http://localhost:8002/xiaozhi/otaMag/download/placeholder"},
            }
            response = web.Response(
                text=json.dumps(return_json, separators=(",", ":")),
                content_type="application/json",
            )
        finally:
            self._add_cors_headers(response)
        return response

    async def handle_get(self, request):
        """处理 OTA GET 请求，返回标准 JSON（mqtt + firmware）"""
        try:
            return_json = self._build_ota_config_response(None, "", "")
            response = web.Response(
                text=json.dumps(return_json, separators=(",", ":")),
                content_type="application/json",
            )
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"OTA GET 异常: {e}")
            return_json = {
                "message": "OTA接口异常",
                "mqtt": {"broker": "localhost", "host": "localhost", "port": 1883, "username": "", "password": ""},
                "firmware": {"version": "2.0.5", "url": "http://localhost:8002/xiaozhi/otaMag/download/placeholder"},
            }
            response = web.Response(
                text=json.dumps(return_json, separators=(",", ":")),
                content_type="application/json",
            )
        finally:
            self._add_cors_headers(response)
        return response

    async def handle_options(self, request):
        """处理 OPTIONS 预检请求"""
        response = web.Response(status=204)
        self._add_cors_headers(response)
        return response
