"""Explicit app-only flashing, identity/layout checks and saved evidence."""
import argparse
from datetime import datetime,timezone
from pathlib import Path
import hashlib
import json
import re
import subprocess
import sys

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
    p=argparse.ArgumentParser();p.add_argument('--port',required=True);p.add_argument('--baud',default='460800');a=p.parse_args()
    root=Path(__file__).resolve().parent;manifest=json.loads((root/'manifest.json').read_text())
    assert sha(root/'xiaozhi.bin')==manifest['app_sha256']
    assert sha(root/'partition-table.reference.bin')==manifest['partition_sha256']
    assert (root/'xiaozhi.bin').stat().st_size<=manifest['app_partition_size']
    def tool(args,after='no_reset'):
        command=[sys.executable,'-m','esptool','--chip','esp32s3','--port',a.port,'--baud',a.baud,
                 '--before','no_reset','--after',after,*args]
        result=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
        with (root/'flash.log').open('a',encoding='utf-8') as f:f.write(result.stdout+'\n')
        print(result.stdout,flush=True)
        result.check_returncode();return result.stdout
    text=tool(['read_mac'])
    macs=re.findall(r'MAC:\s*([a-fA-F0-9:]{17})',text)
    assert macs and all(m.lower()==manifest['device_mac'] for m in macs),'Wrong device; stopped'
    table=root/'device-partition-table.readback.bin'
    tool(['read_flash',hex(manifest['partition_offset']),'0x1000',str(table)])
    expected=(root/'partition-table.reference.bin').read_bytes()
    assert table.read_bytes()[:len(expected)]==expected,'Partition mismatch; stopped'
    # Only this application range is written; assets/bootloader/partition/NVS are excluded.
    tool(['write_flash','--flash_mode','dio','--flash_size','16MB','--flash_freq','80m',
          hex(manifest['app_offset']),str(root/'xiaozhi.bin')],after='hard_reset')
    evidence={'flashed_at':datetime.now(timezone.utc).isoformat(),'port':a.port,
              'mac':manifest['device_mac'],'app_sha256':manifest['app_sha256'],
              'only_factory_written':True,'esptool_hash_verified':True,'hardware_accepted':False}
    (root/'flash-result.json').write_text(json.dumps(evidence,indent=2),encoding='utf-8')
    print(json.dumps(evidence),flush=True)

if __name__=='__main__':main()
