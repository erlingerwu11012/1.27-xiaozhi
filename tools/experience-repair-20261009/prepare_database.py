import importlib.util,json,os,subprocess,re
from pathlib import Path
import pymysql
STAGE=Path('/root/prjs/tmp/experience-repair-20261009');DB='bailian_memory_test_experience_20261009'
spec=importlib.util.spec_from_file_location('private_db','/root/prjs/xiaozhi_mcp_gateway/core/db_config.py');cfg=importlib.util.module_from_spec(spec);spec.loader.exec_module(cfg)
assert DB!=cfg.DB_NAME and DB.startswith('bailian_memory_test_')
db=pymysql.connect(host=cfg.DB_HOST,port=cfg.DB_PORT,user=cfg.DB_USER,password=cfg.DB_PASSWORD)
with db.cursor() as c:c.execute('CREATE DATABASE IF NOT EXISTS `'+DB+'` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci')
db.close()
flag=STAGE/'isolated-db-ready.json'
if not flag.exists():
    schema=Path('/root/prjs/releases/experience-repair-20261009/backup/schema.sql').read_bytes()
    schema=re.sub(rb'SET\s+@@GLOBAL\.[\s\S]*?;',b'',schema,flags=re.I)
    if b'@@GLOBAL' in schema:raise RuntimeError('global_statement_in_schema')
    if b'USE `' in schema or b'CREATE DATABASE' in schema:raise RuntimeError('unexpected_dump_scope')
    proc=subprocess.run(['mysql','-h',cfg.DB_HOST,'-P',str(cfg.DB_PORT),'-u',cfg.DB_USER,DB],input=schema,env=dict(os.environ,MYSQL_PWD=cfg.DB_PASSWORD),capture_output=True)
    if proc.returncode:raise RuntimeError('isolated_schema_import_failed:'+proc.stderr.decode(errors='replace')[:700])
    db=pymysql.connect(host=cfg.DB_HOST,port=cfg.DB_PORT,user=cfg.DB_USER,password=cfg.DB_PASSWORD,database=DB)
    with db.cursor() as c:c.execute('ALTER TABLE ai_person_material ADD COLUMN recall_allowed BOOLEAN NOT NULL DEFAULT TRUE')
    db.commit();db.close();flag.write_text(json.dumps({'database':DB,'production_database_touched':False}))
# Only the isolated schema is available to the database test harness.
env=dict(os.environ,PERSON_MEMORY_TEST_DATABASE=DB,PERSON_MEMORY_TEST_PASSWORD=cfg.DB_PASSWORD)
(STAGE/'private-test-env.json').write_text(json.dumps({k:env[k] for k in ['PERSON_MEMORY_TEST_DATABASE','PERSON_MEMORY_TEST_PASSWORD']}));os.chmod(STAGE/'private-test-env.json',0o600)
print(json.dumps({'database':DB,'production_writes':False}))
