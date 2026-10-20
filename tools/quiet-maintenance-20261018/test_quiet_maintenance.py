import ast,asyncio,json,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,MagicMock,patch
from core.utils.person_identity import PersonTurn,current_turn
from core.utils.habit_router import route_habit_analysis
from core.utils.person_maintenance import service_control
from core.providers.tools.device_mcp.mcp_client import MCPClient

class QuietTests(unittest.IsolatedAsyncioTestCase):
 async def test_legacy_trigger_never_enters_asr_model_or_speaker_reset(self):
  source=Path('core/handle/textHandler/listenMessageHandler.py').read_text()
  tree=ast.parse(source)
  method=next(x for c in tree.body if isinstance(c,ast.ClassDef) for x in c.body if isinstance(x,ast.AsyncFunctionDef) and x.name=='handle')
  method.args.args[-1].annotation=None
  globals_={'TAG':'test'}
  exec(compile(ast.Module(body=[method],type_ignores=[]),source,'exec'),globals_)
  conn=SimpleNamespace(logger=MagicMock(),listen_epoch=3,person_turn='unchanged')
  with patch('core.utils.person_maintenance.start_maintenance') as start:
   await globals_['handle'](None,conn,{'state':'detect','text':'[MAINTENANCE] old instruction'})
   start.assert_called_once_with(conn)
  self.assertEqual((conn.listen_epoch,conn.person_turn),(3,'unchanged'))

 async def test_empty_pattern_completed_without_model_device_or_tts(self):
  actor=PersonTurn('10','person',0,1,'personal','matched','maintenance_job','device','agent',0,'voice',1)
  conn=SimpleNamespace(config={},loop=asyncio.get_running_loop())
  request=AsyncMock(return_value={'device_watermarks':[{'device_id':'server:device','watermark':'8'}]})
  with patch('config.manage_api_client.ManageApiClient') as client,patch('core.utils.habit_router._call_llm_with_tools') as llm:
   client.return_value.request=request
   result=await asyncio.to_thread(route_habit_analysis,conn,{'person_id':'person','watermark':'8','server_job':'job','summaries':[]},actor)
  self.assertTrue(result);llm.assert_not_called();request.assert_awaited_once()
  self.assertEqual(request.call_args.args[1],'person-memory/internal/behavior/complete')
  self.assertIsNone(current_turn(conn));self.assertFalse(service_control.get())

 def test_auto_learning_hidden_from_chat_catalog_but_visible_to_worker(self):
  client=MCPClient()
  client.ready=True;client.closed=False
  client.capabilities={'experimental':{'personBehavior':2}}
  client.tools={'habit_learn':{'description':'learn','inputSchema':{}},'habit_list':{'description':'list','inputSchema':{}}}
  client.name_mapping={'habit_learn':'habit.learn','habit_list':'habit.list'}
  self.assertEqual([x['function']['name'] for x in client.get_available_tools()],['habit_list'])
  self.assertEqual(len(client.get_available_tools(include_maintenance=True)),2)
  self.assertEqual(len(client.get_available_tools()),1)
