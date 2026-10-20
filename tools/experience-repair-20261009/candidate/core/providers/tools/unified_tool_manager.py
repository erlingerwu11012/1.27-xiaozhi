"""统一工具管理器"""

import asyncio
import json
from typing import Dict, List, Optional, Any, Set

# 外部工具（尤其是 MCP）调用超时时间，防止卡死
TOOL_EXECUTE_TIMEOUT = 60
from config.logger import setup_logging
from core.utils.util import sanitize_tool_name
from plugins_func.register import Action, ActionResponse
from .base import ToolType, ToolDefinition, ToolExecutor


class ToolManager:
    """统一工具管理器，管理所有类型的工具"""

    def __init__(self, conn):
        self.conn = conn
        self.logger = setup_logging()
        self.executors: Dict[ToolType, ToolExecutor] = {}
        self._cached_tools: Optional[Dict[str, ToolDefinition]] = None
        self._cached_function_descriptions: Optional[List[Dict[str, Any]]] = None
        # 公开名碰撞：不可静默选最后一个；记录后在执行时拒绝歧义名
        self._ambiguous_tool_names: Set[str] = set()
        self._tool_name_sources: Dict[str, List[str]] = {}

    def register_executor(self, tool_type: ToolType, executor: ToolExecutor):
        """注册工具执行器"""
        self.executors[tool_type] = executor
        self._invalidate_cache()
        self.logger.debug(f"注册工具执行器: {tool_type.value}")

    def _invalidate_cache(self):
        """使缓存失效"""
        self._cached_tools = None
        self._cached_function_descriptions = None

    def get_all_tools(self) -> Dict[str, ToolDefinition]:
        """获取所有工具定义"""
        if self._cached_tools is not None:
            return self._cached_tools

        all_tools = {}
        sources: Dict[str, List[str]] = {}
        ambiguous: Set[str] = set()
        for tool_type, executor in self.executors.items():
            try:
                tools = executor.get_tools()
                for name, definition in tools.items():
                    src = tool_type.value
                    sources.setdefault(name, []).append(src)
                    if name in all_tools:
                        ambiguous.add(name)
                        self.logger.warning(
                            f"工具名称冲突: {name} "
                            f"(已有来源={sources.get(name)}, 新来源={src})；"
                            f"歧义名称将拒绝执行直至治理映射解决"
                        )
                        # 不静默覆盖：保留先注册者，标记歧义
                        continue
                    all_tools[name] = definition
            except Exception as e:
                self.logger.error(f"获取{tool_type.value}工具时出错: {e}")

        self._ambiguous_tool_names = ambiguous
        self._tool_name_sources = sources
        self._cached_tools = all_tools
        return all_tools

    def get_ambiguous_tool_names(self) -> Set[str]:
        self.get_all_tools()
        return set(self._ambiguous_tool_names)

    def get_function_descriptions(self) -> List[Dict[str, Any]]:
        """获取所有工具的函数描述（OpenAI格式）"""
        # 不缓存改写后的描述：设备 MCP 工具集会随 tools/list 变化，
        # 且提醒类描述需按「当前是否支持 note.add」动态调整。
        descriptions = []
        tools = self.get_all_tools()
        for tool_definition in tools.values():
            descriptions.append(tool_definition.description)

        try:
            from core.utils.device_reminder import rewrite_reminder_tool_descriptions

            descriptions = rewrite_reminder_tool_descriptions(descriptions, self.conn)
        except Exception as e:
            self.logger.debug(f"改写提醒工具描述跳过: {e}")

        self._cached_function_descriptions = descriptions
        return descriptions

    def has_tool(self, tool_name: str) -> bool:
        """检查是否存在指定工具"""
        tools = self.get_all_tools()
        return tool_name in tools

    def get_tool_type(self, tool_name: str) -> Optional[ToolType]:
        """获取工具类型"""
        tools = self.get_all_tools()
        tool_def = tools.get(tool_name)
        return tool_def.tool_type if tool_def else None

    def resolve_tool_name(self, tool_name: str) -> Optional[str]:
        """把 LLM 生成的函数名解析为已注册的工具名。

        仅接受精确匹配：注册名（sanitized 形式）或其 sanitize 后等价形式
        （即 LLM 直接输出了带点号的原始名，如 camera.open -> camera_open）。
        任何其他名称（如 selfcameratake_photo）一律不猜测、不模糊恢复，
        由调用方拦截并要求 LLM 按工具列表重新选择。
        """
        tools = self.get_all_tools()
        if tool_name in tools:
            return tool_name
        sanitized = sanitize_tool_name(tool_name)
        if sanitized != tool_name and sanitized in tools:
            self.logger.info(
                f"[工具名解析] LLM使用了原始工具名={tool_name}，映射为注册名={sanitized}"
            )
            return sanitized
        return None

    async def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> ActionResponse:
        """Validate and remember a dispatch before any executor can write."""
        from core.utils.operation_control import enabled, get_control, Request, CONTRACTS, feedback
        if not enabled(self.conn):
            return await self._execute_tool(tool_name, arguments)
        # Device catalogs can change while a connection remains open.
        self._invalidate_cache()
        resolved = self.resolve_tool_name(tool_name)
        if resolved is None:
            return ActionResponse(action=Action.RESPONSE, response="当前没有这项可用能力，这次没有执行。")
        definition = self.get_all_tools()[resolved]
        if definition.tool_type == ToolType.DEVICE_MCP:
            client = getattr(self.conn, "mcp_client", None)
            if not client or not client.ready or getattr(client, "closed", False):
                return ActionResponse(action=Action.RESPONSE, response="设备尚未连接好，这次没有执行。")
        control = get_control(self.conn)
        try:
            from jsonschema import Draft202012Validator
            schema = definition.description.get("function", {}).get("parameters", {"type": "object"})
            arguments = control.normalize_numeric_arguments(resolved, arguments, schema)
            Draft202012Validator(schema).validate(arguments)
        except Exception:
            return ActionResponse(action=Action.RESPONSE, response="操作参数不符合这台设备的要求，这次没有执行。")
        mismatch = control.validate_intent(resolved, arguments)
        if mismatch:
            if (resolved == 'self_get_device_status' and not control.plan.requests
                    and not control.ledger and not control.force_answer):
                control.force_answer = True
                return ActionResponse(action=Action.REQLLM, result=(
                    '未执行任何设备查询或操作。当前请求是概念解释，请直接回答用户的原问题，'
                    '不要再调用工具，不得声称变更了设备。'))
            return ActionResponse(action=Action.RESPONSE, response=mismatch)
        # One turn cannot re-dispatch an identical command, even on unknown timeout.
        # Legitimate repeated tasks in a later user turn receive a fresh ledger.
        fingerprint = (resolved, json.dumps(arguments, sort_keys=True, ensure_ascii=False))
        read_only = resolved in {'self_get_device_status', 'get_world_time', 'query_memory',
                                 'note_list', 'habit_list_manual', 'reminder_get_current'}
        previous = None if read_only else control.ledger.get(fingerprint)
        if previous is not None:
            return previous
        marker = ActionResponse(action=Action.RESPONSE, response="这项请求已经发出，不能确认结果前不会重复执行。")
        control.ledger[fingerprint] = marker
        try:
            result = await self._execute_tool(resolved, arguments)
        except asyncio.CancelledError:
            marker.response = "这项请求已中断，结果尚不确定，不会自动重复执行。"
            raise
        # Control facts reach every native/direct reply path before speech. The
        # primary model remains responsible for read-only status and photo content.
        if resolved == 'reminder_action' and result.action == Action.REQLLM:
            from core.utils.reminder_tool_contracts import reminder_action_completed
            if reminder_action_completed(arguments, result.result):
                result = ActionResponse(action=Action.RESPONSE, response=str(result.result), result=result.result)
                result.operation_state = 'completed'
            else:
                result = ActionResponse(action=Action.RESPONSE, response='这次没有确认到提醒操作完成的回执，结果尚未确定。')
        kind = next((k for k, contract in CONTRACTS.items() if contract[0] == resolved), None)
        if kind and kind not in {"status", "photo"}:
            text = feedback(Request(kind, dict(arguments)), result)
            if text is not None:
                state = getattr(result, 'operation_state', None)
                result = ActionResponse(action=Action.RESPONSE, response=text, result=result.result)
                if state:
                    result.operation_state = state
        control.ledger[fingerprint] = result
        return result

    async def _execute_tool(
        self, tool_name: str, arguments: Dict[str, Any]
    ) -> ActionResponse:
        """执行工具调用"""
        try:
            llm_raw_name = tool_name
            # 公开名碰撞：诊断并拒绝，不静默选最后一个
            if tool_name in self.get_ambiguous_tool_names():
                srcs = self._tool_name_sources.get(tool_name) or []
                self.logger.error(
                    f"[工具歧义] 名称={tool_name} 来源冲突={srcs}，拒绝执行"
                )
                return ActionResponse(
                    action=Action.ERROR,
                    response=(
                        f"工具名称 {tool_name} 存在多个来源冲突（{srcs}），"
                        f"已拒绝执行。请管理员完成治理映射后再试。"
                    ),
                )
            # 白名单校验 + 名称模糊恢复：LLM 生成的名字若不在已注册工具中，
            # 尝试恢复；恢复失败则拦截并要求 LLM 按工具列表重新选择
            resolved_name = self.resolve_tool_name(tool_name)
            if resolved_name is None:
                supported = self.get_supported_tool_names()
                self.logger.warning(
                    f"[工具拦截] LLM原始函数名={llm_raw_name} 不在当前工具白名单中，已拦截。"
                    f"可用工具: {supported}"
                )
                return ActionResponse(
                    action=Action.REQLLM,
                    result=(
                        f"工具 {llm_raw_name} 不存在，禁止调用。"
                        f"请严格从以下工具列表中重新选择正确的工具名: {supported}"
                    ),
                )
            tool_name = resolved_name

            # 查找工具类型
            tool_type = self.get_tool_type(tool_name)
            if not tool_type:
                return ActionResponse(
                    action=Action.NOTFOUND,
                    response=f"工具 {tool_name} 不存在",
                )

            # 获取对应的执行器
            executor = self.executors.get(tool_type)
            if not executor:
                return ActionResponse(
                    action=Action.ERROR,
                    response=f"工具类型 {tool_type.value} 的执行器未注册",
                )

            # 禁止设备语音正式建档 / 按名删除人脸
            try:
                from core.utils.face_enrollment_guard import (
                    maybe_intercept_face_enrollment_tool,
                )

                face_blocked = maybe_intercept_face_enrollment_tool(
                    tool_name, arguments or {}
                )
                if face_blocked is not None:
                    self.logger.info(f"人脸语音建档已拒绝: {tool_name}")
                    return face_blocked
            except Exception as e:
                self.logger.error(f"人脸建档禁令异常: {e}")
                return ActionResponse(
                    action=Action.RESPONSE,
                    response="人脸用户请在管理网页手动输入姓名并完成照片录入；设备语音不能创建或命名人脸。",
                )

            # 设备提醒硬门禁 / 路由：有 note.add 时拦截 add_reminder、假成功便签、相对时间闹钟
            try:
                from core.utils.device_reminder import maybe_intercept_reminder_tool

                intercepted = await maybe_intercept_reminder_tool(
                    self.conn, tool_name, arguments or {}
                )
                if intercepted is not None:
                    self.logger.info(
                        f"提醒工具已由服务端拦截处理: {tool_name}，参数: {arguments}"
                    )
                    return intercepted
            except Exception as e:
                self.logger.error(f"提醒工具拦截层异常: {e}")
                return ActionResponse(
                    action=Action.REQLLM,
                    result=f"提醒处理失败：{e}。请让用户确认具体提醒时间。",
                )

            # 执行工具（增加超时保护，防止 MCP 等外部工具无响应导致卡死）
            self.logger.info(f"执行工具: {tool_name}，参数: {arguments}")
            try:
                result = await asyncio.wait_for(
                    executor.execute(self.conn, tool_name, arguments),
                    timeout=TOOL_EXECUTE_TIMEOUT,
                )
            except asyncio.TimeoutError:
                self.logger.error(f"工具 {tool_name} 调用超时（{TOOL_EXECUTE_TIMEOUT} 秒）")
                return ActionResponse(
                    action=Action.ERROR,
                    response="等待设备回执超时，结果尚不确定，我不会自动重复执行。",
                )
            # 成功读取当前提醒后写入会话快照，供 reminder_action 校验
            if tool_name in (
                "reminder_get_current",
                "reminder.get_current",
            ):
                try:
                    from core.utils.device_reminder import note_reminder_get_current_result

                    note_reminder_get_current_result(self.conn, result)
                except Exception as e:
                    self.logger.debug(f"reminder_get_current 快照记录跳过: {e}")
            self.logger.debug(f"工具执行结果: {result}")
            return result

        except Exception as e:
            self.logger.error(f"执行工具 {tool_name} 时出错: {e}")
            return ActionResponse(action=Action.ERROR, response=str(e))

    def get_supported_tool_names(self) -> List[str]:
        """获取所有支持的工具名称"""
        tools = self.get_all_tools()
        return list(tools.keys())

    def refresh_tools(self):
        """刷新工具缓存"""
        self._invalidate_cache()
        self.logger.debug("工具缓存已刷新")

    def get_tool_statistics(self) -> Dict[str, int]:
        """获取工具统计信息"""
        stats = {}
        for tool_type, executor in self.executors.items():
            try:
                tools = executor.get_tools()
                stats[tool_type.value] = len(tools)
            except Exception as e:
                self.logger.error(f"获取{tool_type.value}工具统计时出错: {e}")
                stats[tool_type.value] = 0
        return stats
