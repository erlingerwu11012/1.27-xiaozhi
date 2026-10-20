from pathlib import Path
import json,subprocess,sys,shutil,os,hashlib,re,pymysql
s=Path('/root/prjs/tmp/hardware-followup-20261013');sys.path.insert(0,str(s))
from budget import Budget
apps=json.loads(subprocess.check_output(['pm2','jlist']));live={a['name']:a for a in apps if a['name'] in ['manager-api','xiaozhi-server'] and a['pm2_env']['status']=='online'}
assert set(live)=={'manager-api','xiaozhi-server'}
for n,a in live.items():print(n,json.dumps({'id':a['pm_id'],'pid':a['pid'],'script':a['pm2_env']['pm_exec_path'],'args':a['pm2_env'].get('args'),'cwd':a['pm2_env']['pm_cwd']}))
old=Path('/root/prjs/releases/harness-stream-20261012');print('WRAPPER', (old/'serve.py').read_text())
api=(old/'start-manager-api.sh').read_text();print('api_script_checks',{'bytes':len(api),'sha256':hashlib.sha256(api.encode()).hexdigest(),'jar_reference':re.findall(r'/root/[^ \n]+\.jar',api),'port_flags':re.findall(r'--server.port=\d+',api)})
print('nginx_routes',{str(p):re.findall(r'proxy_pass\s+([^;]+)',p.read_text()) for p in [Path('/etc/nginx/sites-enabled/www.realecho.cn'),Path('/etc/nginx/conf.d/tool-harness-internal.conf')]})
print('space',shutil.disk_usage('/').free,'budget',Budget().report())
for name in ['final05.log']:
 p=s/name;print(name,'\n'.join(p.read_text().splitlines()[-6:]) if p.exists() else 'pending')
e=json.loads((s/'private-test-env.json').read_text());db=pymysql.connect(host='127.0.0.1',user='root',password=e['PERSON_MEMORY_TEST_PASSWORD'])
with db.cursor() as c:
 c.execute("SELECT table_schema,SUM(data_length+index_length) FROM information_schema.tables WHERE table_schema IN ('xiaozhi_esp32_server','bailian_memory_test_followup20261013') GROUP BY table_schema");print('database_bytes',c.fetchall())
db.close()
