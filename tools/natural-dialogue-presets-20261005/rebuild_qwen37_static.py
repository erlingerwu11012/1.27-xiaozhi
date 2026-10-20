import hashlib,json,os,shutil,subprocess
from pathlib import Path
root=Path('/root/prjs/tmp/qwen37-official-release-20261007')
copy=Path('/root/prjs/tmp/complete-chat-review-20261006/docs/deployments')
original=Path('/root/prjs/xiaozhi-esp32-server/docs/deployments')
assert copy.resolve()==copy and str(copy).startswith('/root/prjs/tmp/complete-chat-review-20261006/')
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.digest()
freed=0
if original.exists():
 for p in copy.rglob('*'):
  other=original/p.relative_to(copy)
  if p.is_file() and other.is_file() and p.stat().st_size==other.stat().st_size and sha(p)==sha(other):
   freed+=p.stat().st_size;p.unlink()
print(json.dumps({'removed_only_identical_copied_deployment_artifacts_bytes':freed,'originals_preserved':True}),flush=True)
cache=root/'static-go-cache';env=dict(os.environ,CGO_ENABLED='0',GOCACHE=str(cache))
with (root/'gateway-static-build.log').open('w') as out:
 p=subprocess.run(['/usr/local/go/bin/go','build','-trimpath','-ldflags=-s -w','-o',str(root/'image/one-api-qwen37'),'.'],cwd=root/'gateway',env=env,stdout=out,stderr=subprocess.STDOUT,timeout=300)
assert p.returncode==0,'static_build_failed'
shutil.copy2(root/'image/one-api-qwen37',root/'one-api-qwen37')
assert str(cache.resolve()).startswith(str(root)+'/');shutil.rmtree(cache)
p=subprocess.run(['docker','build','-t','one-api:qwen37-official-20261007',str(root/'image')],capture_output=True,text=True,timeout=90)
(root/'docker-static-build.log').write_text(p.stdout+p.stderr);assert p.returncode==0
# Test the actual Alpine image starts and reads the existing production DB;
# no bill or customer actions occur. Bind only on a local temporary port.
inspection=json.loads(subprocess.check_output(['docker','inspect','one-api'],text=True))[0]
envfile=root/'smoke-private.env';envfile.write_text('\n'.join(inspection['Config']['Env'])+'\n');envfile.chmod(0o600)
name='one-api-qwen37-smoke-20261007'
subprocess.run(['docker','run','-d','--name',name,'--env-file',str(envfile),'--network',inspection['HostConfig']['NetworkMode'],'-p','127.0.0.1:3099:3000','one-api:qwen37-official-20261007'],check=True,capture_output=True)
import time
from urllib.request import urlopen
try:
 for _ in range(30):
  try:
   with urlopen('http://127.0.0.1:3099/api/status',timeout=2) as r:
    assert r.status==200;(root/'static-container-smoke.json').write_text(json.dumps({'passed':True,'CGO_ENABLED':'0','actual_container':True}));print('static_container_smoke_passed',flush=True);break
  except Exception:time.sleep(1)
 else:raise AssertionError('static_container_smoke_failed')
finally:subprocess.run(['docker','rm','-f',name],capture_output=True)
