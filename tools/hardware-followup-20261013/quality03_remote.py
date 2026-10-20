from pathlib import Path
import sys,subprocess,tarfile
s=Path('/root/prjs/tmp/hardware-followup-20261013')
with tarfile.open(s/'source-delta.tgz') as a:
 assert all((s/m.name).resolve().is_relative_to(s) and 'budget.sqlite3' not in m.name for m in a.getmembers());a.extractall(s,filter='data')
with (s/'quality02.log').open('x') as log:r=subprocess.run([sys.executable,str(s/'quality_probe.py'),'--name','quality02','--repair-fixture'],cwd=s,stdout=log,stderr=subprocess.STDOUT)
print(r.returncode);print((s/'quality02.log').read_text())
