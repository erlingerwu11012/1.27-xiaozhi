"""Prepare model defaults and candidate build only; production stays unchanged."""
import hashlib,json,shutil,subprocess
from pathlib import Path
OUT=Path('/root/prjs/tmp/natural-dialogue-presets-20261005')
PROD=Path('/root/prjs/xiaozhi-esp32-server');CAND=OUT/'worktree'
relative='main/manager-api/src/main/java/xiaozhi/modules/model/OfficialServiceDefaults.java'
before=(PROD/relative).read_bytes()
assert b'LLM_MODEL_NAME = "qwen3.8-flash"' in before
after=before.replace(b'LLM_MODEL_NAME = "qwen3.8-flash"',b'LLM_MODEL_NAME = "qwen3.8-max"').replace(b'LLM_TEMPERATURE = 0.4',b'LLM_TEMPERATURE = 0.3')
(CAND/relative).write_bytes(after)
# Build the current production API with exactly one Java source modification.
# This avoids unknowingly shipping changes left over in earlier candidates.
for path in (PROD/'main/manager-api/src').rglob('*'):
 if path.is_file() and path.relative_to(PROD).as_posix()!=relative:
  dest=CAND/path.relative_to(PROD);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,dest)
for name in ['pom.xml']:
 shutil.copy2(PROD/'main/manager-api'/name,CAND/'main/manager-api'/name)
cmd=['mvn','-o','-q','-DskipTests=false','-Dtest=OfficialServiceDefaultsTest,HardwareBillingPolicyTest','package']
with (OUT/'complete-chat-java-build.log').open('w') as log:
 r=subprocess.run(cmd,cwd=CAND/'main/manager-api',stdout=log,stderr=subprocess.STDOUT,timeout=240)
report={'success':r.returncode==0,'production_changed':False,'source_sha256':hashlib.sha256(after).hexdigest()}
(OUT/'complete-chat-java-build.json').write_text(json.dumps(report))
print(json.dumps(report))
if r.returncode:print((OUT/'complete-chat-java-build.log').read_text()[-6000:]);raise SystemExit(r.returncode)
