"""Non-content evidence for the member's 03:00 extraction and device tool calls."""
from pathlib import Path
import json
import re
import subprocess

target = json.loads((Path('/root/prjs/tmp/memory-test-20260930') / 'target.json').read_text())
assert target['state']['mode'] == 'personal' and len(target['voice_members']) == 1
account = int(target['account_id'])
person = target['voice_members'][0]['person_id']
mysql = ['docker', 'exec', '-i', 'xiaozhi-esp32-server-db', 'sh', '-c',
         'exec env MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --user=root --batch --raw --skip-column-names']

def sql(query):
    return subprocess.run(mysql, input=query, text=True, capture_output=True,
                          check=True).stdout.strip()

def literal(value):
    return "CONVERT(X'" + str(value).encode().hex() + "' USING utf8mb4)"

scope = 'account_id=%d AND user_id=%s AND generation=0' % (account, literal(person))
tasks = sql('SELECT JSON_OBJECT(\'state\',state,\'kind\',kind,'
            '\'created_at\',DATE_FORMAT(created_at,\'%Y-%m-%d %H:%i:%s\'),'
            '\'event_received\',event_id IS NOT NULL,\'attempts\',attempts) '
            'FROM xiaozhi_esp32_server.ai_memory_task WHERE ' + scope +
            ' ORDER BY created_at DESC LIMIT 4;')
entity = sql('SELECT JSON_OBJECT(\'state\',state,'
             '\'daily_started_at\',DATE_FORMAT(daily_started_at,\'%Y-%m-%d %H:%i:%s\'),'
             '\'watermark_reconciled\',daily_watermark=processed_watermark) '
             'FROM xiaozhi_esp32_server.ai_person_memory_entity WHERE ' + scope + ';')

pm = json.loads(subprocess.run(['pm2', 'jlist'], capture_output=True,
                               text=True, check=True).stdout)
service = next(row for row in pm if row['name'] == 'xiaozhi-server')
times = []
for key in ('pm_out_log_path', 'pm_err_log_path'):
    path = Path(service['pm2_env'].get(key) or '')
    if not path.is_file():
        continue
    for line in path.read_bytes()[-60_000_000:].decode('utf-8', 'replace').splitlines():
        if '执行工具: memory_search' not in line:
            continue
        at = re.search(r'260930 (\d\d:\d\d:\d\d)', line)
        if at and at.group(1) >= '02:30:00':
            times.append(at.group(1))

print(json.dumps({'task_metadata': [json.loads(row) for row in tasks.splitlines() if row],
                  'entity_metadata': json.loads(entity) if entity else None,
                  'memory_search_tool_times_since_0230': sorted(set(times)),
                  'service_status': service['pm2_env'].get('status')}, ensure_ascii=False))
