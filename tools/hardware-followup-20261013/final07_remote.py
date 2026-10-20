from pathlib import Path
import subprocess,sys,tarfile,json
s=Path('/root/prjs/tmp/hardware-followup-20261013');sys.path.insert(0,str(s))
with tarfile.open(s/'source-delta.tgz') as a:
 assert all((s/m.name).resolve().is_relative_to(s) and 'budget.sqlite3' not in m.name for m in a.getmembers());a.extractall(s,filter='data')
from budget import Budget
b=Budget()
with (s/'confirmation-01.log').open('x') as log:r=subprocess.run([sys.executable,str(s/'test_confirmation_followup.py')],cwd=s,stdout=log,stderr=subprocess.STDOUT)
print('confirmation',r.returncode,flush=True);print((s/'confirmation-01.log').read_text(),flush=True);assert r.returncode==0
with (s/'final07.log').open('x') as log:r=subprocess.run([sys.executable,str(s/'run_dialogues.py'),'--name','final07','--mode','final','--corpus','cases-followup','--reuse-from','final06','--rerun-groups','single-00,single-04'],cwd=s,stdout=log,stderr=subprocess.STDOUT)
print('final',r.returncode);print('\n'.join((s/'final07.log').read_text().splitlines()[-12:]));print('budget',b.report())
