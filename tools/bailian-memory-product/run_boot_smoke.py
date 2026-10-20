"""Rehearse Liquibase and HTTP auth with synthetic DB and separate Redis."""
import json
import os
import secrets
import subprocess
import time
import urllib.request
import urllib.error
from pathlib import Path

candidate=Path('/root/prjs/tmp/bailian-memory-product/main/manager-api')
db=json.loads(Path('/tmp/bailian-memory-migration-result.json').read_text())['database']
assert db.startswith('bailian_memory_test_') and db.isidentifier()
mysql=['docker','exec','-i','xiaozhi-esp32-server-db','sh','-c','exec env MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --user=root --batch --raw --skip-column-names']
def sql(text):return subprocess.run(mysql,input=text,text=True,capture_output=True,check=True).stdout
# Only migration metadata is copied; no customer rows or credentials are copied.
metadata=subprocess.run(['docker','exec','xiaozhi-esp32-server-db','sh','-c','exec env MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysqldump --user=root --no-create-info --skip-comments --set-gtid-purged=OFF xiaozhi_esp32_server DATABASECHANGELOG'],capture_output=True,text=True,check=True).stdout
sql('USE `'+db+'`; DELETE FROM DATABASECHANGELOG;\n'+metadata)
sql('USE `'+db+'`; DROP TABLE IF EXISTS ai_person_behavior_watermark;')
# Startup requires a default template and writable key rows. These are synthetic;
# the model endpoints cannot call the production gateway.
sql('USE `'+db+'`; '+"""
INSERT IGNORE INTO sys_params(id,param_code,param_value,value_type,param_type) VALUES
(990001,'server.secret','','string',1),(990002,'server.public_key','','string',1),
(990003,'server.private_key','','string',1);
INSERT IGNORE INTO ai_model_config(id,model_type,model_code,model_name,is_enabled,config_json) VALUES
('test_vad','VAD','synthetic','测试VAD',1,'{"type":"synthetic"}'),
('test_asr','ASR','synthetic','测试ASR',1,'{"type":"synthetic"}');
INSERT IGNORE INTO ai_agent_template(id,agent_code,agent_name,asr_model_id,vad_model_id,vllm_model_id,sort)
VALUES('synthetic_boot_template','test','测试模板','test_asr','test_vad',NULL,0);
""")
password=subprocess.run(['docker','exec','xiaozhi-esp32-server-db','sh','-c','printf "%s" "$MYSQL_ROOT_PASSWORD"'],capture_output=True,text=True,check=True).stdout
pm2=json.loads(subprocess.run(['pm2','jlist'],capture_output=True,text=True,check=True).stdout)
pid=next(item['pid'] for item in pm2 if item['name']=='manager-api')
environment=dict(os.environ)
for entry in Path('/proc/'+str(pid)+'/environ').read_bytes().split(b'\0'):
    if b'=' in entry:
        key,value=entry.split(b'=',1);environment[key.decode()]=value.decode()
environment.update(SPRING_DATASOURCE_DRUID_URL='jdbc:mysql://127.0.0.1:3306/'+db+'?useSSL=false&allowPublicKeyRetrieval=true&serverTimezone=Asia/Shanghai',
    SPRING_DATASOURCE_DRUID_USERNAME='root',SPRING_DATASOURCE_DRUID_PASSWORD=password,
    SPRING_DATA_REDIS_PORT='16379',SPRING_DATA_REDIS_DATABASE='0',SERVER_PORT='18022',
    MEMORY_PRODUCT_ENABLED='false',MEMORY_PORTRAIT_ENABLED='false',MEMORY_GATEWAY_URL='http://127.0.0.1:19999',
    FACE_JWT_SECRET=secrets.token_hex(24),FACE_API_BASE_URL='http://127.0.0.1:19999',
    ONEAPI_BASE_URL='http://127.0.0.1:19999')
name='bailian-memory-test-redis-'+secrets.token_hex(4)
subprocess.run(['docker','run','-d','--name',name,'-p','127.0.0.1:16379:6379','redis:latest'],capture_output=True,check=True)
process=None
log=Path('/tmp/bailian-memory-boot-smoke.log')
def request(path,token=None,body=None):
    headers={'Content-Type':'application/json'}
    if token:headers['Authorization']='Bearer '+token
    req=urllib.request.Request('http://127.0.0.1:18022/xiaozhi'+path,headers=headers,data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req,timeout=2) as response:return response.status,json.loads(response.read())
    except urllib.error.HTTPError as error:return error.code,json.loads(error.read())
try:
    with log.open('w') as output:
        process=subprocess.Popen(['java','-jar','target/xiaozhi-esp32-api.jar'],cwd=candidate,env=environment,stdout=output,stderr=subprocess.STDOUT)
        ready=False
        for _ in range(150):
            if process.poll() is not None:break
            try:
                code,result=request('/person-memory/internal/search',body={})
                if code==401:ready=True;break
            except (OSError,ValueError):pass
            time.sleep(.5)
        assert ready,'candidate_boot_failed'
        routes=['/person-memory/internal/background','/person-memory/internal/search','/user-identities/internal/capability','/user-identities/internal/cleanup-ack','/person-memory/admin/99001/usr_a/facts','/pay/memory-bills']
        for route in routes:
            body={} if '/internal/' in route else None
            for token in (None,'synthetic-wrong-token'):
                code,result=request(route,token,body)
                assert code in (401,403) or code==200 and result.get('code') in (401,403), (route,code,result.get('code'))
        secret=sql("SELECT param_value FROM `"+db+"`.sys_params WHERE param_code='server.secret';").strip()
        assert len(secret)>16
        code,result=request('/user-identities/internal/state/99001',secret)
        assert code==200 and result.get('code')==0
        migrations=sql("SELECT ID FROM `"+db+"`.DATABASECHANGELOG WHERE ID='202609290800-behavior-watermark';").strip()
        assert migrations=='202609290800-behavior-watermark'
        report={'passed':True,'database':db,'isolated_redis':True,'liquibase_new_changeset':migrations,'protected_routes':len(routes),'wrong_and_missing_token_rejected':True}
        Path('/tmp/bailian-memory-boot-smoke-result.json').write_text(json.dumps(report,indent=2));print(json.dumps(report),flush=True)
except Exception:
    text='\n'.join(line for line in log.read_text(errors='replace').splitlines()
        if 'DEBUG' not in line and 'Parameters:' not in line)[-5000:]
    for key,value in environment.items():
        if any(word in key.upper() for word in ('SECRET','TOKEN','PASSWORD','KEY')) and len(value)>8:text=text.replace(value,'[redacted]')
    print(text,flush=True)
    raise
finally:
    if process is not None and process.poll() is None:
        process.terminate()
        try:process.wait(timeout=15)
        except subprocess.TimeoutExpired:process.kill();process.wait()
    subprocess.run(['docker','rm','-f',name],capture_output=True)
