"""Emergency executable rollback; financial ledger, deletions and additive schema are retained."""
import os,json,tarfile,shutil,subprocess
from pathlib import Path
out=Path('/root/prjs/tmp/memory-continuity-release-20260930');root=Path('/root/prjs/xiaozhi-esp32-server')
assert json.loads((out/'published.json').read_text())['published']
subprocess.run(['pm2','stop','manager-api','xiaozhi-server'],check=True)
with tarfile.open(out/'source-before.tar.gz') as bundle:
 for member in bundle.getmembers():
  assert member.isfile() and not member.name.startswith('/') and '..' not in Path(member.name).parts
  target=root/member.name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(bundle.extractfile(member).read())
for name,digest in json.loads((out/'baseline.json').read_text()).items():
 if digest is None and (root/name).exists():(root/name).unlink()
shutil.copy2(out/'manager-api-before.jar',root/'main/manager-api/target/xiaozhi-esp32-api.jar')
env=dict(os.environ);env['MEMORY_PRODUCT_ENABLED']='false';env['MEMORY_PORTRAIT_ENABLED']='false'
subprocess.run(['pm2','restart','manager-api','--update-env'],env=env,check=True)
subprocess.run(['pm2','restart','xiaozhi-server'],check=True)
print(json.dumps({'executables_rolled_back':True,'memory_cloud_disabled':True,'deleted_content_not_restored':True,'ledger_retained':True,'schema_retained':True}))
