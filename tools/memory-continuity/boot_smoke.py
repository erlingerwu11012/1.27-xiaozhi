from pathlib import Path
import subprocess,json
subprocess.run(['python3','/tmp/migration_fixture.py'],check=True,stdout=subprocess.DEVNULL)
db=json.loads(Path('/tmp/bailian-memory-migration-result.json').read_text())['database']
assert db.startswith('bailian_memory_test_') and db.isidentifier()
s=Path('/tmp/run_boot_smoke.py').read_text()
s=s.replace("sql('USE `'+db+'`; DROP TABLE IF EXISTS ai_person_behavior_watermark;')",'')
s=s.replace("routes=['/person-memory/internal/background'", "routes=['/person-memory/internal/continuation','/person-memory/internal/recent','/person-memory/internal/background'")
s=s.replace('202609290800-behavior-watermark','202609301900-memory-continuity')
exec(compile(s,'isolated_memory_continuity_boot','exec'))
