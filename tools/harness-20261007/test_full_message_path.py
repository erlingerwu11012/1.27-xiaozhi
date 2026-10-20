"""Real signed model -> ConnectionHandler -> ToolManager -> loopback WS device."""
import asyncio,json,unittest,types
from unittest.mock import MagicMock
import run_compare  # same frozen trusted clock and no verbose prompt printing
from bootstrap import production_provider,stage
from baseline_support import make_baseline,run_baseline
from test_protocol import DeviceProtocol
from core.providers.tools.unified_tool_handler import UnifiedToolHandler
from core.utils.tool_harness.runtime import Harness
from core.utils.tool_harness.ledger import Ledger
from core.utils.person_identity import activate,deactivate

class FullMessagePath(DeviceProtocol):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        previous=self.conn
        deactivate(self.actor_token)
        provider,cfg=production_provider()
        conn,_,self.spy=make_baseline(provider,cfg,asyncio.get_running_loop(),harness=True)
        conn._full_tool_harness.ledger.close()
        conn.device_id=previous.device_id;conn.session_id=previous.session_id
        conn.mcp_client=previous.mcp_client;conn.features=previous.features
        conn.server=previous.server;conn.person_turn=previous.person_turn
        conn.func_handler=UnifiedToolHandler(conn)
        self.conn=conn;self.manager=conn.func_handler.tool_manager
        conn._full_tool_harness=Harness(conn,ledger=Ledger(':memory:'))
        from core.providers.tools.base import ToolDefinition,ToolType
        from test_support import PACK
        definition=next(t for t in PACK['tools'] if t['function']['name']=='add_reminder')
        d=ToolDefinition('add_reminder',{k:v for k,v in definition.items() if k!='source'},ToolType.SERVER_MCP)
        async def forbidden(*a):self.fail('must use actual device reminder interceptor')
        self.manager.register_executor(ToolType.SERVER_MCP,types.SimpleNamespace(get_tools=lambda:{'add_reminder':d},execute=forbidden))
        self.actor_token=activate(conn,conn.person_turn)
    async def asyncTearDown(self):
        await super().asyncTearDown()
        self.conn.executor.shutdown(wait=False,cancel_futures=True)
        self.conn._full_tool_harness.ledger.close()
    async def test_real_model_and_message_path(self):
        cases=[('屏幕亮度帮我改到九成','self_screen_set_brightness',{'brightness':90}),
               ('声音给我轻轻加大一点','self_audio_speaker_set_volume',{'volume':60}),
               ('我想每天晚上十一点让闹钟响','alarm_set',{'hour':23,'repeat_days':127}),
               ('第1条便签把提醒推迟8分钟','note_snooze',{'index':1,'delay_minutes':8}),
               ('拿摄像头拍下桌面，告诉我桌上有什么','self_camera_take_photo',{}),
               ('我喝完了，把当前提醒确认完成','reminder_action',{'instance_id':'sim-card','revision':2,'action':'primary'}),
               ('帮我设一个提醒，七分钟后提醒我热牛奶。','add_reminder',{})]
        evidence=[]
        from dataclasses import replace
        import uuid
        for user,tool,wanted in cases:
            from budget_guard import reserve_record
            reserve_record()
            self.conn.listen_epoch+=1
            self.conn.person_turn=replace(self.conn.person_turn,listen_epoch=self.conn.listen_epoch,turn_id=uuid.uuid4().hex)
            begin=len(self.wire);events=len(self.spy.events)
            outcome=await asyncio.wait_for(asyncio.to_thread(run_baseline,self.conn,self.sim,self.spy,user),95)
            actual=[r for r in outcome.results if r.tool==tool]
            record={'user':user,'outcome':outcome.model_dump(),'wire':self.wire[begin:],'events':self.spy.events[events:],
                    'evidence':'real-model-and-loopback-protocol','hardware':False,'billing_gateway':True}
            evidence.append(record)
            (stage/'full-message-evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf8')
            self.assertEqual(len(actual),1,record)
            self.assertEqual(actual[0].state,'completed',record)
            self.assertTrue(all(actual[0].arguments.get(k)==v for k,v in wanted.items()),record)
            self.assertEqual(self.conn.speech[-1],outcome.reply)
            if tool=='add_reminder':
                writes=[p for p in record['wire'] if p.get('method')=='tools/call' and p['params']['name']=='note.add']
                self.assertEqual(len(writes),1)
                self.assertEqual(writes[0]['params']['arguments']['text'],'热牛奶')

if __name__=='__main__':
    suite=unittest.TestSuite([FullMessagePath('test_real_model_and_message_path')])
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
