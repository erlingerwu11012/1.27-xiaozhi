from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[2]
STAGE=Path(__file__).parent
BUILD=ROOT/'build'
OUT=STAGE/'firmware-mouthfix'
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    OUT.mkdir(exist_ok=True)
    sources=[p for folder in ('main','components/cubicat_home_spine','components/cubicat_home_engine')
             for p in (ROOT/folder).rglob('*') if p.suffix in ('.cc','.cpp','.h')]
    assert max(p.stat().st_mtime for p in sources)<=(BUILD/'xiaozhi.bin').stat().st_mtime,'Rebuild after source changes'
    assert (STAGE/'baseline/device-app-before.bin').stat().st_size==0x4F0000
    device=(STAGE/'baseline/device-partition-table.bin').read_bytes()
    expected=(BUILD/'partition_table/partition-table.bin').read_bytes()
    assert device[:len(expected)]==expected
    for src,dst in ((BUILD/'xiaozhi.bin',OUT/'xiaozhi.bin'),
                    (BUILD/'partition_table/partition-table.bin',OUT/'partition-table.reference.bin'),
                    (STAGE/'flash_app.py',OUT/'flash_app.py')):shutil.copy2(src,dst)
    manifest={'release':'tts-spine-sync-20261013-mouthfix','created_at':datetime.now(timezone.utc).isoformat(),
        'device_mac':'ac:a7:04:fd:20:2c','app_offset':0x20000,'app_partition_size':0x4F0000,
        'partition_offset':0x8000,'app_sha256':sha(OUT/'xiaozhi.bin'),
        'elf_sha256':sha(BUILD/'xiaozhi.elf'),
        'partition_sha256':sha(OUT/'partition-table.reference.bin'),
        'backup_sha256':sha(STAGE/'baseline/device-app-before.bin'),
        'written_partitions':['factory'],'hardware_accepted':False,
        'source_hashes':{str(p.relative_to(ROOT)).replace('\\','/'):sha(p) for p in sources},
        'resource_role':json.loads((ROOT/'main/assets/cubicat_spine_default_42/role.json').read_text())}
    assert (OUT/'xiaozhi.bin').stat().st_size<=manifest['app_partition_size']
    (OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    (STAGE/'before-hashes.json').write_text(json.dumps({f:sha(STAGE/'baseline/server'/f)
        for f in ('core/connection.py','core/providers/tools/device_mcp/mcp_handler.py')}),encoding='utf-8')
    print(json.dumps({k:manifest[k] for k in ('release','app_sha256','elf_sha256','backup_sha256')},indent=2))

if __name__=='__main__':main()
