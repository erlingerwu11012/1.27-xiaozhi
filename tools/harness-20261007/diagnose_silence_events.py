import pathlib,json,collections,re,hashlib
root=pathlib.Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server')
for x in (root/'logs/trace').glob('*.jsonl'):
 counts=collections.Counter()
 for line in x.open(errors='replace'):
  try:r=json.loads(line)
  except:continue
  ts=r.get('ts','');ev=r.get('event','');pay=r.get('payload',{})
  if '2026-10-09T01:11:1' in ts or '2026-10-09T01:11:2' in ts:counts[ev]+=1
  if '2026-10-09T01:11:' in ts and any(t in ev for t in ['asr.turn','llm','harness','abort','tts.turn']):print(ts,ev,json.dumps(pay,ensure_ascii=False)[:2200])
 print('EVENTS',x.name,dict(counts))
for rel in ['core/utils/tool_harness/runtime.py','core/connection.py']:
 p=root/rel;print('SHA',rel,hashlib.sha256(p.read_bytes()).hexdigest())
# Current trace metadata paths only.
for p in [root/'data/trace_log.flags.json']:
 if p.exists():
  flags=json.loads(p.read_text());print('FLAGS_KEYS',list(flags))
