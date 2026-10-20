"""Create only this run's isolated API/database/cache; never switch production."""
from pathlib import Path
import json,os,shutil,subprocess,tarfile
S=Path(__file__).resolve().parent
assert S==Path('/root/prjs/tmp/hardware-followup-20261013')
OLD=Path('/root/prjs/tmp/harness-stream-20261011')
with tarfile.open(S/'candidate-source.tgz') as archive:
    for member in archive.getmembers():
        assert (S/member.name).resolve().is_relative_to(S)
    archive.extractall(S,members=[m for m in archive.getmembers() if m.name!='budget.sqlite3' or not (S/'budget.sqlite3').exists()],filter='data')
from budget import Budget
budget=Budget(S/'budget.sqlite3')
charge=budget.reserve('case','isolated-environment-prepare-v2')
env=json.loads((OLD/'private-test-env.json').read_text())
source_db=env['PERSON_MEMORY_TEST_DATABASE']
assert source_db.startswith('bailian_memory_test_')
database='bailian_memory_test_followup20261013'
import pymysql
with pymysql.connect(host='127.0.0.1',user='root',password=env['PERSON_MEMORY_TEST_PASSWORD'],autocommit=True) as db:
    with db.cursor() as c:
        c.execute('SHOW DATABASES LIKE %s',(database,))
        exists=c.fetchone()
        if not (S/'isolated-db-ready.json').exists():
            if exists:c.execute('DROP DATABASE '+database)
            c.execute('CREATE DATABASE '+database+' CHARACTER SET utf8mb4');exists=None
if not exists:
    private_env=dict(os.environ,MYSQL_PWD=env['PERSON_MEMORY_TEST_PASSWORD'])
    dump=subprocess.Popen(['mysqldump','--set-gtid-purged=OFF','--single-transaction','--skip-lock-tables','--no-tablespaces','-h','127.0.0.1','-u','root',source_db],env=private_env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    restore=subprocess.run(['mysql','-h','127.0.0.1','-u','root',database],env=private_env,stdin=dump.stdout,capture_output=True)
    dump.stdout.close();dump.wait()
    if restore.returncode or dump.returncode:
        (S/'clone-error-private.log').write_bytes(restore.stderr+dump.stderr.read());(S/'clone-error-private.log').chmod(0o600)
        budget.finish(charge,{'error':'isolated_clone_failed'});raise RuntimeError('isolated_clone_failed')
    (S/'isolated-db-ready.json').write_text(json.dumps({'database':database,'source':'previous isolated test database'}))
env['PERSON_MEMORY_TEST_DATABASE']=database
(S/'private-test-env.json').write_text(json.dumps(env));(S/'private-test-env.json').chmod(0o600)
shutil.copy2(OLD/'api-test-secret',S/'api-test-secret');(S/'api-test-secret').chmod(0o600)
J=S/'manager-api'
if not J.exists():shutil.copytree(OLD/'manager-api',J,ignore=shutil.ignore_patterns('target','logs','data','.git','manager-api.log'))
for path in (S/'java').rglob('*.java'):
    target=J/'src/main/java/xiaozhi/modules'/path.relative_to(S/'java')
    target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
budget.finish(charge,{'status':'isolated_sources_database_ready'})
print('isolated_sources_database_ready',flush=True)
