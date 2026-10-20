"""Save a reviewed source-only baseline; never stage production data/configs."""
import json, subprocess, sys, re
from pathlib import Path

root = Path(sys.argv[1]).resolve()
server = (root / 'main/manager-api').exists()
def git(*args):
    return subprocess.check_output(['git', '-C', str(root), *args])
status = git('status', '--porcelain=v1', '-z').split(b'\0')
selected=[]
for entry in status:
    if not entry: continue
    name=entry[3:].decode('utf-8')
    p=root/name
    if server:
        allowed=(name.startswith(('main/manager-api/src/main/java/', 'main/manager-api/src/main/resources/db/',
           'main/manager-api/src/test/java/', 'main/manager-web/src/', 'main/face-api/app/', 'main/face-api/tests/',
           'main/xiaozhi-server/core/', 'main/xiaozhi-server/plugins_func/', 'main/xiaozhi-server/test/'))
           or name=='main/xiaozhi-server/config/manage_api_client.py')
    else:
        allowed=name.startswith(('main/','components/','tools/','docs/')) or name=='.gitignore'
        allowed=allowed and 'delivery/' not in name and 'artifacts/' not in name
    if not allowed: continue
    files=[p] if not p.is_dir() else list(p.rglob('*'))
    for f in files:
        rel=f.relative_to(root).as_posix()
        if f.is_dir(): continue
        if f.suffix.lower() not in {'.py','.cjs','.js','.vue','.java','.sql','.yaml','.h','.cc','.cpp','.c','.md','.ogg','.txt','.yml'} and f.name not in {'.gitignore','LICENSE'}: continue
        if '__pycache__' in rel or f.name in {'config.yaml','application.yml','application-dev.yml'} or 'private' in f.name.lower(): continue
        if f.exists() and f.suffix!='.ogg':
            data=f.read_bytes()
            if re.search(rb'^-----BEGIN (?:RSA |EC )?PRIVATE KEY-----',data,re.M): raise RuntimeError('private_key_in_source: '+rel)
        selected.append(rel)
if selected:
    for start in range(0,len(selected),60):
        subprocess.run(['git','-C',str(root),'add','--',*selected[start:start+60]],check=True)
    subprocess.run(['git','-C',str(root),'commit','-m','chore: preserve tested identity memory and voice baseline before continuity upgrade'],check=True)
print(json.dumps({'repository':root.name,'files':len(selected),'commit':git('rev-parse','HEAD').decode().strip()}))
