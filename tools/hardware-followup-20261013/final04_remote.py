from pathlib import Path
import subprocess,sys,tarfile
s=Path('/root/prjs/tmp/hardware-followup-20261013');sys.path.insert(0,str(s))
with tarfile.open(s/'source-delta.tgz') as a:
 assert all((s/m.name).resolve().is_relative_to(s) and 'budget.sqlite3' not in m.name for m in a.getmembers());a.extractall(s,filter='data')
from budget import Budget
b=Budget();charge=b.reserve('case','firmware-nano-log-format-rebuild-02')
(s/'firmware-build-charge-02.json').write_text(__import__('json').dumps({'id':charge}))
with (s/'final04.log').open('x') as log:r=subprocess.run([sys.executable,str(s/'run_dialogues.py'),'--name','final04','--mode','final','--corpus','cases-followup','--reuse-from','final03','--rerun-groups','combo-04'],cwd=s,stdout=log,stderr=subprocess.STDOUT)
print('final',r.returncode);print('\n'.join((s/'final04.log').read_text().splitlines()[-12:]))
