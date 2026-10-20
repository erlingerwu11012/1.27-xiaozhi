# 文件路径: core/protocol.py
import json
import asyncio
from fastapi.responses import StreamingResponse

def mcp_sse_pack(payload: dict, heartbeat: bool = False):
    """
    将字典数据包装成 MCP 标准的 SSE (Server-Sent Events) 流式响应
    """
    async def event_generator():
        # 发送标准 SSE 格式数据
        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        
        # 如果是浏览器或长连接客户端，维持心跳
        if heartbeat:
            try:
                while True:
                    await asyncio.sleep(25)
                    yield ": heartbeat\n\n"
            except: 
                pass
                
    return StreamingResponse(event_generator(), media_type="text/event-stream")