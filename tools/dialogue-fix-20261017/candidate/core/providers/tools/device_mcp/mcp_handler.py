"""设备端MCP客户端支持模块"""

import json
import asyncio
import re
import time
from concurrent.futures import Future
from core.utils.util import sanitize_tool_name
from config.logger import setup_logging
from .mcp_client import MCPClient
from core.utils.tool_result import DeviceToolError, unwrap_tool_result

TAG = __name__
logger = setup_logging()

# 摄像头相关 MCP 工具的最小超时（秒），按需求不得低于 10 秒
CAMERA_TOOL_MIN_TIMEOUT = 10


def effective_tool_timeout(tool_name: str, timeout: int) -> int:
    """摄像头类工具保证至少 CAMERA_TOOL_MIN_TIMEOUT 秒超时"""
    if "camera" in (tool_name or "") and timeout < CAMERA_TOOL_MIN_TIMEOUT:
        return CAMERA_TOOL_MIN_TIMEOUT
    return timeout


def _mcp_session_tag(conn) -> str:
    """生成可检索的会话标识日志前缀"""
    device_id = getattr(conn, "device_id", None) or (
        conn.headers.get("device-id", "") if getattr(conn, "headers", None) else ""
    )
    session_id = getattr(conn, "session_id", "")
    return f"device_id={device_id} session_id={session_id}"


async def send_mcp_message(conn, payload: dict):
    """Helper to send MCP messages, encapsulating common logic."""
    if not conn.features.get("mcp"):
        raise DeviceToolError('mcp_not_ready')
    from core.utils.device_outbound import guarded_ws_send
    message = json.dumps({"type": "mcp", "payload": payload})
    ok = await guarded_ws_send(conn, message, command="mcp", msg_type="mcp")
    if not ok:
        raise DeviceToolError('connection_closed')


def connection_mcp(conn):
    client = getattr(conn, 'mcp_client', None)
    if not isinstance(client, MCPClient):
        client = MCPClient(device_id=getattr(conn, 'device_id', ''),
                           session_id=getattr(conn, 'session_id', ''))
        conn.mcp_client = client
    return client


def _is_retired_touch_message(payload):
    if not isinstance(payload, dict):
        return False
    if payload.get("type") == "touch_prompt":
        return True
    params = payload.get("params")
    if not isinstance(params, dict):
        return False
    arguments = params.get("arguments")
    if not isinstance(arguments, dict):
        return False
    inner = arguments.get("mcp_data")
    return isinstance(inner, dict) and inner.get("type") == "touch_prompt"


