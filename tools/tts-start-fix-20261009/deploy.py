"""Install only the tested Qwen provider, with guarded backup and rollback."""
import asyncio
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

ROOT = Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server')
STAGE = Path('/root/prjs/tmp/tts-start-fix-20261009.20tmyjcr')
ROLLOUT = Path('/root/prjs/releases/tool-harness-20261008/rollout.py')
REL = Path('core/providers/tts/qwen_audio_tts_plus.py')
OLD = '7cb1a359e8b4d23362ee00e3f245babd4c4ed802bc90c88bfc6687cb0b61fc56'
NEW = 'fd8758346c3c39e94689b896e7621723f78c166a180bc4ea763df169439598c7'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def app():
    rows = json.loads(subprocess.check_output(['pm2', 'jlist']))
    matches = [row for row in rows if row['pm_id'] == 7]
    assert len(matches) == 1, 'pm2 identity missing'
    row = matches[0]
    assert row['pm2_env']['pm_cwd'] == str(ROOT), 'pm2 cwd changed'
    assert row['pm2_env']['pm_exec_path'] == str(ROLLOUT), 'pm2 script changed'
    return row


def restart():
    result = subprocess.run(['pm2', 'restart', '7'], capture_output=True, text=True)
    assert result.returncode == 0, 'pm2 restart failed'


def install(source, target):
    assert target.resolve().is_relative_to(ROOT.resolve()), 'path escape'
    temp = target.with_name(target.name + '.tts-start-fix-tmp')
    assert not temp.exists(), 'temporary file collision'
    shutil.copy2(source, temp)
    os.replace(temp, target)


spec = importlib.util.spec_from_file_location('release_health', ROLLOUT)
health = importlib.util.module_from_spec(spec)
spec.loader.exec_module(health)
report = json.loads((STAGE / 'test-results/test-report.json').read_text())
assert report['passed'] and report['tests'] == 80, 'tests not complete'
assert report['provider_sha256'] == NEW, 'tested source mismatch'
assert digest(STAGE / REL) == NEW and digest(ROOT / REL) == OLD, 'source drift'
before = app()
assert before['pm2_env']['status'] == 'online', 'existing service unhealthy'
preflight = asyncio.run(health.health(internal_port=8006, public=True))
assert all(row['passed'] for row in preflight), 'preflight health failed'
unchanged_paths = ['core/handle/sendAudioHandle.py', 'core/utils/tts_stream.py']
unchanged = {name: digest(ROOT / name) for name in unchanged_paths}
release = Path(tempfile.mkdtemp(prefix='tts-start-fix-20261009.',
                               dir='/root/prjs/releases'))
backup = release / 'qwen_audio_tts_plus.py.before'
shutil.copy2(ROOT / REL, backup)
shutil.copy2(STAGE / REL, release / 'qwen_audio_tts_plus.py.after')
shutil.copy2(STAGE / 'test/test_qwen_tts_device_start.py', release)
shutil.copytree(STAGE / 'test-results', release / 'test-results')
shutil.copy2(Path(__file__), release / 'deploy.py')
state = {'phase': 'backed_up', 'release': str(release), 'old_sha256': OLD,
         'new_sha256': NEW, 'pid_before': before['pid'], 'pm2_id': 7,
         'preflight': preflight, 'hardware': False, 'deployed_at': None,
         'unchanged_source_hashes': unchanged}


def save():
    (release / 'deployment-report.json').write_text(json.dumps(state, indent=2))


save()
try:
    assert digest(ROOT / REL) == OLD, 'source changed during preflight'
    install(STAGE / REL, ROOT / REL)
    state['phase'] = 'installed'
    save()
    restart()
    checks = health.wait_ready(internal_port=8006, public=True)
    after = app()
    assert after['pm2_env']['status'] == 'online', 'process not online'
    assert after['pid'] != before['pid'], 'process did not restart'
    assert after['pm2_env']['restart_time'] == before['pm2_env']['restart_time'] + 1
    assert digest(ROOT / REL) == NEW, 'installed source drift'
    assert all(digest(ROOT / name) == value for name, value in unchanged.items())
    state.update(phase='deployed_verified', health=checks, pid_after=after['pid'],
                 restart_count=after['pm2_env']['restart_time'], deployed_at=time.time())
    save()
    print(json.dumps(state), flush=True)
except Exception as error:
    state['error'] = str(error)
    save()
    if digest(ROOT / REL) == NEW:
        install(backup, ROOT / REL)
        restart()
        state['rollback_health'] = health.wait_ready(internal_port=8006, public=True)
        state['phase'] = 'rolled_back'
        save()
    else:
        state['phase'] = 'rollback_refused_source_drift'
        save()
    print(json.dumps(state), flush=True)
    raise
