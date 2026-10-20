from pathlib import Path
import subprocess,sys,tarfile,json
s=Path('/root/prjs/tmp/hardware-followup-20261013');sys.path.insert(0,str(s))
with tarfile.open(s/'source-delta.tgz') as a:
 assert all((s/m.name).resolve().is_relative_to(s) and 'budget.sqlite3' not in m.name for m in a.getmembers());a.extractall(s,filter='data')
from budget import Budget
b=Budget()
(s/'holdout-exposure.json').write_text(json.dumps({'combo-24':'passed final07, reused','combo-25':'failed final07, now exposed for repair; retained original sample','combo-26':'unseen before final08','combo-27':'unseen before final08','combo-28':'unseen before final08','combo-29':'unseen before final08'},indent=2))
with (s/'final08.log').open('x') as log:r=subprocess.run([sys.executable,str(s/'run_dialogues.py'),'--name','final08','--mode','final','--corpus','cases-followup','--reuse-from','final07'],cwd=s,stdout=log,stderr=subprocess.STDOUT)
print('final',r.returncode);print('\n'.join((s/'final08.log').read_text().splitlines()[-12:]));print('budget',b.report())
