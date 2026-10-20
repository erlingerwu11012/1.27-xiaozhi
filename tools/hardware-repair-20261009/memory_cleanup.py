"""Reversible cleanup of derived memory only; raw conversations retained."""
from pathlib import Path
import json,hashlib,importlib.util,re,sys,os
S=Path(__file__).parent
spec=importlib.util.spec_from_file_location('memory_policy',S/'work/core/utils/tool_harness/memory_policy.py');policy=importlib.util.module_from_spec(spec);spec.loader.exec_module(policy)
def classify(text):
 text=str(text or '');fact=policy.normalize_fact(text)
 if any(x in text for x in ['[本轮可信','[来源:','[来源：','"tool_calls"','"verified_results"']):return ('delete_derived','retrieval_or_tool_pollution',None)
 if text.lstrip().startswith('{'):
  try:r=json.loads(text)
  except (ValueError,TypeError):return None
  if isinstance(r,dict) and 'content' in r:
   if r.get('role')=='assistant':return ('delete_derived','assistant_content',None)
   if fact and fact!=text:return ('normalize','wrapped_user_fact',fact)
   if re.search(r'什么|啥|[？?]|为什么|怎么|能不能',str(r.get('content',''))):return ('delete_derived','wrapped_question',None)
 if re.search(r'(?:我|你).{0,15}(?:喜欢|爱喝|爱吃).{0,8}(?:什么|啥)|[？?]$',text):return ('delete_derived','question_not_fact',None)
 return None

def connect():
 spec=importlib.util.spec_from_file_location('release','/root/prjs/releases/experience-repair-20261009/release.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m.db()
def scan():
 records=[]
 with connect() as db:
  with db.cursor() as c:
   c.execute('SELECT id,account_id,user_id,generation,agent_id,content,recall_allowed FROM ai_person_material')
   for row in c.fetchall():
    action=classify(row[5])
    if action:records.append({'id':row[0],'account_id':row[1],'user_id':row[2],'generation':row[3],'agent_id':row[4],'original_content':row[5],'recall_allowed':row[6],'sha256':hashlib.sha256(row[5].encode()).hexdigest(),'action':action[0],'reason':action[1],'replacement':action[2]})
 p=S/'memory-cleanup-review-private.json';p.write_text(json.dumps({'records':records},ensure_ascii=False,indent=2,default=str));os.chmod(p,0o600)
 counts={a:sum(x['action']==a for x in records) for a in ['normalize','delete_derived']};(S/'memory-cleanup-scan-summary.json').write_text(json.dumps({'records':len(records),'counts':counts,'applied':False,'raw_chat_deleted':0},indent=2));print(json.dumps(counts))
def apply():
 records=json.loads((S/'memory-cleanup-review-private.json').read_text())['records'];journal=S/'memory-cleanup-journal-private.json'
 if journal.exists():raise RuntimeError('journal_exists')
 # Database dump is taken by deployment before this transaction.
 with connect() as db:
  db.autocommit(False)
  try:
   with db.cursor() as c:
    for r in records:
     c.execute('SELECT account_id,user_id,generation,agent_id,content FROM ai_person_material WHERE id=%s FOR UPDATE',(r['id'],));now=c.fetchone()
     if not now or list(map(str,now[:4]))!=list(map(str,[r['account_id'],r['user_id'],r['generation'],r['agent_id']])) or hashlib.sha256(now[4].encode()).hexdigest()!=r['sha256']:raise RuntimeError('memory_record_drift')
     if r['action']=='normalize':c.execute('UPDATE ai_person_material SET content=%s WHERE id=%s',(r['replacement'],r['id']))
     else:c.execute('DELETE FROM ai_person_material WHERE id=%s',(r['id'],))
    journal.write_text(json.dumps({'status':'prepared','records':records},ensure_ascii=False,indent=2));os.chmod(journal,0o600)
   db.commit();d=json.loads(journal.read_text());d['status']='committed';journal.write_text(json.dumps(d,ensure_ascii=False,indent=2));os.chmod(journal,0o600)
  except Exception:db.rollback();raise
 print(json.dumps({'applied':len(records),'raw_chat_deleted':0}))
if __name__=='__main__':scan() if sys.argv[1]=='scan' else apply()
