from pathlib import Path
import json,gzip
S=Path('/root/prjs/tmp/hardware-followup-20261013');old=Path('/root/prjs/tmp/harness-stream-20261011')
for d in [old/'predeploy-backup02',old/'deployment29-private',S/'predeploy-backup02']:
 print('backup',str(d),d.exists(),[(p.name,p.stat().st_size) for p in d.glob('*') if p.name.endswith(('.json','.gz'))])
 if (d/'manifest.json').exists():
  m=json.loads((d/'manifest.json').read_text());print('manifest-fields',list(m),'restore_database',m.get('restore_database'))
 p=d/'database.sql.gz'
 if p.exists():
  found={}
  with gzip.open(p,'rt') as f:
   for line in f:
    if line.startswith('INSERT INTO `ai_'):
     table=line.split('`')[1]
     if table in ['ai_person_material','ai_memory_override','ai_agent_chat_history']:found[table]=found.get(table,0)+len(line)
  print('memory-table-insert-bytes',found)
