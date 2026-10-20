"""Install the checked directory type correction with a local rollback copy."""
from pathlib import Path
import hashlib
import json
import shutil

root = Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server/core/utils')
staging = Path('/root/prjs/tmp/context-memory-release-20260929/directory-schema-20260930')
backup = staging / 'before'
files = (
    ('person_directory_sync.py',
     '8468d8b62fca4d0a24179d829383c2d25f90d3ec0459aa2adf2d4a2f376d33df',
     'd6cf045a1b450f7bbfb9fdc179488744df5ce7174f0bab90646dcab433528d33'),
    ('person_identity.py',
     '21835445abf298af556547a18d7edbb6e24d06bd2c0fbb2cfcd6cca6d4afa7b2',
     '9fe4095e038e2bf1e08fe7428c8d314f335bb25ee761188570aa672f92866640'),
    ('person_maintenance.py',
     '467989c2a767bdddafd79fc7e832d16197db5bfb5fe1c937cf30b28ecb1c4e92',
     '0aca46e6479158e452e97c8323d8b4141ff6443c08afd14dfbe386722beb3185'),
)

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

for name, before, after in files:
    if digest(root / name) != before or digest(staging / name) != after:
        raise RuntimeError('source or live base checksum mismatch: ' + name)

backup.mkdir(mode=0o700, exist_ok=False)
for name, before, after in files:
    shutil.copy2(root / name, backup / name)
    shutil.copy2(staging / name, root / name)
    if digest(root / name) != after:
        raise RuntimeError('installed checksum mismatch: ' + name)
print(json.dumps({'installed': [name for name, _, _ in files],
                  'backup_directory': str(backup), 'checksums_verified': True}))
