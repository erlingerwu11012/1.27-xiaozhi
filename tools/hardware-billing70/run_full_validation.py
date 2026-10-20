"""Schema-only isolated regression and builds; no upstream calls or deployment."""
from pathlib import Path
import json,subprocess,os,uuid,xml.etree.ElementTree as ET

root=Path('/root/prjs/tmp/hardware-billing70-20261001');cand=root/'candidate/server';logs=root/'tests';logs.mkdir(exist_ok=True)
mysql=['docker','exec','-i','xiaozhi-esp32-server-db','sh','-c','exec env MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --user=root --batch --raw --skip-column-names']
def sql(q):return subprocess.run(mysql,input=q,text=True,capture_output=True,check=True).stdout.strip()
env=dict(os.environ);env['PATH']='/usr/local/go/bin:'+env.get('PATH','')
env['VUE_APP_API_BASE_URL']='https://api.realecho.cn/xiaozhi'
db='bailian_memory_test_hardware70_'+uuid.uuid4().hex[:8]
hwdb='hardware_billing_test_'+uuid.uuid4().hex[:8]
assert db.isidentifier() and hwdb.isidentifier()
schema=subprocess.run(['docker','exec','xiaozhi-esp32-server-db','sh','-c','exec env MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysqldump --user=root --no-data --skip-comments --set-gtid-purged=OFF xiaozhi_esp32_server'],capture_output=True,text=True,check=True).stdout
sql('CREATE DATABASE `'+db+'` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;');sql('USE `'+db+'`;\n'+schema)
sql('CREATE DATABASE `'+hwdb+'` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;')
inspect=json.loads(subprocess.run(['docker','inspect','xiaozhi-esp32-server-db'],capture_output=True,text=True,check=True).stdout)[0]
password=next(x.split('=',1)[1] for x in inspect['Config']['Env'] if x.startswith('MYSQL_ROOT_PASSWORD='))
env['PERSON_MEMORY_TEST_DATABASE']=db;env['PERSON_MEMORY_TEST_PASSWORD']=password
env['HW_BILLING_TEST_DATABASE']=hwdb;env['HW_BILLING_TEST_PASSWORD']=password
results=[]
def run(label,args,cwd):
 with (logs/(label+'.log')).open('w') as stream:r=subprocess.run(args,cwd=cwd,env=env,stdout=stream,stderr=subprocess.STDOUT,timeout=900)
 item={'step':label,'exit_code':r.returncode};results.append(item);print(json.dumps(item),flush=True)
 return r.returncode==0

run('mysql-ledger',['go','test','./hardwarebilling','-count=1','-v'],root/'candidate/gateway')
run('java-tests',['mvn','-o','test'],cand/'main/manager-api')
run('java-build',['mvn','-o','package','-Dmaven.test.skip=true'],cand/'main/manager-api')
run('vue-build',['npm','run','build'],cand/'main/manager-web')
python='/root/miniconda3/envs/xiaozhi-esp32-server/bin/python'
bootstrap='''from unittest.mock import MagicMock
import config.logger
config.logger.setup_logging=lambda:MagicMock()
import unittest,sys
sys.path.insert(0,'test')
r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromName(sys.argv[1]))
sys.exit(0 if r.wasSuccessful() else 1)
'''
for file in sorted((cand/'main/xiaozhi-server/test').glob('test*.py')):
 run('python-'+file.stem,[python,'-c',bootstrap,file.stem],cand/'main/xiaozhi-server')
report={'results':results,'schema_only_database':db,'billing_database':hwdb,'upstream_calls':0,'cost_cny':'0','production_changed':False}
(logs/'full-validation.json').write_text(json.dumps(report,indent=2));print(json.dumps({'passed_steps':sum(x['exit_code']==0 for x in results),'failed_steps':sum(x['exit_code']!=0 for x in results)}))
