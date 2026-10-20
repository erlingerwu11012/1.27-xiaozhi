"""Install the checked two-file identity fix with exact-base guards and backups."""
from pathlib import Path
import hashlib
import json
import shutil

root = Path("/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server/core")
staging = Path("/root/prjs/tmp/context-memory-release-20260929")
backup = staging / "backup-identity-fix-20260930"
files = (
    (root / "connection.py", staging / "connection.py.identity-fix",
     "16b1c0d10865a983841b38beffc16f02dc7d068a08ac6ae816d02a47a21def4f",
     "7f7499dfe2b5cdb7ad74b50fd1ed4002312c0bb1a131b4c0d72d8487dec4525e"),
    (root / "utils/person_directory_sync.py", staging / "person_directory_sync.py.identity-fix",
     "13c967ec075a13a2cfa739bd5a4732dd0096a1264c72183553fe429ae7413b23",
     "f8ac53d02f7a82700dd7353d945e2be56bed362736d8b040e8ee93d536df3813"),
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
