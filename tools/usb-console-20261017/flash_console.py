"""Flash only the application after verifying this device and its backups."""
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
MAC = 'ac:a7:04:fd:20:5c'


def run(name, command, after='no_reset'):
    result = subprocess.run([sys.executable, '-m', 'esptool', '--chip', 'esp32s3',
        '--port', 'COM11', '--baud', '921600', '--before', 'no_reset', '--after', after,
        *command], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (OUT / (name + '.log')).write_bytes(result.stdout)
    if result.returncode:
        raise RuntimeError(f'{name} failed; inspect its private log')
    return result.stdout.decode('utf-8', errors='replace')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    raw = (OUT / 'device-before.bin').read_bytes()
    if len(raw) != 0x520000:
        raise RuntimeError('Incomplete original application/config backup')
    partitions = {}
    for pos in range(0, 0x1000, 32):
        magic, kind, sub, offset, size, label, flags = struct.unpack_from('<HBBII16sI', raw, pos)
        if magic in (0xffff, 0xebeb):
            break
        if magic != 0x50aa:
            raise RuntimeError('Bad partition table')
        partitions[label.split(b'\0')[0].decode()] = (offset, size)
    if partitions.get('factory') != (0x20000, 0x4f0000):
        raise RuntimeError('Unexpected application partition')
    if partitions.get('nvs') != (0x9000, 0x10000) or partitions.get('userdata') != (0x510000, 0x20000):
        raise RuntimeError('Unexpected settings partition')
    if MAC not in run('device-mac', ['read_mac']):
        raise RuntimeError('Wrong device on COM11')
    build_result = json.loads((OUT / 'firmware-build-result.json').read_text(encoding='utf-8'))
    if build_result['exit_code'] != 0:
        raise RuntimeError('Build did not pass')
    config = (ROOT / 'build/config/sdkconfig.h').read_text(encoding='utf-8')
    if '#define CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG 1' not in config or '#define CONFIG_USE_USB_STREAM 1' not in config:
        raise RuntimeError('Expected USB console and preserved UVC configuration')
    image = (ROOT / 'build/xiaozhi.bin').read_bytes()
    if len(image) > partitions['factory'][1]:
        raise RuntimeError('Application exceeds partition')
    # Back up the full userdata separately: the contiguous application backup
    # includes its leading portion, but stops before the resource partition.
    run('userdata-backup', ['read_flash', '0x510000', '0x20000', str(OUT / 'userdata-before.bin')])
    protected = raw[:0x12000]
    userdata = (OUT / 'userdata-before.bin').read_bytes()
    if len(userdata) != 0x20000:
        raise RuntimeError('Incomplete userdata backup')
    (OUT / 'xiaozhi-usb-console.bin').write_bytes(image)
    output = run('flash-application', ['write_flash', '--flash_mode', 'keep', '--flash_freq', 'keep',
                '--flash_size', 'keep', '0x20000', str(OUT / 'xiaozhi-usb-console.bin')])
    if 'Hash of data verified.' not in output:
        raise RuntimeError('Flash hash verification missing')
    run('protected-readback', ['read_flash', '0x8000', '0x12000', str(OUT / 'protected-after.bin')])
    run('userdata-readback', ['read_flash', '0x510000', '0x20000', str(OUT / 'userdata-after.bin')])
    if (OUT / 'protected-after.bin').read_bytes() != protected or (OUT / 'userdata-after.bin').read_bytes() != userdata:
        raise RuntimeError('Protected settings changed; retain bootloader for inspection')
    result = {'mac': MAC, 'port': 'COM11', 'application_offset': '0x20000',
              'application_bytes': len(image), 'application_sha256': digest(image),
              'backup_sha256': digest(raw), 'flash_hash_verified': True,
              'partition_nvs_phy_unchanged': True, 'userdata_unchanged': True,
              'uvc_compiled_in': True, 'runtime_logs_verified': False}
    (OUT / 'flash-result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    run('reboot', ['read_mac'], after='hard_reset')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
