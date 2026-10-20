"""Actual HTTP chunks -> OpenAI adapter -> Harness -> TTS queue. No paid model/TTS."""
import bootstrap,asyncio,json,threading,time,unittest,collections
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from bootstrap import budget,stage
from core.providers.llm.openai.openai import LLMProvider
from wire_conversation import WireConversation
from core.utils.reminder_interaction import close_interaction
from unittest.mock import MagicMock

class Network(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.charge=budget.reserve('case',self.id());self.plans=collections.deque();self.requests=[];self.gates=[]
  owner=self
  class Handler(BaseHTTPRequestHandler):
   protocol_version='HTTP/1.1'
   def log_message(self,*args):pass
   def do_POST(self):
    request=json.loads(self.rfile.read(int(self.headers['Content-Length'])));owner.requests.append(request)
    plan=owner.plans.popleft();self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Transfer-Encoding','chunked');self.end_headers()
    def send(content=None,finish=None):
     body={'id':'network-test','object':'chat.completion.chunk','model':'qwen3.7-plus','created':1,'choices':[{'index':0,'delta':{'content':content} if content else {},'finish_reason':finish}]}
     data=('data: '+json.dumps(body,ensure_ascii=False)+'\n\n').encode();self.wfile.write(f'{len(data):x}\r\n'.encode()+data+b'\r\n');self.wfile.flush()
    try:
     for part in plan['before']:send(part)
     if plan.get('gate'):
      plan['sent'].set()
      if not plan['gate'].wait(12):raise TimeoutError('consumer_did_not_observe_network_chunk')
     for part in plan.get('after',[]):send(part)
     send(finish='stop');self.wfile.write(b'0\r\n\r\n');self.wfile.flush()
    except (BrokenPipeError,ConnectionResetError):pass
  self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
  self.provider=LLMProvider({'model_name':'qwen3.7-plus','api_key':'local-test','base_url':f'http://127.0.0.1:{self.server.server_port}/v1','temperature':.4})
  cfg=json.loads(Path('/root/prjs/tmp/harness-20261007/private-backup/runtime-config.json').read_text())
  self.w=await WireConversation().setup(self.provider,cfg);close_interaction(self.w.c);self.w.device.state['card']['active']=False;self.w.device.save()
 async def asyncTearDown(self):
  for gate in self.gates:gate.set()
  await self.w.close();self.provider.client.close();await asyncio.to_thread(self.server.shutdown);self.server.server_close();self.thread.join(2)
  budget.finish(self.charge,{'network_requests':len(self.requests),'paid_model':False,'real_tts':False})
 def plan(self,before,after=(),gated=False):
  p={'before':list(before),'after':list(after)}
  if gated:p.update(gate=threading.Event(),sent=threading.Event());self.gates.append(p['gate'])
  self.plans.append(p);return p
 async def wait_text(self,text):
  for _ in range(150):
   if text in ''.join(e['text'] for e in self.w.events):return
   await asyncio.sleep(.02)
  self.fail('first_sentence_not_emitted_before_full_HTTP_response')
 async def test_first_sentence_before_complete_response(self):
  p=self.plan(['{"mode":"chat","steps":[],"authorized_writes":[],"reply":"第一句。'],['引号\\"和反斜线\\\\。"}'],True)
  task=asyncio.create_task(self.w.turn('普通聊天，说两句话。'))
  await self.wait_text('第一句。');self.assertFalse(task.done());p['gate'].set();r=await task
  self.assertEqual(r['speech'],'第一句。引号"和反斜线\\。');self.assertEqual(r['assistant_history'],[r['speech']]);self.assertEqual(len(self.requests),1)
 async def test_truncation_after_speech_stops_continuation(self):
  self.plan(['{"mode":"chat","steps":[],"authorized_writes":[],"reply":"第一句。'])
  # A repair may be requested, but a closed output cannot replay a replacement.
  self.plan(['{"mode":"chat","steps":[],"authorized_writes":[],"reply":"替换整段回复。"}'])
  r=await self.w.turn('普通聊天，说两句话。')
  self.assertEqual(r['speech'],'第一句。后续回复中断了。');self.assertNotIn('替换',r['speech']);self.assertEqual([e['type'] for e in r['events']],['FIRST','MIDDLE','MIDDLE','LAST'])
 async def test_write_waits_for_full_validated_decision(self):
  self.w.c._full_tool_harness.fast_decision=lambda *a:None
  p=self.plan(['{"mode":"operate","steps":[{"id":"s","tool":"self_audio_speaker_set_volume","arguments":{"volume":30}}],"authorized_writes":[],'],['"reply":""}'],True)
  self.plan(['{"mode":"chat","steps":[],"authorized_writes":[],"reply":"音量已调到30。"}'])
  task=asyncio.create_task(self.w.turn('把音量调到三十。'))
  await asyncio.to_thread(p['sent'].wait,4);await asyncio.sleep(.05)
  self.assertFalse(self.w.device.calls);self.assertFalse(self.w.events);p['gate'].set();r=await task
  self.assertEqual(self.w.device.state['volume'],30);self.assertEqual(len([c for c in r['calls'] if c['tool']=='self_audio_speaker_set_volume']),1)
 async def test_new_request_does_not_receive_old_stream(self):
  p=self.plan(['{"mode":"chat","steps":[],"authorized_writes":[],"reply":"旧的第一句。'],['旧的后半句。"}'],True)
  self.plan(['{"mode":"chat","steps":[],"authorized_writes":[],"reply":"新的回答。"}'])
  actor=self.w.c.person_turn
  first=asyncio.create_task(asyncio.to_thread(self.w.c.chat,'聊聊第一件事',_identity=actor))
  await self.wait_text('旧的第一句。')
  second=asyncio.create_task(asyncio.to_thread(self.w.c.chat,'现在换个话题',_identity=actor))
  await asyncio.sleep(.08);p['gate'].set();await asyncio.gather(first,second)
  text=''.join(e['text'] for e in self.w.events);self.assertEqual(text,'旧的第一句。新的回答。')
  history=[m.content for m in self.w.c.dialogue.dialogue if m.role=='assistant' and m.content]
  self.assertEqual(history[-2:],['旧的第一句。','新的回答。'])
 async def test_random_chat_cannot_speak_before_receipt(self):
  self.w.c._full_tool_harness.fast_decision=lambda *a:None
  p=self.plan(['{"mode":"chat","steps":[],"authorized_writes":[],"reply":"掷出了四点。'],['"}'],True)
  self.plan(['{"mode":"retrieve","retrieval_query":"随机掷骰子","steps":[],"authorized_writes":[],"reply":""}'])
  self.plan(['{"mode":"operate","steps":[{"id":"r","tool":"random_decision","arguments":{"mode":"dice"}}],"authorized_writes":[],"reply":""}'])
  self.plan(['{"mode":"chat","steps":[],"authorized_writes":[],"reply":"骰子结果请以本次查询结果为准。"}'])
  task=asyncio.create_task(self.w.turn('给我掷一次骰子。'))
  await asyncio.to_thread(p['sent'].wait,4);await asyncio.sleep(.05)
  self.assertFalse(self.w.events,'unverified random result streamed before validation')
  p['gate'].set();r=await task
  self.assertTrue(any(x['tool']=='random_decision' for x in r['outcome']['results']),r['outcome'])
  self.assertNotIn('掷出了四点',r['speech'])
 async def test_public_task_survives_chat_and_time_variant(self):
  self.w.c._full_tool_harness.fast_decision=lambda *a:None
  self.plan([json.dumps({'mode':'clarify','steps':[],'authorized_writes':[],'task_update':{'target_tool':'add_reminder','parameters':{'text':'取编号42包裹','content':'取编号42包裹'},'missing_fields':['remind_time_str']},'reply':'什么时候取四十二个包裹？'},ensure_ascii=False)])
  first=await self.w.turn('先帮大家记一个定时事项，内容是取编号42包裹')
  self.assertEqual(first['speech'],'想在什么时候提醒？')
  created=self.w.c._full_tool_harness.task.created
  self.plan(['{"mode":"clarify","steps":[],"task_action":"resume","authorized_writes":[],"reply":"路上安静挺难得的。不过包裹什么时候取？没定时间我可记不住。"}'])
  second=await self.w.turn('今天路上挺安静')
  self.assertEqual(second['speech'],'路上安静挺难得的。')
  self.assertEqual(self.w.c._full_tool_harness.task.created,created)
  self.assertEqual(self.w.c._full_tool_harness.task.supplements,{})
  self.plan([json.dumps({'mode':'operate','steps':[{'id':'a','tool':'add_reminder','arguments':{'text':'取错包裹','content':'取错包裹','remind_time_str':5}}],'authorized_writes':['add_reminder'],'reply':''},ensure_ascii=False)])
  self.plan(['{"mode":"retrieve","retrieval_query":"创建事项提醒","steps":[],"authorized_writes":[],"reply":""}'])
  self.plan([json.dumps({'mode':'operate','steps':[{'id':'a','tool':'add_reminder','arguments':{'text':'取编号42包裹','content':'取编号42包裹','remind_time_str':'五分钟后'}}],'authorized_writes':['add_reminder'],'reply':''},ensure_ascii=False)])
  self.plan(['{"mode":"chat","steps":[],"authorized_writes":[],"reply":"公共提醒已设好，五分钟后提醒大家取编号42包裹。"}'])
  last=await self.w.turn('接着刚才的事项，五分钟以后')
  calls=[c for c in last['calls'] if c['tool']=='note_add']
  self.assertEqual(len(calls),1,last['outcome'])
  self.assertEqual(calls[0]['arguments']['recipient_person_id'],'all')
  self.assertEqual(calls[0]['arguments']['text'],'取编号42包裹')
 async def test_deictic_query_reads_new_device_state(self):
  self.w.c._full_tool_harness.fast_decision=lambda *a:None
  self.plan(['{"mode":"operate","steps":[{"id":"v","tool":"self_audio_speaker_set_volume","arguments":{"volume":25}}],"authorized_writes":["self_audio_speaker_set_volume"],"reply":""}'])
  self.plan(['{"mode":"chat","steps":[],"authorized_writes":[],"reply":"音量已调到25。"}'])
  first=await self.w.turn('音量改到25')
  self.assertEqual(self.w.device.state['volume'],25)
  self.w.device.state['volume']=31;self.w.device.save()
  self.plan(['{"mode":"chat","steps":[],"authorized_writes":[],"reply":"当前音量31，亮度三档。"}'])
  latest=await self.w.turn('查询一下目前两个设置')
  self.assertTrue(any(r['tool']=='self_get_device_status' for r in latest['outcome']['results']))
  self.assertIn('31',latest['speech'])
  self.assertFalse(any(c['tool']=='self_audio_speaker_set_volume' for c in latest['calls']))

if __name__=='__main__':unittest.main(verbosity=2)
