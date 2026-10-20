from pathlib import Path
import subprocess,re,json,pymysql,os
s=Path('/root/prjs/tmp/hardware-followup-20261013');e=json.loads((s/'private-test-env.json').read_text())
with pymysql.connect(host='127.0.0.1',user='root',password=e['PERSON_MEMORY_TEST_PASSWORD']) as d:
 with d.cursor() as c:c.execute('SELECT trx_id,trx_state,trx_started,trx_mysql_thread_id,trx_query FROM information_schema.innodb_trx');print('transactions',[(str(a),b,str(t),p,(q or '').split(' ',1)[0]) for a,b,t,p,q in c.fetchall()])
r=subprocess.run(['docker','logs','--since','20m','--tail','100','xiaozhi-esp32-server-db'],capture_output=True,text=True)
for line in (r.stdout+r.stderr).splitlines():
 if re.search('full|space|retry|failed|error',line,re.I):print(line[:260])
v=os.statvfs('/root/prjs');print('available_bytes',v.f_bavail*v.f_frsize)
