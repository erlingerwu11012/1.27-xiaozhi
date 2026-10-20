from pathlib import Path
import json,os,re,shutil,subprocess,xml.etree.ElementTree as ET
import pymysql
S=Path('/root/prjs/tmp/quiet-maintenance-20261018');API=S/'manager-api'
environment=json.loads(Path('/root/prjs/tmp/hardware-followup-20261013/private-test-env.json').read_text())
database='bailian_memory_test_quiet20261018'
template=environment['PERSON_MEMORY_TEST_DATABASE']
assert re.fullmatch(r'bailian_memory_test_[a-zA-Z0-9_]+',template)
with pymysql.connect(host='127.0.0.1',user='root',password=environment['PERSON_MEMORY_TEST_PASSWORD'],autocommit=True) as db:
 with db.cursor() as c:
  c.execute('SHOW DATABASES LIKE %s',(database,));assert not c.fetchone()
  c.execute('CREATE DATABASE `'+database+'` CHARACTER SET utf8mb4')
  c.execute('SHOW TABLES FROM `'+template+'`')
  for (table,) in c.fetchall():
   assert re.fullmatch(r'[a-zA-Z0-9_]+',table)
   c.execute('CREATE TABLE `'+database+'`.`'+table+'` LIKE `'+template+'`.`'+table+'`')
env=dict(os.environ,PERSON_MEMORY_TEST_DATABASE=database,PERSON_MEMORY_TEST_PASSWORD=environment['PERSON_MEMORY_TEST_PASSWORD'])
names='QuietMaintenanceDatabaseTest,MemoryContinuityDatabaseTest,PersonMemoryDatabaseTest,MemoryMaterialPolicyTest,MemoryBillingServiceTest,MemoryDailyWorkerTest,PersonMemoryContractHttpTest,DeviceAuthRecoveryFlowTest,DeviceOtaBootstrapHttpTest'
with (S/'api-test.log').open('w') as log:
 p=subprocess.run(['mvn','-q','-Dtest='+names,'test'],cwd=API,env=env,stdout=log,stderr=subprocess.STDOUT)
summary={'exit_code':p.returncode,'tests':0,'errors':0,'failures':0,'skipped':0}
for report in (API/'target/surefire-reports').glob('TEST-*.xml'):
 r=ET.parse(report).getroot()
 for key in ['tests','errors','failures','skipped']:summary[key]+=int(r.attrib.get(key,0))
(S/'api-test-result.json').write_text(json.dumps(summary));print(summary,flush=True)
if p.returncode:raise SystemExit(p.returncode)
with (S/'api-build.log').open('w') as log:
 p=subprocess.run(['mvn','-q','-DskipTests','package'],cwd=API,env=env,stdout=log,stderr=subprocess.STDOUT)
print('PACKAGE_EXIT',p.returncode,flush=True)
raise SystemExit(p.returncode)
