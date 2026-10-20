"""Isolated modules avoid legacy tests' global CV2/OpenVINO stub pollution."""
import json
import shutil
import subprocess
from pathlib import Path

root=Path('/root/prjs/tmp/bailian-memory-product/main/face-api')
dependencies=Path('/root/prjs/tmp/bailian-face-test-deps-v2')
packages=Path('/root/miniconda3/envs/xiaozhi-esp32-server/lib/python3.10/site-packages')
dependencies.mkdir(exist_ok=True)
for name in ('httpx','httpcore','h11','certifi','idna','sniffio','anyio'):
    if not (dependencies/name).exists():shutil.copytree(packages/name,dependencies/name)
results=[]
with open('/tmp/bailian-memory-face-regression.log','w') as output:
    for module in sorted((root/'tests').glob('test_*.py')):
        command=['docker','run','--rm','--network','none','-v',str(root)+':/app:ro','-v',str(dependencies)+':/testdeps:ro',
            '-e','PYTHONPATH=/testdeps:/app','-e','PYTHONDONTWRITEBYTECODE=1','-e','FACE_ENV=test',
            '-e','FACE_JWT_SECRET=test-only-isolated-secret-not-production','-e','FACE_ALLOW_INSECURE=1',
            '-w','/app','face-api-face-api','python','-m','unittest','discover','-s','tests','-p',module.name,'-v']
        run=subprocess.run(command,capture_output=True,text=True)
        output.write(module.name+'\n'+run.stdout+run.stderr+'\n');output.flush()
        results.append({'module':module.name,'exit_code':run.returncode})
        print(json.dumps(results[-1]),flush=True)
Path('/tmp/bailian-memory-face-results.json').write_text(json.dumps(results,indent=2))
raise SystemExit(any(item['exit_code'] for item in results))
