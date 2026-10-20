"""Authorized coordinated production release; no model calls or business probes."""
from pathlib import Path
import asyncio
import gzip
import hashlib
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import tarfile
import time

import pymysql
import requests
import websockets
import yaml

STAGE = Path('/root/prjs/tmp/harness-repair-20261017')
ROOT = Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server')
RELEASE = Path('/root/prjs/releases/harness-repair-20261017-r2')
OLD_RUNTIME = Path('/root/prjs/releases/tts-spine-sync-20261013/runtime')
OLD_SERVE = OLD_RUNTIME.parent / 'serve.py'
API_SCRIPT = Path('/root/prjs/releases/harness-followup-20261013/start-manager-api.sh')
STATE = STAGE / 'deployment-r2.json'
PRIVATE = STAGE / 'deployment-private-r2'
MAC = 'ac:a7:04:fd:20:5c'
CHANGES = ['core/providers/tools/device_reminder_adapter.py',
           'core/providers/tools/unified_tool_manager.py', 'core/utils/tool_harness/registry.py',
           'core/utils/tool_harness/reply_composer.py', 'core/utils/tool_harness/runtime.py']


def pm2():
    return json.loads(subprocess.check_output(['pm2', 'jlist']))


def command(args, env=None):
    result = subprocess.run(args, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if result.returncode:
        raise RuntimeError('command_failed:' + args[0])


def process_env(pid):
    return {k.decode(): v.decode() for field in (Path('/proc')/str(pid)/'environ').read_bytes().split(b'\0')
            if b'=' in field for k, v in [field.split(b'=', 1)]}


def save():
    STATE.write_text(json.dumps(state, indent=2))


def database():
    return pymysql.connect(host='127.0.0.1', user='root', password=db_password,
                           database='xiaozhi_esp32_server', cursorclass=pymysql.cursors.DictCursor)


def binding():
    with database() as db:
        with db.cursor() as cursor:
            cursor.execute('SELECT id,user_id,agent_id FROM ai_device WHERE mac_address=%s', (MAC,))
            rows = cursor.fetchall()
            assert len(rows) == 1, 'unexpected_binding'
            return rows[0]


def api_ready():
    try:
        r = requests.post('http://127.0.0.1:18005/xiaozhi/config/server-base',
                          headers={'Authorization': 'Bearer ' + secret}, json={}, timeout=3)
        body = r.json()
        return r.status_code == 200 and body.get('code') == 0 and body.get('data', {}).get('wakeup_words') == ['你好小念']
    except (requests.RequestException, ValueError):
        return False


def ports_ready():
    try:
        for port in [8270, 8273, 8276]:
            with socket.create_connection(('127.0.0.1', port), timeout=.5):
                pass
        return True
    except OSError:
        return False


def wait_ready(fn, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if fn():
            return
        time.sleep(1)
    raise RuntimeError('readiness_timeout')


def find_app(script):
    return next(x for x in pm2() if x['pm2_env'].get('pm_exec_path') == str(script))


assert not STATE.exists() and not RELEASE.exists() and not PRIVATE.exists()
verification = json.loads((STAGE/'verification.json').read_text())
assert verification['python'] == {'tests': 69, 'failures': 0, 'errors': 0, 'skipped': 0}
assert verification['java_totals'] == {'tests': 53, 'failures': 0, 'errors': 0, 'skipped': 0}
manifest = json.loads((STAGE/'manifest.json').read_text())
jar = Path(manifest['api_jar'])
assert hashlib.sha256(jar.read_bytes()).hexdigest() == manifest['api_jar_sha256']
assert shutil.disk_usage('/').free > 1024**3
apps = pm2()
old = {x['name']: x for x in apps if x.get('pm_id') in [11, 13]}
assert set(old) == {'manager-api', 'xiaozhi-server'}
assert all(x['pm2_env']['status'] == 'online' for x in old.values())
assert old['manager-api']['pm2_env']['pm_exec_path'] == str(API_SCRIPT)
assert old['xiaozhi-server']['pm2_env']['pm_exec_path'] == str(OLD_SERVE)
environments = {name: process_env(app['pid']) for name, app in old.items()}
assert all(env.get('XIAOZHI_RELEASE_CANDIDATE') != '1' for env in environments.values())
secret = yaml.safe_load((ROOT/'data/.config.yaml').read_text())['manager-api']['secret']
db_password = json.loads(Path('/root/prjs/tmp/hardware-followup-20261013/private-test-env.json').read_text())['PERSON_MEMORY_TEST_PASSWORD']
assert api_ready()
baseline_binding = binding()
with database() as db:
    with db.cursor() as cursor:
        cursor.execute('SHOW COLUMNS FROM ai_memory_override')
        # Record IDs and expected versions are request/receipt fields. The SQL
        # store uses its numeric id plus content-derived version, not new columns.
        assert {'id', 'material_cutoff_id', 'archive_cutoff_id'} <= {r['Field'] for r in cursor.fetchall()}
with tarfile.open('/tmp/harness-repair-active-source-20261017.tar.gz') as baseline:
    for rel in CHANGES:
        if rel.endswith('device_reminder_adapter.py'):
            assert not (OLD_RUNTIME/rel).exists()
        else:
            assert (OLD_RUNTIME/rel).read_bytes() == baseline.extractfile(rel).read(), 'runtime_changed_since_test:' + rel
config_digest = hashlib.sha256((ROOT/'data/.config.yaml').read_bytes()).hexdigest()
PRIVATE.mkdir(mode=0o700)
(PRIVATE/'pm2-before.json').write_text(json.dumps(apps));(PRIVATE/'pm2-before.json').chmod(0o600)
(PRIVATE/'binding-before.json').write_text(json.dumps(baseline_binding));(PRIVATE/'binding-before.json').chmod(0o600)
for p in [ROOT/'data/.config.yaml', ROOT/'config.yaml', API_SCRIPT, OLD_SERVE]:
    target = PRIVATE/(p.parent.name+'-'+p.name)
    shutil.copy2(p, target);target.chmod(0o600)
state = {'phase': 'backing_up', 'started_at': time.time(), 'release': str(RELEASE),
         'old_ids': {n: x['pm_id'] for n, x in old.items()}, 'new_ids': {},
         'model_calls': 0, 'physical_device_operations': 0, 'schema_migration': False}
save()
print('Fresh production backup starting', flush=True)
env = dict(os.environ, MYSQL_PWD=db_password)
with (PRIVATE/'backup-errors.log').open('wb') as errors:
    dump = subprocess.Popen(['mysqldump', '--set-gtid-purged=OFF', '--single-transaction', '--skip-lock-tables',
                             '--hex-blob', '--no-tablespaces', '-h', '127.0.0.1', '-u', 'root', 'xiaozhi_esp32_server'],
                            env=env, stdout=subprocess.PIPE, stderr=errors)
    with gzip.open(PRIVATE/'database.sql.gz', 'wb') as output:
        while True:
            chunk = dump.stdout.read(1024*1024)
            if not chunk:
                break
            output.write(chunk)
    assert dump.wait() == 0, 'backup_failed'
(PRIVATE/'database.sql.gz').chmod(0o600)
for source in (ROOT/'data').rglob('*.sqlite3'):
    target = PRIVATE/('sqlite-'+str(source.relative_to(ROOT/'data')).replace('/', '-'))
    with sqlite3.connect(source) as src, sqlite3.connect(target) as dest:
        src.backup(dest)
        assert dest.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    target.chmod(0o600)
print('Backup complete; assembling matched release', flush=True)
RELEASE.mkdir()
shutil.copytree(OLD_RUNTIME, RELEASE/'runtime')
for rel in CHANGES:
    target = RELEASE/'runtime'/rel
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(STAGE/'python'/rel, target)
    assert target.read_bytes() == (STAGE/'python'/rel).read_bytes()
shutil.copy2(jar, RELEASE/'xiaozhi-esp32-api.jar')
serve = OLD_SERVE.read_text().replace(str(OLD_RUNTIME), str(RELEASE/'runtime'))
assert str(OLD_RUNTIME) not in serve
(RELEASE/'serve.py').write_text(serve)
script = API_SCRIPT.read_text()
old_jars = re.findall(r'[^\s\"\x27]+\.jar', script)
assert len(old_jars) == 1
(RELEASE/'start-manager-api.sh').write_text(script.replace(old_jars[0], str(RELEASE/'xiaozhi-esp32-api.jar')))
command(['/root/miniconda3/envs/xiaozhi-esp32-server/bin/python', '-m', 'compileall', '-q', str(RELEASE/'runtime')])

switched = False
try:
    state['phase'] = 'starting_api';save();switched = True
    command(['pm2', 'stop', str(old['manager-api']['pm_id'])])
    command(['pm2', 'start', str(RELEASE/'start-manager-api.sh'), '--name', 'manager-api', '--interpreter', '/usr/bin/bash',
             '--cwd', old['manager-api']['pm2_env']['pm_cwd']], env=environments['manager-api'])
    app = find_app(RELEASE/'start-manager-api.sh');state['new_ids']['manager-api'] = app['pm_id'];save()
    wait_ready(api_ready, 100)
    # Empty validation probe cannot write. It distinguishes the new route from a 404.
    response = requests.post('http://127.0.0.1:18005/xiaozhi/person-memory/internal/add',
                             headers={'Authorization': 'Bearer ' + secret}, json={}, timeout=5)
    assert response.status_code != 404
    assert response.status_code == 400 or response.json().get('code') != 0
    print('Matched API ready; restarting voice service', flush=True)
    state['phase'] = 'starting_python';save()
    command(['pm2', 'stop', str(old['xiaozhi-server']['pm_id'])])
    command(['pm2', 'start', str(RELEASE/'serve.py'), '--name', 'xiaozhi-server', '--interpreter',
             old['xiaozhi-server']['pm2_env']['exec_interpreter'], '--cwd', old['xiaozhi-server']['pm2_env']['pm_cwd']],
            env=environments['xiaozhi-server'])
    app = find_app(RELEASE/'serve.py');state['new_ids']['xiaozhi-server'] = app['pm_id'];save()
    wait_ready(ports_ready, 80)
    command(['nginx', '-t'])
    assert requests.get('https://www.realecho.cn/', timeout=15).status_code == 200
    public = requests.post('https://api.realecho.cn/xiaozhi/person-memory/internal/add',
                           headers={'Authorization': 'Bearer ' + secret}, json={}, timeout=15)
    assert public.status_code != 404
    assert public.status_code == 400 or public.json().get('code') != 0

    async def reject_invalid_token():
        async with websockets.connect('wss://api.realecho.cn/xiaozhi/v1/',
                additional_headers={'device-id': 'aa:00:00:17:10:ff', 'client-id': 'harness-release-negative-probe',
                                    'Authorization': 'Bearer invalid'}, open_timeout=15) as ws:
            try:
                while True:
                    await asyncio.wait_for(ws.recv(), 12)
            except websockets.exceptions.ConnectionClosed:
                assert ws.close_code == 1008
    asyncio.run(reject_invalid_token())
    assert binding() == baseline_binding, 'binding_changed'
    assert hashlib.sha256((ROOT/'data/.config.yaml').read_bytes()).hexdigest() == config_digest
    active = {x['pm_id']: x for x in pm2()}
    assert all(active[i]['pm2_env']['status'] == 'online' for i in state['new_ids'].values())
    untouched = [x for x in apps if x['pm_id'] not in [11, 13]]
    assert all(active[x['pm_id']]['pm2_env']['status'] == x['pm2_env']['status'] for x in untouched)
    assert api_ready() and ports_ready()
    command(['pm2', 'save'])
    state.update(phase='complete', completed_at=time.time(), api_jar_sha256=manifest['api_jar_sha256'],
                 checks=['public_https_200', 'public_add_route_exists_and_rejects_invalid_body',
                         'public_wss_rejects_invalid_token_1008', 'production_ports_ready', 'nginx_valid',
                         'device_binding_unchanged', 'root_config_unchanged', 'other_processes_unchanged'],
                 hardware_tested=False)
    save();print(json.dumps(state), flush=True)
except BaseException as exc:
    state.update(phase='rolling_back', failure_type=type(exc).__name__);save()
    if switched:
        for script in [RELEASE/'serve.py', RELEASE/'start-manager-api.sh']:
            try:
                command(['pm2', 'stop', str(find_app(script)['pm_id'])])
            except Exception:
                pass
        command(['pm2', 'restart', str(old['manager-api']['pm_id'])])
        wait_ready(api_ready, 100)
        command(['pm2', 'restart', str(old['xiaozhi-server']['pm_id'])])
        wait_ready(ports_ready, 80)
        command(['pm2', 'save'])
    state.update(phase='rolled_back', finished_at=time.time());save()
    raise
