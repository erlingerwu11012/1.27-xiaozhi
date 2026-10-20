"""Publish the default-local-only policy with source and jar rollback."""
import ast
import hashlib
import json
import os
import shutil
import subprocess
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

root = Path('/root/prjs/xiaozhi-esp32-server/main')
release = Path('/root/prjs/tmp/default-local-only-20260930')
voice = release / 'voice'
candidate = release / 'manager-api'
backup = release / 'before'
files = [
    ('voice/core/utils/person_identity.py', root/'xiaozhi-server/core/utils/person_identity.py'),
    ('voice/core/utils/recent_memory.py', root/'xiaozhi-server/core/utils/recent_memory.py'),
    ('voice/core/providers/memory/bailian/bailian.py', root/'xiaozhi-server/core/providers/memory/bailian/bailian.py'),
    ('voice/core/connection.py', root/'xiaozhi-server/core/connection.py'),
    ('manager-api/src/main/java/xiaozhi/modules/personmemory/PersonMemoryService.java', root/'manager-api/src/main/java/xiaozhi/modules/personmemory/PersonMemoryService.java'),
    ('manager-api/src/main/java/xiaozhi/modules/personmemory/MemoryDailyWorker.java', root/'manager-api/src/main/java/xiaozhi/modules/personmemory/MemoryDailyWorker.java'),
]
jar = root/'manager-api/target/xiaozhi-esp32-api.jar'
next_jar = candidate/'target/xiaozhi-esp32-api.jar'

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def install(src, dst):
    tmp = dst.with_name(dst.name+'.default-local-next')
    shutil.copy2(src,tmp)
    os.replace(tmp,dst)

def run(command):
    result=subprocess.run(command,capture_output=True,text=True)
    if result.returncode:
        raise RuntimeError('command_failed:'+command[0]+':'+str(result.returncode))

def wait(url, required, seconds=100):
    until=time.monotonic()+seconds
    while time.monotonic()<until:
        try:
            with urllib.request.urlopen(url,timeout=3) as response:
                if response.status==200 and required(json.loads(response.read())):return
        except Exception:pass
        time.sleep(1)
    raise RuntimeError('health_timeout:'+url)

if (release/'published.json').exists():raise RuntimeError('already_published')
if not next_jar.is_file() or next_jar.stat().st_size<100000000:raise RuntimeError('candidate_jar_missing')
for source, target in files:
    current=release/source
    if not current.is_file() or not target.is_file():raise RuntimeError('source_missing:'+source)
    if source.endswith('.py'):ast.parse(current.read_text(encoding='utf-8'))
backup.mkdir(exist_ok=False)
manifest={}
for source,target in files:
    saved=backup/source
    saved.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(target,saved)
    manifest[source]={'before':sha(saved),'after':sha(release/source)}
shutil.copy2(jar,backup/'manager-api.jar')
manifest['jar']={'before':sha(backup/'manager-api.jar'),'after':sha(next_jar)}
(release/'manifest.json').write_text(json.dumps(manifest,indent=2))

try:
    run(['pm2','stop','manager-api','xiaozhi-server'])
    for source,target in files:install(release/source,target)
    install(next_jar,jar)
    for source,target in files:
        if sha(target)!=manifest[source]['after']:raise RuntimeError('hash_mismatch:'+source)
    if sha(jar)!=manifest['jar']['after']:raise RuntimeError('jar_hash_mismatch')
    run(['pm2','restart','manager-api'])
    wait('http://127.0.0.1:8002/xiaozhi/user/pub-config',lambda value:value.get('code')==0)
    run(['pm2','restart','xiaozhi-server'])
    wait('http://127.0.0.1:8006/openapi.json',lambda value:'/api/v1/device/send' in value.get('paths',{}))
    run(['pm2','save'])
    states={item['name']:item['pm2_env']['status'] for item in json.loads(subprocess.check_output(['pm2','jlist'])) if item['name'] in ('manager-api','xiaozhi-server')}
    if states!={'manager-api':'online','xiaozhi-server':'online'}:raise RuntimeError('pm2_not_online')
    report={'published':True,'at_utc':datetime.now(timezone.utc).isoformat(),'service_states':states,'source_count':len(files),'jar_sha256':sha(jar),'portrait_unchanged':True,'firmware_unchanged':True}
    (release/'published.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report))
except Exception as error:
    for source,target in files:install(backup/source,target)
    install(backup/'manager-api.jar',jar)
    subprocess.run(['pm2','restart','manager-api','xiaozhi-server'],capture_output=True)
    (release/'failed.json').write_text(json.dumps({'rolled_back_sources_and_jar':True,'reason':str(error)}))
    raise
