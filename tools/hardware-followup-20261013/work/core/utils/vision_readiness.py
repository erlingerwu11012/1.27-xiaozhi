import asyncio,time
from concurrent.futures import Future

async def ensure_vision(conn,identity=False):
    client=getattr(conn,'mcp_client',None)
    if not client or client.capabilities.get('experimental',{}).get('visionStatus',0)<1:return None
    session=getattr(conn,'session_id','')
    async def request(method,params):
        from core.providers.tools.device_mcp.mcp_handler import send_mcp_message
        call_id=await client.get_next_id();future=Future()
        await client.register_call_result_future(call_id,future)
        try:
            await send_mcp_message(conn,{'jsonrpc':'2.0','id':call_id,'method':method,'params':params})
            result=await asyncio.wait_for(asyncio.wrap_future(future),3)
            if not isinstance(result,dict) or result.get('session_id')!=session or getattr(conn,'session_id','')!=session:raise ValueError('vision_session_mismatch')
            return result
        finally:
            client.call_results.pop(call_id,None)
    state=await request('vision/status',{'session_id':session})
    key='identity_ready' if identity else 'explain_ready'
    if state.get(key) is True:return state
    reason=state.get('identity_reason' if identity else 'explain_reason','unknown')
    if time.monotonic()-getattr(conn,'_vision_refresh_at',0)<60:return state
    if reason in {'connection_closed','vision_session_mismatch'}:return state
    from core.utils.vision_capability import build_vision_capabilities
    from core.utils.account_identity import resolve_face_account_id
    cap=build_vision_capabilities(conn.config,device_id=conn.device_id,account_id=resolve_face_account_id(conn=conn) or '',session_id=session)
    if not cap.ok:return state
    conn._vision_refresh_at=time.monotonic()
    return await request('vision/refresh',{'session_id':session,'vision':cap.vision})
