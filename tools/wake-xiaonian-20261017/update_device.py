"""Update app and wake config while preserving the device's visual/model assets."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'tools/wake-hi-niannian-20261017'))
from migration import bundle, table_entries

MAC = 'ac:a7:04:fd:20:5c'
COMMAND = {'command': 'ni hao xiao nian', 'text': '你好，小念', 'action': 'wake'}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def backup():
    raw = (OUT / 'device-before.bin').read_bytes()
    if len(raw) != 0xbf8000:
        raise RuntimeError('Incomplete original app/settings/assets backup')
    entries = table_entries(raw[:0x1000])
    expected = {'factory': (0x20000, 0x4f0000), 'assets': (0x530000, 0x6d0000),
                'nvs': (0x9000, 0x10000), 'userdata': (0x510000, 0x20000),
                'spine': (0xc00000, 0x300000), 'wallpaper': (0xf00000, 0x100000)}
    if any(entries.get(k) != v for k, v in expected.items()):
        raise RuntimeError('Unexpected partition map')
    return raw, entries


def package():
    raw, entries = backup()
    if json.loads((OUT / 'firmware-build-result.json').read_text(encoding='utf-8'))['exit_code'] != 0:
        raise RuntimeError('Build did not pass')
    _, files = bundle(raw[0x530000 - 0x8000:])
    index = json.loads(files['index.json'].decode('utf-8'))
    if index['multinet_model']['language'] != 'cn' or b'mn7_cn' not in files[index['srmodels']]:
        raise RuntimeError('Expected existing Chinese MultiNet7 model')
    index['multinet_model']['commands'] = [COMMAND]
    new_index = json.dumps(index, ensure_ascii=False, indent=2).encode('utf-8')
    # Keep following resources at their original alignment modulo four.
    new_index += b' ' * ((len(files['index.json']) - len(new_index)) % 4)
    count = len(files)
    table, data = bytearray(), bytearray()
    original = raw[0x530000 - 0x8000:]
    for i in range(count):
        label, size, offset, width, height = struct.unpack_from('<32sIIHH', original, 12 + i * 44)
        name = label.split(b'\0')[0].decode('utf-8')
        content = new_index if name == 'index.json' else files[name]
        table.extend(struct.pack('<32sIIHH', label, len(content), len(data), width, height))
        data.extend(b'ZZ' + content)
    body = table + data
    assets = struct.pack('<III', count, sum(body) & 0xffff, len(body)) + body
    _, candidate = bundle(assets)
    if any(candidate[k] != v for k, v in files.items() if k != 'index.json'):
        raise RuntimeError('Non-wake resource changed')
    compiled_raw, compiled = bundle((ROOT / 'build/generated_assets.bin').read_bytes())
    compiled_index = json.loads(compiled['index.json'].decode('utf-8'))
    if compiled_index['multinet_model']['commands'] != [COMMAND]:
        raise RuntimeError('Generated assets do not have the new command')
    app = (ROOT / 'build/xiaozhi.bin').read_bytes()
    if len(app) > entries['factory'][1] or len(assets) > entries['assets'][1]:
        raise RuntimeError('Image exceeds partition')
    config = (ROOT / 'build/config/sdkconfig.h').read_text(encoding='utf-8')
    for flag in ['CONFIG_TASK_DIAGNOSTICS_PERIODIC', 'CONFIG_AUDIO_WAKE_DIAGNOSTICS']:
        if '#define ' + flag + ' 1' in config:
            raise RuntimeError('Verbose diagnostics still enabled')
    for flag in ['CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG', 'CONFIG_USE_USB_STREAM']:
        if '#define ' + flag + ' 1' not in config:
            raise RuntimeError('USB console/UVC config changed')
    (OUT / 'xiaozhi.bin').write_bytes(app)
    (OUT / 'assets.bin').write_bytes(assets)
    result = {'mac': MAC, 'wake_command': COMMAND, 'threshold': index['multinet_model']['threshold'],
              'backup_sha256': sha(raw), 'app_sha256': sha(app), 'assets_sha256': sha(assets),
              'app_bytes': len(app), 'assets_bytes': len(assets),
              'preserved_resource_files': [k for k in files if k != 'index.json']}
    (OUT / 'manifest.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


def tool(name, args):
    r = subprocess.run([sys.executable, '-m', 'esptool', '--chip', 'esp32s3', '--port', 'COM11',
        '--baud', '460800', '--before', 'no_reset', '--after', 'no_reset', *args],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (OUT / (name + '.log')).write_bytes(r.stdout)
    if r.returncode:
        raise RuntimeError(name + ' failed; see private log')
    return r.stdout.decode('utf-8', errors='replace')


def flash():
    result = package()
    raw, entries = backup()
    if MAC not in tool('mac-preflash', ['read_mac']):
        raise RuntimeError('Wrong device')
    # Check current settings before writing; a stale backup must never be used.
    for name, start, length in [('protected', 0x8000, 0x12000), ('userdata', 0x510000, 0x20000)]:
        path = OUT / (name + '-preflash.bin')
        tool(name + '-preflash', ['read_flash', hex(start), hex(length), str(path)])
        if path.read_bytes() != raw[start - 0x8000:start - 0x8000 + length]:
            raise RuntimeError('Settings changed after backup')
    output = tool('flash', ['write_flash', '--flash_mode', 'keep', '--flash_freq', 'keep',
        '--flash_size', 'keep', '0x20000', str(OUT / 'xiaozhi.bin'), '0x530000', str(OUT / 'assets.bin')])
    if output.count('Hash of data verified.') != 2:
        raise RuntimeError('Both image hashes must be verified')
    for name, start, length in [('protected', 0x8000, 0x12000), ('userdata', 0x510000, 0x20000)]:
        path = OUT / (name + '-after.bin')
        tool(name + '-after', ['read_flash', hex(start), hex(length), str(path)])
        if path.read_bytes() != raw[start - 0x8000:start - 0x8000 + length]:
            raise RuntimeError('Protected partition changed; keep device in download mode')
    result.update(flashed=True, protected_partitions_unchanged=True, images_hash_verified=True,
                  acoustic_test_passed=False, runtime_verified=False)
    (OUT / 'flash-result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))
    # Leave in download mode; capture/reset startup separately to catch early logs.


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser()
    parser.add_argument('--flash', action='store_true')
    args = parser.parse_args()
    if args.flash:
        flash()
    else:
        print(json.dumps(package(), ensure_ascii=False))
