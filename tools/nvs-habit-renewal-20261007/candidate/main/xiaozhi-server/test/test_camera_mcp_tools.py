"""ESP-BOX-3 摄像头 MCP 工具调用与 WebSocket 会话处理回归测试

运行方式:
    cd main/xiaozhi-server
    python test/test_camera_mcp_tools.py

覆盖验收项:
1. tools/list 含 camera.open 时，LLM 函数名（sanitized 或原始名）必须下发
   tools/call params.name == camera.open（严格等于 tools/list 中的原始名）
2. 错误名称 selfcameratake_photo 必须在服务端被拦截，不能发给设备
3. camera 类工具执行超时至少 10 秒
4. camera.open 调用挂起期间，服务端 close() 必须延迟，等待 MCP result
5. "关闭摄像头" 对应 camera_close -> camera.close
6. tools/list 未就绪时不得调用任何摄像头工具
7. 系统提示词包含摄像头意图强制路由规则
8. tools/list 缓存按 device_id/firmware/session_id 隔离
"""

import os
import sys
import json
import time
import asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.providers.tools.device_mcp.mcp_client import MCPClient
from core.providers.tools.device_mcp.mcp_handler import (
    call_mcp_tool,
    handle_mcp_message,
    effective_tool_timeout,
    CAMERA_TOOL_MIN_TIMEOUT,
)

PASS = []
FAIL = []


def check(name, cond, detail=""):
    if cond:
        PASS.append(name)
        print(f"  [PASS] {name}")
    else:
        FAIL.append(name)
        print(f"  [FAIL] {name} {detail}")


class FakeWebSocket:
    def __init__(self):
        self.sent_messages = []
        self.closed = False

    async def send(self, message):
        self.sent_messages.append(message)

    async def close(self):
        self.closed = True


class FakeLogger:
    def bind(self, **kwargs):
        return self

    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass

    def debug(self, *a, **k):
        pass


class FakeConn:
    def __init__(self, mcp_client):
        self.websocket = FakeWebSocket()
        self.mcp_client = mcp_client
        self.features = {"mcp": True}
        self.device_id = "esp-box-3-test"
        self.session_id = "session-test-001"
        self.headers = {"device-id": "esp-box-3-test"}
        self.logger = FakeLogger()
        self.last_activity_time = 0.0


DEVICE_TOOLS = [
    "camera.open",
    "camera.close",
    "self.camera.take_photo",
    "camera.face.register",
    "camera.face.delete",
]


async def make_ready_client():
    client = MCPClient(
        device_id="esp-box-3-test", firmware_version="1.0.0", session_id="session-test-001"
    )
    for name in DEVICE_TOOLS:
        await client.add_tool(
            {"name": name, "description": f"tool {name}", "inputSchema": {}}
        )
    await client.set_ready(True)
    return client


def sent_tool_call_names(ws):
    """提取 FakeWebSocket 上所有 tools/call 的 params.name"""
    names = []
    for m in ws.sent_messages:
        data = json.loads(m)
        payload = data.get("payload", {})
        if payload.get("method") == "tools/call":
            names.append(payload["params"]["name"])
    return names


async def call_and_autoresolve(conn, client, llm_name, timeout=30):
    """调用 call_mcp_tool，同时模拟设备返回 result"""

    async def auto_resolve():
        for _ in range(50):
            await asyncio.sleep(0.02)
            if client.call_results:
                call_id = next(iter(client.call_results))
                await client.resolve_call_result(
                    call_id, {"content": [{"text": "ok"}]}
                )
                return

    resolver = asyncio.create_task(auto_resolve())
    try:
        result = await call_mcp_tool(conn, client, llm_name, "{}", timeout=timeout)
        return result, None
    except Exception as e:
        return None, e
    finally:
        resolver.cancel()


async def test_1_open_camera_dispatches_camera_open():
    print("\n[1] LLM 函数名 camera_open / camera.open -> 设备收到 params.name=camera.open")
    for llm_name in ["camera_open", "camera.open"]:
        client = await make_ready_client()
        conn = FakeConn(client)
        result, err = await call_and_autoresolve(conn, client, llm_name)
        names = sent_tool_call_names(conn.websocket)
        check(
            f"'{llm_name}' 下发 params.name == 'camera.open'",
            err is None and names == ["camera.open"],
            f"err={err} names={names}",
        )
        check(
            f"'{llm_name}' 的 params.name 严格存在于 tools/list 原始名中",
            all(n in DEVICE_TOOLS for n in names),
            f"names={names}",
        )


