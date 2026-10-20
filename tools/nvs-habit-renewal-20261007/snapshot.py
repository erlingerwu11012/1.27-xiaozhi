import hashlib, json, os, shutil, subprocess, tarfile
from pathlib import Path
stage=Path('/root/prjs/tmp/nvs-habit-renewal-20261007')
stage.mkdir(parents=True,exist_ok=True)
os.chmod(stage,0o700)
repo=Path('/root/prjs/xiaozhi-esp32-server')
gateway=Path('/root/prjs/xiaozhi_mcp_gateway')
files=[]
for base,prefix in [(repo/'main/manager-api/src/main/java','main/manager-api/src/main/java'),(repo/'main/manager-web/src','main/manager-web/src'),(repo/'main/xiaozhi-server','main/xiaozhi-server'),(gateway,'gateway')]:
    for p in base.rglob('*'):
        if p.is_file() and p.suffix in {'.py','.java','.vue','.js','.json','.xml'} and not any(x in p.parts for x in ('node_modules','target','data','.git','__pycache__')):
            files.append((p, str(Path(prefix)/p.relative_to(base))))
for rel in ['main/manager-api/pom.xml','main/manager-web/package.json','main/manager-web/package-lock.json']:
    p=repo/rel
    if p.exists(): files.append((p,rel))
with tarfile.open(stage/'source.tgz','w:gz') as tar:
    for p,rel in files: tar.add(p,arcname=rel)
baseline={rel:hashlib.sha256(p.read_bytes()).hexdigest() for p,rel in files}
(stage/'baseline.json').write_text(json.dumps(baseline,indent=2))
backup=stage/'private-backup'
backup.mkdir(exist_ok=True);os.chmod(backup,0o700)
for p in [repo/'main/xiaozhi-server/data/.config.yaml',repo/'main/manager-api/target/manager-api.jar']:
    if p.exists(): shutil.copy2(p,backup/p.name)
print(json.dumps({'source_files':len(files),'backup':str(backup)}))
