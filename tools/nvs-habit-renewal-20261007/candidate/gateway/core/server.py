# 文件路径: core/server.py
import asyncio
import copy
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.requests import ClientDisconnect

from core.config import config
from core.protocol import mcp_sse_pack

logger = logging.getLogger(__name__)

_PC_REMOVED_MSG = "电脑控制功能已下架，无法调用该工具。"


def _is_hidden_tool(tool_info: dict) -> bool:
    """判断工具是否被标记为隐藏。"""
    func = tool_info.get("func") if isinstance(tool_info, dict) else None
    meta = getattr(func, "__tool_meta__", None) if func else None
    return bool(meta and meta.get("hidden"))


def _is_retired_pc_tool(name: str | None) -> bool:
    return bool(name) and str(name).startswith("pc_")


def _pc_removed_result():
    return {"content": [{"type": "text", "text": _PC_REMOVED_MSG}], "isError": True}


def _resolve_control_session_id(request: Request, arguments: dict | None = None) -> str:
    """
    统一解析“主控设备/会话设备”ID。
    优先顺序：header/query 的 device_id > controller_device_id > X-Device-Id > unknown。
    """
    args = arguments or {}
    return (
        request.headers.get("device_id")
        or request.query_params.get("device_id")
        or args.get("device_id")
        or args.get("controller_device_id")
        or request.headers.get("X-Device-Id")
        or request.query_params.get("controller_device_id")
        or "unknown"
    )


