from pathlib import Path
import json,pymysql,time
s=Path('/root/prjs/tmp/hardware-followup-20261013');e=json.loads((s/'private-test-env.json').read_text())
with pymysql.connect(host='127.0.0.1',user='root',password=e['PERSON_MEMORY_TEST_PASSWORD'],cursorclass=pymysql.cursors.DictCursor) as db:
 with db.cursor() as c:
  c.execute('SELECT trx_id,trx_state,trx_started,trx_mysql_thread_id,trx_query FROM information_schema.innodb_trx')
  rows=c.fetchall()
  print('active_transactions',[dict(id=x['trx_id'],state=x['trx_state'],started=str(x['trx_started']),thread=x['trx_mysql_thread_id'],query_kind=(x['trx_query'] or '').split(' ',1)[0]) for x in rows])
  c.execute('SELECT ID,USER,HOST,DB,COMMAND,TIME,STATE,INFO FROM information_schema.PROCESSLIST WHERE COMMAND<>\'Sleep\' OR TIME>60')
  rows=c.fetchall()
  print('processes',[dict(thread=x['ID'],host=x['HOST'],database=x['DB'],command=x['COMMAND'],age=x['TIME'],state=x['STATE'],query_kind=(x['INFO'] or '').split(' ',1)[0]) for x in rows if x['DB'] or x['COMMAND']!='Sleep'])
  c.execute('SELECT REQUESTING_THREAD_ID,BLOCKING_THREAD_ID,REQUESTING_ENGINE_TRANSACTION_ID,BLOCKING_ENGINE_TRANSACTION_ID FROM performance_schema.data_lock_waits');print('waits',c.fetchall())
