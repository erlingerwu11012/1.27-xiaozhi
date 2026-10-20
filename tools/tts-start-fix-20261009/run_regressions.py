"""Run offline suites in separate processes; retain logs and frame evidence."""
import hashlib
import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

root = Path(sys.argv[1]).resolve()
out = root / 'test-results'
out.mkdir(exist_ok=True)
patterns = [
    'test_qwen_tts_device_start.py',
    'test_qwen_audio_tts_plus.py',
    'test_official_tts_compiler.py',
    'test_tts_subtitle.py',
    'test_tts_listen_observe.py',
    'test_tts_sentence_telemetry.py',
    'test_reminder_voice_abort.py',
]
report = {
    'timestamp': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
    'hardware': False,
    'synthesis': 'fixed PCM stub; real Opus encoder/decoder',
    'transport': 'loopback aiohttp WebSocket; production TTS threads/queues/sender',
    'uplink_scope': 'protocol-v2 frames counted at loopback endpoint; no real ASR/Harness',
    'baseline': 'Before fix both official and legacy second replies omitted start; two failing assertions',
    'provider_sha256': hashlib.sha256((root / 'core/providers/tts/qwen_audio_tts_plus.py').read_bytes()).hexdigest(),
    'suites': [],
    'device_evidence': [],
}
for pattern in patterns:
    started = time.monotonic()
    result = subprocess.run(
        [sys.executable, '-m', 'unittest', 'discover', '-s', 'test', '-p', pattern, '-v'],
        cwd=root, capture_output=True, text=True, timeout=120)
    output = result.stdout + '\n' + result.stderr
    (out / (pattern + '.log')).write_text(output, encoding='utf-8')
    count = re.search(r'Ran (\d+) tests?', output)
    row = {'pattern': pattern, 'tests': int(count.group(1)) if count else 0,
           'exit_code': result.returncode, 'seconds': round(time.monotonic() - started, 3)}
    report['suites'].append(row)
    for evidence in re.findall(r'TTS_DEVICE_EVIDENCE (\{[^\n]+\})', result.stdout):
        report['device_evidence'].append(json.loads(evidence))
    print(json.dumps(row), flush=True)
    if result.returncode:
        print(output[-9000:], flush=True)
    report['tests'] = sum(s['tests'] for s in report['suites'])
    report['passed'] = all(s['exit_code'] == 0 and s['tests'] > 0 for s in report['suites'])
    (out / 'test-report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print('RESULT', json.dumps({'tests': report['tests'], 'passed': report['passed']}), flush=True)
raise SystemExit(0 if report['passed'] else 1)
