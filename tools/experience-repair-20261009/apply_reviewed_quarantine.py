from pathlib import Path
import json,sys,time
S=Path('/root/prjs/tmp/experience-repair-20261009');B=Path('/root/prjs/releases/experience-repair-20261009/backup');sys.path.insert(0,str(S))
from memory_quarantine import connect,write,change
from budget import Budget
original=B/'memory-review-private.json';approved=B/'memory-review-approved-private.json';journal=B/'memory-quarantine-journal-private.json'
d=json.loads(original.read_text());assert len(d['records'])==4
for r in d['records']:
 assert r['table']=='ai_person_material' and r['reason'] in {'retrieval_wrapper_in_tool_result','retrieval_wrapper_in_dialogue_assistant'}
 assert r['account_id'] and r['person_id'] and r['agent_id']
 r['approved']=True;r['review_basis']='retrieval wrapper in tool_result or dialogue_assistant; not user factual material'
write(approved,d)
with connect(False) as db:
 n=change(db,approved,journal)
 with db.cursor() as c:
  for r in d['records']:
   c.execute('SELECT recall_allowed FROM ai_person_material WHERE id=%s',(r['id'],));assert c.fetchone()['recall_allowed']==0
Budget(S/'budget.sqlite3').reserve('case','deployment-recall-quarantine-verification')
summary={'quarantined':n,'source_kinds':['tool_result','dialogue_assistant'],'raw_records_deleted':0,'user_fact_records_changed':0,'reversible':True,'journal_private':str(journal),'at':time.time()};(S/'production-recall-quarantine-summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary))
