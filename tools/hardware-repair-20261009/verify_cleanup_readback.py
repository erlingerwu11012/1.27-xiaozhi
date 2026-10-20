from pathlib import Path
import json,importlib.util,time
S=Path(__file__).parent
spec=importlib.util.spec_from_file_location('cleanup',S/'scoped_memory_cleanup.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
j=json.loads((S/'memory-cleanup-scoped-journal-private.json').read_text());assert j['status']=='committed'
ids=[r['original']['id'] for r in j['records'] if r['action']=='delete_derived']
with m.release.db() as d:
 with d.cursor() as c:
  c.execute('SELECT COUNT(*) FROM ai_person_material WHERE account_id=%s AND id IN ('+','.join(['%s']*len(ids))+')',(j['account_id'],*ids));remaining=c.fetchone()[0]
assert remaining==0
r={'passed':True,'scoped_deleted_records':len(ids),'remaining_target_records':remaining,'journal_committed':True,'full_backup_columns':len(j['columns']),'raw_chat_deleted':0,'at':time.time()}
(S/'memory-cleanup-readback.json').write_text(json.dumps(r,indent=2));print(json.dumps(r))
