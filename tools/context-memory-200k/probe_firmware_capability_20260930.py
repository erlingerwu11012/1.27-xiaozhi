"""Read-only capability view for the account owning the user-named device."""
from pathlib import Path
import json,subprocess
target=json.loads((Path('/root/prjs/tmp/memory-test-20260930')/'target.json').read_text())
account=int(target['account_id'])
query="SELECT JSON_OBJECT('mac',d.mac_address,'identity',c.identity_version,'cleanup',c.cleanup_version,'behavior',c.behavior_version,'schedule',c.schedule_version,'firmware',c.firmware_version,'has_capability',c.device_id IS NOT NULL) FROM xiaozhi_esp32_server.ai_device d LEFT JOIN xiaozhi_esp32_server.ai_device_identity_capability c ON c.device_id=d.mac_address AND c.account_id=d.user_id WHERE d.user_id="+str(account)+" ORDER BY d.mac_address;"
cmd=['docker','exec','-i','xiaozhi-esp32-server-db','sh','-c','exec env MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --user=root --batch --raw --skip-column-names']
rows=subprocess.run(cmd,input=query,text=True,capture_output=True,check=True).stdout.splitlines()
print(json.dumps({'devices':[json.loads(row) for row in rows if row]},ensure_ascii=False))
