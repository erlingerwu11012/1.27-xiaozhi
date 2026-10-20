"""Preserve device resources while expanding assets by 2 MiB over USB."""
from datetime import datetime, timezone
from pathlib import Path
import argparse
import hashlib
import json
import re
import shutil
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
STAGE = Path(__file__).parent
EVIDENCE = STAGE / 'evidence'
PACKAGE = STAGE / 'firmware'
NEW = {'factory': (0x20000, 0x4F0000), 'assets': (0x530000, 0x6D0000),
       'spine': (0xC00000, 0x300000), 'wallpaper': (0xF00000, 0x100000)}
PROTECTED = {'nvs': (0x9000, 0x10000), 'userdata': (0x510000, 0x20000)}

def digest(data):
    return hashlib.sha256(data).hexdigest()

def bundle(raw):
    """Validate a complete mmap bundle and return its exact payload and file map."""
    if raw[:12] == b'\xff' * 12:
        return None, {}
    if len(raw) < 12:
        raise ValueError('Truncated bundle header')
    count, checksum, length = struct.unpack_from('<III', raw)
    table_size = count * 44
    if not 0 < count <= 256 or not table_size <= length <= len(raw) - 12:
        raise ValueError('Invalid bundle length or file count')
    payload = raw[:12 + length]
    if sum(payload[12:]) & 0xffff != checksum:
        raise ValueError('Bundle checksum mismatch')
    files = {}
    for i in range(count):
        name, size, offset, width, height = struct.unpack_from('<32sIIHH', payload, 12 + i * 44)
        name = name.split(b'\0', 1)[0].decode('utf-8')
        start = 12 + table_size + offset
        end = start + 2 + size
        if not name or name in files or end > len(payload) or payload[start:start + 2] != b'ZZ':
            raise ValueError('Invalid bundle entry: ' + name)
        files[name] = payload[start + 2:end]
    return payload, files

def table_entries(raw):
    entries = {}
    for offset in range(0, len(raw) - 31, 32):
        magic, kind, subtype, start, size, label, flags = struct.unpack_from('<HBBII16sI', raw, offset)
        if magic in (0xffff, 0xebeb):
            break
        if magic != 0x50aa:
            raise ValueError('Invalid partition entry')
        name = label.split(b'\0', 1)[0].decode('ascii')
        if name in entries:
            raise ValueError('Duplicate partition: ' + name)
        entries[name] = (start, size)
    ordered = sorted(entries.values())
    if any(start + size > 0x1000000 for start, size in ordered):
        raise ValueError('Partition exceeds 16 MiB')
    if any(a + n > b for (a, n), (b, _) in zip(ordered, ordered[1:])):
        raise ValueError('Overlapping partitions')
    return entries

