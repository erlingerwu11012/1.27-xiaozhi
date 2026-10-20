"""Final reviewed Python-only guard, on top of this published release."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess,time,urllib.request
prod=Path('/root/prjs/xiaozhi-esp32-server');cand=Path('/root/prjs/tmp/bailian-memory-product');release=Path('/root/prjs/tmp/context-memory-release-20260929')
old=json.loads((release/'manifest.json').read_text())
names=['main/xiaozhi-server/core/connection.py','main/xiaozhi-server/core/utils/person_short_memory.py']
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
assert json.loads((release/'published.json').read_text())['published']
for name in names:assert digest(prod/name)==old[name], 'concurrent_change'
folder=release/'final-summary-revision';folder.mkdir(exist_ok=True)
bootstrap="from unittest.mock import MagicMock;import config.logger as log;log.setup_logging=lambda:MagicMock();import sys;sys.path.insert(0,'test');import unittest;unittest.main(module='test_context_memory_200k',verbosity=2)"
with (folder/'tests.log').open('w') as output:
    test=subprocess.run(['/root/miniconda3/envs/xiaozhi-esp32-server/bin/python','-c',bootstrap],cwd=cand/'main/xiaozhi-server',stdout=output,stderr=subprocess.STDOUT)
assert test.returncode==0,'final_guard_test_failed'
for name in names:
    backup=folder/Path(name).name;shutil.copy2(prod/name,backup)
try:
    for name in names:
        target=prod/name;tmp=target.with_name(target.name+'.context-final');shutil.copy2(cand/name,tmp);os.replace(tmp,target)
    subprocess.run(['pm2','restart','xiaozhi-server'],capture_output=True,check=True)
    ready=False
    for _ in range(60):
        try:
            with urllib.request.urlopen('http://127.0.0.1:8006/openapi.json',timeout=2) as response:
                if response.status==200:ready=True;break
        except Exception:pass
        time.sleep(.5)
    assert ready,'voice_not_healthy'
except Exception:
    for name in names:shutil.copy2(folder/Path(name).name,prod/name)
    subprocess.run(['pm2','restart','xiaozhi-server'],capture_output=True)
    raise
for name in names:old[name]=digest(prod/name)
(release/'manifest.json').write_text(json.dumps(old,indent=2))
report={'published':True,'at':time.strftime('%Y-%m-%d %H:%M:%S %z'),'files':{name:digest(prod/name) for name in names},'late_summary_rejected':True}
(folder/'published.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