async def handle_mcp_message(conn, mcp_client: MCPClient, payload: dict):
    """处理MCP消息,包括初始化、工具列表和工具调用响应等"""
    logger.bind(tag=TAG).debug(
        f"处理MCP消息 payload_keys={list(payload.keys()) if isinstance(payload, dict) else type(payload).__name__}"
    )

    # Retired protocol: touch is handled locally and cannot trigger speech.
    if _is_retired_touch_message(payload):
        logger.bind(tag=TAG).debug('Legacy touch_prompt ignored')
        return

    if not isinstance(payload, dict):
        logger.bind(tag=TAG).error("MCP消息缺少payload字段或格式错误")
        return

    # 兼容 ESP-BOX-3 固件的包装格式：真正的 JSON-RPC 消息嵌在
    # payload.params.arguments.mcp_data 中（toolName=mcp_response_tool）。
    # 不解包会导致 tools/list、initialize、tools/call result 全部被静默丢弃，
    # 设备工具（camera.open 等）永远无法注册。
    if (
        "result" not in payload
        and "method" not in payload
        and "error" not in payload
    ):
        wrapped = (
            payload.get("params", {}).get("arguments", {}).get("mcp_data")
        )
        if isinstance(wrapped, dict) and (
            "result" in wrapped or "method" in wrapped or "error" in wrapped
        ):
            logger.bind(tag=TAG).info(
                f"[MCP解包] {_mcp_session_tag(conn)} 检测到 mcp_response_tool 包装格式，"
                f"解包 jsonrpc id={wrapped.get('id')}"
            )
            payload = wrapped

    if getattr(conn, 'mcp_client', mcp_client) is not mcp_client or mcp_client.closed:
        return
    if mcp_client.session_id and mcp_client.session_id != getattr(conn, 'session_id', ''):
        return
    method = payload.get('method')
    if method == 'notifications/tools/list_changed':
        await send_mcp_tools_list_request(conn)
        return
    if method:
        logger.bind(tag=TAG).debug(f'MCP notification method={method}')
        return
    msg_id = payload.get('id')
    if not isinstance(msg_id, int) or isinstance(msg_id, bool):
        return
    if 'error' in payload:
        error = payload['error'] if isinstance(payload['error'], dict) else {}
        if msg_id in mcp_client.call_results:
            data = error.get('data') or {}
            code = data.get('errorCode') if isinstance(data, dict) else None
            await mcp_client.reject_call_result(msg_id, DeviceToolError(code, error.get('message', '')))
        mcp_client.take_request(msg_id)
        return
    if 'result' not in payload:
        return
    result = payload['result']
    if msg_id in mcp_client.call_results:
        await mcp_client.resolve_call_result(msg_id, result)
        return
    kind, generation = mcp_client.take_request(msg_id)
    if kind == 'initialize' and isinstance(result, dict):
        caps = result.get('capabilities', {})
        mcp_client.capabilities = caps if isinstance(caps, dict) else {}
        from core.utils.person_directory_sync import report_capability
        asyncio.create_task(report_capability(conn, result))
        # Only this matched initialize receipt opens catalog discovery. This
        # preserves hello -> initialize -> receipt -> tools/list on the wire.
        await send_mcp_tools_list_request(conn)
    elif kind == 'tools/list' and generation == mcp_client.catalog_generation:
        if not isinstance(result, dict) or not isinstance(result.get('tools'), list):
            logger.bind(tag=TAG).warning('Invalid MCP tools/list response')
            return
        mcp_client.catalog_pages.extend(result['tools'])
        cursor = result.get('nextCursor')
        if cursor:
            if not isinstance(cursor, str) or cursor in mcp_client.catalog_cursors or len(mcp_client.catalog_cursors) >= 128:
                logger.bind(tag=TAG).warning('Invalid or repeated MCP catalog cursor')
                return
            mcp_client.catalog_cursors.add(cursor)
            await send_mcp_tools_list_continue_request(conn, cursor)
        elif await mcp_client.finish_catalog(generation):
            logger.bind(tag=TAG).info(f'[MCP catalog] {_mcp_session_tag(conn)} version={mcp_client.catalog_version} tools={len(mcp_client.tools)}')
            if getattr(conn, 'func_handler', None):
                conn.func_handler.tool_manager.refresh_tools()
                conn.func_handler.current_support_functions()
    else:
        logger.bind(tag=TAG).debug(f'[MCP stale_result] {_mcp_session_tag(conn)} id={msg_id}')


