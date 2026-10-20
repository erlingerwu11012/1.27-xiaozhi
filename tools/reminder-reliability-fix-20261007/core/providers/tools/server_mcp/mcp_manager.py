"""服务端MCP管理器"""

import asyncio
import json
import os
from typing import Any, Dict, List, Tuple

from mcp.types import LoggingMessageNotificationParams

from config.config_loader import get_project_dir
from config.logger import setup_logging
from .mcp_client import ServerMCPClient

TAG = __name__
logger = setup_logging()


class ServerMCPManager:
    """管理多个服务端MCP服务的集中管理器"""

    def __init__(self, conn) -> None:
        """初始化MCP管理器"""
        self.conn = conn
        self.config_path = get_project_dir() + "data/.mcp_server_settings.json"
        if not os.path.exists(self.config_path):
            self.config_path = ""
            logger.bind(tag=TAG).warning(
                "请检查mcp服务配置文件：data/.mcp_server_settings.json"
            )
        self.clients: Dict[str, ServerMCPClient] = {}
        self.tools: List[Dict[str, Any]] = []

    def load_config(self) -> Dict[str, Any]:
        """加载MCP服务配置"""
        if len(self.config_path) == 0:
            return {}

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            return config.get("mcpServers", {})
        except Exception as e:
            logger.bind(tag=TAG).error(
                f"Error loading MCP config from {self.config_path}: {e}"
            )
            return {}

    def _build_client_config(self, srv_config: Dict[str, Any]) -> Dict[str, Any]:
        """复制服务配置并注入动态请求头提供器"""
        client_config = dict(srv_config)
        original_header_provider = client_config.get("header_provider")

        def header_provider() -> Dict[str, Any]:
            headers: Dict[str, Any] = {}

            if original_header_provider:
                try:
                    provider_headers = (
                        original_header_provider()
                        if callable(original_header_provider)
                        else original_header_provider
                    )
                    if provider_headers:
                        headers.update(
                            {
                                key: value
                                for key, value in dict(provider_headers).items()
                                if value is not None
                            }
                        )
                except Exception as e:
                    logger.bind(tag=TAG).warning(f"获取原始 header_provider 失败: {e}")

            device_id = getattr(self.conn, "device_id", None)
            if device_id:
                headers["X-Device-Id"] = device_id

            return headers

        client_config["header_provider"] = header_provider
        return client_config

    async def _create_client(
        self, name: str, srv_config: Dict[str, Any]
    ) -> ServerMCPClient:
        """根据服务配置创建并初始化MCP客户端"""
        logger.bind(tag=TAG).info(f"初始化服务端MCP客户端: {name}")
        client = ServerMCPClient(self._build_client_config(srv_config))
        await client.initialize(logging_callback=self.logging_callback)
        return client

    def _rebuild_all_tools(self) -> int:
        """从所有客户端重新汇总工具列表"""
        before_count = len(self.tools)
        tools: List[Dict[str, Any]] = []
        for client in self.clients.values():
            tools.extend(client.get_available_tools())
        self.tools = tools
        after_count = len(self.tools)

        logger.bind(tag=TAG).info(
            f"服务端MCP工具列表已重建: {before_count} -> {after_count}"
        )
        return after_count

    def _find_client_by_tool(
        self, tool_name: str
    ) -> Tuple[str | None, ServerMCPClient | None]:
        """根据工具名查找所属客户端"""
        for name, client in self.clients.items():
            if client.has_tool(tool_name):
                return name, client
        return None, None

    def _prepare_tool_arguments(
        self, tool_name: str, arguments: Dict[str, Any] | None
    ) -> Dict[str, Any]:
        """补充服务端MCP工具调用参数"""
        prepared_arguments = dict(arguments or {})
        return prepared_arguments

    async def initialize_servers(self) -> None:
        """初始化所有MCP服务"""
        config = self.load_config()
        self.tools = []

        for name, srv_config in config.items():
            if not srv_config.get("command") and not srv_config.get("url"):
                logger.bind(tag=TAG).warning(
                    f"Skipping server {name}: neither command nor url specified"
                )
                continue

            try:
                client = await self._create_client(name, srv_config)
                self.clients[name] = client
            except Exception as e:
                logger.bind(tag=TAG).error(
                    f"Failed to initialize MCP server {name}: {e}"
                )

        self._rebuild_all_tools()

        # 输出当前支持的服务端MCP工具列表
        if hasattr(self.conn, "func_handler") and self.conn.func_handler:
            if hasattr(self.conn.func_handler, "tool_manager"):
                self.conn.func_handler.tool_manager.refresh_tools()
            self.conn.func_handler.current_support_functions()

    def get_all_tools(self) -> List[Dict[str, Any]]:
        """获取所有服务的工具function定义"""
        return self.tools

    def is_mcp_tool(self, tool_name: str) -> bool:
        """检查是否是MCP工具"""
        for tool in self.tools:
            if (
                tool.get("function") is not None
                and tool["function"].get("name") == tool_name
            ):
                return True
        return False

    async def refresh_all_tools(self) -> int:
        """刷新所有客户端的远端工具，并重建本地汇总工具列表"""
        before_count = len(self.tools)

        for name, client in list(self.clients.items()):
            try:
                await client.refresh_tools()
            except Exception as e:
                logger.bind(tag=TAG).warning(
                    f"刷新服务端MCP客户端工具失败 {name}: {e}"
                )

        after_count = self._rebuild_all_tools()
        logger.bind(tag=TAG).info(
            f"服务端MCP工具总数已刷新: {before_count} -> {after_count}"
        )
        return after_count

    async def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """执行工具调用，失败时会尝试重新连接"""
        max_retries = 3
        retry_interval = 2

        client_name, target_client = self._find_client_by_tool(tool_name)
        if not target_client:
            logger.bind(tag=TAG).info(
                f"工具 {tool_name} 初次查找未命中，先刷新服务端MCP工具列表后重试"
            )
            await self.refresh_all_tools()
            client_name, target_client = self._find_client_by_tool(tool_name)

        if not target_client:
            raise ValueError(f"工具 {tool_name} 在任意MCP服务中未找到")

        call_arguments = self._prepare_tool_arguments(tool_name, arguments)
        logger.bind(tag=TAG).info(
            f"执行服务端MCP工具 {tool_name}，参数: {call_arguments}"
        )

        for attempt in range(max_retries):
            try:
                return await target_client.call_tool(
                    tool_name,
                    call_arguments,
                    progress_callback=self.progress_callback,
                )
            except Exception as e:
                if attempt == max_retries - 1:
                    raise

                logger.bind(tag=TAG).warning(
                    f"执行工具 {tool_name} 失败 (尝试 {attempt + 1}/{max_retries}): {e}"
                )

                logger.bind(tag=TAG).info(
                    f"重试前尝试重新连接 MCP 客户端 {client_name}"
                )
                try:
                    await target_client.cleanup()

                    config = self.load_config()
                    if client_name in config:
                        client = await self._create_client(client_name, config[client_name])
                        self.clients[client_name] = client
                        target_client = client
                        self._rebuild_all_tools()
                        logger.bind(tag=TAG).info(
                            f"成功重新连接 MCP 客户端: {client_name}"
                        )
                    else:
                        logger.bind(tag=TAG).error(
                            f"Cannot reconnect MCP client {client_name}: config not found"
                        )
                except Exception as reconnect_error:
                    logger.bind(tag=TAG).error(
                        f"Failed to reconnect MCP client {client_name}: {reconnect_error}"
                    )

                await asyncio.sleep(retry_interval)

    async def cleanup_all(self) -> None:
        """关闭所有 MCP客户端"""
        for name, client in list(self.clients.items()):
            try:
                if hasattr(client, "cleanup"):
                    await asyncio.wait_for(client.cleanup(), timeout=20)
                logger.bind(tag=TAG).info(f"服务端MCP客户端已关闭: {name}")
            except (asyncio.TimeoutError, Exception) as e:
                logger.bind(tag=TAG).error(f"关闭服务端MCP客户端 {name} 时出错: {e}")
        self.clients.clear()
        self.tools = []

    async def logging_callback(self, params: LoggingMessageNotificationParams):
        logger.bind(tag=TAG).info(
            f"[Server Log - {params.level.upper()}] {params.data}"
        )

    async def progress_callback(
        self, progress: float, total: float | None, message: str | None
    ) -> None:
        logger.bind(tag=TAG).info(f"[Progress {progress}/{total}]: {message}")
