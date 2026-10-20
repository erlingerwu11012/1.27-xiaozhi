from pathlib import Path
import sys,json,pymysql
s=Path('/root/prjs/tmp/hardware-followup-20261013');e=json.loads((s/'private-test-env.json').read_text())
with pymysql.connect(host='127.0.0.1',user='root',password=e['PERSON_MEMORY_TEST_PASSWORD'],database=e['PERSON_MEMORY_TEST_DATABASE']) as d:
 with d.cursor() as c:
  c.execute("SHOW TABLES LIKE '%role%'");tables=[x[0] for x in c.fetchall()];print('tables',tables)
  for name in tables:
   if 'deploy_task' in name or name.endswith('role_pack'):
    c.execute('DESCRIBE '+name);print(name,[(x[0],x[1],x[2],x[4]) for x in c.fetchall()])
