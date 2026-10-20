import pathlib,json,re,subprocess
root=pathlib.Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server')
apps=json.loads(subprocess.check_output(['pm2','jlist'],text=True));a=next(x for x in apps if x['name']=='xiaozhi-server')
p=pathlib.Path(a['pm2_env']['pm_out_log_path'])
with p.open('rb') as f:f.seek(max(0,p.stat().st_size-12000000));lines=f.read().decode(errors='replace').splitlines()
hits=[i for i,l in enumerate(lines) if '识别文本: 看看这是啥' in l]
for i in hits[-3:]:
 for l in lines[max(0,i-5):i+90]:
  if any(t in l for t in ['识别文本','harness.','self_camera_take_photo','vision_capability','MCP call','type=mcp','发送第一段']):print(l[:1300])
print('MATCHING_REQUESTS',len(hits))
counts={}
for p in (root/'logs/trace').glob('*.jsonl'):
 for l in p.open(errors='replace'):
  if 'vision_not_ready' not in l and 'vision_http_' not in l:continue
  try:r=json.loads(l)
  except:continue
  e=r.get('event','');counts[e]=counts.get(e,0)+1
  if e.startswith('harness'):print('VISION_TRACE',r.get('ts'),e,str(r.get('payload'))[:700])
print('VISION_CODE_EVENT_COUNTS',counts)
