import bootstrap,asyncio,json,wave,hashlib
from bootstrap import stage,budget,production_provider
from core.providers.tts.qwen_audio_tts_plus import TTSProvider
async def main():
 _,cfg=production_provider();config=cfg['TTS'][cfg['selected_module']['TTS']]
 assert config.get('official_billing')=='customer_device_token'
 provider=TTSProvider(config,True);records=[]
 rows=[json.loads(x) for x in (stage/'final-results.jsonl').read_text().splitlines()]
 texts=[next(x['speech'] for x in rows if x['case']['id']==i and not x['errors']) for i in ['reg-16','reg-45','new-26']]
 for text in texts:
  budget.reserve('case','real-tts:'+text);charge=budget.reserve('tts','official-customer-voice');path=stage/('audio-'+str(charge)+'.wav')
  try:
   await provider.synthesize_wav_isolated(text,str(path))
   with wave.open(str(path)) as w:record={'text':text,'path':path.name,'frames':w.getnframes(),'sample_rate':w.getframerate(),'duration':w.getnframes()/w.getframerate(),'channels':w.getnchannels(),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
   assert record['frames']>1000 and record['channels']==1
  except Exception as exc:record={'text':text,'error':type(exc).__name__+':'+str(exc)[:100]}
  records.append(record);budget.finish(charge,record);print(json.dumps(record,ensure_ascii=False),flush=True)
 await provider.close();(stage/'real-tts-results.json').write_text(json.dumps(records,ensure_ascii=False,indent=2));print(budget.report())
asyncio.run(main())
