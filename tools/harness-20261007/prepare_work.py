import json,os,shutil,tarfile
from pathlib import Path
stage=Path(__file__).parent;root=Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server');work=stage/'work'
work.mkdir(exist_ok=True)
with tarfile.open(stage/'source.tgz') as archive:archive.extractall(work)
with tarfile.open(stage/'candidate.tgz') as archive:archive.extractall(work)
(work/'data').mkdir(exist_ok=True)
for rel in ['config.yaml','data/.config.yaml','data/.mcp_server_settings.json','agent-base-prompt-v2.txt']:
    if (root/rel).exists():shutil.copy2(root/rel,work/rel);os.chmod(work/rel,0o600)
for rel in ['config/assets']:
    if not (work/rel).exists():(work/rel).symlink_to(root/rel,target_is_directory=True)
print(json.dumps({'candidate_prepared':True}))
