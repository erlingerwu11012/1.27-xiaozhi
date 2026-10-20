from pathlib import Path
import gzip,hashlib,json,os,sqlite3,subprocess,sys,tarfile,time,shutil,pymysql
s=Path('/root/prjs/tmp/hardware-followup-20261013');sys.path.insert(0,str(s))
from budget import Budget
b=Budget();charge=b.reserve('case','production-readonly-backup-isolated-restore-01')
d=s/'predeploy-backup01';assert not d.exists();d.mkdir(mode=0o700)
old=Path('/root/prjs/releases/harness-stream-20261012');root=Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server')
assert shutil.disk_usage('/').free>200*1024**2
apps=json.loads(subprocess.check_output(['pm2','jlist']));live={a['name']:a for a in apps if a['name'] in ['xiaozhi-server','manager-api'] and a['pm2_env']['status']=='online'}
assert {a['pm_id'] for a in live.values()}=={9,10}
e=json.loads((s/'private-test-env.json').read_text());pw=e['PERSON_MEMORY_TEST_PASSWORD']
cnf=d/'mysql-private.cnf';cnf.write_text('[client]\nhost=127.0.0.1\nuser=root\npassword="'+pw.replace('\\','\\\\').replace('"','\\"')+'"\n');cnf.chmod(0o600)
production='xiaozhi_esp32_server';restore='bailian_memory_test_restore_followup20261013'
cn=pymysql.connect(host='127.0.0.1',user='root',password=pw,autocommit=True)
with cn.cursor() as c:
 c.execute('SELECT schema_name FROM information_schema.schemata WHERE schema_name=%s',(restore,));assert not c.fetchone()
 c.execute("SELECT table_name FROM information_schema.tables WHERE table_schema=%s AND table_type='BASE TABLE'",(production,));tables=[r[0] for r in c.fetchall()]
 counts={}
 for table in tables:c.execute('SELECT COUNT(*) FROM `'+production+'`.`'+table+'`');counts[table]=c.fetchone()[0]
with (d/'dump-errors.log').open('wb') as err:
 proc=subprocess.Popen(['mysqldump','--defaults-extra-file='+str(cnf),'--set-gtid-purged=OFF','--single-transaction','--hex-blob','--no-tablespaces','--routines','--triggers',production],stdout=subprocess.PIPE,stderr=err)
 with gzip.open(d/'database.sql.gz','wb') as out:
  while chunk:=proc.stdout.read(1024*1024):out.write(chunk)
 assert proc.wait()==0
with cn.cursor() as c:c.execute('CREATE DATABASE `'+restore+'` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci')
with (d/'restore-errors.log').open('wb') as err:
 proc=subprocess.Popen(['mysql','--defaults-extra-file='+str(cnf),restore],stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=err)
 with gzip.open(d/'database.sql.gz','rb') as src:
  while chunk:=src.read(1024*1024):proc.stdin.write(chunk)
 proc.stdin.close();assert proc.wait()==0
with cn.cursor() as c:
 restored={}
 for table in tables:c.execute('SELECT COUNT(*) FROM `'+restore+'`.`'+table+'`');restored[table]=c.fetchone()[0]
 assert all(restored[t]>=counts[t] for t in tables)
 c.execute('SHOW COLUMNS FROM `'+restore+'`.ai_memory_override');columns=[r[0] for r in c.fetchall()]
 assert all(n in columns for n in ['record_id','expected_version','material_cutoff_id','archive_cutoff_id'])
cn.close()
ledger=[]
for src in (root/'data').rglob('*.sqlite3'):
 dest=d/('sqlite-'+str(src.relative_to(root/'data')).replace('/','-'))
 with sqlite3.connect(src) as original,sqlite3.connect(dest) as snapshot:original.backup(snapshot)
 with sqlite3.connect(dest) as snapshot:assert snapshot.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
 ledger.append(dest.name)
# Binary/model rollback originals remain immutable. Back up source/config and
# their binary hashes without copying large model files onto the small disk.
paths=[old/'serve.py',old/'start-manager-api.sh',Path('/etc/nginx/sites-enabled/www.realecho.cn'),Path('/etc/nginx/conf.d/tool-harness-internal.conf'),Path('/root/.pm2/dump.pm2')]
paths += [p for p in (old/'runtime').rglob('*') if p.is_file() and not p.is_symlink() and not any(part in {'models','data','logs','tmp','__pycache__'} for part in p.relative_to(old/'runtime').parts)]
paths += [p for p in (root/'data').glob('*.yaml')]+[p for p in root.glob('*.yaml')]
with tarfile.open(d/'source-config-private.tgz','w:gz') as archive:
 for p in paths:
  if p.exists():archive.add(p,arcname=str(p).lstrip('/'))
(d/'processes-private.json').write_text(json.dumps({'apps':apps,'environments':{name:dict(field.split(b'=',1) for field in (Path('/proc')/str(a['pid'])/'environ').read_bytes().split(b'\0') if b'=' in field) for name,a in []}},default=str))
# Copy process environment as JSON strings, protected locally on the server.
environments={}
for name,a in live.items():
 environments[name]={k.decode():v.decode() for field in (Path('/proc')/str(a['pid'])/'environ').read_bytes().split(b'\0') if b'=' in field for k,v in [field.split(b'=',1)]}
(d/'environments-private.json').write_text(json.dumps(environments))
manifest={'created':time.time(),'restore_passed':True,'restore_database':restore,'table_count':len(tables),'before_counts':counts,'restored_counts':restored,'no_migration_required':True,'existing_columns':columns,'sqlite_snapshots':ledger,'rollback_jar':str(old/'xiaozhi-esp32-api.jar'),'rollback_jar_sha256':hashlib.sha256((old/'xiaozhi-esp32-api.jar').read_bytes()).hexdigest(),'files':{p.name:{'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in d.iterdir() if p.is_file() and p.name!='mysql-private.cnf'},'production_business_writes':0,'model_calls':0}
for p in d.iterdir():
 if p.is_file():p.chmod(0o600)
(d/'manifest.json').write_text(json.dumps(manifest,indent=2));b.finish(charge,{'passed':True,'table_count':len(tables),'sqlite_count':len(ledger)});print(json.dumps({'backup_restore_passed':True,'tables':len(tables),'ledgers':len(ledger),'free_bytes':shutil.disk_usage('/').free}))