async def send_mcp_initialize_message(conn):
    """发送MCP初始化消息（含 vision + reminder_control + face_enrollment 能力）。"""
    from core.utils.vision_capability import build_vision_capabilities
    from core.utils.reminder_control_capability import build_reminder_control_capability
    from core.utils.face_enrollment_capability import (
        build_face_enrollment_capability_for_conn,
    )
    from core.utils.account_identity import resolve_face_account_id
    from core.utils.device_outbound import is_outbound_allowed

    capture_session = getattr(conn, "session_id", None) or ""
    device_id = ""
    if getattr(conn, "headers", None):
        device_id = conn.headers.get("device-id") or ""
    device_id = device_id or getattr(conn, "device_id", "") or ""

    account_id = resolve_face_account_id(conn=conn) or ""

    cap = build_vision_capabilities(
        conn.config,
        device_id=device_id,
        account_id=account_id,
        session_id=capture_session,
    )
    # fail-closed：不合规时不下发半成品 vision（尤其禁止无 identity_url）
    vision = cap.vision if cap.ok else {}
    if not cap.ok:
        logger.bind(tag=TAG).warning(
            f"MCP vision capabilities fail-closed: {cap.reason}"
        )

    rc = build_reminder_control_capability(conn.config)
    # 静态 enrollment + 可选动态身份字段（失败则两字段缺失，固件 unknown）
    fe = await build_face_enrollment_capability_for_conn(conn)

    # 网络/组装后再次确认仍为当前 session，避免旧连接写 capability
    if getattr(conn, "session_id", None) != capture_session or not is_outbound_allowed(
        conn
    ):
        logger.bind(tag=TAG).info(
            f"[MCP initialize] skip stale session device_id={device_id} "
            f"session_prefix={capture_session[:8]}"
        )
        return

    capabilities = {
        "roots": {"listChanged": True},
        "sampling": {},
        "vision": vision,
        "experimental": {
            "structuredErrors": True,
            "sessionBoundCatalog": True,
            "requestCancellation": False,
        },
    }
    # 只有公网 WSS 配置有效时才广告 reminder_control（不下发密钥）
    if rc.ok and rc.capability:
        capabilities["reminder_control"] = rc.capability
    else:
        logger.bind(tag=TAG).warning(
            f"MCP reminder_control fail-closed: {rc.reason}"
        )
    # 人脸采集：HTTPS + 配对鉴权配置齐全才下发（不下发 FACE_JWT）
    if fe.ok and fe.capability:
        capabilities["face_enrollment"] = fe.capability
        has_count = "enrolled_count" in (fe.capability or {})
        has_owner = "default_owner_person_id" in (fe.capability or {})
        logger.bind(tag=TAG).info(
            f"[MCP initialize] face_enrollment identity_fields "
            f"enrolled_count_set={1 if has_count else 0} "
            f"owner_set={1 if has_owner else 0} "
            f"enrolled_count={fe.capability.get('enrolled_count') if has_count else 'n/a'} "
            f"session_prefix={capture_session[:8]}"
        )
    else:
        logger.bind(tag=TAG).warning(
            f"MCP face_enrollment fail-closed: {fe.reason}"
        )

    payload = {
        "jsonrpc": "2.0",
        "id": await connection_mcp(conn).register_request("initialize"),
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": capabilities,
            "clientInfo": {
                "name": "XiaozhiClient",
                "version": "1.0.0",
            },
        },
    }
    logger.bind(tag=TAG).debug("发送MCP初始化消息")
    try:
        await send_mcp_message(conn, payload)
    except BaseException:
        connection_mcp(conn).take_request(payload['id'])
        raise


async def send_mcp_tools_list_request(conn):
    client = connection_mcp(conn)
    await client.begin_catalog()
    await send_mcp_tools_list_continue_request(conn, '')


async def send_mcp_tools_list_continue_request(conn, cursor: str):
    client = connection_mcp(conn)
    request_id = await client.register_request('tools/list', client.catalog_generation)
    payload = {'jsonrpc':'2.0', 'id':request_id, 'method':'tools/list'}
    if cursor:
        payload['params'] = {'cursor':cursor}
    try:
        await send_mcp_message(conn, payload)
    except BaseException:
        client.take_request(request_id)
        raise


