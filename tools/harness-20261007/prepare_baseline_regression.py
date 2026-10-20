"""Prepare an immutable pre-change tree for comparing existing test failures."""
import json,os,shutil,tarfile
from pathlib import Path
p=Path(__file__).parent;target=p/'baseline-regression';work=target/'work'
target.mkdir(mode=0o700,exist_ok=True);work.mkdir(exist_ok=True)
with tarfile.open(p/'source.tgz') as archive:archive.extractall(work)
root=Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server')
for rel in ['config.yaml','data/.config.yaml','data/.mcp_server_settings.json','agent-base-prompt-v2.txt']:
    if (root/rel).exists():
        (work/rel).parent.mkdir(exist_ok=True,parents=True)
        shutil.copy2(root/rel,work/rel);os.chmod(work/rel,0o600)
for rel in ['config/assets','models']:
    if (root/rel).exists() and not (work/rel).exists():(work/rel).symlink_to(root/rel,target_is_directory=True)
for file in ['bootstrap.py','run_regressions.py']:shutil.copy2(p/file,target/file)
print(json.dumps({'prepared':str(target)}))
