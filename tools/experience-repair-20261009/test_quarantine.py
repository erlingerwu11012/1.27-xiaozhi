import json,uuid
from pathlib import Path
from memory_quarantine import connect,scan,change,write
from budget import Budget
S=Path(__file__).parent;b=Budget(S/'budget.sqlite3');report=S/'quarantine-test-private.json';journal=S/'quarantine-test-journal.json'
with connect(True) as d:
 with d.cursor() as c:
  c.execute("INSERT INTO ai_agent_chat_history(mac_address,agent_id,session_id,chat_type,content,account_id,person_id,identity_status,turn_id,event_id,directory_version,default_generation,recall_allowed,created_at) VALUES('QUARANTINE-TEST','agent_http','audit',1,%s,99001,'audit-only','default',%s,%s,1,0,TRUE,NOW())",('[本轮可信记忆检索] 我喜欢咖啡',uuid.uuid4().hex,uuid.uuid4().hex));key=c.lastrowid
 d.commit()
 try:
  b.reserve('case','audit-private-scan');scan(d,report);j=json.loads(report.read_text());j['records']=[r for r in j['records'] if r['table']=='ai_agent_chat_history' and r['id']==key];assert len(j['records'])==1
  b.reserve('case','audit-unreviewed-no-change');write(report,j);assert change(d,report,journal)==0
  b.reserve('case','audit-approved-reversible-isolation');j['records'][0]['approved']=True;write(report,j);assert change(d,report,journal)==1
  with d.cursor() as c:c.execute('SELECT recall_allowed,content FROM ai_agent_chat_history WHERE id=%s',(key,));r=c.fetchone();assert r['recall_allowed']==0 and '咖啡' in r['content']
  b.reserve('case','audit-restore-original');assert change(d,journal,S/'quarantine-test-restore.json',True)==1
  with d.cursor() as c:c.execute('SELECT recall_allowed FROM ai_agent_chat_history WHERE id=%s',(key,));assert c.fetchone()['recall_allowed']==1
 finally:
  with d.cursor() as c:c.execute('DELETE FROM ai_agent_chat_history WHERE id=%s AND mac_address=%s',(key,'QUARANTINE-TEST'))
  d.commit()
print('private audit reversible PASS',b.report())
