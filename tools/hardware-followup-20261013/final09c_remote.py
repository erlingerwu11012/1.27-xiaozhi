from pathlib import Path
import subprocess,sys,tarfile,json
s=Path('/root/prjs/tmp/hardware-followup-20261013');sys.path.insert(0,str(s))
with tarfile.open(s/'source-delta.tgz') as a:
 assert all((s/m.name).resolve().is_relative_to(s) and 'budget.sqlite3' not in m.name for m in a.getmembers());a.extractall(s,filter='data')
from budget import Budget
b=Budget()
with (s/'selection-03.log').open('x') as log:r=subprocess.run([sys.executable,str(s/'test_selection_followup.py')],cwd=s,stdout=log,stderr=subprocess.STDOUT)
print('selection',r.returncode,flush=True);print((s/'selection-03.log').read_text(),flush=True);assert r.returncode==0
with (s/'final09.log').open('x') as log:r=subprocess.run([sys.executable,str(s/'run_dialogues.py'),'--name','final09','--mode','final','--corpus','cases-followup','--reuse-from','final08'],cwd=s,stdout=log,stderr=subprocess.STDOUT)
print('final',r.returncode);print('\n'.join((s/'final09.log').read_text().splitlines()[-12:]));print('budget',b.report())
