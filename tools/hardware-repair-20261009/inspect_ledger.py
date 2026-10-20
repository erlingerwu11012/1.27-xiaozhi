from pathlib import Path
import json,sqlite3,hashlib
S=Path(__file__).parent;p=Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server/data/harness/operations.sqlite3')
with sqlite3.connect('file:'+str(p)+'?mode=ro',uri=True) as d:
 tables=d.execute('SELECT name FROM sqlite_master WHERE type=\'table\'').fetchall();print('ledger_tables',[x[0] for x in tables]);print('existing_duplicate_groups',d.execute('SELECT COUNT(*) FROM (SELECT 1 FROM dispatch GROUP BY scope,turn,fingerprint HAVING COUNT(*)>1)').fetchone()[0]);print('dispatch_states',dict(d.execute('SELECT state,count(*) FROM dispatch GROUP BY state')))
print('ledger_permissions',oct(p.stat().st_mode&0o777));print('firmware_package_sha256',hashlib.sha256(Path('/root/prjs/tmp/hardware-repair-20261009/manager-api/target/xiaozhi-esp32-api.jar').read_bytes()).hexdigest()[:16])
