"""Run on host only. Reviewed candidate -> compatible migration -> paused cutover.

Keys are neither printed nor included in public delivery. Financial tables are
never dropped on rollback. Run preflight first; --publish is explicit activation.
"""
from pathlib import Path
import subprocess,json,hashlib,os,shutil,time,secrets,argparse,zipfile
from fractions import Fraction

ROOT=Path('/root/prjs/tmp/hardware-billing70-20261001')
PROD=Path('/root/prjs/xiaozhi-esp32-server')
GATE=Path('/root/prjs/one-api-bailian')
BACK=ROOT/'release-backup'
MYSQL=['docker','exec','-i','xiaozhi-esp32-server-db','sh','-c','exec env MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --user=root --default-character-set=utf8mb4 --batch --raw --skip-column-names']
def command(args,**kw):
    p=subprocess.run(args,capture_output=True,text=True,**kw)
    if p.returncode:raise RuntimeError('release command failed: '+args[0])
    return p.stdout.strip()
def sql(q):return command(MYSQL,input=q)
def quoted(s):return "'"+str(s).replace('\\','\\\\').replace("'","''")+"'"
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
def receipt(stage,**values):
    data={'stage':stage,'time':int(time.time()),**values}
    (ROOT/'release-state.json').write_text(json.dumps(data,indent=2))
    print(json.dumps(data),flush=True)
def wait_http(url):
    for _ in range(60):
        x=subprocess.run(['curl','-s','--max-time','3','-o','/dev/null','-w','%{http_code}',url],capture_output=True,text=True)
        if x.stdout in ['200','401','403']:return
        time.sleep(1)
    raise RuntimeError('health timeout')

def preflight():
    manifest=json.loads((ROOT/'candidate-manifest.json').read_text())
    for row in manifest['changes']:
        group,rel=row['path'].split('/',1)
        if digest((PROD if group=='server' else GATE)/rel)!=row['baseline_sha256']:
            raise RuntimeError('production baseline mismatch '+row['path'])
        if digest(ROOT/'candidate'/row['path'])!=row['candidate_sha256']:
            raise RuntimeError('candidate artifact mismatch '+row['path'])
    # Unchanged runtime resources must survive partial-source candidate builds.
    resource_root=PROD/'main/manager-api/src/main/resources'
    jar=ROOT/'candidate/server/main/manager-api/target/xiaozhi-esp32-api.jar'
    with zipfile.ZipFile(jar) as artifact:
        entries=set(artifact.namelist())
        for resource in resource_root.rglob('*'):
            if resource.is_file():
                name='BOOT-INF/classes/'+resource.relative_to(resource_root).as_posix()
                assert name in entries,'missing runtime resource '+name
        for directory in ['i18n','lua']:
            for resource in (resource_root/directory).rglob('*'):
                if resource.is_file():
                    name='BOOT-INF/classes/'+resource.relative_to(resource_root).as_posix()
                    assert artifact.read(name)==resource.read_bytes(),'runtime resource changed '+name
    frontend=ROOT/'candidate/server/main/manager-web/dist'
    import re
    index=(frontend/'index.html').read_text()
    app=re.search(r'src="(/js/app[^" ]+\.js)"',index).group(1)
    bundle=(frontend/app.lstrip('/')).read_text()
    assert 'https://api.realecho.cn/xiaozhi' in bundle,'missing compiled production API base'
    assert '.VUE_APP_API_BASE_URL' not in bundle,'unresolved frontend API environment'
    tests=json.loads((ROOT/'tests/full-validation.json').read_text())
    assert len(tests['results'])==58 and all(x['exit_code']==0 for x in tests['results'])
    for name in ['real-auth-relay-ledger.json','real-production-audio-ledger.json','real-memory-ledger.json']:
        assert (ROOT/'tests'/name).exists()
    assert json.loads((ROOT/'tests/migration-rehearsal.json').read_text())['exit_code']==0
    native=ROOT/'candidate/one-api-bailian-hardware70'
    assert native.exists(),'build the independent ./cmd/bailian binary'
    help_result=subprocess.run([str(native),'-help'],capture_output=True,text=True)
    assert '-recover-before' in help_result.stderr and '-migrate' in help_result.stderr,'wrong native entry'
    assert digest(native)!=digest(ROOT/'candidate/one-api-hardware70'),'native and core binaries must differ'
    assert shutil.disk_usage('/root').free>700_000_000,'insufficient safe release space'
    if sql("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='one_api' AND table_name='hardware_billing_wallet';")=='1':
        assert sql("SELECT COUNT(*) FROM one_api.hardware_billing_wallet;")=='0','cutover already started'
    return manifest

