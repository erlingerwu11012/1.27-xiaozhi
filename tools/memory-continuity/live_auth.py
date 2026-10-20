"""One user-authorized synthetic fact for the newly bound member, via One API.

Credentials are resolved only in server memory. The persisted report contains
the synthetic test fact and non-sensitive status, never keys or user IDs.
"""
from pathlib import Path
import base64
import hashlib
import hmac
import json
import os
import secrets
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

mode = "continuity"
root = Path('/root/prjs/tmp/memory-continuity-release-20260930')
root.mkdir(mode=0o700, exist_ok=True)
report_path = root / 'result.json'
target = json.loads((Path('/root/prjs/tmp/memory-test-20260930') / 'target.json').read_text())
assert target['device_id'].lower() == 'ac:a7:04:fd:20:2c'
assert target['memory'] == 'Memory_bailian'
assert len(target['voice_members']) == 1
account = int(target['account_id'])
member = target['voice_members'][0]
person = member['person_id']
mysql = ['docker', 'exec', '-i', 'xiaozhi-esp32-server-db', 'sh', '-c',
         'exec env MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --user=root --batch --raw --skip-column-names']

def sql(query):
    return subprocess.run(mysql, input=query, text=True, capture_output=True,
                          check=True).stdout.strip()

def http(method, url, headers, body=None, timeout=20):
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())

service_secret = sql("SELECT param_value FROM xiaozhi_esp32_server.sys_params "
                     "WHERE param_code='server.secret';")
manager_headers = {'Authorization': 'Bearer ' + service_secret,
                   'Content-Type': 'application/json'}
code, envelope = http('GET', 'http://127.0.0.1:8002/xiaozhi/user-identities/internal/state/'
                      + str(account), manager_headers)
assert code == 200 and envelope.get('code') == 0
state = envelope['data']
assert state['mode'] == 'personal' and state['default_user_id'] is None
profiles = state.get('voice_profiles') or []
assert any(p.get('user_id') == person and p.get('voiceprint_id') == member['voiceprint_id']
           for p in profiles)
assert len(state.get('cleanup_tasks') or []) == 0, 'cleanup_still_pending'
binding = json.loads(sql('SELECT JSON_OBJECT(\'owner\',oneapi_user_id,\'cipher\','
                         'oneapi_token_key_cipher,\'fingerprint\',oneapi_token_key_fingerprint) '
                         'FROM xiaozhi_esp32_server.sys_user_oneapi_binding WHERE sys_user_id=%d;' % account))
owner = int(binding['owner'])
pm = json.loads(subprocess.run(['pm2', 'jlist'], capture_output=True,
                               text=True, check=True).stdout)
pid = next(item['pid'] for item in pm if item['name'] == 'manager-api')
env = dict(item.decode().split('=', 1) for item in
           Path('/proc/%d/environ' % pid).read_bytes().split(b'\0') if b'=' in item)
assert env.get('MEMORY_PRODUCT_ENABLED') == 'true' and env.get('MEMORY_PORTRAIT_ENABLED') == 'false'
encrypted = base64.b64decode(binding['cipher'])
token = AESGCM(bytes.fromhex(env['ONEAPI_TOKEN_CIPHER_KEY'])).decrypt(
    encrypted[:12], encrypted[12:], None).decode()
assert hashlib.sha256(token.encode()).hexdigest() == binding['fingerprint']
if not token.startswith('sk-'):
    token = 'sk-' + token
gateway_env = {}
for line in Path('/etc/one-api-bailian.env').read_text().splitlines():
    if line.strip() and not line.lstrip().startswith('#'):
        key, value = shlex.split(line)[0].split('=', 1)
        gateway_env[key] = value
signature_secret = gateway_env['BAILIAN_MEMORY_SERVICE_SECRET'].encode()

def gateway(method, path, body=None, idem=None, timeout=20):
    expiry = str(int(time.time()) + 120)
    canonical = '\n'.join(['memory-v1', str(owner), str(account), person, '0', expiry])
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json',
               'X-Memory-Account': str(account), 'X-Memory-Person': person,
               'X-Memory-Generation': '0', 'X-Memory-Expires': expiry,
               'X-Memory-Signature': hmac.new(signature_secret, canonical.encode(),
                                               hashlib.sha256).hexdigest(),
               'X-Memory-Strategy': 'lite'}
    if idem:
        headers['Idempotency-Key'] = idem
    return http(method, 'https://api.realecho.cn/bailian/api/v2/apps/memory/' + path,
                headers, body, timeout)

def save(report):
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    os.chmod(report_path, 0o600)
