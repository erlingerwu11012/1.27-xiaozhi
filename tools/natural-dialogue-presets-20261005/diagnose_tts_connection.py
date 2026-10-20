"""Print protocol codes only; never credentials, customer inputs or raw logs."""
import asyncio,json,os,subprocess,uuid,time
from collections import Counter
from pathlib import Path
os.environ['CANDIDATE_RUNTIME']='1'
source=Path(__file__).with_name('runtime_production_acceptance.py').read_text().split('async def runtime_mcp():')[0]
exec(compile(source,'<bootstrap>','exec'));provider.client.close()
audio_source=Path('/root/prjs/tmp/natural-dialogue-20261003/live_chain_acceptance.py').read_text()
segment=audio_source[audio_source.index('async def synthesize('):audio_source.index('async def voice_test():')]
segment=segment.replace("msg=json.loads(chunk);event=msg.get('header',{}).get('event')", "msg=json.loads(chunk);event=msg.get('header',{}).get('event'); protocol(msg)")
def protocol(msg):
 import re
 codes={}
 def collect(obj,prefix=''):
  if not isinstance(obj,dict):return
  for key,value in obj.items():
   if key in ('code','error_code','type','event'):
    if isinstance(value,(int,float)) or (isinstance(value,str) and re.fullmatch('[A-Za-z0-9_.:-]{1,64}',value) and not value.startswith('sk-')):
     codes[prefix+key]=value
   elif isinstance(value,dict):collect(value,prefix+key+'.')
 collect(msg)
 print(json.dumps({'root_keys':list(msg),'protocol_codes':codes}),flush=True)
exec(compile(segment,'<tts-protocol>','exec'))
async def run():
 cfg=model_config('TTS_QwenAudioTTSPlus')
 if os.environ.get('TTS_EXISTING_TEST_CREDENTIAL')=='1':cfg['api_key']=llm['api_key']
 for text in ['语音连接测试。','东京当地时间是2026年10月6日，00点21分。','上海当地时间是2026年10月5日，23点21分。']:
  try:
   pcm,first=await asyncio.wait_for(synthesize(cfg,text),45)
   print(json.dumps({'test_text':text,'ok':True,'pcm_bytes':len(pcm),'first_ms':first}),flush=True)
  except Exception as error:
   print(json.dumps({'test_text':text,'ok':False,'type':type(error).__name__,'close_code':getattr(error,'code',None)}),flush=True)
asyncio.run(run())
