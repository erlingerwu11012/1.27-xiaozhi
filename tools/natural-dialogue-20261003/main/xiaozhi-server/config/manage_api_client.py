import os
import time
import base64
from typing import Optional, Dict

import httpx

TAG = __name__


class DeviceNotFoundException(Exception):
    pass


class DeviceBindException(Exception):
    def __init__(self, bind_code):
        self.bind_code = bind_code
        super().__init__(f"设备绑定异常，绑定码: {bind_code}")


class ManageApiClient:
    _instance = None
    _client = None
    _secret = None

    def __new__(cls, config):
        """单例模式确保全局唯一实例，并支持传入配置参数"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._init_client(config)
        return cls._instance

    @classmethod
    def _init_client(cls, config):
        """初始化持久化连接池"""
        cls.config = config.get("manager-api")

        if not cls.config:
            raise Exception("manager-api配置错误")

        if not cls.config.get("url") or not cls.config.get("secret"):
            raise Exception("manager-api的url或secret配置错误")

        if "你" in cls.config.get("secret"):
            raise Exception("请先配置manager-api的secret")

        cls._secret = cls.config.get("secret")
        cls.max_retries = cls.config.get("max_retries", 6)  # 最大重试次数
        cls.retry_delay = cls.config.get("retry_delay", 10)  # 初始重试延迟(秒)
        # 确保 base_url 包含 context-path /xiaozhi，否则 POST /config/server-base 会 404
        base_url = (cls.config.get("url") or "").rstrip("/")
        if base_url and "/xiaozhi" not in base_url.split("?")[0]:
            base_url = base_url + "/xiaozhi"
        # httpx 要求 base_url 以 / 结尾，否则相对路径会错误拼接为 /config/server-base（丢失 xiaozhi）
        if base_url and not base_url.endswith("/"):
            base_url = base_url + "/"
        # NOTE(goody): 2025/4/16 http相关资源统一管理，后续可以增加线程池或者超时
        cls._client = httpx.Client(
            base_url=base_url,
            headers={
                "User-Agent": f"PythonClient/2.0 (PID:{os.getpid()})",
                "Accept": "application/json",
                "Authorization": "Bearer " + cls._secret,
            },
            timeout=cls.config.get("timeout", 30),  # 默认超时时间30秒
        )
        cls._async_client = httpx.AsyncClient(
            base_url=base_url,
            headers={
                "User-Agent": f"PythonClient/2.0 (PID:{os.getpid()})",
                "Accept": "application/json",
                "Authorization": "Bearer " + cls._secret,
            },
            timeout=cls.config.get("timeout", 30),
        )
        
    # 为了供外部直接调用自定义请求提供一个实例方法
    async def request(self, method: str, endpoint: str, **kwargs) -> Dict:
        """异步请求包装器，避免阻塞事件循环"""
        endpoint = endpoint.lstrip("/")
        response = await self._async_client.request(method, endpoint, **kwargs)
        response.raise_for_status()
        result = response.json()
        if result.get("code") == 10041:
            raise DeviceNotFoundException(result.get("msg"))
        elif result.get("code") == 10042:
            raise DeviceBindException(result.get("msg"))
        elif result.get("code") != 0:
            raise Exception(f"API返回错误: {result.get('msg', '未知错误')}")
        return result.get("data") if result.get("code") == 0 else None

    @classmethod
    def _request(cls, method: str, endpoint: str, **kwargs) -> Dict:
        """发送单次HTTP请求并处理响应"""
        endpoint = endpoint.lstrip("/")
        response = cls._client.request(method, endpoint, **kwargs)
        response.raise_for_status()

        result = response.json()

        # 处理API返回的业务错误
        if result.get("code") == 10041:
            raise DeviceNotFoundException(result.get("msg"))
        elif result.get("code") == 10042:
            raise DeviceBindException(result.get("msg"))
        elif result.get("code") != 0:
            raise Exception(f"API返回错误: {result.get('msg', '未知错误')}")

        # 返回成功数据
        return result.get("data") if result.get("code") == 0 else None

    @classmethod
    def _should_retry(cls, exception: Exception) -> bool:
        """判断异常是否应该重试"""
        # 网络连接相关错误
        if isinstance(
            exception, (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError)
        ):
            return True

        # HTTP状态码错误（404 通常为路径错误，不重试）
        if isinstance(exception, httpx.HTTPStatusError):
            status_code = exception.response.status_code
            return status_code in [408, 429, 500, 502, 503, 504]

        return False

    @classmethod
    def _execute_request(cls, method: str, endpoint: str, **kwargs) -> Dict:
        """带重试机制的请求执行器"""
        retry_count = 0

        while retry_count <= cls.max_retries:
            try:
                # 执行请求
                return cls._request(method, endpoint, **kwargs)
            except Exception as e:
                # 判断是否应该重试
                if retry_count < cls.max_retries and cls._should_retry(e):
                    retry_count += 1
                    print(
                        f"{method} {endpoint} 请求失败，将在 {cls.retry_delay:.1f} 秒后进行第 {retry_count} 次重试"
                    )
                    time.sleep(cls.retry_delay)
                    continue
                else:
                    if isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 404:
                        print(
                            "提示：404 Not Found，请确认 manager-api.url 已包含 /xiaozhi，"
                            "例如：http://127.0.0.1:8002/xiaozhi"
                        )
                    raise

    @classmethod
    def safe_close(cls):
        """安全关闭连接池"""
        import asyncio
        if cls._client:
            cls._client.close()
        if hasattr(cls, "_async_client") and cls._async_client:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(cls._async_client.aclose())
                else:
                    loop.run_until_complete(cls._async_client.aclose())
            except Exception:
                pass
        cls._instance = None


def get_server_config() -> Optional[Dict]:
    """获取服务器基础配置"""
    return ManageApiClient._instance._execute_request("POST", "/config/server-base")

async def get_device_config(device_id: str) -> Optional[Dict]:
    """获取设备配置（包含 userId 等，供 aimi 设备网关按用户路由）。

    使用服务密钥鉴权的 /device/by-mac/{mac}，按 MAC 查询（服务间认证），
    避免命中 oauth2 用户态导致 Unauthorized。
    """
    return await manage_api.request("GET", f"/device/by-mac/{device_id}")

def get_agent_models(
    mac_address: str, client_id: str, selected_module: Dict
) -> Optional[Dict]:
    """获取代理模型配置"""
    return ManageApiClient._instance._execute_request(
        "POST",
        "/config/agent-models",
        json={
            "macAddress": mac_address,
            "clientId": client_id,
            "selectedModule": selected_module,
        },
    )


def save_mem_local_short(mac_address: str, short_momery: str) -> Optional[Dict]:
    try:
        return ManageApiClient._instance._execute_request(
            "PUT",
            f"/agent/saveMemory/" + mac_address,
            json={
                "summaryMemory": short_momery,
            },
        )
    except Exception as e:
        print(f"存储短期记忆到服务器失败: {e}")
        return None


def report(
    mac_address: str, session_id: str, chat_type: int, content: str, audio, report_time, metadata=None
) -> Optional[Dict]:
    """带熔断的业务方法示例"""
    if not content or not ManageApiClient._instance:
        return None
    try:
        return ManageApiClient._instance._execute_request(
            "POST",
            f"/agent/chat-history/report",
            json={
                "macAddress": mac_address,
                "sessionId": session_id,
                "chatType": chat_type,
                "content": content,
                "reportTime": report_time,
                **(metadata or {}),
                "audioBase64": (
                    base64.b64encode(audio).decode("utf-8") if audio else None
                ),
            },
        )
    except Exception as e:
        print(f"TTS上报失败: {e}")
        return None


def init_service(config):
    ManageApiClient(config)
    global manage_api
    manage_api = ManageApiClient._instance


def manage_api_http_safe_close():
    ManageApiClient.safe_close()
    
manage_api = ManageApiClient._instance
