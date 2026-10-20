"""Exercise the actual MCP handler without loading production config or models."""
import ast
import asyncio
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import AsyncMock, MagicMock

ROOT = Path(__file__).resolve().parent / 'server'

def load_handler():
    tree = ast.parse((ROOT/'core/providers/tools/device_mcp/mcp_handler.py').read_text(encoding='utf-8'))
    names = {'_is_retired_touch_message', '_mcp_session_tag', 'handle_mcp_message'}
    tree.body = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names]
    scope = dict(asyncio=asyncio, json=json, MCPClient=object, logger=MagicMock(), TAG='test',
                 send_mcp_tools_list_request=AsyncMock(), send_mcp_tools_list_continue_request=AsyncMock())
    exec(compile(tree, '<production-mcp-handler>', 'exec'), scope)
    return scope

class TouchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.s = load_handler()
        self.client = types.SimpleNamespace(closed=False, session_id='session', call_results={},
            take_request=MagicMock(return_value=('tools/list', 1)), catalog_generation=1,
            catalog_pages=[], catalog_cursors=set(), finish_catalog=AsyncMock(return_value=True),
            tools={}, catalog_version='v1', resolve_call_result=AsyncMock())
        self.conn = types.SimpleNamespace(mcp_client=self.client, session_id='session', device_id='test',
            websocket=types.SimpleNamespace(send=AsyncMock()), executor=MagicMock(), chat=MagicMock())

    async def test_flat_touch_does_nothing(self):
        await self.s['handle_mcp_message'](self.conn, self.client, {'type':'touch_prompt','source':'head_tap'})
        self.conn.websocket.send.assert_not_awaited()
        self.conn.executor.submit.assert_not_called()
        self.client.take_request.assert_not_called()
        self.assertFalse(hasattr(self.conn, 'touch_count'))
        self.assertFalse(hasattr(self.conn, 'pending_touch_prompt'))

    async def test_wrapped_touch_does_nothing(self):
        msg={'params':{'arguments':{'mcp_data':{'type':'touch_prompt','source':'face_swipe'}}}}
        await self.s['handle_mcp_message'](self.conn,self.client,msg)
        self.conn.websocket.send.assert_not_awaited()
        self.conn.executor.submit.assert_not_called()
        self.client.take_request.assert_not_called()

    async def test_repeat_touches_never_schedule(self):
        for _ in range(8):
            await self.s['handle_mcp_message'](self.conn,self.client,{'type':'touch_prompt'})
        self.conn.executor.submit.assert_not_called()
        self.assertFalse(hasattr(self.conn,'last_touch_time'))

    def test_malformed_retired_detection(self):
        for msg in (None, [], {'params':None}, {'params':{'arguments':None}},
                    {'params':{'arguments':{'mcp_data':None}}}):
            self.assertFalse(self.s['_is_retired_touch_message'](msg))

    async def test_normal_tool_result(self):
        self.client.call_results[4]=object()
        await self.s['handle_mcp_message'](self.conn,self.client,{'id':4,'result':{'ok':True}})
        self.client.resolve_call_result.assert_awaited_once_with(4,{'ok':True})

    async def test_catalog_still_finishes(self):
        await self.s['handle_mcp_message'](self.conn,self.client,{'id':2,'result':{'tools':[]}})
        self.client.finish_catalog.assert_awaited_once_with(1)

    async def test_wrapped_tool_result(self):
        self.client.call_results[5]=object()
        result={'id':5,'result':{'ok':True}}
        await self.s['handle_mcp_message'](self.conn,self.client,{'params':{'arguments':{'mcp_data':result}}})
        self.client.resolve_call_result.assert_awaited_once_with(5,{'ok':True})

    async def test_catalog_notification(self):
        await self.s['handle_mcp_message'](self.conn,self.client,{'method':'notifications/tools/list_changed'})
        self.s['send_mcp_tools_list_request'].assert_awaited_once_with(self.conn)

    async def test_initialize_receipt(self):
        self.client.take_request.return_value=('initialize',1)
        module=types.ModuleType('core.utils.person_directory_sync')
        module.report_capability=AsyncMock()
        with unittest.mock.patch.dict(sys.modules,{'core.utils.person_directory_sync':module}):
            await self.s['handle_mcp_message'](self.conn,self.client,{'id':1,'result':{'capabilities':{'vision':True}}})
            await asyncio.sleep(0)
        self.assertEqual(self.client.capabilities,{'vision':True})
        self.s['send_mcp_tools_list_request'].assert_awaited_once_with(self.conn)

    def test_no_touch_hint_or_emotion_emit_left(self):
        source=(ROOT/'core/connection.py').read_text(encoding='utf-8')
        self.assertNotIn('pending_touch_prompt',source)
        handler=(ROOT/'core/providers/tools/device_mcp/mcp_handler.py').read_text(encoding='utf-8')
        for old in ('touch_count','last_touch_time','emotion_payload','trigger_touch_chat'):
            self.assertNotIn(old,handler)

if __name__=='__main__': unittest.main(verbosity=2)
