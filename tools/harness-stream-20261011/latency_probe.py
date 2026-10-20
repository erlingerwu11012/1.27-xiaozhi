import argparse,os
cli=argparse.ArgumentParser();cli.add_argument('--phase',choices=['baseline','candidate','repair'],required=True);cli.add_argument('--name',required=True);cli.add_argument('--audio',type=int,default=0);cli.add_argument('--final',action='store_true');cli.add_argument('--exclusive',action='store_true');opt=cli.parse_args()
os.environ['TEST_PHASE']=opt.phase
if opt.final:os.environ['MODEL_TEST_PHASE']='final'
if opt.phase=='baseline':os.environ['CANDIDATE_WORK']='/root/prjs/tmp/harness-stream-20261011/baseline-work'
import bootstrap,asyncio,json,time,uuid,wave,hashlib,statistics
if opt.exclusive:
 from pathlib import Path
 for proc in Path('/proc').iterdir():
  if not proc.name.isdigit() or int(proc.name)==os.getpid():continue
  try:args=(proc/'cmdline').read_bytes().split(b'\0')
  except (FileNotFoundError,PermissionError,ProcessLookupError):continue
  assert not any(Path(a.decode(errors='ignore')).name in {'tool_coverage.py','run_dialogues.py','retrieval_probe.py','latency_probe.py'} for a in args),'exclusive_latency_blocked_by_paid_test'
from bootstrap import stage,budget,production_provider
from wire_conversation import WireConversation
from core.utils.reminder_interaction import close_interaction
from core.providers.tts.qwen_audio_tts_plus import TTSProvider,build_run_task,build_continue_task,build_finish_task,freeze_snapshot

QUERIES=[
 '用两三句话说说雨天在窗边看书的感觉，不用给我建议，也别提问。',
 '我只是随便聊聊，用两三句话说说热咖啡和冰咖啡口感有什么不同。',
 '我刚把桌子收拾干净，用两三句普通话接着聊，别替我安排下一步。',
 '用两三句话给我讲讲为什么傍晚的光看起来柔和，别开玩笑。',
 '我今天重听了一张老唱片，你用两三句话说说老歌为什么容易让人想起以前。',
 '我喜欢安静一点的房间，用两三句自然地聊聊这种感觉，不用建议。',
 '用两三句话解释一下为什么面包烤过以后会更香，不要太专业。',
 '这次认真说，用两三句话解释为什么运动后会觉得口渴。',
 '我最近在看一本很慢的小说，用两三句说说慢故事的趣味，别反问。',
 '给我两三句话解释树叶为什么会在秋天变黄，日常聊天的语气。',
 '我刚收到朋友寄的明信片，用两三句普通的话聊聊纸质信件的感觉。',
 '用两三句话说说现场音乐和耳机听歌的不同，别给我推荐东西。',
 '把声音设为四十','给我查查当前音量','把屏幕亮度设为三档','今晚十点半设个闹钟',
 '保存一条不定时便签，内容是买洗衣液','列出所有便签','把音量再提高十个点','查一下我有哪些闹钟'
]

class AudioProbe:
 def __init__(self,provider,started,label):
  self.provider,self.started,self.label=provider,started,label;self.q=asyncio.Queue();self.audio=bytearray();self.first_audio=None;self.first_text=None;self.ws=None
 async def run(self):
  fragment=await self.q.get()
  self.first_text=time.monotonic()-self.started
  charge=budget.reserve('tts',self.label)
  try:
   p=self.provider;snapshot=dict(freeze_snapshot(p._config_snapshot));snapshot['format']='pcm';snapshot.pop('bit_rate',None);snapshot['sample_rate']=p.sample_rate
   task_id=str(uuid.uuid4());self.ws=await p._connect(p.ws_url,p._auth_header())
   await self.ws.send(json.dumps(build_run_task(task_id,snapshot)))
   async def receive():
    async for message in self.ws:
     if isinstance(message,(bytes,bytearray)):
      if self.first_audio is None:self.first_audio=time.monotonic()-self.started
      self.audio.extend(message);continue
     data=json.loads(message);header=data.get('header',{});event=header.get('event')
     if header.get('task_id')!=task_id:raise RuntimeError('tts_unpaired_receipt')
     if event=='task-started':ready.set()
     elif event=='task-failed':raise RuntimeError('tts_failed')
     elif event=='task-finished':return
   ready=asyncio.Event();reader=asyncio.create_task(receive());await asyncio.wait_for(ready.wait(),15)
   while fragment is not None:
    await self.ws.send(json.dumps(build_continue_task(task_id,fragment)))
    fragment=await self.q.get()
   await self.ws.send(json.dumps(build_finish_task(task_id)));await asyncio.wait_for(reader,25)
   assert self.first_audio is not None and len(self.audio)>1000
   path=stage/(self.label+'.wav')
   with wave.open(str(path),'wb') as f:f.setnchannels(1);f.setsampwidth(2);f.setframerate(p.sample_rate);f.writeframes(self.audio)
   meta={'first_audio_seconds':self.first_audio,'first_text_seconds':self.first_text,'bytes':len(self.audio),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
   budget.finish(charge,meta);return meta
  except Exception as exc:budget.finish(charge,{'error':type(exc).__name__});raise
  finally:
   if self.ws:await self.ws.close()

async def main():
 out=stage/(opt.name+'-latency.jsonl');assert not out.exists()
 for i,query in enumerate(QUERIES):
  charge=budget.reserve('case',opt.name+':'+str(i));provider,cfg=production_provider();w=await WireConversation().setup(provider,cfg)
  close_interaction(w.c);w.device.state['card']['active']=False;w.device.save()
  started=time.monotonic();audio=None;audio_task=None;tts=None
  if i<opt.audio:
   config=cfg['TTS'][cfg['selected_module']['TTS']];assert config.get('official_billing')=='customer_device_token'
   tts=TTSProvider(config,True);audio=AudioProbe(tts,started,opt.name+'-audio-'+str(i));audio_task=asyncio.create_task(audio.run());original=w.c.enqueue_tts;loop=asyncio.get_running_loop()
   def enqueue(dto):
    original(dto)
    if dto.content_type.name=='TEXT':loop.call_soon_threadsafe(audio.q.put_nowait,str(dto.content_detail or ''))
   w.c.enqueue_tts=enqueue
  try:
   record=await w.turn(query);record['index']=i;record['phase']=opt.phase;record['total_seconds']=time.monotonic()-started
   text_events=[e for e in record['events'] if e['content_type']=='TEXT'];record['first_text_seconds']=text_events[0]['elapsed_seconds'] if text_events else None
   if audio:
    await audio.q.put(None);record['real_audio']=await asyncio.wait_for(audio_task,45)
   budget.finish(charge,{'total_seconds':record['total_seconds'],'first_text_seconds':record['first_text_seconds']})
   with out.open('a') as f:f.write(json.dumps(record,ensure_ascii=False,default=str)+'\n')
   print(json.dumps({'i':i,'first_text':record['first_text_seconds'],'total':record['total_seconds'],'audio':record.get('real_audio'),'speech':record['speech']},ensure_ascii=False),flush=True)
  finally:
   if audio_task and not audio_task.done():audio_task.cancel()
   if tts:await tts.close()
   await w.close();provider.client.close()
 print(json.dumps(budget.report()),flush=True)
asyncio.run(main())
