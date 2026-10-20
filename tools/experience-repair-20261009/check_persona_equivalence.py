from pathlib import Path
import json,hashlib
S=Path('/root/prjs/tmp/experience-repair-20261009');old=json.loads(Path('/root/prjs/tmp/harness-20261007/private-backup/runtime-config.json').read_text());live=json.loads((S/'live-config-readonly.json').read_text());h=hashlib.sha256(str(old.get('prompt') or '').encode()).hexdigest()
print(json.dumps({'test_persona_hash':h,'live_persona_hash':live['persona_sha256'],'matches':h==live['persona_sha256']}))
(S/'persona-config-equivalence.json').write_text(json.dumps({'test_persona_sha256':h,'live_persona_sha256':live['persona_sha256'],'matches':h==live['persona_sha256']}))
