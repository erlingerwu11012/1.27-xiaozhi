from pathlib import Path
import sys,subprocess,tarfile
s=Path('/root/prjs/tmp/hardware-followup-20261013');sys.path.insert(0,str(s))
with tarfile.open(s/'source-delta.tgz') as a:
 assert all((s/m.name).resolve().is_relative_to(s) and 'budget.sqlite3' not in m.name for m in a.getmembers());a.extractall(s,filter='data')
with (s/'development04.log').open('w') as log:r=subprocess.run([sys.executable,str(s/'run_dialogues.py'),'--name','development04','--mode','development','--corpus','cases-followup'],cwd=s,stdout=log,stderr=subprocess.STDOUT)
print('exit',r.returncode);print('\n'.join((s/'development04.log').read_text().splitlines()[-15:]))
