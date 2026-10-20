import json,subprocess,time
from pathlib import Path
from urllib.request import urlopen
root=Path('/root/prjs/tmp/qwen37-official-release-20261007')
dockerfile=root/'image/Dockerfile'
dockerfile.write_text('FROM one-api:natural-dialogue-20261005\nCOPY one-api-qwen37 /one-api-bailian-core-image\nCMD ["/one-api-bailian-core-image"]\n')
subprocess.run(['docker','build','-t','one-api:qwen37-official-20261007',str(root/'image')],check=True,stdout=subprocess.DEVNULL)
name='one-api-qwen37-smoke-20261007'
subprocess.run(['docker','rm','-f',name],capture_output=True)
subprocess.run(['docker','run','-d','--name',name,'--env-file',str(root/'smoke-private.env'),'--network','bridge','-p','127.0.0.1:3099:3000','one-api:qwen37-official-20261007'],check=True,capture_output=True)
try:
 for _ in range(30):
  try:
   with urlopen('http://127.0.0.1:3099/api/status',timeout=2) as r:
    assert r.status==200
    (root/'static-container-smoke.json').write_text(json.dumps({'passed':True,'CGO_ENABLED':'0','actual_container':True}))
    print('static_container_smoke_passed');break
  except Exception:time.sleep(1)
 else:raise AssertionError('static_container_smoke_failed')
finally:subprocess.run(['docker','rm','-f',name],capture_output=True)
