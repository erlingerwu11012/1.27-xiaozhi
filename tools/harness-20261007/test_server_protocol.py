import asyncio,json,types,unittest
from unittest.mock import MagicMock
from aiohttp import web
from bootstrap import stage
from test_support import PACK
from core.providers.tools.server_mcp.mcp_client import ServerMCPClient
from core.providers.tools.server_mcp.mcp_executor import ServerMCPExecutor
from core.providers.tools.server_plugins.plugin_executor import ServerPluginExecutor
from core.providers.tools.device_iot.iot_executor import DeviceIoTExecutor
from core.providers.tools.mcp_endpoint.mcp_endpoint_executor import MCPEndpointExecutor
from core.utils.tool_harness.contracts import receipt

class ServerProtocol(unittest.IsolatedAsyncioTestCase):
    async def test_http_mcp_actual_sdk_and_executor(self):
        calls=[];failure=False
        tools=[t for t in PACK['tools'] if t['source']=='server_mcp' and t['function']['name'] in {'get_world_time','random_decision'}]
        async def endpoint(request):
            if request.method=='GET':return web.Response(status=405)
            if request.method=='DELETE':return web.Response(status=200)
            p=await request.json()
            if 'id' not in p:return web.Response(status=202)
            if p['method']=='initialize':result={'protocolVersion':p['params']['protocolVersion'],'capabilities':{'tools':{}},'serverInfo':{'name':'loopback-simulation','version':'1'}}
            elif p['method']=='tools/list':result={'tools':[{'name':t['function']['name'],'description':t['function']['description'],'inputSchema':t['function']['parameters']} for t in tools]}
            elif p['method']=='tools/call':
                name=p['params']['name'];calls.append(p)
                result={'isError':failure,'content':[{'type':'text','text':'模拟服务拒绝' if failure else PACK['fixtures'][name]['receipt']}]}
            else:return web.json_response({'jsonrpc':'2.0','id':p['id'],'error':{'code':-32601,'message':'unsupported'}})
            return web.json_response({'jsonrpc':'2.0','id':p['id'],'result':result})
        app=web.Application();app.router.add_route('*','/mcp',endpoint)
        runner=web.AppRunner(app);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
        port=site._server.sockets[0].getsockname()[1]
        client=ServerMCPClient({'url':f'http://127.0.0.1:{port}/mcp','transport':'streamable-http','timeout':3})
        try:
            await asyncio.wait_for(client.initialize(),5)
            conn=types.SimpleNamespace(config={})
            executor=ServerMCPExecutor(conn);executor._initialized=True
            executor.mcp_manager=types.SimpleNamespace(execute_tool=client.call_tool,get_all_tools=client.get_available_tools)
            self.assertEqual(2,len(executor.get_tools()))
            evidence=[]
            for name in ['get_world_time','random_decision']:
                f=PACK['fixtures'][name];r=await executor.execute(conn,name,f['arguments']);v=receipt(name,f['arguments'],r,'http-'+name)
                self.assertEqual(v.state,'completed',v.model_dump());evidence.append(v.model_dump())
            failure=True;r=await executor.execute(conn,'get_world_time',{'timezone':'Asia/Tokyo'})
            self.assertEqual(receipt('get_world_time',{},r,'failed').state,'failed')
            (stage/'protocol-server-evidence.json').write_text(json.dumps({'evidence':'software-loopback','results':evidence,'calls':calls},ensure_ascii=False,indent=2))
        finally:await client.cleanup();await runner.cleanup()

    async def test_actual_lunar_plugin_facts_only(self):
        import plugins_func.functions.get_time
        conn=types.SimpleNamespace(config={});executor=ServerPluginExecutor(conn)
        args={'date':'2026-10-08','query':'农历和干支'}
        r=await executor.execute(conn,'get_lunar',args);v=receipt('get_lunar',args,r,'lunar')
        self.assertEqual(v.state,'completed');self.assertIn('农历',v.reply);self.assertIn('干支',v.reply);self.assertNotIn('根据以下信息',v.reply)
        self.assertNotIn('宜忌',v.reply)

    async def test_inactive_iot_and_endpoint_not_enabled(self):
        conn=types.SimpleNamespace(config={})
        for executor in [DeviceIoTExecutor(conn),MCPEndpointExecutor(conn)]:
            self.assertEqual({},executor.get_tools())
            result=await executor.execute(conn,'not_enabled',{})
            self.assertIn(result.action.name,{'ERROR','NOTFOUND'})

    async def test_memory_plugins_preserve_trusted_actor_and_pending_stage(self):
        from unittest.mock import AsyncMock,patch
        from core.utils.person_identity import PersonTurn,activate,deactivate
        import plugins_func.functions.person_memory
        actor=PersonTurn('simulation-account','person-a',1,1,'personal','matched','memory-turn','sim-device','sim-agent',1)
        dialogue=MagicMock();dialogue.dialogue=[]
        conn=types.SimpleNamespace(config={},memory=None,dialogue=dialogue)
        client=MagicMock();client.request=AsyncMock(return_value={'status':'found','text':'喜欢咖啡','reliable':True})
        token=activate(conn,actor)
        try:
            with patch('config.manage_api_client.ManageApiClient',return_value=client):
                executor=ServerPluginExecutor(conn)
                r=await executor.execute(conn,'memory_search',{'query':'喜欢咖啡'})
                self.assertEqual(receipt('memory_search',{'query':'喜欢咖啡'},r,'search').state,'completed')
                sent=client.request.call_args.kwargs['json'];self.assertEqual(sent['actor']['person_id'],'person-a')
                r=await executor.execute(conn,'memory_forget',{'match':'喜欢咖啡'})
                self.assertEqual(receipt('memory_forget',{'match':'喜欢咖啡'},r,'forget').state,'accepted')
                r=await executor.execute(conn,'memory_correct',{'match':'喜欢咖啡','replacement':'喜欢绿茶'})
                self.assertEqual(receipt('memory_correct',{'match':'喜欢咖啡','replacement':'喜欢绿茶'},r,'correct').state,'accepted')
        finally:deactivate(token)

if __name__=='__main__':unittest.main(verbosity=2)
