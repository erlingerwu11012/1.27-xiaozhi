"""Guarded production deployment, source-only backup and health rollback."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time
from datetime import datetime, timezone
from urllib.request import urlopen

ROOT = Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server')
RELEASE = Path('/root/prjs/tmp/remove-llm-rewrite-20261003')
report = json.loads((RELEASE / 'regression.json').read_text())
assert report['success'] and report['run'] >= 114, 'candidate regression incomplete'
manifest = json.loads((RELEASE / 'manifest.json').read_text())
assert set(manifest) == {'core/connection.py', 'core/utils/prompt_pipeline.py', 'test/test_prompt_pipeline_v2.py', 'test/test_official_dialogue.py'}
prepared = {}
for name, row in manifest.items():
    assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == row['before_sha256'], 'source changed: ' + name
    content = (RELEASE / 'delivery' / name).read_bytes()
    assert hashlib.sha256(content).hexdigest() == row['after_sha256'], 'delivery changed: ' + name
    compile(content.decode('utf-8'), name, 'exec')
    prepared[name] = content
new_test = 'test/test_primary_answer_direct_tts.py'
assert not (ROOT / new_test).exists(), 'new test already exists'
prepared[new_test] = (RELEASE / 'delivery' / new_test).read_bytes()
compile(prepared[new_test].decode(), new_test, 'exec')
processes = json.loads(subprocess.run(['pm2', 'jlist'], check=True, capture_output=True, text=True, timeout=20).stdout)
proc = next(p for p in processes if p['name'] == 'xiaozhi-server')
assert proc['pm2_env'].get('pm_cwd') == str(ROOT), 'unexpected process directory'

stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-utc')
backup = RELEASE / ('backup-' + stamp)
backup.mkdir()
for name in prepared:
    path = ROOT / name
    if path.exists():
        saved = backup / name
        saved.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, saved)


def health():
    processes = json.loads(subprocess.run(['pm2', 'jlist'], check=True, capture_output=True, text=True, timeout=10).stdout)
    proc = next(p for p in processes if p['name'] == 'xiaozhi-server')
    if proc['pm2_env']['status'] != 'online':
        return None
    with socket.create_connection(('127.0.0.1', 8000), timeout=3):
        pass
    # Managed mode deliberately omits the local OTA route. This GET is always
    # registered and returns a static endpoint description, not customer data.
    with urlopen('http://127.0.0.1:8003/mcp/vision/explain', timeout=4) as res:
        status = res.status
    return {'voice_status': 'online', 'pid': proc['pid'], 'ws_port': 8000, 'http_probe': '/mcp/vision/explain', 'http_status': status}


changed = []
try:
    for name, content in prepared.items():
        target = ROOT / name
        temp = target.with_name(target.name + '.direct-tts-new')
        temp.write_bytes(content)
        if target.exists():
            shutil.copystat(target, temp)
        os.utime(temp, None)
        os.replace(temp, target)
        changed.append(name)
    subprocess.run(['pm2', 'restart', 'xiaozhi-server'], check=True, capture_output=True, text=True, timeout=40)
    current = None
    for attempt in range(12):
        time.sleep(2)
        try:
            current = health()
            if current and current['http_status'] == 200:
                break
        except Exception:
            pass
    assert current and current['http_status'] == 200, 'voice health failed'
    time.sleep(3)
    stable = health()
    assert stable['pid'] == current['pid'], 'process restarted unexpectedly'
except Exception:
    for name in changed:
        saved = backup / name
        target = ROOT / name
        if saved.exists():
            shutil.copy2(saved, target)
            os.utime(target, None)
        elif name == new_test:
            target.unlink()
    subprocess.run(['pm2', 'restart', 'xiaozhi-server'], capture_output=True, text=True, timeout=40)
    raise

receipt = {'deployed_at_utc': datetime.now(timezone.utc).isoformat(), 'backup': str(backup), 'regression': report, 'health': stable, 'files': manifest, 'new_test_sha256': hashlib.sha256(prepared[new_test]).hexdigest(), 'pipeline': 'ASR -> primary LLM / necessary tool continuation -> TTS', 'second_llm_rewrite': 'removed'}
(RELEASE / 'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(receipt, ensure_ascii=False))
