"""Scope derived-memory cleanup to the test-device owner; full-row reversible journal."""
from pathlib import Path
import hashlib,importlib.util,json,os,re,sys,time
S=Path(__file__).parent
spec=importlib.util.spec_from_file_location('cleanup_policy',S/'memory_cleanup.py');policy=importlib.util.module_from_spec(spec);spec.loader.exec_module(policy)
spec=importlib.util.spec_from_file_location('previous_release','/root/prjs/releases/experience-repair-20261009/release.py');release=importlib.util.module_from_spec(spec);spec.loader.exec_module(release)
def dump(x):return json.dumps(x,ensure_ascii=False,sort_keys=True,default=str)
def digest(row):return hashlib.sha256(dump(row).encode()).hexdigest()
def write(p,obj):release.atomic(p,json.dumps(obj,ensure_ascii=False,indent=2,default=str).encode(),0o600)
def scan_and_restore_test():
 with release.db() as d:
  with d.cursor() as c:
   c.execute('SELECT user_id FROM ai_device WHERE mac_address=%s',('ac:a7:04:fd:20:2c',));owners=c.fetchall();assert len(owners)==1 and owners[0][0] is not None;account=owners[0][0]
   c.execute('SELECT * FROM ai_person_material WHERE account_id=%s ORDER BY id',(account,));columns=[x[0] for x in c.description];records=[]
   for row in c.fetchall():
    item=dict(zip(columns,row));action=policy.classify(item['content'])
    if action:records.append({'original':item,'hash':digest(item),'action':action[0],'reason':action[1],'replacement':action[2]})
   production_db=d.db.decode() if isinstance(d.db,bytes) else d.db
 assert re.fullmatch(r'[a-zA-Z0-9_]+',production_db)
 review={'created_at':time.time(),'scope_device':'ac:a7:04:fd:20:2c','account_id':account,'columns':columns,'records':records};write(S/'memory-cleanup-scoped-review-private.json',review)
 import pymysql
 e=json.loads((S/'private-test-env.json').read_text());assert e['PERSON_MEMORY_TEST_DATABASE'].startswith('bailian_memory_test_')
 with pymysql.connect(host='127.0.0.1',user='root',password=e['PERSON_MEMORY_TEST_PASSWORD'],database=e['PERSON_MEMORY_TEST_DATABASE'],autocommit=True) as d:
  with d.cursor() as c:
   c.execute('CREATE TEMPORARY TABLE cleanup_restore_probe LIKE `'+production_db+'`.`ai_person_material`')
   names=','.join('`'+x+'`' for x in columns);slots=','.join(['%s']*len(columns))
   for r in records:c.execute('INSERT INTO cleanup_restore_probe ('+names+') VALUES ('+slots+')',tuple(r['original'][x] for x in columns))
   c.execute('SELECT * FROM cleanup_restore_probe ORDER BY id');before=[dict(zip(columns,x)) for x in c.fetchall()];assert [digest(x) for x in before]==[r['hash'] for r in records]
   c.execute('DELETE FROM cleanup_restore_probe')
   # Restore from serialized on-disk journal, not the in-memory source rows.
   saved=json.loads((S/'memory-cleanup-scoped-review-private.json').read_text())
   for r in saved['records']:c.execute('INSERT INTO cleanup_restore_probe ('+names+') VALUES ('+slots+')',tuple(r['original'][x] for x in columns))
   c.execute('SELECT * FROM cleanup_restore_probe ORDER BY id');after=[dict(zip(columns,x)) for x in c.fetchall()];assert [digest(x) for x in before]==[digest(x) for x in after]
 result={'passed':True,'records':len(records),'full_columns':len(columns),'full_row_restore_verified':True,'production_written':False,'raw_chat_deleted':0,'counts':{k:sum(r['action']==k for r in records) for k in ['delete_derived','normalize']}};write(S/'memory-cleanup-restore-test.json',result);print(json.dumps(result))
def apply():
 assert json.loads((S/'resume-release-gate.json').read_text())['passed']
 review=json.loads((S/'memory-cleanup-scoped-review-private.json').read_text());journal=S/'memory-cleanup-scoped-journal-private.json';assert not journal.exists()
 with release.db() as d:
  d.autocommit(False)
  try:
   with d.cursor() as c:
    c.execute('SELECT user_id FROM ai_device WHERE mac_address=%s',('ac:a7:04:fd:20:2c',));assert str(c.fetchone()[0])==str(review['account_id'])
    for r in review['records']:
     row=r['original'];c.execute('SELECT * FROM ai_person_material WHERE id=%s AND account_id=%s FOR UPDATE',(row['id'],review['account_id']));actual=c.fetchone();assert actual and digest(dict(zip(review['columns'],actual)))==r['hash'],'memory drift'
     if r['action']=='normalize':c.execute('UPDATE ai_person_material SET content=%s WHERE id=%s AND account_id=%s',(r['replacement'],row['id'],review['account_id']))
     else:c.execute('DELETE FROM ai_person_material WHERE id=%s AND account_id=%s',(row['id'],review['account_id']))
     assert c.rowcount==1
    write(journal,dict(review,status='prepared'));d.commit();write(journal,dict(review,status='committed'))
   result={'applied':len(review['records']),'raw_chat_deleted':0,'restorable':True,'at':time.time()};write(S/'memory-cleanup-applied.json',result);print(json.dumps(result))
  except Exception:d.rollback();raise

def restore():
 j=json.loads((S/'memory-cleanup-scoped-journal-private.json').read_text());cols=j['columns'];assert all(re.fullmatch(r'[a-z_]+',x) for x in cols)
 with release.db() as d:
  d.autocommit(False)
  try:
   with d.cursor() as c:
    for r in j['records']:
     old=r['original'];c.execute('SELECT * FROM ai_person_material WHERE id=%s FOR UPDATE',(old['id'],));actual=c.fetchone()
     if actual:
      row=dict(zip(cols,actual))
      if digest(row)==r['hash']:continue
      expected=dict(old,content=r['replacement']);assert r['action']=='normalize' and digest(row)==digest(expected),'restore conflict'
      c.execute('UPDATE ai_person_material SET content=%s WHERE id=%s AND account_id=%s',(old['content'],old['id'],j['account_id']))
     else:c.execute('INSERT INTO ai_person_material ('+','.join('`'+x+'`' for x in cols)+') VALUES ('+','.join(['%s']*len(cols))+')',tuple(old[x] for x in cols))
   d.commit();j['status']='restored';write(S/'memory-cleanup-scoped-journal-private.json',j);print('memory cleanup restored')
  except Exception:d.rollback();raise
if __name__=='__main__':
 if sys.argv[1]=='scan':scan_and_restore_test()
 elif sys.argv[1]=='apply':apply()
 elif sys.argv[1]=='restore':restore()
 else:raise ValueError('unknown action')