async def test_2_bad_name_intercepted():
    print("\n[2] 错误名称必须被拦截，不能发给设备")
    for bad_name in ["selfcameratake_photo", "self.camera.open", "cameraopen", "not_a_tool"]:
        client = await make_ready_client()
        conn = FakeConn(client)
        result, err = await call_and_autoresolve(conn, client, bad_name)
        names = sent_tool_call_names(conn.websocket)
        check(
            f"'{bad_name}' 被拦截（抛 ValueError 且未发送 tools/call）",
            isinstance(err, ValueError) and names == [],
            f"err={err!r} names={names}",
        )
        if isinstance(err, ValueError):
            check(
                f"'{bad_name}' 拦截提示包含可用工具列表（供LLM重新选择）",
                "camera.open" in str(err),
                f"msg={err}",
            )


async def test_3_take_photo_valid_names():
    print("\n[3] 拍照工具：只有精确名 self_camera_take_photo / self.camera.take_photo 可调用")
    for llm_name in ["self_camera_take_photo", "self.camera.take_photo"]:
        client = await make_ready_client()
        conn = FakeConn(client)
        result, err = await call_and_autoresolve(conn, client, llm_name)
        names = sent_tool_call_names(conn.websocket)
        check(
            f"'{llm_name}' 下发 params.name == 'self.camera.take_photo'",
            err is None and names == ["self.camera.take_photo"],
            f"err={err} names={names}",
        )


async def test_4_close_camera():
    print("\n[4] 关闭摄像头 -> camera.close")
    client = await make_ready_client()
    conn = FakeConn(client)
    result, err = await call_and_autoresolve(conn, client, "camera_close")
    names = sent_tool_call_names(conn.websocket)
    check(
        "'camera_close' 下发 params.name == 'camera.close'",
        err is None and names == ["camera.close"],
        f"err={err} names={names}",
    )


def test_5_camera_timeout():
    print("\n[5] camera 类工具超时至少 10 秒")
    check(
        "camera.open timeout 1s -> 提升到 >=10s",
        effective_tool_timeout("camera.open", 1) >= CAMERA_TOOL_MIN_TIMEOUT,
    )
    check(
        "camera.close timeout 5s -> 提升到 >=10s",
        effective_tool_timeout("camera.close", 5) >= CAMERA_TOOL_MIN_TIMEOUT,
    )
    check(
        "camera.open timeout 30s 保持 30s",
        effective_tool_timeout("camera.open", 30) == 30,
    )
    check(
        "非摄像头工具 timeout 不受影响",
        effective_tool_timeout("get_weather", 5) == 5,
    )


async def test_6_not_ready_blocks_camera_calls():
    print("\n[6] tools/list 未就绪时不得调用任何摄像头工具")
    client = MCPClient(
        device_id="esp-box-3-test", firmware_version="1.0.0", session_id="session-x"
    )
    # 未 add_tool、未 set_ready
    conn = FakeConn(client)
    result, err = await call_and_autoresolve(conn, client, "camera_open")
    names = sent_tool_call_names(conn.websocket)
    check(
        "未取得 tools/list 时调用被拒绝且不发送 tools/call",
        isinstance(err, RuntimeError) and names == [],
        f"err={err!r} names={names}",
    )


async def test_7_close_deferred_during_pending_call():
    print("\n[7] MCP 调用挂起期间，服务端 close() 延迟等待 result；TTS 可经原连接发送")
    from core.connection import ConnectionHandler

    client = await make_ready_client()

    class CloseStub:
        device_id = "esp-box-3-test"
        session_id = "session-test-001"
        timeout_task = None
        func_handler = None
        websocket = FakeWebSocket()
        tts = None
        executor = None
        logger = FakeLogger()
        stop_event = asyncio.Event()
        mcp_client = client

        def clear_queues(self):
            pass

        # 绑定被测方法
        has_pending_mcp_calls = ConnectionHandler.has_pending_mcp_calls
        close = ConnectionHandler.close

    stub = CloseStub()

    # 挂起一个未返回的 MCP 调用
    call_id = await client.get_next_id()
    fut = asyncio.Future()
    await client.register_call_result_future(call_id, fut)

    check("挂起调用时 has_pending_mcp_calls == True", stub.has_pending_mcp_calls())

    async def resolve_later():
        await asyncio.sleep(1.2)
        # 模拟设备通过原连接先收到 TTS，再返回 result
        await stub.websocket.send(json.dumps({"type": "tts", "state": "sentence_start"}))
        await client.resolve_call_result(call_id, {"content": [{"text": "opened"}]})

    resolver = asyncio.create_task(resolve_later())
    t0 = time.monotonic()
    await stub.close()
    elapsed = time.monotonic() - t0
    await resolver

    check(
        f"close() 等待 result 返回后才关闭（等待 {elapsed:.2f}s >= 1.2s）",
        elapsed >= 1.2,
        f"elapsed={elapsed:.2f}",
    )
    check(
        "等待期间 TTS 消息仍可通过原连接发送",
        any("tts" in m for m in stub.websocket.sent_messages),
    )
    check("等待结束后连接才被清理关闭", stub.websocket.closed)


