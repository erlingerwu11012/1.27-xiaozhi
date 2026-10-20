import pathlib,json,re
root=pathlib.Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server')
p=root/'logs/trace';print('TRACEFILES',[(x.name,x.stat().st_size) for x in p.glob('*') if x.is_file()])
for x in p.glob('*'):
 if not x.is_file() or x.stat().st_size>60000000:continue
 for line in x.open(errors='replace'):
  if '2026-10-09T01:' not in line and '2026-10-09 01:' not in line:continue
  if not re.search(r'01:(?:09:0[25]|11:1[0-9]|11:2[0-9]|11:3[0-6])',line):continue
  try:r=json.loads(line)
  except:continue
  event=str(r.get('event',''))
  if any(t in event for t in ['harness','llm','tool','mcp','utterance']):
   print(json.dumps(r,ensure_ascii=False)[:4500])
for rel in ['core/utils/audio_ingress.py','core/utils/utterance.py','core/utils/utterance_state.py']:
 p=root/rel
 if p.exists():
  print('SOURCE',rel)
  for i,l in enumerate(p.read_text().splitlines()):
   if 'utterance_id' in l or 'finish_utterance' in l or 'begin_utterance' in l:print(str(i+1)+':'+l)
print('LIVE_RUNTIME_MTIME',(root/'core/utils/tool_harness/runtime.py').stat().st_mtime)
