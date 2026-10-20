"""Private backup and isolated staging. Never change a running service."""
import hashlib, importlib.util, json, os, shutil, sqlite3, subprocess, tarfile, time
from pathlib import Path
ROOT=Path('/root/prjs/xiaozhi-esp32-server/main')
STAGE=Path('/root/prjs/tmp/experience-repair-20261009')
BACKUP=Path('/root/prjs/releases/experience-repair-20261009/backup')
STAGE.mkdir(parents=True,exist_ok=True,mode=0o700);os.chmod(STAGE,0o700)
if not BACKUP.exists():
    BACKUP.mkdir(parents=True,mode=0o700);os.chmod(BACKUP.parent,0o700)
    with tarfile.open(BACKUP/'sources-private.tgz','w:gz') as archive:
        for part in ('xiaozhi-server','manager-api'):
            for path in (ROOT/part).rglob('*'):
                rel=path.relative_to(ROOT)
                if path.is_file() and not set(rel.parts)&{'node_modules','target','__pycache__','.git','logs','tmp','venv'} and path.suffix not in {'.opus','.wav','.mp3','.sqlite3','.db'}:
                    archive.add(path,arcname=str(rel),recursive=False)
    (BACKUP/'pm2-private.json').write_bytes(subprocess.check_output(['pm2','jlist']))
    shutil.copytree('/etc/nginx',BACKUP/'nginx')
    ledger=ROOT/'xiaozhi-server/data/harness/operations.sqlite3'
    if ledger.exists():
        with sqlite3.connect(ledger) as source, sqlite3.connect(BACKUP/'operations.sqlite3') as dest:source.backup(dest)
    spec=importlib.util.spec_from_file_location('private_db','/root/prjs/xiaozhi_mcp_gateway/core/db_config.py')
    cfg=importlib.util.module_from_spec(spec);spec.loader.exec_module(cfg)
    env=dict(os.environ,MYSQL_PWD=cfg.DB_PASSWORD)
    args=['mysqldump','--single-transaction','--skip-lock-tables','--no-tablespaces','-h',cfg.DB_HOST,'-P',str(cfg.DB_PORT),'-u',cfg.DB_USER,cfg.DB_NAME]
    with (BACKUP/'schema.sql').open('wb') as f:subprocess.run(args+['--no-data'],env=env,stdout=f,check=True,stderr=subprocess.PIPE)
    import pymysql
    db=pymysql.connect(host=cfg.DB_HOST,port=cfg.DB_PORT,user=cfg.DB_USER,password=cfg.DB_PASSWORD,database=cfg.DB_NAME)
    with db.cursor() as c:
        c.execute('SHOW TABLES');tables=[r[0] for r in c.fetchall() if r[0].startswith('ai_person_') or r[0]=='ai_agent_chat_history']
    db.close()
    with (BACKUP/'memory-private.sql').open('wb') as f:subprocess.run(args+tables,env=env,stdout=f,check=True,stderr=subprocess.PIPE)
    (BACKUP/'metadata.json').write_text(json.dumps({'created_at':time.time(),'root':str(ROOT),'tables':tables}))
    for p in BACKUP.rglob('*'):os.chmod(p,0o700 if p.is_dir() else 0o600)
WORK=STAGE/'work'
if not WORK.exists():
    shutil.copytree(ROOT/'xiaozhi-server',WORK,ignore=shutil.ignore_patterns('logs','tmp','__pycache__','.git','*.opus','*.wav','*.mp3','*.sqlite3','*.db'))
    shutil.copytree(ROOT/'manager-api',STAGE/'manager-api',ignore=shutil.ignore_patterns('target','.git'))
    manifest={str(p.relative_to(WORK)):hashlib.sha256(p.read_bytes()).hexdigest() for p in WORK.rglob('*') if p.is_file() and p.suffix in {'.py','.yaml','.json'}}
    (STAGE/'baseline.json').write_text(json.dumps(manifest,indent=2))
print(json.dumps({'backup':str(BACKUP),'stage':str(STAGE),'production_modified':False}))
