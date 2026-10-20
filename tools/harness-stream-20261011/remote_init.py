import os,json,shutil,subprocess,importlib.util,hashlib
from pathlib import Path
S=Path(__file__).parent;H=Path('/root/prjs/tmp/hardware-repair-20261009');R=Path('/root/prjs/xiaozhi-esp32-server/main/manager-api')
if not (S/'manager-api').exists():shutil.copytree(R,S/'manager-api',ignore=shutil.ignore_patterns('target','logs','.git','node_modules'))
for name in ['private-test-env.json','api-test-secret']:
 if not (S/name).exists():shutil.copy2(H/name,S/name);(S/name).chmod(0o600)
for name in ['bootstrap.py','wire_conversation.py','stateful_device.py','experience_protocol.py','start_api.py']:
 if not (S/name).exists():shutil.copy2(H/name,S/name)
# Ensure there can be no test accidentally using a live data directory.
assert not (S/'work/data').is_symlink()
spec=importlib.util.spec_from_file_location('db_private','/root/prjs/xiaozhi_mcp_gateway/core/db_config.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
import pymysql
with pymysql.connect(host=m.DB_HOST,port=m.DB_PORT,user=m.DB_USER,password=m.DB_PASSWORD,database=m.DB_NAME) as d:
 with d.cursor() as c:
  c.execute('SHOW TABLES');tables=[r[0] for r in c.fetchall() if r[0].startswith('ai_person_') or r[0] in {'ai_agent_chat_history','ai_memory_override'}]
args=['mysqldump','--single-transaction','--skip-lock-tables','--no-tablespaces','-h',m.DB_HOST,'-P',str(m.DB_PORT),'-u',m.DB_USER,m.DB_NAME]
for name,extra in [('schema.sql',['--no-data']),('memory-private.sql',tables)]:
 p=S/'baseline'/name
 if not p.exists():
  with p.open('wb') as f:r=subprocess.run(args+extra,env=dict(os.environ,MYSQL_PWD=m.DB_PASSWORD),stdout=f,stderr=subprocess.PIPE)
  if r.returncode:raise RuntimeError('database_backup_failed')
  p.chmod(0o600)
print('database_backup_ready',len(tables),'candidate_api_sources_ready')
for p in (S/'java').glob('*.java'):shutil.copy2(p,S/'manager-api/src/main/java/xiaozhi/modules/personmemory'/p.name)
r=subprocess.run(['mvn','-q','-DskipTests','package'],cwd=S/'manager-api',stdout=(S/'java-build.log').open('w'),stderr=subprocess.STDOUT)
print('java_build_exit',r.returncode,flush=True)
if r.returncode:raise SystemExit(r.returncode)
subprocess.run(['/root/miniconda3/envs/xiaozhi-esp32-server/bin/python',str(S/'start_api.py')],check=True)
