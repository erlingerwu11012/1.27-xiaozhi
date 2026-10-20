import pathlib,json,re,subprocess
root=pathlib.Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server')
apps=json.loads(subprocess.check_output(['pm2','jlist'],text=True));a=next(x for x in apps if x['name']=='xiaozhi-server')
for key in ['pm_out_log_path','pm_err_log_path']:
 p=pathlib.Path(a['pm2_env'][key])
 with p.open('rb') as f:f.seek(max(0,p.stat().st_size-6000000));lines=f.read().decode(errors='replace').splitlines()
 for l in lines:
  if re.search(r'261009 01:20:(?:4[4-9]|5\d)|261009 01:21:0\d',l) and any(t in l for t in ['harness.','大模型收到','listen_start','ERROR','WARNING','LLM','WebSocket close','发送第一段','abort']):print(l[:1800])
for p in (root/'logs/trace').glob('*.jsonl'):
 for l in p.open(errors='replace'):
  if not re.search(r'2026-10-09T01:20:(?:4[4-9]|5\d)|2026-10-09T01:21:0\d',l):continue
  try:r=json.loads(l)
  except:continue
  ev=r.get('event','')
  if any(t in ev for t in ['harness','listen','abort','asr.turn_end','tts.turn','llm']):
   ids=r.get('ids',{});print(json.dumps({'ts':r.get('ts'),'event':ev,'listen_epoch':ids.get('listen_epoch'),'utterance_id':ids.get('utterance_id'),'payload':r.get('payload')},ensure_ascii=False)[:2200])
