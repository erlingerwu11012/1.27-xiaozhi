"""Exercise the deployed recent->cloud route for the scoped synthetic fact.

Does not print any returned archive or cloud content; incurs one Search.
"""
from pathlib import Path
import asyncio
import json
import subprocess
import time
import types

from core.utils.person_identity import PersonTurn, activate, deactivate
from core.utils.recent_memory import search
from core.providers.memory.bailian.bailian import MemoryProvider

target = json.loads((Path('/root/prjs/tmp/memory-test-20260930') / 'target.json').read_text())
assert target['state']['mode'] == 'personal' and len(target['voice_members']) == 1
member = target['voice_members'][0]
account = str(target['account_id'])
mysql = ['docker', 'exec', '-i', 'xiaozhi-esp32-server-db', 'sh', '-c',
         'exec env MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --user=root --batch --raw --skip-column-names']
secret = subprocess.run(mysql,
    input="SELECT param_value FROM xiaozhi_esp32_server.sys_params WHERE param_code='server.secret';",
    text=True, capture_output=True, check=True).stdout.strip()
version = int(subprocess.run(mysql,
    input='SELECT directory_version FROM xiaozhi_esp32_server.ai_account_identity_state WHERE account_id=%s;' % account,
    text=True, capture_output=True, check=True).stdout.strip())
actor = PersonTurn(account, member['person_id'], 0, version, 'personal', 'matched',
                   'member_route_probe_20260930', target['device_id'], target['agent_id'],
                   1, member['voiceprint_id'], int(member['template_version']), '',
                   int(time.time() * 1000))
conn = types.SimpleNamespace(config={
    'manager-api': {'url': 'http://127.0.0.1:8002', 'secret': secret},
    'sys_user_id': account, 'agent_id': target['agent_id']})
conn.memory = MemoryProvider({'search_timeout_seconds': 1})

async def main():
    token = activate(conn, actor)
    try:
        started = time.monotonic()
        result = await search(conn, '我书房的测试小台灯叫什么，放在哪里？')
        elapsed = round((time.monotonic() - started) * 1000)
    finally:
        deactivate(token)
    text = str(result.get('text') or '')
    print(json.dumps({'status': result.get('status'), 'source': result.get('source'),
                      'contains_expected_test_fact': '晨星灯' in text,
                      'elapsed_ms': elapsed}, ensure_ascii=False))

asyncio.run(main())
