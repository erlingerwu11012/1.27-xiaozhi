"""Remote increment release. Only voice/Java source, jar and compression settings."""
from pathlib import Path
import os,json,hashlib,re,shutil,subprocess,tarfile,time,urllib.request
import yaml
os.umask(0o077)
prod=Path('/root/prjs/xiaozhi-esp32-server');cand=Path('/root/prjs/tmp/bailian-memory-product')
release=Path('/root/prjs/tmp/context-memory-release-20260929')
manifest=json.loads((release/'manifest.json').read_text());base=json.loads((release/'baseline.json').read_text())
assert json.loads((release/'tests.json').read_text())['passed']
assert json.loads((release/'real-model.json').read_text())['passed']
assert json.loads(Path('/tmp/bailian-memory-boot-smoke-result.json').read_text())['liquibase_new_changeset']=='202609292100-context-archive'
assert not (release/'published.json').exists(), 'already_published'
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
names=[n for n in manifest if '/src/test/' not in n and '/test/' not in n]
for n in names:
    assert digest(prod/n)==base[n], 'production_source_changed: '+n
    assert digest(cand/n)==manifest[n], 'candidate_source_changed: '+n
with tarfile.open(release/'source-before.tar.gz','w:gz') as archive:
    for n in names:
        if (prod/n).exists():archive.add(prod/n,arcname=n)
jar=prod/'main/manager-api/target/xiaozhi-esp32-api.jar'
shutil.copy2(jar,release/'manager-api-before.jar')
shutil.copy2(cand/'main/manager-api/target/xiaozhi-esp32-api.jar',release/'manager-api.jar')
cfg=prod/'main/xiaozhi-server/config.yaml'
text=cfg.read_text()
pattern=re.compile(r'^context_compress:[^\n]*\n(?:(?!^[A-Za-z_][^\n]*:).*(?:\n|$))*',re.M)
match=pattern.search(text);assert match,'missing_context_config'
old_block=match.group(0)
new_block='''context_compress:
  enabled: true
  input_limit_tokens: 200000
  prepare_tokens: 160000
  trigger_tokens: 180000
  target_tokens: 50000
  keep_recent_rounds: 4
  summary_target_chars: 3000
  summary_max_chars: 6000
  summary_batch_tokens: 24000

'''
new_text=text[:match.start()]+new_block+text[match.end():]
before_config=yaml.safe_load(text);after_config=yaml.safe_load(new_text)
assert {k:v for k,v in before_config.items() if k!='context_compress'}=={k:v for k,v in after_config.items() if k!='context_compress'}, 'unrelated_configuration_changed'
(release/'context-config-before.json').write_text(json.dumps({'block':old_block,'before_hash':digest(cfg)},indent=2))
def install(source,target):
    target.parent.mkdir(parents=True,exist_ok=True)
    tmp=target.with_name(target.name+'.context-next');shutil.copy2(source,tmp);os.replace(tmp,target)
def write(value,target):
    mode=target.stat().st_mode & 0o777
    tmp=target.with_name(target.name+'.context-next');tmp.write_text(value);tmp.chmod(mode);os.replace(tmp,target)
def run(args,log):
    with (release/log).open('w') as output:r=subprocess.run(args,stdout=output,stderr=subprocess.STDOUT)
    if r.returncode:raise RuntimeError(log)
def wait(url,check,seconds=90):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        try:
            with urllib.request.urlopen(url,timeout=3) as r:
                if r.status==200 and check(json.loads(r.read())):return
        except Exception:pass
        time.sleep(.5)
    raise RuntimeError('health_timeout')
mysql=['docker','exec','-i','xiaozhi-esp32-server-db','sh','-c','exec env MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --user=root --batch --raw --skip-column-names']
def sql(q):return subprocess.run(mysql,input=q,text=True,capture_output=True,check=True).stdout.strip()
try:
    run(['pm2','stop','xiaozhi-server','manager-api'],'stop.log')
    for n in names:install(cand/n,prod/n)
    install(release/'manager-api.jar',jar)
    write(new_text,cfg)
    run(['pm2','restart','manager-api'],'java-start.log')
    wait('http://127.0.0.1:8002/xiaozhi/user/pub-config',lambda body:body.get('code')==0)
    assert sql("SELECT COUNT(*) FROM xiaozhi_esp32_server.DATABASECHANGELOG WHERE ID='202609292100-context-archive';")=='1'
    run(['pm2','restart','xiaozhi-server'],'voice-start.log')
    wait('http://127.0.0.1:8006/openapi.json',lambda body:'/api/v1/device/send' in body.get('paths',{}),60)
    run(['pm2','save'],'pm2-save.log')
    report={'published':True,'at':time.strftime('%Y-%m-%d %H:%M:%S %z'),'source_files':len(names),
        'jar_sha256':digest(jar),'config_sha256':digest(cfg),'input_limit':200000,'prepare':160000,'trigger':180000,'target':50000,
        'portraits_enabled':False,'firmware_ota':False,'gateway_changed':False,'frontend_changed':False,'automation_recreated':False}
    (release/'published.json').write_text(json.dumps(report,indent=2));print(json.dumps(report),flush=True)
except Exception:
    with tarfile.open(release/'source-before.tar.gz') as archive:archive.extractall(prod,filter='data')
    install(release/'manager-api-before.jar',jar)
    current=cfg.read_text();current_match=pattern.search(current)
    if current_match:write(current[:current_match.start()]+old_block+current[current_match.end():],cfg)
    subprocess.run(['pm2','restart','manager-api','xiaozhi-server'],capture_output=True)
    (release/'publish-failed.json').write_text(json.dumps({'rolled_back_executables':True,'migration_deletion_ledger_retained':True}))
    raise
