"""Exercise production wake methods with AFE/MultiNet fault injection, not acoustic inference."""
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from run_ws_audio_send_host_test import function

def main():
    compiler = shutil.which('g++') or shutil.which('clang++')
    if not compiler:
        raise SystemExit('Run with a host C++ compiler, for example Python in WSL')
    source = (Path(__file__).parent / 'wake_host.cpp').read_text(encoding='utf-8')
    production = (ROOT / 'main/audio/wake_words/custom_wake_word.cc').read_text(encoding='utf-8')
    timeout = re.search(r'constexpr int kFetchTimeoutMs = \d+;', production).group(0)
    source = source.replace('// @FETCH_TIMEOUT', timeout)
    for marker, path in [('BASE', 'main/audio/wake_word.h'), ('CLASS', 'main/audio/wake_words/custom_wake_word.h')]:
        header = (ROOT / path).read_text(encoding='utf-8')
        source = source.replace('// @' + marker, re.sub(r'^#include[^\n]*', '', header, flags=re.M))
    methods = [function('main/audio/wake_words/custom_wake_word.cc', sig) for sig in (
        'void CustomWakeWord::Start(', 'void CustomWakeWord::Stop(',
        'void CustomWakeWord::Feed(', 'void CustomWakeWord::AudioDetectionTask(',
        'void CustomWakeWord::DetectProcessedAudio(', 'size_t CustomWakeWord::GetFeedSize(',
        'void CustomWakeWord::StoreWakeWordData(', 'void CustomWakeWord::OnWakeWordDetected(')]
    source = source.replace('// @METHODS', '\n\n'.join(methods))
    out = ROOT / 'build/wake_dialogue_fix_host'
    out.mkdir(parents=True, exist_ok=True)
    generated, binary = out / 'test.cpp', out / 'test'
    generated.write_text(source, encoding='utf-8')
    subprocess.run([compiler, '-std=c++17', '-O1', '-g', '-pthread',
                    '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                    '-fno-omit-frame-pointer', str(generated), '-o', str(binary)], check=True)
    result = subprocess.run([str(binary)], text=True, capture_output=True, timeout=30)
    evidence = Path(__file__).parent / 'evidence'
    evidence.mkdir(exist_ok=True)
    (evidence / 'wake-host.log').write_text(result.stdout + result.stderr, encoding='utf-8')
    print(result.stdout + result.stderr, end='')
    result.check_returncode()

if __name__ == '__main__':
    main()
