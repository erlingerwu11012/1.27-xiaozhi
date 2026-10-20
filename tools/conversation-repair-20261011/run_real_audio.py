import bootstrap,asyncio,json,wave,hashlib
from bootstrap import stage,budget,production_provider
from core.providers.tts.qwen_audio_tts_plus import TTSProvider
async def main():
 llm,cfg=production_provider();llm.client.close();config=cfg['TTS'][cfg['selected_module']['TTS']]
 assert config.get('official_billing')=='customer_device_token'
 provider=TTSProvider(config,True);records=[]
 rows=[json.loads(x) for x in (stage/'final01-results.jsonl').read_text().splitlines()]
 texts=list(dict.fromkeys(x['speech'] for x in rows if not x['errors'] and x.get('speech')))[:3]
 assert len(texts)==3
 for text in texts:
  case=budget.reserve('case','real-tts');charge=budget.reserve('tts','official-customer-voice');path=stage/('audio-'+str(charge)+'.wav')
  try:
   await provider.synthesize_wav_isolated(text,str(path))
   with wave.open(str(path)) as w:record={'text':text,'path':path.name,'frames':w.getnframes(),'sample_rate':w.getframerate(),'duration':w.getnframes()/w.getframerate(),'channels':w.getnchannels(),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
   assert record['frames']>1000 and record['channels']==1
  except Exception as exc:record={'text':text,'error':type(exc).__name__}
  records.append(record);budget.finish(charge,record);budget.finish(case,record);print(json.dumps(record,ensure_ascii=False),flush=True)
 await provider.close();(stage/'real-tts-results.json').write_text(json.dumps(records,ensure_ascii=False,indent=2))
 assert all('error' not in x for x in records)
asyncio.run(main())
