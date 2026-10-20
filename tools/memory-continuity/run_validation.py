"""SSH host validation: schema-only clone, synthetic fixtures, no paid calls."""
from pathlib import Path
import json,subprocess,os,sys
root=Path('/root/prjs/tmp/bailian-memory-product');out=Path('/root/prjs/tmp/memory-continuity-release-20260930');out.mkdir(exist_ok=True)
def run(args,cwd,log,env=None):
 with (out/log).open('w') as stream:r=subprocess.run(args,cwd=cwd,stdout=stream,stderr=subprocess.STDOUT,env=env)
 print(json.dumps({'step':log,'exit':r.returncode}),flush=True)
 if r.returncode:
  for line in (out/log).read_text(errors='replace').splitlines()[-60:]:
   if not any(x in line.lower() for x in ('password','api_key','authorization','bearer','config_json','parameters:','jdbc:mysql')):print(line)
  raise RuntimeError(log)
run(['python3','/tmp/migration_fixture.py'],root,'migration.log')
fixture=json.loads(Path('/tmp/bailian-memory-migration-result.json').read_text());db=fixture['database'];assert db.startswith('bailian_memory_test_')
mysql=['docker','exec','-i','xiaozhi-esp32-server-db','sh','-c','exec env MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --user=root --batch --raw --skip-column-names']
def sql(q):return subprocess.run(mysql,input=q,text=True,capture_output=True,check=True).stdout.strip()
path=root/'main/manager-api/src/main/resources/db/changelog/202609301900_memory_continuity.sql'
columns=sql("SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA='"+db+"' AND TABLE_NAME='ai_person_material' AND COLUMN_NAME='user_tokens';")
assert columns in ('0','1')
if columns=='0':sql('USE `'+db+'`;\n'+path.read_text())
env=dict(os.environ);inspect=json.loads(subprocess.run(['docker','inspect','xiaozhi-esp32-server-db'],capture_output=True,text=True,check=True).stdout)[0]
env['PERSON_MEMORY_TEST_PASSWORD']=next(x.split('=',1)[1] for x in inspect['Config']['Env'] if x.startswith('MYSQL_ROOT_PASSWORD='));env['PERSON_MEMORY_TEST_DATABASE']=db
run(['mvn','-o','test'],root/'main/manager-api','java-tests.log',env)
run(['mvn','-o','package','-Dmaven.test.skip=true'],root/'main/manager-api','java-build.log',env)
python='/root/miniconda3/envs/xiaozhi-esp32-server/bin/python'
bootstrap="""from unittest.mock import MagicMock
import config.logger
config.logger.setup_logging=lambda:MagicMock()
import unittest,sys
sys.path.insert(0,'test')
r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromName(sys.argv[1]))
sys.exit(0 if r.wasSuccessful() else 1)
"""
for module in ['test_memory_continuity','test_context_memory_200k','test_person_memory_identity','test_person_memory_tools','test_person_memory_chat_init','test_person_memory_recovery','test_multi_device_isolation','test_prompt_pipeline_v2','test_tts_sentence_telemetry','test_tts_subtitle']:
 run([python,'-c',bootstrap,module],root/'main/xiaozhi-server','voice-'+module+'.log')
report={'passed':True,'database':db,'synthetic_only':True,'paid_calls':0,'portraits':False,'firmware_ota':False}
(out/'tests.json').write_text(json.dumps(report,indent=2));print(json.dumps(report),flush=True)
