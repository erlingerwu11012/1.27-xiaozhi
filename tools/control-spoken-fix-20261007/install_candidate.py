"""Install only the tested manifest, with baseline conflicts and explicit rollback."""
import hashlib, json, os, py_compile, shutil, sys
from pathlib import Path

stage = Path(__file__).parent
production = Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server')
candidate = stage / 'candidate/main/xiaozhi-server'
backup = stage / 'production-backup'
rows = json.loads((stage / 'manifest.json').read_text())

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None

def safe(root, relative):
    path = root / relative
    if Path(relative).is_absolute() or '..' in Path(relative).parts or not relative.startswith(('core/', 'test/')):
        raise RuntimeError('invalid manifest path')
    if path.exists() and path.is_symlink():
        raise RuntimeError('symlink target rejected')
    return path

def restore():
    for row in rows:
        dst = safe(production, row['path'])
        if row['baseline_sha256'] is None:
            if dst.exists():
                if sha(dst) != row['candidate_sha256']:
                    raise RuntimeError('rollback conflict: ' + row['path'])
                dst.unlink()
        else:
            source = safe(backup, row['path'])
            if sha(source) != row['baseline_sha256']:
                raise RuntimeError('invalid backup: ' + row['path'])
            shutil.copy2(source, dst)

if '--rollback' in sys.argv:
    restore()
    print(json.dumps({'rollback': True, 'files': len(rows)}))
    sys.exit(0)

conflicts = []
for row in rows:
    dst, src = safe(production, row['path']), safe(candidate, row['path'])
    if sha(dst) != row['baseline_sha256'] or sha(src) != row['candidate_sha256']:
        conflicts.append(row['path'])
    py_compile.compile(str(src), doraise=True)
if conflicts:
    print(json.dumps({'conflicts': conflicts}))
    sys.exit(2)
print(json.dumps({'baseline_matches': True, 'compiled_files': len(rows)}), flush=True)
if '--apply' not in sys.argv:
    sys.exit(0)
if backup.exists():
    raise RuntimeError('backup already exists; refusing to overwrite it')
protected = [production / 'data/.config.yaml',
             production / 'config/assets/wakeup_words/83dca73ebd19180d2b8b39723dae401b.wav']
protected_hashes = [sha(p) for p in protected]
for row in rows:
    dst = safe(production, row['path'])
    if dst.exists():
        target = safe(backup, row['path'])
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(dst, target)
(backup / 'manifest.json').write_text(json.dumps(rows, indent=2))
try:
    for row in rows:
        dst = safe(production, row['path'])
        src = safe(candidate, row['path'])
        dst.parent.mkdir(parents=True, exist_ok=True)
        temp = dst.with_name(dst.name + '.reminder-reliability-new')
        shutil.copy2(src, temp)
        os.chmod(temp, dst.stat().st_mode & 0o777 if dst.exists() else 0o644)
        os.replace(temp, dst)
    unchanged = protected_hashes == [sha(p) for p in protected]
    if not unchanged:
        raise RuntimeError('protected file unexpectedly changed')
    print(json.dumps({'installed': True, 'files': len(rows), 'config_and_user_audio_unchanged': unchanged}))
except BaseException:
    restore()
    raise
