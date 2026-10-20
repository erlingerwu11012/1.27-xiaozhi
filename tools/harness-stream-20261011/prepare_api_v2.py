"""Apply additive migration and build in a new isolated candidate directory only."""
import os,json,shutil,subprocess
from pathlib import Path
S=Path(__file__).parent;old=Path('/root/prjs/tmp/conversation-repair-20261011/manager-api');new=S/'manager-api'
if not new.exists():shutil.copytree(old,new,ignore=shutil.ignore_patterns('target','logs','data','manager-api.log'))
for file in (S/'java').glob('*.java'):
 destination=new/('src/test/java' if file.name.endswith('Test.java') else 'src/main/java')/'xiaozhi/modules/personmemory'/file.name
 destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(file,destination)
e=json.loads((S/'private-test-env.json').read_text());assert e['PERSON_MEMORY_TEST_DATABASE'].startswith('bailian_memory_test_')
import pymysql
with pymysql.connect(host='127.0.0.1',user='root',password=e['PERSON_MEMORY_TEST_PASSWORD'],database=e['PERSON_MEMORY_TEST_DATABASE'],autocommit=True) as db:
 with db.cursor() as c:
  for name in ('material_cutoff_id','archive_cutoff_id'):
   c.execute('SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name=%s AND column_name=%s',('ai_memory_override',name))
   if c.fetchone()[0]==0:c.execute('ALTER TABLE ai_memory_override ADD COLUMN '+name+' BIGINT NULL')
with (S/'java-v2-build.log').open('w') as out:r=subprocess.run(['mvn','-q','-DskipTests','package'],cwd=new,stdout=out,stderr=subprocess.STDOUT)
print('BUILD_EXIT',r.returncode,flush=True);assert r.returncode==0
