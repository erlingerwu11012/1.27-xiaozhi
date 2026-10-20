"""Additive migration. Backup schema and records stays private on the server."""
import json, os, sys
from pathlib import Path
import pymysql
sys.path.insert(0,'/root/prjs/xiaozhi_mcp_gateway')
from core.db_config import DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME
stage=Path(__file__).parent
db=pymysql.connect(host=DB_HOST,port=DB_PORT,user=DB_USER,password=DB_PASSWORD,database=DB_NAME,charset='utf8mb4',cursorclass=pymysql.cursors.DictCursor)
with db.cursor() as c:
    c.execute('SHOW CREATE TABLE sys_habits'); schema=c.fetchone()
    c.execute('SELECT * FROM sys_habits'); rows=c.fetchall()
    backup=stage/'private-backup/habits-before.json'
    if not backup.exists():
        backup.write_text(json.dumps({'schema':schema,'rows':rows},ensure_ascii=False,default=str,indent=2));os.chmod(backup,0o600)
    c.execute('SHOW COLUMNS FROM sys_habits');columns={r['Field'] for r in c.fetchall()}
    added={
        'recipient_person_id':'VARCHAR(64) NULL', 'recipient_display_name':'VARCHAR(96) NULL',
        'sync_state':"VARCHAR(32) NOT NULL DEFAULT 'needs_binding'", 'sync_error':'VARCHAR(64) NULL',
        'content_hash':'CHAR(64) NULL','device_rule_id':'INT NULL',
        'config_version':'BIGINT NOT NULL DEFAULT 1', 'synced_at':'DATETIME NULL'}
    for name,definition in added.items():
        if name not in columns:c.execute('ALTER TABLE sys_habits ADD COLUMN '+name+' '+definition)
    if 'sync_state' not in columns:
        # Legacy HTTP-only success is untrusted. Never guess recipients/account/device.
        c.execute("UPDATE sys_habits SET synced=0,sync_state='needs_binding',sync_error='legacy_unverified'")
    db.commit()
    c.execute('SELECT sync_state,COUNT(*) AS count FROM sys_habits GROUP BY sync_state')
    print(json.dumps({'backup_saved':True,'old_records':len(rows),'states':c.fetchall()},default=str))
db.close()
