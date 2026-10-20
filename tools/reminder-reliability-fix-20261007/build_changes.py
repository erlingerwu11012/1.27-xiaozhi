import hashlib, json, tarfile
from pathlib import Path
root = Path(__file__).parent
sources = [
    'core/utils/recipient_resolver.py', 'core/utils/unified_recipient_resolver.py',
    'core/utils/tool_result.py', 'core/utils/device_reminder.py',
    'core/utils/reminder_voice.py', 'core/utils/operation_control.py',
    'core/utils/reminder_tool_contracts.py', 'core/utils/reply_repetition.py',
    'core/providers/tools/unified_tool_manager.py',
    'core/providers/tools/device_mcp/mcp_executor.py',
    'core/providers/tts/qwen_audio_tts_plus.py',
]
tests = ['test/test_reminder_reliability.py', 'test/test_operation_control.py',
         'test/test_operation_pipeline.py', 'test/test_recipient_resolver.py',
         'test/test_device_reminder.py', 'test/test_qwen_audio_tts_plus.py']
def digest(data):
    return hashlib.sha256(data).hexdigest()
manifest = []
with tarfile.open(root / 'source.tgz') as baseline:
    members = {m.name.removeprefix('./'): m for m in baseline.getmembers() if m.isfile()}
    for path in sources + tests:
        old = baseline.extractfile(members[path]).read() if path in members else None
        new = (root / path).read_bytes()
        if old != new:
            manifest.append({'path': path, 'baseline_sha256': digest(old) if old is not None else None,
                             'candidate_sha256': digest(new)})
(root / 'manifest.json').write_text(json.dumps(manifest, indent=2))
with tarfile.open(root / 'changes.tgz', 'w:gz') as out:
    for row in manifest:
        out.add(root / row['path'], arcname=row['path'])
print(json.dumps({'files': [r['path'] for r in manifest]}, indent=2))
