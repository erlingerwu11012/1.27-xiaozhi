"""User-run segmented ESP32-S3 upgrade. Never run by Codex against a device."""
import argparse,hashlib,json,re,struct,subprocess,sys,time
from pathlib import Path
FLASH_SIZE=0x1000000
PROTECTED={'userdata':(0x510000,0x20000),'spine':(0xA00000,0x400000),'wallpaper':(0xE00000,0x200000)}

def sha(data):return hashlib.sha256(data).hexdigest()
def partitions(table):
    out={};prefix=bytearray();found_md5=False
    for offset in range(0,0x1000,32):
        block=table[offset:offset+32]
        if len(block)!=32:raise ValueError('short partition table')
        if block[:2]==b'\xeb\xeb':
            if block[16:]!=hashlib.md5(prefix).digest():raise ValueError('invalid partition table checksum')
            found_md5=True;break
        if block==b'\xff'*32:break
        magic,kind,subtype,start,size,label,flags=struct.unpack('<HBBII16sI',block)
        if magic!=0x50aa:raise ValueError('invalid partition entry')
        name=label.split(b'\0')[0].decode('ascii');out[name]=(start,size);prefix.extend(block)
    if not found_md5:raise ValueError('partition checksum missing')
    spans=sorted((start,start+size,name) for name,(start,size) in out.items())
    if any(end>FLASH_SIZE or start<0x9000 for start,end,name in spans):raise ValueError('partition outside flash')
    if any(a[1]>b[0] for a,b in zip(spans,spans[1:])):raise ValueError('partition overlap')
    return out

def migrated_nvs(backup):
    if len(backup)!=FLASH_SIZE:raise ValueError('backup must contain the full 16MB flash')
    layout=partitions(backup[0x8000:0x9000])
    if any(layout.get(name)!=span for name,span in PROTECTED.items()) or layout.get('assets')!=(0x530000,0x4d0000):raise ValueError('unsupported old resource/data layout')
    if layout.get('nvs')==(0x9000,0x4000) and layout.get('factory')==(0x10000,0x500000) and layout.get('phy_init')==(0xd000,0x1000):
        return backup[0x9000:0xd000]+b'\xff'*0xc000,backup[0xd000:0xe000],True
    if layout.get('nvs')==(0x9000,0x10000) and layout.get('factory')==(0x20000,0x4f0000) and layout.get('phy_init')==(0x19000,0x1000):
        return backup[0x9000:0x19000],backup[0x19000:0x1a000],False
    raise ValueError('unsupported old NVS/app layout; no writes performed')

def verify_preserved(before,after,nvs,phy):
    if len(after)!=FLASH_SIZE:raise ValueError('short post-flash read')
    for name,(start,size) in PROTECTED.items():
        if after[start:start+size]!=before[start:start+size]:raise ValueError('preserved partition mismatch: '+name)
    if after[0x9000:0x19000]!=nvs:raise ValueError('NVS migration mismatch')
    if after[0x19000:0x1a000]!=phy:raise ValueError('PHY migration mismatch')

def verify_package(root):
    manifest=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
    for name,digest in manifest['sha256'].items():
        p=(root/name).resolve()
        if root.resolve() not in p.parents or sha(p.read_bytes())!=digest:raise ValueError('package checksum mismatch: '+name)
    layout=partitions((root/'partition-table.bin').read_bytes().ljust(0x1000,b'\xff'))
    if layout.get('nvs')!=(0x9000,0x10000) or layout.get('factory')!=(0x20000,0x4f0000) or layout.get('phy_init')!=(0x19000,0x1000):raise ValueError('unexpected new partitions')
    for name,span in PROTECTED.items():
        if layout.get(name)!=span:raise ValueError('protected address changed')
    return manifest

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--port',required=True);parser.add_argument('--baud',type=int,default=460800);args=parser.parse_args()
    root=Path(__file__).resolve().parent;manifest=verify_package(root)
    subprocess.run([sys.executable,'-c','import esptool,serial'],check=True)
    stamp=time.strftime('%Y%m%d-%H%M%S');backup_dir=root/'backups'/stamp;backup_dir.mkdir(parents=True,exist_ok=False)
    log=backup_dir/'upgrade.log'
    base=[sys.executable,'-m','esptool','--chip','esp32s3','--port',args.port,'--baud',str(args.baud),'--before','default_reset','--after','no_reset']
    def run(*cmd):
        result=subprocess.run(base+list(map(str,cmd)),capture_output=True,text=True,encoding='utf-8',errors='replace')
        with log.open('a',encoding='utf-8') as f:f.write(result.stdout+result.stderr+'\n')
        print(result.stdout,flush=True)
        if result.returncode:raise RuntimeError('esptool failed; preserve backup and consult upgrade.log')
        return result.stdout
    info=run('get_security_info')
    if 'Secure Boot: Disabled' not in info or 'Flash Encryption: Disabled' not in info:raise ValueError('encrypted/secure-boot device unsupported; no writes performed')
    flash_info=run('flash_id')
    if not re.search(r'Detected flash size:\s*16MB',flash_info,re.IGNORECASE):raise ValueError('device must have a detected 16MB flash; no writes performed')
    before=backup_dir/'flash-before.bin';check=backup_dir/'flash-readback.bin'
    print('Reading complete 16MB backup twice. No writes before both reads match.',flush=True)
    run('read_flash','0','0x1000000',before);run('read_flash','0','0x1000000',check)
    old=before.read_bytes()
    if len(old)!=FLASH_SIZE or sha(old)!=sha(check.read_bytes()):raise ValueError('backup verification failed; no writes performed')
    (backup_dir/'flash-before.sha256').write_text(sha(old)+'  flash-before.bin\n')
    nvs,phy,expanded=migrated_nvs(old)
    nvs_file=backup_dir/'nvs-preserved-64k.bin';nvs_file.write_bytes(nvs)
    phy_file=backup_dir/'phy-preserved.bin';phy_file.write_bytes(phy)
    if expanded and nvs[0x4000:]!=b'\xff'*0xc000:raise ValueError('new NVS region not erased')
    files=[('0x0',root/'bootloader.bin'),('0x8000',root/'partition-table.bin'),('0x9000',nvs_file),('0x19000',phy_file),('0x20000',root/'xiaozhi.bin'),('0x530000',root/'generated_assets.bin')]
    print('Backup verified. Writing only bootloader, partition table, preserved NVS/PHY, app and factory assets.',flush=True)
    run('write_flash','--flash_mode','dio','--flash_size','16MB','--flash_freq','80m',*[x for pair in files for x in pair])
    run('verify_flash',*[x for pair in files for x in pair])
    after=backup_dir/'flash-after.bin';run('read_flash','0','0x1000000',after)
    verify_preserved(old,after.read_bytes(),nvs,phy)
    (backup_dir/'verified.json').write_text(json.dumps({'ok':True,'old_flash_sha256':sha(old),'new_flash_sha256':sha(after.read_bytes()),'nvs_expanded':expanded,'protected':PROTECTED},indent=2))
    print('SUCCESS: NVS and user/role/wallpaper data verified. Disconnect and reconnect USB to start the new firmware. Backups contain private device data; keep them locally.',flush=True)

if __name__=='__main__':
    try:main()
    except Exception as exc:
        print('STOPPED: '+str(exc),file=sys.stderr);sys.exit(1)
