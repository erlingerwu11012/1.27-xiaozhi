import json,os,subprocess,secrets,sys,time
from pathlib import Path
S=Path(__file__).parent;J=S/'manager-api'
e=json.loads((S/'private-test-env.json').read_text())
import pymysql
c=pymysql.connect(host='127.0.0.1',user='root',password=e['PERSON_MEMORY_TEST_PASSWORD'],database=e['PERSON_MEMORY_TEST_DATABASE'],autocommit=True)
secret_file=S/'api-test-secret'
if not secret_file.exists():secret_file.write_text(secrets.token_urlsafe(40));os.chmod(secret_file,0o600)
with c.cursor() as q:
 q.execute("INSERT INTO sys_params(id,param_code,param_value,value_type,param_type) VALUES(1,'server.secret',%s,'string',1) ON DUPLICATE KEY UPDATE param_value=VALUES(param_value)",(secret_file.read_text(),))
 q.execute("INSERT IGNORE INTO ai_agent_template(id,agent_name,sort,vllm_model_id) VALUES('template_http','Isolated test',0,NULL)")
 q.execute("INSERT IGNORE INTO ai_agent(id,user_id,mem_model_id) VALUES('agent_http',99003,'Memory_mem_local_short')")
 q.execute("INSERT IGNORE INTO ai_device(id,user_id,mac_address,agent_id) VALUES('device_http',99003,'test-device-http','agent_http')")
c.close()
redis_dir=S/'redis-runtime';redis_dir.mkdir(exist_ok=True)
if subprocess.run(['docker','inspect','experience-repair-redis'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode:
 subprocess.run(['docker','run','-d','--name','experience-repair-redis','-p','127.0.0.1:16380:6379','redis:latest'],check=True,stdout=subprocess.DEVNULL)
subprocess.run(['docker','start','experience-repair-redis'],check=True,stdout=subprocess.DEVNULL)
env=dict(os.environ,ISO_MANAGER_JDBC_URL='jdbc:mysql://127.0.0.1:3306/'+e['PERSON_MEMORY_TEST_DATABASE']+'?useSSL=false&allowPublicKeyRetrieval=true&serverTimezone=Asia/Shanghai',ISO_MANAGER_DB_USER='root',ISO_MANAGER_DB_PASSWORD=e['PERSON_MEMORY_TEST_PASSWORD'])
isolated=J/'config/application-experience-test.yml'
isolated.write_text((J/'src/main/resources/application-iso.yml').read_text())
assert env['ISO_MANAGER_JDBC_URL'].split('/')[3].split('?')[0].startswith('bailian_memory_test_')
jar=Path(os.environ.get('EXPERIENCE_API_JAR',str(J/'target/xiaozhi-esp32-api.jar')))
assert jar in {J/'target/xiaozhi-esp32-api.jar',Path('/root/prjs/releases/harness-stream-20261012/xiaozhi-esp32-api.jar')}
args=['java','-Xms128m','-Xmx384m','-jar',str(jar),'--spring.profiles.active=test,experience-test','--server.port=18002','--spring.data.redis.port=16380','--spring.data.redis.database=1','--memory.product.enabled=false','--memory.gateway.url=http://127.0.0.1:9','--spring.quartz.auto-startup=false','--xiaozhi.face.base-url=http://127.0.0.1:9']
with (S/'candidate-manager.log').open('a') as f:p=subprocess.Popen(args,cwd=J,env=env,stdout=f,stderr=subprocess.STDOUT,start_new_session=True)
(S/'candidate-manager-pid.json').write_text(json.dumps({'pid':p.pid,'jar':str(jar)}));print('candidate_manager_pid',p.pid)

import requests
for _ in range(90):
 if p.poll() is not None:raise RuntimeError('isolated_api_start_failed')
 try:
  response=requests.get('http://127.0.0.1:18002/xiaozhi/user-identities/internal/state/99003',headers={'Authorization':'Bearer '+secret_file.read_text()},timeout=.5)
  if response.status_code==200 and response.json().get('code')==0:print('isolated api ready');break
 except requests.RequestException:pass
 time.sleep(.5)
else:raise RuntimeError('isolated_api_not_ready')
