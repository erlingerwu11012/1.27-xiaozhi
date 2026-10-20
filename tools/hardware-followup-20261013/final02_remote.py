from pathlib import Path
import subprocess,sys,tarfile
s=Path('/root/prjs/tmp/hardware-followup-20261013')
with tarfile.open(s/'source-delta.tgz') as a:
 assert all((s/m.name).resolve().is_relative_to(s) and 'budget.sqlite3' not in m.name for m in a.getmembers());a.extractall(s,filter='data')
with (s/'lifecycle-02.log').open('x') as log:r=subprocess.run([sys.executable,str(s/'test_lifecycle_followup.py')],cwd=s,stdout=log,stderr=subprocess.STDOUT)
print('lifecycle',r.returncode,flush=True);print((s/'lifecycle-02.log').read_text()[-2000:],flush=True);assert r.returncode==0
with (s/'final02.log').open('x') as log:r=subprocess.run([sys.executable,str(s/'run_dialogues.py'),'--name','final02','--mode','final','--corpus','cases-followup'],cwd=s,stdout=log,stderr=subprocess.STDOUT)
print('final',r.returncode);print('\n'.join((s/'final02.log').read_text().splitlines()[-12:]))
