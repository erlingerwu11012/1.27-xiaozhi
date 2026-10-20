import hashlib,json,tarfile
from pathlib import Path
p=Path(__file__).parent
files=['core/connection.py','config/config_loader.py','core/providers/llm/openai/openai.py','core/handle/receiveAudioHandle.py','core/utils/tool_result.py','core/utils/device_reminder.py','test/test_account_owner_and_reminder.py','test/test_official_service_defaults.py']+[str(x.relative_to(p/'candidate')).replace('\\','/') for x in (p/'candidate/core/utils/tool_harness').glob('*.py')]
with tarfile.open(p/'candidate.tgz','w:gz') as archive:
    for f in files:archive.add(p/'candidate'/f,arcname=f)
manifest={f:hashlib.sha256((p/'candidate'/f).read_bytes()).hexdigest() for f in files}
(p/'candidate-manifest.json').write_text(json.dumps(manifest,indent=2))
print(json.dumps({'files':len(files),'code_sha256':hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest()}))
