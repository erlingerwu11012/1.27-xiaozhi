"""Install two checked Python modules, preserving exact originals for rollback."""
from pathlib import Path
import hashlib
import json
import shutil

root = Path("/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server/core/utils")
staging = Path("/root/prjs/tmp/context-memory-release-20260929")
backup = staging / "backup-voiceprint-refresh-20260930"
files = (
    (root / "person_identity.py", staging / "person_identity.py.voiceprint-fix",
     "b01d308b65519ebb0843980650e14c43cc4d69e0447d0aea71498236acd6e546",
     "21835445abf298af556547a18d7edbb6e24d06bd2c0fbb2cfcd6cca6d4afa7b2"),
    (root / "person_directory_sync.py", staging / "person_directory_sync.py.voiceprint-fix",
     "f8ac53d02f7a82700dd7353d945e2be56bed362736d8b040e8ee93d536df3813",
     "8468d8b62fca4d0a24179d829383c2d25f90d3ec0459aa2adf2d4a2f376d33df"),
)

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

for target, source, before, after in files:
    if digest(target) != before or digest(source) != after:
        raise RuntimeError("source or live base checksum mismatch: " + target.name)
backup.mkdir(mode=0o700, exist_ok=True)
for target, source, before, after in files:
    shutil.copy2(target, backup / target.name)
    shutil.copy2(source, target)
    if digest(target) != after:
        raise RuntimeError("installed checksum mismatch: " + target.name)
print(json.dumps({"installed": [item[0].name for item in files],
                  "backup_directory": str(backup), "checksums_verified": True}))
