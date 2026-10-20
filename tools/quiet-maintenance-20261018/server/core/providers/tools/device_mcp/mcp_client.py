"""设备端MCP客户端定义"""

import asyncio
from concurrent.futures import Future
from core.utils.util import sanitize_tool_name
from config.logger import setup_logging

TAG = __name__
logger = setup_logging()


class MCPClient:
    """设备端MCP客户端，用于管理MCP状态和工具

    工具列表严格按 WebSocket 会话隔离：每个连接的 hello 都会创建新的 MCPClient，
    缓存 key = (device_id, firmware_version, session_id)，不跨会话复用。
    """

    def __init__(self, device_id: str = "", firmware_version: str = "", session_id: str = ""):
        self.device_id = device_id
        self.firmware_version = firmware_version
        self.session_id = session_id
        self.tools = {}  # sanitized_name -> tool_data
        self.name_mapping = {}  # sanitized_name -> original name（tools/list 原样返回）
        self.ready = False
        self.call_results = {}  # To store Futures for tool call responses
        self.next_id = 1
        self.lock = asyncio.Lock()
        self._cached_available_tools = None  # Cache for get_available_tools
        self.requests = {}
        self.catalog_generation = 0
        self.catalog_version = 0
        self.catalog_pages = []
        self.catalog_cursors = set()
        self.catalog_timer = None
        self.closed = False
        self.capabilities = {}
        self.ready_event = asyncio.Event()

    @property
    def cache_key(self) -> str:
        return f"device_id={self.device_id}|firmware={self.firmware_version}|session_id={self.session_id}"

    def has_tool(self, name: str) -> bool:
        return name in self.tools

    def get_raw_tool_names(self) -> list:
        """返回设备 tools/list 原始工具名列表（未经任何改写）"""
        return list(self.name_mapping.values())

    def resolve_tool_name(self, name: str):
        """把 LLM 生成的函数名解析为设备 tools/list 中的原始工具名。

        仅接受精确匹配：
        1. sanitized 名精确匹配（LLM 正常应生成该形式，如 camera_open）
        2. 原始名精确匹配（LLM 直接用了带点号的原名，如 camera.open）
        其他任何名称（如 selfcameratake_photo）一律返回 None，
        由调用方拦截并要求 LLM 重新选择，绝不发给设备。
        """
        if not name:
            return None
        if name in self.name_mapping:
            return self.name_mapping[name]
        for original in self.name_mapping.values():
            if name == original:
                return original
        return None

    async def reset_tools(self):
        """清空工具列表（新一轮 tools/list 开始时调用，避免残留旧数据）"""
        async with self.lock:
            self.tools = {}
            self.name_mapping = {}
            self.ready = False
            self._cached_available_tools = None

    def get_available_tools(self, include_maintenance=False) -> list:
        if not self.ready or self.closed:
            return []
        # Check if the cache is valid
        if self._cached_available_tools is not None and not include_maintenance:
            return self._cached_available_tools

        # If cache is not valid, regenerate the list
        result = []
        for tool_name, tool_data in self.tools.items():
            if self.name_mapping.get(tool_name,"").startswith(("behavior.","habit.")) and self.capabilities.get("experimental",{}).get("personBehavior",0)<2:
                continue
            if self.name_mapping.get(tool_name) in {"behavior.ack", "habit.analyze", "behavior.clear"}:
                continue
            if self.name_mapping.get(tool_name) == "habit.learn" and not include_maintenance:
                continue
            function_def = {
                "name": tool_name,
                "description": tool_data["description"],
                "parameters": {
                    "type": tool_data["inputSchema"].get("type", "object"),
                    "properties": tool_data["inputSchema"].get("properties", {}),
                    "required": tool_data["inputSchema"].get("required", []),
                },
            }
            result.append({"type": "function", "function": function_def})

        if not include_maintenance:
            self._cached_available_tools = result
        return result

    async def is_ready(self) -> bool:
        async with self.lock:
            return self.ready

    async def set_ready(self, status: bool):
        async with self.lock:
            self.ready = status
            if status:
                self.ready_event.set()
            else:
                self.ready_event.clear()

    async def wait_ready(self, timeout=2):
        if not self.ready:
            try:
                await asyncio.wait_for(self.ready_event.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                return False
        return self.ready and not self.closed

    async def add_tool(self, tool_data: dict):
        async with self.lock:
            sanitized_name = sanitize_tool_name(tool_data["name"])
            self.tools[sanitized_name] = tool_data
            self.name_mapping[sanitized_name] = tool_data["name"]
            self._cached_available_tools = (
                None  # Invalidate the cache when a tool is added
            )

    async def get_next_id(self) -> int:
        async with self.lock:
            if self.closed or self.next_id > 2147483647:
                raise ConnectionError('MCP connection closed or request IDs exhausted')
            current_id = self.next_id
            self.next_id += 1
            return current_id

    async def register_call_result_future(self, id: int, future: Future):
        async with self.lock:
            self.call_results[id] = future

    async def resolve_call_result(self, id: int, result: any):
        async with self.lock:
            if id in self.call_results:
                future = self.call_results.pop(id)
                if not future.done():
                    future.set_result(result)

    async def reject_call_result(self, id: int, exception: Exception):
        async with self.lock:
            if id in self.call_results:
                future = self.call_results.pop(id)
                if not future.done():
                    future.set_exception(exception)

    async def cleanup_call_result(self, id: int):
        async with self.lock:
            future = self.call_results.pop(id, None)
            if future is not None and not future.done():
                future.cancel()

    async def register_request(self, kind, generation=0):
        request_id = await self.get_next_id()
        self.requests[request_id] = (kind, generation)
        return request_id

    def take_request(self, request_id):
        return self.requests.pop(request_id, (None, None))

    async def begin_catalog(self):
        async with self.lock:
            self.catalog_generation += 1
            self.ready = False
            self.catalog_pages = []
            self.ready_event.clear()
            self.catalog_cursors = set()
            self.requests = {k:v for k,v in self.requests.items() if v[0] != 'tools/list'}
            if self.catalog_timer:
                self.catalog_timer.cancel()
            generation = self.catalog_generation
            def expire():
                if generation == self.catalog_generation:
                    self.requests = {k:v for k,v in self.requests.items() if v[0] != 'tools/list'}
                    self.catalog_pages = []
                    self.ready = False
                    logger.bind(tag=TAG).warning('MCP catalog refresh timeout')
            self.catalog_timer = asyncio.get_running_loop().call_later(20, expire)
            return generation

    async def finish_catalog(self, generation):
        async with self.lock:
            if generation != self.catalog_generation or self.closed:
                return False
            tools = {}
            mapping = {}
            for tool in self.catalog_pages:
                if not isinstance(tool, dict) or not isinstance(tool.get('name'), str):
                    continue
                name = sanitize_tool_name(tool['name'])
                if name in mapping and mapping[name] != tool['name']:
                    raise ValueError('MCP tool name collision')
                schema = tool.get('inputSchema')
                schema = schema if isinstance(schema, dict) else {'type':'object','properties':{}}
                tools[name] = dict(name=tool['name'], description=str(tool.get('description', '')), inputSchema=schema)
                mapping[name] = tool['name']
            for tool in tools.values():
                for name, original in mapping.items():
                    tool['description'] = tool['description'].replace(original, name)
            self.tools, self.name_mapping = tools, mapping
            self.catalog_pages = []
            self._cached_available_tools = None
            self.ready = True
            self.ready_event.set()
            self.catalog_version += 1
            if self.catalog_timer:
                self.catalog_timer.cancel()
                self.catalog_timer = None
            return True

    async def close(self):
        from core.utils.tool_result import DeviceToolError
        async with self.lock:
            self.closed = True
            self.ready = False
            self.ready_event.clear()
            if self.catalog_timer:
                self.catalog_timer.cancel()
                self.catalog_timer = None
            for future in self.call_results.values():
                if not future.done():
                    future.set_exception(DeviceToolError('connection_closed'))
            self.call_results.clear()
            self.requests.clear()
            self.catalog_pages = []
