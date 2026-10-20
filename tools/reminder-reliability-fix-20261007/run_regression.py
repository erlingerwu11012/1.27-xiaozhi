import json, os, re, subprocess, sys
from pathlib import Path
root = Path(__file__).parent / 'candidate/main/xiaozhi-server'
names = ['reminder_reliability', 'operation_control', 'operation_pipeline',
         'unified_recipient_outbound', 'reminder_interaction', 'reminder_voice',
         'reminder_voice_abort', 'reminder_voice_download', 'device_send_auth',
         'qwen_audio_tts_plus', 'recipient_resolver', 'device_reminder']
results = []
for name in names:
    p = subprocess.run([sys.executable, str(Path(__file__).parent / 'offline_test.py'), name], cwd=root,
                       capture_output=True, text=True, timeout=100)
    log = p.stdout + p.stderr
    (Path(__file__).parent / ('test-'+name+'.log')).write_text(log)
    count = re.search(r'Ran (\d+) tests?', log)
    # The two older script suites implement explicit PASS/FAIL counters.
    failed = p.returncode != 0 or '[FAIL]' in log
    row = {'suite': name, 'exit_code': p.returncode, 'passed': not failed,
           'test_count': int(count[1]) if count else log.count('[PASS]')}
    results.append(row)
    print(json.dumps(row), flush=True)
    if failed:
        print(log[-7000:], flush=True)
(Path(__file__).parent / 'test-results.json').write_text(json.dumps(results, indent=2))
sys.exit(0 if all(r['passed'] for r in results) else 1)
