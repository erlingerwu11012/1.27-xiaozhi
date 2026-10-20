"""Install one checked search-routing module and preserve its exact prior version."""
from pathlib import Path
import hashlib
import json
import shutil

name = 'recent_memory.py'
live = Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server/core/utils') / name
stage = Path('/root/prjs/tmp/context-memory-release-20260929/directory-schema-20260930')
source = stage / name
backup = stage / (name + '.before-cloud-precedence')
before = '229b29008c4e7b953e836da647d8d7b66ef476a5acffa0f09e7c6b6166c91668'
after = '2bd5b989dbbe1337e163f33b9db45302ab8d736aeb04974c797373d56a17118d'

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

if sha(live) != before or sha(source) != after or backup.exists():
    raise RuntimeError('source, live base, or backup state mismatch')
shutil.copy2(live, backup)
shutil.copy2(source, live)
if sha(live) != after:
    raise RuntimeError('installed checksum mismatch')
print(json.dumps({'installed': name, 'checksums_verified': True,
                  'backup': str(backup)}))
