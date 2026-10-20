"""Private, reversible recall quarantine. Scan only unless reviewed rows are approved."""
import argparse,hashlib,json,os,importlib.util,datetime
from pathlib import Path
TABLES={'ai_agent_chat_history':('id','person_id','default_generation'),'ai_person_material':('id','user_id','generation')}
MARKERS=('[本轮可信','[来源:','[来源：','"memory_retrieval": true','"memory_retrieval":true')
def suspects(row,table):
 text=str(row.get('content') or '')
 structured=any(x in text for x in MARKERS)
 role=str(row.get('kind') or '') if table=='ai_person_material' else ('user' if row.get('chat_type')==1 else 'assistant')
 return 'retrieval_wrapper_in_'+role if structured else None
def connect(test=False):
 import pymysql
 spec=importlib.util.spec_from_file_location('private_db','/root/prjs/xiaozhi_mcp_gateway/core/db_config.py');cfg=importlib.util.module_from_spec(spec);spec.loader.exec_module(cfg)
 name='bailian_memory_test_experience_20261009' if test else cfg.DB_NAME
 return pymysql.connect(host=cfg.DB_HOST,port=cfg.DB_PORT,user=cfg.DB_USER,password=cfg.DB_PASSWORD,database=name,cursorclass=pymysql.cursors.DictCursor,autocommit=False)
def write(path,data):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(data,ensure_ascii=False,indent=2,default=str));os.chmod(path,0o600)
def scan(db,path):
 out=[]
 with db.cursor() as c:
  c.execute('SELECT NOW() AS t');stamp=str(c.fetchone()['t'])
  for table,(key,person,generation) in TABLES.items():
   c.execute('SELECT COUNT(*) AS n FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name=%s AND column_name=%s',(table,'recall_allowed'))
   has_flag=bool(c.fetchone()['n'])
   c.execute('SELECT * FROM '+table+(' WHERE recall_allowed=TRUE' if has_flag else ''))
   for r in c.fetchall():
    why=suspects(r,table)
    if why:out.append({'table':table,'id':r[key],'account_id':r.get('account_id'),'person_id':r.get(person),'generation':r.get(generation),'agent_id':r.get('agent_id'),'sha256':hashlib.sha256(str(r.get('content') or '').encode()).hexdigest(),'reason':why,'content':r.get('content'),'approved':False})
 write(path,{'created_at':stamp,'review_required':True,'records':out});return len(out)
def change(db,review,journal,restore=False):
 data=json.loads(Path(review).read_text());changed=[]
 try:
  with db.cursor() as c:
   c.execute('SELECT NOW() AS t');stamp=str(c.fetchone()['t'])
   for r in data['records']:
    if not restore and not r.get('approved'):continue
    table=r['table'];assert table in TABLES;key,person,gen=TABLES[table]
    c.execute('SELECT * FROM '+table+' WHERE '+key+'=%s FOR UPDATE',(r['id'],));now=c.fetchone()
    if not now or hashlib.sha256(str(now.get('content') or '').encode()).hexdigest()!=r['sha256']:raise ValueError('record_changed')
    if any(str(now.get(col))!=str(r.get(field)) for col,field in [('account_id','account_id'),(person,'person_id'),(gen,'generation'),('agent_id','agent_id')]):raise ValueError('scope_changed')
    if restore:
     c.execute('SELECT COUNT(*) AS n FROM ai_memory_override WHERE account_id=%s AND user_id=%s AND generation=%s AND created_at>=%s',(r['account_id'],r['person_id'],r['generation'],data['created_at']))
     if c.fetchone()['n']:raise ValueError('later_memory_override_do_not_restore')
    expected=0 if restore else 1
    if int(now['recall_allowed'])!=expected:raise ValueError('recall_state_changed')
    c.execute('UPDATE '+table+' SET recall_allowed=%s WHERE '+key+'=%s',(1 if restore else 0,r['id']));changed.append(r)
   write(journal,{'created_at':stamp,'operation':'restore' if restore else 'quarantine','records':changed,'status':'prepared'})
  db.commit();write(journal,{'created_at':stamp,'operation':'restore' if restore else 'quarantine','records':changed,'status':'committed'});return len(changed)
 except Exception:db.rollback();raise
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('action',choices=['scan','apply','restore']);p.add_argument('--test',action='store_true');p.add_argument('--review',required=True);p.add_argument('--journal');a=p.parse_args()
 with connect(a.test) as db:
  n=scan(db,a.review) if a.action=='scan' else change(db,a.review,a.journal,restore=a.action=='restore')
 print(json.dumps({'operation':a.action,'rows':n,'raw_records_deleted':0,'private_report':str(a.review)}))

