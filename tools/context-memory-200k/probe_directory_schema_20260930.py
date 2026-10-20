"""Read-only production probe of identity directory field types; no personal values."""
from pathlib import Path
import json
import subprocess
import urllib.request

target = json.loads((Path('/root/prjs/tmp/memory-test-20260930') / 'target.json').read_text())
account = str(target['account_id'])
mysql = ['docker', 'exec', '-i', 'xiaozhi-esp32-server-db', 'sh', '-c',
         'exec env MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --user=root --batch --raw --skip-column-names']
secret = subprocess.run(mysql,
    input="SELECT param_value FROM xiaozhi_esp32_server.sys_params WHERE param_code='server.secret';",
    text=True, capture_output=True, check=True).stdout.strip()
req = urllib.request.Request(
    'http://127.0.0.1:8002/xiaozhi/user-identities/internal/state/' + account,
    headers={'Authorization': 'Bearer ' + secret})
with urllib.request.urlopen(req, timeout=8) as response:
    envelope = json.loads(response.read())
state = envelope.get('data') or {}

def field(obj, key):
    value = obj.get(key) if isinstance(obj, dict) else None
    return {'type': type(value).__name__, 'present': key in obj if isinstance(obj, dict) else False,
            'nonempty': bool(value), 'length': len(value) if isinstance(value, list) else None}

keys = ('account_id', 'mode', 'directory_version', 'default_generation',
        'members', 'voice_profiles', 'cleanup_tasks')
schema = {key: field(state, key) for key in keys}
result = {
    'http_api_code': envelope.get('code'),
    'state_fields': schema,
    'first_member_fields': {key: field((state.get('members') or [None])[0], key)
                            for key in ('user_id', 'display_name', 'kind', 'status')},
    'first_voice_fields': {key: field((state.get('voice_profiles') or [None])[0], key)
                           for key in ('voiceprint_id', 'user_id', 'template_version')},
    'first_cleanup_fields': {key: field((state.get('cleanup_tasks') or [None])[0], key)
                             for key in ('id', 'user_id', 'generation', 'directory_version')},
}
print(json.dumps(result, ensure_ascii=False))
