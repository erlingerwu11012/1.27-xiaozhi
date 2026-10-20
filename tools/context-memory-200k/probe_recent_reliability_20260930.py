"""Read-only check whether local archive falsely blocks cloud for test query."""
from pathlib import Path
import json
import subprocess
import time
import urllib.request

target = json.loads((Path('/root/prjs/tmp/memory-test-20260930') / 'target.json').read_text())
member = target['voice_members'][0]
account = str(target['account_id'])
mysql = ['docker', 'exec', '-i', 'xiaozhi-esp32-server-db', 'sh', '-c',
         'exec env MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --user=root --batch --raw --skip-column-names']
secret = subprocess.run(mysql,
    input="SELECT param_value FROM xiaozhi_esp32_server.sys_params WHERE param_code='server.secret';",
    text=True, capture_output=True, check=True).stdout.strip()
actor = {'account_id': account, 'person_id': member['person_id'],
         'generation': 0, 'directory_version': int(target['state']['directory_version']),
         'status': 'matched', 'mode': 'personal', 'device_id': target['device_id'],
         'agent_id': target['agent_id'], 'voiceprint_id': member['voiceprint_id'],
         'template_version': int(member['template_version']),
         'turn_id': 'member_test_recent_probe_20260930', 'listen_epoch': 1,
         'captured_at': int(time.time() * 1000)}
query = '我书房的测试小台灯叫什么，放在哪里？'
request = urllib.request.Request(
    'http://127.0.0.1:8002/xiaozhi/person-memory/internal/recent',
    data=json.dumps({'actor': actor, 'query': query}, ensure_ascii=False).encode(),
    headers={'Authorization': 'Bearer ' + secret, 'Content-Type': 'application/json'},
    method='POST')
with urllib.request.urlopen(request, timeout=5) as response:
    envelope = json.loads(response.read())
result = envelope.get('data') or {}
text = str(result.get('text') or '')
print(json.dumps({'api_code': envelope.get('code'), 'status': result.get('status'),
                  'reliable': result.get('reliable'), 'text_chars': len(text),
                  'contains_cloud_only_test_answer': '晨星灯' in text}, ensure_ascii=False))
