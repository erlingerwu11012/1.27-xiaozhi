from pathlib import Path
import json,os,subprocess,xml.etree.ElementTree as ET
S=Path('/root/prjs/tmp/quiet-maintenance-20261018')
e=json.loads(Path('/root/prjs/tmp/hardware-followup-20261013/private-test-env.json').read_text())
env=dict(os.environ,PERSON_MEMORY_TEST_DATABASE='bailian_memory_test_quiet20261018',PERSON_MEMORY_TEST_PASSWORD=e['PERSON_MEMORY_TEST_PASSWORD'])
names='QuietMaintenanceDatabaseTest,MemoryContinuityDatabaseTest,PersonMemoryDatabaseTest,MemoryMaterialPolicyTest,MemoryBillingServiceTest,MemoryDailyWorkerTest,PersonMemoryContractHttpTest,DeviceAuthRecoveryFlowTest,DeviceOtaBootstrapHttpTest'
with (S/'api-retest.log').open('w') as log:
 p=subprocess.run(['mvn','-q','-Dtest='+names,'test'],cwd=S/'manager-api',env=env,stdout=log,stderr=subprocess.STDOUT)
summary={'exit_code':p.returncode,'tests':0,'errors':0,'failures':0,'skipped':0}
for report in (S/'manager-api/target/surefire-reports').glob('TEST-*.xml'):
 r=ET.parse(report).getroot()
 for k in ['tests','errors','failures','skipped']:summary[k]+=int(r.attrib.get(k,0))
(S/'api-retest-result.json').write_text(json.dumps(summary));print(summary,flush=True)
if p.returncode:raise SystemExit(p.returncode)
with (S/'api-rebuild.log').open('w') as log:
 p=subprocess.run(['mvn','-q','-DskipTests','package'],cwd=S/'manager-api',env=env,stdout=log,stderr=subprocess.STDOUT)
print('PACKAGE_EXIT',p.returncode,flush=True);raise SystemExit(p.returncode)
