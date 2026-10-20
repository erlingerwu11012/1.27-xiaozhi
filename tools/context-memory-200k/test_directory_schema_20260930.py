"""Check the staged protocol adapter against the live directory without printing data."""
from pathlib import Path
import importlib.util
import json
import subprocess
import urllib.request

stage = Path('/root/prjs/tmp/context-memory-release-20260929/directory-schema-20260930')
spec = importlib.util.spec_from_file_location('person_directory_sync_staged', stage / 'person_directory_sync.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

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
    state = json.loads(response.read())['data']
snapshot = module.normalize_directory(state)
assert str(snapshot['account_id']) == account
assert isinstance(snapshot['directory_version'], int) and snapshot['directory_version'] > 0
assert isinstance(snapshot['default_generation'], int)
assert all(isinstance(item['template_version'], int) for item in snapshot['voice_profiles'])
assert all(isinstance(item['generation'], int) and isinstance(item['directory_version'], int)
           for item in snapshot['cleanup_tasks'])
assert all(isinstance(snapshot[key], list) for key in ('members', 'voice_profiles', 'cleanup_tasks'))
assert isinstance(json.loads(json.dumps(snapshot))['directory_version'], int)
assert isinstance(state['directory_version'], str)  # The adapter did not mutate the API response.
for invalid in ('bad', '-1', True, 2**53):
    bad = dict(state, directory_version=invalid)
    try:
        module.normalize_directory(bad)
    except ValueError:
        pass
    else:
        raise AssertionError('invalid version accepted')
print(json.dumps({'schema_matches_firmware': True, 'source_immutable': True,
                  'account_id_preserves_precision': True, 'invalid_versions_rejected': True,
                  'member_count': len(snapshot['members']),
                  'voice_count': len(snapshot['voice_profiles']),
                  'cleanup_count': len(snapshot['cleanup_tasks'])}))
