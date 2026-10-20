import bootstrap,asyncio,json,copy,dataclasses,uuid,types,time
from bootstrap import stage,budget
from stateful_device import StatefulDevice
import experience_protocol as test_protocol
from test_support import definitions,PACK
from baseline_support import make_baseline
from core.providers.tools.unified_tool_manager import ToolManager
from core.providers.tools.base import ToolType
from core.utils.tool_harness.runtime import Harness
from core.utils.tool_harness.ledger import Ledger
from core.utils.person_identity import activate,deactivate
from plugins_func.register import Action,ActionResponse
from core.utils.recipient_resolver import ProfileDirectory,ProfileRecord
from unittest.mock import patch,AsyncMock
_directory_patch=None
_directory_users=0
# Transport remains the real MCPClient + DeviceMCPExecutor over loopback WebSocket.
test_protocol.SimulationManager=StatefulDevice
class WireConversation:
 async def setup(self,provider,cfg):
  global _directory_patch,_directory_users
  import requests
  self.api_headers={'Authorization':'Bearer '+(stage/'api-test-secret').read_text()}
  info=requests.get('http://127.0.0.1:18002/xiaozhi/user-identities/internal/state/99003',headers=self.api_headers,timeout=3).json()['data']
  p=self.protocol=test_protocol.DeviceProtocol();await p.asyncSetUp();old=p.conn
  self.c,_,self.spy=make_baseline(provider,cfg,asyncio.get_running_loop(),True);c=self.c
  from bootstrap import system_prompt
  c.change_system_prompt(system_prompt(cfg))
  c.device_id=old.device_id;c.person_turn=dataclasses.replace(c.person_turn,device_id=c.device_id,turn_id=uuid.uuid4().hex)
  c.features=old.features;c.headers={};c.account_id='99003';c.person_turn=dataclasses.replace(c.person_turn,account_id='99003',person_id=info['default_user_id'],mode='default',status='default',generation=info['default_generation'],directory_version=info['directory_version'],agent_id='agent_http',display_name='默认用户');c.config['manager-api']={'url':'http://127.0.0.1:18002/xiaozhi','secret':(stage/'api-test-secret').read_text(),'max_retries':0};c.mcp_client=old.mcp_client;c.server=old.server;c.session_id=old.session_id;p.conn=c
  self.device=p.sim;self.device.conn=c
  manager=c.func_handler.tool_manager
  manager.get_all_tools=lambda:dict(self.device.tools);manager.get_ambiguous_tool_names=lambda:set()
  manager._execute_tool=types.MethodType(ToolManager._execute_tool,manager)
  # All non-device external executors are replaced with local test adapters.
  device=self.device
  class SafeExecutor:
   async def execute(self,conn,name,args):
    if name=='memory_search':
     from core.utils.recent_memory import search
     return ActionResponse(Action.REQLLM,result=await search(conn,args['query']))
    if name=='memory_add':
     from core.utils.recent_memory import add
     return ActionResponse(Action.REQLLM,result=await add(conn,args['fact']))
    if name in {'memory_correct','memory_forget'}:
     from core.utils.recent_memory import override
     return ActionResponse(Action.REQLLM,result=await override(conn,'correct' if name=='memory_correct' else 'forget',args.get('match',''),args.get('replacement'),record_id=args.get('record_id',''),expected_version=args.get('expected_version','')))
    if name=='add_reminder':raise AssertionError('real reminder interceptor must run')
    return await device._execute_tool(name,args)
  for kind in list(manager.executors):
   if kind!=ToolType.DEVICE_MCP:manager.executors[kind]=SafeExecutor()
  from core.utils.reminder_interaction import open_interaction
  import time
  open_interaction(c,instance_id='sim-card',revision=2,expires_at=int(time.time())+180)
  c.func_handler.current_support_functions=lambda:list(self.device.tools)
  # Directory is synthetic; authentication/ownership are independently tested over real HTTP.
  directory=ProfileDirectory(account_id='99003',profiles=[ProfileRecord(c.person_turn.person_id,'测试用户','active','99003')])
  if _directory_users==0:
   _directory_patch=patch('core.utils.unified_recipient_resolver._fetch_directory',AsyncMock(return_value=directory));_directory_patch.start()
  _directory_users+=1
  self.events=[]
  def enqueue(dto):self.events.append({'at':time.monotonic(),'type':dto.sentence_type.name,'content_type':dto.content_type.name,'text':str(dto.content_detail or ''),'sentence_id':dto.sentence_id,'epoch':dto.abort_epoch});return True
  c.enqueue_tts=enqueue;c._full_tool_harness=Harness(c,ledger=Ledger(':memory:'))
  # Test clock is frozen for planning, parsing and expected time calculations.
  return self
 async def turn(self,query,noise=False):
  started=time.monotonic()
  c=self.c;c.person_turn=dataclasses.replace(c.person_turn,turn_id=uuid.uuid4().hex);start=len(self.events);calls=len(self.device.calls);wire=len(self.protocol.wire);model=len(self.spy.events)
  async def ingress_noise():
   for _ in range(5):
    await asyncio.sleep(.08);c.listen_epoch+=1;c.utterance_id=getattr(c,'utterance_id',0)+1
  task=asyncio.create_task(ingress_noise()) if noise else None
  previous_outcome=getattr(c._full_tool_harness,'last_outcome',None)
  task_before=dataclasses.asdict(c._full_tool_harness.task) if c._full_tool_harness.task else None
  await asyncio.to_thread(c.chat,query,_identity=c.person_turn)
  if task:await task
  o=c._full_tool_harness.last_outcome
  if o is None or o is previous_outcome:raise RuntimeError('request_did_not_produce_current_outcome')
  events=copy.deepcopy(self.events[start:]);speech=''.join(e['text'] for e in events if e['content_type']=='TEXT')
  for event in events:event['elapsed_seconds']=event['at']-started
  return {'query':query,'task_before':task_before,'task_after':dataclasses.asdict(c._full_tool_harness.task) if c._full_tool_harness.task else None,'outcome':o.model_dump(),'speech':speech,'events':events,'calls':copy.deepcopy(self.device.calls[calls:]),'wire':copy.deepcopy(self.protocol.wire[wire:]),'state':copy.deepcopy(self.device.state),'decisions':copy.deepcopy(self.spy.events[model:]),'assistant_history':[m.content for m in c.dialogue.dialogue if m.role=='assistant' and m.content][-1:],'user_history':[m.content for m in c.dialogue.dialogue if m.role=='user' and isinstance(m.content,str)],'dialogue_history':[{'role':m.role,'content':m.content} for m in c.dialogue.dialogue if m.role in {'user','assistant'} and m.content]}
 async def close(self):
  global _directory_users,_directory_patch
  from core.utils.reminder_interaction import close_interaction
  close_interaction(self.c)
  _directory_users-=1
  if _directory_users==0:_directory_patch.stop()
  await self.protocol.asyncTearDown();self.c.executor.shutdown(wait=False);self.c._full_tool_harness.ledger.close()
