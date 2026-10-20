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


async def handle_mcp_message(conn, mcp_client: MCPClient, payload: dict):
    """处理MCP消息,包括初始化、工具列表和工具调用响应等"""
    logger.bind(tag=TAG).debug(
        f"处理MCP消息 payload_keys={list(payload.keys()) if isinstance(payload, dict) else type(payload).__name__}"
    )

    # 1. 拦截物理触摸事件（touch_prompt），并设置延时触发 LLM + 情绪疲劳计数
    try:
        # 优先将其视为扁平结构，如果 type 不是 touch_prompt，再去深层查找兼容老结构
        mcp_data = payload if isinstance(payload, dict) else {}
        if mcp_data.get("type") != "touch_prompt":
            mcp_data = payload.get("params", {}).get("arguments", {}).get("mcp_data", {})

        if isinstance(mcp_data, dict) and mcp_data.get("type") == "touch_prompt":
            source = mcp_data.get("source", "head_tap")
            # 原始硬件提示词如果后面需要可再使用
            _raw_prompt = mcp_data.get("prompt")

            # 初始化触摸计数相关字段
            now = time.time()
            last_touch_time = getattr(conn, "last_touch_time", None)
            touch_count = getattr(conn, "touch_count", 0)

            # 计算触摸次数：超过 60 秒视为重新开始
            if last_touch_time is None or now - last_touch_time > 60:
                touch_count = 0
            touch_count += 1

            conn.touch_count = touch_count
            conn.last_touch_time = now

            # 1) 获取用户昵称（称呼），默认为“用户”
            nickname = (
                conn.config.get("user_nickname", "用户")
                if hasattr(conn, "config") and isinstance(conn.config, dict)
                else "用户"
            )

            # 2) 将英文 source 翻译为中文身体部位
            part_map = {
                "head_tap": "头",
                "face_swipe": "脸",
                "circle": "面前（转圈圈）",
            }
            body_part = part_map.get(source, "身体")

            # 3) 生成分级动态提示词（系统客观旁白，与大模型人格兼容）
            if conn.touch_count <= 2:
                dynamic_prompt = (
                    f"[系统动作事件：{nickname}刚刚轻轻摸了你的{body_part}。"
                    "请严格保持你当前的角色设定，用符合你性格的语气给出简短的感官反馈，"
                    "不要解释，10字以内。]"
                )
            elif conn.touch_count <= 4:
                dynamic_prompt = (
                    f"[系统动作事件：{nickname}在短时间内连续摸了你{conn.touch_count}次{body_part}。"
                    "请严格保持你当前的角色设定，表现出疑惑或轻微的无奈，"
                    "给出一句简短的回应，不要解释，10字以内。]"
                )
            else:
                dynamic_prompt = (
                    f"[系统动作事件：{nickname}一直在疯狂碰你的{body_part}！你现在感到非常不适。"
                    "请严格保持你当前的角色设定，用符合你性格的语气强烈抗议并要求对方停手，"
                    "不要解释，10字以内！]"
                )

            # 将动态生成的提示词暂存到连接对象中
            prompt = dynamic_prompt
            conn.pending_touch_prompt = dynamic_prompt
            conn.logger.bind(tag=TAG).info(
                f"拦截到物理触摸事件: {source}, 次数={touch_count}"
            )

            # 结合触摸动作与疲劳度，计算瞬时表情反馈
            if touch_count >= 5:
                emotion_str = "angry"
            elif touch_count >= 3:
                emotion_str = "confused"
            else:
                if source == "head_tap":
                    emotion_str = "happy"
                elif source == "face_swipe":
                    emotion_str = "angry"
                elif source == "circle":
                    emotion_str = "dizzy"
                else:
                    emotion_str = "happy"

            # 立即下发表情控制帧（毫秒级视觉反馈）；经 current-guarded 路径
            try:
                from core.utils.device_outbound import guarded_ws_send, track_outbound_task

                emotion_payload = json.dumps({"type": "llm", "emotion": emotion_str})
                track_outbound_task(
                    conn,
                    asyncio.create_task(
                        guarded_ws_send(
                            conn,
                            emotion_payload,
                            command="llm_emotion",
                            msg_type="llm",
                        )
                    ),
                )
                conn.logger.bind(tag=TAG).info(f"已下发瞬时表情反馈: {emotion_str}")
            except Exception as e:
                conn.logger.bind(tag=TAG).error(f"下发表情失败: {e}")

            # 启动一个异步任务：如果 1.5 秒内 VAD 没有录到真实声音，主动触发 LLM
            async def trigger_touch_chat():
                await asyncio.sleep(1.5)
                # 如果 1.5 秒后 pending_touch_prompt 还在，说明用户真没说话
                if getattr(conn, "pending_touch_prompt", None) == prompt:
                    conn.logger.bind(tag=TAG).info("纯触摸触发（无有效语音），主动调用 LLM")
                    conn.pending_touch_prompt = None
                    # 提交到线程池执行 chat
                    if hasattr(conn, "executor"):
                        conn.executor.submit(conn.chat, f"[{prompt}]")

            asyncio.create_task(trigger_touch_chat())
            return  # 拦截完毕，直接返回，不走后续普通的 MCP 工具注册逻辑
    except Exception as e:
        conn.logger.bind(tag=TAG).error(f"解析 touch_prompt 失败: {e}")

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
