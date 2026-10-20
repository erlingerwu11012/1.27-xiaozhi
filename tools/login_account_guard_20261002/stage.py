"""Server-side isolated build. Production source/static files remain unchanged."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import sys

WORK=Path('/root/prjs/tmp/login-account-guard-20261002')
PROD=Path('/root/prjs/xiaozhi-esp32-server/main/manager-web')
BASELINE='ab9bc9d710460bd9ed68af7da2baa9f6c22d27191e934427b958d0106603a0f0'
def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()
if digest(PROD/'src/views/login.vue')!=BASELINE: raise RuntimeError('production login source changed')
candidate=WORK/'candidate'
if candidate.exists():
    if '--rebuild' not in sys.argv or not (candidate/'node_modules').is_symlink():
        raise RuntimeError('candidate already exists; explicit rebuild required')
else:
    shutil.copytree(PROD,candidate,ignore=shutil.ignore_patterns('node_modules','dist','logs','*.log','.git'))
    (candidate/'node_modules').symlink_to(PROD/'node_modules',target_is_directory=True)
shutil.copyfile(WORK/'login.after.vue',candidate/'src/views/login.vue')
env=os.environ.copy();env['VUE_APP_API_BASE_URL']='https://api.realecho.cn/xiaozhi'
with (WORK/'build.log').open('w') as log:
    result=subprocess.run(['npm','run','build'],cwd=candidate,env=env,stdout=log,stderr=subprocess.STDOUT)
if result.returncode: raise RuntimeError('build failed; see build.log')
dist=candidate/'dist'
index=(dist/'index.html').read_text()
import re
app=re.search(r'src="(/js/app[^" ]+\.js)"',index).group(1)
bundle=(dist/app.lstrip('/')).read_text()
if 'https://api.realecho.cn/xiaozhi' not in bundle or '.VUE_APP_API_BASE_URL' in bundle:
    raise RuntimeError('production API URL not compiled correctly')
chunks=[p for p in (dist/'js').glob('*.js') if 'credentialGuardReady' in p.read_text()]
if len(chunks)!=1: raise RuntimeError('missing/ambiguous login guard chunk')
with tarfile.open(WORK/'candidate-dist.tar.gz','w:gz') as tar: tar.add(dist,arcname='dist')
receipt=dict(built=True,source_before=BASELINE,source_after=digest(candidate/'src/views/login.vue'),
             app=app,login_chunk=chunks[0].name,index_sha256=digest(dist/'index.html'),
             dist_archive_sha256=digest(WORK/'candidate-dist.tar.gz'))
(WORK/'build-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(receipt,indent=2))
