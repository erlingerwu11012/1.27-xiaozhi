"""设备端MCP工具执行器"""

from typing import Dict, Any
from ..base import ToolType, ToolDefinition, ToolExecutor
from plugins_func.register import Action, ActionResponse
from .mcp_handler import call_mcp_tool
from core.utils.tool_result import DeviceToolError, require_enrollment_accepted


class DeviceMCPExecutor(ToolExecutor):
    """设备端MCP工具执行器"""

    def __init__(self, conn):
        self.conn = conn

    async def execute(
        self, conn, tool_name: str, arguments: Dict[str, Any]
    ) -> ActionResponse:
        """执行设备端MCP工具"""
        if not hasattr(conn, "mcp_client") or not conn.mcp_client:
            return ActionResponse(
                action=Action.ERROR,
                response="设备端MCP客户端未初始化",
            )

        if not await conn.mcp_client.is_ready():
            return ActionResponse(
                action=Action.ERROR,
                response="设备端MCP客户端未准备就绪",
            )

        try:
            # 转换参数为JSON字符串
            import json

            args_str = json.dumps(arguments) if arguments else "{}"

            # 调用设备端MCP工具
            result = await call_mcp_tool(conn, conn.mcp_client, tool_name, args_str)

            # 人脸录入启动成功：静默（Action.NONE），由固件本地 START 独占播报；
            # Only acceptance is acknowledged; capture and web commitment are separate stages.
            from core.utils.face_enrollment_start_intent import (
                ENROLL_STARTED_MARKER,
                is_face_enroll_start_tool,
            )

            if is_face_enroll_start_tool(tool_name):
                require_enrollment_accepted(result)
                return ActionResponse(
                    action=Action.NONE, result=ENROLL_STARTED_MARKER
                )

            resultJson = None
            if isinstance(result, str):
                try:
                    resultJson = json.loads(result)
                except Exception as e:
                    pass

            # 视觉大模型不经过二次LLM处理
            if isinstance(resultJson, dict) and 'face.identify' in tool_name.replace('_', '.'):
                status = resultJson.get('status')
                if status == 'known' and resultJson.get('confirmed') is False:
                    status = 'ambiguous'
                messages = {'empty':'当前账号还没有录入人脸。',
                            'unknown':'这次没有匹配到已录入的人脸。',
                            'no_face':'这次没有拍到清晰的人脸。',
                            'ambiguous':'这次识别结果不一致，请正对摄像头再试一次。'}
                if status in messages:
                    return ActionResponse(action=Action.RESPONSE, response=messages[status], result=str(result))
            # Device business fields named "action" (primary/secondary) are data,
            # never a request to select a server Action enum or bypass receipts.
            return ActionResponse(action=Action.REQLLM, result=str(result))

        except DeviceToolError as e:
            return ActionResponse(action=Action.RESPONSE, response=e.user_message, result=json.dumps(e.as_dict(), ensure_ascii=False))
        except ValueError as e:
            # 工具名不在当前会话 tools/list 白名单内：把错误信息回喂给 LLM，
            # 要求其按 tools/list 重新选择工具，而不是直接把错误播报给用户
            return ActionResponse(action=Action.REQLLM, result=str(e))
        except TimeoutError as e:
            # 超时只标记本次工具失败，连接保持；由 LLM 生成兜底话术
            return ActionResponse(action=Action.RESPONSE, response=DeviceToolError('request_timeout').user_message)
        except Exception as e:
            return ActionResponse(action=Action.ERROR, response=str(e))

    def get_tools(self) -> Dict[str, ToolDefinition]:
        """获取所有设备端MCP工具"""
        if not hasattr(self.conn, "mcp_client") or not self.conn.mcp_client:
            return {}

        tools = {}
        mcp_tools = self.conn.mcp_client.get_available_tools()

        for tool in mcp_tools:
            from core.utils.reminder_tool_contracts import describe_tool
            tool = describe_tool(tool)
            func_def = tool.get("function", {})
            tool_name = func_def.get("name", "")

            if tool_name:
                # 模型侧不再暴露旧版 card_*；设备 tools/list 缓存不受影响
                from core.utils.device_reminder import is_legacy_card_tool_name

                if is_legacy_card_tool_name(tool_name):
                    continue
                tools[tool_name] = ToolDefinition(
                    name=tool_name, description=tool, tool_type=ToolType.DEVICE_MCP
                )

        return tools

    def has_tool(self, tool_name: str) -> bool:
        """检查是否有指定的设备端MCP工具"""
        if not hasattr(self.conn, "mcp_client") or not self.conn.mcp_client:
            return False

        return self.conn.mcp_client.has_tool(tool_name)
