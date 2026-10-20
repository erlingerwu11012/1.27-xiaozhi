"""Run only on the server; creates a fresh empty isolated schema, never production."""
import json
import os
from pathlib import Path
import re
import subprocess

import pymysql

stage = Path('/root/prjs/tmp/harness-repair-20261017')
assert stage.is_dir()
environment = json.loads(Path('/root/prjs/tmp/hardware-followup-20261013/private-test-env.json').read_text())
template = environment['PERSON_MEMORY_TEST_DATABASE']
database = 'bailian_memory_test_harnessrepair20261017'
assert re.fullmatch(r'bailian_memory_test_[a-zA-Z0-9_]+', template)
assert database != template
with pymysql.connect(host='127.0.0.1', user='root', password=environment['PERSON_MEMORY_TEST_PASSWORD'], autocommit=True) as db:
    with db.cursor() as cursor:
        cursor.execute('SHOW DATABASES LIKE %s', (database,))
        if cursor.fetchone():
            raise RuntimeError('Test schema already exists; refusing to overwrite it')
        cursor.execute('CREATE DATABASE `' + database + '` CHARACTER SET utf8mb4')
        cursor.execute('SHOW TABLES FROM `' + template + '`')
        for (name,) in cursor.fetchall():
            assert re.fullmatch(r'[a-zA-Z0-9_]+', name)
            cursor.execute('CREATE TABLE `' + database + '`.`' + name + '` LIKE `' + template + '`.`' + name + '`')

test = stage / 'manager-api/src/test/java/xiaozhi/modules/personmemory/MemoryContinuityDatabaseTest.java'
source = test.read_text()
assert 'explicitFactSaveReadbackAndIdempotency' not in source
at = source.rfind('}')
source = source[:at] + '''
 @Test void explicitFactSaveReadbackAndIdempotency(){transaction.executeWithoutResult(tx->{
  var a=member();
  var saved=memory.add(a,"我最爱喝咖啡");
  assertEquals(true,saved.get("local_applied"));
  assertNotNull(saved.get("record_id"));
  var again=memory.add(a,"我最爱喝咖啡");
  assertEquals(saved.get("record_id"),again.get("record_id"));
  var archive=new RecentArchiveService(jdbc,memory,identities);
  var read=archive.search(a,"我最爱喝什么","related",1,List.of(saved.get("record_id").toString()));
  var items=(List<Map<String,Object>>)read.get("items");
  assertEquals(1,items.size());assertEquals("我最爱喝咖啡",items.get(0).get("text"));
  assertEquals(saved.get("record_id"),items.get(0).get("record_id"));
  assertThrows(xiaozhi.common.exception.RenException.class,()->memory.add(a,"我最爱喝绿茶"));
 });}
 @Test void explicitFactRejectsQuestionsAndStaleIdentity(){transaction.executeWithoutResult(tx->{
  var a=member();
  assertThrows(xiaozhi.common.exception.RenException.class,()->memory.add(a,"我最爱喝什么？"));
  assertThrows(xiaozhi.common.exception.RenException.class,()->memory.add(a,"请你记住我最爱喝咖啡"));
  a.setDirectoryVersion(a.getDirectoryVersion()+1);
  assertThrows(xiaozhi.common.exception.RenException.class,()->memory.add(a,"我最爱喝咖啡"));
 });}
''' + source[at:]
test.write_text(source)
env = dict(os.environ, PERSON_MEMORY_TEST_DATABASE=database,
           PERSON_MEMORY_TEST_PASSWORD=environment['PERSON_MEMORY_TEST_PASSWORD'])
with (stage / 'api-database-test.log').open('w') as log:
    result = subprocess.run(['mvn', '-q', '-Dtest=MemoryContinuityDatabaseTest,PersonMemoryDatabaseTest,MemoryMaterialPolicyTest,MemoryBillingServiceTest,MemoryDailyWorkerTest,DeviceAuthRecoveryFlowTest,DeviceOtaBootstrapHttpTest', 'test'],
                            cwd=stage/'manager-api', env=env, stdout=log, stderr=subprocess.STDOUT)
(stage / 'api-database-result.json').write_text(json.dumps({'exit_code': result.returncode, 'database': database}))
print('ISOLATED_DATABASE_TEST_EXIT', result.returncode, flush=True)
