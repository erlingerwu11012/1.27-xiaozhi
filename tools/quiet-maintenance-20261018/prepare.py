from pathlib import Path
import json,os,shutil,subprocess
S=Path('/root/prjs/tmp/quiet-maintenance-20261018');BASE=Path('/root/prjs/tmp/harness-repair-20261017/manager-api')
API=S/'manager-api'
assert not API.exists()
API.mkdir()
for name in ['pom.xml','src']:
    source=BASE/name;target=API/name
    if source.is_dir():shutil.copytree(source,target)
    else:shutil.copy2(source,target)
for source in (S/'api').glob('*.java'):
    dest=API/'src'/('test' if source.name.endswith('Test.java') else 'main')/'java/xiaozhi/modules/personmemory'/source.name
    shutil.copy2(source,dest)
p=API/'src/test/java/xiaozhi/modules/personmemory/PersonMemoryContractHttpTest.java'
p.write_text(p.read_text().replace('mock(PersonBehaviorService.class),recent)','mock(PersonBehaviorService.class),recent,mock(MemoryDailyWorker.class))'))
# Existing isolated schema setup remains authoritative; change only its stage.
setup=Path('/root/prjs/tmp/harness-repair-20261017/prepare_api_regression.py').read_text()
(S/'prior-db-setup.py').write_text(setup)
print('prepared sources')
