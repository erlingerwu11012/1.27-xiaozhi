"""Back up and atomically publish the checked static frontend; no service restart."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone

WORK = Path('/root/prjs/tmp/login-account-guard-20261002')
LIVE = Path('/var/www/realecho-www')
SOURCE = Path('/root/prjs/xiaozhi-esp32-server/main/manager-web/src/views/login.vue')

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def atomic_copy(src, dst):
    dst.parent.mkdir(parents=True, exist_ok=True)
    temporary = dst.with_name(dst.name + '.login-release-tmp')
    shutil.copyfile(src, temporary)
    os.chmod(temporary, 0o644)
    os.replace(temporary, dst)

def restore(backup):
    assert backup.parent == WORK and backup.name.startswith('backup-')
    atomic_copy(backup / 'login.vue', SOURCE)
    for name in ('index.html.gz', 'index.html.br'):
        previous = backup / 'static' / name
        if previous.exists():
            atomic_copy(previous, LIVE / name)
        elif (LIVE / name).exists():
            (LIVE / name).unlink()
    atomic_copy(backup / 'static/index.html', LIVE / 'index.html')

if len(sys.argv) > 1:
    assert len(sys.argv) == 3 and sys.argv[1] == '--rollback'
    restore(Path(sys.argv[2]).resolve())
    print(json.dumps({'rolled_back': True, 'index_sha256': sha(LIVE / 'index.html')}))
    raise SystemExit

receipt = json.loads((WORK / 'build-receipt.json').read_text())
checks = json.loads((WORK / 'candidate-check.json').read_text())
assert checks['passed'] and checks['mode'] == 'candidate' and len(checks['domains']) == 2
assert checks['build_index_sha256'] == receipt['index_sha256']
assert sha(SOURCE) == receipt['source_before'], 'Production source changed; abort'
assert sha(LIVE / 'index.html') == 'f1f9e16ce876e9f9b5574794c4ad7d53a2a69335a132db3b6c5f299501a40eb1', 'Production index changed; abort'
candidate = WORK / 'candidate/dist'
assert sha(candidate / 'index.html') == receipt['index_sha256']
assert sha(WORK / 'login.after.vue') == receipt['source_after']
assert (candidate / receipt['app'].lstrip('/')).is_file()
stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
backup = WORK / ('backup-' + stamp)
backup.mkdir()
shutil.copytree(LIVE, backup / 'static')
shutil.copy2(SOURCE, backup / 'login.vue')
result = {'backup': str(backup), 'published_utc': stamp, 'app': receipt['app'],
          'source_before': receipt['source_before'], 'source_after': receipt['source_after'],
          'index_before': sha(backup / 'static/index.html'), 'index_after': receipt['index_sha256']}
(WORK / 'deploy-receipt.json').write_text(json.dumps(result, indent=2))
try:
    # Install content-addressed assets first. Retain old chunks for open clients.
    for entry in candidate.rglob('*'):
        assert not entry.is_symlink()
        if entry.is_file() and entry.name not in ('index.html', 'index.html.gz', 'index.html.br'):
            atomic_copy(entry, LIVE / entry.relative_to(candidate))
    atomic_copy(WORK / 'login.after.vue', SOURCE)
    for name in ('index.html.gz', 'index.html.br'):
        if (candidate / name).exists():
            atomic_copy(candidate / name, LIVE / name)
        elif (LIVE / name).exists():
            (LIVE / name).unlink()
    atomic_copy(candidate / 'index.html', LIVE / 'index.html')
    assert sha(SOURCE) == receipt['source_after']
    assert sha(LIVE / 'index.html') == receipt['index_sha256']
except BaseException:
    restore(backup)
    raise
result['published'] = True
(WORK / 'deploy-receipt.json').write_text(json.dumps(result, indent=2))
print(json.dumps(result, indent=2))
