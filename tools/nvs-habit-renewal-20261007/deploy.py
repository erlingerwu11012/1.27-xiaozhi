"""Explicit manifest deployment with source/config conflict checks and rollback."""
import hashlib,json,os,shutil,subprocess,sys,time
from pathlib import Path
stage=Path(__file__).parent;repo=Path('/root/prjs/xiaozhi-esp32-server');gw=Path('/root/prjs/xiaozhi_mcp_gateway')
manifest=json.loads((stage/'manifest.json').read_text());backup=stage/'production-backup'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
def destination(rel):
    if '..' in Path(rel).parts or Path(rel).is_absolute():raise RuntimeError('unsafe path')
    if rel.startswith('gateway/tools/'):return gw/rel.removeprefix('gateway/')
    if rel.startswith(('main/manager-api/src/','main/manager-web/src/','main/xiaozhi-server/core/','main/xiaozhi-server/test/')) or rel=='main/xiaozhi-server/app.py':return repo/rel
    raise RuntimeError('unexpected manifest path')
def pm2(*args):
    r=subprocess.run(['pm2',*args],capture_output=True,text=True)
    if r.returncode:raise RuntimeError('pm2 '+str(args)+' failed')
def wait_api():
    import httpx
    deadline=time.monotonic()+60
    while time.monotonic()<deadline:
        try:
            r=httpx.get('http://127.0.0.1:8002/xiaozhi/habits/internal/1',timeout=2)
            if r.status_code==401:return
        except Exception:pass
        time.sleep(2)
    raise RuntimeError('manager API not ready')
jar=repo/'main/manager-api/target/xiaozhi-esp32-api.jar';newjar=stage/'work/manager-api/target/xiaozhi-esp32-api.jar'
secretfile=repo/'secrets/habit-service-secret'
protected=[repo/'main/xiaozhi-server/data/.config.yaml',repo/'secrets/start-manager-api.sh',repo/'main/xiaozhi-server/config/assets/wakeup_words/83dca73ebd19180d2b8b39723dae401b.wav']
if '--rollback' in sys.argv:
    previous=json.loads((backup/'deployment.json').read_text())
    for row in manifest:
        dst=destination(row['path']);src=backup/row['path']
        if row['baseline_sha256'] is None:
            if dst.exists():
                if sha(dst)!=row['candidate_sha256']:raise RuntimeError('rollback source conflict')
                dst.unlink()
        else:
            if sha(dst) not in (row['baseline_sha256'],row['candidate_sha256']):raise RuntimeError('rollback source conflict')
            shutil.copy2(src,dst)
    shutil.copy2(backup/'xiaozhi-esp32-api.jar',jar)
    if previous['secret_existed']:shutil.copy2(backup/'habit-service-secret',secretfile)
    elif secretfile.exists() and sha(secretfile)==previous['secret_sha256']:secretfile.unlink()
    for name in ['manager-api','xiaozhi-server','mcp-gateway','manager-web']:pm2('restart',name)
    print('rollback complete; additive database columns retained');sys.exit(0)
conflicts=[r['path'] for r in manifest if sha(destination(r['path']))!=r['baseline_sha256'] or sha(stage/'candidate'/r['path'])!=r['candidate_sha256']]
if conflicts:raise RuntimeError('baseline conflict: '+','.join(conflicts))
results=json.loads((stage/'test-results.json').read_text());assert all(r['passed'] for r in results)
assert newjar.is_file()
reports=list((stage/'work/manager-api/target/surefire-reports').glob('TEST-*HabitSyncServiceTest.xml'));assert reports and 'failures="0"' in reports[0].read_text()
print(json.dumps({'preflight_ok':True,'source_files':len(manifest),'python_tests':sum(r['tests'] for r in results),'jar_sha256':sha(newjar)}),flush=True)
if '--apply' not in sys.argv:sys.exit(0)
if backup.exists():raise RuntimeError('refusing to overwrite deployment backup')
backup.mkdir();os.chmod(backup,0o700)
for row in manifest:
    dst=destination(row['path'])
    if dst.exists():p=backup/row['path'];p.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(dst,p)
shutil.copy2(jar,backup/'xiaozhi-esp32-api.jar')
before={str(p):sha(p) for p in protected}
secret_existed=secretfile.exists()
if secret_existed:shutil.copy2(secretfile,backup/'habit-service-secret')
import yaml
config=yaml.safe_load(protected[0].read_text());secret=config.get('manager-api',{}).get('secret','')
if not secret or '你' in secret:raise RuntimeError('dedicated service secret unavailable')
secretfile.write_text(secret+'\n');os.chmod(secretfile,0o600)
deployment={'protected':before,'jar_before':sha(jar),'jar_after':sha(newjar),'secret_existed':secret_existed,'secret_sha256':sha(secretfile),'manifest':manifest}
(backup/'deployment.json').write_text(json.dumps(deployment,indent=2));os.chmod(backup/'deployment.json',0o600)
try:
    # Stop the obsolete scheduler before the additive migration can expose new pending rows.
    pm2('stop','mcp-gateway')
    subprocess.run([sys.executable,str(stage/'migrate.py')],check=True)
    for prefix in ['main/manager-api/','main/xiaozhi-server/','gateway/','main/manager-web/']:
        for row in manifest:
            if not row['path'].startswith(prefix):continue
            dst=destination(row['path']);dst.parent.mkdir(parents=True,exist_ok=True)
            temp=dst.with_name(dst.name+'.habit-renewal-new');shutil.copy2(stage/'candidate'/row['path'],temp);os.replace(temp,dst)
        if prefix=='main/manager-api/':
            tmp=jar.with_suffix('.new.jar');shutil.copy2(newjar,tmp);os.replace(tmp,jar);pm2('restart','manager-api');wait_api()
        elif prefix=='main/xiaozhi-server/':pm2('restart','xiaozhi-server')
        elif prefix=='gateway/':pm2('restart','mcp-gateway')
        else:pm2('restart','manager-web')
    if any(sha(p)!=before[str(p)] for p in protected):raise RuntimeError('protected config changed')
    result={'applied':True,'files':len(manifest),'jar_sha256':sha(jar),'protected_unchanged':True,'deployed_at':time.strftime('%Y-%m-%d %H:%M:%S%z')}
    (stage/'deployment-result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)
except Exception:
    print('deployment failed; restoring this manifest',flush=True)
    subprocess.run([sys.executable,str(__file__),'--rollback'],check=True)
    raise
