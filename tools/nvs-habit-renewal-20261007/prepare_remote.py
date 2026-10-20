import hashlib,json,os,shutil,tarfile
from pathlib import Path
stage=Path(__file__).parent;repo=Path('/root/prjs/xiaozhi-esp32-server')
with tarfile.open(stage/'changes.tgz') as tar:
    if any(m.name.startswith('/') or '..' in Path(m.name).parts or m.issym() or m.islnk() for m in tar.getmembers()):raise RuntimeError('unsafe archive')
    tar.extractall(stage/'candidate')
# Full independent server/API/web candidates; never mutate production during tests.
for name in ('xiaozhi-server','manager-api','manager-web'):
    target=stage/'work'/name
    if not target.exists():shutil.copytree(repo/'main'/name,target,ignore=shutil.ignore_patterns('node_modules','target','logs','tmp','__pycache__','.git'))
    for p in (stage/'candidate/main'/name).rglob('*'):
        if p.is_file():
            dst=target/p.relative_to(stage/'candidate/main'/name);dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dst)
web=stage/'work/manager-web'
if not (web/'node_modules').exists():os.symlink(repo/'main/manager-web/node_modules',web/'node_modules',target_is_directory=True)
gw=stage/'work/gateway'
if not gw.exists():shutil.copytree('/root/prjs/xiaozhi_mcp_gateway',gw,ignore=shutil.ignore_patterns('logs','__pycache__','*.log','mcp_context'))
for p in (stage/'candidate/gateway').rglob('*.py'):
    dst=gw/p.relative_to(stage/'candidate/gateway');dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dst)
print('isolated candidates prepared')
