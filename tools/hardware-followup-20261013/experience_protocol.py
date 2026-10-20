"""Loopback software device and HTTP MCP. No production devices or business writes."""
import asyncio,copy,json,types,unittest
from unittest.mock import MagicMock
from aiohttp import web,ClientSession,WSMsgType
from bootstrap import stage
from test_support import PACK,SimulationManager,decision,step
from core.providers.tools.device_mcp.mcp_client import MCPClient
from core.providers.tools.device_mcp.mcp_handler import handle_mcp_message,send_mcp_tools_list_request,_call_mcp_tool
from core.providers.tools.device_mcp.mcp_executor import DeviceMCPExecutor
from core.providers.tools.unified_tool_manager import ToolManager
from core.providers.tools.base import ToolType
from core.utils.person_identity import PersonTurn,activate,deactivate
from core.utils.tool_harness.runtime import Harness
from core.utils.tool_harness.ledger import Ledger
from core.utils.tool_harness.contracts import receipt

def raw_name(name):
    special={'self_get_device_status':'self.get_device_status','self_get_system_info':'self.get_system_info',
      'self_audio_speaker_set_volume':'self.audio_speaker.set_volume','self_camera_take_photo':'self.camera.take_photo',
      'self_camera_identify_person':'self.camera.identify_person','self_reboot':'self.reboot'}
    if name in special:return special[name]
    if name.startswith('camera_face_enroll_'):return 'camera.face.enroll.'+name[len('camera_face_enroll_'):]
    if name.startswith('self_screen_'):return 'self.screen.'+name[len('self_screen_'):]
    prefix,tail=name.split('_',1);return prefix+'.'+tail

