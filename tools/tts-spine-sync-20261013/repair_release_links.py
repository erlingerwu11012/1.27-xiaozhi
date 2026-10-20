"""Undo this release's duplicate model copy after byte-for-byte verification."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import time

OLD=Path('/root/prjs/releases/harness-followup-20261013/runtime')
NEW=Path('/root/prjs/releases/tts-spine-sync-20261013/runtime')
ORIGINAL=Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server/models')
def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        while chunk:=f.read(1024*1024):h.update(chunk)
    return h.hexdigest()

def main():
    models=NEW/'models'
    assert (OLD/'models').is_symlink()
    assert (OLD/'models').resolve()==ORIGINAL.resolve()
    assert models.resolve()==Path('/root/prjs/releases/tts-spine-sync-20261013/runtime/models')
    assert models.is_dir() and not models.is_symlink()
    assert NEW.resolve()==Path('/root/prjs/releases/tts-spine-sync-20261013/runtime')
    source_files={str(p.relative_to(ORIGINAL)):p for p in ORIGINAL.rglob('*')
                  if p.is_file() and '__pycache__' not in p.parts}
    cloned_files={str(p.relative_to(models)):p for p in models.rglob('*')
                  if p.is_file() and '__pycache__' not in p.parts}
    assert source_files.keys()==cloned_files.keys(),'Model contents differ: stop'
    for rel,path in cloned_files.items():
        assert not path.is_symlink()
        source=source_files[rel]
        assert path.stat().st_size==source.stat().st_size and sha(path)==sha(source),rel
    byte_count=sum(p.stat().st_size for p in cloned_files.values())
    # Rename within this release so all later model opens use the original
    # immediately. The only recursive deletion target is our verified clone.
    duplicate=NEW/'models.verified-duplicate-20261013'
    assert not duplicate.exists()
    models.rename(duplicate)
    os.symlink(os.readlink(OLD/'models'),models,target_is_directory=True)
    assert models.is_symlink() and models.resolve()==ORIGINAL.resolve()
    assert duplicate.resolve()==Path('/root/prjs/releases/tts-spine-sync-20261013/runtime/models.verified-duplicate-20261013')
    shutil.rmtree(duplicate)
    copied_config=NEW/'data/.config.yaml'
    old_config=OLD/'data/.config.yaml'
    if old_config.is_symlink() and not copied_config.is_symlink():
        backup=NEW/'data/.config.clone-before-link.yaml'
        assert not backup.exists()
        copied_config.rename(backup)
        os.symlink(os.readlink(old_config),copied_config)
    report={'at':time.time(),'verified_duplicate_files':len(cloned_files),
            'verified_duplicate_bytes':byte_count,'models_link':str(models.resolve()),
            'removed_only_this_release_duplicate':True,'original_models_retained':True,
            'free_bytes_after':shutil.disk_usage('/').free}
    (NEW.parent/'link-repair.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report),flush=True)

if __name__=='__main__':main()
