from pathlib import Path
p=Path('tools/hardware-repair-20261009/release.py');s=p.read_text(encoding='utf-8')
s=s.replace("s['phase']='observing';s['deployed_at']=time.time();save(s)","s['phase']='observing';s['deployed_at']=time.time();s['log_offsets']={p:Path(p).stat().st_size if Path(p).exists() else 0 for a in [app(i) for i in s['new'].values()] for p in [a['pm2_env'].get('pm_out_log_path'),a['pm2_env'].get('pm_err_log_path')] if p};save(s)")
needle="def observe():\n";insert='''def inspect_new_logs(s):
 counts={'tracebacks':0,'severe_failures':0,'reply_fallbacks':0,'identity_blocked':0,'harness_receipts':0};critical=[]
 for name,offset in s.get('log_offsets',{}).items():
  p=Path(name)
  if not p.exists():continue
  with p.open('rb') as f:
   if p.stat().st_size<offset:offset=0
   f.seek(offset);chunk=f.read(2*1024*1024);s['log_offsets'][name]=f.tell()
  text=chunk.decode(errors='replace');counts['tracebacks']+=text.count('Traceback (most recent call last)');counts['reply_fallbacks']+=text.count('harness.reply_fallback');counts['identity_blocked']+=text.count('identity_unconfirmed');counts['harness_receipts']+=text.count('harness.receipt')
  for pattern in ['MemoryError','Fatal Python error','Address already in use','OutOfMemoryError','memory_query_unrequested_write_executed','harness.false_success','harness.unauthorized_write','harness.duplicate_dispatch']:
   if pattern in text:critical.append(pattern);counts['severe_failures']+=text.count(pattern)
 return {'counts':counts,'critical':sorted(set(critical))}

''';s=s.replace(needle,insert+needle,1)
s=s.replace("checks=asyncio.run(old.health(**PORTS,public=True));meta=metadata(s);ok=", "checks=asyncio.run(old.health(**PORTS,public=True));meta=metadata(s);logs=inspect_new_logs(s);ok=not logs['critical'] and ")
s=s.replace("'checks':checks,'metadata':meta}","'checks':checks,'metadata':meta,'logs':logs}")
s=s.replace("if time.time()>=s['deployed_at']+1800:break", "save(s)\n  if time.time()>=s['deployed_at']+1800:break")
p.write_text(s,encoding='utf-8')
