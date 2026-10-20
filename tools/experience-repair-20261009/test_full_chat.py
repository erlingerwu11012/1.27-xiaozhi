import bootstrap,asyncio,json,sys,dataclasses,copy,time
from bootstrap import stage,budget,system_prompt
from baseline_support import make_baseline
from stateful_device import StatefulDevice
from unittest.mock import MagicMock
from core.utils.tool_harness.runtime import Harness
from core.utils.tool_harness.ledger import Ledger
from core.utils.person_identity import PersonTurn
from test_support import decision,step
cfg=json.load(open('/root/prjs/tmp/harness-20261007/private-backup/runtime-config.json'))
class Fake:
 last_usage={}
 def decision(self,messages):return {'mode':'chat','reply':'你好，我在。'}
async def main():
 c,m,spy=make_baseline(Fake(),cfg,asyncio.get_running_loop(),True)
 d=StatefulDevice();d.conn=c;manager=c.func_handler.tool_manager
 manager.get_all_tools=d.get_all_tools;manager.get_ambiguous_tool_names=d.get_ambiguous_tool_names;manager._execute_tool=d._execute_tool
 c._full_tool_harness=Harness(c,ledger=Ledger(':memory:'))
 events=[]
 def enqueue(dto):
  events.append({'type':dto.sentence_type.name,'content_type':dto.content_type.name,'text':str(dto.content_detail or ''),'sentence_id':dto.sentence_id,'epoch':dto.abort_epoch});return True
 c.enqueue_tts=enqueue
 results=[]
 for query in ['嘿，你好呀','亮度调到百分之九十','音量再大一点']:
  budget.reserve('case','full-chat:'+query);c.person_turn=dataclasses.replace(c.person_turn,turn_id=__import__('uuid').uuid4().hex)
  start=len(events);await asyncio.to_thread(c.chat,query,_identity=c.person_turn)
  outcome=c._full_tool_harness.last_outcome
  text=''.join(x['text'] for x in events[start:] if x['content_type']=='TEXT')
  assert text and text==outcome.reply,(query,text,outcome)
  assert [x['type'] for x in events[start:]]==['FIRST','MIDDLE','LAST'],events[start:]
  assert c.llm_finish_task
  results.append({'query':query,'speech':text,'outcome':outcome.model_dump(),'events':events[start:],'state':copy.deepcopy(d.state)})
 (stage/'full-chat-deterministic.json').write_text(json.dumps(results,ensure_ascii=False,indent=2));print('full chat PASS',len(results),budget.report())
asyncio.run(main())
