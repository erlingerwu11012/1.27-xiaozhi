import json,sys,importlib.util,pymysql
from pathlib import Path
S=Path(__file__).parent;e=json.loads((S/'private-test-env.json').read_text())
spec=importlib.util.spec_from_file_location('dbconf','/root/prjs/xiaozhi_mcp_gateway/core/db_config.py');cfg=importlib.util.module_from_spec(spec);spec.loader.exec_module(cfg)
src=pymysql.connect(host=cfg.DB_HOST,port=cfg.DB_PORT,user=cfg.DB_USER,password=cfg.DB_PASSWORD,database=cfg.DB_NAME)
dst=pymysql.connect(host='127.0.0.1',user='root',password=e['PERSON_MEMORY_TEST_PASSWORD'],database=e['PERSON_MEMORY_TEST_DATABASE'],autocommit=True)
assert e['PERSON_MEMORY_TEST_DATABASE']!=cfg.DB_NAME
for table in ['DATABASECHANGELOG','DATABASECHANGELOGLOCK']:
 with src.cursor() as q:q.execute('SELECT * FROM '+table);rows=q.fetchall();columns=[d[0] for d in q.description]
 with dst.cursor() as q:
  q.execute('DELETE FROM '+table)
  if rows:q.executemany('INSERT INTO '+table+'('+','.join('`'+c+'`' for c in columns)+') VALUES('+','.join(['%s']*len(columns))+')',rows)
print('isolated migration metadata copied; production read only')
