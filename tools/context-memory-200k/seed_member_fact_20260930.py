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

mode = sys.argv[1]
root = Path('/root/prjs/tmp/member-memory-test-20260930')
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
    return http(method, 'http://127.0.0.1:3011/bailian/api/v2/apps/memory/' + path,
                headers, body, timeout)

def save(report):
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    os.chmod(report_path, 0o600)

fact = '【虚构测试信息】我的书房测试小台灯叫晨星灯，放在书房书桌右侧。'
question = '我书房的测试小台灯叫什么，放在哪里？'

if mode == 'preflight':
    code, data = gateway('GET', 'memory_nodes?page_size=100&page_num=1')
    assert code == 200
    assert data.get('total') == 0, 'member_has_existing_cloud_facts'
    assert not report_path.exists(), 'test_already_started'
    print(json.dumps({'member_scope_verified': True, 'cleanup_complete': True,
                      'portrait_disabled': True, 'cloud_fact_count': data['total'],
                      'test_fact': fact, 'test_question': question}, ensure_ascii=False))
elif mode == 'start':
    assert not report_path.exists(), 'test_already_started'
    code, data = gateway('GET', 'memory_nodes?page_size=100&page_num=1')
    assert code == 200 and data.get('total') == 0, 'member_has_existing_cloud_facts'
    report = {'state': 'prepared', 'test_fact': fact, 'test_question': question,
              'idempotency': 'member-test-20260930-' + secrets.token_hex(8)}
    save(report)  # Unknown responses must not cause a blind second Add.
    code, data = gateway('POST', 'add-async',
                         {'messages': [{'role': 'user', 'content': fact}]},
                         report['idempotency'], timeout=90)
    report['http_status'] = code
    if code != 200 or not data.get('event_id'):
        report['state'] = 'unknown'
        save(report)
        raise RuntimeError('add_result_unknown_no_resubmission')
    report['event_id'] = data['event_id']
    report['state'] = 'accepted'
    save(report)
    print(json.dumps({'state': 'accepted', 'test_fact': fact,
                      'test_question': question}, ensure_ascii=False))
elif mode == 'verify':
    report = json.loads(report_path.read_text())
    assert report['state'] in ('accepted', 'complete'), 'add_not_confirmed'
    code, data = gateway('GET', 'events/' + report['event_id'])
    assert code == 200
    def statuses(value):
        if isinstance(value, list):
            return [state for item in value for state in statuses(item)]
        if isinstance(value, dict):
            current = [value['status']] if isinstance(value.get('status'), str) else []
            return current + [state for key in ('events', 'event') if key in value
                              for state in statuses(value[key])]
        return []
    states = statuses(data)
    if any(value in ('FAILED', 'UNRECORDED') for value in states):
        report['state'] = 'failed'
        save(report)
        raise RuntimeError('upstream_extraction_failed')
    if not states or not all(value == 'SUCCEEDED' for value in states):
        print(json.dumps({'state': 'pending', 'event_states': states}))
        sys.exit(0)
    report['state'] = 'complete'
    save(report)
    code, facts = gateway('GET', 'memory_nodes?page_size=100&page_num=1')
    assert code == 200
    texts = [str(item.get('content') or item.get('custom_content') or '')
             for item in facts.get('memory_nodes', [])]
    stored = any('晨星灯' in text for text in texts)
    code, found = gateway('POST', 'memory_nodes/search',
                          {'messages': [{'role': 'user', 'content': question}],
                           'top_k': 5, 'plan_version': 'lite'},
                          report['idempotency'] + '-search')
    assert code == 200
    recalled = any('晨星灯' in str(item.get('content') or item.get('custom_content') or '')
                   for item in found.get('memory_nodes', []))
    actor = {'account_id': account, 'person_id': person, 'generation': 0,
             'directory_version': int(state['directory_version']),
             'device_id': target['device_id'], 'agent_id': target['agent_id'],
             'status': 'matched', 'mode': 'personal',
             'voiceprint_id': member['voiceprint_id'],
             'template_version': int(member['template_version']),
             'turn_id': report['idempotency'] + '-service', 'listen_epoch': 1,
             'captured_at': int(time.time() * 1000)}
    code, service = http('POST',
        'http://127.0.0.1:8002/xiaozhi/person-memory/internal/search',
        manager_headers, {'actor': actor, 'query': question}, timeout=5)
    service_recalled = (code == 200 and service.get('code') == 0 and
                        '晨星灯' in str((service.get('data') or {}).get('text') or ''))
    report.update(cloud_fact_count=facts.get('total'), stored_expected_fact=stored,
                  recalled_expected_fact=recalled, service_recalled_expected_fact=service_recalled,
                  service_http_status=code, service_api_code=service.get('code'))
    save(report)
    print(json.dumps({'state': 'complete', 'cloud_fact_count': facts.get('total'),
                      'stored_expected_fact': stored, 'recalled_expected_fact': recalled,
                      'service_recalled_expected_fact': service_recalled,
                      'test_fact': fact, 'test_question': question}, ensure_ascii=False))
else:
    raise ValueError('use preflight, start, or verify')