async def _call_mcp_tool(
    conn, mcp_client: MCPClient, tool_name: str, args: str = "{}", timeout: int = 30
):
    """
    调用指定的工具，并等待响应

    tool_name 为 LLM 生成的原始函数名。此处会把它解析/校验为本会话
    tools/list 中的原始工具名；解析失败则拦截，绝不发给设备。
    """
    session_tag = _mcp_session_tag(conn)
    llm_raw_name = tool_name

    if not await mcp_client.is_ready():
        raise DeviceToolError('mcp_not_ready')

    # 工具名白名单校验 + 模糊恢复（如 selfcameratake_photo -> self.camera.take_photo）
    actual_name = mcp_client.resolve_tool_name(tool_name)
    if actual_name is None:
        raw_names = mcp_client.get_raw_tool_names()
        logger.bind(tag=TAG).warning(
            f"[MCP拦截] {session_tag} LLM原始函数名={llm_raw_name} 不在当前会话 tools/list 中，"
            f"已拦截，不发给设备。可用工具: {raw_names}"
        )
        raise ValueError(
            f"工具 {llm_raw_name} 不在当前设备的可用工具列表中，禁止调用。"
            f"请从以下工具中重新选择: {raw_names}"
        )

    # 双保险：即使绕过 unified_tool_manager，也不允许语音建档发到设备
    from core.utils.face_enrollment_guard import maybe_intercept_face_enrollment_tool

    face_blocked = maybe_intercept_face_enrollment_tool(actual_name)
    if face_blocked is not None:
        logger.bind(tag=TAG).info(
            f"[MCP拦截] {session_tag} 拒绝人脸语音建档/按名删除: {actual_name}"
        )
        return face_blocked.response or face_blocked.result or ""

    # 处理参数
    try:
        if isinstance(args, str):
            # 确保字符串是有效的JSON
            if not args.strip():
                arguments = {}
            else:
                try:
                    # 尝试直接解析
                    arguments = json.loads(args)
                except json.JSONDecodeError:
                    # 如果解析失败，尝试合并多个JSON对象
                    try:
                        # 使用正则表达式匹配所有JSON对象
                        json_objects = re.findall(r"\{[^{}]*\}", args)
                        if len(json_objects) > 1:
                            # 合并所有JSON对象
                            merged_dict = {}
                            for json_str in json_objects:
                                try:
                                    obj = json.loads(json_str)
                                    if isinstance(obj, dict):
                                        merged_dict.update(obj)
                                except json.JSONDecodeError:
                                    continue
                            if merged_dict:
                                arguments = merged_dict
                            else:
                                raise ValueError(f"无法解析任何有效的JSON对象: {args}")
                        else:
                            raise ValueError(f"参数JSON解析失败: {args}")
                    except Exception as e:
                        logger.bind(tag=TAG).error(
                            f"参数JSON解析失败: {str(e)}, 原始参数: {args}"
                        )
                        raise ValueError(f"参数JSON解析失败: {str(e)}")
        elif isinstance(args, dict):
            arguments = args
        else:
            raise ValueError(f"参数类型错误，期望字符串或字典，实际类型: {type(args)}")

        # 确保参数是字典类型
        if not isinstance(arguments, dict):
            raise ValueError(f"参数必须是字典类型，实际类型: {type(arguments)}")

    except Exception as e:
        if not isinstance(e, ValueError):
            raise ValueError(f"参数处理失败: {str(e)}")
        raise e

    tool_call_id = await mcp_client.get_next_id()
    result_future = asyncio.get_running_loop().create_future()
    await mcp_client.register_call_result_future(tool_call_id, result_future)

    # 摄像头类工具保证至少 10 秒超时，避免设备执行慢被误判失败
    timeout = effective_tool_timeout(actual_name, timeout)

    payload = {
        "jsonrpc": "2.0",
        "id": tool_call_id,
        "method": "tools/call",
        "params": {"name": actual_name, "arguments": arguments},
    }
    from core.utils.person_identity import current_turn
    actor=current_turn(conn)
    from core.utils.person_maintenance import service_control
    if actual_name in {"behavior.ack","habit.analyze","behavior.clear"} and not service_control.get():
        await mcp_client.cleanup_call_result(tool_call_id)
        raise DeviceToolError('service_control_required')
    if actor:
        payload["params"]["_meta"]={"person_turn":actor.payload()}
    versions=getattr(mcp_client,"capabilities",{}).get("experimental",{})
    if actual_name.startswith(("habit.","behavior.")) and versions.get("personBehavior",0)<2:
        await mcp_client.cleanup_call_result(tool_call_id)
        raise DeviceToolError('firmware_person_behavior_unsupported')
    if actual_name in {"note.add","habit.learn"} and int(arguments.get("repeat_days",0) or 0) not in (0,127) and versions.get("weeklySchedule",0)<2:
        await mcp_client.cleanup_call_result(tool_call_id)
        raise DeviceToolError('firmware_weekly_schedule_unsupported')
    if actual_name.startswith(("habit.","behavior.")) and (actor is None or not actor.eligible):
        await mcp_client.cleanup_call_result(tool_call_id)
        raise DeviceToolError('identity_unconfirmed')
    if actual_name=="behavior.log":
        arguments["raw"]=getattr(conn,"_person_inputs",{}).get(actor.turn_id,"")
        results=getattr(conn,"_person_tool_results",{}).get(actor.turn_id,[])
        arguments["outcome"]="executed" if any(item.get("success") for item in results) else ("failed" if results else "conversation")

    # 工具调用执行期间视为活跃，防止空闲超时逻辑在等待 result 时关闭 WebSocket
    conn.last_activity_time = time.time() * 1000

    logger.bind(tag=TAG).info(f'[MCP call] {session_tag} id={tool_call_id} name={actual_name} timeout={timeout}')
    try:
        await send_mcp_message(conn, payload)
        raw_result = await asyncio.wait_for(result_future, timeout=timeout)
        if getattr(mcp_client, 'session_id', '') and getattr(mcp_client, 'session_id', '') != getattr(conn, 'session_id', ''):
            raise DeviceToolError('connection_closed')
        conn.last_activity_time = time.time() * 1000
        result=unwrap_tool_result(raw_result)
        if actor and actor.eligible and not actual_name.startswith(("habit.","behavior.")):
            if not hasattr(conn,"_person_tool_results"):conn._person_tool_results={}
            history=conn._person_tool_results.setdefault(actor.turn_id,[])
            history.append({"tool":actual_name,"result":result,"success":result is not False and not (isinstance(result,dict) and result.get("success") is False)})
            if len(history)>16:del history[:-16]
            if len(conn._person_tool_results)>128:conn._person_tool_results.pop(next(iter(conn._person_tool_results)))
        if actual_name=="behavior.log" and actor and actor.eligible:
            try:
                record=json.loads(result) if isinstance(result,str) else result
                if isinstance(record,dict) and record.get("person")==actor.person_id and record.get("turn")==actor.turn_id:
                    from core.utils.person_material_outbox import material_outbox
                    material_outbox.enqueue(actor,"behavior",json.dumps(record,ensure_ascii=False),record["event"])
                    asyncio.create_task(material_outbox.pump(conn))
            except (ValueError,KeyError,TypeError):
                pass
        if actual_name=="habit.analyze" and actor and actor.eligible:
            from core.utils.habit_router import route_habit_analysis
            import threading
            threading.Thread(target=route_habit_analysis,args=(conn,result,actor),daemon=True).start()
        return result
    except asyncio.TimeoutError as exc:
        # Cancellation is negotiated; older firmware may still finish the operation.
        experimental = getattr(mcp_client, 'capabilities', {}).get('experimental', {})
        if isinstance(experimental, dict) and experimental.get('requestCancellation') is True:
            try:
                await send_mcp_message(conn, {'jsonrpc':'2.0', 'method':'notifications/cancelled',
                    'params':{'requestId':tool_call_id, 'reason':'request_timeout'}})
            except Exception:
                pass
        logger.bind(tag=TAG).warning(f'[MCP timeout] {session_tag} id={tool_call_id} cancel_supported={bool(isinstance(experimental, dict) and experimental.get("requestCancellation") is True)}')
        raise TimeoutError('设备请求等待超时，任务结果未确认。') from exc
    finally:
        await mcp_client.cleanup_call_result(tool_call_id)


async def call_mcp_tool(conn, mcp_client, tool_name, args='{}', timeout=30):
    from core.providers.tools.retired_tools import is_retired_tool
    if is_retired_tool(tool_name):
        raise ValueError("这项维护工具已停用，禁止下发。")
    from core.utils.face_enrollment_start_intent import is_face_enroll_start_tool
    from core.utils.face_enrollment_operation import start_operation, cancelled_operation
    if is_face_enroll_start_tool(tool_name):
        return await start_operation(conn,mcp_client,_call_mcp_tool,tool_name,args,timeout)
    result = await _call_mcp_tool(conn,mcp_client,tool_name,args,timeout)
    if tool_name.replace('_','.') in ('camera.face.enroll.cancel','self.camera.face.enroll.cancel'):
        cancelled_operation(conn)
    return result
