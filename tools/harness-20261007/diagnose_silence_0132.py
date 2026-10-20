import pathlib,json,re,subprocess
root=pathlib.Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server')
apps=json.loads(subprocess.check_output(['pm2','jlist'],text=True));a=next(x for x in apps if x['name']=='xiaozhi-server')
for key in ['pm_out_log_path','pm_err_log_path']:
 p=pathlib.Path(a['pm2_env'][key])
 with p.open('rb') as f:f.seek(max(0,p.stat().st_size-5000000));lines=f.read().decode(errors='replace').splitlines()
 for l in lines:
  if re.search(r'261009 01:(?:32|33):',l) and any(t in l for t in ['harness.','大模型收到','ERROR','WARNING','LLM 处理','超时','WebSocket close','发送第一段语音','listen_start']):print(l[:1300])
for p in (root/'logs/trace').glob('*.jsonl'):
 for l in p.open(errors='replace'):
  if not re.search(r'2026-10-09T01:32:',l):continue
  try:r=json.loads(l)
  except:continue
  e=r.get('event','')
  if any(t in e for t in ['harness','llm','device.listen','asr.turn_end','asr.emotion_inject']):
   ids=r.get('ids',{});pay=r.get('payload',{})
   if e=='asr.turn_end':pay={k:pay.get(k) for k in ['listen_epoch','utterance_id','outcome','delivered','error']}
   print(json.dumps({'ts':r.get('ts'),'event':e,'epoch':ids.get('listen_epoch'),'uid':ids.get('utterance_id'),'payload':pay},ensure_ascii=False)[:1400])
