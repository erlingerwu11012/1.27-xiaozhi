"""Build the local wake-word candidate; never connect to or flash a device."""
from pathlib import Path
import json
import csv
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
STAGE = Path(__file__).parent
EVIDENCE = STAGE / 'evidence'
PYTHON = Path('E:/Espressif/python_env/idf5.5_py3.11_env/Scripts/python.exe')
NINJA = Path('E:/Espressif/tools/ninja/1.12.1/ninja.exe')

def main():
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    EVIDENCE.mkdir(exist_ok=True)
    env = os.environ.copy()
    env['IDF_PATH'] = 'E:/Espressif/frameworks/esp-idf-v5.5.4'
    env['IDF_TOOLS_PATH'] = 'E:/Espressif'
    env['IDF_PYTHON_ENV_PATH'] = str(PYTHON.parent.parent)
    env['CCACHE_DISABLE'] = '1'
    env['PYTHONUTF8'] = '1'
    env['PYTHONIOENCODING'] = 'utf-8'
    env['ESP_ROM_ELF_DIR'] = 'E:/Espressif/tools/esp-rom-elfs/20241011'
    directories = [PYTHON.parent, NINJA.parent,
                   Path('E:/Espressif/tools/cmake/3.30.2/bin'),
                   Path('E:/Espressif/tools/ccache/4.12.1/ccache-4.12.1-windows-x86_64')]
    directories += list(Path('E:/Espressif/tools/xtensa-esp-elf').glob('*/xtensa-esp-elf/bin'))
    directories += list(Path('E:/Espressif/tools/idf-git').glob('*/cmd'))
    env['PATH'] = os.pathsep.join(map(str, directories)) + os.pathsep + env.get('PATH', '')
    with (EVIDENCE / 'firmware-build.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen([str(NINJA), '-C', 'build', '-j', '4'], cwd=ROOT, env=env,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, encoding='utf-8', errors='replace')
        for line in process.stdout:
            log.write(line)
            log.flush()
            if (line.startswith('[') and (any(s in line for s in ('/2]', '/102]', 'Linking', 'Generating binary', 'default assets')))) or any(s in line.lower() for s in ('error:', 'error ', 'binary size', 'overflow', 'failed', 'custom wake word', 'multinet models')):
                print(line, end='', flush=True)
        code = process.wait()
    with (ROOT / 'partitions/v2/16m.csv').open(encoding='utf-8') as partition_file:
        assets_capacity = next(int(row[4].strip(), 0) for row in csv.reader(partition_file)
                               if row and row[0].strip() == 'assets')
    if code == 0 and (ROOT / 'build/generated_assets.bin').stat().st_size > assets_capacity:
        print('ERROR: generated assets exceed the existing assets partition', flush=True)
        code = 1
    (EVIDENCE / 'firmware-build-result.json').write_text(
        json.dumps({'exit_code': code, 'hardware_accepted': False}, indent=2), encoding='utf-8')
    return code

if __name__ == '__main__':
    sys.exit(main())