def package(preflight):
    backup = Path(preflight['backup'])
    if not preflight.get('migration_backup_complete'):
        raise RuntimeError('Back up the source partitions first')
    for filename, key in [('application.bin', 'app_sha256'), ('assets.bin', 'assets_sha256')]:
        if digest((backup / filename).read_bytes()) != preflight[key]:
            raise RuntimeError('Original device backup hash mismatch: ' + filename)
    build = json.loads((EVIDENCE / 'firmware-build-result.json').read_text(encoding='utf-8'))
    if build['exit_code'] != 0:
        raise RuntimeError('Candidate build did not pass')
    old_table = (backup / 'partition-table.bin').read_bytes()
    new_table = (ROOT / 'build/partition_table/partition-table.bin').read_bytes()
    old_entries, new_entries = table_entries(old_table), table_entries(new_table)
    for name, target in {**NEW, **PROTECTED}.items():
        if new_entries.get(name) != target:
            raise RuntimeError('Unexpected target partition: ' + name)
    for name in ('nvs', 'phy_init', 'factory', 'userdata'):
        if old_entries[name] != new_entries[name]:
            raise RuntimeError('Protected partition moved: ' + name)
    tail = (backup / 'resource-tail.bin').read_bytes()
    if len(tail) != 0x600000 or digest(tail) != preflight['resource_tail_sha256']:
        raise RuntimeError('Resource backup size/hash mismatch')
    old_spine, spine_files = bundle(tail[:0x400000])
    old_wallpaper, wallpaper_files = bundle(tail[0x400000:])
    if old_spine is not None and 'role.json' not in spine_files:
        raise RuntimeError('Source Spine package has no role manifest')
    if old_wallpaper is not None and 'wallpaper.json' not in wallpaper_files:
        raise RuntimeError('Source wallpaper package has no manifest')
    for name, payload in [('spine', old_spine), ('wallpaper', old_wallpaper)]:
        if payload is not None and len(payload) > NEW[name][1]:
            raise RuntimeError('Existing package does not fit after shrinking: ' + name)
    assets_raw = (ROOT / 'build/generated_assets.bin').read_bytes()
    _, files = bundle(assets_raw)
    _, previous_files = bundle((backup / 'assets.bin').read_bytes())
    for name, content in previous_files.items():
        if name not in ('index.json', 'srmodels.bin') and files.get(name) != content:
            raise RuntimeError('Factory UI/font/role unexpectedly changed: ' + name)
    index = json.loads(files['index.json'].decode('utf-8'))
    expected = {'command': 'hai nian nian', 'text': 'hi，念念', 'action': 'wake'}
    model_config = index['multinet_model']
    if model_config['language'] != 'cn' or model_config['commands'] != [expected]:
        raise RuntimeError('Unexpected wake command configuration')
    model = files[index['srmodels']]
    if b'mn7_cn' not in model or b'wn9_nihaoxiaozhi' in model:
        raise RuntimeError('Expected Chinese MultiNet7 without the old WakeNet model')
    PACKAGE.mkdir(exist_ok=True)
    shutil.copyfile(ROOT / 'build/xiaozhi.bin', PACKAGE / 'xiaozhi.bin')
    (PACKAGE / 'assets.bin').write_bytes(assets_raw)
    for name, payload in [('spine', old_spine), ('wallpaper', old_wallpaper)]:
        payload = payload or b''
        (PACKAGE / (name + '.bin')).write_bytes(payload + b'\xff' * (NEW[name][1] - len(payload)))
    (PACKAGE / 'partition-table.bin').write_bytes(new_table)
    (PACKAGE / 'partition-table.before.bin').write_bytes(old_table)
    images = {}
    for name, (offset, capacity) in NEW.items():
        filename = 'xiaozhi.bin' if name == 'factory' else name + '.bin'
        data = (PACKAGE / filename).read_bytes()
        if len(data) > capacity:
            raise RuntimeError('Image too large: ' + filename)
        images[filename] = {'offset': offset, 'capacity': capacity, 'size': len(data), 'sha256': digest(data)}
    images['partition-table.bin'] = {'offset': 0x8000, 'capacity': 0x1000, 'size': len(new_table), 'sha256': digest(new_table)}
    manifest = {'device_mac': preflight['mac'], 'images': images, 'wake_command': expected,
                'source_backup': str(backup), 'preserved_factory_files': sorted(set(previous_files) - {'index.json', 'srmodels.bin'}),
                'spine_payload_size': len(old_spine or b''), 'wallpaper_payload_size': len(old_wallpaper or b''),
                'hardware_accepted': False}
    (PACKAGE / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Package validated: MultiNet7; factory assets unchanged; Spine/wallpaper resources preserved.', flush=True)
    return manifest

def main():
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', default='COM11')
    parser.add_argument('--baud', default='921600')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--prepare', action='store_true')
    mode.add_argument('--package', action='store_true')
    mode.add_argument('--flash', action='store_true')
    args = parser.parse_args()
    record_path = EVIDENCE / 'device-preflight.json'
    preflight = json.loads(record_path.read_text(encoding='utf-8'))
    backup = Path(preflight['backup'])

    def tool(command, before='no_reset', after='no_reset'):
        result = subprocess.run([sys.executable, '-m', 'esptool', '--chip', 'esp32s3', '--port', args.port,
                                 '--baud', args.baud, '--before', before, '--after', after, *command],
                                capture_output=True, text=True, encoding='utf-8', errors='replace')
        output = result.stdout + result.stderr
        with (EVIDENCE / 'migration-flash.log').open('a', encoding='utf-8') as log:
            log.write('COMMAND: ' + ' '.join(command) + '\n' + output + '\n')
        for line in output.splitlines():
            if any(s in line.lower() for s in ('chip is', 'mac:', 'read ', 'wrote ', 'hash of data', 'fatal', 'error', 'hard reset')):
                print(line, flush=True)
        result.check_returncode()
        return output

    def identity():
        output = tool(['read_mac'], before='default_reset')
        macs = re.findall(r'MAC:\s*([a-fA-F0-9:]{17})', output)
        if args.port != preflight['port'] or not macs or macs[-1].lower() != preflight['mac']:
            raise RuntimeError('Port/device changed; no flash write performed')

    def verify_old_table():
        path = EVIDENCE / 'partition-before-migration.bin'
        tool(['read_flash', '0x8000', '0x1000', str(path)])
        if path.read_bytes() != (backup / 'partition-table.bin').read_bytes():
            raise RuntimeError('Device source layout changed; no flash write performed')

    if args.package:
        package(preflight)
        return
    identity()
    verify_old_table()
    if args.prepare:
        if preflight.get('migration_backup_complete'):
            print('Migration backup already recorded; source layout verified.', flush=True)
            return
        tail_path = backup / 'resource-tail.bin'
        if tail_path.exists():
            raise RuntimeError('Unrecorded backup exists; do not overwrite it')
        tool(['read_flash', '0xA00000', '0x600000', str(tail_path)])
        tail = tail_path.read_bytes()
        if len(tail) != 0x600000:
            raise RuntimeError('Incomplete resource backup')
        for name, (offset, size) in PROTECTED.items():
            path = backup / (name + '.bin')
            tool(['read_flash', hex(offset), hex(size), str(path)])
            if path.stat().st_size != size:
                raise RuntimeError('Incomplete protected-data backup')
        preflight.update({'migration_backup_complete': True, 'resource_tail_sha256': digest(tail),
                          'protected_sha256': {name: digest((backup / (name + '.bin')).read_bytes()) for name in PROTECTED}})
        record_path.write_text(json.dumps(preflight, indent=2), encoding='utf-8')
        print('Migration backup complete; no device flash has been written.', flush=True)
        return

    manifest = json.loads((PACKAGE / 'manifest.json').read_text(encoding='utf-8'))
    if manifest['device_mac'] != preflight['mac'] or not preflight.get('migration_backup_complete'):
        raise RuntimeError('Migration package does not match backup/device')
    for filename, image in manifest['images'].items():
        data = (PACKAGE / filename).read_bytes()
        if len(data) != image['size'] or len(data) > image['capacity'] or digest(data) != image['sha256']:
            raise RuntimeError('Image size/hash mismatch: ' + filename)
    command = ['write_flash', '--flash_mode', 'keep', '--flash_freq', 'keep', '--flash_size', 'keep']
    # Write all data before committing the new partition table. Never erase all flash.
    for filename in ('spine.bin', 'wallpaper.bin', 'assets.bin', 'xiaozhi.bin'):
        command += [hex(manifest['images'][filename]['offset']), str(PACKAGE / filename)]
    output = tool(command)
    if output.count('Hash of data verified.') != 4:
        raise RuntimeError('Did not verify all four data images; partition table not committed')
    output = tool(['write_flash', '0x8000', str(PACKAGE / 'partition-table.bin')])
    if 'Hash of data verified.' not in output:
        raise RuntimeError('Partition-table verification did not pass')
    table_path = EVIDENCE / 'partition-after-migration.bin'
    tool(['read_flash', '0x8000', '0x1000', str(table_path)])
    expected = (PACKAGE / 'partition-table.bin').read_bytes()
    if table_path.read_bytes()[:len(expected)] != expected:
        raise RuntimeError('Partition table read-back mismatch')
    for name, (offset, size) in PROTECTED.items():
        path = EVIDENCE / (name + '-after.bin')
        tool(['read_flash', hex(offset), hex(size), str(path)])
        if digest(path.read_bytes()) != preflight['protected_sha256'][name]:
            raise RuntimeError('Protected data unexpectedly changed: ' + name)
    result = {'at': datetime.now(timezone.utc).isoformat(), 'port': args.port, 'mac': preflight['mac'],
              'images': manifest['images'], 'backup': str(backup), 'esptool_hash_verified': True,
              'partition_table_readback_verified': True, 'protected_data_unchanged': True,
              'hardware_accepted': False}
    (EVIDENCE / 'flash-result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    tool(['read_mac'], after='hard_reset')
    print('Migration and flash verified; rebooted for startup/acoustic checks.', flush=True)

if __name__ == '__main__':
    main()