def test_8_prompt_contains_camera_routing():
    print("\n[8] 系统提示词包含摄像头意图强制路由规则")
    from core.connection import ConnectionHandler

    class Dialogue:
        def __init__(self):
            self.system_message = None

        def update_system_message(self, prompt):
            self.system_message = prompt

    class PromptStub:
        dialogue = Dialogue()
        change_system_prompt = ConnectionHandler.change_system_prompt

    stub = PromptStub()
    stub.change_system_prompt("基础人设提示词")
    p = stub.prompt

    check("提示词包含 打开摄像头 -> camera_open 规则", "打开摄像头" in p and "camera_open" in p)
    check("提示词包含 关闭摄像头 -> camera_close 规则", "关闭摄像头" in p and "camera_close" in p)
    check(
        "提示词包含 拍照 -> self_camera_take_photo 规则",
        "拍照" in p and "self_camera_take_photo" in p,
    )
    check(
        "提示词禁止 打开摄像头 调用 take_photo",
        "绝对不能调用 self_camera_take_photo" in p,
    )
    check("提示词禁止发明 selfcameratake_photo", "selfcameratake_photo" in p and "禁止" in p)


async def test_9_session_cache_isolation():
    print("\n[9] tools/list 缓存按 device_id/firmware/session_id 隔离")
    c1 = MCPClient(device_id="dev-A", firmware_version="1.0", session_id="s1")
    c2 = MCPClient(device_id="dev-A", firmware_version="1.0", session_id="s2")
    await c1.add_tool({"name": "camera.open", "description": "x", "inputSchema": {}})
    check("不同会话 cache_key 不同", c1.cache_key != c2.cache_key)
    check("会话1工具不泄漏到会话2", c2.get_raw_tool_names() == [])
    check("会话1工具列表正确", c1.get_raw_tool_names() == ["camera.open"])


async def test_10_wrapped_mcp_response_unwrapped():
    print("\n[10] ESP-BOX-3 包装格式（mcp_response_tool/mcp_data）必须被解包处理")
    client = MCPClient(
        device_id="esp-box-3-test", firmware_version="2.0.5", session_id="session-wrap"
    )
    conn = FakeConn(client)

    # 真实固件日志中的包装格式：jsonrpc 嵌在 payload.params.arguments.mcp_data
    wrapped_tools_list = {
        "params": {
            "toolName": "mcp_response_tool",
            "arguments": {
                "mcp_data": {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "result": {
                        "tools": [
                            {
                                "name": "camera.open",
                                "description": "打开摄像头实时预览",
                                "inputSchema": {"type": "object", "properties": {}},
                            }
                        ]
                    },
                }
            },
        }
    }
    await handle_mcp_message(conn, client, wrapped_tools_list)

    check(
        "包装格式的 tools/list 被解包，camera.open 注册成功",
        client.get_raw_tool_names() == ["camera.open"],
        f"raw_names={client.get_raw_tool_names()}",
    )
    check("解包后 MCP 客户端就绪", await client.is_ready())

    # 包装格式的 tools/call result 也必须能解包并 resolve 挂起的调用
    call_id = await client.get_next_id()
    fut = asyncio.Future()
    await client.register_call_result_future(call_id, fut)
    wrapped_call_result = {
        "params": {
            "toolName": "mcp_response_tool",
            "arguments": {
                "mcp_data": {
                    "jsonrpc": "2.0",
                    "id": call_id,
                    "result": {"content": [{"text": "camera opened"}]},
                }
            },
        }
    }
    await handle_mcp_message(conn, client, wrapped_call_result)
    check(
        "包装格式的 tools/call result 被解包并 resolve",
        fut.done() and fut.result() == {"content": [{"text": "camera opened"}]},
        f"done={fut.done()}",
    )

    # 未包装的标准格式仍然兼容
    client2 = MCPClient(device_id="dev-std", firmware_version="1.0", session_id="s-std")
    conn2 = FakeConn(client2)
    await handle_mcp_message(
        conn2,
        client2,
        {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {
                "tools": [
                    {"name": "camera.close", "description": "x", "inputSchema": {}}
                ]
            },
        },
    )
    check(
        "标准（未包装）tools/list 仍正常解析",
        client2.get_raw_tool_names() == ["camera.close"],
        f"raw_names={client2.get_raw_tool_names()}",
    )


async def main():
    await test_1_open_camera_dispatches_camera_open()
    await test_2_bad_name_intercepted()
    await test_3_take_photo_valid_names()
    await test_4_close_camera()
    test_5_camera_timeout()
    await test_6_not_ready_blocks_camera_calls()
    await test_7_close_deferred_during_pending_call()
    test_8_prompt_contains_camera_routing()
    await test_9_session_cache_isolation()
    await test_10_wrapped_mcp_response_unwrapped()

    print(f"\n===== 结果: {len(PASS)} passed, {len(FAIL)} failed =====")
    if FAIL:
        for f in FAIL:
            print(f"  FAILED: {f}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