def publish():
    m=preflight();assert not BACK.exists(),'release already started; inspect receipt before resuming'
    BACK.mkdir(mode=0o700)
    inspect=json.loads(command(['docker','inspect','one-api']))[0]
    # Preserve existing wrappers/binary/JAR/front-end on the same host only.
    for source,rel in [
        (PROD/'main/manager-api/target/xiaozhi-esp32-api.jar','manager-api.jar'),
        (Path('/opt/one-api-bailian/one-api-bailian'),'native-gateway'),
        (Path('/etc/one-api-bailian.env'),'native.env'),
        (PROD/'secrets/start-manager-api.sh','start-manager-api.sh'),
        (PROD/'secrets/start-xiaozhi-server.sh','start-xiaozhi-server.sh')]:
        shutil.copy2(source,BACK/rel);os.chmod(BACK/rel,0o600)
    shutil.copytree('/var/www/realecho-www',BACK/'frontend')
    for row in m['changes']:
        group,rel=row['path'].split('/',1);source=(PROD if group=='server' else GATE)/rel
        if source.exists():
            dest=BACK/'source'/row['path'];dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,dest)
    # No API keys in financial snapshots.
    snapshot=sql('SELECT b.sys_user_id,b.oneapi_user_id,u.quota,u.used_quota,u.`group` FROM xiaozhi_esp32_server.sys_user_oneapi_binding b JOIN one_api.users u ON u.id=b.oneapi_user_id ORDER BY b.sys_user_id;')
    (BACK/'wallet-preflight.tsv').write_text(snapshot);os.chmod(BACK/'wallet-preflight.tsv',0o600)
    image=ROOT/'docker-image';image.mkdir(exist_ok=True)
    shutil.copy2(ROOT/'candidate/one-api-hardware70',image/'one-api-hardware70')
    (image/'Dockerfile').write_text('FROM one-api:bailian-20260915\nCOPY one-api-hardware70 /one-api-bailian-core-image\n')
    command(['docker','build','-t','one-api:hardware70-20261001',str(image)])
    # Install source and compatible API with feature still disabled.
    for row in m['changes']:
        group,rel=row['path'].split('/',1);dest=(PROD if group=='server' else GATE)/rel
        dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/'candidate'/row['path'],dest)
    shutil.copy2(ROOT/'candidate/server/main/manager-api/target/xiaozhi-esp32-api.jar',PROD/'main/manager-api/target/xiaozhi-esp32-api.jar')
    command(['pm2','restart','manager-api']);wait_http('http://127.0.0.1:8002/xiaozhi/user/pub-config')
    assert sql("SELECT COUNT(*) FROM information_schema.columns WHERE table_schema='one_api' AND table_name='hardware_billing_bill' AND column_name='settlement_legacy_debit';")=='1'
    receipt('compatible_schema_installed',production_billing_switched=False)
    for name in ['manager-api','xiaozhi-server']:command(['pm2','stop',name])
    command(['systemctl','stop','one-api-bailian']);command(['docker','stop','one-api'])
    # All product account money writers are paused; take the definitive snapshot.
    rows=sql('SELECT b.sys_user_id,b.oneapi_user_id,u.quota,u.used_quota,u.`group` FROM xiaozhi_esp32_server.sys_user_oneapi_binding b JOIN one_api.users u ON u.id=b.oneapi_user_id ORDER BY b.sys_user_id;').splitlines()
    assert rows and all(x.split('\t')[4]=='default' for x in rows)
    (BACK/'wallet-cutover.tsv').write_text('\n'.join(rows));os.chmod(BACK/'wallet-cutover.tsv',0o600)
    q=['START TRANSACTION;']
    for row in rows:
        account,user,quota,used,group=row.split('\t');assert all(v.isdigit() for v in [account,user,quota,used])
        points=str(Fraction(int(quota),500));now=int(time.time())
        q += [f"INSERT INTO one_api.hardware_billing_wallet(user_id,product_account,state,created_at,legacy_used_quota) VALUES({user},{quoted(account)},'enabled',{now},{used});",
              f"INSERT INTO one_api.hardware_billing_lot(id,user_id,kind,remaining,cny_per_point,original_points,created_at) VALUES({quoted('legacy:'+account)},{user},'legacy',{quoted(points)},'0',{quoted(points)},{time.time_ns()});",
              f"UPDATE one_api.users SET `group`='hardware70' WHERE id={user};"]
    q += ["UPDATE xiaozhi_esp32_server.pay_package SET quota_points=100,description='1元100点' WHERE id=1 AND amount_cents=100;","COMMIT;"]
    sql('\n'.join(q))
    for model in ['qwen-plus','qwen3-vl-flash','qwen3-asr-flash-realtime','qwen-audio-3.0-tts-plus']:
        sql("UPDATE one_api.tokens t JOIN xiaozhi_esp32_server.sys_user_oneapi_binding b ON b.oneapi_token_id=t.id AND b.oneapi_user_id=t.user_id JOIN one_api.hardware_billing_wallet w ON w.user_id=t.user_id AND w.product_account=CAST(b.sys_user_id AS CHAR) SET t.models=CONCAT(t.models,',"+model+"') WHERE t.name='xiaozhi-device' AND t.models IS NOT NULL AND t.models<>'' AND FIND_IN_SET('"+model+"',t.models)=0;")
    # Dedicated group changes no Aimi route, channel or account.
    group_raw=sql("SELECT value FROM one_api.options WHERE `key`='GroupRatio';")
    groups=json.loads(group_raw) if group_raw else {'default':1,'vip':1,'svip':1};groups['hardware70']=groups.get('default',1)
    sql("INSERT INTO one_api.options (`key`,value) VALUES('GroupRatio',"+quoted(json.dumps(groups))+" ) ON DUPLICATE KEY UPDATE value=VALUES(value);")
    base='https://dashscope.aliyuncs.com/compatible-mode/v1'
    sql("INSERT INTO one_api.channels(type,`key`,status,name,weight,created_time,base_url,models,`group`,priority,model_mapping) SELECT 50,`key`,1,'hardware70-main',0,UNIX_TIMESTAMP(),"+quoted(base)+",'qwen-plus','hardware70',0,'{}' FROM one_api.channels WHERE id=2 AND type=17 AND status=1;")
    sql("INSERT INTO one_api.channels(type,`key`,status,name,weight,created_time,base_url,models,`group`,priority,model_mapping) SELECT 50,JSON_UNQUOTE(JSON_EXTRACT(config_json,'$.api_key')),1,'hardware70-vision',0,UNIX_TIMESTAMP(),"+quoted(base)+",'qwen3-vl-flash','hardware70',0,'{}' FROM xiaozhi_esp32_server.ai_model_config WHERE id='VLLM_QwenVLVLLM' AND model_type='VLLM';")
    sql("INSERT INTO one_api.abilities (`group`,model,channel_id,enabled,priority) SELECT 'hardware70',models,id,1,0 FROM one_api.channels WHERE name IN ('hardware70-main','hardware70-vision') AND `group`='hardware70';")
    native=Path('/etc/one-api-bailian.env');native_vars={}
    for line in native.read_text().splitlines():
        if '=' in line and not line.startswith('#'):
            k,v=line.split('=',1);native_vars[k]=v.strip().strip('\"').strip("'")
    memory_channel=int(native_vars['BAILIAN_MEMORY_CHANNEL_ID'])
    sql(f"UPDATE one_api.channels SET `group`=CONCAT(`group`,',hardware70') WHERE id IN (7,{memory_channel}) AND FIND_IN_SET('hardware70',`group`)=0;")
    key=secrets.token_hex(32)
    private=PROD/'secrets/hardware-billing70.env'
    private.write_text('export HW_BILLING_ENABLED=1\nexport HW_BILLING_SERVICE_KEY='+key+'\nexport HW_BILLING_GATEWAY_ORIGIN=http://127.0.0.1:3000\nexport HW_BILLING_AUDIO_GATEWAY_ORIGIN=http://127.0.0.1:3011\nexport HARDWARE_BILLING_ENABLED=true\nexport HARDWARE_BILLING_SCHEMA=one_api\nexport HARDWARE_BILLING_GROUP=hardware70\nexport HARDWARE_BILLING_GATEWAY_BASE_URL=http://127.0.0.1:3000/v1\nexport HARDWARE_BILLING_AUDIO_BASE_URL=http://127.0.0.1:3011\n');os.chmod(private,0o600)
    for name in ['start-manager-api.sh','start-xiaozhi-server.sh']:
        p=PROD/'secrets'/name;s=p.read_text();s=s.replace('\nexec ','\nsource '+str(private)+'\nexec ',1);p.write_text(s)
    native.write_text(native.read_text()+'\nHW_BILLING_ENABLED=1\nHW_BILLING_SERVICE_KEY='+key+'\n');os.chmod(native,0o600)
    shutil.copy2(ROOT/'candidate/one-api-bailian-hardware70','/opt/one-api-bailian/one-api-bailian')
    old_name='one-api-before-hardware70-20261001';command(['docker','rename','one-api',old_name])
    args=['docker','create','--name','one-api','--restart',inspect['HostConfig']['RestartPolicy']['Name']]
    for bind in inspect['HostConfig'].get('Binds',[]) or []:args+=['-v',bind]
    for port,entries in inspect['HostConfig'].get('PortBindings',{}).items():
        for entry in entries or []:args+=['-p',entry['HostIp']+':'+entry['HostPort']+':'+port.split('/')[0]]
    args+=['--network',inspect['HostConfig']['NetworkMode']]
    for value in inspect['Config']['Env']:
        if not value.startswith(('HW_BILLING_ENABLED=','HW_BILLING_SERVICE_KEY=')):args+=['-e',value]
    args+=['-e','HW_BILLING_ENABLED=1','-e','HW_BILLING_SERVICE_KEY='+key,'one-api:hardware70-20261001',*inspect['Config']['Cmd']]
    command(args);command(['docker','start','one-api']);command(['systemctl','start','one-api-bailian'])
    wait_http('http://127.0.0.1:3000/api/status')
    wait_http('http://127.0.0.1:3011/healthz')
    for name in ['manager-api','xiaozhi-server']:command(['pm2','restart',name])
    wait_http('http://127.0.0.1:8002/xiaozhi/user/pub-config')
    dest=Path('/var/www/realecho-www');candidate=ROOT/'candidate/server/main/manager-web/dist'
    for p in candidate.iterdir():
        if p.is_dir():shutil.copytree(p,dest/p.name,dirs_exist_ok=True)
        else:shutil.copy2(p,dest/p.name)
    wait_http('https://www.realecho.cn');wait_http('https://api.realecho.cn/api/status')
    receipt('published_pending_financial_smoke',production_billing_switched=True,accounts=len(rows),image='one-api:hardware70-20261001',portraits_enabled=False,firmware_ota=False)

if __name__=='__main__':
    args=argparse.ArgumentParser();args.add_argument('--publish',action='store_true');opts=args.parse_args()
    if opts.publish:publish()
    else:
        m=preflight();receipt('preflight_passed',production_billing_switched=False,source_files=len(m['changes']))
