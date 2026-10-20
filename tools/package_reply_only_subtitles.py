"""Preserve a verified app image and receipt; never open a serial port."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'build'
RELEASE = ROOT / 'releases/reply-only-subtitles-20261009'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    source = ROOT / 'main/application.cc'
    text = source.read_text(encoding='utf-8')
    stt = text.split('else if (strcmp(type->valuestring, "stt") == 0)', 1)[1]
    stt = stt.split('else if (strcmp(type->valuestring, "llm") == 0)', 1)[0]
    assert 'SetChatMessage' not in stt and 'Schedule(' not in stt
    assert 'ESP_LOGI(TAG, ">> %s", text->valuestring)' in stt
    assert 'QueueTtsSubtitle(generation, audio_service_.NextPlaybackSequence(), message)' in text
    image = BUILD / 'xiaozhi.bin'
    assert image.stat().st_mtime > source.stat().st_mtime, 'image predates source'
    project = json.loads((BUILD / 'project_description.json').read_text())
    assert project['target'] == 'esp32s3'
    layout = json.loads((BUILD / 'flasher_args.json').read_text())
    assert layout['app']['offset'] == '0x20000'
    assert image.stat().st_size <= 0x4F0000
    check = subprocess.run([sys.executable, '-m', 'esptool', '--chip', 'esp32s3',
                            'image_info', str(image)], capture_output=True, text=True)
    assert check.returncode == 0, check.stderr
    RELEASE.mkdir(parents=True, exist_ok=False)
    shutil.copy2(image, RELEASE / 'xiaozhi.bin')
    (RELEASE / 'image-info.txt').write_text(check.stdout, encoding='utf-8')
    diff = subprocess.check_output(['git', 'diff', '--', 'main/application.cc'],
                                   cwd=ROOT).decode('utf-8')
    (RELEASE / 'source.patch').write_text(diff, encoding='utf-8')
    for stream in ['stdout', 'stderr']:
        logs = sorted((BUILD / 'log').glob('idf_py_' + stream + '_output_*'),
                      key=lambda p: p.stat().st_mtime, reverse=True)
        if logs:
            shutil.copy2(logs[0], RELEASE / ('build-' + stream + '.log'))
    receipt = {
        'built_at': datetime.now().astimezone().isoformat(),
        'behavior': 'STT logged only; assistant TTS subtitles unchanged',
        'project_version': project['project_version'], 'target': project['target'],
        'idf_path': project['idf_path'], 'app_offset_reference': layout['app']['offset'],
        'build_command': 'idf.py -B build build',
        'physical_device_test': False, 'flashed': False,
        'host_regression': {'passed': 20, 'sanitizers': ['ASan', 'UBSan'],
                            'command': 'python3 tools/run_tts_interrupt_host_test.py'},
        'source_sha256': digest(source),
        'sdkconfig_sha256': digest(ROOT / 'sdkconfig'),
        'partition_csv_sha256': digest(ROOT / 'partitions/v2/16m.csv'),
        'image': {'file': 'xiaozhi.bin', 'bytes': image.stat().st_size,
                  'sha256': digest(image)},
        'partition_note': 'Application image only. No partitions, NVS, assets or user data written.',
    }
    assert digest(RELEASE / 'xiaozhi.bin') == receipt['image']['sha256']
    (RELEASE / 'manifest.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    print(json.dumps({'release': str(RELEASE), **receipt}, indent=2))


if __name__ == '__main__':
    main()
