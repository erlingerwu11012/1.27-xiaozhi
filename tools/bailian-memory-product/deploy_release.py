"""Publish the tested server stage; never publish firmware or enable portraits."""
import fcntl
import hashlib
import json
import os
import secrets
import shlex
import shutil
import subprocess
import tarfile
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

os.umask(0o077)
release=Path('/root/prjs/tmp/bailian-memory-release-20260929')
production=Path('/root/prjs/xiaozhi-esp32-server')
lock=(release/'publish.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
prepared=json.loads((release/'prepared.json').read_text())
if (release/'published.json').exists():raise SystemExit('Already published; use the verification script.')
for name,digest in prepared['artifacts'].items():assert hashlib.sha256((release/name).read_bytes()).hexdigest()==digest,name
for path in ['/tmp/bailian-memory-boot-smoke-result.json','/tmp/bailian-memory-mysql-ledger-result.json','/tmp/bailian-memory-model-tool-result.json','/tmp/bailian-memory-frontend-result.json']:
    assert json.loads(Path(path).read_text())['passed'],path
for path in ['/tmp/bailian-memory-face-results.json','/tmp/bailian-memory-python-regression-result.json']:
    assert all(row.get('exit_code',row.get('exit'))==0 for row in json.loads(Path(path).read_text())),path
reports=[ET.parse(path).getroot() for path in Path('/root/prjs/tmp/bailian-memory-product/main/manager-api/target/surefire-reports').glob('TEST-*.xml')]
assert sum(int(row.get('tests','0')) for row in reports)>=190
assert all(int(row.get('failures','0'))==0 and int(row.get('errors','0'))==0 and int(row.get('skipped','0'))==0 for row in reports)
assert 'FAIL' not in Path('/tmp/bailian-memory-all-go-tests.log').read_text()
assert '\nPASS\n' in Path('/tmp/bailian-memory-real-cloud.log').read_text()

def run(command,log):
    with (release/log).open('a') as output:result=subprocess.run(command,stdout=output,stderr=subprocess.STDOUT)
    if result.returncode:raise RuntimeError('release step failed: '+log)
    print(json.dumps({'step':log,'ok':True}),flush=True)
def write_atomic(path,content,mode=0o600):
    tmp=path.with_name(path.name+'.memory-new');tmp.write_text(content);tmp.chmod(mode);os.replace(tmp,path)
def install(source,target,mode=0o644):
    target.parent.mkdir(parents=True,exist_ok=True)
    tmp=target.with_name(target.name+'.memory-new');shutil.copyfile(source,tmp);tmp.chmod(mode);os.replace(tmp,target)
def overlay(archive,root):
    with tarfile.open(archive) as bundle:
        for entry in bundle.getmembers():
            assert not entry.name.startswith('/') and '..' not in Path(entry.name).parts
            if entry.isdir():
                (root/entry.name).mkdir(parents=True,exist_ok=True)
                continue
            assert entry.isfile()
            target=root/entry.name;target.parent.mkdir(parents=True,exist_ok=True)
            tmp=target.with_name(target.name+'.memory-new')
            with tmp.open('wb') as output:shutil.copyfileobj(bundle.extractfile(entry),output)
            tmp.chmod(entry.mode & 0o777);os.replace(tmp,target)
def wait(url,success,seconds=60):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        try:
            with urllib.request.urlopen(url,timeout=3) as response:
                if success(response.read()):return
        except (OSError,ValueError):pass
        time.sleep(1)
    raise RuntimeError('health check failed: '+url)
def env_file(path):
    result={}
    for line in path.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith('#'):continue
        values=shlex.split(line)
        if values and values[0]=='export':values=values[1:]
        for value in values:
            if '=' in value:key,text=value.split('=',1);result[key]=text
    return result
mysql=['docker','exec','-i','xiaozhi-esp32-server-db','sh','-c','exec env MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --user=root --batch --raw --skip-column-names']
def sql(query):return subprocess.run(mysql,input=query,text=True,capture_output=True,check=True).stdout.strip()
manifest=json.loads(Path('/tmp/bailian-memory-delivery-manifest.json').read_text())
for component,root in [('server',production),('gateway',Path('/root/prjs/one-api-bailian'))]:
    for name,base in manifest[component]['base_files'].items():
        path=root/name;current=hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
        assert current in (base,manifest[component]['files'][name]),'concurrent source change: '+name

gateway_env=Path('/etc/one-api-bailian.env')
environment=env_file(gateway_env)
secret=secrets.token_hex(32)
environment.update(BAILIAN_MEMORY_BILLING='1',BAILIAN_MEMORY_SERVICE_SECRET=secret,
    BAILIAN_MEMORY_RULES_VERIFIED='1',BAILIAN_MEMORY_DEFAULT_FACT_STRATEGY='lite',
    BAILIAN_MEMORY_FACT_LITE_PROJECT_ID='e3a1924778904ce1bd113cec24c30f7d',BAILIAN_MEMORY_STORAGE_COUNT_VERIFIED='1',
    BAILIAN_MEMORY_TOP_K='5',BAILIAN_MEMORY_PORTRAIT_ENABLED='0',BAILIAN_MEMORY_PORTRAIT_DELETE_VERIFIED='0',BAILIAN_MEMORY_PORTRAIT_COUNT_VERIFIED='0')
memory_env=production/'secrets/memory-product.env'
java_hook=production/'secrets/start-manager-api.sh'
original_hook=java_hook.read_text()
new_hook=original_hook.replace('exec java -jar','if [[ -r "$ROOT/secrets/memory-product.env" ]]; then\n  set -a\n  source "$ROOT/secrets/memory-product.env"\n  set +a\nfi\nexec java -jar',1)
assert new_hook!=original_hook
settings={'MEMORY_PRODUCT_ENABLED':'false','MEMORY_PORTRAIT_ENABLED':'false','MEMORY_GATEWAY_URL':'http://127.0.0.1:3011','MEMORY_GATEWAY_SERVICE_SECRET':secret,'MEMORY_FACT_STRATEGY':'lite','MEMORY_SEARCH_STRATEGY':'lite','MEMORY_PORTRAIT_STRATEGY':'lite'}
def save_memory():write_atomic(memory_env,'\n'.join(key+'='+shlex.quote(value) for key,value in settings.items())+'\n')
face=json.loads((release/'face-before.json').read_text())
old_face_name='face-api-before-memory-20260929'
face_changed=False
try:
    # Migration is additive and precedes binaries/config that use its tables.
    with (release/'gateway-migration.log').open('w') as output:
        result=subprocess.run([str(release/'one-api-bailian'),'-migrate'],env=dict(os.environ,**environment),stdout=output,stderr=subprocess.STDOUT)
    assert result.returncode==0,'gateway migration failed'
    run(['pm2','stop','xiaozhi-server','manager-api'],'backend-stop.log')
    overlay(release/'server-overlay.tar.gz',production)
    overlay(release/'gateway-overlay.tar.gz',Path('/root/prjs/one-api-bailian'))
    install(release/'manager-api.jar',production/'main/manager-api/target/xiaozhi-esp32-api.jar')
    install(release/'one-api-bailian',Path('/opt/one-api-bailian/one-api-bailian'),0o755)
    save_memory();write_atomic(java_hook,new_hook,0o700)
    write_atomic(gateway_env,'\n'.join(key+'='+shlex.quote(value) for key,value in environment.items())+'\n')
    run(['systemctl','restart','one-api-bailian'],'gateway-restart.log')
    wait('http://127.0.0.1:3011/healthz',lambda b:json.loads(b).get('status')=='ok')
    run(['docker','stop','face-api'],'face-stop.log')
    run(['docker','rename','face-api',old_face_name],'face-rename.log');face_changed=True
    command=['docker','run','-d','--name','face-api','--network',face['HostConfig']['NetworkMode'],'--restart','unless-stopped']
    for mount in face['Mounts']:
        assert mount['Type']=='bind'
        command+=['-v',mount['Source']+':'+mount['Destination']+('' if mount['RW'] else ':ro')]
    for port,bindings in face['HostConfig']['PortBindings'].items():
        for binding in bindings:command+=['-p',binding['HostIp']+':'+binding['HostPort']+':'+port]
    for value in face['Config']['Env']:command+=['-e',value]
    command+=['face-api-memory-product:20260929']+face['Config']['Cmd']
    run(command,'face-start.log')
    wait('http://127.0.0.1:8765/health',lambda b:json.loads(b).get('status') in ('ok','healthy'))
    run(['pm2','restart','manager-api'],'java-restart.log')
    wait('http://127.0.0.1:8002/xiaozhi/user/pub-config',lambda b:json.loads(b).get('code')==0)
    assert sql("SELECT COUNT(*) FROM xiaozhi_esp32_server.DATABASECHANGELOG WHERE ID='202609290800-behavior-watermark';")=='1'
    # Only restore the two selections recorded at the temporary compatibility fix.
    agents=json.loads(Path('/root/prjs/tmp/bailian-memory-transition-agents.json').read_text())
    assert isinstance(agents,list) and len(agents)==2
    for agent in agents:
        assert isinstance(agent,str) and len(agent)<=64 and all(c.isalnum() or c in '_-' for c in agent)
        sql("UPDATE xiaozhi_esp32_server.ai_agent SET mem_model_id='Memory_bailian' WHERE id='"+agent+"' AND mem_model_id='Memory_mem_local_short';")
    sql("UPDATE xiaozhi_esp32_server.ai_model_config SET is_enabled=1 WHERE id='Memory_bailian';")
    settings['MEMORY_PRODUCT_ENABLED']='true';save_memory()
    # Restart also refreshes the ordinary configuration cache after selections migrate.
    run(['pm2','restart','manager-api'],'java-enable-memory.log')
    wait('http://127.0.0.1:8002/xiaozhi/user/pub-config',lambda b:json.loads(b).get('code')==0)
    run(['pm2','restart','xiaozhi-server'],'python-restart.log')
    wait('http://127.0.0.1:8006/openapi.json',lambda b:'/api/v1/device/send' in json.loads(b).get('paths',{}),30)
    # Preserve old hashed assets and unrelated installers. Replace the entry last.
    stage=release/'frontend';stage.mkdir(exist_ok=True)
    overlay(release/'frontend.tar.gz',stage)
    www=Path('/var/www/realecho-www')
    entries=[p for p in stage.rglob('*') if p.is_file()]
    entries.sort(key=lambda p:(p.name in ('index.html','service-worker.js'),p.name=='service-worker.js'))
    for path in entries:install(path,www/path.relative_to(stage))
    overlay(release/'frontend.tar.gz',production/'main/manager-web/dist')
    run(['pm2','restart','manager-web'],'frontend-restart.log')
    run(['pm2','save'],'pm2-save.log')
    report={'published':True,'release':'20260929','server_frontend':True,'firmware_ota':False,'portraits_enabled':False,'memory_enabled':True,'migrated_long_term_agents':len(agents),'artifacts':prepared['artifacts'],'published_at':time.strftime('%Y-%m-%d %H:%M:%S %z')}
    (release/'published.json').write_text(json.dumps(report,indent=2));print(json.dumps(report),flush=True)
except Exception:
    # Keep all applied deletions, billing and migrations. Only revert executable
    # versions and selections; recovery snapshots must never overwrite a wallet.
    settings['MEMORY_PRODUCT_ENABLED']='false';save_memory()
    for agent in json.loads(Path('/root/prjs/tmp/bailian-memory-transition-agents.json').read_text()):
        sql("UPDATE xiaozhi_esp32_server.ai_agent SET mem_model_id='Memory_mem_local_short' WHERE id='"+agent+"' AND mem_model_id='Memory_bailian';")
    sql("UPDATE xiaozhi_esp32_server.ai_model_config SET is_enabled=0 WHERE id='Memory_bailian';")
    overlay(release/'server-source-before.tar.gz',production)
    overlay(release/'gateway-source-before.tar.gz',Path('/root/prjs/one-api-bailian'))
    install(release/'manager-api-before.jar',production/'main/manager-api/target/xiaozhi-esp32-api.jar')
    install(release/'gateway-before',Path('/opt/one-api-bailian/one-api-bailian'),0o755)
    install(release/'gateway-before.env',gateway_env,0o600)
    install(release/'start-manager-api-before.sh',java_hook,0o700)
    overlay(release/'frontend-before.tar.gz',Path('/var/www/realecho-www'))
    if face_changed:
        subprocess.run(['docker','stop','face-api'],capture_output=True)
        subprocess.run(['docker','rename','face-api','face-api-failed-memory-'+str(int(time.time()))],capture_output=True)
        subprocess.run(['docker','rename',old_face_name,'face-api'],capture_output=True)
        subprocess.run(['docker','start','face-api'],capture_output=True)
    subprocess.run(['systemctl','restart','one-api-bailian'],capture_output=True)
    subprocess.run(['pm2','restart','manager-api','xiaozhi-server','manager-web'],capture_output=True)
    (release/'publish-failed.txt').write_text('Publication failed; executable rollback attempted. Inspect service health. Wallet/deletion records retained.\n')
    raise
