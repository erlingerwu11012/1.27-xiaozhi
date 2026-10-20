from pathlib import Path
import json,shutil,subprocess,sys,tarfile,os
S=Path(__file__).resolve().parent
assert S==Path('/root/prjs/tmp/hardware-followup-20261013')
from budget import Budget
version=os.environ.get('FOLLOWUP_BUILD_VERSION','02')
b=Budget();charge=b.reserve('case','candidate-api-compile-'+version)
with tarfile.open(S/'source-delta.tgz') as archive:
    assert all((S/m.name).resolve().is_relative_to(S) and 'budget.sqlite3' not in m.name for m in archive.getmembers())
    archive.extractall(S,filter='data')
J=S/'manager-api'
for source in (S/'java').rglob('*.java'):
    target=J/'src/main/java/xiaozhi/modules'/source.relative_to(S/'java')
    target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
with (S/('api-compile-'+version+'.log')).open('w') as out:
    result=subprocess.run(['mvn','-q','-DskipTests','compile'],cwd=J,stdout=out,stderr=subprocess.STDOUT)
b.finish(charge,{'exit':result.returncode,'log':'api-compile-'+version+'.log'})
print('api_compile_exit',result.returncode,flush=True)
if result.returncode:
    print('\n'.join((S/('api-compile-'+version+'.log')).read_text(errors='replace').splitlines()[-30:]))
raise SystemExit(result.returncode)