class DeviceProtocol(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.sim=SimulationManager();self.wire=[];self.fault=None;self.reader=None
        self.raw={raw_name(t['function']['name']):t['function']['name'] for t in PACK['tools'] if t['source']=='device_mcp' and t['function']['name'] in self.sim.tools}
        self.raw['reminder.close_current']='reminder_close_current'
        async def device(request):
            ws=web.WebSocketResponse();await ws.prepare(request)
            async for msg in ws:
                if msg.type!=WSMsgType.TEXT:continue
                p=json.loads(msg.data)['payload'];self.wire.append(p)
                if p.get('method')=='tools/list':
                    body={'tools':[{'name':raw,'description':self.sim.tools[name].description['function']['description'],'inputSchema':self.sim.tools[name].description['function']['parameters']} for raw,name in self.raw.items()]}
                elif p.get('method')=='tools/call':
                    if self.fault=='timeout':continue
                    name=self.raw[p['params']['name']];args=p['params']['arguments']
                    if self.fault=='storage':content=''
                    else:
                        result=await self.sim._execute_tool(name,args)
                        content=result.result
                    if name=='reminder_get_current':
                        content=json.dumps({**json.loads(content),'recipient_id':self.conn.person_turn.person_id})
                    body={'content':[{'type':'text','text':str(content)}]}
                    if self.fault=='wrong_id':
                        await ws.send_json({'type':'mcp','payload':{'jsonrpc':'2.0','id':p['id']+10000,'result':{'content':[{'type':'text','text':'wrong response'}]}}})
                    if self.fault=='storage':body={'isError':True,'content':[{'type':'text','text':'{"errorCode":"storage_no_space","message":"NVS空间不足"}'}]}
                    if self.fault=='wrong_value':body={'content':[{'type':'text','text':'{"ok":true,"volume":99}'}]}
                    if self.fault=='queued':body={'content':[{'type':'text','text':'{"accepted":true,"volume":30}'}]}
                    if self.fault=='stale_session':self.conn.session_id='replacement'
                else:continue
                await ws.send_json({'type':'mcp','payload':{'jsonrpc':'2.0','id':p['id'],'result':body}})
            return ws
        app=web.Application();app.router.add_get('/device',device)
        self.runner=web.AppRunner(app);await self.runner.setup();site=web.TCPSite(self.runner,'127.0.0.1',0);await site.start()
        port=site._server.sockets[0].getsockname()[1]
        self.http=ClientSession();self.ws=await self.http.ws_connect(f'http://127.0.0.1:{port}/device')
        self.conn=types.SimpleNamespace(device_id='SOFTWARE-DEVICE-ONLY',session_id='software-session',features={'mcp':True},config={'harness':{'enabled':True}},logger=MagicMock(),listen_epoch=1,tts=None)
        self.conn.person_turn=PersonTurn('simulation-account','person-a',1,1,'personal','matched','protocol-turn',self.conn.device_id,'sim-agent',1)
        self.conn.mcp_client=MCPClient(device_id=self.conn.device_id,session_id=self.conn.session_id)
        self.conn.mcp_client.capabilities={'experimental':{'personBehavior':2,'personalIdentity':2,'identityCleanup':2,'weeklySchedule':2}}
        async def send(device_id,data,**kw):
            if not self.conn.server.is_current_connection(device_id,self.conn):return False
            await self.ws.send_str(data);return True
        self.conn.server=types.SimpleNamespace(is_current_connection=lambda d,c:not getattr(c,'superseded',False),send_to_current=send)
        self.manager=ToolManager(self.conn);self.manager.register_executor(ToolType.DEVICE_MCP,DeviceMCPExecutor(self.conn))
        self.conn.func_handler=types.SimpleNamespace(tool_manager=self.manager,current_support_functions=lambda:None)
        async def read():
            async for msg in self.ws:
                if msg.type==WSMsgType.TEXT:await handle_mcp_message(self.conn,self.conn.mcp_client,json.loads(msg.data)['payload'])
        self.reader=asyncio.create_task(read())
        await send_mcp_tools_list_request(self.conn);self.assertTrue(await self.conn.mcp_client.wait_ready())
        self.actor_token=activate(self.conn,self.conn.person_turn)

    async def asyncTearDown(self):
        deactivate(self.actor_token)
        monitor=getattr(self.conn,'_face_enrollment_monitor',None)
        if monitor:monitor.cancel()
        await self.conn.mcp_client.close();await self.ws.close()
        if self.reader:await self.reader
        await self.http.close();await self.runner.cleanup()

    async def test_whole_device_catalog_real_executor(self):
        from core.providers.tools.retired_tools import is_retired_tool
        self.assertEqual({n for n in self.raw.values() if not is_retired_tool(n)},set(self.manager.get_all_tools()))
        records=[]
        for name in self.raw.values():
            with self.subTest(tool=name):
                if is_retired_tool(name):
                    response=await self.manager._execute_tool(name,{})
                    self.assertEqual(response.action.name,'ERROR')
                    records.append({'tool':name,'state':'disabled','reason':'retired_maintenance_endpoint'})
                    continue
                fixture=PACK['fixtures'].get(name,{'query':'关闭当前卡片','arguments':{'instance_id':'sim-card','revision':2}})
                self.conn._person_tool_results={}
                self.conn._person_inputs={self.conn.person_turn.turn_id:fixture['arguments'].get('raw','')}
                self.sim.state['notes']=[{'text':'测试备忘','remind_at':0}]
                self.sim.state['habits']=[{'description':'喝水','hour':18,'minute':0}]
                self.sim.state['alarms']=[{'hour':22,'minute':0,'repeat_days':0,'label':'闹钟'}]
                self.sim.state['card'].update(active=True,instance_id='sim-card',revision=2)
                self.sim.save()
                response=await self.manager._execute_tool(name,copy.deepcopy(fixture['arguments']))
                verified=receipt(name,fixture['arguments'],response,'contract-'+name)
                records.append(verified.model_dump())
                expected='accepted' if name in {'self_reboot','camera_face_enroll_start'} else 'completed'
                self.assertEqual(expected,verified.state,verified.model_dump())
        import os
        (stage/(os.getenv('PROTOCOL_RUN_NAME','protocol')+'-device-evidence.json')).write_text(json.dumps({'evidence':'software-loopback','tools':records,'wire':self.wire},ensure_ascii=False,indent=2))

    async def test_actual_relative_harness(self):
        h=Harness(self.conn,ledger=Ledger(':memory:'),decide=lambda _:decision(step('self_audio_speaker_set_volume',relative=10)))
        result=await h.run('大声一点',[])
        self.assertEqual(result.results[-1].state,'completed');self.assertEqual(self.sim.volume,60)
        self.assertEqual([p['params']['name'] for p in self.wire if p.get('method')=='tools/call'],['self.get_device_status','self.audio_speaker.set_volume']);h.ledger.close()

    async def test_rpc_wrong_id_ignored(self):
        self.fault='wrong_id';result=await self.manager._execute_tool('self_audio_speaker_set_volume',{'volume':30})
        self.assertEqual(receipt('self_audio_speaker_set_volume',{'volume':30},result,'x').state,'completed')
        self.assertFalse(self.conn.mcp_client.call_results)

    async def test_rpc_storage_error(self):
        self.fault='storage';result=await self.manager._execute_tool('note_add',{'text':'测试便签','remind_at':0})
        self.assertEqual(receipt('note_add',{'text':'测试便签','remind_at':0},result,'x').state,'failed')

    async def test_wrong_value_and_queued_not_completed(self):
        for fault in ['wrong_value','queued']:
            self.fault=fault;result=await self.manager._execute_tool('self_audio_speaker_set_volume',{'volume':30})
            self.assertNotEqual(receipt('self_audio_speaker_set_volume',{'volume':30},result,'x').state,'completed')

    async def test_session_replacement_rejects_receipt(self):
        self.fault='stale_session'
        result=await self.manager._execute_tool('self_audio_speaker_set_volume',{'volume':30})
        self.assertNotEqual(receipt('self_audio_speaker_set_volume',{'volume':30},result,'x').state,'completed')

    async def test_timeout_not_retried(self):
        self.fault='timeout'
        with self.assertRaises(TimeoutError):await _call_mcp_tool(self.conn,self.conn.mcp_client,'self_audio_speaker_set_volume','{"volume":30}',timeout=.03)
        self.assertEqual(len([p for p in self.wire if p.get('method')=='tools/call']),1)

    async def test_unknown_identity_cannot_write_habit(self):
        from dataclasses import replace
        unknown=replace(self.conn.person_turn,person_id='',status='unknown')
        token=activate(self.conn,unknown)
        try:result=await self.manager._execute_tool('habit_learn',PACK['fixtures']['habit_learn']['arguments'])
        finally:deactivate(token)
        self.assertEqual(receipt('habit_learn',PACK['fixtures']['habit_learn']['arguments'],result,'x').state,'failed')
        self.assertFalse([p for p in self.wire if p.get('method')=='tools/call'])

    async def test_reminder_real_interceptor_checks_saved_arguments(self):
        from core.providers.tools.base import ToolDefinition
        tool=next(t for t in PACK['tools'] if t['function']['name']=='add_reminder')
        definition=ToolDefinition('add_reminder',{k:v for k,v in tool.items() if k!='source'},ToolType.SERVER_MCP)
        async def forbidden(*a):self.fail('reminder must use authorized device, never gateway fallback')
        executor=types.SimpleNamespace(get_tools=lambda:{'add_reminder':definition},execute=forbidden)
        self.manager.register_executor(ToolType.SERVER_MCP,executor)
        self.conn.config['operation_control']={'enabled':True}
        args={'content':'喝水','remind_time_str':'十分钟后'}
        response=await self.manager._execute_tool('add_reminder',args)
        self.assertEqual(receipt('add_reminder',args,response,'create').state,'completed')
        response=await self.manager._execute_tool('add_reminder',{'text':'设一个提醒，七分钟后提醒我热牛奶'})
        self.assertEqual(receipt('add_reminder',{'text':'设一个提醒，七分钟后提醒我热牛奶'},response,'header').state,'completed')
        self.assertEqual([x for x in self.wire if x.get('method')=='tools/call'][-1]['params']['arguments']['text'],'热牛奶')
        from plugins_func.register import Action,ActionResponse
        self.sim.faults['note_add']=ActionResponse(Action.REQLLM,result='已记录：错误的内容')
        response=await self.manager._execute_tool('add_reminder',args)
        self.assertNotEqual(receipt('add_reminder',args,response,'mismatch').state,'completed')

if __name__=='__main__':unittest.main(verbosity=2)
