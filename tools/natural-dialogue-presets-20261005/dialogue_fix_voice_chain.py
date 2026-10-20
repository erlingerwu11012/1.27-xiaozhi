"""Synthetic PCM -> real ASR -> actual chat handler -> live MCP -> official TTS.

No physical microphone, device connection, customer memory or hardware writes.
"""
import asyncio,json,os,re,time,wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
os.environ['CANDIDATE_RUNTIME']='1'
source=Path(__file__).with_name('runtime_production_acceptance.py').read_text().split('async def runtime_mcp():')[0]
exec(compile(source,'<voice-bootstrap>','exec'));provider.client.close()
audio_source=Path('/root/prjs/tmp/natural-dialogue-20261003/live_chain_acceptance.py').read_text()
exec(compile(audio_source[audio_source.index('async def synthesize('):audio_source.index('async def voice_test():')],'<official-tts>','exec'))
from test_primary_answer_direct_tts import PrimaryAnswerDirectTtsTests
from test_qwen3_asr_realtime import FakeConn
from core.providers.asr.qwen3_asr_realtime import ASRProvider
from core.utils.utterance_state import request_stop
from core.utils.prompt_pipeline import is_pipeline_v2
from core.utils.dialogue import Message
from core.providers.tts.dto.dto import ContentType
from plugins_func.register import Action,ActionResponse

MODEL=os.environ.get('ACCEPTANCE_MODEL','qwen3.8-max')
result={'source':'real ASR and TTS with synthetic recordings; actual candidate ConnectionHandler and live read-only MCP',
 'physical_voice_test':False,'hardware_writes':0,'secondary_rewrite':False,'model':MODEL,'cases':[],
 'limits':{'tts_calls':10,'asr_sessions':5,'chat_turns':5},'completed':False}
asr_cfg=model_config(base['selected_module']['ASR']);tts_cfg=model_config('TTS_QwenAudioTTSPlus')
result['providers']={'asr_model':asr_cfg.get('model_name'),'tts_model':tts_cfg.get('model')}
def save(): (OUT/'dialogue-fix-voice-chain.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
def wav(path,data):
 with wave.open(str(path),'wb') as f:f.setnchannels(1);f.setsampwidth(2);f.setframerate(16000);f.writeframes(data)

async def transcribe(text):
 audio,first=await asyncio.wait_for(synthesize(tts_cfg,text),45)
 c=FakeConn(asyncio.get_running_loop());c.session_id='synthetic-chain';done=asyncio.Future()
 p=ASRProvider(asr_cfg,True)
 async def capture(conn,frames,final_text=None,**kwargs):
  if not done.done():done.set_result(final_text)
 p.handle_voice_stop=capture
 try:
  await p.open_audio_channels(c);await p.receive_audio(c,audio[:1920],True)
  for _ in range(160):
   if p._current and p._current.state=='RUNNING':break
   await asyncio.sleep(.05)
  assert p._current and p._current.state=='RUNNING','asr_not_ready'
  for off in range(1920,len(audio),1920):
   await p.receive_audio(c,audio[off:off+1920],True);await asyncio.sleep(.06)
  request_stop(c,'device_stop');await p.stop_listening(c)
  return await asyncio.wait_for(done,20)
 finally:await p.close()

async def run():
 test=PrimaryAnswerDirectTtsTests();test.setUpClass();test.setUp()
 h=test.handler();h.config['operation_control']={'enabled':True};h.actor.key=('synthetic','voice',1)
 h.dialogue.update_system_message(PromptManager({'system_base_prompt':base.get('system_base_prompt',''),'language':'中文'},logger=MagicMock()).build_enhanced_prompt_v2(PERSONA,'synthetic-voice',device_name='小智',user_nickname='主人',official_enhanced=True))
 h.llm=LLMProvider(dict(llm,model_name=MODEL,timeout=40,max_tokens=350));h.llm.client=h.llm.client.with_options(max_retries=0)
 settings=json.loads((PROD/'data/.mcp_server_settings.json').read_text())['mcpServers']
 client=ServerMCPClient(next(c for c in settings.values() if not c.get('disabled',False)))
 tool_events=[]
 try:
  await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(client.initialize(),h.loop))
  definitions=client.get_available_tools()
  executor=ServerMCPExecutor(h);executor._initialized=True
  executor.mcp_manager=SimpleNamespace(get_all_tools=lambda:definitions,execute_tool=client.call_tool)
  manager=ToolManager(h);manager.register_executor(ToolType.SERVER_MCP,executor)
  async def handler(conn,call):
   if call['name'] not in {'get_world_time','mcp_get_world_time'}:
    return ActionResponse(action=Action.RESPONSE,response='本次隔离验收未授权这个操作，工具未执行。')
   receipt=await manager.execute_tool(call['name'],json.loads(call['arguments']))
   tool_events.append({'name':call['name'],'arguments':json.loads(call['arguments']),'receipt':receipt.result,'action':receipt.action.name})
   return receipt
  h.func_handler=SimpleNamespace(tool_manager=manager,handle_llm_function_call=handler,get_functions=lambda:definitions)
  samples=['刚买了个书架，还没发货，我就是随便聊聊，别替我安排。',
           '成年人的朋友为什么越来越难约？别反问我，说说你的看法。',
           '查询伦敦现在的时间','查询东京现在的时间','查询上海现在的时间']
  for index,text in enumerate(samples,1):
   check_budget();row={'turn':index,'input_text':text};result['cases'].append(row)
   try:
    transcript=await transcribe(text);row['asr_text']=transcript;assert transcript,'asr_empty'
    h.tts_events.clear();tool_events.clear()
    before=sum(m.role=='assistant' and not m.tool_calls for m in h.dialogue.dialogue)
    ok=await asyncio.to_thread(lambda:h.chat(transcript,_identity=h.actor))
    spoken=''.join(str(e.content_detail) for e in h.tts_events if e.content_type==ContentType.TEXT)
    row.update(chat_success=bool(ok),spoken_text=spoken,tool_events=list(tool_events),tts_events=len(h.tts_events))
    assert spoken,'spoken_text_empty'
    if index>=3:
     assert len(tool_events)==1 and tool_events[0]['name']=='get_world_time','time_tool_not_executed'
     row['time_reply_matches_receipt']=bool(re.search(r'(\d{2}):(\d{2}):',tool_events[0]['receipt']) and re.search(r'(\d{2}):(\d{2}):',tool_events[0]['receipt']).group(1)+'点'+re.search(r'(\d{2}):(\d{2}):',tool_events[0]['receipt']).group(2)+'分' in spoken)
     assert row['time_reply_matches_receipt'],'wrong_time_transcription'
    audio,first=await asyncio.wait_for(synthesize(tts_cfg,spoken),45)
    filename=f'dialogue-fix-voice-{index}.wav';wav(OUT/filename,audio)
    row.update(reply_audio_file=filename,reply_audio_ms=round(len(audio)/32),tts_first_audio_ms=first,success=True)
   except Exception as e:
    row.update(success=False,error_type=type(e).__name__,error_code=str(e) if re.fullmatch('[a-z_]+',str(e)) else 'redacted_failure')
   save();print(json.dumps(row,ensure_ascii=False),flush=True)
 finally:
  await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(client.cleanup(),h.loop))
  h.llm.client.close();test.doCleanups();test.tearDownClass()
 result['completed']=len(result['cases'])==5 and all(c.get('success') for c in result['cases']);save()
asyncio.run(run())
