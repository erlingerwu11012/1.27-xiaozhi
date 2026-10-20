from pathlib import Path
import hashlib,json,os,subprocess,time,zipfile
S=Path(__file__).resolve().parent;J=S/'manager-api'
assert S==Path('/root/prjs/tmp/hardware-followup-20261013')
from budget import Budget
version=os.environ.get('FOLLOWUP_BUILD_VERSION','02')
b=Budget();charge=b.reserve('case','isolated-api-package-and-start-'+version)
jar_name='candidate-api-'+version+'.jar'
evidence_name='api-package-evidence-'+version+'.json'
jar=S/jar_name
if not jar.exists():
    baseline=Path('/root/prjs/releases/harness-stream-20261012/xiaozhi-esp32-api.jar')
    classes=J/'target/classes';selected={}
    for source in (S/'java').rglob('*.java'):
        relative=source.relative_to(S/'java')
        if source.read_bytes()==(S/'baseline/java'/relative).read_bytes():continue
        folder=classes/'xiaozhi/modules'/relative.parent
        for compiled in folder.glob(source.stem+'*.class'):
            assert compiled.stem==source.stem or compiled.stem.startswith(source.stem+'$')
            selected['BOOT-INF/classes/'+compiled.relative_to(classes).as_posix()]=compiled.read_bytes()
    assert selected and any('AccountIdentityStateService.class' in x for x in selected)
    jar=S/jar_name
    with zipfile.ZipFile(baseline) as old,zipfile.ZipFile(jar,'w') as out:
        for entry in old.infolist():out.writestr(entry,selected.pop(entry.filename) if entry.filename in selected else old.read(entry.filename))
        for name,value in selected.items():out.writestr(name,value)
    with zipfile.ZipFile(baseline) as old,zipfile.ZipFile(jar) as new:
        changes=[x for x in new.namelist() if x not in old.namelist() or old.read(x)!=new.read(x)]
        assert all(x.startswith('BOOT-INF/classes/xiaozhi/modules/personmemory/') or x=='BOOT-INF/classes/xiaozhi/modules/useridentity/service/AccountIdentityStateService.class' or x.startswith('BOOT-INF/classes/xiaozhi/modules/rolepack/') for x in changes)
    (S/evidence_name).write_text(json.dumps({'baseline':str(baseline),'baseline_sha256':hashlib.sha256(baseline.read_bytes()).hexdigest(),'candidate_sha256':hashlib.sha256(jar.read_bytes()).hexdigest(),'changed_entries':changes,'other_entries_identical':True},indent=2))
else:
    changes=json.loads((S/evidence_name).read_text())['changed_entries']
env=json.loads((S/'private-test-env.json').read_text());database=env['PERSON_MEMORY_TEST_DATABASE'];assert database=='bailian_memory_test_followup20261013'
runtime_env=dict(os.environ,ISO_MANAGER_JDBC_URL='jdbc:mysql://127.0.0.1:3306/'+database+'?useSSL=false&allowPublicKeyRetrieval=true&serverTimezone=Asia/Shanghai',ISO_MANAGER_DB_USER='root',ISO_MANAGER_DB_PASSWORD=env['PERSON_MEMORY_TEST_PASSWORD'])
(J/'config').mkdir(exist_ok=True)
(J/'config/application-experience-test.yml').write_text((J/'src/main/resources/application-iso.yml').read_text())
if subprocess.run(['docker','inspect','hardware-followup-redis-20261013'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode:
    subprocess.run(['docker','run','-d','--name','hardware-followup-redis-20261013','-p','127.0.0.1:16382:6379','redis:latest','--save','','--appendonly','no'],check=True,stdout=subprocess.DEVNULL)
else:subprocess.run(['docker','start','hardware-followup-redis-20261013'],check=True,stdout=subprocess.DEVNULL)
args=['java','-Xms128m','-Xmx384m','-jar',str(jar),'--spring.profiles.active=test,experience-test','--server.port=18006','--spring.data.redis.port=16382','--spring.data.redis.database=0','--memory.product.enabled=false','--memory.gateway.url=http://127.0.0.1:9','--spring.quartz.auto-startup=false','--xiaozhi.face.base-url=http://127.0.0.1:9']
with (S/'isolated-manager.log').open('a') as out:p=subprocess.Popen(args,cwd=J,env=runtime_env,stdout=out,stderr=subprocess.STDOUT,start_new_session=True)
(S/'isolated-manager-pid.json').write_text(json.dumps({'pid':p.pid,'jar':str(jar),'port':18006}))
import requests
for _ in range(100):
    if p.poll() is not None:break
    try:
        response=requests.get('http://127.0.0.1:18006/xiaozhi/user-identities/internal/state/99003',headers={'Authorization':'Bearer '+(S/'api-test-secret').read_text()},timeout=.5)
        if response.status_code==200 and response.json().get('code')==0:
            b.finish(charge,{'status':'ready','port':18006,'changed_classes':len(changes)});print('isolated_api_ready',flush=True);break
    except requests.RequestException:pass
    time.sleep(.4)
else:
    b.finish(charge,{'error':'api_not_ready'});raise RuntimeError('api_not_ready')
if p.poll() is not None:
    b.finish(charge,{'error':'api_start_failed'});raise RuntimeError('api_start_failed')
