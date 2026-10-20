from pathlib import Path
import subprocess,sys,tarfile,json
s=Path('/root/prjs/tmp/hardware-followup-20261013');sys.path.insert(0,str(s))
with tarfile.open(s/'source-delta.tgz') as a:
 assert all((s/m.name).resolve().is_relative_to(s) and 'budget.sqlite3' not in m.name for m in a.getmembers());a.extractall(s,filter='data')
from budget import Budget
b=Budget();b.finish(json.loads((s/'firmware-build-charge-02.json').read_text())['id'],{'passed':True,'local_log':'firmware-build-02.log','sha256':'78a7f11ac1e4fdc910bed85b73dbf029a5f277666bb23679c08f19209c89371e','flashed':False})
with (s/'lifecycle-03.log').open('x') as log:r=subprocess.run([sys.executable,str(s/'test_lifecycle_followup.py')],cwd=s,stdout=log,stderr=subprocess.STDOUT)
print('lifecycle',r.returncode,flush=True);print('\n'.join((s/'lifecycle-03.log').read_text().splitlines()[-12:]),flush=True)
assert r.returncode==0
with (s/'final05.log').open('x') as log:r=subprocess.run([sys.executable,str(s/'run_dialogues.py'),'--name','final05','--mode','final','--corpus','cases-followup'],cwd=s,stdout=log,stderr=subprocess.STDOUT)
print('final',r.returncode);print('\n'.join((s/'final05.log').read_text().splitlines()[-12:]));print('budget',b.report())
