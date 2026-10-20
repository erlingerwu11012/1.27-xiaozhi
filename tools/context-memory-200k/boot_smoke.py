"""Fresh schema-only fixture so Liquibase, not the unit-test SQL, applies the increment."""
from pathlib import Path
import subprocess,json
subprocess.run(['python3','/tmp/migration_fixture.py'],check=True)
db=json.loads(Path('/tmp/bailian-memory-migration-result.json').read_text())['database']
assert db.startswith('bailian_memory_test_') and db.isidentifier()
mysql=['docker','exec','-i','xiaozhi-esp32-server-db','sh','-c','exec env MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --user=root --batch --raw --skip-column-names']
def fixture_sql(query):return subprocess.run(mysql,input=query,text=True,capture_output=True,check=True).stdout.strip()
# After publication the schema-only clone already contains the new columns.
# Undo them only in this empty, explicitly named fixture to rehearse Liquibase.
assert fixture_sql('SELECT COUNT(*) FROM `'+db+'`.ai_agent_chat_history;')=='0'
columns=int(fixture_sql("SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA='"+db+"' AND TABLE_NAME='ai_agent_chat_history' AND COLUMN_NAME IN('account_id','person_id','identity_status','turn_id','event_id','directory_version','default_generation','recall_allowed');"))
assert columns in (0,8)
if columns==8:
    fixture_sql('ALTER TABLE `'+db+'`.ai_agent_chat_history DROP INDEX uk_chat_account_event, DROP INDEX ix_chat_person_recent, DROP INDEX ix_chat_audio_owner,'
        ' DROP COLUMN account_id, DROP COLUMN person_id, DROP COLUMN identity_status, DROP COLUMN turn_id, DROP COLUMN event_id,'
        ' DROP COLUMN directory_version, DROP COLUMN default_generation, DROP COLUMN recall_allowed;')
s=Path('/tmp/run_boot_smoke.py').read_text()
anchor="sql('USE `'+db+'`; DROP TABLE IF EXISTS ai_person_behavior_watermark;')"
assert s.count(anchor)==1
s=s.replace(anchor,anchor+"\nsql('DELETE FROM `'+db+\"`.DATABASECHANGELOG WHERE ID IN('202609290800-behavior-watermark','202609292100-context-archive');\")")
s=s.replace("routes=['/person-memory/internal/background'", "routes=['/person-memory/internal/recent','/person-memory/internal/background'")
s=s.replace("WHERE ID='202609290800-behavior-watermark'", "WHERE ID='202609292100-context-archive'")
s=s.replace("assert migrations=='202609290800-behavior-watermark'", "assert migrations=='202609292100-context-archive'")
exec(compile(s,'isolated_boot_smoke','exec'))
