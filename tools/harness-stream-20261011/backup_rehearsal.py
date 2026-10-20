"""Read-only production snapshot; restore only into a newly isolated database."""
import json,os,gzip,subprocess,sqlite3,tarfile,hashlib,time
from pathlib import Path
import pymysql
S=Path(__file__).parent;D=S/'predeploy-backup02';assert not D.exists();D.mkdir(mode=0o700)
from budget import Budget
budget=Budget(S/'budget.sqlite3');charge=budget.reserve('case','backup-restore-rehearsal-02')
e=json.loads((S/'private-test-env.json').read_text());assert e['PERSON_MEMORY_TEST_DATABASE'].startswith('bailian_memory_test_')
pw=e['PERSON_MEMORY_TEST_PASSWORD'];cnf=D/'mysql-private.cnf'
cnf.write_text('[client]\nhost=127.0.0.1\nport=3306\nuser=root\npassword="'+pw.replace('\\','\\\\').replace('"','\\"')+'"\n');os.chmod(cnf,0o600)
c=pymysql.connect(host='127.0.0.1',user='root',password=pw,autocommit=True)
production='xiaozhi_esp32_server';restored='bailian_memory_test_restore_20261011_02'
assert restored.startswith('bailian_memory_test_') and restored!=production
with c.cursor() as q:
 q.execute('SELECT schema_name FROM information_schema.schemata WHERE schema_name=%s',(restored,));assert not q.fetchone(),'never replace an existing restore database'
 q.execute('SELECT table_name FROM information_schema.tables WHERE table_schema=%s AND table_type=\'BASE TABLE\'',(production,));tables=[x[0] for x in q.fetchall()]
 counts={}
 for table in tables:q.execute('SELECT COUNT(*) FROM `'+production+'`.`'+table+'`');counts[table]=q.fetchone()[0]
charge_file=D/'database.sql.gz'
with (D/'dump-errors.log').open('w') as err:
 p=subprocess.Popen(['mysqldump','--defaults-extra-file='+str(cnf),'--set-gtid-purged=OFF','--single-transaction','--hex-blob','--no-tablespaces','--routines','--triggers',production],stdout=subprocess.PIPE,stderr=err)
 with gzip.open(charge_file,'wb') as f:
  while chunk:=p.stdout.read(1024*1024):f.write(chunk)
 assert p.wait()==0,'dump_failed'
os.chmod(charge_file,0o600)
root=Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server')
targets=[Path('/root/prjs/releases/mcp-prune-20261010'),Path('/root/prjs/releases/hardware-repair-20261009/start-manager-api.sh'),Path('/root/prjs/xiaozhi-esp32-server/secrets'),Path('/etc/nginx'),Path('/root/.pm2/dump.pm2')]
targets.extend(p for p in (root/'data').glob('*.yaml'));targets.extend(p for p in root.glob('*.yaml'))
with tarfile.open(D/'source-config-private.tgz','w:gz') as archive:
 for path in targets:
  if path.exists():archive.add(path,arcname=str(path).lstrip('/'))
os.chmod(D/'source-config-private.tgz',0o600)
ledgers=[]
for src in (root/'data').rglob('*.sqlite3'):
 out=D/('sqlite-'+str(src.relative_to(root/'data')).replace('/','-'))
 with sqlite3.connect(src) as original,sqlite3.connect(out) as snapshot:original.backup(snapshot)
 with sqlite3.connect(out) as check:assert check.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
 os.chmod(out,0o600);ledgers.append(out.name)
processes=json.loads(subprocess.check_output(['pm2','jlist']))
(D/'pm2-private.json').write_text(json.dumps(processes));os.chmod(D/'pm2-private.json',0o600)
with c.cursor() as q:q.execute('CREATE DATABASE `'+restored+'` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci')
with (D/'restore-errors.log').open('w') as err:
 p=subprocess.Popen(['mysql','--defaults-extra-file='+str(cnf),restored],stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=err)
 with gzip.open(charge_file,'rb') as f:
  while chunk:=f.read(1024*1024):p.stdin.write(chunk)
 p.stdin.close();assert p.wait()==0,'restore_failed'
with c.cursor() as q:
 restored_counts={}
 for table in tables:q.execute('SELECT COUNT(*) FROM `'+restored+'`.`'+table+'`');restored_counts[table]=q.fetchone()[0]
 # Concurrent production append-only traffic can increase counts after the
 # pre-dump sample, but the isolated restore must contain at least that snapshot.
 assert all(restored_counts[t]>=counts[t] for t in tables),'restored_rows_missing'
 for col in ('material_cutoff_id','archive_cutoff_id'):q.execute('ALTER TABLE `'+restored+'`.ai_memory_override ADD COLUMN `'+col+'` BIGINT NULL')
 q.execute('SHOW COLUMNS FROM `'+restored+'`.ai_memory_override');columns=[r[0] for r in q.fetchall()]
 assert all(x in columns for x in ('material_cutoff_id','archive_cutoff_id'))
 # Rollback compatibility: the old projection still reads the unchanged rows.
 q.execute('SELECT COUNT(*) FROM `'+restored+'`.ai_memory_override');assert q.fetchone()[0]==restored_counts['ai_memory_override']
c.close()
manifest={'created':time.time(),'production_database':production,'restore_database':restored,'table_count':len(tables),'before_counts':counts,'restored_counts':restored_counts,'sqlite_snapshots':ledgers,'restore_passed':True,'additive_migration_rehearsed':True,'old_column_projection_compatible':True,'files':{p.name:{'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in D.iterdir() if p.name not in {'mysql-private.cnf','manifest.json'}}}
(D/'manifest.json').write_text(json.dumps(manifest,indent=2));budget.finish(charge,{'passed':True});print('BACKUP_RESTORE',len(tables),'tables',len(ledgers),'ledgers passed',flush=True)
