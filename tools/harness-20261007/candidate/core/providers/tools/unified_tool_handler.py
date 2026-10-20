"""统一工具处理器"""

import json
from typing import Dict, List, Any, Optional
from config.logger import setup_logging
from plugins_func.loadplugins import auto_import_modules

from .base import ToolType
from plugins_func.register import Action, ActionResponse
from .unified_tool_manager import ToolManager
from .server_plugins import ServerPluginExecutor
from .server_mcp import ServerMCPExecutor
from .device_iot import DeviceIoTExecutor
from .device_mcp import DeviceMCPExecutor
from .mcp_endpoint import MCPEndpointExecutor
from core.utils import trace_log as trace
import time


class UnifiedToolHandler:
    """统一工具处理器"""

    def __init__(self, conn):
        self.conn = conn
        self.config = conn.config
        self.logger = setup_logging()

        # 创建工具管理器
        self.tool_manager = ToolManager(conn)

        # 创建各类执行器
        self.server_plugin_executor = ServerPluginExecutor(conn)
        self.server_mcp_executor = ServerMCPExecutor(conn)
        self.device_iot_executor = DeviceIoTExecutor(conn)
        self.device_mcp_executor = DeviceMCPExecutor(conn)
        self.mcp_endpoint_executor = MCPEndpointExecutor(conn)

        # 注册执行器
        self.tool_manager.register_executor(
            ToolType.SERVER_PLUGIN, self.server_plugin_executor
        )
        self.tool_manager.register_executor(
            ToolType.SERVER_MCP, self.server_mcp_executor
        )
        self.tool_manager.register_executor(
            ToolType.DEVICE_IOT, self.device_iot_executor
        )
        self.tool_manager.register_executor(
            ToolType.DEVICE_MCP, self.device_mcp_executor
        )
        self.tool_manager.register_executor(
            ToolType.MCP_ENDPOINT, self.mcp_endpoint_executor
        )

        # 初始化标志
        self.finish_init = False

    async def _initialize(self):
        """异步初始化"""
        try:
            # 自动导入插件模块
            auto_import_modules("plugins_func.functions")

            # 初始化服务端MCP
            await self.server_mcp_executor.initialize()

            # 初始化MCP接入点
            await self._initialize_mcp_endpoint()

            # 初始化Home Assistant（如果需要）
            self._initialize_home_assistant()

            self.finish_init = True
            self.logger.debug("统一工具处理器初始化完成")

            # 输出当前支持的所有工具列表
            self.current_support_functions()

        except Exception as e:
            self.logger.error(f"统一工具处理器初始化失败: {e}")

    async def _initialize_mcp_endpoint(self):
        """初始化MCP接入点"""
        try:
            from .mcp_endpoint import connect_mcp_endpoint

            # 从配置中获取MCP接入点URL
            mcp_endpoint_url = self.config.get("mcp_endpoint", "")

            if (
                mcp_endpoint_url
                and "你的" not in mcp_endpoint_url
                and mcp_endpoint_url != "null"
            ):
                self.logger.info(f"正在初始化MCP接入点: {mcp_endpoint_url}")
                mcp_endpoint_client = await connect_mcp_endpoint(
                    mcp_endpoint_url, self.conn
                )

                if mcp_endpoint_client:
                    # 将MCP接入点客户端保存到连接对象中
                    self.conn.mcp_endpoint_client = mcp_endpoint_client
                    self.logger.info("MCP接入点初始化成功")
                else:
                    self.logger.warning("MCP接入点初始化失败")

        except Exception as e:
            self.logger.error(f"初始化MCP接入点失败: {e}")

    def _initialize_home_assistant(self):
        """初始化Home Assistant提示词"""
        try:
            from plugins_func.functions.hass_init import append_devices_to_prompt

            append_devices_to_prompt(self.conn)
        except ImportError:
            pass  # 忽略导入错误
        except Exception as e:
            self.logger.error(f"初始化Home Assistant失败: {e}")

    def get_functions(self) -> List[Dict[str, Any]]:
        """获取所有工具的函数描述"""
        return self.tool_manager.get_function_descriptions()

    def get_functions_for_names(self, names: List[str]) -> List[Dict[str, Any]]:
        """按候选公开名返回工具描述；schema 不改，仅过滤列表。"""
        from .tool_selector import filter_descriptions_by_names

        all_desc = self.tool_manager.get_function_descriptions()
        return filter_descriptions_by_names(all_desc, names)

    def build_tool_catalog(self):
        """构建当前合法工具快照（改写描述后）。"""
        from .tool_catalog import ToolCatalogBuilder, load_routing_policy
        from .tool_routing_config import get_tool_routing_config

        cfg = get_tool_routing_config(self.config)
        policy = load_routing_policy(cfg.get("policy_path"))
        descriptions = self.tool_manager.get_function_descriptions()
        tool_defs = self.tool_manager.get_all_tools()
        ambiguous = self.tool_manager.get_ambiguous_tool_names()
        return ToolCatalogBuilder(policy).build(
            descriptions,
            tool_defs,
            name_collisions=list(ambiguous),
        )

    def select_candidate_functions(
        self,
        query: str,
        *,
        turn_id: str,
        abort_epoch=None,
        mode: str = "enabled",
        recent_user_context=None,
    ):
        """本地候选筛选。返回 (functions_or_None用于发送, ToolSelectionContext)。

        mode=off: 不筛选，functions=全集，context.mode=off
        mode=shadow: 计算候选并记录，发送仍为全集
        mode=enabled: 发送候选集
        """
        from .tool_routing_config import get_tool_routing_config
        from .tool_selector import ToolSelector, SelectorConfig
        from .tool_catalog import load_routing_policy
        from .tool_selection_context import ToolSelectionContext

        cfg = get_tool_routing_config(self.config)
        effective_mode = mode if mode in ("off", "shadow", "enabled") else cfg["mode"]
        all_functions = self.get_functions()

        if effective_mode == "off":
            ctx = ToolSelectionContext(
                turn_id=turn_id,
                abort_epoch=abort_epoch,
                original_query=query or "",
                catalog_version="off",
                policy_version=str(cfg.get("policy_version") or "v1"),
                candidate_public_names=[],
                confidence="n/a",
                mode="off",
                exposed_public_names=[
                    (d.get("function") or {}).get("name")
                    for d in all_functions
                    if isinstance(d, dict)
                ],
            )
            return all_functions, ctx

        try:
            policy = load_routing_policy(cfg.get("policy_path"))
            catalog = self.build_tool_catalog()
            selector = ToolSelector(
                policy=policy,
                config=SelectorConfig(
                    soft_candidate_target=int(cfg["soft_candidate_target"]),
                    selector_budget_ms=float(cfg["selector_budget_ms"]),
                    fallback=str(cfg["fallback"]),
                ),
            )
            ctx = selector.select_for_connection(
                self.conn,
                query,
                catalog,
                turn_id=turn_id,
                abort_epoch=abort_epoch,
                mode=effective_mode,
                recent_user_context=recent_user_context,
            )
            if ctx.elapsed_ms > float(cfg["selector_budget_ms"]):
                self.logger.warning(
                    f"工具选择耗时 {ctx.elapsed_ms:.2f}ms 超过预算 "
                    f"{cfg['selector_budget_ms']}ms"
                )

            if effective_mode == "shadow":
                ctx.exposed_public_names = [
                    (d.get("function") or {}).get("name")
                    for d in all_functions
                    if isinstance(d, dict)
                ]
                self.logger.info(
                    f"[tool_routing:shadow] {ctx.to_log_dict()}"
                )
                return all_functions, ctx

            # enabled
            selected = self.get_functions_for_names(ctx.candidate_public_names)
            if not selected:
                # 候选为空不得静默失去合法能力
                ctx.confidence = "fallback"
                ctx.fallback_reason = ctx.fallback_reason or "empty_selection"
                ctx.candidate_public_names = [
                    (d.get("function") or {}).get("name")
                    for d in all_functions
                    if isinstance(d, dict)
                ]
                selected = all_functions
            ctx.exposed_public_names = [
                (d.get("function") or {}).get("name")
                for d in selected
                if isinstance(d, dict)
            ]
            self.logger.info(f"[tool_routing:enabled] {ctx.to_log_dict()}")
            return selected, ctx
        except Exception as e:
            self.logger.error(f"工具候选筛选异常，回退合法全集: {e}")
            ctx = ToolSelectionContext(
                turn_id=turn_id,
                abort_epoch=abort_epoch,
                original_query=query or "",
                catalog_version="error",
                policy_version=str(cfg.get("policy_version") or "v1"),
                candidate_public_names=[],
                confidence="fallback",
                fallback_reason=f"selector_error:{type(e).__name__}",
                mode=effective_mode,
                exposed_public_names=[
                    (d.get("function") or {}).get("name")
                    for d in all_functions
                    if isinstance(d, dict)
                ],
            )
            return all_functions, ctx

    def current_support_functions(self) -> List[str]:
        """获取当前支持的函数名称列表"""
        func_names = self.tool_manager.get_supported_tool_names()
        self.logger.info(f"当前支持的函数列表: {func_names}")
        return func_names

    def upload_functions_desc(self):
        """刷新函数描述列表"""
        self.tool_manager.refresh_tools()
        self.logger.info("函数描述列表已刷新")

    def has_tool(self, tool_name: str) -> bool:
        """检查是否有指定工具"""
        return self.tool_manager.has_tool(tool_name)

    async def handle_llm_function_call(
        self, conn, function_call_data: Dict[str, Any]
    ) -> Optional[ActionResponse]:
        """处理LLM函数调用"""
        try:
            # 处理多函数调用
            if "function_calls" in function_call_data:
                responses = []
                for call in function_call_data["function_calls"]:
                    result = await self.tool_manager.execute_tool(
                        call["name"], call.get("arguments", {})
                    )
                    responses.append(result)
                return self._combine_responses(responses)

            # 处理单函数调用
            function_name = function_call_data["name"]
            arguments = function_call_data.get("arguments", {})

            # 如果arguments是字符串，尝试解析为JSON
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments) if arguments else {}
                except json.JSONDecodeError:
                    self.logger.error(f"无法解析函数参数: {arguments}")
                    return ActionResponse(
                        action=Action.ERROR,
                        response="无法解析函数参数",
                    )

            self.logger.debug(f"调用函数: {function_name}, 参数: {arguments}")

            started = time.monotonic()
            trace.emit(
                "llm.tool_start",
                conn,
                {"name": function_name, "arguments": arguments},
            )
            # 执行工具调用
            result = await self.tool_manager.execute_tool(function_name, arguments)
            elapsed_ms = round((time.monotonic() - started) * 1000.0, 3)
            action = getattr(result, "action", None)
            trace.emit(
                "llm.tool_result",
                conn,
                {
                    "name": function_name,
                    "ok": action not in (Action.ERROR, Action.NOTFOUND) if action else True,
                    "action": str(action) if action is not None else None,
                    "result": getattr(result, "result", None),
                    "response": getattr(result, "response", None),
                    "elapsed_ms": elapsed_ms,
                },
            )
            return result

        except Exception as e:
            self.logger.error(f"处理function call错误: {e}")
            trace.emit(
                "llm.tool_error",
                conn,
                {"error_type": type(e).__name__, "error": str(e)},
            )
            return ActionResponse(action=Action.ERROR, response=str(e))

    def _combine_responses(self, responses: List[ActionResponse]) -> ActionResponse:
        """合并多个函数调用的响应"""
        if not responses:
            return ActionResponse(action=Action.NONE, response="无响应")

        # 如果有任何错误，返回第一个错误
        for response in responses:
            if response.action == Action.ERROR:
                return response

        # 合并所有成功的响应
        contents = []
        responses_text = []

        for response in responses:
            if response.content:
                contents.append(response.content)
            if response.response:
                responses_text.append(response.response)

        # 确定最终的动作类型
        final_action = Action.RESPONSE
        for response in responses:
            if response.action == Action.REQLLM:
                final_action = Action.REQLLM
                break

        return ActionResponse(
            action=final_action,
            result="; ".join(contents) if contents else None,
            response="; ".join(responses_text) if responses_text else None,
        )

    async def register_iot_tools(self, descriptors: List[Dict[str, Any]]):
        """注册IoT设备工具"""
        self.device_iot_executor.register_iot_tools(descriptors)
        self.tool_manager.refresh_tools()
        self.logger.info(f"注册了{len(descriptors)}个IoT设备的工具")

    def get_tool_statistics(self) -> Dict[str, int]:
        """获取工具统计信息"""
        return self.tool_manager.get_tool_statistics()

    async def cleanup(self):
        """清理资源"""
        try:
            await self.server_mcp_executor.cleanup()

            # 清理MCP接入点连接
            if (
                hasattr(self.conn, "mcp_endpoint_client")
                and self.conn.mcp_endpoint_client
            ):
                await self.conn.mcp_endpoint_client.close()

            self.logger.info("工具处理器清理完成")
        except Exception as e:
            self.logger.error(f"工具处理器清理失败: {e}")
