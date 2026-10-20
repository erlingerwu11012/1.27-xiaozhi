"""Remote: isolated SQL fixture, Java tests/build and independent voice regressions."""
from pathlib import Path
import os,json,subprocess
from datetime import datetime
root=Path('/root/prjs/tmp/bailian-memory-product')
out=Path('/root/prjs/tmp/context-memory-release-20260929')
python='/root/miniconda3/envs/xiaozhi-esp32-server/bin/python'
(out/'tests.json').write_text(json.dumps({'passed':False,'started_at':datetime.now().isoformat(),'synthetic_only':True}))
def run(args,cwd,log,env=None):
    with (out/log).open('w') as stream:r=subprocess.run(args,cwd=cwd,stdout=stream,stderr=subprocess.STDOUT,env=env)
    print(json.dumps({'step':log,'exit':r.returncode}),flush=True)
    if r.returncode:
        # Test sources and synthetic output only; don't dump application config.
        lines=(out/log).read_text(errors='replace').splitlines()
        for line in lines[-55:]:
            if not any(word in line.lower() for word in ('password','api_key','authorization','bearer','config_json','parameters:')):print(line)
        raise RuntimeError(log)
run(['python3','/tmp/migration_fixture.py'],root,'migration.log')
fixture=json.loads(Path('/tmp/bailian-memory-migration-result.json').read_text());database=fixture['database']
assert database.startswith('bailian_memory_test_')
mysql=['docker','exec','-i','xiaozhi-esp32-server-db','sh','-c','exec env MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --user=root --batch --raw --skip-column-names']
def sql(value):return subprocess.run(mysql,input=value,text=True,capture_output=True,check=True).stdout
archive_columns=int(sql("SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA='"+database+"' AND TABLE_NAME='ai_agent_chat_history' AND COLUMN_NAME IN('account_id','person_id','identity_status','turn_id','event_id','directory_version','default_generation','recall_allowed');").strip())
assert archive_columns in (0,8), 'partial_archive_schema'
if archive_columns==0:
    sql('USE `'+database+'`;\n'+(root/'main/manager-api/src/main/resources/db/changelog/202609292100_context_archive.sql').read_text())
env=dict(os.environ)
inspect=json.loads(subprocess.run(['docker','inspect','xiaozhi-esp32-server-db'],capture_output=True,text=True,check=True).stdout)[0]
env['PERSON_MEMORY_TEST_PASSWORD']=next(x.split('=',1)[1] for x in inspect['Config']['Env'] if x.startswith('MYSQL_ROOT_PASSWORD='))
env['PERSON_MEMORY_TEST_DATABASE']=database
run(['mvn','-o','test'],root/'main/manager-api','java-tests.log',env)
run(['mvn','-o','package','-Dmaven.test.skip=true'],root/'main/manager-api','java-build.log',env)
bootstrap="""from unittest.mock import MagicMock
import config.logger
config.logger.setup_logging=lambda:MagicMock()
import unittest,sys
sys.path.insert(0,'test')
suite=unittest.TestSuite()
for name in sys.argv[1:]:suite.addTests(unittest.defaultTestLoader.loadTestsFromName(name))
r=unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(0 if r.wasSuccessful() else 1)
"""
modules=['test_context_memory_200k','test_prompt_pipeline_v2','test_person_memory_identity','test_person_memory_tools','test_person_memory_chat_init','test_person_memory_recovery','test_identity_snapshot_request','test_multi_device_isolation','test_tts_sentence_telemetry','test_tts_subtitle']
for module in modules:run([python,'-c',bootstrap,module],root/'main/xiaozhi-server','voice-'+module+'.log')
run(['python3','/tmp/run_python_regression.py'],root,'voice-regression.log')
result={'passed':True,'database':database,'synthetic_only':True,'portraits':False,'firmware_ota':False}
(out/'tests.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)