def _resolve_target_device_id(arguments: dict | None = None, controller_id: str | None = None) -> str | None:
    """解析动作目标设备 ID：仅从调用参数读取。"""
    args = arguments or {}
    return args.get("target_device_id")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时创建提醒调度任务，关闭时可选清理。"""
    from tools.reminder_tool import scheduler_loop
    from tools.habit_tool import habit_scheduler_loop
    asyncio.create_task(scheduler_loop())
    asyncio.create_task(habit_scheduler_loop())
    yield
    #  shutdown: 可在此添加清理逻辑


# 初始化 FastAPI（使用 lifespan 替代已弃用的 on_event）
app = FastAPI(title="Xiaozhi Unified Gateway v2.1", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def _schema_with_hidden_config(tool_name: str, schema: dict) -> dict:
    """
    根据 internal_config 从 schema 中移除“已在网关配置”的参数，前端不再展示这些输入框。
    """
    filled = config.internal_config.get(tool_name) or {}
    if not filled:
        return schema
    schema = copy.deepcopy(schema)
    props = schema.get("properties") or {}
    for key in list(props.keys()):
        if key in filled and filled[key]:
            props.pop(key, None)
    schema["properties"] = props
    required = schema.get("required")
    if isinstance(required, list):
        schema["required"] = [r for r in required if r not in filled or not filled.get(r)]
    return schema


def _merge_internal_args(tool_name: str, arguments: dict) -> dict:
    """
    调用时合并参数：用户传入的优先，未传的配置项从 internal_config 补全。
    """
    args = dict(arguments or {})
    tool_info = config.mcp_tools.get(tool_name)
    if not tool_info:
        return args
    schema = tool_info.get("schema") or {}
    props = schema.get("properties") or {}
    internal = config.internal_config.get(tool_name) or {}
    for param_name in props:
        if param_name not in args and param_name in internal and internal[param_name]:
            args[param_name] = internal[param_name]
    return args


# ---------- 工具发现接口（供 Java 管理台 /list_tools 同步插件列表） ----------
def _build_list_tools_payload():
    """返回标准 JSON 数组；title 从各工具函数的 __tool_meta__ 动态读取，无则回退工具名；hidden 为 True 的工具不返回。"""
    result = []
    for name, info in config.mcp_tools.items():
        if name == "mcp_response_tool" or _is_retired_pc_tool(name):
            continue
        func = info.get("func")
        meta = getattr(func, "__tool_meta__", None) if func else None
        if meta and meta.get("hidden"):
            continue
        title = (meta.get("title") if meta else None) or name
        filtered_schema = _schema_with_hidden_config(name, info["schema"])
        result.append({
            "name": name,
            "title": title,
            "description": info["desc"],
            "input_schema": filtered_schema,
        })
    return result

# GET /list_tools 与 /list-tools 在 main.py 中注册，确保先加载 tools 再暴露接口

@app.post("/streamable-http")
async def gateway_entry(request: Request):
    try:
        # A. 鉴权
        if request.headers.get("Authorization") != f"Bearer {config.auth_token}":
            return JSONResponse(status_code=401, content={"err": "Unauthorized"})

        # B. 提取 Body
        try:
            raw_body = await request.body()
        except ClientDisconnect:
            return JSONResponse(status_code=499, content={"err": "Closed"})
        
        if not raw_body: 
            return JSONResponse(status_code=200, content={"ok": True})
        
        # 暴力解码，防止乱码
        text = raw_body.decode("utf-8", errors="ignore").strip().strip('\x00')
        start, end = text.find('{'), text.rfind('}')
        
        if start == -1 or end == -1:
            return JSONResponse(status_code=200, content={"status": "keepalive"})

        data = json.loads(text[start:end+1])
        mode = request.headers.get("X-Xiaozhi-Mode", "Standard")
        is_hardware = (mode == "Hardware")

        # C. 协议分发逻辑
        # 1. 标准 MCP 消息
        if "method" in data:
            method = data["method"]
            rid = data.get("id")

            if method == "initialize":
                print(f"🤝 握手初始化 (ID: {rid})")
                res = {
                    "jsonrpc": "2.0", "id": rid,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "Xiaozhi-v2.1", "version": "2.1.0"}
                    }
                }
                return mcp_sse_pack(res, heartbeat=(not is_hardware))

            elif method == "tools/list":
                control_session_id = _resolve_control_session_id(request)
                t_list = []
                for n, i in config.mcp_tools.items():
                    if n == "mcp_response_tool" or _is_hidden_tool(i) or _is_retired_pc_tool(n):
                        continue
                    t_list.append({
                        "name": n,
                        "description": i["desc"],
                        "inputSchema": _schema_with_hidden_config(n, i["schema"]),
                    })
                logger.info(
                    "📋 tools/list control_session_id=%s tool_count=%s",
                    control_session_id,
                    len(t_list),
                )
                return mcp_sse_pack({"jsonrpc": "2.0", "id": rid, "result": {"tools": t_list}})

            elif method == "tools/call":
                p = data.get("params", {}) or {}
                target_name = p.get("name")
                args = p.get("arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args) if args.strip() else {}
                    except json.JSONDecodeError:
                        args = {}
                if not isinstance(args, dict):
                    args = {}

                control_session_id = _resolve_control_session_id(request, args)
                target_device_id = _resolve_target_device_id(args, controller_id=control_session_id)

                print(f"🚀 执行工具: {target_name}")
                print(f"DEBUG: 准备调用 {target_name}，传入参数: {args}")

                if not target_name:
                    err = {"content": [{"type": "text", "text": "工具调用缺少 name 参数"}], "isError": True}
                    return mcp_sse_pack({"jsonrpc": "2.0", "id": rid, "result": err})

                logger.info(
                    "🚀 tools/call name=%s control_session_id=%s target_device_id=%s",
                    target_name,
                    control_session_id,
                    target_device_id,
                )
                if _is_retired_pc_tool(target_name):
                    return mcp_sse_pack({"jsonrpc": "2.0", "id": rid, "result": _pc_removed_result()})

                if target_name not in config.mcp_tools:
                    available = list(config.mcp_tools.keys())
                    print(f"DEBUG: 工具 [{target_name}] 未找到。已注册工具: {available}")
                    err = {"content": [{"type": "text", "text": f"工具 {target_name} 不存在，已注册: {available}"}], "isError": True}
                    return mcp_sse_pack({"jsonrpc": "2.0", "id": rid, "result": err})

                # ── PreToolUse 规则引擎拦截 ──
                try:
                    from hooks.rule_engine import evaluate_rules
                    decision = evaluate_rules(target_name, args)
                    if decision["action"] == "block":
                        block_msg = (
                            f"[安全规则拦截] {decision['message']}"
                            f"\n规则: {decision['rule_name']}"
                        )
                        logger.warning(f"🛡️ 规则拦截: {target_name} → {decision['rule_name']}")
                        err = {"content": [{"type": "text", "text": block_msg}], "isError": True}
                        return mcp_sse_pack({"jsonrpc": "2.0", "id": rid, "result": err})
                    elif decision["action"] == "warn":
                        logger.warning(f"⚠️ 规则警告: {target_name} → {decision['message']}")
                        # warn 不阻断，继续执行
                except Exception as e:
                    logger.error(f"规则引擎调用异常，放行: {e}")
                    
                # 防注入防火墙：拦截高危操作
                tool_info = config.mcp_tools[target_name]
                if tool_info.get("danger_level") == "High":
                    print(f"⚠️ [安全警报] 检测到高危操作 '{target_name}'，等待用户本地确认...")
                    pass

                try:
                    from core.executor import execute_tool
                    call_args = dict(args)
                    # 所有工具统一注入上下文参数（use_skill 等组合工具也能透传）
                    if target_device_id and "target_device_id" not in call_args:
                        call_args["target_device_id"] = target_device_id
                    if control_session_id and "controller_device_id" not in call_args:
                        call_args["controller_device_id"] = control_session_id
                    ans = await execute_tool(target_name, **call_args)

                    # ── PostToolUse 安全审计：检查返回内容是否泄露敏感信息 ──
                    try:
                        from hooks.post_check import audit_tool_result, inject_system_warning
                        warning = audit_tool_result(target_name, ans)
                        if warning:
                            ans = inject_system_warning(ans, warning)
                    except Exception as audit_err:
                        logger.error(f"PostToolUse 审计异常，跳过: {audit_err}")

                    if isinstance(ans, dict) and "content" in ans:
                        res = dict(ans)
                        res.setdefault("isError", False)
                        return mcp_sse_pack({"jsonrpc": "2.0", "id": rid, "result": res})
                    return mcp_sse_pack({"jsonrpc": "2.0", "id": rid, "result": {"content": [{"type": "text", "text": str(ans)}], "isError": False}})
                except TypeError as e:
                    print(f"DEBUG: 工具 {target_name} 参数不匹配 (TypeError): {e}")
                    err = {"content": [{"type": "text", "text": f"工具调用参数错误: {e}"}], "isError": True}
                    return mcp_sse_pack({"jsonrpc": "2.0", "id": rid, "result": err})

            else:
                return JSONResponse({"jsonrpc": "2.0", "result": "ok"})

        # 2. 硬件专属响应 (toolName 模式)，统一经 executor 分发
        # 安全检查与 tools/call 路径保持一致
        params = data.get("params", {}) or {}
        if params.get("toolName"):
            t_name = params["toolName"]
            t_args = params.get("arguments") or {}
            rid_hw = data.get("id", "resp")

            if isinstance(t_args, str):
                try:
                    t_args = json.loads(t_args) if t_args.strip() else {}
                except json.JSONDecodeError:
                    t_args = {}
            if not isinstance(t_args, dict):
                t_args = {}

            control_session_id = _resolve_control_session_id(request, t_args)
            target_device_id = _resolve_target_device_id(t_args)

            if _is_retired_pc_tool(t_name):
                return mcp_sse_pack({"jsonrpc": "2.0", "id": rid_hw, "result": _pc_removed_result()})

            if t_name not in config.mcp_tools:
                return mcp_sse_pack({"jsonrpc": "2.0", "id": rid_hw, "result": {"content": [{"type": "text", "text": f"工具 {t_name} 不存在"}], "isError": True}})

            logger.info(
                "🧰 hardware toolName=%s control_session_id=%s target_device_id=%s",
                t_name,
                control_session_id,
                target_device_id,
            )

            # ── PreToolUse 规则引擎 ──
            try:
                from hooks.rule_engine import evaluate_rules
                decision = evaluate_rules(t_name, t_args)
                if decision["action"] == "block":
                    block_msg = f"[安全规则拦截] {decision['message']}"
                    return mcp_sse_pack({"jsonrpc": "2.0", "id": rid_hw, "result": {"content": [{"type": "text", "text": block_msg}], "isError": True}})
            except Exception:
                pass

            # ── 执行工具 ──
            from core.executor import execute_tool
            call_args = dict(t_args)
            ans = await execute_tool(t_name, **call_args)

            # ── PostToolUse 审计 ──
            try:
                from hooks.post_check import audit_tool_result, inject_system_warning
                warning = audit_tool_result(t_name, ans)
                if warning:
                    ans = inject_system_warning(ans, warning)
            except Exception:
                pass

            if isinstance(ans, dict) and "content" in ans:
                res = dict(ans)
                res.setdefault("isError", False)
                return mcp_sse_pack({"jsonrpc": "2.0", "id": rid_hw, "result": res})
            return mcp_sse_pack({"jsonrpc": "2.0", "id": rid_hw, "result": {"content": [{"type": "text", "text": str(ans)}], "isError": False}})

        return JSONResponse({"jsonrpc": "2.0", "result": "ignored"})

    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"🔥 网关捕获异常: {e}")
        return JSONResponse(status_code=500, content={"err": str(e)})